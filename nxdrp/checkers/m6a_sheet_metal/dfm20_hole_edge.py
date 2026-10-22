# -*- coding: utf-8 -*-
"""DFM-20 孔到边缘距离（粗筛）。

孔中心到零件包围盒在板面两方向的最小距离，减去孔半径，得到孔边净距。
包围盒代替真实板边轮廓，异形板件会偏保守/偏乐观。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding

from ._m6a_dfm_common import (
    SheetMetalChecker,
    emit_finding,
    in_plane_axes,
    positive_number,
    thickness_text,
)


class HoleEdgeDistanceChecker(SheetMetalChecker):
    check_item_id = "DFM-20"
    name = "孔到边缘距离"
    requires = ("faces", "normals", "axes", "cylindrical_faces", "face_radius")
    default_params = {
        "min_edge_distance_ratio": 1.5,
        "sheet_thickness_mm": None,
    }

    def applies(self, model, params):
        feats = self.features(model, params)
        if not any(self.thickness(feats, hole.part_id) for hole in feats.holes):
            return False, "未识别到孔候选（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        ratio = positive_number(ctx.param("min_edge_distance_ratio")) or 1.5
        feats = self.features(ctx.model, ctx.params)
        boxes = {part.part_id: part.bbox for part in ctx.model.parts}
        findings = []
        for hole in feats.holes:
            thickness = self.thickness(feats, hole.part_id)
            bbox = boxes.get(hole.part_id)
            if thickness is None or bbox is None:
                continue
            axes = in_plane_axes(hole.axis)
            lows = (bbox.xmin, bbox.ymin, bbox.zmin)
            highs = (bbox.xmax, bbox.ymax, bbox.zmax)
            edge = min(
                min(hole.center[i] - lows[i], highs[i] - hole.center[i])
                for i in axes
            )
            gap = edge - hole.r_max
            limit = ratio * thickness.value
            if gap >= limit - 1e-9:
                continue
            faces = "、".join(hole.face_ids)
            findings.append(
                emit_finding(
                    ctx,
                    part_id=hole.part_id,
                    face_ids=hole.face_ids,
                    message=(
                        f"【粗筛】零件 {hole.part_id} 孔组（面 {faces}）孔边到板边净距 "
                        f"{gap:.3f} mm < {ratio:.2f}×t={limit:.3f} mm"
                        f"（{thickness_text(thickness)}）"
                    ),
                    measured=gap,
                    threshold=limit,
                    suggestion=(
                        f"将孔中心向板内移动至少 {limit - gap:.2f} mm，"
                        f"使孔边到板边净距达到 {limit:.2f} mm；"
                        f"若空间受限，可改用翻边孔或局部加强。"
                    ),
                    thickness=thickness,
                    feature_kind="hole",
                    feature_confidence=hole.confidence,
                    location=hole.center,
                    note=(
                        "钣金粗筛：用零件包围盒估计板边，按孔轴选两个全局坐标轴近似板面方向，"
                        "异形板边或斜孔会有偏差，需人工复核"
                    ),
                )
            )
        return findings


CHECKERS = [HoleEdgeDistanceChecker()]
