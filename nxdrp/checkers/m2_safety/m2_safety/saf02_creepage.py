# -*- coding: utf-8 -*-
"""SAF-02 爬电距离：绝缘表面图上的多源最短路径。"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from .engine import (
    SafetyInputError,
    ThresholdUnavailable,
    creepage_input_issue,
    creepage_measurements,
    creepage_threshold_mm,
    has_creepage_input,
    merged_safety_params,
    network_pairs,
    resolve_networks,
)


class CreepageChecker(BaseChecker):
    check_item_id = "SAF-02"
    name = "爬电距离"
    version = "1.0.0"
    owner = "M2 宋馨雨"
    process_types = ("safety",)
    requires = ("faces", "multiple_parts")
    default_params = {
        "rated_voltage_v": 400,
        "working_voltage_v": 400,
        "pollution_degree": 2,
        "material_group": "II",
        "mesh_weld_tolerance_mm": 0.001,
        "terminal_vertex_count": 3,
        "creepage_confidence": 0.9,
    }

    def applies(self, model, params) -> tuple[bool, str]:
        merged = merged_safety_params(model, params)
        try:
            creepage_threshold_mm(merged)
        except ThresholdUnavailable as exc:
            return False, str(exc)
        networks = resolve_networks(model, merged)
        if len(networks) < 2 or not network_pairs(networks, model, merged):
            return False, "缺少至少两个不同电位的网络；请配置 meta.safety.networks"
        if not has_creepage_input(model, merged):
            return False, "缺少绝缘表面图、绝缘体 STL 或已测爬电路径"
        issue = creepage_input_issue(model, merged)
        if issue:
            return False, issue
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        params = merged_safety_params(ctx.model, ctx.params)
        threshold, source = creepage_threshold_mm(params)
        try:
            measurements = creepage_measurements(ctx, threshold)
        except SafetyInputError:
            return []

        findings = []
        for item in measurements:
            if item.compliant:
                continue
            findings.append(
                ctx.finding(
                    severity="P0",
                    message=(
                        f"网络 {item.network_a} ↔ {item.network_b} 爬电距离 "
                        f"{item.measured_mm:.3f} mm < 要求 {threshold:.3f} mm"
                    ),
                    part_refs=item.part_refs,
                    location=item.location,
                    path_points=item.path_points,
                    measured_value=round(item.measured_mm, 6),
                    threshold_value=threshold,
                    confidence=item.confidence,
                    suggestion_text=(
                        f"延长绝缘表面路径至 {threshold:.3f} mm 以上；"
                        "可增加绝缘筋/沟槽或调整端子在绝缘表面的接触边界。"
                    ),
                    suggestion_delta={
                        "target_creepage_mm": threshold,
                        "increase_mm": round(threshold - item.measured_mm, 6),
                    },
                    face_ids=item.face_ids,
                    note=f"{item.note}；阈值来源：{source}",
                    extra={
                        "network_a": item.network_a,
                        "network_b": item.network_b,
                        "method": item.method,
                        "source_standard": source,
                        "path_vertex_count": len(item.path_points),
                        "path_rules": item.extra.get("path_rules", {}),
                    },
                )
            )
        return findings


CHECKERS = [CreepageChecker()]
