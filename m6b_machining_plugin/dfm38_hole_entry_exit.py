# -*- coding: utf-8 -*-
"""DFM-38 孔的入刀/出刀面（粗筛）。

孔口所在面的法向与孔轴夹角过大时，钻头入刀会滑偏、出刀会崩边。
粗筛判定：孔组端部位于零件表面的相邻面（孔口），其法向与孔轴的锐角
> max_entry_angle_deg（默认 5°）即报。孔口在曲面上（无法向）的情况
暂不判定，在 README 中列为已知限制。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding

from _m6b_machining_common import (
    MachiningChecker,
    acute_angle_deg,
    emit_finding,
    extract_holes,
    face_normal,
    face_point,
    nonnegative_number,
)


class HoleEntryExitChecker(MachiningChecker):
    check_item_id = "DFM-38"
    name = "孔的入刀/出刀面"
    requires = ("cylindrical_faces", "face_radius", "adjacency", "normals", "axes")
    default_params = {
        "max_entry_angle_deg": 5.0,
    }

    def applies(self, model, params) -> tuple[bool, str]:
        holes = extract_holes(model)
        if not any(
            any(e.kind == "opening" for e in h.ends) and not h.is_boss for h in holes
        ):
            return False, "未识别到带孔口面的孔（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        max_angle = nonnegative_number(ctx.param("max_entry_angle_deg"))
        max_angle = 5.0 if max_angle is None else max_angle

        findings = []
        for hole in extract_holes(ctx.model):
            if hole.is_boss:
                continue  # 凸台端盖不涉及入刀/出刀
            for end in hole.ends:
                if end.kind != "opening":
                    continue
                normal = face_normal(end.face)
                if normal is None:
                    continue  # 孔口在曲面上，粗筛暂不判定
                angle = acute_angle_deg(normal, hole.axis)
                if angle <= max_angle:
                    continue
                diameter = 2.0 * hole.r_min
                point = face_point(end.face)
                findings.append(
                    emit_finding(
                        ctx,
                        part_id=hole.part_id,
                        face_ids=hole.face_ids + [end.face.face_id],
                        message=(
                            f"【粗筛】零件 {hole.part_id} 孔（面 {'、'.join(hole.face_ids)}）"
                            f"孔口面 {end.face.face_id} 与孔轴夹角 {angle:.1f}° > {max_angle:.1f}°，"
                            f"钻头入刀/出刀易滑偏（孔径 Ø{diameter:.2f}）"
                        ),
                        measured=angle,
                        threshold=max_angle,
                        unit="deg",
                        suggestion=(
                            "优先将孔口面改为与孔轴垂直（先铣平面/锪平台再钻孔）；"
                            "结构受限时，用定心钻或刚性好的短钻，入刀降速，"
                            "并与工艺确认斜面钻孔方案。"
                        ),
                        feature_kind="hole_opening",
                        confidence=hole.confidence,
                        location=point or hole.center,
                        extra={
                            "diameter_mm": round(diameter, 4),
                            "opening_face_id": end.face.face_id,
                        },
                    )
                )
        return findings


CHECKERS = [HoleEntryExitChecker()]
