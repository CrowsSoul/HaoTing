# -*- coding: utf-8 -*-
"""PERF-01 载流–温升。从模型里取导体圆柱，用回归树预测温升区间。"""

from __future__ import annotations

import math
import os

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding, ModelBundle, Part
from .physics import RULE_PARAMS, canonical_material, feature_vector
from .tree_model import apply_interval, load, predict_temperature

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "data", "model.json")

_MODEL = None


def model_path() -> str:
    return MODEL_PATH


def load_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = load(MODEL_PATH)
    return _MODEL


def predict_raw(area_mm2: float, length_mm: float, rho_ohm_m: float, current_a: float, h_w_m2k: float) -> dict:
    """给一组工况，返回点预测和区间。调用前模型文件必须已经训练好。"""
    model = load_model()
    x = feature_vector(area_mm2, length_mm, rho_ohm_m, current_a, h_w_m2k)
    point = max(0.0, predict_temperature(model, x))
    low, high = apply_interval(point, model["q_low"], model["q_high"])
    return {"delta_t_c": point, "delta_t_low_c": low, "delta_t_high_c": high}


def _span(params: dict, lo_key: str, hi_key: str, value: float, label: str) -> str:
    lo = float(params[lo_key])
    hi = float(params[hi_key])
    if value < lo or value > hi:
        return f"{label} {value:.4g} 超出适用范围 {lo:.4g}–{hi:.4g}"
    return ""


def condition_problem(params: dict) -> str:
    """工况或模型文件不满足时返回原因，满足则返回空串。"""
    if not os.path.isfile(MODEL_PATH):
        return "预测模型文件不存在，先运行 python -m nxdrp.checkers.m5_performance.train"
    try:
        model = load_model()
    except Exception as exc:
        return f"预测模型无法读取：{exc}"
    trained = float(model.get("interval_confidence", 0.8))
    asked = float(params.get("interval_confidence", trained))
    if abs(asked - trained) > 0.02:
        return f"规则要求区间置信度 {asked:.2f}，当前模型只标定了 {trained:.2f}"
    for key, label in (
        ("current_a", "电流"),
        ("ambient_temp_c", "环境温度"),
        ("convection_h_w_m2k", "对流换热系数"),
    ):
        if key not in params:
            return f"规则缺少 {key}"
    return (
        _span(params, "current_a_min", "current_a_max", float(params["current_a"]), "电流 A")
        or _span(params, "ambient_temp_c_min", "ambient_temp_c_max", float(params["ambient_temp_c"]), "环境温度 °C")
        or _span(params, "h_w_m2k_min", "h_w_m2k_max", float(params["convection_h_w_m2k"]), "对流换热系数")
    )


def cylinder_spec(face) -> dict | None:
    if face.solid_face_type != "cylindrical":
        return None
    if face.radius_diameter is None or float(face.radius_diameter) <= 0:
        return None
    if face.area is None or float(face.area) <= 0:
        return None
    radius = float(face.radius_diameter)
    if not face.is_radius:
        radius = radius / 2.0
    length = float(face.area) / (2.0 * math.pi * radius)
    return {
        "face_id": face.face_id,
        "radius_mm": radius,
        "length_mm": length,
        "area_mm2": math.pi * radius * radius,
        "cog": face.cog or face.point,
    }


def bottleneck(model: ModelBundle, part: Part, params: dict) -> tuple[dict | None, str]:
    specs = []
    for face in model.faces_of(part.part_id, "cylindrical"):
        spec = cylinder_spec(face)
        if spec is not None:
            specs.append(spec)
    if not specs:
        return None, "没有带半径和面积的圆柱面，无法估计载流截面积"
    spec = min(specs, key=lambda s: s["area_mm2"])
    area_problem = _span(params, "area_mm2_min", "area_mm2_max", spec["area_mm2"], "截面积 mm²")
    length_problem = _span(params, "length_mm_min", "length_mm_max", spec["length_mm"], "导体长度 mm")
    if area_problem or length_problem:
        return None, area_problem or length_problem
    return spec, ""


def conductor_parts(model: ModelBundle, params: dict) -> list[Part]:
    materials = params.get("materials") or {}
    found = []
    for part in model.parts:
        if canonical_material(part.material, materials):
            found.append(part)
    return found


def _search_current(raw: dict, max_rise: float, current_min: float) -> float:
    lo = float(current_min)
    hi = float(raw["current_a"])
    if predict_raw(raw["area_mm2"], raw["length_mm"], raw["rho_ohm_m"], lo, raw["h_w_m2k"])["delta_t_c"] >= max_rise:
        return lo
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        rise = predict_raw(raw["area_mm2"], raw["length_mm"], raw["rho_ohm_m"], mid, raw["h_w_m2k"])["delta_t_c"]
        if rise >= max_rise:
            hi = mid
        else:
            lo = mid
    return lo


