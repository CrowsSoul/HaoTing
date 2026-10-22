# -*- coding: utf-8 -*-
"""参考实现：DFM-32 底部圆角一致性。

思路：统计零件上所有回转圆角面（toroidal）的半径种类数。种类越多，加工时换刀次数越多、
成本越高。这是典型的「几何统计类」检查器，很适合作为第一个上手的模板。

参考实现，最终版本由 M6 按甲方工艺标准完善。
"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ...geom import cluster_values


class FilletUniformityChecker(BaseChecker):
    check_item_id = "DFM-32"
    name = "底部圆角一致性"
    version = "0.1.0"
    owner = "M6 张百瑞"
    process_types = ("machining",)
    requires = ("toroidal_faces", "face_radius")
    default_params = {
        "max_distinct_radii": 3,
        "cluster_tolerance_mm": 0.1,
        "min_radius_mm": 0.2,
    }

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        max_distinct = int(ctx.param("max_distinct_radii", 3))
        tol = float(ctx.param("cluster_tolerance_mm", 0.1))
        rmin = float(ctx.param("min_radius_mm", 0.2))

        groups: dict[str, list] = {}
        for face in ctx.faces(face_type="toroidal"):
            radius = face.radius_diameter
            if radius is None:
                continue
            radius = radius if face.is_radius else radius / 2.0
            if radius < rmin:
                continue
            groups.setdefault(face.part_id, []).append((radius, face))

        findings = []
        for part_id, pairs in groups.items():
            radii = [r for r, _ in pairs]
            reps = cluster_values(radii, tol)
            if len(reps) <= max_distinct:
                continue
            part = ctx.part(part_id)
            findings.append(
                ctx.finding(
                    severity=ctx.rule.severity,
                    message=(
                        f"零件 {part_id} 存在 {len(reps)} 种不同的回转圆角半径 "
                        f"（{', '.join('R%.2f' % r for r in reps[:6])}{' …' if len(reps) > 6 else ''}），"
                        f"超过允许的 {max_distinct} 种，会显著增加换刀次数"
                    ),
                    part_refs=[part_id],
                    bbox=part.bbox if part else None,
                    measured_value=float(len(reps)),
                    threshold_value=float(max_distinct),
                    unit="种",
                    confidence=0.8,
                    face_ids=[f.face_id for _, f in pairs][:20],
                    suggestion_text=(
                        f"将圆角半径归并到不超过 {max_distinct} 种标准值（建议 "
                        f"{', '.join('R%.1f' % r for r in reps[:max_distinct])}），或与工艺确认哪些圆角可统一。"
                    ),
                    suggestion_delta={"distinct_radii_target": max_distinct},
                    note="按回转面半径聚类统计；刀尖圆角与设计圆角需人工区分",
                    extra={"radii": [round(r, 3) for r in reps]},
                )
            )
        return findings


CHECKERS = [FilletUniformityChecker()]
