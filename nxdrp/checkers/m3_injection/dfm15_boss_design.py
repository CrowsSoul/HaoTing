# -*- coding: utf-8 -*-
"""DFM-15 凸台设计。"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ._rules import m3_default_params
from ._common import boss_features, feature_face_ids, feature_location, nominal_wall_for_part, wall_samples


class BossDesignChecker(BaseChecker):
    check_item_id = "DFM-15"
    name = "凸台设计"
    version = "0.1.0"
    owner = "M3 代世航"
    process_types = ("injection", "casting")
    requires = ("faces",)
    default_params = m3_default_params("DFM-15")

    @staticmethod
    def _boss_wall(record: dict, nominal: float | None) -> tuple[float | None, str]:
        for key in ("wall_thickness_mm", "boss_wall_thickness_mm"):
            if record.get(key) is not None:
                try:
                    return float(record[key]), key
                except (TypeError, ValueError):
                    pass
        inner = record.get("inner_radius_mm")
        outer = record.get("outer_radius_mm")
        if inner is not None and outer is not None:
            try:
                return max(0.0, float(outer) - float(inner)), "outer_minus_inner_radius"
            except (TypeError, ValueError):
                pass
        return nominal, "nominal_wall"

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        records = boss_features(ctx)
        if not records:
            return []
        samples = wall_samples(ctx)
        findings: list[Finding] = []
        for rec in records:
            part_id = str(rec.get("part_id") or "")
            part = ctx.part(part_id)
            if part is None:
                continue
            nominal = nominal_wall_for_part(
                ctx,
                part_id,
                samples,
                ctx.param("nominal_wall_thickness_mm"),
            )
            wall, wall_source = self._boss_wall(rec, nominal)
            issues = []

            min_wall = float(ctx.param("min_boss_wall_thickness_mm"))
            if wall is not None and wall < min_wall:
                issues.append(("boss_wall", wall, min_wall, "凸台壁厚"))

            top = rec.get("top_thickness_mm")
            min_top = float(ctx.param("min_top_thickness_mm"))
            if top is not None:
                try:
                    top_val = float(top)
                    if top_val < min_top:
                        issues.append(("top_thickness", top_val, min_top, "凸台顶厚"))
                except (TypeError, ValueError):
                    pass

            root = rec.get("root_fillet_radius_mm", rec.get("root_radius_mm"))
            min_root_ratio = float(ctx.param("min_root_fillet_to_wall_ratio"))
            if root is not None and wall is not None:
                try:
                    root_val = float(root)
                    root_min = wall * min_root_ratio
                    if root_val < root_min:
                        issues.append(("root_fillet", root_val, root_min, "凸台根部圆角"))
                except (TypeError, ValueError):
                    pass

            clearance = rec.get("side_wall_clearance_mm")
            min_clearance = float(ctx.param("min_side_wall_clearance_mm"))
            if clearance is not None:
                try:
                    clear_val = float(clearance)
                    if clear_val < min_clearance:
                        issues.append(("side_clearance", clear_val, min_clearance, "凸台到侧壁距离"))
                except (TypeError, ValueError):
                    pass

            if not issues:
                continue
            kind, measured, threshold, label = min(issues, key=lambda v: v[1] / max(v[2], 1e-9))
            origin = str(rec.get("origin") or "upstream_feature")
            findings.append(
                ctx.finding(
                    part_refs=[part_id],
                    location=feature_location(ctx, rec),
                    bbox=part.bbox,
                    measured_value=round(float(measured), 4),
                    threshold_value=round(float(threshold), 4),
                    confidence=0.9 if origin == "upstream_feature" else 0.66,
                    face_ids=feature_face_ids(rec),
                    message=(
                        f"{label} {float(measured):.2f} mm < 要求 {float(threshold):.2f} mm"
                    ),
                    suggestion_text=(
                        f"将{label}增加到至少 {float(threshold):.2f} mm；"
                        "凸台与主壁同厚过近时，改用减胶槽或加强筋连接。"
                    ),
                    suggestion_delta={"target_value_mm": round(float(threshold), 3)},
                    note=(
                        "来自上游凸台特征"
                        if origin == "upstream_feature"
                        else "由圆柱面与圆形端盖推断凸台，建议用截面确认是否空心"
                    ),
                    extra={
                        "issue": kind,
                        "wall_thickness_source": wall_source,
                        "all_issues": [
                            {"kind": k, "measured_mm": round(v, 3), "threshold_mm": round(t, 3)}
                            for k, v, t, _ in issues
                        ],
                        "method": origin,
                    },
                )
            )
        return findings


CHECKERS = [BossDesignChecker()]
