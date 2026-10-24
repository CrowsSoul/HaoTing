# -*- coding: utf-8 -*-
"""PERF-02 插拔力。从零件包围盒估计簧片尺寸，用回归树预测插入力和拔出力。

几何口径（写进模型卡，别当成实测）：把导体零件包围盒的三个边长排序，
最小边当簧片厚度 t，中间边当宽度 b，最长边当长度 L。过盈量、摩擦系数、
引导角、接触点数取规则里的默认值——真实簧片的中性轴和过盈量需要实测或 NX 量测，
现在这条链路只保证流程跑通。
"""

from __future__ import annotations

import math
import os

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding, ModelBundle, Part
from .force_model import MODEL_PATH as FORCE_MODEL_PATH
from .force_model import load as load_force_model
from .force_model import predict_force, predict_withdrawal
from .force_physics import RULE_PARAMS, canonical_material, feature_vector
from .tree_model import apply_interval

_MODEL = None


def model_path() -> str:
    return FORCE_MODEL_PATH


def load_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = load_force_model(FORCE_MODEL_PATH)
    return _MODEL


def _span(params: dict, lo_key: str, hi_key: str, value: float, label: str) -> str:
    lo = float(params[lo_key])
    hi = float(params[hi_key])
    if value < lo or value > hi:
        return f"{label} {value:.4g} 超出适用范围 {lo:.4g}–{hi:.4g}"
    return ""


def condition_problem(params: dict) -> str:
    """工况或模型文件不满足时返回原因，满足则返回空串。"""
    if not os.path.isfile(FORCE_MODEL_PATH):
        return "插拔力模型文件不存在，先运行 python -m nxdrp.checkers.m5_performance.force_train"
    try:
        model = load_model()
    except Exception as exc:
        return f"插拔力模型无法读取：{exc}"
    trained = float(model.get("interval_confidence", 0.8))
    asked = float(params.get("interval_confidence", trained))
    if abs(asked - trained) > 0.02:
        return f"规则要求区间置信度 {asked:.2f}，当前模型只标定了 {trained:.2f}"
    for key in ("contacts", "lead_angle_deg", "friction_coeff", "overlap_mm"):
        if key not in params:
            return f"规则缺少 {key}"
    return _span(params, "friction_min", "friction_max", float(params["friction_coeff"]), "摩擦系数") or _span(
        params, "overlap_mm_min", "overlap_mm_max", float(params["overlap_mm"]), "过盈量 mm"
    )


def spring_spec(part: Part, params: dict) -> tuple[dict | None, str]:
    """从包围盒猜簧片尺寸。猜不出来就返回原因，调用方跳过。"""
    bbox = part.bbox
    if bbox is None:
        return None, "零件没有包围盒，无法估计簧片尺寸"
    dims = sorted([bbox.xmax - bbox.xmin, bbox.ymax - bbox.ymin, bbox.zmax - bbox.zmin])
    if dims[0] <= 0 or dims[2] <= 0:
        return None, "零件包围盒退化，无法估计簧片尺寸"
    thickness, width, length = dims[0], dims[1], dims[2]
    problem = (
        _span(params, "thickness_mm_min", "thickness_mm_max", thickness, "簧片厚度 mm")
        or _span(params, "width_mm_min", "width_mm_max", width, "簧片宽度 mm")
        or _span(params, "length_mm_min", "length_mm_max", length, "簧片长度 mm")
    )
    if problem:
        return None, problem
    return {
        "part_id": part.part_id,
        "thickness_mm": thickness,
        "width_mm": width,
        "length_mm": length,
        "overlap_mm": float(params["overlap_mm"]),
        "contacts": float(params["contacts"]),
        "lead_angle_deg": float(params["lead_angle_deg"]),
        "friction_coeff": float(params["friction_coeff"]),
        "bbox": bbox,
    }, ""


def conductor_parts(model: ModelBundle, params: dict) -> list[Part]:
    materials = params.get("materials") or {}
    return [p for p in model.parts if canonical_material(p.material, materials)]


def _anchor_face(model: ModelBundle, part: Part) -> str | None:
    """给 Finding 一个可点回 3D 的定位面。尺寸仍来自包围盒。"""
    planes = model.faces_of(part.part_id, "planar")
    if not planes:
        return None
    best = max(planes, key=lambda f: f.area or 0.0)
    return best.face_id


