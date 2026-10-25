# -*- coding: utf-8 -*-
"""DFM-07 紧固件啮合长度。"""

from __future__ import annotations

from ...checkers.base import CheckContext
from ...contracts import Finding, ModelBundle
from ._assembly_base import AssemblyChecker
from ._assembly_common import EPS, extract_fasteners, trace_location


class EngagementLengthChecker(AssemblyChecker):
    check_item_id = "DFM-07"
    name = "紧固件啮合长度"
    requires = ("multiple_parts",)
    default_params = {"engagement_ratio_steel": 1.0, "engagement_ratio_plastic": 1.5}

    def applies(self, model: ModelBundle, params: dict) -> tuple[bool, str]:
        ready, reason = super().applies(model, params)
        if not ready:
            return ready, reason
        measurable = [
            feature
            for feature in extract_fasteners(model)
            if feature.engagement_length_mm is not None
            and feature.nominal_diameter_mm is not None
            and feature.nominal_diameter_mm > 0
        ]
        return (
            (True, "")
            if measurable
            else (False, "缺少螺纹啮合长度或公称直径；请提供 assembly_features.fasteners 数据")
        )

    def check(self, ctx: CheckContext) -> list[Finding]:
        steel = float(ctx.param("engagement_ratio_steel", 1.0))
        soft = float(ctx.param("engagement_ratio_plastic", 1.5))
        findings: list[Finding] = []
        for fastener in extract_fasteners(ctx.model):
            diameter = fastener.nominal_diameter_mm
            engagement = fastener.engagement_length_mm
            if diameter is None or diameter <= 0 or engagement is None:
                continue
            material = fastener.material.lower()
            ratio_limit = (
                soft
                if any(token in material for token in ("plastic", "aluminum", "aluminium", "塑料", "铝"))
                else steel
            )
            ratio = engagement / diameter
            if ratio >= ratio_limit - EPS:
                continue
            target_length = ratio_limit * diameter
            location, bbox = trace_location(
                ctx.model, fastener.face_ids, fastener.head_center
            )
            findings.append(ctx.finding(
                severity="P2",
                message=(
                    f"紧固件 {fastener.feature_id} 的啮合长度比 L/D={ratio:.3f} "
                    f"< {ratio_limit:.3f}（材料：{fastener.material}）。"
                ),
                part_refs=[fastener.part_id],
                location=location,
                bbox=bbox,
                measured_value=round(ratio, 6),
                threshold_value=ratio_limit,
                unit="ratio",
                confidence=0.99,
                face_ids=fastener.face_ids,
                suggestion_text=(
                    f"将有效啮合长度由 {engagement:.3f} mm 增加到至少"
                    f" {target_length:.3f} mm，或改用相匹配的紧固件。"
                ),
                suggestion_delta={"target_engagement_length_mm": round(target_length, 4)},
                extra={
                    "engagement_length_mm": engagement,
                    "nominal_diameter_mm": diameter,
                    "material": fastener.material,
                    "required_ratio": ratio_limit,
                },
            ))
        return findings
