# -*- coding: utf-8 -*-
"""SAF-04 安规量化建议。"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from .engine import (
    clearance_input_issue,
    combined_measurements,
    creepage_input_issue,
    has_clearance_input,
    has_creepage_input,
    latest_measurements,
    merged_safety_params,
    grouped_by_pair,
)


class SafetySuggestionChecker(BaseChecker):
    check_item_id = "SAF-04"
    name = "安规量化建议"
    version = "1.0.0"
    owner = "M2 宋馨雨"
    process_types = ("safety",)
    requires = ("faces", "multiple_parts")
    default_params = {
        "rated_voltage_v": 400,
        "working_voltage_v": 400,
        "pollution_degree": 2,
        "material_group": "II",
        "overvoltage_category": "III",
        "target_margin_mm": 0.5,
    }

    def applies(self, model, params) -> tuple[bool, str]:
        merged = merged_safety_params(model, params)
        if latest_measurements(model, "clearance") or latest_measurements(model, "creepage"):
            return True, ""
        reasons = []
        clearance_ready = has_clearance_input(model, merged)
        creepage_ready = has_creepage_input(model, merged)
        if clearance_ready:
            issue = clearance_input_issue(model, merged)
            if issue:
                reasons.append(issue)
            else:
                return True, ""
        if creepage_ready:
            issue = creepage_input_issue(model, merged)
            if issue:
                reasons.append(issue)
            else:
                return True, ""
        return False, "；".join(reasons) or "缺少电气间隙和爬电路径输入"

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        margin = max(0.0, float(ctx.param("target_margin_mm", 0.5)))
        measurements, missing = combined_measurements(ctx)
        findings = []
        for pair, items in grouped_by_pair(measurements).items():
            failed = [item for item in items if not item.compliant]
            if not failed:
                continue

            actions = []
            delta = {}
            for item in failed:
                #目标值 = 标准要求 + 安全量
                target = item.threshold_mm + margin
                #还需要增加多少 = 目标值 - 实测值
                increase = max(0.0, target - item.measured_mm)
                if item.kind == "clearance":
                    actions.append(
                        f"将最短空气间隙从 {item.measured_mm:.3f} mm "
                        f"增加到至少 {target:.3f} mm（增加 {increase:.3f} mm）"
                    )
                    delta.update({
                        "target_clearance_mm": round(target, 6),
                        "clearance_increase_mm": round(increase, 6),
                    })
                else:
                    actions.append(
                        f"通过增加绝缘筋/沟槽或移动端子，将爬电路径从 {item.measured_mm:.3f} mm "
                        f"延长到至少 {target:.3f} mm（增加 {increase:.3f} mm）"
                    )
                    delta.update({
                        "target_creepage_mm": round(target, 6),
                        "creepage_increase_mm": round(increase, 6),
                    })

            worst = min(failed, key=lambda item: item.deviation_mm)
            face_ids = list(dict.fromkeys(x for item in failed for x in item.face_ids))
            part_refs = list(dict.fromkeys(x for item in failed for x in item.part_refs))
            path = next((item.path_points for item in failed if item.path_points), [])
            findings.append(
                ctx.finding(
                    severity="P1",
                    message=f"网络 {pair[0]} ↔ {pair[1]} 需要量化整改",
                    part_refs=part_refs,
                    location=worst.location,
                    path_points=path,
                    measured_value=round(worst.measured_mm, 6),
                    threshold_value=worst.threshold_mm + margin,
                    confidence=min(item.confidence for item in failed),
                    suggestion_text="；".join(actions) + "。",
                    suggestion_delta=delta,
                    face_ids=face_ids,
                    note="目标值 = IEC/企业限值 + 安全裕量",
                    extra={
                        "network_a": pair[0],
                        "network_b": pair[1],
                        "target_margin_mm": margin,
                        "missing_inputs": missing,
                    },
                )
            )
        return findings


CHECKERS = [SafetySuggestionChecker()]