def _search_area(raw: dict, max_rise: float, area_max: float) -> float | None:
    lo = float(raw["area_mm2"])
    hi = float(area_max)
    if hi <= lo:
        return None
    if predict_raw(hi, raw["length_mm"], raw["rho_ohm_m"], raw["current_a"], raw["h_w_m2k"])["delta_t_c"] >= max_rise:
        return None
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        rise = predict_raw(mid, raw["length_mm"], raw["rho_ohm_m"], raw["current_a"], raw["h_w_m2k"])["delta_t_c"]
        if rise >= max_rise:
            lo = mid
        else:
            hi = mid
    return hi


class CurrentTempChecker(BaseChecker):
    check_item_id = "PERF-01"
    name = "载流-温升预测"
    version = "0.1.0"
    owner = "M5 杜滨芳"
    process_types = ("performance",)
    default_params = dict(RULE_PARAMS)

    def applies(self, model: ModelBundle, params: dict) -> tuple[bool, str]:
        problem = condition_problem(params)
        if problem:
            return False, problem
        parts = conductor_parts(model, params)
        if not parts:
            return False, "模型中没有已知导体材料（Cu、CuSn6、CuZn37、CuBe2），缺少材料就不能预测温升"
        reasons = []
        for part in parts:
            spec, why = bottleneck(model, part, params)
            if spec is None:
                reasons.append(f"{part.part_id} {why}")
            else:
                return True, ""
        return False, "导体零件无法估计载流截面：" + "；".join(reasons)

    def check(self, ctx: CheckContext) -> list[Finding]:
        params = ctx.params
        materials = params.get("materials") or {}
        current = float(params["current_a"])
        ambient = float(params["ambient_temp_c"])
        h = float(params["convection_h_w_m2k"])
        max_rise = float(params["max_rise_c"])
        confidence = float(params["interval_confidence"])
        findings = []
        for part in conductor_parts(ctx.model, params):
            material = canonical_material(part.material, materials)
            spec, _why = bottleneck(ctx.model, part, params)
            if material is None or spec is None:
                continue
            rho = float(materials[material]["rho_ohm_m"])
            raw = {
                "area_mm2": spec["area_mm2"],
                "length_mm": spec["length_mm"],
                "rho_ohm_m": rho,
                "current_a": current,
                "h_w_m2k": h,
            }
            pred = predict_raw(**raw)
            rise = pred["delta_t_c"]
            if rise < max_rise:
                continue
            target_area = _search_area(raw, max_rise, float(params["area_mm2_max"]))
            allow_current = _search_current(raw, max_rise, float(params["current_a_min"]))
            actions = []
            delta = {"current_a": round(allow_current, 3)}
            if target_area is not None:
                actions.append(f"把载流截面积加大到 {target_area:.2f} mm²")
                delta["area_mm2"] = round(target_area, 3)
            else:
                actions.append(
                    f"截面积加到上限 {float(params['area_mm2_max']):.1f} mm² 仍然超限"
                )
            actions.append(f"或把电流降到 {allow_current:.2f} A")
            low = pred["delta_t_low_c"]
            high = pred["delta_t_high_c"]
            findings.append(
                ctx.finding(
                    message=(
                        f"零件 {part.part_id}（{material}）在 {current:.1f} A、环境 {ambient:.0f} °C 下，"
                        f"预测稳态温升 {rise:.1f} °C（{low:.1f}–{high:.1f} °C，置信度 {confidence:.0%}），"
                        f"不低于允许温升 {max_rise:.1f} °C。"
                        + "，".join(actions)
                        + "。"
                    ),
                    part_refs=[part.part_id],
                    location=spec["cog"],
                    bbox=part.bbox,
                    measured_value=rise,
                    threshold_value=max_rise,
                    unit="°C",
                    confidence=confidence,
                    suggestion_text="，".join(actions) + "。",
                    suggestion_delta=delta,
                    face_ids=[spec["face_id"]],
                    note="截面积取该零件半径最小的圆柱面，按 πr² 作为载流瓶颈",
                    extra={
                        "delta_t_c": rise,
                        "delta_t_low_c": low,
                        "delta_t_high_c": high,
                        "interval_confidence": confidence,
                        "allowable_current_a": allow_current,
                        "current_a": current,
                        "ambient_temp_c": ambient,
                        "area_mm2": spec["area_mm2"],
                        "length_mm": spec["length_mm"],
                        "material": material,
                        "absolute_temp_c": ambient + rise,
                    },
                )
            )
        return findings


CHECKERS = [CurrentTempChecker()]
