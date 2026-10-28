# -*- coding: utf-8 -*-
"""DFM-18 尖角。"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ._rules import m3_default_params
from ._common import dihedral_angle_deg, edge_between, edge_index


class SharpCornerChecker(BaseChecker):
    check_item_id = "DFM-18"
    name = "尖角"
    version = "0.1.0"
    owner = "M3 代世航"
    process_types = ("injection", "casting", "sheet_metal")
    requires = ("faces", "edges", "adjacency", "normals")
    default_params = m3_default_params("DFM-18")

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        threshold = float(ctx.param("sharp_angle_deg"))
        tolerance = float(ctx.param("angle_tolerance_deg"))
        exemptions = {str(x) for x in (ctx.param("exempt_edge_ids") or ())}
        edges = edge_index(ctx.model)
        findings: list[Finding] = []
        seen: set[tuple[str, str]] = set()
        for a_id, b_id in ctx.model.adjacency:
            key = tuple(sorted((a_id, b_id)))
            if key in seen:
                continue
            seen.add(key)
            edge = edge_between(edges, a_id, b_id)
            if edge is not None and edge.edge_id in exemptions:
                continue
            a, b = ctx.face(a_id), ctx.face(b_id)
            if a is None or b is None or a.solid_face_type != "planar" or b.solid_face_type != "planar":
                continue
            angle = dihedral_angle_deg(a, b)
            if angle is None or angle >= threshold - tolerance:
                continue
            loc = None
            if a.cog is not None and b.cog is not None:
                loc = tuple((a.cog[i] + b.cog[i]) / 2.0 for i in range(3))
            findings.append(
                ctx.finding(
                    part_refs=[a.part_id],
                    location=loc,
                    bbox=edge.bbox if edge is not None and edge.bbox is not None else (a.bbox or b.bbox),
                    measured_value=round(angle, 4),
                    threshold_value=threshold,
                    unit="deg",
                    confidence=0.91,
                    face_ids=[a.face_id, b.face_id],
                    edge_ids=[edge.edge_id] if edge else [],
                    message=(
                        f"相邻面 {a.face_id} / {b.face_id} 的二面角 "
                        f"{angle:.2f}° < {threshold:.1f}°，形成尖角"
                    ),
                    suggestion_text=(
                        f"增加圆角或倒角，使该二面角达到至少 {threshold:.1f}°；"
                        "优先采用 R≥0.25t 的内圆角。"
                    ),
                    suggestion_delta={"min_dihedral_angle_deg": threshold},
                    note="按相邻平面外法向计算；已排除规则中的豁免边",
                    extra={"edge_id": edge.edge_id if edge else None},
                )
            )
        return findings


CHECKERS = [SharpCornerChecker()]
