# -*- coding: utf-8 -*-
"""DFM-12 模具壁厚。"""

from __future__ import annotations

from itertools import combinations
from math import sqrt
from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding, Rule
from ...geom import dot, sub
from ._rules import m3_default_params
from ._common import boss_features, feature_face_ids, feature_location, meta_features, pull_direction


class MoldWallThicknessChecker(BaseChecker):
    check_item_id = "DFM-12"
    name = "模具壁厚"
    version = "0.1.0"
    owner = "M3 代世航"
    process_types = ("injection", "casting")
    requires = ("faces",)
    default_params = m3_default_params("DFM-12")

    def applies(self, model, params) -> tuple[bool, str]:
        rule = Rule(
            rule_id="DFM-12-preflight",
            check_item_id=self.check_item_id,
            params=params,
        )
        ctx = CheckContext(model=model, rule=rule, params=params, checker=self)
        records = self._feature_records(ctx)
        counts: dict[str, int] = {}
        for record in records:
            part_id = str(record.get("part_id") or "")
            counts[part_id] = counts.get(part_id, 0) + 1
        if any(count >= 2 for count in counts.values()):
            return True, ""
        return False, "缺少同一零件内至少两个可比较的筋/凸台特征"

    @staticmethod
    def _width(record: dict) -> float | None:
        for key in ("root_thickness_mm", "width_mm", "outer_diameter_mm"):
            if record.get(key) is not None:
                try:
                    return float(record[key])
                except (TypeError, ValueError):
                    pass
        for key in ("outer_radius_mm", "radius_mm"):
            if record.get(key) is not None:
                try:
                    return 2.0 * float(record[key])
                except (TypeError, ValueError):
                    pass
        return None

    def _feature_records(self, ctx: CheckContext) -> list[dict]:
        ribs = meta_features(ctx, "ribs")
        bosses = boss_features(ctx)
        records = []
        for kind, values in (("rib", ribs), ("boss", bosses)):
            for value in values:
                width = self._width(value)
                location = feature_location(ctx, value)
                if width and width > 0.0 and location is not None:
                    rec = dict(value)
                    rec["_kind"], rec["_width"], rec["_location"] = kind, width, location
                    records.append(rec)
        return records

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        minimum = float(ctx.param("min_mold_steel_thickness_mm"))
        pull = pull_direction(ctx)
        records = self._feature_records(ctx)
        findings: list[Finding] = []
        for a, b in combinations(records, 2):
            if a.get("part_id") != b.get("part_id"):
                continue
            la, lb = a["_location"], b["_location"]
            delta = sub(lb, la)
            axial = dot(delta, pull)
            perpendicular = tuple(delta[i] - axial * pull[i] for i in range(3))
            center_distance = sqrt(dot(perpendicular, perpendicular))
            steel = center_distance - a["_width"] / 2.0 - b["_width"] / 2.0
            if steel >= minimum:
                continue
            part_id = str(a.get("part_id"))
            part = ctx.part(part_id)
            findings.append(
                ctx.finding(
                    part_refs=[part_id],
                    location=tuple((la[i] + lb[i]) / 2.0 for i in range(3)),
                    bbox=part.bbox if part else None,
                    measured_value=round(steel, 4),
                    threshold_value=minimum,
                    confidence=0.88 if all(v.get("origin") == "upstream_feature" for v in (a, b)) else 0.67,
                    face_ids=list(dict.fromkeys(feature_face_ids(a) + feature_face_ids(b))),
                    message=(
                        f"相邻{a['_kind']}与{b['_kind']}之间模具钢净厚约 {steel:.2f} mm "
                        f"< {minimum:.2f} mm"
                    ),
                    suggestion_text=(
                        f"将两特征中心距增加至少 {-steel + minimum:.2f} mm，"
                        f"或减小特征外包尺寸，使模具钢净厚达到 {minimum:.2f} mm。"
                    ),
                    suggestion_delta={
                        "min_mold_steel_thickness_mm": minimum,
                        "center_distance_delta_mm": round(max(0.0, minimum - steel), 3),
                    },
                    note="用特征中心距减两个外包宽度估算；中心可能为上游位置或圆柱轴线点",
                    extra={
                        "center_distance_mm": round(center_distance, 4),
                        "feature_a": a["_kind"],
                        "feature_b": b["_kind"],
                    },
                )
            )
        return findings


CHECKERS = [MoldWallThicknessChecker()]
