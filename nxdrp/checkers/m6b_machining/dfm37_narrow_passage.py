# -*- coding: utf-8 -*-
"""DFM-37 窄通道（二期粗筛）。

通道宽度小于最小刀具直径时，刀具进不去，通道无法铣出。粗筛复用槽识别
结果：槽宽 < min_channel_width_mm（默认取 tool_library 最小刀具直径）即报。

已知不足：只比对宽度，未做空间遮挡分析——宽度足够但上方有遮挡的通道
同样不可达（需刀具包络扫掠，二期）；弯曲通道、异形截面通道不在粗筛范围。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding

from ._m6b_machining_common import (
    MachiningChecker,
    emit_finding,
    extract_slots,
    positive_number,
    tool_values,
)


class NarrowPassageChecker(MachiningChecker):
    check_item_id = "DFM-37"
    name = "窄通道"
    requires = ("faces", "normals", "adjacency", "face_bbox")
    default_params = {
        "min_channel_width_mm": 1.0,
    }

    def applies(self, model, params) -> tuple[bool, str]:
        if not extract_slots(model):
            return False, "未识别到槽/通道特征（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        fallback = tool_values(ctx, None, "min_tool_diameter_mm", [1.0])
        wmin = positive_number(ctx.param("min_channel_width_mm")) or (fallback[0] if fallback else 1.0)

        findings = []
        for slot in extract_slots(ctx.model):
            if slot.width <= 0 or slot.width >= wmin:
                continue
            findings.append(
                emit_finding(
                    ctx,
                    part_id=slot.part_id,
                    face_ids=slot.face_ids,
                    message=(
                        f"【粗筛】零件 {slot.part_id} 通道（面 {'、'.join(slot.face_ids)}）"
                        f"宽度 {slot.width:.3f} mm < 最小刀具直径 {wmin:.2f} mm，刀具无法进入"
                    ),
                    measured=slot.width,
                    threshold=wmin,
                    suggestion=(
                        f"将通道宽度加大到 {wmin:.2f} mm 以上；若宽度由功能决定，"
                        f"改用电火花、线切割或激光加工，并在图纸上注明特种加工要求。"
                    ),
                    feature_kind="narrow_passage",
                    confidence=slot.confidence,
                    location=slot.location,
                    note="二期粗筛：只比对通道宽度，未做刀具包络遮挡分析，需人工复核",
                    extra={"depth_mm": round(slot.depth, 4)},
                )
            )
        return findings


CHECKERS = [NarrowPassageChecker()]
