# -*- coding: utf-8 -*-
"""DFM-35 深圆角转角（二期粗筛）。

内腔转角圆角半径小于刀具半径时，刀具进不去，转角处留料或需电火花清角。
粗筛判定：位于零件内部、且与两个互垂平面相邻的回转圆角面，半径
< min_corner_radius_mm（默认取标准刀具最小刀尖圆角）即报。

已知不足：未评估型腔深度——浅腔的小转角可用小刀具够到，只有深腔才真正
不可达；真实判定需结合腔深与刀具悬伸（二期）。结果需人工复核。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding

from ._m6b_machining_common import (
    MachiningChecker,
    PERPENDICULAR_DOT,
    adjacency_map,
    dot,
    emit_finding,
    extract_fillets,
    face_normal,
    face_point,
    positive_number,
)


class DeepRadiusCornerChecker(MachiningChecker):
    check_item_id = "DFM-35"
    name = "深圆角转角"
    requires = ("face_radius", "adjacency")
    default_params = {
        "min_corner_radius_mm": 0.5,
    }

    def applies(self, model, params) -> tuple[bool, str]:
        if not any(f.interior for f in extract_fillets(model)):
            return False, "未识别到内部圆角转角（粗筛）"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        rmin = positive_number(ctx.param("min_corner_radius_mm")) or 0.5
        adj = adjacency_map(ctx.model)
        face_map = ctx.model.face_map()

        findings = []
        for fillet in extract_fillets(ctx.model):
            if not fillet.interior or fillet.radius >= rmin:
                continue
            # 转角特征：圆角面两侧是互垂的平面
            parents = []
            for fid in sorted(adj.get(fillet.face.face_id, ())):
                candidate = face_map.get(fid)
                n = face_normal(candidate) if candidate is not None else None
                if n is not None:
                    parents.append(n)
            perpendicular = any(
                abs(dot(a, b)) <= PERPENDICULAR_DOT
                for i, a in enumerate(parents)
                for b in parents[i + 1:]
            )
            if not perpendicular:
                continue
            point = face_point(fillet.face)
            findings.append(
                emit_finding(
                    ctx,
                    part_id=fillet.part_id,
                    face_ids=fillet.face_ids,
                    message=(
                        f"【粗筛】零件 {fillet.part_id} 内部转角圆角 R{fillet.radius:.2f} "
                        f"< 标准刀具最小刀尖圆角 {rmin:.2f} mm；"
                        f"若为深腔转角，刀具无法到位，转角处会留料"
                    ),
                    measured=fillet.radius,
                    threshold=rmin,
                    suggestion=(
                        f"将转角圆角加大到 R{rmin:.1f} 以上（与所用立铣刀刀尖圆角匹配，"
                        f"并复核型腔深度对应的刀具直径）；若转角必须清根，"
                        f"注明电火花或钳工修整工序。"
                    ),
                    feature_kind="corner_fillet",
                    confidence=fillet.confidence,
                    location=point,
                    note=(
                        "二期粗筛：只比对转角半径与最小刀尖圆角，未评估型腔深度；"
                        "浅腔小转角可能被误报，需人工复核"
                    ),
                )
            )
        return findings


CHECKERS = [DeepRadiusCornerChecker()]
