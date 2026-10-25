# -*- coding: utf-8 -*-
"""DFM-04 孔/槽对齐。"""

from __future__ import annotations

from ...checkers.base import CheckContext
from ...contracts import Finding, ModelBundle
from ._assembly_base import AssemblyChecker
from ._assembly_common import (
    EPS,
    extract_holes,
    extract_slots,
    pair_holes_slots,
    radial_offset,
    unsigned_axis_angle_deg,
)


class HoleSlotAlignmentChecker(AssemblyChecker):
    check_item_id = "DFM-04"
    name = "孔/槽对齐"
    requires = ("multiple_parts",)
    default_params = {
        "center_offset_tolerance_mm": 0.2,
        "axis_angle_tolerance_deg": 1.0,
        "candidate_search_radius_mm": 3.0,
        "candidate_angle_deg": 10.0,
    }

    def _pairs(self, model: ModelBundle, params: dict):
        return pair_holes_slots(
            extract_holes(model),
            extract_slots(model),
            float(params["candidate_search_radius_mm"]),
            float(params["candidate_angle_deg"]),
        )

    def applies(self, model: ModelBundle, params: dict) -> tuple[bool, str]:
        ready, reason = super().applies(model, params)
        if not ready:
            return ready, reason
        if not extract_slots(model):
            return False, "ModelBundle 不含可靠槽语义；请提供 assembly_features.slots 标注"
        if not self._pairs(model, params):
            return False, "未识别到可靠的跨零件孔/槽配对"
        return True, ""

    def check(self, ctx: CheckContext) -> list[Finding]:
        offset_limit = float(ctx.param("center_offset_tolerance_mm", 0.2))
        angle_limit = float(ctx.param("axis_angle_tolerance_deg", 1.0))
        findings: list[Finding] = []
        for hole, slot in self._pairs(ctx.model, ctx.params):
            offset = radial_offset(hole.center, slot.center, slot.axis)
            angle = unsigned_axis_angle_deg(hole.axis, slot.axis)
            if offset <= offset_limit + EPS and angle <= angle_limit + EPS:
                continue
            findings.append(ctx.finding(
                severity="P2",
                message=(
                    f"零件 {hole.part_id} 的孔与 {slot.part_id} 的槽未对齐："
                    f"中心偏差 {offset:.3f} mm，轴线夹角 {angle:.3f}°。"
                ),
                part_refs=[hole.part_id, slot.part_id],
                location=hole.center,
                measured_value=round(offset, 6),
                threshold_value=offset_limit,
                confidence=min(hole.confidence, slot.confidence),
                face_ids=hole.face_ids + slot.face_ids,
                suggestion_text=(
                    f"移动孔中心或槽中线，使中心偏差≤{offset_limit:.3f} mm，"
                    f"轴线夹角≤{angle_limit:.3f}°。"
                ),
                suggestion_delta={
                    "center_offset_tolerance_mm": offset_limit,
                    "axis_angle_tolerance_deg": angle_limit,
                },
                extra={
                    "center_offset_mm": offset,
                    "axis_angle_deg": angle,
                    "hole_diameter_mm": hole.diameter,
                    "slot_width_mm": slot.width,
                },
            ))
        return findings
