# -*- coding: utf-8 -*-
"""DFM-10 壁厚变化。"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ._rules import m3_default_params
from ._common import edge_between, edge_index, wall_samples


class WallVariationChecker(BaseChecker):
    check_item_id = "DFM-10"
    name = "壁厚变化"
    version = "0.1.0"
    owner = "M3 代世航"
    process_types = ("injection", "casting")
    requires = ("faces", "face_area")
    default_params = m3_default_params("DFM-10")

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        limit = float(ctx.param("max_gradient_ratio"))
        samples = wall_samples(ctx)
        by_face: dict[str, list] = defaultdict(list)
        for sample in samples:
            for fid in sample.face_ids:
                by_face[fid].append(sample)

        pairs: set[tuple[str, str]] = set()
        for sample in samples:
            source = sample.face_ids[0] if sample.face_ids else ""
            for neighbor in sample.adjacent_face_ids:
                if neighbor in by_face:
                    pairs.add(tuple(sorted((source, neighbor))))
        for a, b in ctx.model.adjacency:
            if a in by_face and b in by_face:
                pairs.add(tuple(sorted((a, b))))

        edges = edge_index(ctx.model)
        findings: list[Finding] = []
        for a_id, b_id in sorted(pairs):
            a_sample = min(by_face[a_id], key=lambda s: s.thickness_mm)
            b_sample = min(by_face[b_id], key=lambda s: s.thickness_mm)
            if a_sample.part_id != b_sample.part_id:
                continue
            ta, tb = a_sample.thickness_mm, b_sample.thickness_mm
            ratio = abs(tb - ta) / max(abs(ta), abs(tb), 1e-9)
            if ratio <= limit:
                continue
            edge = edge_between(edges, a_id, b_id)
            a_face, b_face = ctx.face(a_id), ctx.face(b_id)
            loc = None
            if a_face is not None and a_face.cog is not None and b_face is not None and b_face.cog is not None:
                loc = tuple((a_face.cog[i] + b_face.cog[i]) / 2.0 for i in range(3))
            part = ctx.part(a_sample.part_id)
            findings.append(
                ctx.finding(
                    part_refs=[a_sample.part_id],
                    location=loc,
                    bbox=part.bbox if part else None,
                    measured_value=round(ratio * 100.0, 3),
                    threshold_value=round(limit * 100.0, 3),
                    unit="%",
                    confidence=0.82,
                    face_ids=[a_id, b_id],
                    edge_ids=[edge.edge_id] if edge else [],
                    message=(
                        f"相邻区域壁厚由 {ta:.3f} mm 变为 {tb:.3f} mm，"
                        f"变化率 {ratio * 100:.1f}% > {limit * 100:.1f}%"
                    ),
                    suggestion_text=(
                        f"将相邻壁厚差控制在 {limit * 100:.0f}% 以内，"
                        f"建议从较厚侧做长度不小于 3 倍壁厚差的渐变。"
                    ),
                    suggestion_delta={"max_gradient_ratio": limit},
                    note="按共享边或上游相邻壁厚区域计算变化率",
                    extra={"thickness_a_mm": round(ta, 4), "thickness_b_mm": round(tb, 4)},
                )
            )
        return findings


CHECKERS = [WallVariationChecker()]