def predict_insertion(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    material: str,
    params: dict | None = None,
) -> dict:
    """给簧片尺寸和材料，返回插拔力区间。不经过 3D 模型。"""
    merged = dict(RULE_PARAMS)
    if params:
        merged.update(params)
    problem = condition_problem(merged)
    if problem:
        return {"ok": False, "reason": problem}
    canon = canonical_material(material, merged.get("materials") or {})
    if canon is None:
        return {"ok": False, "reason": f"材料 {material} 不是已知簧片材料（CuSn6、CuBe2、CuZn37）"}
    problem = (
        _span(merged, "length_mm_min", "length_mm_max", float(length_mm), "簧片长度 mm")
        or _span(merged, "width_mm_min", "width_mm_max", float(width_mm), "簧片宽度 mm")
        or _span(merged, "thickness_mm_min", "thickness_mm_max", float(thickness_mm), "簧片厚度 mm")
    )
    if problem:
        return {"ok": False, "reason": problem}

    e_gpa = float(merged["materials"][canon]["e_gpa"])
    overlap = float(merged["overlap_mm"])
    friction = float(merged["friction_coeff"])
    x = feature_vector(length_mm, width_mm, thickness_mm, overlap, e_gpa, friction)
    model = load_model()
    insertion = predict_force(model, x)
    low, high = apply_interval(insertion, model["q_low"], model["q_high"])
    withdrawal = predict_withdrawal(model, x)
    max_n = float(merged["insertion_force_max_n"])
    min_n = float(merged["withdrawal_force_min_n"])
    return {
        "ok": True,
        "reason": "",
        "material": canon,
        "insertion_force_n": insertion,
        "insertion_force_low_n": low,
        "insertion_force_high_n": high,
        "withdrawal_force_n": withdrawal,
        "interval_confidence": float(merged["interval_confidence"]),
        "insertion_force_max_n": max_n,
        "withdrawal_force_min_n": min_n,
        "alarm": insertion >= max_n or withdrawal < min_n,
        "length_mm": float(length_mm),
        "width_mm": float(width_mm),
        "thickness_mm": float(thickness_mm),
        "overlap_mm": overlap,
        "contacts": float(merged["contacts"]),
    }


def _with(features: list[float], index: int, value: float) -> list[float]:
    out = list(features)
    out[index] = value
    return out


def _limit_overlap(model: dict, features: list[float], max_n: float, lo: float, hi: float) -> float | None:
    """把过盈量从当前值往小调，找仍然不超限的最大过盈量。"""
    if predict_force(model, _with(features, 3, math.log(hi))) < max_n:
        return hi
    if predict_force(model, _with(features, 3, math.log(lo))) >= max_n:
        return None
    a, b = lo, hi
    for _ in range(24):
        mid = 0.5 * (a + b)
        if predict_force(model, _with(features, 3, math.log(mid))) >= max_n:
            b = mid
        else:
            a = mid
    return a


def _needed_length(model: dict, features: list[float], max_n: float, start: float, hi: float) -> float | None:
    """簧片加长会变软。找能把插入力压到上限以下的最短长度。"""
    if predict_force(model, _with(features, 0, math.log(hi))) >= max_n:
        return None
    a, b = start, hi
    for _ in range(24):
        mid = 0.5 * (a + b)
        if predict_force(model, _with(features, 0, math.log(mid))) >= max_n:
            a = mid
        else:
            b = mid
    return b


