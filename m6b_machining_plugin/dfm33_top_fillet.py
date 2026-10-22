# -*- coding: utf-8 -*-
"""DFM-33 顶部圆角（粗筛）。

顶边圆角缺失（锐边）或半径小于标准刀具最小刀尖圆角时，加工后留刀痕或
需要额外修整。粗筛约定：
  * 「顶区」= 沿 up_direction（默认 +Z，可用规则参数覆盖）上部的
    (1 - top_region_ratio) 跨度范围；
  * 锐边 = 一对互垂平面直接相邻（中间没有圆角面）且位于顶区；
  * 小圆角 = 顶区内的回转圆角面半径 < min_top_fillet_mm。
真实模型的「顶」取决于装夹方向，粗筛按建模方向判定，需人工复核。
"""

from __future__ import annotations

from typing import Iterable

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import Finding

from _m6b_machining_common import (
    MachiningChecker,
    dot,
    emit_finding,
    extract_fillets,
    extract_sharp_edges,
    face_point,
    norm,
    positive_number,
)


def _top_threshold(ctx: CheckContext, part, up) -> float | None:
    """零件顶区的下界（沿 up 方向的投影值）。"""
    if part is None or part.bbox is None:
        return None
    ratio = positive_number(ctx.param("top_region_ratio")) or 0.75
    box = part.bbox
    corners = [
        (box.xmin, box.ymin, box.zmin), (box.xmax, box.ymax, box.zmax),
    ]
    lo = min(dot(c, up) for c in corners)
    hi = max(dot(c, up) for c in corners)
    if hi - lo <= 1e-9:
        return None
    return lo + ratio * (hi - lo)


class TopFilletChecker(MachiningChecker):
    check_item_id = "DFM-33"
    name = "顶部圆角"
    requires = ("faces", "normals")
    default_params = {
        "min_top_fillet_mm": 0.5,
        "top_region_ratio": 0.75,
        "up_direction": [0.0, 0.0, 1.0],
    }

    def applies(self, model, params) -> tuple[bool, str]:
        has_adjacency = bool(model.adjacency or model.edges)
        has_radius = any(f.radius_diameter is not None for f in model.faces)
        if not has_adjacency and not has_radius:
            return False, "缺少面邻接与圆角数据，无法识别锐边/圆角（粗筛）"
        return True, ""

    def _up(self, ctx: CheckContext):
        raw = ctx.param("up_direction", [0.0, 0.0, 1.0])
        try:
            vec = (float(raw[0]), float(raw[1]), float(raw[2]))
        except (TypeError, ValueError, IndexError):
            vec = (0.0, 0.0, 1.0)
        return norm(vec)

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        rmin = positive_number(ctx.param("min_top_fillet_mm")) or 0.5
        up = self._up(ctx)

        thresholds = {
            part.part_id: _top_threshold(ctx, part, up) for part in ctx.model.parts
        }

        findings = []
        # 1) 顶区锐边 → 缺圆角（按零件归并，避免刷屏）
        sharp_by_part: dict[str, list] = {}
        for edge in extract_sharp_edges(ctx.model):
            threshold = thresholds.get(edge.part_id)
            if threshold is None or edge.location is None:
                continue
            if dot(edge.location, up) < threshold:
                continue
            sharp_by_part.setdefault(edge.part_id, []).append(edge)
        for part_id, edges in sharp_by_part.items():
            face_ids = sorted({fid for e in edges for fid in e.face_ids})
            findings.append(
                emit_finding(
                    ctx,
                    part_id=part_id,
                    face_ids=face_ids[:20],
                    message=(
                        f"【粗筛】零件 {part_id} 顶区存在 {len(edges)} 条锐边（两平面直接相交，"
                        f"无圆角），顶边圆角缺失；标准要求顶边 R ≥ {rmin:.2f} mm"
                    ),
                    measured=0.0,
                    threshold=rmin,
                    suggestion=(
                        f"为顶边添加 R{rmin:.1f} 以上圆角（推荐与零件其他圆角统一）；"
                        f"若顶边为装配贴合面需要保持锐边，请在此处豁免并注明去毛刺要求。"
                    ),
                    feature_kind="sharp_edge",
                    confidence=0.4,
                    location=edges[0].location,
                    extra={"sharp_edge_count": len(edges)},
                )
            )

        # 2) 顶区小圆角 → R 不足
        for fillet in extract_fillets(ctx.model):
            if fillet.interior:
                continue
            threshold = thresholds.get(fillet.part_id)
            if threshold is None:
                continue
            point = face_point(fillet.face)
            if point is None or dot(point, up) < threshold:
                continue
            if fillet.radius >= rmin:
                continue
            findings.append(
                emit_finding(
                    ctx,
                    part_id=fillet.part_id,
                    face_ids=fillet.face_ids,
                    message=(
                        f"【粗筛】零件 {fillet.part_id} 顶边圆角 R{fillet.radius:.2f} "
                        f"< 标准刀具最小刀尖圆角 {rmin:.2f} mm，加工后顶边留尖角/刀痕"
                    ),
                    measured=fillet.radius,
                    threshold=rmin,
                    suggestion=(
                        f"将顶边圆角加大到 R{rmin:.1f} 以上，与标准刀具刀尖圆角匹配；"
                        f"若为配合倒角而非圆角，请改标倒角尺寸。"
                    ),
                    feature_kind="fillet",
                    confidence=fillet.confidence,
                    location=point,
                )
            )
        return findings


CHECKERS = [TopFilletChecker()]
