# -*- coding: utf-8 -*-
"""插拔力的悬臂梁 + 摩擦模型，以及训练和规则共用的默认参数。

假设（写进模型卡，别当成实测）：每个接触点是一根等截面悬臂簧片，
过盈量由簧片弯曲吸收，小变形、线弹性、摩擦系数为常数。

    I    = b · t³ / 12
    k    = 3 E I / L³
    Fn   = k · δ
    Fin  = n · Fn · (μ + tanθ) / (1 - μ·tanθ)
    Fout = n · Fn · μ

θ 是引导角，μ 是摩擦系数，n 是接触点数，δ 是过盈量。
函数入口用毫米、吉帕和度，公式内部换成 SI。

仓库里没有插拔力的实测数据，也没有接触簧片的专用仿真。
标签来自这个公式再乘散差；平台方给出实测或仿真后，替换 delta_force_n 再训练。
"""

from __future__ import annotations

import math

#: 与 rules/dfm_default.json 里 R-PERF-02 的 params 保持同一份初值。
RULE_PARAMS = {
    "contacts": 4.0,
    "lead_angle_deg": 30.0,
    "friction_coeff": 0.20,
    "overlap_mm": 0.20,
    "length_mm_min": 6.0,
    "length_mm_max": 15.0,
    "width_mm_min": 1.0,
    "width_mm_max": 4.0,
    "thickness_mm_min": 0.2,
    "thickness_mm_max": 0.6,
    "overlap_mm_min": 0.10,
    "overlap_mm_max": 0.50,
    "friction_min": 0.12,
    "friction_max": 0.30,
    "interval_confidence": 0.8,
    "insertion_force_max_n": 20.0,
    "withdrawal_force_min_n": 1.0,
    "materials": {
        "CuSn6": {"e_gpa": 110.0},
        "CuBe2": {"e_gpa": 131.0},
        "CuZn37": {"e_gpa": 100.0},
    },
}

FEATURE_NAMES = (
    "log_length_mm",
    "log_width_mm",
    "log_thickness_mm",
    "log_overlap_mm",
    "log_e_gpa",
    "log_mu",
)

_ALIASES = {
    "cusn6": "CuSn6",
    "锡青铜": "CuSn6",
    "c5210": "CuSn6",
    "cube2": "CuBe2",
    "铍铜": "CuBe2",
    "c17200": "CuBe2",
    "cuzn37": "CuZn37",
    "黄铜": "CuZn37",
    "h62": "CuZn37",
    "h65": "CuZn37",
    "c2680": "CuZn37",
}


def canonical_material(name: str, materials: dict | None = None) -> str | None:
    """把零件上的材料名对齐到规则表。对不上就返回 None，调用方必须跳过。"""
    table = materials if materials is not None else RULE_PARAMS["materials"]
    text = (name or "").strip()
    if not text:
        return None
    if text in table:
        return text
    key = _ALIASES.get(text.casefold()) or _ALIASES.get(text)
    if key and key in table:
        return key
    return None


def normal_force_n(length_mm: float, width_mm: float, thickness_mm: float, overlap_mm: float, e_gpa: float) -> float:
    """单根簧片的正压力，单位 N。"""
    length = float(length_mm) * 1e-3
    width = float(width_mm) * 1e-3
    thick = float(thickness_mm) * 1e-3
    overlap = float(overlap_mm) * 1e-3
    inertia = width * thick ** 3 / 12.0
    stiffness = 3.0 * float(e_gpa) * 1e9 * inertia / length ** 3
    return stiffness * overlap


def _lead_factor(lead_angle_deg: float, friction: float) -> float | None:
    tan_theta = math.tan(math.radians(float(lead_angle_deg)))
    denom = 1.0 - float(friction) * tan_theta
    if denom <= 1e-6:
        return None
    return (float(friction) + tan_theta) / denom


def insertion_force_n(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    overlap_mm: float,
    e_gpa: float,
    contacts: float,
    lead_angle_deg: float,
    friction: float,
) -> float:
    """总插入力，单位 N。"""
    factor = _lead_factor(lead_angle_deg, friction)
    if factor is None:
        raise ValueError("引导角与摩擦系数组合会让分母为零：1 - μ·tanθ ≤ 0")
    return float(contacts) * normal_force_n(length_mm, width_mm, thickness_mm, overlap_mm, e_gpa) * factor


def withdrawal_force_n(
    length_mm: float,
    width_mm: float,
    thickness_mm: float,
    overlap_mm: float,
    e_gpa: float,
    contacts: float,
    friction: float,
) -> float:
    """总拔出力，单位 N。平直段只靠摩擦，没有引导角助力。"""
    return float(contacts) * normal_force_n(length_mm, width_mm, thickness_mm, overlap_mm, e_gpa) * float(friction)


def feature_vector(length_mm: float, width_mm: float, thickness_mm: float, overlap_mm: float, e_gpa: float, friction: float) -> list[float]:
    return [
        math.log(float(length_mm)),
        math.log(float(width_mm)),
        math.log(float(thickness_mm)),
        math.log(float(overlap_mm)),
        math.log(float(e_gpa)),
        math.log(float(friction)),
    ]