class InsertionForceChecker(BaseChecker):
    check_item_id = "PERF-02"
    name = "插拔力预测"
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
            return False, "模型中没有已知簧片材料（CuSn6、CuBe2、CuZn37），缺少材料就不能预测插拔力"
        reasons = []
        for part in parts:
            spec, why = spring_spec(part, params)
            if spec is not None:
                return True, ""
            reasons.append(f"{part.part_id} {why}")
        return False, "导体零件无法当作簧片：" + "；".join(reasons)

    def check(self, ctx: CheckContext) -> list[Finding]:
        params = ctx.params
        materials = params.get("materials") or {}
        max_n = float(params["insertion_force_max_n"])
        min_n = float(params["withdrawal_force_min_n"])
        confidence = float(params["interval_confidence"])
        model = load_model()
        findings = []
        for part in conductor_parts(ctx.model, params):
            material = canonical_material(part.material, materials)
            spec, _why = spring_spec(part, params)
            if material is None or spec is None:
                continue
            e_gpa = float(materials[material]["e_gpa"])
            features = feature_vector(
                spec["length_mm"], spec["width_mm"], spec["thickness_mm"],
                spec["overlap_mm"], e_gpa, spec["friction_coeff"],
            )
            insertion = predict_force(model, features)
            low, high = apply_interval(insertion, model["q_low"], model["q_high"])
            withdrawal = predict_withdrawal(model, features)
            anchor = _anchor_face(ctx.model, part)
            common = {
                "part_id": part.part_id,
                "material": material,
                "length_mm": round(spec["length_mm"], 4),
                "width_mm": round(spec["width_mm"], 4),
                "thickness_mm": round(spec["thickness_mm"], 4),
                "overlap_mm": spec["overlap_mm"],
                "friction_coeff": spec["friction_coeff"],
                "contacts": spec["contacts"],
                "insertion_force_n": round(insertion, 4),
                "insertion_force_low_n": round(low, 4),
                "insertion_force_high_n": round(high, 4),
                "withdrawal_force_n": round(withdrawal, 4),
                "interval_confidence": confidence,
                "geometry_source": "part_bbox",
            }
            if insertion >= max_n:
                actions = []
                delta = {}
                overlap_fix = _limit_overlap(
                    model, features, max_n,
                    float(params["overlap_mm_min"]), spec["overlap_mm"],
                )
                if overlap_fix is not None:
                    actions.append(f"把过盈量从 {spec['overlap_mm']:.2f} mm 减到 {overlap_fix:.3f} mm")
                    delta["overlap_mm"] = round(overlap_fix, 4)
                length_fix = _needed_length(
                    model, features, max_n, spec["length_mm"], float(params["length_mm_max"])
                )
                if length_fix is not None:
                    actions.append(f"把簧片长度加到 {length_fix:.2f} mm（加长会变软）")
                    delta["length_mm"] = round(length_fix, 4)
                if not actions:
                    actions.append("当前尺寸范围内减不下来，需要换簧片截面或减少接触点数")
                findings.append(
                    ctx.finding(
                        severity="P2",
                        message=(
                            f"零件 {part.part_id}（{material}）按包围盒估计簧片 "
                            f"{spec['length_mm']:.1f}×{spec['width_mm']:.1f}×{spec['thickness_mm']:.2f} mm、"
                            f"过盈量 {spec['overlap_mm']:.2f} mm、{spec['contacts']:.0f} 个接触点，"
                            f"预测插入力 {insertion:.2f} N（{low:.2f}–{high:.2f} N，置信度 {confidence:.0%}），"
                            f"不低于上限 {max_n:.1f} N。" + "，".join(actions) + "。"
                        ),
                        part_refs=[part.part_id],
                        location=None,
                        bbox=part.bbox,
                        measured_value=insertion,
                        threshold_value=max_n,
                        unit="N",
                        confidence=confidence,
                        suggestion_text="，".join(actions) + "。",
                        suggestion_delta=delta,
                        face_ids=[anchor] if anchor else [],
                        note="簧片尺寸取自零件包围盒；face_id 用于定位零件",
                        extra=common,
                    )
                )
            elif withdrawal < min_n:
                findings.append(
                    ctx.finding(
                        severity="P3",
                        message=(
                            f"零件 {part.part_id}（{material}）预测拔出力 {withdrawal:.2f} N，"
                            f"低于下限 {min_n:.1f} N，接触压力可能不足。"
                            f"可在规则范围内加大过盈量（当前 {spec['overlap_mm']:.2f} mm）或更换弹性模量更高的材料。"
                        ),
                        part_refs=[part.part_id],
                        bbox=part.bbox,
                        measured_value=withdrawal,
                        threshold_value=min_n,
                        unit="N",
                        confidence=confidence,
                        suggestion_text="加大过盈量或换更高弹性模量的簧片材料。",
                        suggestion_delta={"overlap_mm_min": float(params["overlap_mm_min"])},
                        face_ids=[anchor] if anchor else [],
                        note="簧片尺寸取自零件包围盒；face_id 用于定位零件",
                        extra=common,
                    )
                )
        return findings


CHECKERS = [InsertionForceChecker()]
