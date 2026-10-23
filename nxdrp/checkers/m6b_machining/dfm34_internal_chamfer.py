# -*- coding: utf-8 -*-
"""DFM-34 内部倒角（粗筛）。

倒角角度 / 尺寸不在标准系列内时，需要非标倒角刀或多次走刀。粗筛把
「与两个互垂平面相邻、法向夹在中间的小平面」识别为倒角面：
  * 角度 = 与两个母平面夹角的均值，比对标准角度系列（默认 30/45/60°）；
  * 尺寸 = 倒角面最小包围盒尺寸（≈ 倒角宽度），比对标准尺寸系列。
系列值来自 tool_library.json，可用规则参数覆盖。母平面不垂直的斜倒角、
非 45° 对称倒角会被漏检或误判，需人工复核。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding

from ._m6b_machining_common import (
    MachiningChecker,
    emit_finding,
    extract_chamfers,
    face_point,
    nearest,
    nonnegative_number,
    tool_values,
)

FALLBACK_CHAMFER_ANGLES = [30.0, 45.0, 60.0]
FALLBACK_CHAMFER_SIZES = [0.2, 0.3, 0.5, 1.0, 1.5, 2.0]


class InternalChamferChecker(MachiningChecker):
    check_item_id = "DFM-34"
    name = "内部倒角"
    requires = ("faces", "normals", "adjacency")
    default_params = {
        "angle_tolerance_deg": 5.0,
        "size_tolerance_mm": 0.1,
    }

    def applies(self, model, params) -> tuple[bool, str]:
        if not extract_chamfers(model):
            return False, "未识别到倒角特征（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        ang_tol = nonnegative_number(ctx.param("angle_tolerance_deg"))
        ang_tol = 5.0 if ang_tol is None else ang_tol
        size_tol = nonnegative_number(ctx.param("size_tolerance_mm"))
        size_tol = 0.1 if size_tol is None else size_tol
        angles = tool_values(ctx, "standard_chamfer_angles_deg", "standard_chamfer_angles_deg", FALLBACK_CHAMFER_ANGLES)
        sizes = tool_values(ctx, "standard_chamfer_sizes_mm", "standard_chamfer_sizes_mm", FALLBACK_CHAMFER_SIZES)

        findings = []
        for chamfer in extract_chamfers(ctx.model):
            point = face_point(chamfer.face)
            target_angle = nearest(angles, chamfer.angle_deg)
            target_size = nearest(sizes, chamfer.size_mm)

            if target_angle is not None and abs(chamfer.angle_deg - target_angle) > ang_tol:
                findings.append(
                    emit_finding(
                        ctx,
                        part_id=chamfer.part_id,
                        face_ids=chamfer.face_ids,
                        message=(
                            f"【粗筛】零件 {chamfer.part_id} 倒角（面 {chamfer.face.face_id}）"
                            f"角度 {chamfer.angle_deg:.1f}° 不在标准倒角角度系列内"
                            f"（最近标准值 {target_angle:.0f}°，偏差 {chamfer.angle_deg - target_angle:+.1f}°）"
                        ),
                        measured=chamfer.angle_deg,
                        threshold=target_angle,
                        unit="deg",
                        suggestion=(
                            f"将倒角角度改为 {target_angle:.0f}°（标准倒角刀）；"
                            f"若该角度由配合决定，请与工艺确认非标刀具或两刀合成方案。"
                        ),
                        feature_kind="chamfer",
                        confidence=chamfer.confidence,
                        location=point,
                        extra={"size_mm": round(chamfer.size_mm, 4)},
                    )
                )
                continue
            if (
                chamfer.size_mm > 0
                and target_size is not None
                and abs(chamfer.size_mm - target_size) > size_tol
            ):
                findings.append(
                    emit_finding(
                        ctx,
                        part_id=chamfer.part_id,
                        face_ids=chamfer.face_ids,
                        message=(
                            f"【粗筛】零件 {chamfer.part_id} 倒角（面 {chamfer.face.face_id}）"
                            f"尺寸 {chamfer.size_mm:.2f} mm 不在标准倒角尺寸系列内"
                            f"（最近标准值 {target_size:.1f} mm，偏差 {chamfer.size_mm - target_size:+.2f} mm）"
                        ),
                        measured=chamfer.size_mm,
                        threshold=target_size,
                        suggestion=(
                            f"将倒角尺寸改为 {target_size:.1f} mm（标准系列），"
                            f"角度 {chamfer.angle_deg:.0f}° 保持不变；"
                            f"若为去毛刺倒角，可直接标注 C{target_size:.1f}。"
                        ),
                        feature_kind="chamfer",
                        confidence=chamfer.confidence,
                        location=point,
                        extra={"angle_deg": round(chamfer.angle_deg, 2)},
                    )
                )
        return findings


CHECKERS = [InternalChamferChecker()]
