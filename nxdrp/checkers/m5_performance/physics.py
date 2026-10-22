# -*- coding: utf-8 -*-
"""载流–温升的集总热模型，以及训练和规则共用的默认参数。

稳态温升（圆柱端子，侧面加两端对流）：

    P = I^2 * rho * L / A
    d = 2 * sqrt(A / pi)
    A_surf = pi * d * L + 2 * A
    delta_T = P / (h * A_surf)

函数入口用毫米和安培，公式内部换算成米。

仓库里没有热仿真 journal。造样本时用这个公式当标签，再乘对数正态散差。
平台方给出仿真温升后，替换样本里的 delta_t_c，重新训练即可。
"""

from __future__ import annotations

import math

#: 与 rules/dfm_default.json 里 R-PERF-01 的 params 保持同一份初值。
RULE_PARAMS = {
    "current_a": 16.0,
    "ambient_temp_c": 25.0,
    "interval_confidence": 0.8,
    "max_rise_c": 45.0,
    "convection_h_w_m2k": 15.0,
    "area_mm2_min": 0.5,
    "area_mm2_max": 20.0,
    "length_mm_min": 5.0,
    "length_mm_max": 40.0,
    "current_a_min": 1.0,
    "current_a_max": 40.0,
    "ambient_temp_c_min": 0.0,
    "ambient_temp_c_max": 80.0,
    "h_w_m2k_min": 8.0,
    "h_w_m2k_max": 25.0,
    "materials": {
        "Cu": {"rho_ohm_m": 1.724e-8},
        "CuSn6": {"rho_ohm_m": 1.3e-7},
        "CuZn37": {"rho_ohm_m": 6.2e-8},
        "CuBe2": {"rho_ohm_m": 7.8e-8},
    },
}

FEATURE_NAMES = (
    "log_area_mm2",
    "log_length_mm",
    "log_rho_ohm_m",
    "log_current_a",
    "log_h_w_m2k",
)

#: 零件材料字段里常见的写法。阈值不在这里，这里只做名字对齐。
_ALIASES = {
    "cu": "Cu",
    "copper": "Cu",
    "纯铜": "Cu",
    "c11000": "Cu",
    "cusn6": "CuSn6",
    "锡青铜": "CuSn6",
    "cuzn37": "CuZn37",
    "黄铜": "CuZn37",
    "brass": "CuZn37",
    "cube2": "CuBe2",
    "铍铜": "CuBe2",
    "c17200": "CuBe2",
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


def delta_t_c(area_mm2: float, length_mm: float, rho_ohm_m: float, current_a: float, h_w_m2k: float) -> float:
    """集总模型的稳态温升，单位 °C。输入必须为正。"""
    area_m2 = float(area_mm2) * 1e-6
    length_m = float(length_mm) * 1e-3
    diameter_m = 2.0 * math.sqrt(area_m2 / math.pi)
    power_w = (float(current_a) ** 2) * float(rho_ohm_m) * length_m / area_m2
    surface_m2 = math.pi * diameter_m * length_m + 2.0 * area_m2
    return power_w / (float(h_w_m2k) * surface_m2)


def feature_vector(area_mm2: float, length_mm: float, rho_ohm_m: float, current_a: float, h_w_m2k: float) -> list[float]:
    return [
        math.log(float(area_mm2)),
        math.log(float(length_mm)),
        math.log(float(rho_ohm_m)),
        math.log(float(current_a)),
        math.log(float(h_w_m2k)),
    ]
