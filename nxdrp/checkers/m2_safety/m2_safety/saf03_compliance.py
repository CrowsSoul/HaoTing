# -*- coding: utf-8 -*-
"""SAF-03 安规不合规归集。"""

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


class SafetyComplianceChecker(BaseChecker):
    check_item_id = "SAF-03"
    name = "安规不合规归集"
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
        "combine": "worst",
    }

    def applies(self, model, params) -> tuple[bool, str]:
        merged = merged_safety_params(model, params)
        if latest_measurements(model, "clearance") or latest_measurements(model, "creepage"):
            return True, ""
        reasons = []
        #检查是否有间隙数据
        clearance_ready = has_clearance_input(model, merged)
        creepage_ready = has_creepage_input(model, merged)
        if clearance_ready:
            issue = clearance_input_issue(model, merged)
            if issue:
                reasons.append(issue)
            else:
                return True, ""
        #检查是否有爬电数据
        if creepage_ready:
            issue = creepage_input_issue(model, merged)
            if issue:
                reasons.append(issue)
            else:
                return True, ""
        return False, "；".join(reasons) or "缺少电气间隙和爬电路径输入"

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        #把 SAF-01（间隙）和 SAF-02（爬电）的所有测量结果打包拉过来
        measurements, missing = combined_measurements(ctx)
        findings = []
        for pair, items in grouped_by_pair(measurements).items():
            #挑出一对网络里，所有不合规（failed）的项
            failed = [item for item in items if not item.compliant]
            if not failed:
                continue
            worst = min(failed, key=lambda item: item.deviation_mm)
            kinds = {item.kind: item for item in items}
            clearance = kinds.get("clearance")
            creepage = kinds.get("creepage")
            details = []
            if clearance:
                details.append(
                    f"间隙 {clearance.measured_mm:.3f}/{clearance.threshold_mm:.3f} mm"
                )
            if creepage:
                details.append(
                    f"爬电 {creepage.measured_mm:.3f}/{creepage.threshold_mm:.3f} mm"
                )
            face_ids = list(dict.fromkeys(x for item in failed for x in item.face_ids))
            part_refs = list(dict.fromkeys(x for item in failed for x in item.part_refs))
            path = next((item.path_points for item in failed if item.path_points), [])
            findings.append(
                ctx.finding(
                    severity="P0",
                    message=f"网络 {pair[0]} ↔ {pair[1]} 安规不合格：" + "；".join(details),
                    part_refs=part_refs,
                    location=worst.location,
                    path_points=path,
                    measured_value=round(worst.measured_mm, 6),
                    threshold_value=worst.threshold_mm,
                    confidence=min(item.confidence for item in failed),
                    suggestion_text="必须处理所有未达标项后再放行；优先修正偏差最大的距离。",
                    suggestion_delta={
                        "worst_increase_mm": round(-worst.deviation_mm, 6),
                        "failed_items": [item.kind for item in failed],
                    },
                    face_ids=face_ids,
                    note="最不利原则归集；任一电气间隙或爬电距离低于限值即不合格",
                    extra={
                        "network_a": pair[0],
                        "network_b": pair[1],
                        "clearance": _summary(clearance),
                        "creepage": _summary(creepage),
                        "missing_inputs": missing,
                    },
                )
            )
        return findings


def _summary(item):
    if item is None:
        return None
    return {
        "measured_mm": item.measured_mm,
        "threshold_mm": item.threshold_mm,
        "compliant": item.compliant,
        "method": item.method,
    }


CHECKERS = [SafetyComplianceChecker()]
