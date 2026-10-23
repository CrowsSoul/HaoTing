# -*- coding: utf-8 -*-
"""DFM-27 深孔（粗筛）。

孔深 / 孔径 > deep_hole_ratio（默认 4）报警示；> very_deep_hole_ratio（默认 10）
升为 P1（需深孔钻工艺）。孔深取同轴孔组各段沿轴的包围盒总跨度，孔径取孔组
最小直径（最窄段决定钻孔难度）。包围盒跨度代替真实孔深，盲孔底部钻尖段会
被一并计入，结果偏保守，需人工复核。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding

from ._m6b_machining_common import (
    MachiningChecker,
    emit_finding,
    extract_holes,
    positive_number,
)


class DeepHoleChecker(MachiningChecker):
    check_item_id = "DFM-27"
    name = "深孔"
    requires = ("cylindrical_faces", "face_radius", "face_bbox", "axes")
    default_params = {
        "deep_hole_ratio": 4.0,
        "very_deep_hole_ratio": 10.0,
        "min_hole_diameter_mm": 0.5,
        "max_hole_diameter_mm": 50.0,
    }

    def applies(self, model, params) -> tuple[bool, str]:
        if not any(not h.is_boss for h in extract_holes(model)):
            return False, "未识别到孔特征（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        deep_ratio = positive_number(ctx.param("deep_hole_ratio")) or 4.0
        very_deep_ratio = positive_number(ctx.param("very_deep_hole_ratio")) or 10.0
        dmin = positive_number(ctx.param("min_hole_diameter_mm")) or 0.5
        dmax = positive_number(ctx.param("max_hole_diameter_mm")) or 50.0

        findings = []
        for hole in extract_holes(ctx.model):
            if hole.is_boss:
                continue  # 凸台/销钉不是钻出来的，深径比不适用
            # 深径比按孔组逐段计算，取最恶劣的一段（阶梯孔的窄段决定钻孔难度）
            worst = None  # (ratio, span, diameter, face_id)
            for face_id, radius, span in hole.segments:
                diameter = 2.0 * radius
                if diameter < dmin or diameter > dmax or span <= 0:
                    continue
                ratio = span / diameter
                if worst is None or ratio > worst[0]:
                    worst = (ratio, span, diameter, face_id)
            if worst is None:
                continue
            ratio, span, diameter, worst_face = worst
            if ratio <= deep_ratio:
                continue
            very_deep = ratio > very_deep_ratio
            faces = "、".join(hole.face_ids)
            target_d = span / deep_ratio
            findings.append(
                emit_finding(
                    ctx,
                    severity="P1" if very_deep else ctx.rule.severity,
                    part_id=hole.part_id,
                    face_ids=hole.face_ids,
                    message=(
                        f"【粗筛】零件 {hole.part_id} 孔组（面 {faces}）深径比 {ratio:.2f} "
                        f"> {very_deep_ratio:.0f}（超深孔，窄段 {worst_face}："
                        f"深 {span:.2f} mm / Ø{diameter:.2f}）" if very_deep else
                        f"【粗筛】零件 {hole.part_id} 孔组（面 {faces}）深径比 {ratio:.2f} "
                        f"> {deep_ratio:.2f}（窄段 {worst_face}：深 {span:.2f} mm / Ø{diameter:.2f}）"
                    ),
                    measured=ratio,
                    threshold=very_deep_ratio if very_deep else deep_ratio,
                    unit="比值",
                    suggestion=(
                        f"需采用深孔钻工艺（枪钻/BTA），并确认排屑与冷却方案；"
                        f"若结构允许，将孔径加大到 Ø{target_d:.1f} 以上或从两面钻孔，"
                        f"使深径比降到 {deep_ratio:.0f} 以内。" if very_deep else
                        f"优先从两面钻孔或做阶梯孔，将单侧深径比降到 {deep_ratio:.0f} 以内；"
                        f"若必须单侧钻，将孔径加大到 Ø{target_d:.1f} 以上，或与工艺确认断屑方案。"
                    ),
                    feature_kind="hole",
                    confidence=hole.confidence,
                    location=hole.center,
                    extra={
                        "depth_mm": round(span, 4),
                        "diameter_mm": round(diameter, 4),
                        "total_depth_mm": round(hole.depth, 4),
                        "worst_face_id": worst_face,
                        "very_deep": very_deep,
                    },
                )
            )
        return findings


CHECKERS = [DeepHoleChecker()]
