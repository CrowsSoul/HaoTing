# -*- coding: utf-8 -*-
"""按参数范围造插拔力样本。

    python -m nxdrp.checkers.m5_performance.force_samples

标签 = 悬臂梁摩擦公式 × 对数正态散差。
"""

from __future__ import annotations

import json
import math
import os
import random

from .force_physics import RULE_PARAMS, insertion_force_n, withdrawal_force_n

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES_PATH = os.path.join(HERE, "data", "perf02_samples.json")
N_SAMPLES = 360
SEED = 20261029


def _log_uniform(rng: random.Random, lo: float, hi: float) -> float:
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))


def generate(n: int = N_SAMPLES, seed: int = SEED) -> dict:
    rng = random.Random(seed)
    materials = RULE_PARAMS["materials"]
    names = list(materials)
    contacts = float(RULE_PARAMS["contacts"])
    lead = float(RULE_PARAMS["lead_angle_deg"])
    rows = []
    for i in range(n):
        material = names[i % len(names)]
        e_gpa = float(materials[material]["e_gpa"])
        length = rng.uniform(RULE_PARAMS["length_mm_min"], RULE_PARAMS["length_mm_max"])
        width = rng.uniform(RULE_PARAMS["width_mm_min"], RULE_PARAMS["width_mm_max"])
        thickness = rng.uniform(RULE_PARAMS["thickness_mm_min"], RULE_PARAMS["thickness_mm_max"])
        overlap = rng.uniform(RULE_PARAMS["overlap_mm_min"], RULE_PARAMS["overlap_mm_max"])
        friction = rng.uniform(RULE_PARAMS["friction_min"], RULE_PARAMS["friction_max"])
        clean_in = insertion_force_n(length, width, thickness, overlap, e_gpa, contacts, lead, friction)
        clean_out = withdrawal_force_n(length, width, thickness, overlap, e_gpa, contacts, friction)
        factor = math.exp(rng.gauss(0.0, 0.08))
        factor = min(1.30, max(0.75, factor))
        rows.append(
            {
                "sample_id": f"F{i + 1:04d}",
                "material": material,
                "length_mm": length,
                "width_mm": width,
                "thickness_mm": thickness,
                "overlap_mm": overlap,
                "friction_coeff": friction,
                "e_gpa": e_gpa,
                "contacts": contacts,
                "lead_angle_deg": lead,
                "insertion_clean_n": clean_in,
                "insertion_n": clean_in * factor,
                "withdrawal_clean_n": clean_out,
                "withdrawal_n": clean_out * factor,
            }
        )
    return {
        "schema": "perf02-samples-v1",
        "count": len(rows),
        "seed": seed,
        "label_source": "cantilever_friction_v1",
        "note": (
            "标签 = 悬臂梁摩擦公式 × 对数正态散差（标准差 0.08，截断 0.75–1.30）。"
            "替换 insertion_n / withdrawal_n 后重新训练。"
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
