# -*- coding: utf-8 -*-
"""模拟 NX 仿真里的热求解。

给定圆柱端子的截面积、长度、材料、电流、
环境温度和换热系数，迭代求出温升。比 physics.delta_t_c 多三件事：

- 电阻率随温度升高
- 表面辐射
- 两端一个很小的接触电阻

样本里的 delta_t_c 用 simulate_nx_delta_t。delta_t_clean_c 仍是集总公式，
回归树学的就是模拟 NX 仿真和这道公式的差。
"""

from __future__ import annotations

import math

SIGMA = 5.670374419e-8
EMISSIVITY = 0.25
# 电阻温度系数，1/°C。用来让模拟 NX 的温升和纯对流公式拉开。
ALPHA = {
    "Cu": 0.00393,
    "CuSn6": 0.0006,
    "CuZn37": 0.0015,
    "CuBe2": 0.0010,
}


def simulate_nx_delta_t(
    area_mm2: float,
    length_mm: float,
    rho_ohm_m: float,
    current_a: float,
    ambient_temp_c: float,
    h_w_m2k: float,
    material: str = "Cu",
) -> float:
    """返回稳态温升 °C。输入必须为正。"""
    area_m2 = float(area_mm2) * 1e-6
    length_m = float(length_mm) * 1e-3
    diameter_m = 2.0 * math.sqrt(area_m2 / math.pi)
    surface_m2 = math.pi * diameter_m * length_m + 2.0 * area_m2
    alpha = ALPHA.get(material, 0.002)
    # 端部接触：截面积越小，附加电阻越大。单位 Ω。
    contact_ohm = 1.5e-4 / max(float(area_mm2), 0.2)
    ambient = float(ambient_temp_c)
    temperature = ambient + 5.0

    def loss(temp: float, power: float) -> float:
        conv = float(h_w_m2k) * surface_m2 * (temp - ambient)
        rad = (
            EMISSIVITY
            * SIGMA
            * surface_m2
            * ((temp + 273.15) ** 4 - (ambient + 273.15) ** 4)
        )
        return conv + rad - power

    for _ in range(12):
        rho_hot = float(rho_ohm_m) * (1.0 + alpha * (temperature - 20.0))
        rho_hot = max(rho_hot, float(rho_ohm_m) * 0.5)
        power = float(current_a) ** 2 * (rho_hot * length_m / area_m2 + contact_ohm)
        lo = ambient
        hi = ambient + 4000.0
        for _step in range(48):
            mid = 0.5 * (lo + hi)
            if loss(mid, power) < 0.0:
                lo = mid
            else:
                hi = mid
        temperature = 0.5 * (lo + hi)
    return max(0.0, temperature - ambient)
