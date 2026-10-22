# -*- coding: utf-8 -*-
"""参考实现：DFM-31 特征尺寸与刀具标准。

作用有两个：
  1. 真实可用 —— 找出孔径不在标准钻头/刀具系列里的孔，减少非标刀具与换刀成本；
  2. 当模板 —— 这是「一个 checker 应该长什么样」的完整范例，含参数、跳过逻辑、
     证据、量化建议、置信度。

注意：这是参考实现，M6 的张百瑞要在它基础上按甲方刀具库扩充，并补单元测试。
"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding

#: 常用标准钻头/立铣刀直径（mm）。甲方若有厂内刀具库，应以规则参数覆盖这一组。
DEFAULT_STANDARD_DIAMETERS = [
    1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0,
    6.5, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 14.0, 16.0, 18.0, 20.0,
]


class ToolStandardChecker(BaseChecker):
    check_item_id = "DFM-31"
    name = "特征尺寸与刀具标准"
    version = "0.1.0"
    owner = "M6 张百瑞"
    process_types = ("machining",)
    requires = ("cylindrical_faces", "face_radius")
    default_params = {
        "standard_diameters": DEFAULT_STANDARD_DIAMETERS,
        "tolerance_mm": 0.05,
        "max_hole_diameter_mm": 20.0,
        "min_hole_diameter_mm": 0.5,
    }

    def applies(self, model, params) -> tuple[bool, str]:
        if not model.faces_of(None, "cylindrical"):
            return False, "模型中没有圆柱面，判定为非孔类零件"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        series = [float(x) for x in ctx.param("standard_diameters", DEFAULT_STANDARD_DIAMETERS)]
        tol = float(ctx.param("tolerance_mm", 0.05))
        dmax = float(ctx.param("max_hole_diameter_mm", 20.0))
        dmin = float(ctx.param("min_hole_diameter_mm", 0.5))

        findings = []
        for face in ctx.faces(face_type="cylindrical"):
            # radius_diameter 是半径还是直径由数据源声明，这里统一换算
            raw = face.radius_diameter
            if raw is None:
                continue
            diameter = raw * 2.0 if face.is_radius else raw
            if diameter < dmin or diameter > dmax:
                continue

            nearest = min(series, key=lambda s: abs(s - diameter))
            if abs(nearest - diameter) <= tol:
                continue

            findings.append(
                ctx.finding(
                    severity=ctx.rule.severity,
                    message=(
                        f"孔直径 Ø{diameter:.2f} 不在标准刀具系列内"
                        f"（最近标准值 Ø{nearest:.1f}，偏差 {diameter - nearest:+.2f} mm）"
                    ),
                    part_refs=[face.part_id],
                    location=face.cog,
                    bbox=face.bbox,
                    measured_value=round(diameter, 4),
                    threshold_value=nearest,
                    confidence=0.9,
                    face_ids=[face.face_id],
                    suggestion_text=(
                        f"将孔径改为 Ø{nearest:.1f}（标准刀具），或确认该孔为非标定制并承担刀具成本；"
                        f"若为销孔/螺纹底孔，请以配合件为准并在此处豁免。"
                    ),
                    suggestion_delta={"diameter_mm": round(nearest, 3), "delta_mm": round(nearest - diameter, 3)},
                    note="按标准刀具体系判定；甲方厂内刀具库应以规则参数覆盖",
                    extra={"face_type": face.solid_face_type, "part_id": face.part_id},
                )
            )
        return findings


CHECKERS = [ToolStandardChecker()]
