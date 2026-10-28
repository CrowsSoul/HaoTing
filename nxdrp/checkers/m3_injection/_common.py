# -*- coding: utf-8 -*-
"""M3 注塑 / 铸造检查器共用的轻量几何分析。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Iterable

from ...checkers.base import CheckContext
from ...contracts import Edge, Face, Part, Vec3
from ...geom import angle_between_deg, dot, face_radius, norm, sub


@dataclass(frozen=True)
class WallSample:
    """一个局部壁厚样本。origin 用于标识几何推断或上游特征记录。"""

    part_id: str
    thickness_mm: float
    area_mm2: float
    face_ids: tuple[str, ...]
    location: Vec3 | None
    origin: str
    adjacent_face_ids: frozenset[str] = frozenset()


def solid_parts(ctx: CheckContext) -> list[Part]:
    return [p for p in ctx.parts() if p.body_type != "sheet" and not p.is_sheet]


def meta_features(ctx: CheckContext, key: str) -> list[dict]:
    """读取 ModelBundle.meta 中可选的上游特征记录。

    约定使用 ``meta.m3_features.<key>``；字段只存在于参数口子 ``meta`` 中，
    不修改 ModelBundle 契约。没有记录时 checker 会退化为几何推断或明确跳过。
    """

    payload = ctx.model.meta.get("m3_features") or {}
    values = payload.get(key, []) if isinstance(payload, dict) else []
    if isinstance(values, dict):
        values = [values]
    return [dict(v) for v in values if isinstance(v, dict)]


def _part(ctx: CheckContext, part_id: str | None) -> Part | None:
    return ctx.part(part_id) if part_id else None


def feature_location(ctx: CheckContext, feature: dict) -> Vec3 | None:
    loc = feature.get("location")
    if isinstance(loc, (list, tuple)) and len(loc) == 3:
        try:
            return tuple(float(v) for v in loc)  # type: ignore[return-value]
        except (TypeError, ValueError):
            pass
    cogs = []
    for fid in feature.get("face_ids") or ():
        face = ctx.face(str(fid))
        if face is not None and face.cog is not None:
            cogs.append(face.cog)
    if cogs:
        return tuple(sum(p[i] for p in cogs) / len(cogs) for i in range(3))  # type: ignore[return-value]
    part = _part(ctx, feature.get("part_id"))
    return part.bbox.center if part is not None and part.bbox is not None else None


def feature_face_ids(feature: dict) -> list[str]:
    return [str(v) for v in (feature.get("face_ids") or ()) if v]


def _bbox_center(face: Face) -> Vec3 | None:
    if face.cog is not None:
        return face.cog
    if face.bbox is not None:
        return face.bbox.center
    return None


def _projected_overlap_ratio(a: Face, b: Face, normal: Vec3) -> float:
    """平行面在两个切向轴上的包围盒重叠比例。

    这是保守粗筛：用于排除明显不相邻的平行面，不宣称是真实接触面积。
    """

    if a.bbox is None or b.bbox is None:
        return 0.0
    # 法向贡献最小的两个坐标轴最接近面的切向平面。
    axes = sorted(range(3), key=lambda i: abs(normal[i]))[:2]
    amin = (a.bbox.xmin, a.bbox.ymin, a.bbox.zmin)
    amax = (a.bbox.xmax, a.bbox.ymax, a.bbox.zmax)
    bmin = (b.bbox.xmin, b.bbox.ymin, b.bbox.zmin)
    bmax = (b.bbox.xmax, b.bbox.ymax, b.bbox.zmax)
    overlap = 1.0
    for i in axes:
        span = min(amax[i], bmax[i]) - max(amin[i], bmin[i])
        ref = min(amax[i] - amin[i], bmax[i] - bmin[i])
        if span <= 0.0 or ref <= 1e-9:
            return 0.0
        overlap *= min(1.0, span / ref)
    return overlap


def inferred_wall_samples(ctx: CheckContext) -> list[WallSample]:
    """从成对、平行、投影重叠的平面估算局部壁厚。"""

    max_sample = float(ctx.param("wall_sample_max_mm"))
    min_sample = float(ctx.param("wall_sample_min_mm"))
    min_overlap = float(ctx.param("min_projected_overlap_ratio"))
    opposing_cos = float(ctx.param("opposing_normal_cos"))

    out: list[WallSample] = []
    seen: set[tuple[str, tuple[str, ...], float]] = set()
    for part in solid_parts(ctx):
        faces = [
            f
            for f in ctx.faces(part.part_id, "planar")
            if f.normal is not None and f.cog is not None
        ]
        for i, a in enumerate(faces):
            na = norm(a.normal)  # type: ignore[arg-type]
            for b in faces[i + 1 :]:
                nb = norm(b.normal)  # type: ignore[arg-type]
                if dot(na, nb) > opposing_cos:
                    continue
                overlap = _projected_overlap_ratio(a, b, na)
                if overlap < min_overlap:
                    continue
                thickness = abs(dot(sub(b.cog, a.cog), na))  # type: ignore[arg-type]
                if not (min_sample <= thickness <= max_sample):
                    continue
                key = (
                    part.part_id,
                    tuple(sorted((a.face_id, b.face_id))),
                    round(thickness, 5),
                )
                if key in seen:
                    continue
                seen.add(key)
                area = min(a.area or 0.0, b.area or 0.0)
                if area <= 0.0 and a.bbox and b.bbox:
                    area = max(1.0, min(a.bbox.diagonal, b.bbox.diagonal) ** 2 * overlap)
                out.append(
                    WallSample(
                        part_id=part.part_id,
                        thickness_mm=thickness,
                        area_mm2=area,
                        face_ids=(a.face_id, b.face_id),
                        location=tuple((a.cog[i] + b.cog[i]) / 2.0 for i in range(3)),  # type: ignore[arg-type]
                        origin="opposing_planar_faces",
                    )
                )
    return out


def wall_samples(ctx: CheckContext) -> list[WallSample]:
    """优先使用上游壁厚特征，否则执行平行面几何推断。"""

    out: list[WallSample] = []
    for rec in meta_features(ctx, "wall_samples"):
        try:
            thickness = float(rec.get("thickness_mm", rec.get("distance_mm")))
        except (TypeError, ValueError):
            continue
        if thickness <= 0.0:
            continue
        part_id = str(rec.get("part_id") or "")
        if not part_id or ctx.part(part_id) is None:
            continue
        face_ids = tuple(feature_face_ids(rec))
        adjacent = frozenset(
            str(x)
            for x in (
                rec.get("adjacent_face_ids")
                or rec.get("neighbor_face_ids")
                or ()
            )
            if x
        )
        out.append(
            WallSample(
                part_id=part_id,
                thickness_mm=thickness,
                area_mm2=max(0.0, float(rec.get("area_mm2", rec.get("area", 0.0)) or 0.0)),
                face_ids=face_ids,
                location=feature_location(ctx, rec),
                origin="upstream_feature",
                adjacent_face_ids=adjacent,
            )
        )
    return out or inferred_wall_samples(ctx)


def nominal_wall_for_part(
    ctx: CheckContext,
    part_id: str,
    samples: Iterable[WallSample],
    explicit: float | None = None,
) -> float | None:
    candidates = [s for s in samples if s.part_id == part_id and s.thickness_mm > 0.0]
    if explicit is not None and explicit > 0.0:
        return float(explicit)
    part_nominal = ctx.param("part_nominal_wall_thickness_mm", {}) or {}
    if isinstance(part_nominal, dict) and part_id in part_nominal:
        try:
            value = float(part_nominal[part_id])
            return value if value > 0.0 else None
        except (TypeError, ValueError):
            pass
    if not candidates:
        return None
    return float(median(s.thickness_mm for s in candidates))


def _material_key(material: str) -> str:
    value = material.strip().upper().replace(" ", "")
    if not value:
        return ""
    # PA66-GF30 / PA66_GF30 等牌号归一到基础材料。
    return value.replace("_", "-").split("-", 1)[0]


def material_for_part(ctx: CheckContext, part: Part) -> str:
    part_materials = ctx.param("part_materials", {}) or {}
    raw = part.material
    if not raw and isinstance(part_materials, dict):
        raw = str(part_materials.get(part.part_id, ""))
    if not raw:
        raw = str(ctx.param("material", ""))
    return _material_key(str(raw or ""))


def material_min_wall(ctx: CheckContext, material: str) -> float | None:
    mapping = ctx.param("material_min_wall_thickness_mm") or {}
    if not isinstance(mapping, dict):
        return None
    normalized = {
        _material_key(str(k)): float(v)
        for k, v in mapping.items()
        if isinstance(v, (int, float)) and float(v) > 0.0
    }
    if material in normalized:
        return normalized[material]
    return None


def edge_index(model) -> dict[frozenset[str], list[Edge]]:
    out: dict[frozenset[str], list[Edge]] = {}
    for edge in model.edges:
        if len(edge.face_ids) >= 2:
            key = frozenset(edge.face_ids[:2])
            out.setdefault(key, []).append(edge)
    return out


def edge_between(index: dict[frozenset[str], list[Edge]], a: str, b: str) -> Edge | None:
    values = index.get(frozenset((a, b)))
    return values[0] if values else None


def _axis_value(feature: dict, *names: str) -> Vec3 | None:
    for name in names:
        value = feature.get(name)
        if isinstance(value, (list, tuple)) and len(value) == 3:
            try:
                vec = norm(tuple(float(x) for x in value))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if vec != (0.0, 0.0, 0.0):
                return vec
    return None


def _infer_bosses(ctx: CheckContext) -> list[dict]:
    """从“圆柱面 + 匹配的圆形端盖”推断圆柱凸台。"""

    pull = _axis_value({"pull": ctx.param("pull_direction")}, "pull")
    if pull is None:
        return []
    axis_pull_min = float(ctx.param("boss_axis_pull_min_dot"))
    cap_normal_min = float(ctx.param("boss_cap_normal_min_dot"))
    cap_radius_tol = float(ctx.param("boss_cap_radius_tolerance_mm"))
    cap_radius_ratio = float(ctx.param("boss_cap_radius_tolerance_ratio"))
    cap_radial_tol = float(ctx.param("boss_cap_radial_tolerance_mm"))
    cap_radial_ratio = float(ctx.param("boss_cap_radial_tolerance_ratio"))
    cap_end_tol = float(ctx.param("boss_cap_end_tolerance_mm"))
    cap_end_ratio = float(ctx.param("boss_cap_end_tolerance_ratio"))
    records: list[dict] = []
    for part in solid_parts(ctx):
        planar = [f for f in ctx.faces(part.part_id, "planar") if f.normal and f.cog]
        for cyl in ctx.faces(part.part_id, "cylindrical"):
            radius = face_radius(cyl)
            if radius is None or radius <= 0.0 or cyl.axis is None or cyl.point is None:
                continue
            axis = norm(cyl.axis)
            if abs(dot(axis, pull)) < axis_pull_min:
                continue
            cap_candidates = []
            for cap in planar:
                if abs(dot(norm(cap.normal), axis)) < cap_normal_min:  # type: ignore[arg-type]
                    continue
                cap_radius = math.sqrt(max(cap.area or 0.0, 0.0) / math.pi)
                if (
                    cap_radius <= 0.0
                    or abs(cap_radius - radius)
                    > max(cap_radius_tol, radius * cap_radius_ratio)
                ):
                    continue
                delta = sub(cap.cog, cyl.point)  # type: ignore[arg-type]
                along = dot(delta, axis)
                radial = math.sqrt(max(0.0, dot(delta, delta) - along * along))
                if radial <= max(cap_radial_tol, radius * cap_radial_ratio):
                    cap_candidates.append((abs(along), along, cap, cap_radius))
            if not cap_candidates:
                continue
            _, along, cap, _ = min(cap_candidates, key=lambda x: x[0])
            height = (cyl.area or 0.0) / (2.0 * math.pi * radius)
            # 端盖必须靠近圆柱端部；否则很容易把孔口或内部台阶误认成凸台。
            if abs(abs(along) - height / 2.0) > max(cap_end_tol, height * cap_end_ratio):
                continue
            tangent_axes = sorted(range(3), key=lambda i: abs(pull[i]))[:2]
            clearances = []
            for i in tangent_axes:
                low = (part.bbox.xmin, part.bbox.ymin, part.bbox.zmin)[i]
                high = (part.bbox.xmax, part.bbox.ymax, part.bbox.zmax)[i]
                clearances.extend((cyl.point[i] - low, high - cyl.point[i]))
            side_clearance = min(clearances) - radius
            records.append(
                {
                    "part_id": part.part_id,
                    "axis": list(axis),
                    "outer_radius_mm": radius,
                    "height_mm": height,
                    "location": list(cyl.point),
                    "face_ids": [cyl.face_id, cap.face_id],
                    "side_wall_clearance_mm": max(0.0, side_clearance),
                    "origin": "cylinder_with_circular_cap",
                    "cap_along_axis": along,
                }
            )
    return records


def boss_features(ctx: CheckContext) -> list[dict]:
    records = meta_features(ctx, "bosses")
    if records:
        return records
    if not bool(ctx.param("infer_bosses_from_geometry")):
        return []
    return _infer_bosses(ctx)


def undercut_features(ctx: CheckContext) -> list[dict]:
    """倒扣必须由上游特征提供；仅凭面法向无法可靠区分倒扣与普通侧壁。"""

    return [
        rec
        for rec in meta_features(ctx, "undercuts")
        if rec.get("part_id") in ctx.model.part_map()
    ]


def pull_direction(ctx: CheckContext) -> Vec3:
    direction = _axis_value({"pull": ctx.param("pull_direction")}, "pull")
    if direction is None:
        raise ValueError("规则缺少有效的 pull_direction")
    return direction


def dihedral_angle_deg(a: Face, b: Face) -> float | None:
    if a.normal is None or b.normal is None:
        return None
    # 平面外法向夹角 α 对应实体内部二面角 180° - α。
    return 180.0 - angle_between_deg(a.normal, b.normal)


def part_face_area(ctx: CheckContext, face_ids: Iterable[str]) -> float:
    total = 0.0
    for fid in face_ids:
        face = ctx.face(str(fid))
        if face is not None:
            total += face.area or 0.0
    return total
