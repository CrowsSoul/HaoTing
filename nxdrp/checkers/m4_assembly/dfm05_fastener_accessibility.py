# -*- coding: utf-8 -*-
"""DFM-05 紧固件可达性。"""

from __future__ import annotations

from ...checkers.base import CheckContext
from ...contracts import Finding, ModelBundle
from ._assembly_base import AssemblyChecker
from ._assembly_common import EPS, extract_fasteners, trace_location


class FastenerAccessibilityChecker(AssemblyChecker):
    check_item_id = "DFM-05"
    name = "紧固件可达性"
    requires = ("multiple_parts",)
    default_params = {"tool_envelope_diameter_mm": 10.0, "tool_envelope_height_mm": 40.0}

    def applies(self, model: ModelBundle, params: dict) -> tuple[bool, str]:
        ready, reason = super().applies(model, params)
        if not ready:
            return ready, reason
        measurable = [
            feature
            for feature in extract_fasteners(model)
            if feature.accessible is not None
            or feature.available_tool_diameter_mm is not None
            or feature.available_tool_height_mm is not None
        ]
        return (
            (True, "")
            if measurable
            else (False, "缺少紧固件工具包络测量；请提供 assembly_features.fasteners 的可达性数据")
        )

    def check(self, ctx: CheckContext) -> list[Finding]:
        req_d = float(ctx.param("tool_envelope_diameter_mm", 10.0))
        req_h = float(ctx.param("tool_envelope_height_mm", 40.0))
        findings: list[Finding] = []
        for fastener in extract_fasteners(ctx.model):
            diameter = fastener.available_tool_diameter_mm
            height = fastener.available_tool_height_mm
            blocked = (
                fastener.accessible is False
                or (diameter is not None and diameter < req_d - EPS)
                or (height is not None and height < req_h - EPS)
            )
            if not blocked:
                continue
            measured = diameter if diameter is not None else (height if height is not None else 0.0)
            threshold = req_d if diameter is not None or height is None else req_h
            location, bbox = trace_location(
                ctx.model, fastener.face_ids, fastener.head_center
            )
            findings.append(ctx.finding(
                severity="P1",
                message=(
                    f"紧固件 {fastener.feature_id} 的工具包络不可达："
                    f"可用直径={diameter} mm，可用高度={height} mm，"
                    f"要求至少 Φ{req_d:.2f}×{req_h:.2f} mm。"
                ),
                part_refs=[fastener.part_id] + fastener.blocking_part_ids,
                location=location,
                bbox=bbox,
                measured_value=measured,
                threshold_value=threshold,
                confidence=0.98,
                face_ids=fastener.face_ids,
                suggestion_text=(
                    "移除/避让遮挡件或扩大操作空间，使工具包络达到"
                    f"Φ{req_d:.2f}×{req_h:.2f} mm。"
                ),
                suggestion_delta={
                    "target_tool_diameter_mm": req_d,
                    "target_tool_height_mm": req_h,
                },
                extra={
                    "available_tool_diameter_mm": diameter,
                    "available_tool_height_mm": height,
                    "blocking_part_ids": fastener.blocking_part_ids,
                },
            ))
        return findings
