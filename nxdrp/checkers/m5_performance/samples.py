# -*- coding: utf-8 -*-
"""按参数范围造载流–温升样本。

    python -m nxdrp.checkers.m5_performance.samples

尺寸在规则范围内抽取。温升由模拟 NX 仿真（thermal_solver.simulate_nx_delta_t）算出。
"""

from __future__ import annotations

import json
import math
import os
import random

from .physics import RULE_PARAMS, delta_t_c
from .thermal_solver import simulate_nx_delta_t

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES_PATH = os.path.join(HERE, "data", "samples.json")
N_SAMPLES = 360
SEED = 20261029


def _log_uniform(rng: random.Random, lo: float, hi: float) -> float:
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))


def generate(n: int = N_SAMPLES, seed: int = SEED) -> dict:
    rng = random.Random(seed)
    materials = RULE_PARAMS["materials"]
    names = list(materials)
    rows = []
    for i in range(n):
        material = names[i % len(names)]
        rho = float(materials[material]["rho_ohm_m"])
        area = _log_uniform(rng, RULE_PARAMS["area_mm2_min"], RULE_PARAMS["area_mm2_max"])
        length = rng.uniform(RULE_PARAMS["length_mm_min"], RULE_PARAMS["length_mm_max"])
        current = _log_uniform(rng, RULE_PARAMS["current_a_min"], RULE_PARAMS["current_a_max"])
        ambient = rng.uniform(RULE_PARAMS["ambient_temp_c_min"], RULE_PARAMS["ambient_temp_c_max"])
        h = rng.uniform(RULE_PARAMS["h_w_m2k_min"], RULE_PARAMS["h_w_m2k_max"])
        clean = delta_t_c(area, length, rho, current, h)
        solved = simulate_nx_delta_t(area, length, rho, current, ambient, h, material)
        rows.append(
            {
                "sample_id": f"S{i + 1:04d}",
                "material": material,
                "area_mm2": area,
                "length_mm": length,
                "current_a": current,
                "ambient_temp_c": ambient,
                "rho_ohm_m": rho,
                "h_w_m2k": h,
                "delta_t_clean_c": clean,
                "delta_t_c": solved,
            }
        )
    return {
        "schema": "perf01-samples-v1",
        "count": len(rows),
        "seed": seed,
        "label_source": "simulated_nx_v1",
        "note": (
            "温升由模拟 NX 仿真 thermal_solver.simulate_nx_delta_t 生成，"
            "含对流、辐射、电阻率随温度和端部接触。"
            "集总对流公式写在 delta_t_clean_c，供回归树学习两者之差。"
        ),
        "samples": rows,
    }


def save(payload: dict, path: str = SAMPLES_PATH) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def load(path: str = SAMPLES_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main() -> None:
    path = save(generate())
    print(f"已写入 {path} ，共 {N_SAMPLES} 条")


if __name__ == "__main__":
    main()
