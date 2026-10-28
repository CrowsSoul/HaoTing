# -*- coding: utf-8 -*-
"""DFM-17 多抽芯方向。"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ...geom import angle_between_deg, norm
from ._rules import m3_default_params
from ._common import feature_face_ids, feature_location, undercut_features


class MultiPullDirectionChecker(BaseChecker):
    check_item_id = "DFM-17"
    name = "多抽芯方向"
    version = "0.1.0"
    owner = "M3 代世航"
    process_types = ("injection", "casting")
    requires = ("faces",)
    default_params = m3_default_params("DFM-17")

    def applies(self, model, params) -> tuple[bool, str]:
        payload = model.meta.get("m3_features") or {}
        values = payload.get("undercuts", []) if isinstance(payload, dict) else []
        if not values:
            return False, "缺少倒扣方向记录，无法统计抽芯方向簇"
        return True, ""

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        tolerance = float(ctx.param("direction_cluster_angle_deg"))
        directions = []
        for rec in undercut_features(ctx):
            if bool(rec.get("exempt") or rec.get("design_intent")):
                continue
            raw = rec.get("direction") or rec.get("draw_direction")
            if not isinstance(raw, (list, tuple)) or len(raw) != 3:
                continue
            vec = norm(tuple(float(x) for x in raw))
            if vec == (0.0, 0.0, 0.0):
                continue
            if not any(angle_between_deg(vec, existing["direction"]) <= tolerance for existing in directions):
                directions.append({"direction": vec, "records": [rec]})
            else:
                for existing in directions:
                    if angle_between_deg(vec, existing["direction"]) <= tolerance:
                        existing["records"].append(rec)
                        break
        if len(directions) <= 1:
            return []
        all_records = [r for group in directions for r in group["records"]]
        part_ids = list(dict.fromkeys(str(r.get("part_id")) for r in all_records if r.get("part_id")))
        face_ids = list(dict.fromkeys(fid for r in all_records for fid in feature_face_ids(r)))
        location = feature_location(ctx, all_records[0])
        return [
            ctx.finding(
                part_refs=part_ids,
                location=location,
                measured_value=float(len(directions)),
                threshold_value=1.0,
                unit="方向",
                confidence=0.9,
                face_ids=face_ids,
                message=(
                    f"倒扣需要 {len(directions)} 个独立抽芯方向："
                    + ", ".join(str(tuple(round(x, 3) for x in d["direction"])) for d in directions)
                ),
                suggestion_text=(
                    "合并同向倒扣并调整为单一滑块方向；无法合并时，"
                    "按各方向分别增加斜顶/滑块机构并评估模具空间。"
                ),
                suggestion_delta={"target_pull_direction_count": 1},
                note=f"方向按夹角 {tolerance:.1f}° 聚类",
                extra={"directions": [list(d["direction"]) for d in directions]},
            )
        ]


CHECKERS = [MultiPullDirectionChecker()]
