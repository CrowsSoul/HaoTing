# -*- coding: utf-8 -*-
"""DFM-30 刀具可达性（二期占位粗筛）。

沿孔轴线的刀具包络被其他零件遮挡时，刀具到不了工位。本占位实现只做
最粗的一阶筛查：从每个孔口沿孔轴向外伸出一段包络圆柱
（半径 = 孔半径 + tool_clearance_mm，长度 = envelope_length_mm），
检查是否与其他零件的包围盒相交。单零件模型直接判可达（ok:0）。

已知不足：包围盒级近似，遮挡体积、同零件自身遮挡、刀柄形状都未建模，
误报漏报都可能存在；真实可达性需刀具包络扫掠 + 实体求交（二期）。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding

from ._m6b_machining_common import (
    MachiningChecker,
    dot,
    emit_finding,
    extract_holes,
    face_point,
    norm,
    positive_number,
    scale,
    segment_bbox_distance,
    sub,
)


class ToolAccessibilityChecker(MachiningChecker):
    check_item_id = "DFM-30"
    name = "刀具可达性"
    requires = ("cylindrical_faces", "face_radius", "adjacency", "multiple_parts", "face_bbox")
    default_params = {
        "tool_clearance_mm": 2.0,
        "envelope_length_mm": 40.0,
    }

    def applies(self, model, params) -> tuple[bool, str]:
        if len(model.parts) < 2:
            return False, "单零件模型：占位粗筛只查跨零件遮挡，跳过"
        if not any(not h.is_boss for h in extract_holes(model)):
            return False, "未识别到孔特征（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        clearance = positive_number(ctx.param("tool_clearance_mm")) or 2.0
        env_len = positive_number(ctx.param("envelope_length_mm")) or 40.0

        other_boxes = {
            part.part_id: part.bbox for part in ctx.model.parts if part.bbox is not None
        }
        centers = {
            part.part_id: part.bbox.center
            for part in ctx.model.parts
            if part.bbox is not None
        }

        findings = []
        for hole in extract_holes(ctx.model):
            if hole.is_boss:
                continue
            part_center = centers.get(hole.part_id)
            for end in hole.ends:
                if end.kind != "opening":
                    continue
                opening = face_point(end.face)
                if opening is None or part_center is None:
                    continue
                # 包络方向：从零件中心指向孔口（ outward ），投影到孔轴上取正号
                outward = sub(opening, part_center)
                sign = 1.0 if dot(outward, hole.axis) >= 0 else -1.0
                direction = scale(norm(hole.axis), sign)
                far = (
                    opening[0] + direction[0] * env_len,
                    opening[1] + direction[1] * env_len,
                    opening[2] + direction[2] * env_len,
                )
                radius = hole.r_max + clearance
                blockers = [
                    pid
                    for pid, box in other_boxes.items()
                    if pid != hole.part_id
                    and segment_bbox_distance(opening, far, box) < radius
                ]
                if not blockers:
                    continue
                findings.append(
                    emit_finding(
                        ctx,
                        part_id=hole.part_id,
                        face_ids=hole.face_ids + [end.face.face_id],
                        message=(
                            f"【粗筛】零件 {hole.part_id} 孔（面 {'、'.join(hole.face_ids)}）"
                            f"孔口 {end.face.face_id} 沿轴 {env_len:.0f} mm 刀具包络"
                            f"（半径 {radius:.1f} mm）与零件 {'、'.join(sorted(blockers))} 的"
                            f"包围盒相交，刀具可能不可达"
                        ),
                        measured=radius,
                        threshold=None,
                        suggestion=(
                            "复核装配状态下该孔的加工/装配次序：先加工后装配，"
                            "或调整相邻零件结构让出刀具包络；若为装配后配作孔，"
                            "请在此处豁免并注明配作工序。"
                        ),
                        feature_kind="tool_envelope",
                        confidence=0.3,
                        location=opening,
                        note=(
                            "二期占位粗筛：包围盒级近似，仅查跨零件遮挡，"
                            "未建模刀柄形状与同零件遮挡，需人工复核"
                        ),
                        extra={
                            "blockers": sorted(blockers),
                            "envelope_length_mm": env_len,
                            "envelope_radius_mm": round(radius, 4),
                        },
                    )
                )
        return findings


CHECKERS = [ToolAccessibilityChecker()]
