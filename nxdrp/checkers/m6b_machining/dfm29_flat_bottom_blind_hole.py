# -*- coding: utf-8 -*-
"""DFM-29 平底盲孔（粗筛）。

盲孔底部端面为平面（无钻尖角）时不利排屑，且需要立铣刀清底，多一道工序。
孔底取孔组端部位于零件内部的相邻面：平面底判为平底盲孔；圆锥底（钻尖）
不报；无法向的孔底（曲面/球面底）暂不判定，在 note 中说明。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding

from ._m6b_machining_common import (
    MachiningChecker,
    _is_cone,
    emit_finding,
    extract_holes,
    face_point,
)


class FlatBottomBlindHoleChecker(MachiningChecker):
    check_item_id = "DFM-29"
    name = "平底盲孔"
    requires = ("cylindrical_faces", "face_radius", "adjacency", "normals")
    default_params = {}

    def applies(self, model, params) -> tuple[bool, str]:
        holes = extract_holes(model)
        if not any(hole.ends and not hole.is_boss for hole in holes):
            return False, "未识别到带端面信息的盲孔（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        findings = []
        for hole in extract_holes(ctx.model):
            if hole.is_boss:
                continue  # 凸台端盖不是盲孔底
            bottoms = [end for end in hole.ends if end.kind == "bottom"]
            for end in bottoms:
                if _is_cone(end.face):
                    continue  # 钻尖底，排屑正常
                if end.face.solid_face_type != "planar" and end.face.normal is None:
                    continue  # 曲面/球面底，粗筛暂不判定
                diameter = 2.0 * hole.r_min
                point = face_point(end.face)
                findings.append(
                    emit_finding(
                        ctx,
                        part_id=hole.part_id,
                        face_ids=hole.face_ids + [end.face.face_id],
                        message=(
                            f"【粗筛】零件 {hole.part_id} 盲孔（面 {'、'.join(hole.face_ids)}）"
                            f"孔底为平面（底面 {end.face.face_id}），无钻尖角，"
                            f"不利排屑且需额外清底工序（孔径 Ø{diameter:.2f}，孔深 {hole.depth:.2f} mm）"
                        ),
                        measured=hole.depth,
                        threshold=None,
                        suggestion=(
                            "若结构无平底要求，改为钻尖底孔（约 118°）以省去清底工序；"
                            "若必须平底，图纸注明用立铣刀清底并给出底面平面度要求，"
                            "或改用锪钻一次成形。"
                        ),
                        feature_kind="hole_bottom",
                        confidence=hole.confidence,
                        location=point or hole.center,
                        extra={
                            "diameter_mm": round(diameter, 4),
                            "bottom_face_id": end.face.face_id,
                        },
                    )
                )
        return findings


CHECKERS = [FlatBottomBlindHoleChecker()]
