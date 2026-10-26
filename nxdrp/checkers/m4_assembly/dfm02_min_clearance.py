# -*- coding: utf-8 -*-
"""DFM-02 最小间隙。"""

from __future__ import annotations

from itertools import combinations

from ...checkers.base import CheckContext
from ...contracts import Finding
from ...geom import bbox_gap
from ._assembly_base import AssemblyChecker
from ._assembly_common import EPS, candidate_face_pairs, nearest_face_pair


class MinClearanceChecker(AssemblyChecker):
    check_item_id = "DFM-02"
    name = "最小间隙"
    requires = ("multiple_parts", "face_bbox")
    default_params = {"min_clearance_mm": 0.3, "confidence_crude": 0.55}

    def check(self, ctx: CheckContext) -> list[Finding]:
        threshold = float(ctx.param("min_clearance_mm", 0.3))
        candidates: list[tuple] = []
        for a, b in combinations([p for p in ctx.parts() if p.bbox is not None], 2):
            coarse_gap = bbox_gap(a.bbox, b.bbox)
            if coarse_gap > threshold + EPS:
                continue
            face_pairs = candidate_face_pairs(ctx.model, a.part_id, b.part_id, threshold)
            if not face_pairs:
                fallback = nearest_face_pair(ctx.model, a.part_id, b.part_id)
                face_pairs = [fallback] if fallback is not None else []
            if face_pairs:
                candidates.append((a, b, coarse_gap, face_pairs))

        tag_pairs = [
            (fa.tag, fb.tag)
            for _, _, _, face_pairs in candidates
            for fa, fb in face_pairs
            if fa.tag is not None and fb.tag is not None
        ]
        if ctx.nx is not None and tag_pairs:
            # 整个 checker 只启动一次 NX；随后 distance() 只查代理缓存。
            ctx.nx.prefetch(tag_pairs)

        findings: list[Finding] = []
        for a, b, coarse_gap, face_pairs in candidates:
            exact_rows = []
            if ctx.nx is not None:
                for fa, fb in face_pairs:
                    if fa.tag is None or fb.tag is None:
                        continue
                    distance = ctx.nx.distance(fa.tag, fb.tag)
                    if distance is not None:
                        exact_rows.append((float(distance), fa, fb))

            if exact_rows:
                gap, fa, fb = min(exact_rows, key=lambda row: row[0])
                precise = True
            else:
                gap = coarse_gap
                fa, fb = face_pairs[0]
                precise = False
            if gap > threshold + EPS:
                continue

            findings.append(ctx.finding(
                severity=(ctx.rule.severity if precise else "P3"),
                message=(
                    ("" if precise else "【包围盒粗筛】")
                    + f"零件 {a.part_id} 与 {b.part_id} 的最小间隙 {gap:.3f} mm "
                    f"≤ 阈值 {threshold:.3f} mm。"
                ),
                part_refs=[a.part_id, b.part_id],
                # 这是两面之间的关系；用 bbox + face_ids 定位，不伪造单点坐标。
                bbox=fa.bbox,
                measured_value=round(gap, 6),
                threshold_value=threshold,
                confidence=(
                    0.98
                    if precise
                    else min(0.6, float(ctx.param("confidence_crude", 0.55)))
                ),
                face_ids=[fa.face_id, fb.face_id],
                suggestion_text=(
                    f"调整 {a.part_id} 或 {b.part_id} 的结构/定位，"
                    f"使精确最小间隙大于 {threshold:.3f} mm。"
                ),
                suggestion_delta={"target_min_clearance_mm": threshold},
                note=(
                    "NX 面-面最小距离"
                    if precise
                    else "包围盒距离下界，需用 NX 精确测距复核"
                ),
                extra={
                    "method": "nx_minimum_distance" if precise else "bbox_gap",
                    "coarse": not precise,
                    "needs_nx_confirmation": not precise,
                    "candidate_face_pair_count": len(face_pairs),
                },
            ))
        return findings
