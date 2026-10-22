# -*- coding: utf-8 -*-
"""参考实现：DFM-02 最小间隙（包围盒粗筛版）。

用包围盒只能给出间隙的下界，真实间隙要回 NX 用 Measurement.GetMinimumDistance 精确算。
所以这里输出 confidence=0.55、severity=P3，并在 message 里写明是粗筛。

M4 的汪琪俊应在此基础上接入 NX 精确测距，把置信度提到 0.95 以上。
"""

from __future__ import annotations

from itertools import combinations
from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ...geom import bbox_gap


class MinClearanceChecker(BaseChecker):
    check_item_id = "DFM-02"
    name = "最小间隙"
    version = "0.1.0"
    owner = "M4 汪琪俊"
    process_types = ("assembly",)
    requires = ("multiple_parts",)
    default_params = {
        "min_clearance_mm": 0.3,
        "confidence_crude": 0.55,
    }

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        threshold = float(ctx.param("min_clearance_mm", 0.3))
        conf = float(ctx.param("confidence_crude", 0.55))

        parts = [p for p in ctx.parts() if p.bbox is not None]
        if len(parts) < 2:
            return []

        findings = []
        for a, b in combinations(parts, 2):
            gap = bbox_gap(a.bbox, b.bbox)
            if gap > threshold:
                continue
            findings.append(
                ctx.finding(
                    severity="P3",
                    message=(
                        f"零件 {a.part_id} 与 {b.part_id} 的包围盒间隙 {gap:.3f} mm "
                        f"≤ 阈值 {threshold:.2f} mm（粗筛结果，需精确测量确认）"
                    ),
                    part_refs=[a.part_id, b.part_id],
                    bbox=a.bbox,
                    measured_value=round(gap, 4),
                    threshold_value=threshold,
                    confidence=conf,
                    suggestion_text=(
                        f"用 NX 精确测距复核；若真实间隙仍小于 {threshold:.2f} mm，"
                        f"调整 {a.part_id} 或 {b.part_id} 的结构使间隙达到 {threshold:.2f} mm 以上。"
                    ),
                    suggestion_delta={"min_clearance_mm": threshold},
                    note="包围盒粗筛：只在包围盒相交或贴近时触发，不代表真实干涉",
                    extra={"method": "bbox", "needs_precise_check": True},
                )
            )
        return findings


CHECKERS = [MinClearanceChecker()]
