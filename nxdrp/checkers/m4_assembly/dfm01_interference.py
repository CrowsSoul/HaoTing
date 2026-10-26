# -*- coding: utf-8 -*-
"""DFM-01 干涉检测。"""

from __future__ import annotations

from itertools import combinations

from ...checkers.base import CheckContext
from ...contracts import BBox, Finding
from ._assembly_base import AssemblyChecker
from ._assembly_common import (
    EPS,
    bbox_volume,
    faces_near_box,
    feature_rows,
    intersection_box,
    number,
    overlap_extents,
    trace_location,
    valid_face_ids,
)


class InterferenceChecker(AssemblyChecker):
    check_item_id = "DFM-01"
    name = "干涉检测"
    requires = ("multiple_parts", "face_bbox")
    default_params = {
        "interference_volume_mm3": 0.01,
        "critical_gap_mm": 0.05,
        "ignore_face_area_below_mm2": 0.1,
        "min_overlap_extent_mm": 0.05,
        "confidence_crude": 0.5,
    }

    def check(self, ctx: CheckContext) -> list[Finding]:
        volume_limit = float(ctx.param("interference_volume_mm3", 0.01))
        min_extent = float(ctx.param("min_overlap_extent_mm", 0.05))
        min_area = float(ctx.param("ignore_face_area_below_mm2", 0.1))
        crude_confidence = min(0.6, float(ctx.param("confidence_crude", 0.5)))
        part_map = ctx.model.part_map()
        annotated = feature_rows(ctx.model, "interferences")
        rows: list[dict] = []

        if annotated:
            for row in annotated:
                part_ids = [str(x) for x in row.get("part_ids", [])]
                if len(part_ids) != 2 or any(pid not in part_map for pid in part_ids):
                    continue
                volume = number(row.get("volume_mm3"))
                if volume is None:
                    continue
                box = BBox.from_dict(row.get("bbox"))
                if box is None:
                    box = intersection_box(part_map[part_ids[0]].bbox, part_map[part_ids[1]].bbox)
                face_ids = valid_face_ids(ctx.model, row.get("face_ids", []))
                if not face_ids:
                    face_ids = faces_near_box(ctx.model, part_ids, box, min_area)
                if box is None:
                    _, box = trace_location(ctx.model, face_ids)
                rows.append({
                    "parts": part_ids,
                    "volume": volume,
                    "box": box,
                    "face_ids": face_ids,
                    "confidence": 0.98,
                    "method": "nx_interference",
                    "exact": True,
                })
        else:
            parts = [part for part in ctx.parts() if part.bbox is not None]
            for a, b in combinations(parts, 2):
                box = intersection_box(a.bbox, b.bbox)
                extents = overlap_extents(a.bbox, b.bbox)
                if box is None or min(extents) <= min_extent:
                    continue
                face_ids = faces_near_box(ctx.model, (a.part_id, b.part_id), box, min_area)
                rows.append({
                    "parts": [a.part_id, b.part_id],
                    "volume": bbox_volume(box),
                    "box": box,
                    "face_ids": face_ids,
                    "confidence": crude_confidence,
                    "method": "bbox_overlap",
                    "exact": False,
                    "overlap_extents_mm": extents,
                })

        findings: list[Finding] = []
        for row in rows:
            volume = float(row["volume"])
            if volume <= volume_limit + EPS or len(row["face_ids"]) < 2:
                continue
            a, b = row["parts"]
            exact = bool(row["exact"])
            prefix = "" if exact else "【包围盒粗筛】"
            findings.append(ctx.finding(
                severity="P1",
                message=(
                    f"{prefix}零件 {a} 与 {b} 的重叠体积 {volume:.4f} mm³ "
                    f"> 阈值 {volume_limit:.4f} mm³。"
                ),
                part_refs=[a, b],
                location=row["box"].center if row["box"] else None,
                bbox=row["box"],
                measured_value=round(volume, 6),
                threshold_value=volume_limit,
                unit="mm^3",
                confidence=row["confidence"],
                face_ids=row["face_ids"],
                suggestion_text=(
                    f"调整 {a} 或 {b} 的装配定位/结构，消除实体重叠；"
                    f"精确求交体积应不大于 {volume_limit:.4f} mm³。"
                ),
                suggestion_delta={"target_interference_volume_mm3": volume_limit},
                note=(
                    "NX 精确实体求交结果"
                    if exact
                    else "包围盒只用于候选预筛，必须在 NX 中执行实体求交复核"
                ),
                extra={
                    "method": row["method"],
                    "coarse": not exact,
                    "needs_nx_confirmation": not exact,
                    "overlap_extents_mm": row.get("overlap_extents_mm"),
                },
            ))
        return findings
