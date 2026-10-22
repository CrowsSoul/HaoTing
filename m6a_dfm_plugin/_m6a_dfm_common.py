# -*- coding: utf-8 -*-
"""M6A 钣金 DFM 插件的公共几何工具。

数据契约里没有料厚、弯曲线、翻边、凸台、槽等钣金专有字段，因此本模块
全部采用低置信度的几何粗筛。结果只用于跑通流程，必须人工复核。

设计约定：
  * 文件名以 ``_`` 开头，registry 不会把它当 checker 加载；
  * checker 通过 ``from _m6a_dfm_common import ...`` 平铺导入；
  * 所有几何字段先判空，拿不到就跳过，不产出看似精确的假结果。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations

from nxdrp.checkers.base import BaseChecker
from nxdrp.contracts import BBox, Face, ModelBundle, Part, Vec3
from nxdrp.geom import (
    bbox_extent_along,
    cross,
    dist,
    dot,
    face_axis,
    face_normal,
    face_radius,
    length,
    norm,
    scale,
    sub,
)

#: 两个方向视为平行 / 垂直的判定阈值（夹角的余弦绝对值）
PARALLEL_DOT = 0.98
PERPENDICULAR_DOT = 0.2
_EPS = 1e-9


# --------------------------------------------------------------------------
# 特征结构
# --------------------------------------------------------------------------
@dataclass
class Thickness:
    """某个零件的料厚估计。"""

    value: float | None = None
    source: str = "unknown"          # rule / 2V/A / bbox_min / unknown
    confidence: float = 0.0          # 0.9 / 0.4 / 0.2 / 0.0


@dataclass
class HoleFeature:
    """同轴孔组：把沉孔/阶梯孔的多段圆柱合并为一个孔。"""

    part_id: str
    center: Vec3
    axis: Vec3
    r_min: float
    r_max: float
    face_ids: list[str] = field(default_factory=list)
    confidence: float = 0.45


@dataclass
class BendFeature:
    """折弯候选：与至少两个互不平行的平面相邻的圆柱面。"""

    part_id: str
    face: Face
    radius: float
    axis: Vec3
    point: Vec3
    legs: list[Face] = field(default_factory=list)
    confidence: float = 0.45


@dataclass
class BossFeature:
    """冲压凸台候选：端部有小面积端盖、且与轴向平行的圆柱面。"""

    part_id: str
    face: Face
    radius: float
    axis: Vec3
    height: float
    confidence: float = 0.5


@dataclass
class SlotFeature:
    """直槽候选：两块互相对置、位于零件内部的平面壁，且有共同槽底。"""

    part_id: str
    width: float
    normal: Vec3
    location: Vec3
    face_ids: list[str] = field(default_factory=list)
    confidence: float = 0.45


@dataclass
class Features:
    """一次模型解析出来的全部粗筛特征。"""

    thickness: dict[str, Thickness] = field(default_factory=dict)
    holes: list[HoleFeature] = field(default_factory=list)
    bends: list[BendFeature] = field(default_factory=list)
    bosses: list[BossFeature] = field(default_factory=list)
    slots: list[SlotFeature] = field(default_factory=list)


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def positive_number(value) -> float | None:
    """把参数转成正数；None / 非数值 / 非正数一律返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def face_point(face: Face) -> Vec3 | None:
    """取一个可用于定位的点：优先 value.point，其次重心，最后包围盒中心。"""
    if face.point is not None:
        return face.point
    if face.cog is not None:
        return face.cog
    if face.bbox is not None:
        return face.bbox.center
    return None


def _is_cylinder(face: Face) -> bool:
    if face.solid_face_type == "cylindrical":
        return True
    # 某些数据源不给 solid_face_type，但保留 NX 的 UF 面类型（17 = 圆柱）
    return (
        face.uf_face_type == 17
        and face.axis is not None
        and face.radius_diameter is not None
        and face.normal is None
    )


