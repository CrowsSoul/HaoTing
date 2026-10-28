# -*- coding: utf-8 -*-
"""SAF-01 电气间隙。"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from .engine import (
    SafetyInputError,
    ThresholdUnavailable,
    clearance_input_issue,
    clearance_measurements,
    clearance_threshold_mm,
    has_clearance_input,
    merged_safety_params,
    network_pairs,
    resolve_networks,
)


class ClearanceChecker(BaseChecker):
    check_item_id = "SAF-01"
    name = "电气间隙"
    version = "1.0.0"
    owner = "M2 宋馨雨"
    process_types = ("safety",)
    requires = ("faces", "multiple_parts")
    default_params = {
        "rated_voltage_v": 400,
        "pollution_degree": 2,
        "overvoltage_category": "III",
        "altitude_m": 2000,
        "max_exact_face_pairs": 5000,
        "allow_bbox_fallback": False,
        "bbox_confidence": 0.55,
    }
    #先检查手里的数据够不够
    def applies(self, model, params) -> tuple[bool, str]:
        merged = merged_safety_params(model, params)
        try:
            clearance_threshold_mm(merged)
        except ThresholdUnavailable as exc:
            return False, str(exc)
        #找电气网络
        networks = resolve_networks(model, merged)
        if len(networks) < 2 or not network_pairs(networks, model, merged):
            return False, "缺少至少两个不同电位的网络；请配置 meta.safety.networks"
        if not has_clearance_input(model, merged):
            return False, "缺少 NX .prt/精确测量结果；如需粗筛请显式启用 allow_bbox_fallback"
        issue = clearance_input_issue(model, merged)
        if issue:
            return False, issue
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        params = merged_safety_params(ctx.model, ctx.params)
        #查表得到安全电气距离
        threshold, source = clearance_threshold_mm(params)
        try:
            #模型里各个网络之间的距离
            measurements = clearance_measurements(ctx, threshold)
        except SafetyInputError:
            return []

        findings = []
        for item in measurements:
            if item.compliant:
                continue
            coarse = item.method == "bbox-lower-bound"
            suggestion_target = threshold
            #打包错误信息
            findings.append(
                ctx.finding(
                    #粗筛给 P3（警告），精确算出来不合格给 P0（致命）
                    severity="P3" if coarse else "P0",
                    message=(
                        f"网络 {item.network_a} ↔ {item.network_b} 电气间隙 "
                        f"{item.measured_mm:.3f} mm < 要求 {threshold:.3f} mm"
                        + ("（包围盒粗筛，需精确复核）" if coarse else "")
                    ),
                    #涉及哪几个零件
                    part_refs=item.part_refs,
                    # 3D 坐标
                    location=item.location,
                    #实测值（保留6位）
                    measured_value=round(item.measured_mm, 6),
                    #及格线
                    threshold_value=threshold,
                    #置信度（粗筛 0.55，精确 0.99）
                    confidence=item.confidence,
                    suggestion_text=(
                        f"调整端子或隔离结构，使两网络最短空气距离达到 "
                        f"{suggestion_target:.3f} mm 以上。"
                    ),
                    suggestion_delta={
                        "target_clearance_mm": suggestion_target,
                        "increase_mm": round(threshold - item.measured_mm, 6),
                    },
                    face_ids=item.face_ids,
                    note=f"{item.note}；阈值来源：{source}",
                    extra={
                        "network_a": item.network_a,
                        "network_b": item.network_b,
                        "method": item.method,
                        "p1": list(item.p1) if item.p1 else None,
                        "p2": list(item.p2) if item.p2 else None,
                        "source_standard": source,
                    },
                )
            )
        return findings


CHECKERS = [ClearanceChecker()]
