# -*- coding: utf-8 -*-
"""DFM-36 角度铣削面（粗筛）。

侧面与基准面夹角非 90° 且不在标准角度系列内时，需要角度头、非标角度铣刀
或多次装夹。粗筛约定：
  * 基准面 = 零件面积最大的平面；
  * 其余平面（面积 ≥ min_face_area_mm2，已识别为倒角的小面除外）与基准面的
    夹角必须是标准角（默认 0/30/45/60/90°，±angle_tolerance_deg）。
基准面选择依赖面积启发，箱体类多基准零件可能选错基准，需人工复核。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding

from ._m6b_machining_common import (
    MachiningChecker,
    acute_angle_deg,
    base_planes,
    emit_finding,
    extract_chamfers,
    face_normal,
    face_point,
    nearest,
    nonnegative_number,
    tool_values,
)

FALLBACK_PLANE_ANGLES = [0.0, 30.0, 45.0, 60.0, 90.0]


class AngularMillingChecker(MachiningChecker):
    check_item_id = "DFM-36"
    name = "角度铣削面"
    requires = ("faces", "normals", "face_area")
    default_params = {
        "angle_tolerance_deg": 1.0,
        "min_face_area_mm2": 1.0,
    }

    def applies(self, model, params) -> tuple[bool, str]:
        if not base_planes(model):
            return False, "未找到可作为基准的平面"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        tol = nonnegative_number(ctx.param("angle_tolerance_deg"))
        tol = 1.0 if tol is None else tol
        min_area = nonnegative_number(ctx.param("min_face_area_mm2"))
        min_area = 1.0 if min_area is None else min_area
        standards = tool_values(ctx, "standard_angles_deg", "standard_plane_angles_deg", FALLBACK_PLANE_ANGLES)

        bases = base_planes(ctx.model)
        chamfer_face_ids = {c.face.face_id for c in extract_chamfers(ctx.model)}

        findings = []
        for part in ctx.model.parts:
            base = bases.get(part.part_id)
            if base is None:
                continue
            n_base = face_normal(base)
            if n_base is None:
                continue
            for face in ctx.faces(part.part_id, "planar"):
                if face.face_id == base.face_id or face.face_id in chamfer_face_ids:
                    continue
                n = face_normal(face)
                if n is None or (face.area is not None and face.area < min_area):
                    continue
                angle = acute_angle_deg(n, n_base)
                target = nearest(standards, angle)
                if target is None or abs(angle - target) <= tol:
                    continue
                findings.append(
                    emit_finding(
                        ctx,
                        part_id=part.part_id,
                        face_ids=[face.face_id, base.face_id],
                        message=(
                            f"【粗筛】零件 {part.part_id} 平面 {face.face_id} 与基准面 "
                            f"{base.face_id} 夹角 {angle:.1f}°，非 90° 且不在标准角度系列内"
                            f"（最近标准值 {target:.0f}°，偏差 {angle - target:+.1f}°）"
                        ),
                        measured=angle,
                        threshold=target,
                        unit="deg",
                        suggestion=(
                            f"优先将该面改为与基准面垂直（90°）或标准角 {target:.0f}°；"
                            f"若角度由功能决定，注明需角度头/斜垫铁装夹，并与工艺确认。"
                        ),
                        feature_kind="angular_face",
                        confidence=0.4,
                        location=face_point(face),
                        extra={"base_face_id": base.face_id},
                    )
                )
        return findings


CHECKERS = [AngularMillingChecker()]
