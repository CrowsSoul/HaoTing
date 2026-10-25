# -*- coding: utf-8 -*-
"""M4 装配 DFM 的公共特征解析与几何工具。

装配专有语义（紧固件、配对孔、槽）不在 ModelBundle 的一级字段中。为了不改
公共契约，本模块只读取 ``model.meta["assembly_features"]`` 中的可选标注；
没有可靠数据时由 checker 明确跳过，绝不根据名字硬猜并产出高置信度结论。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Iterable

from ...contracts import BBox, Face, ModelBundle, Vec3
from ...geom import bbox_gap, cross, dot, face_axis, face_radius, length, norm, scale, sub

EPS = 1e-9


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def vec3(value: Any) -> Vec3 | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    values = [number(v) for v in value]
    if any(v is None for v in values):
        return None
    return (float(values[0]), float(values[1]), float(values[2]))


def feature_rows(model: ModelBundle, key: str) -> list[dict]:
    root = model.meta.get("assembly_features", {}) if isinstance(model.meta, dict) else {}
    rows = root.get(key, []) if isinstance(root, dict) else []
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def intersection_box(a: BBox | None, b: BBox | None) -> BBox | None:
    if a is None or b is None:
        return None
    box = BBox(
        max(a.xmin, b.xmin), max(a.ymin, b.ymin), max(a.zmin, b.zmin),
        min(a.xmax, b.xmax), min(a.ymax, b.ymax), min(a.zmax, b.zmax),
    )
    return box if box.is_valid() else None


def bbox_volume(box: BBox | None) -> float:
    if box is None:
        return 0.0
    sx, sy, sz = box.size
    return max(0.0, sx) * max(0.0, sy) * max(0.0, sz)


def overlap_extents(a: BBox | None, b: BBox | None) -> tuple[float, float, float]:
    box = intersection_box(a, b)
    if box is None:
        return (0.0, 0.0, 0.0)
    return tuple(max(0.0, x) for x in box.size)


def face_point(face: Face) -> Vec3 | None:
    return face.point or face.cog or (face.bbox.center if face.bbox else None)


def radial_offset(a: Vec3, b: Vec3, axis: Vec3) -> float:
    unit = norm(axis)
    delta = sub(a, b)
    return length(sub(delta, scale(unit, dot(delta, unit))))


def unsigned_axis_angle_deg(a: Vec3, b: Vec3) -> float:
    na, nb = norm(a), norm(b)
    cosine = max(-1.0, min(1.0, abs(dot(na, nb))))
    return math.degrees(math.acos(cosine))


def line_distance(p1: Vec3, d1: Vec3, p2: Vec3, d2: Vec3) -> float | None:
    d1, d2 = norm(d1), norm(d2)
    if length(d1) <= EPS or length(d2) <= EPS:
        return None
    normal = cross(d1, d2)
    if length(normal) <= 1e-6:
        return radial_offset(p1, p2, d1)
    return abs(dot(sub(p2, p1), norm(normal)))


def valid_face_ids(model: ModelBundle, values: Iterable[Any]) -> list[str]:
    known = model.face_map()
    out: list[str] = []
    for value in values:
        value = str(value)
        if value in known and value not in out:
            out.append(value)
    return out


def trace_location(model: ModelBundle, face_ids: Iterable[str],
                   preferred: Vec3 | None = None) -> tuple[Vec3 | None, BBox | None]:
    """用语义位置或首个证据面补齐 Finding 的 3D 定位信息。"""
    face_map = model.face_map()
    for face_id in face_ids:
        face = face_map.get(face_id)
        if face is None:
            continue
        location = preferred or face.cog or (face.bbox.center if face.bbox else None)
        return location, face.bbox
    return preferred, None


def nearest_face_pair(model: ModelBundle, part_a: str, part_b: str) -> tuple[Face, Face] | None:
    faces_a = [f for f in model.faces_of(part_a) if f.bbox is not None]
    faces_b = [f for f in model.faces_of(part_b) if f.bbox is not None]
    if not faces_a or not faces_b:
        return None
    return min(
        ((a, b) for a in faces_a for b in faces_b),
        key=lambda pair: (bbox_gap(pair[0].bbox, pair[1].bbox), pair[0].face_id, pair[1].face_id),
    )


def candidate_face_pairs(model: ModelBundle, part_a: str, part_b: str,
                         max_gap: float) -> list[tuple[Face, Face]]:
    """返回可能小于阈值的全部面配对，供一次性 NX 精确测距。

    面包围盒距离只是下界，因此不能只测“最接近”的一个面配对；所有下界不大于
    阈值的配对都必须送入同一批 NX 测量，再从精确结果中取最小值。
    """
    faces_a = [face for face in model.faces_of(part_a) if face.bbox is not None]
    faces_b = [face for face in model.faces_of(part_b) if face.bbox is not None]
    pairs = [
        (a, b)
        for a in faces_a
        for b in faces_b
        if bbox_gap(a.bbox, b.bbox) <= max_gap + EPS
    ]
    return sorted(
        pairs,
        key=lambda pair: (
            bbox_gap(pair[0].bbox, pair[1].bbox),
            pair[0].face_id,
            pair[1].face_id,
        ),
    )


def faces_near_box(model: ModelBundle, part_ids: Iterable[str], box: BBox | None,
                   min_area: float = 0.0) -> list[str]:
    selected: list[tuple[float, str]] = []
    for part_id in part_ids:
        candidates = []
        for face in model.faces_of(part_id):
            if face.bbox is None or (face.area is not None and face.area < min_area):
                continue
            gap = bbox_gap(face.bbox, box) if box is not None else 0.0
            candidates.append((gap, face.face_id))
        if candidates:
            best = min(g for g, _ in candidates)
            selected.extend(row for row in candidates if row[0] <= best + 1e-6)
    return [fid for _, fid in sorted(selected)[:8]]


@dataclass
class HoleFeature:
    feature_id: str
    part_id: str
    center: Vec3
    axis: Vec3
    diameter: float
    face_ids: list[str] = field(default_factory=list)
    mate_id: str = ""
    confidence: float = 0.45
    source: str = "geometry"


@dataclass
class SlotFeature:
    feature_id: str
    part_id: str
    center: Vec3
    axis: Vec3
    width: float
    face_ids: list[str] = field(default_factory=list)
    mate_id: str = ""
    confidence: float = 0.95


@dataclass
class FastenerFeature:
    feature_id: str
    part_id: str
    face_ids: list[str]
    axis: Vec3 | None = None
    head_center: Vec3 | None = None
    nominal_diameter_mm: float | None = None
    engagement_length_mm: float | None = None
    material: str = "steel"
    available_tool_diameter_mm: float | None = None
    available_tool_height_mm: float | None = None
    radial_clearance_mm: float | None = None
    axial_clearance_mm: float | None = None
    accessible: bool | None = None
    blocking_part_ids: list[str] = field(default_factory=list)


def _metadata_holes(model: ModelBundle) -> list[HoleFeature]:
    out: list[HoleFeature] = []
    for index, row in enumerate(feature_rows(model, "holes"), 1):
        center, axis = vec3(row.get("center")), vec3(row.get("axis"))
        diameter = number(row.get("diameter_mm"))
        part_id = str(row.get("part_id", ""))
        face_ids = valid_face_ids(model, row.get("face_ids", []))
        if not part_id or center is None or axis is None or not diameter or diameter <= 0 or not face_ids:
            continue
        out.append(HoleFeature(
            feature_id=str(row.get("feature_id") or f"hole-{index}"), part_id=part_id,
            center=center, axis=norm(axis), diameter=diameter, face_ids=face_ids,
            mate_id=str(row.get("mate_id", "")), confidence=0.98, source="metadata",
        ))
    return out


def _geometry_holes(model: ModelBundle) -> list[HoleFeature]:
    raw: list[HoleFeature] = []
    for face in model.faces:
        # UF 面类型是 NX 的稳定几何语义；旧版 JSON 的 SolidFaceType 数值映射曾
        # 把 UF16 平面写成 cylindrical。存在 UF 数据时必须以 UF17 为准。
        if face.uf_face_type:
            if face.uf_face_type != 17:
                continue
        elif face.solid_face_type != "cylindrical":
            continue
        axis, radius, center = face_axis(face), face_radius(face), face_point(face)
        if axis is None or radius is None or radius <= EPS or center is None:
            continue
        raw.append(HoleFeature(
            feature_id=face.face_id, part_id=face.part_id, center=center, axis=axis,
            diameter=2.0 * radius, face_ids=[face.face_id], confidence=0.4,
        ))

    grouped: list[HoleFeature] = []
    for candidate in raw:
        match = None
        for existing in grouped:
            if existing.part_id != candidate.part_id:
                continue
            if unsigned_axis_angle_deg(existing.axis, candidate.axis) > 1.0:
                continue
            if radial_offset(existing.center, candidate.center, existing.axis) > max(0.1, 0.02 * existing.diameter):
                continue
            match = existing
            break
        if match is None:
            grouped.append(candidate)
        else:
            match.face_ids.extend(fid for fid in candidate.face_ids if fid not in match.face_ids)
            # 阶梯孔用最小直径作为配合孔径，避免沉孔直径造成假不匹配。
            match.diameter = min(match.diameter, candidate.diameter)
    return grouped


def extract_holes(model: ModelBundle) -> list[HoleFeature]:
    annotated = _metadata_holes(model)
    return annotated if annotated else _geometry_holes(model)


def extract_slots(model: ModelBundle) -> list[SlotFeature]:
    out: list[SlotFeature] = []
    for index, row in enumerate(feature_rows(model, "slots"), 1):
        center, axis = vec3(row.get("center")), vec3(row.get("axis"))
        width = number(row.get("width_mm"))
        part_id = str(row.get("part_id", ""))
        face_ids = valid_face_ids(model, row.get("face_ids", []))
        if not part_id or center is None or axis is None or not width or width <= 0 or not face_ids:
            continue
        out.append(SlotFeature(
            feature_id=str(row.get("feature_id") or f"slot-{index}"), part_id=part_id,
            center=center, axis=norm(axis), width=width, face_ids=face_ids,
            mate_id=str(row.get("mate_id", "")),
        ))
    return out


def extract_fasteners(model: ModelBundle) -> list[FastenerFeature]:
    out: list[FastenerFeature] = []
    for index, row in enumerate(feature_rows(model, "fasteners"), 1):
        face_ids = valid_face_ids(model, row.get("face_ids", []))
        part_id = str(row.get("part_id", ""))
        if not part_id or not face_ids:
            continue
        accessible = row.get("accessible")
        if not isinstance(accessible, bool):
            accessible = None
        out.append(FastenerFeature(
            feature_id=str(row.get("feature_id") or f"fastener-{index}"),
            part_id=part_id, face_ids=face_ids, axis=vec3(row.get("axis")),
            head_center=vec3(row.get("head_center")),
            nominal_diameter_mm=number(row.get("nominal_diameter_mm")),
            engagement_length_mm=number(row.get("engagement_length_mm")),
            material=str(row.get("material") or "steel"),
            available_tool_diameter_mm=number(row.get("available_tool_diameter_mm")),
            available_tool_height_mm=number(row.get("available_tool_height_mm")),
            radial_clearance_mm=number(row.get("radial_clearance_mm")),
            axial_clearance_mm=number(row.get("axial_clearance_mm")),
            accessible=accessible,
            blocking_part_ids=[str(x) for x in row.get("blocking_part_ids", [])],
        ))
    return out


def pair_holes(holes: list[HoleFeature], search_radius: float,
               angle_tolerance_deg: float) -> list[tuple[HoleFeature, HoleFeature]]:
    candidates: list[tuple[float, HoleFeature, HoleFeature]] = []
    for a, b in combinations(holes, 2):
        if a.part_id == b.part_id:
            continue
        if a.mate_id or b.mate_id:
            if not a.mate_id or a.mate_id != b.mate_id:
                continue
        angle = unsigned_axis_angle_deg(a.axis, b.axis)
        distance = line_distance(a.center, a.axis, b.center, b.axis)
        if distance is None or distance > search_radius or angle > angle_tolerance_deg:
            continue
        candidates.append((distance + angle * 0.01, a, b))

    used: set[str] = set()
    out: list[tuple[HoleFeature, HoleFeature]] = []
    for _, a, b in sorted(candidates, key=lambda row: (row[0], row[1].feature_id, row[2].feature_id)):
        keys = {f"{a.part_id}:{a.feature_id}", f"{b.part_id}:{b.feature_id}"}
        if used & keys:
            continue
        used.update(keys)
        out.append((a, b))
    return out


def pair_holes_slots(holes: list[HoleFeature], slots: list[SlotFeature], search_radius: float,
                     angle_tolerance_deg: float) -> list[tuple[HoleFeature, SlotFeature]]:
    candidates: list[tuple[float, HoleFeature, SlotFeature]] = []
    for hole in holes:
        for slot in slots:
            if hole.part_id == slot.part_id:
                continue
            if hole.mate_id or slot.mate_id:
                if not hole.mate_id or hole.mate_id != slot.mate_id:
                    continue
            angle = unsigned_axis_angle_deg(hole.axis, slot.axis)
            offset = radial_offset(hole.center, slot.center, slot.axis)
            if offset <= search_radius and angle <= angle_tolerance_deg:
                candidates.append((offset + angle * 0.01, hole, slot))

    used_holes: set[str] = set()
    used_slots: set[str] = set()
    out: list[tuple[HoleFeature, SlotFeature]] = []
    for _, hole, slot in sorted(candidates, key=lambda row: (row[0], row[1].feature_id, row[2].feature_id)):
        hk, sk = f"{hole.part_id}:{hole.feature_id}", f"{slot.part_id}:{slot.feature_id}"
        if hk in used_holes or sk in used_slots:
            continue
        used_holes.add(hk)
        used_slots.add(sk)
        out.append((hole, slot))
    return out
