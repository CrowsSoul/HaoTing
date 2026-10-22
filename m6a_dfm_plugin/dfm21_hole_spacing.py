# -*- coding: utf-8 -*-
"""DFM-21 孔间距（粗筛）。

同零件、轴线平行的两个孔组，中心距减去两孔半径得到净距。
只支持圆孔，异形孔/腰形孔按外接圆处理。
"""

from __future__ import annotations

from itertools import combinations
from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding
from nxdrp.geom import dist, dot

from _m6a_dfm_common import (
    PARALLEL_DOT,
    SheetMetalChecker,
    emit_finding,
    positive_number,
    thickness_text,
)


class HoleSpacingChecker(SheetMetalChecker):
    check_item_id = "DFM-21"
    name = "孔间距"
    requires = ("faces", "normals", "axes", "cylindrical_faces", "face_radius")
    default_params = {
        "min_hole_spacing_ratio": 2.0,
        "sheet_thickness_mm": None,
    }

    def applies(self, model, params):
        feats = self.features(model, params)
        if not any(self.thickness(feats, hole.part_id) for hole in feats.holes):
            return False, "未识别到孔候选（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        ratio = positive_number(ctx.param("min_hole_spacing_ratio")) or 2.0
        feats = self.features(ctx.model, ctx.params)
        by_part: dict[str, list] = {}
        for hole in feats.holes:
            by_part.setdefault(hole.part_id, []).append(hole)

        findings = []
        for part_id, holes in by_part.items():
            thickness = self.thickness(feats, part_id)
            if thickness is None:
                continue
            limit = ratio * thickness.value
            for a, b in combinations(holes, 2):
                if abs(dot(a.axis, b.axis)) < PARALLEL_DOT:
                    continue
                center_distance = dist(a.center, b.center)
                clear = center_distance - a.r_max - b.r_max
                if clear >= limit - 1e-9:
                    continue
                faces_a = "、".join(a.face_ids)
                faces_b = "、".join(b.face_ids)
                location = (
                    (a.center[0] + b.center[0]) / 2.0,
                    (a.center[1] + b.center[1]) / 2.0,
                    (a.center[2] + b.center[2]) / 2.0,
                )
                findings.append(
                    emit_finding(
                        ctx,
                        part_id=part_id,
                        face_ids=list(a.face_ids) + list(b.face_ids),
                        message=(
                            f"【粗筛】零件 {part_id} 孔组（面 {faces_a}）与孔组"
                            f"（面 {faces_b}）净距 {clear:.3f} mm < "
                            f"{ratio:.2f}×t={limit:.3f} mm（{thickness_text(thickness)}）"
                        ),
                        measured=clear,
                        threshold=limit,
                        suggestion=(
                            f"将两孔中心距增大到至少 "
                            f"{limit + a.r_max + b.r_max:.2f} mm，或减小其中一孔孔径。"
                        ),
                        thickness=thickness,
                        feature_kind="hole",
                        feature_confidence=min(a.confidence, b.confidence),
                        location=location,
                    )
                )
        return findings


CHECKERS = [HoleSpacingChecker()]
