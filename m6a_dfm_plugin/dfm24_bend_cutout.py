# -*- coding: utf-8 -*-
"""DFM-24 折弯与切口距离（二期占位实现，粗筛）。

孔轴线到折弯圆柱轴线的公垂线距离，减去孔半径，与 3t + R 比较。
真实判定应量孔边到折弯切线的距离，这里用轴线近似。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding

from _m6a_dfm_common import (
    SheetMetalChecker,
    emit_finding,
    line_line_distance,
    positive_number,
    thickness_text,
)


class BendCutoutDistanceChecker(SheetMetalChecker):
    check_item_id = "DFM-24"
    name = "折弯与切口距离"
    requires = ("faces", "normals", "axes", "cylindrical_faces", "face_radius")
    default_params = {
        "bend_clearance_ratio": 3.0,
        "bend_radius_override_mm": None,
        "sheet_thickness_mm": None,
    }

    def applies(self, model, params):
        feats = self.features(model, params)
        if not any(self.thickness(feats, bend.part_id) for bend in feats.bends):
            return False, "未识别到折弯候选圆柱面（粗筛）"
        if not any(self.thickness(feats, hole.part_id) for hole in feats.holes):
            return False, "未识别到孔/切口候选（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        ratio = positive_number(ctx.param("bend_clearance_ratio")) or 3.0
        radius_override = positive_number(ctx.param("bend_radius_override_mm"))
        feats = self.features(ctx.model, ctx.params)
        holes_by_part: dict[str, list] = {}
        for hole in feats.holes:
            holes_by_part.setdefault(hole.part_id, []).append(hole)

        findings = []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for bend in feats.bends:
            thickness = self.thickness(feats, bend.part_id)
            if thickness is None:
                continue
            radius = radius_override or bend.radius
            limit = ratio * thickness.value + radius
            for hole in holes_by_part.get(bend.part_id, ()):
                distance = line_line_distance(
                    hole.center, hole.axis, bend.point, bend.axis
                )
                if distance is None:
                    continue
                clear = distance - hole.r_max
                if clear >= limit - 1e-9:
                    continue
                key = (bend.face.face_id, tuple(hole.face_ids))
                if key in seen:
                    continue
                seen.add(key)
                faces = "、".join(hole.face_ids)
                findings.append(
                    emit_finding(
                        ctx,
                        part_id=bend.part_id,
                        face_ids=list(hole.face_ids) + [bend.face.face_id],
                        message=(
                            f"【粗筛】零件 {bend.part_id} 孔组（面 {faces}）轴线到折弯面 "
                            f"{bend.face.face_id} 轴线距离 {distance:.3f} mm，"
                            f"扣除孔半径后净距 {clear:.3f} mm < "
                            f"{ratio:.2f}×t+R={limit:.3f} mm"
                            f"（R={radius:.3f}，{thickness_text(thickness)}）"
                        ),
                        measured=clear,
                        threshold=limit,
                        suggestion=(
                            f"将该孔/切口沿远离折弯线方向移动至少 "
                            f"{limit - clear:.2f} mm，或减小孔半径/折弯半径。"
                        ),
                        thickness=thickness,
                        feature_kind="bend_hole",
                        feature_confidence=min(bend.confidence, hole.confidence),
                        location=hole.center,
                        note=(
                            "钣金粗筛（二期项）：用孔轴线到折弯圆柱轴线的公垂线距离近似，"
                            "未按真实折弯切线与孔边计算，需人工复核"
                        ),
                    )
                )
        return findings


CHECKERS = [BendCutoutDistanceChecker()]
