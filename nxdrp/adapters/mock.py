# -*- coding: utf-8 -*-
"""Mock 模型来源：从 JSON 读取 ModelBundle，不需要 NX。

用途：
  * 7 位同学在自己的机器上没有 NX 时，仍然能开发和测试 checker；
  * CI 里跑回归；
  * 前端（M7）联调。
"""

from __future__ import annotations

import json
import os

from ..contracts import BBox, Face, ModelBundle, Part

from .base import BaseModelSource


class MockAdapter(BaseModelSource):
    name = "mock"

    def __init__(self, model_dir: str | None = None):
        self.model_dir = model_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "mockdata", "models",
        )

    def available(self) -> bool:
        return os.path.isdir(self.model_dir)

    def load(self, part_path: str, **kwargs) -> ModelBundle:
        if not os.path.isfile(part_path):
            candidate = os.path.join(self.model_dir, part_path)
            if os.path.isfile(candidate):
                part_path = candidate
        bundle = ModelBundle.load(part_path)
        bundle.validate()
        bundle.meta.setdefault("cache", "mock")
        return bundle


def synthesize(model_id: str = "synthetic-001", faces: int = 12, parts: int = 2) -> ModelBundle:
    """编程式生成一个最小可用模型，用于单元测试。

    结构：parts 个立方体，每个 faces 个面，面类型按 planar/cylindrical 交替，
    包围盒首尾相接，方便测试「最小间隙」类 checker。
    """
    from ..version import SCHEMA_VERSION

    bundle = ModelBundle(model_id=model_id, units="mm", nx_version="mock", schema_version=SCHEMA_VERSION)
    fid = 0
    for i in range(parts):
        pid = f"P{i + 1:02d}"
        x0 = i * 30.0
        box = BBox(x0, 0.0, 0.0, x0 + 20.0, 20.0, 20.0)
        bundle.parts.append(
            Part(part_id=pid, name=f"BOX_{i + 1}", body_type="solid", bbox=box,
                 volume=8000.0, area=2400.0, face_count=faces)
        )
        for k in range(faces):
            fid += 1
            is_cyl = (k % 4 == 1)
            bundle.faces.append(
                Face(
                    face_id=f"F{fid}",
                    part_id=pid,
                    tag=fid,
                    solid_face_type="cylindrical" if is_cyl else "planar",
                    solid_face_code=2 if is_cyl else 1,
                    uf_face_type=17 if is_cyl else 16,
                    point=(x0 + 10.0, 10.0, 10.0),
                    normal=None if is_cyl else (0.0, 0.0, 1.0),
                    axis=(0.0, 0.0, 1.0) if is_cyl else None,
                    area=400.0 if not is_cyl else 125.6,
                    perimeter=80.0 if not is_cyl else 62.8,
                    radius_diameter=5.0 if is_cyl else None,
                    is_radius=True,
                    bbox=box,
                    edge_count=4,
                )
            )
    bundle.validate()
    return bundle
