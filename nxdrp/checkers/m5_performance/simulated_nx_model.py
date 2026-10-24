# -*- coding: utf-8 -*-
"""模拟 NX 的圆柱端子。

结构与解析结果相同：材料、圆柱面、半径和侧面面积。
"""

from __future__ import annotations

import math
import os

from ...contracts import BBox, Face, ModelBundle, Part

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "data", "simulated_nx_terminal.model.json")


def build_simulated_nx_terminal(
    diameter_mm: float = 2.0,
    length_mm: float = 8.0,
    material: str = "CuSn6",
) -> ModelBundle:
    """按圆柱端子组一份和 NX 解析结果同结构的模型。"""
    radius = float(diameter_mm) / 2.0
    length = float(length_mm)
    lateral = 2.0 * math.pi * radius * length
    return ModelBundle(
        model_id="simulated_nx_terminal",
        source="simulated_nx://terminal",
        nx_version="simulated-nx",
        units="mm",
        generator="nxdrp.checkers.m5_performance.simulated_nx_model",
        parts=[
            Part(
                part_id="P01",
                name="TERMINAL",
                material=material,
                body_type="solid",
                volume=math.pi * radius * radius * length,
                bbox=BBox(0.0, -radius, -radius, length, radius, radius),
                face_count=1,
                occurrence_path="ROOT/TERMINAL(1)",
            )
        ],
        faces=[
            Face(
                face_id="F_cyl",
                part_id="P01",
                solid_face_type="cylindrical",
                uf_face_type=17,
                area=lateral,
                radius_diameter=radius,
                is_radius=True,
                axis=(1.0, 0.0, 0.0),
                point=(length / 2.0, 0.0, 0.0),
                cog=(length / 2.0, 0.0, 0.0),
            )
        ],
        meta={"flow": "模拟NX"},
    )


def save_simulated_nx_terminal(path: str = MODEL_PATH, **kwargs) -> str:
    bundle = build_simulated_nx_terminal(**kwargs)
    bundle.validate()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bundle.save(path)
    return path
