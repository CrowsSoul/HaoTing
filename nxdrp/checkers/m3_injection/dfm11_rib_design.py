# -*- coding: utf-8 -*-
"""DFM-11 加强筋设计。"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ._rules import m3_default_params
from ._common import (
    feature_face_ids,
    feature_location,
    meta_features,
    nominal_wall_for_part,
    wall_samples,
)


class RibDesignChecker(BaseChecker):
    check_item_id = "DFM-11"
    name = "加强筋设计"
    version = "0.1.0"
    owner = "M3 代世航"
    process_types = ("injection", "casting")
    requires = ("faces",)
    default_params = m3_default_params("DFM-11")

    def _inferred_ribs(self, ctx: CheckContext) -> list[dict]:
        samples = wall_samples(ctx)
        min_samples = max(1, int(ctx.param("min_samples_for_rib_inference")))
        if len(samples) < min_samples:
            return []
        inferred_ratio = float(ctx.param("max_rib_root_to_wall_ratio"))
        dimension_ratio = float(ctx.param("inferred_rib_dimension_ratio"))
        dimension_min = float(ctx.param("inferred_rib_dimension_min_mm"))
        inferred = []
        for sample in samples:
            if not sample.face_ids:
                continue
            nominal = nominal_wall_for_part(
                ctx,
                sample.part_id,
                samples,
                ctx.param("nominal_wall_thickness_mm"),
            )
            if nominal is None or sample.thickness_mm >= nominal * inferred_ratio:
                continue
            faces = [ctx.face(fid) for fid in sample.face_ids]
            faces = [f for f in faces if f is not None and f.bbox is not None]
            if not faces:
                continue
            dims = [
                v
                for f in faces
                for v in f.bbox.size  # type: ignore[union-attr]
                if v > max(sample.thickness_mm * dimension_ratio, dimension_min)
            ]
            if not dims:
                continue
            inferred.append(
                {
                    "part_id": sample.part_id,
                    "root_thickness_mm": sample.thickness_mm,
                    "height_mm": max(dims),
                    "face_ids": list(sample.face_ids),
                    "location": list(sample.location) if sample.location else None,
                    "origin": "slender_wall_inference",
                }
            )
        return inferred

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        records = meta_features(ctx, "ribs") or self._inferred_ribs(ctx)
        max_root_ratio = float(ctx.param("max_rib_root_to_wall_ratio"))
        max_height_ratio = float(ctx.param("max_rib_height_to_root_ratio"))
        samples = wall_samples(ctx)
        findings: list[Finding] = []
        for rib in records:
            part_id = str(rib.get("part_id") or "")
            if not part_id:
                continue
            try:
                root = float(rib.get("root_thickness_mm"))
                height = float(rib.get("height_mm"))
            except (TypeError, ValueError):
                continue
            if root <= 0.0 or height <= 0.0:
                continue
            nominal = nominal_wall_for_part(
                ctx,
                part_id,
                samples,
                ctx.param("nominal_wall_thickness_mm"),
            )
            root_ratio = root / nominal if nominal and nominal > 0.0 else None
            height_ratio = height / root
            root_bad = root_ratio is not None and root_ratio > max_root_ratio
            height_bad = height_ratio > max_height_ratio
            if not (root_bad or height_bad):
                continue
            if root_bad and height_bad:
                message = (
                    f"筋根厚/壁厚 {root_ratio:.2f} > {max_root_ratio:.2f}，"
                    f"筋高/根厚 {height_ratio:.2f} > {max_height_ratio:.1f}"
                )
            elif root_bad:
                message = (
                    f"筋根厚 {root:.2f} mm 为名义壁厚 {nominal:.2f} mm 的 "
                    f"{root_ratio:.2f} 倍，超过 {max_root_ratio:.2f}"
                )
            else:
                message = (
                    f"筋高/根厚 {height_ratio:.2f} 超过 {max_height_ratio:.1f}，"
                    f"根部填充与顶出风险高"
                )
            target_root = nominal * max_root_ratio if nominal else root
            origin = str(rib.get("origin") or "upstream_feature")
            part = ctx.part(part_id)
            findings.append(
                ctx.finding(
                    part_refs=[part_id],
                    location=feature_location(ctx, rib),
                    bbox=part.bbox if part else None,
                    measured_value=round(root_ratio if root_bad else height_ratio, 4),
                    threshold_value=max_root_ratio if root_bad else max_height_ratio,
                    confidence=0.9 if origin == "upstream_feature" else 0.62,
                    face_ids=feature_face_ids(rib),
                    message=message,
                    suggestion_text=(
                        f"把筋根厚控制在 {target_root:.2f} mm 以内，"
                        f"必要时增加筋数量或缩短筋高至根厚的 {max_height_ratio:.0f} 倍以内。"
                    ),
                    suggestion_delta={
                        "max_root_thickness_mm": round(target_root, 3),
                        "max_height_mm": round(max(target_root, 0.1) * max_height_ratio, 3),
                    },
                    note=(
                        "使用上游筋特征"
                        if origin == "upstream_feature"
                        else "由细长壁厚样本推断，需在截面上确认是否为加强筋"
                    ),
                    extra={
                        "root_thickness_mm": round(root, 4),
                        "height_mm": round(height, 4),
                        "nominal_wall_mm": round(nominal, 4) if nominal else None,
                        "method": origin,
                    },
                )
            )
        return findings


CHECKERS = [RibDesignChecker()]