def adjacency_map(model: ModelBundle) -> dict[str, set[str]]:
    """合并 model.adjacency 与 edge.face_ids，得到对称的邻接表。"""
    out: dict[str, set[str]] = {}

    def link(a: str, b: str) -> None:
        if a == b:
            return
        out.setdefault(a, set()).add(b)
        out.setdefault(b, set()).add(a)

    for a, b in model.adjacency:
        link(a, b)
    for edge in model.edges:
        ids = [fid for fid in edge.face_ids if fid]
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                link(ids[i], ids[j])
    return out


def in_plane_axes(axis: Vec3) -> tuple[int, int]:
    """选两个与给定轴最不平行的全局坐标轴，作为“板面内”方向。"""
    comps = [abs(c) for c in norm(axis)]
    order = sorted(range(3), key=lambda i: comps[i])
    return order[0], order[1]


def line_line_distance(p1: Vec3, d1: Vec3, p2: Vec3, d2: Vec3) -> float | None:
    """两条直线的公垂线距离；平行时退化为点到直线距离。"""
    d1n, d2n = norm(d1), norm(d2)
    if length(d1n) <= _EPS or length(d2n) <= _EPS:
        return None
    c = cross(d1n, d2n)
    if length(c) <= 1e-6:
        return length(cross(sub(p2, p1), d1n))
    return abs(dot(sub(p2, p1), norm(c)))


def thickness_text(thickness: Thickness) -> str:
    if thickness.value is None:
        return "t=未知"
    return f"t≈{thickness.value:.3f} mm（{thickness.source}，置信度 {thickness.confidence:.2f}）"


# --------------------------------------------------------------------------
# 料厚
# --------------------------------------------------------------------------
def resolve_thickness(part: Part, params: dict | None = None) -> Thickness:
    """料厚优先级：规则显式值 > 2V/A > 最小包围盒尺寸。"""
    explicit = positive_number((params or {}).get("sheet_thickness_mm"))
    if explicit is not None:
        return Thickness(explicit, "rule", 0.9)

    bbox = part.bbox
    min_dim = min(bbox.size) if bbox is not None else None
    if min_dim is not None and min_dim <= _EPS:
        min_dim = None

    volume = positive_number(part.volume)
    area = positive_number(part.area)
    if volume is not None and area is not None:
        estimate = 2.0 * volume / area
        if estimate > _EPS and (min_dim is None or estimate <= 1.5 * min_dim):
            return Thickness(estimate, "2V/A", 0.4)

    if min_dim is not None:
        return Thickness(min_dim, "bbox_min", 0.2)
    return Thickness(None, "unknown", 0.0)


# --------------------------------------------------------------------------
# 特征提取
# --------------------------------------------------------------------------
def _nonparallel_count(normals: list[Vec3 | None]) -> int:
    reps: list[Vec3] = []
    for n in normals:
        if n is None:
            continue
        if not any(abs(dot(n, r)) >= PARALLEL_DOT for r in reps):
            reps.append(n)
    return len(reps)


@dataclass
class _CylinderClass:
    kind: str                        # bend / boss / hole
    confidence: float = 0.45
    legs: list[Face] = field(default_factory=list)
    height: float | None = None


def _classify_cylinder(
    face: Face,
    part: Part,
    planes_by_id: dict[str, Face],
    adj: dict[str, set[str]],
    thickness_value: float | None,
) -> _CylinderClass:
    axis = face_axis(face)
    radius = face_radius(face)
    if axis is None or radius is None or radius <= _EPS:
        return _CylinderClass("hole", 0.2)

    planar_neighbors: list[Face] = []
    for fid in adj.get(face.face_id, ()):
        candidate = planes_by_id.get(fid)
        if candidate is not None:
            planar_neighbors.append(candidate)

    # 凸台：端部有与轴平行、面积和圆柱截面积同量级的端盖
    for plane in planar_neighbors:
        n = face_normal(plane)
        if n is None or abs(dot(n, axis)) < PARALLEL_DOT:
            continue
        if plane.area is None or plane.area > 1.5 * math.pi * radius * radius:
            continue
        if face.bbox is None:
            continue
        height = bbox_extent_along(face.bbox, axis)
        if height > _EPS:
            return _CylinderClass("boss", 0.5, height=height)

    # 折弯：至少两个互不平行的相邻平面与圆柱轴垂直
    perpendicular = []
    for plane in planar_neighbors:
        n = face_normal(plane)
        if n is not None and abs(dot(n, axis)) <= PERPENDICULAR_DOT:
            perpendicular.append(plane)
    if _nonparallel_count([face_normal(p) for p in perpendicular]) >= 2:
        return _CylinderClass("bend", 0.45, legs=perpendicular)

    # 其余按孔处理；轴向跨度与料厚/零件厚度同量级时提高一点置信度
    confidence = 0.25
    span = bbox_extent_along(face.bbox, axis) if face.bbox is not None else None
    part_span = (
        bbox_extent_along(part.bbox, axis)
        if part.bbox is not None
        else None
    )
    if thickness_value is not None and span is not None:
        if span <= 2.5 * thickness_value:
            confidence = 0.45
        elif part_span is not None and span >= 0.45 * part_span:
            confidence = 0.45
    return _CylinderClass("hole", confidence)


