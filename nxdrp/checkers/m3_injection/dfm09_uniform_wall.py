# -*- coding: utf-8 -*-
"""DFM-09 均匀壁厚。"""

from __future__ import annotations

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ._rules import m3_default_params
from ._common import nominal_wall_for_part, solid_parts, wall_samples


class UniformWallThicknessChecker(BaseChecker):
    check_item_id = "DFM-09"
    name = "均匀壁厚"
    version = "0.1.0"
    owner = "M3 代世航"
    process_types = ("injection", "casting")
    requires = ("faces", "face_area")
    default_params = m3_default_params("DFM-09")

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        low = float(ctx.param("uniform_ratio_low"))
        high = float(ctx.param("uniform_ratio_high"))
        max_ratio = float(ctx.param("max_area_ratio"))
        min_samples = max(1, int(ctx.param("min_samples_for_uniformity")))
        explicit = ctx.param("nominal_wall_thickness_mm")
        if explicit is not None:
            try:
                explicit = float(explicit)
            except (TypeError, ValueError):
                explicit = None

        samples = wall_samples(ctx)
        findings: list[Finding] = []
        for part in solid_parts(ctx):
            candidates = [s for s in samples if s.part_id == part.part_id]
            nominal = nominal_wall_for_part(ctx, part.part_id, candidates, explicit)
            if nominal is None or nominal <= 0.0 or len(candidates) < min_samples:
                continue
            total_area = sum(max(s.area_mm2, 1e-6) for s in candidates)
            bad = []
            for sample in candidates:
                ratio = sample.thickness_mm / nominal
                if ratio < low or ratio > high:
                    bad.append((sample, ratio))
            if not bad:
                continue
            bad_area = sum(max(s.area_mm2, 1e-6) for s, _ in bad)
            area_ratio = bad_area / total_area
            if area_ratio <= max_ratio:
                continue
            worst, worst_ratio = max(bad, key=lambda item: abs(item[1] - 1.0))
            findings.append(
                ctx.finding(
                    part_refs=[part.part_id],
                    location=worst.location,
                    bbox=part.bbox,
                    measured_value=round(area_ratio * 100.0, 3),
                    threshold_value=round(max_ratio * 100.0, 3),
                    unit="%",
                    confidence=0.78 if worst.origin == "opposing_planar_faces" else 0.92,
                    face_ids=[fid for s, _ in bad for fid in s.face_ids][:24],
                    message=(
                        f"{part.name or part.part_id} 有 {area_ratio * 100:.1f}% 的壁厚样本"
                        f"超出名义壁厚 {nominal:.2f} mm 的 [{low:.2f}, {high:.2f}] 倍范围；"
                        f"最不利位置为 {worst_ratio:.2f} 倍"
                    ),
                    suggestion_text=(
                        f"将偏离区域的壁厚调整到 {nominal * low:.2f}–{nominal * high:.2f} mm，"
                        f"并把厚度突变改为渐变或圆角过渡。"
                    ),
                    suggestion_delta={
                        "nominal_wall_thickness_mm": round(nominal, 3),
                        "ratio_low": low,
                        "ratio_high": high,
                    },
                    note=(
                        "按局部壁厚样本面积统计；名义壁厚取上游值或面积样本中位数"
                    ),
                    extra={
                        "nominal_wall_thickness_mm": round(nominal, 3),
                        "worst_ratio": round(worst_ratio, 4),
                        "bad_sample_count": len(bad),
                        "sample_count": len(candidates),
                        "method": worst.origin,
                    },
                )
            )
        return findings


CHECKERS = [UniformWallThicknessChecker()]
