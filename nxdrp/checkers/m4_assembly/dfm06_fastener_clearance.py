# -*- coding: utf-8 -*-
"""DFM-06 紧固件间隙。"""

from __future__ import annotations

from ...checkers.base import CheckContext
from ...contracts import Finding, ModelBundle
from ._assembly_base import AssemblyChecker
from ._assembly_common import EPS, extract_fasteners, trace_location


class FastenerClearanceChecker(AssemblyChecker):
    check_item_id = "DFM-06"
    name = "紧固件间隙"
    requires = ("multiple_parts",)
    default_params = {"axial_clearance_mm": 0.5, "radial_clearance_mm": 0.5}

    def applies(self, model: ModelBundle, params: dict) -> tuple[bool, str]:
        ready, reason = super().applies(model, params)
        if not ready:
            return ready, reason
        measurable = [
            feature
            for feature in extract_fasteners(model)
            if feature.axial_clearance_mm is not None or feature.radial_clearance_mm is not None
        ]
        return (
            (True, "")
            if measurable
            else (False, "缺少紧固件轴向/径向间隙测量；请提供 assembly_features.fasteners 数据")
        )

    def check(self, ctx: CheckContext) -> list[Finding]:
        limits = (
            ("radial", "径向", float(ctx.param("radial_clearance_mm", 0.5))),
            ("axial", "轴向", float(ctx.param("axial_clearance_mm", 0.5))),
        )
        findings: list[Finding] = []
        for fastener in extract_fasteners(ctx.model):
            for key, label, limit in limits:
                measured = getattr(fastener, f"{key}_clearance_mm")
                if measured is None or measured >= limit - EPS:
                    continue
                location, bbox = trace_location(
                    ctx.model, fastener.face_ids, fastener.head_center
                )
                findings.append(ctx.finding(
                    severity="P2",
                    message=(
                        f"紧固件 {fastener.feature_id} 的{label}间隙 "
                        f"{measured:.3f} mm < 阈值 {limit:.3f} mm。"
                    ),
                    part_refs=[fastener.part_id] + fastener.blocking_part_ids,
                    location=location,
                    bbox=bbox,
                    measured_value=measured,
                    threshold_value=limit,
                    confidence=0.98,
                    face_ids=fastener.face_ids,
                    suggestion_text=(
                        f"调整孔位、紧固件头部或周边结构，使{label}间隙"
                        f"达到 {limit:.3f} mm 以上。"
                    ),
                    suggestion_delta={f"target_{key}_clearance_mm": limit},
                    extra={"clearance_direction": key, "fastener_id": fastener.feature_id},
                ))
        return findings