def _radial_offset(a: Vec3, b: Vec3, axis: Vec3) -> float:
    delta = sub(a, b)
    along = dot(delta, axis)
    return length(sub(delta, scale(axis, along)))


def _group_holes(
    part_id: str,
    raw: list[tuple[Face, float, Vec3, Vec3, float]],
) -> list[HoleFeature]:
    """把同轴且径向偏移很小的圆柱合并为孔组（处理沉孔/阶梯孔）。"""
    groups: list[HoleFeature] = []
    for face, radius, axis, point, confidence in raw:
        target: HoleFeature | None = None
        for group in groups:
            if abs(dot(axis, group.axis)) < PARALLEL_DOT:
                continue
            tolerance = max(0.1, 0.05 * max(radius, group.r_max))
            if _radial_offset(point, group.center, group.axis) > tolerance:
                continue
            target = group
            break
        if target is None:
            groups.append(
                HoleFeature(
                    part_id=part_id,
                    center=point,
                    axis=axis,
                    r_min=radius,
                    r_max=radius,
                    face_ids=[face.face_id],
                    confidence=confidence,
                )
            )
            continue
        target.face_ids.append(face.face_id)
        target.r_min = min(target.r_min, radius)
        if radius > target.r_max:
            target.r_max = radius
            target.center = point
        target.confidence = min(target.confidence, confidence)
    return groups


def _is_interior(point: Vec3, normal: Vec3, bbox: BBox | None) -> bool:
    """平面中心是否位于零件包围盒内部（用于排除零件外表面）。"""
    if bbox is None:
        return False
    comps = [abs(c) for c in normal]
    idx = max(range(3), key=lambda i: comps[i])
    lows = (bbox.xmin, bbox.ymin, bbox.zmin)
    highs = (bbox.xmax, bbox.ymax, bbox.zmax)
    lo, hi = lows[idx], highs[idx]
    if hi - lo <= _EPS:
        return False
    eps = max(1e-6, 1e-3 * (hi - lo))
    return lo + eps < point[idx] < hi - eps


