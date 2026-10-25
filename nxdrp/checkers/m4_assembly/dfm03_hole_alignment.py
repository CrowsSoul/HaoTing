# -*- coding: utf-8 -*-
"""DFM-03 孔对齐。"""

from __future__ import annotations

from ...checkers.base import CheckContext
from ...contracts import Finding, ModelBundle
from ._assembly_base import AssemblyChecker
from ._assembly_common import (
    EPS,
    extract_holes,
    line_distance,
    pair_holes,
    unsigned_axis_angle_deg,
)


class HoleAlignmentChecker(AssemblyChecker):
    check_item_id = "DFM-03"
    name = "孔对齐"
    requires = ("multiple_parts",)
    default_params = {
        "axis_offset_tolerance_mm": 0.1,
        "diameter_tolerance_mm": 0.1,
        "axis_angle_tolerance_deg": 1.0,
        "candidate_search_radius_mm": 2.0,
        "candidate_angle_deg": 10.0,
    }

    def _pairs(self, model: ModelBundle, params: dict):
        return pair_holes(
            extract_holes(model),
            float(params["candidate_search_radius_mm"]),
            float(params["candidate_angle_deg"]),
        )

    def applies(self, model: ModelBundle, params: dict) -> tuple[bool, str]:
        ready, reason = super().applies(model, params)
        if not ready:
            return ready, reason
        if not self._pairs(model, params):
            return False, "未识别到可靠的跨零件配对孔；需要圆柱面轴线或 assembly_features.holes 标注"
        return True, ""

    def check(self, ctx: CheckContext) -> list[Finding]:
        offset_limit = float(ctx.param("axis_offset_tolerance_mm", 0.1))
        diameter_limit = float(ctx.param("diameter_tolerance_mm", 0.1))
        angle_limit = float(ctx.param("axis_angle_tolerance_deg", 1.0))
        findings: list[Finding] = []
        for a, b in self._pairs(ctx.model, ctx.params):
            offset = line_distance(a.center, a.axis, b.center, b.axis)
            if offset is None:
                continue
            diameter_delta = abs(a.diameter - b.diameter)
            angle = unsigned_axis_angle_deg(a.axis, b.axis)
            if (
                offset <= offset_limit + EPS
                and diameter_delta <= diameter_limit + EPS
                and angle <= angle_limit + EPS
            ):
                continue
            coarse = a.source != "metadata" or b.source != "metadata"
            findings.append(ctx.finding(
                severity="P2",
                message=(
                    ("【几何粗筛】" if coarse else "")
                    + f"零件 {a.part_id}/{b.part_id} 的配对孔未对齐：轴线偏差 {offset:.3f} mm，"
                    f"直径差 {diameter_delta:.3f} mm，轴线夹角 {angle:.3f}°。"
                ),
                part_refs=[a.part_id, b.part_id],
                location=a.center,
                measured_value=round(offset, 6),
                threshold_value=offset_limit,
                confidence=min(a.confidence, b.confidence),
                face_ids=a.face_ids + b.face_ids,
                suggestion_text=(
                    f"调整孔中心/装配定位，使轴线偏差≤{offset_limit:.3f} mm、"
                    f"直径差≤{diameter_limit:.3f} mm、夹角≤{angle_limit:.3f}°。"
                ),
                suggestion_delta={
                    "axis_offset_tolerance_mm": offset_limit,
                    "diameter_tolerance_mm": diameter_limit,
                    "axis_angle_tolerance_deg": angle_limit,
                },
                note="metadata 标注为高置信度；纯圆柱面推断为几何粗筛",
                extra={
                    "axis_offset_mm": offset,
                    "diameter_delta_mm": diameter_delta,
                    "axis_angle_deg": angle,
                    "coarse": coarse,
                },
            ))
        return findings
