# -*- coding: utf-8 -*-
"""DFM-25 翻边高度（粗筛）。

折弯圆柱的相邻平面视为折弯腿，量取腿面在“轴×法向”方向上的包围盒跨度
作为翻边高度，与 3t + R 比较。高度从包围盒起算，未按真实切线扣除弯区。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding
from nxdrp.geom import bbox_extent_along, cross, face_normal, length, norm

from _m6a_dfm_common import (
    SheetMetalChecker,
    emit_finding,
    face_point,
    positive_number,
    thickness_text,
)


class FlangeHeightChecker(SheetMetalChecker):
    check_item_id = "DFM-25"
    name = "翻边高度"
    requires = ("faces", "normals", "axes", "cylindrical_faces", "face_radius")
    default_params = {
        "min_flange_height_ratio": 3.0,
        "bend_radius_override_mm": None,
        "sheet_thickness_mm": None,
    }

    def applies(self, model, params):
        feats = self.features(model, params)
        usable = [
            bend for bend in feats.bends
            if bend.legs and self.thickness(feats, bend.part_id) is not None
        ]
        if not usable:
            return False, "未识别到折弯腿平面（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        ratio = positive_number(ctx.param("min_flange_height_ratio")) or 3.0
        radius_override = positive_number(ctx.param("bend_radius_override_mm"))
        feats = self.features(ctx.model, ctx.params)
        findings = []
        seen: set[tuple[str, float]] = set()
        for bend in feats.bends:
            thickness = self.thickness(feats, bend.part_id)
            if thickness is None:
                continue
            radius = radius_override or bend.radius
            limit = ratio * thickness.value + radius
            for leg in bend.legs:
                normal = face_normal(leg)
                if normal is None or leg.bbox is None:
                    continue
                direction = norm(cross(bend.axis, normal))
                if length(direction) <= 1e-9:
                    continue
                height = bbox_extent_along(leg.bbox, direction)
                if height <= 1e-9 or height >= limit - 1e-9:
                    continue
                key = (bend.face.face_id, round(height, 3))
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    emit_finding(
                        ctx,
                        part_id=bend.part_id,
                        face_ids=[bend.face.face_id, leg.face_id],
                        message=(
                            f"【粗筛】零件 {bend.part_id} 折弯面 {bend.face.face_id} 的腿面 "
                            f"{leg.face_id} 展开高度 {height:.3f} mm < "
                            f"{ratio:.2f}×t+R={limit:.3f} mm"
                            f"（R={radius:.3f}，{thickness_text(thickness)}）"
                        ),
                        measured=height,
                        threshold=limit,
                        suggestion=(
                            f"将翻边高度增大到至少 {limit:.2f} mm（自弯曲线附近起算），"
                            f"或减小折弯半径。"
                        ),
                        thickness=thickness,
                        feature_kind="flange",
                        feature_confidence=bend.confidence,
                        location=face_point(leg) or bend.point,
                        note=(
                            "钣金粗筛：翻边高度取腿面包围盒沿展开方向的跨度，"
                            "包含弯区长度，需人工复核"
                        ),
                    )
                )
        return findings


CHECKERS = [FlangeHeightChecker()]