def _detect_slots(
    part: Part,
    part_faces: list[Face],
    face_map: dict[str, Face],
    adj: dict[str, set[str]],
) -> list[SlotFeature]:
    planes = [
        f for f in part_faces
        if face_normal(f) is not None and face_point(f) is not None
    ]
    out: list[SlotFeature] = []
    for a, b in combinations(planes, 2):
        na, nb = face_normal(a), face_normal(b)
        pa, pb = face_point(a), face_point(b)
        if na is None or nb is None or pa is None or pb is None:
            continue
        if dot(na, nb) > -PARALLEL_DOT:
            continue
        width = abs(dot(sub(pb, pa), na))
        if width <= _EPS:
            continue
        if not _is_interior(pa, na, part.bbox) or not _is_interior(pb, nb, part.bbox):
            continue
        bottom: Face | None = None
        for fid in sorted(adj.get(a.face_id, set()) & adj.get(b.face_id, set())):
            candidate = face_map.get(fid)
            if candidate is None:
                continue
            nc = face_normal(candidate)
            if nc is None or abs(dot(nc, na)) > PERPENDICULAR_DOT:
                continue
            pc = face_point(candidate)
            # 槽底必须在零件内部；零件外表面也可能同时与两壁相邻，但不是槽底
            if pc is None or not _is_interior(pc, nc, part.bbox):
                continue
            bottom = candidate
            break
        if bottom is None:
            continue
        location = ((pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0, (pa[2] + pb[2]) / 2.0)
        out.append(
            SlotFeature(
                part_id=part.part_id,
                width=width,
                normal=na,
                location=location,
                face_ids=[a.face_id, b.face_id, bottom.face_id],
                confidence=0.45,
            )
        )
    return out


def extract_features(model: ModelBundle, params: dict | None = None) -> Features:
    """一次模型解析出料厚、孔、折弯、凸台、槽五类粗筛特征。"""
    params = params or {}
    feats = Features()
    face_map = model.face_map()
    adj = adjacency_map(model)
    planes_by_id = {
        fid: face for fid, face in face_map.items() if face_normal(face) is not None
    }

    for part in model.parts:
        thickness = resolve_thickness(part, params)
        feats.thickness[part.part_id] = thickness
        part_faces = model.faces_of(part.part_id)
        raw_holes: list[tuple[Face, float, Vec3, Vec3, float]] = []

        for face in part_faces:
            if not _is_cylinder(face):
                continue
            axis = face_axis(face)
            radius = face_radius(face)
            if axis is None or radius is None or radius <= _EPS:
                continue
            cls = _classify_cylinder(
                face, part, planes_by_id, adj, thickness.value
            )
            point = face_point(face)
            if cls.kind == "bend":
                if point is None:
                    continue
                feats.bends.append(
                    BendFeature(
                        part_id=part.part_id,
                        face=face,
                        radius=radius,
                        axis=axis,
                        point=point,
                        legs=list(cls.legs),
                        confidence=cls.confidence,
                    )
                )
            elif cls.kind == "boss":
                if cls.height is None:
                    continue
                feats.bosses.append(
                    BossFeature(
                        part_id=part.part_id,
                        face=face,
                        radius=radius,
                        axis=axis,
                        height=cls.height,
                        confidence=cls.confidence,
                    )
                )
            else:
                if point is None:
                    continue
                raw_holes.append((face, radius, axis, point, cls.confidence))

        feats.holes.extend(_group_holes(part.part_id, raw_holes))
        feats.slots.extend(_detect_slots(part, part_faces, face_map, adj))

    return feats


# --------------------------------------------------------------------------
# checker 基类与产出
# --------------------------------------------------------------------------
class SheetMetalChecker(BaseChecker):
    version = "0.1.0"
    owner = "M6A 于大淇"
    process_types = ("sheet_metal",)
    default_params = {"sheet_thickness_mm": None}

    def features(self, model: ModelBundle, params: dict) -> Features:
        return extract_features(model, params)

    @staticmethod
    def thickness(feats: Features, part_id: str) -> Thickness | None:
        t = feats.thickness.get(part_id)
        return t if t is not None and t.value is not None else None


def emit_finding(
    ctx,
    *,
    part_id: str,
    face_ids: list[str],
    message: str,
    measured: float,
    threshold: float,
    suggestion: str,
    thickness: Thickness,
    feature_kind: str,
    feature_confidence: float,
    location: Vec3 | None = None,
    note: str = "",
):
    """统一产出带粗筛标记、料厚来源、低置信度的 Finding。"""
    confidence = min(
        0.6,
        0.3 + 0.4 * float(thickness.confidence) + 0.2 * float(feature_confidence),
    )
    return ctx.finding(
        severity="P2",
        message=message,
        part_refs=[part_id],
        location=location,
        measured_value=round(float(measured), 4),
        threshold_value=round(float(threshold), 4),
        confidence=round(confidence, 3),
        suggestion_text=suggestion,
        face_ids=list(face_ids),
        note=note or "钣金粗筛：基于圆柱面/平面/包围盒的几何近似，需人工复核",
        extra={
            "coarse": True,
            "feature_kind": feature_kind,
            "thickness_mm": round(thickness.value, 4) if thickness.value is not None else None,
            "thickness_source": thickness.source,
            "thickness_confidence": thickness.confidence,
        },
    )
