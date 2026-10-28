# -*- coding: utf-8 -*-
"""DFM-16 圆角半径。"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ...geom import face_radius
from ._rules import m3_default_params
from ._common import (
    feature_face_ids,
    feature_location,
    meta_features,
    nominal_wall_for_part,
    solid_parts,
    wall_samples,
)


class FilletRadiusChecker(BaseChecker):
    check_item_id = "DFM-16"
    name = "圆角半径"
    version = "0.1.0"
    owner = "M3 代世航"
    process_types = ("injection", "casting")
    requires = ("faces",)
    default_params = m3_default_params("DFM-16")

    def _inferred_fillets(self, ctx: CheckContext) -> list[dict]:
        samples = wall_samples(ctx)
        records = []
        for part in solid_parts(ctx):
            nominal = nominal_wall_for_part(
                ctx,
                part.part_id,
                samples,
                ctx.param("nominal_wall_thickness_mm"),
            )
            for face in ctx.faces(part.part_id, "toroidal"):
                radius = face_radius(face)
                if radius is None or nominal is None:
                    continue
                records.append(
                    {
                        "part_id": part.part_id,
                        "kind": "inner",
                        "radius_mm": radius,
                        "nominal_wall_mm": nominal,
                        "face_ids": [face.face_id],
                        "location": list(face.cog) if face.cog else None,
                        "origin": "toroidal_face_inference",
                    }
                )
        return records

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        records = meta_features(ctx, "corners") or self._inferred_fillets(ctx)
        samples = wall_samples(ctx)
        inner_ratio = float(ctx.param("inner_radius_ratio"))
        outer_ratio = float(ctx.param("outer_radius_ratio"))
        findings: list[Finding] = []
        for rec in records:
            part_id = str(rec.get("part_id") or "")
            part = ctx.part(part_id)
            if part is None:
                continue
            kind = str(rec.get("kind") or "inner").lower()
            ratio = outer_ratio if kind in ("outer", "convex") else inner_ratio
            nominal = rec.get("nominal_wall_mm")
            if nominal is None:
                nominal = nominal_wall_for_part(
                    ctx,
                    part_id,
                    samples,
                    ctx.param("nominal_wall_thickness_mm"),
                )
            if nominal is None:
                continue
            try:
                nominal_val = float(nominal)
            except (TypeError, ValueError):
                continue
            minimum = nominal_val * ratio
            radius = rec.get("radius_mm", rec.get("radius"))
            if radius is None:
                measured, message = 0.0, f"{'内' if kind == 'inner' else '外'}角缺少圆角"
            else:
                try:
                    measured = float(radius)
                except (TypeError, ValueError):
                    continue
                if measured >= minimum:
                    continue
                message = (
                    f"{'内' if kind == 'inner' else '外'}圆角 R{measured:.2f} "
                    f"< 要求 R{minimum:.2f}（{ratio:.2f} × 壁厚 {nominal_val:.2f}）"
                )
            origin = str(rec.get("origin") or "upstream_feature")
            findings.append(
                ctx.finding(
                    part_refs=[part_id],
                    location=feature_location(ctx, rec),
                    bbox=part.bbox,
                    measured_value=round(measured, 4),
                    threshold_value=round(minimum, 4),
                    confidence=0.9 if origin == "upstream_feature" else 0.63,
                    face_ids=feature_face_ids(rec),
                    message=message,
                    suggestion_text=(
                        f"将该角圆角增大到至少 R{minimum:.2f}，"
                        "并让圆角与相邻壁厚平滑过渡。"
                    ),
                    suggestion_delta={"target_fillet_radius_mm": round(minimum, 3)},
                    note=(
                        "来自上游圆角特征"
                        if origin == "upstream_feature"
                        else "环面只能证明存在圆角；按内圆角阈值粗筛，内外角归属需截面确认"
                    ),
                    extra={"fillet_kind": kind, "method": origin},
                )
            )
        return findings


CHECKERS = [FilletRadiusChecker()]
