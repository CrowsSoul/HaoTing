# -*- coding: utf-8 -*-
"""M6B 机加工 DFM 插件的公共几何工具。

数据契约里没有孔深、槽深、倒角、型腔等机加工专有字段，因此本模块全部采用
低置信度的几何粗筛。结果只用于跑通流程，必须人工复核。

设计约定（与 M6A 插件一致）：
  * 文件名以 ``_`` 开头，registry 不会把它当 checker 加载；
  * checker 通过 ``from _m6b_machining_common import ...`` 平铺导入；
  * 所有几何字段先判空，拿不到就跳过，不产出看似精确的假结果；
  * 阈值一律来自规则参数或 tool_library.json，不在代码里写死。
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from itertools import combinations

from nxdrp.checkers.base import BaseChecker
from nxdrp.contracts import BBox, Face, ModelBundle, Part, Vec3
from nxdrp.geom import (
    angle_between_deg,
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
class HoleEnd:
    """孔组端部相邻面（孔口或孔底）。"""

    face: Face
    kind: str                        # opening / bottom / side
    interior: bool = False


@dataclass
class HoleFeature:
    """同轴孔组：把沉孔/阶梯孔的多段圆柱合并为一个孔。"""

    part_id: str
    center: Vec3
    axis: Vec3
    r_min: float
    r_max: float
    depth: float = 0.0               # 同轴各段沿轴总跨度
    segments: list[tuple[str, float, float]] = field(default_factory=list)  # (face_id, 半径, 沿轴跨度)
    face_ids: list[str] = field(default_factory=list)
    ends: list[HoleEnd] = field(default_factory=list)
    is_boss: bool = False            # 凸台/销钉误判为孔的标记，钻孔类检查应跳过
    confidence: float = 0.45


@dataclass
class SlotFeature:
    """直槽候选：两块互相对置、位于零件内部的平面壁，且有共同槽底。"""

    part_id: str
    width: float
    depth: float
    normal: Vec3                     # 槽宽方向（壁面法向）
    up: Vec3                         # 槽口方向（槽底法向）
    location: Vec3
    face_ids: list[str] = field(default_factory=list)
    confidence: float = 0.45


@dataclass
class ChamferFeature:
    """倒角候选：与两个互垂平面相邻、法向介于两者之间的小平面。"""

    part_id: str
    face: Face
    angle_deg: float                 # 与两个母平面夹角的均值
    size_mm: float                   # 倒角面最小包围盒尺寸（≈ 倒角宽度）
    face_ids: list[str] = field(default_factory=list)
    confidence: float = 0.4


@dataclass
class FilletFeature:
    """圆角候选：回转圆角面（toroidal/cylindrical），标注是否位于零件内部。"""

    part_id: str
    face: Face
    radius: float
    interior: bool
    face_ids: list[str] = field(default_factory=list)
    confidence: float = 0.45


@dataclass
class SharpEdge:
    """锐边候选：一对互垂平面直接相邻（中间没有圆角面）。"""

    part_id: str
    face_ids: tuple[str, str]
    location: Vec3 | None
    confidence: float = 0.4


@dataclass
class Features:
    """一次模型解析出来的全部粗筛特征。"""

    holes: list[HoleFeature] = field(default_factory=list)
    slots: list[SlotFeature] = field(default_factory=list)
    chamfers: list[ChamferFeature] = field(default_factory=list)
    fillets: list[FilletFeature] = field(default_factory=list)
    sharp_edges: list[SharpEdge] = field(default_factory=list)
    base_planes: dict[str, Face] = field(default_factory=dict)   # part_id -> 最大平面


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


def nonnegative_number(value) -> float | None:
    """同 positive_number，但允许 0（角度等参数用）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
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


def _is_cone(face: Face) -> bool:
    if face.solid_face_type == "conical":
        return True
    return face.uf_face_type == 18 and face.axis is not None and face.normal is None


def _is_torus(face: Face) -> bool:
    if face.solid_face_type == "toroidal":
        return True
    return face.uf_face_type == 20 and face.radius_diameter is not None


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


def span_along(boxes: list[BBox | None], axis: Vec3) -> float:
    """一组包围盒沿某方向的总投影跨度（最大投影 - 最小投影）。"""
    d = norm(axis)
    lo = hi = None
    for box in boxes:
        if box is None:
            continue
        corners = [
            (box.xmin, box.ymin, box.zmin), (box.xmax, box.ymin, box.zmin),
            (box.xmin, box.ymax, box.zmin), (box.xmax, box.ymax, box.zmin),
            (box.xmin, box.ymin, box.zmax), (box.xmax, box.ymin, box.zmax),
            (box.xmin, box.ymax, box.zmax), (box.xmax, box.ymax, box.zmax),
        ]
        for c in corners:
            s = dot(c, d)
            lo = s if lo is None else min(lo, s)
            hi = s if hi is None else max(hi, s)
    if lo is None:
        return 0.0
    return hi - lo


def _is_interior(point: Vec3, normal: Vec3, bbox: BBox | None) -> bool:
    """平面中心是否位于零件包围盒内部（用于区分孔口与孔底）。"""
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


def _bbox_interior(point: Vec3, bbox: BBox | None) -> bool:
    """点是否严格位于包围盒内部（三轴同时满足，用于内/外圆角区分）。"""
    if bbox is None:
        return False
    lows = (bbox.xmin, bbox.ymin, bbox.zmin)
    highs = (bbox.xmax, bbox.ymax, bbox.zmax)
    for i in range(3):
        span = highs[i] - lows[i]
        if span <= _EPS:
            continue
        eps = max(1e-6, 1e-3 * span)
        if not (lows[i] + eps < point[i] < highs[i] - eps):
            return False
    return True


def acute_angle_deg(a: Vec3, b: Vec3) -> float:
    """两个方向的无符号锐角（0~90°），用于平面夹角。"""
    ang = angle_between_deg(a, b)
    return ang if ang <= 90.0 else 180.0 - ang


def radial_extent(bbox: BBox | None, axis: Vec3) -> float | None:
    """回转面包围盒在径向的最大跨度。

    完整圆柱（孔）径向跨度 ≈ 2r；部分圆柱（圆角，如四分之一圆弧）≈ r。
    用于把「圆柱形圆角」从孔里区分出来。
    """
    if bbox is None:
        return None
    a = norm(axis)
    ref = (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = norm(cross(a, ref))
    v = norm(cross(a, u))
    return max(bbox_extent_along(bbox, u), bbox_extent_along(bbox, v))


#: 径向跨度 / 半径低于该值判为部分圆柱（圆角），否则按完整圆柱（孔）处理
FULL_CYLINDER_RATIO = 1.8


# --------------------------------------------------------------------------
# 刀具库
# --------------------------------------------------------------------------
_TOOL_LIB: dict | None = None


def tool_library() -> dict:
    """读取插件目录下的 tool_library.json；读不到返回空表。"""
    global _TOOL_LIB
    if _TOOL_LIB is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tool_library.json")
        try:
            with open(path, encoding="utf-8") as fh:
                _TOOL_LIB = json.load(fh)
        except (OSError, ValueError):
            _TOOL_LIB = {}
    return _TOOL_LIB


def tool_values(ctx, param_key: str, library_key: str, fallback: list[float]) -> list[float]:
    """数列型阈值的取值顺序：规则参数 > tool_library.json > 代码兜底。"""
    raw = ctx.param(param_key)
    if raw is None:
        raw = tool_library().get(library_key)
    if raw is None:
        raw = fallback
    out: list[float] = []
    try:
        for x in raw:
            v = float(x)
            if math.isfinite(v):
                out.append(v)
    except (TypeError, ValueError):
        return list(fallback)
    return out


def nearest(series: list[float], value: float) -> float | None:
    if not series:
        return None
    return min(series, key=lambda s: abs(s - value))


# --------------------------------------------------------------------------
# 特征提取：孔
# --------------------------------------------------------------------------
def _radial_offset(a: Vec3, b: Vec3, axis: Vec3) -> float:
    delta = sub(a, b)
    along = dot(delta, axis)
    return length(sub(delta, scale(axis, along)))


def _group_holes(
    part_id: str,
    raw: list[tuple[Face, float, Vec3, Vec3]],
) -> list[HoleFeature]:
    """把同轴且径向偏移很小的圆柱合并为孔组（处理沉孔/阶梯孔）。"""
    groups: list[HoleFeature] = []
    members: list[list[Face]] = []
    for face, radius, axis, point in raw:
        target_idx: int | None = None
        for idx, group in enumerate(groups):
            if abs(dot(axis, group.axis)) < PARALLEL_DOT:
                continue
            tolerance = max(0.1, 0.05 * max(radius, group.r_max))
            if _radial_offset(point, group.center, group.axis) > tolerance:
                continue
            target_idx = idx
            break
        if target_idx is None:
            groups.append(
                HoleFeature(
                    part_id=part_id,
                    center=point,
                    axis=axis,
                    r_min=radius,
                    r_max=radius,
                    face_ids=[face.face_id],
                )
            )
            members.append([face])
            continue
        group = groups[target_idx]
        group.face_ids.append(face.face_id)
        members[target_idx].append(face)
        group.r_min = min(group.r_min, radius)
        if radius > group.r_max:
            group.r_max = radius
            group.center = point
    for group, faces in zip(groups, members):
        group.depth = span_along([f.bbox for f in faces], group.axis)
        radii = {f.face_id: face_radius(f) for f in faces}
        group.segments = [
            (f.face_id, radii[f.face_id] or 0.0, span_along([f.bbox], group.axis))
            for f in faces
        ]
    return groups


#: 端面面积超过该倍数 × 孔截面积时，判定孔开在这个大面上（孔口），不可能是孔底
BIG_FACE_RATIO = 4.0


def _classify_hole_ends(
    hole: HoleFeature,
    member_ids: set[str],
    adj: dict[str, set[str]],
    face_map: dict[str, Face],
    part: Part,
) -> None:
    """找出孔组端部的相邻面，区分孔口（opening）与孔底（bottom）。

    判定规则（粗筛）：
      * 法向与孔轴垂直的面：横向结构，记 side，不参与判定；
      * 面积 > BIG_FACE_RATIO × πr² 的大面：孔只可能开在它上面 → opening
        （斜面孔口也因此能被识别，不依赖内部性测试）；
      * 小端盖（≈ πr²）：位于零件内部 → bottom（盲孔底），否则 → opening
        （凸台顶盖，交给 _mark_boss 进一步甄别）。
    """
    big_area = BIG_FACE_RATIO * math.pi * hole.r_max * hole.r_max
    seen: set[str] = set()
    for fid in hole.face_ids:
        for nid in sorted(adj.get(fid, ())):
            if nid in member_ids or nid in seen:
                continue
            face = face_map.get(nid)
            if face is None:
                continue
            seen.add(nid)
            n = face_normal(face)
            a = face_axis(face) if _is_cone(face) else None
            direction = n if n is not None else a
            point = face_point(face)
            if direction is None or point is None:
                hole.ends.append(HoleEnd(face, "side"))
                continue
            if abs(dot(norm(direction), hole.axis)) < PERPENDICULAR_DOT:
                # 端面方向与孔轴垂直：多半是横向贯穿结构，不参与孔口/孔底判定
                hole.ends.append(HoleEnd(face, "side"))
                continue
            if face.area is not None and face.area > big_area:
                hole.ends.append(HoleEnd(face, "opening", False))
                continue
            interior = _is_interior(point, norm(direction), part.bbox)
            hole.ends.append(HoleEnd(face, "bottom" if interior else "opening", interior))


def _mark_boss(hole: HoleFeature, part: Part) -> None:
    """凸台/销钉甄别：端盖面积与圆柱截面积同量级、且位于圆柱背向零件主体的一侧。

    盲孔底盖面积同样 ≈ πr²，但它位于圆柱朝向零件主体的一侧（孔往零件里钻）；
    凸台顶盖位于圆柱背向主体的一侧（凸台从零件表面伸出来）。
    """
    if part.bbox is None or hole.r_max <= _EPS:
        return
    part_center = part.bbox.center
    s_center = dot(part_center, hole.axis)
    s_cyl = dot(hole.center, hole.axis)
    cap_limit = 1.5 * math.pi * hole.r_max * hole.r_max
    for end in hole.ends:
        face = end.face
        if face_normal(face) is None or face.area is None or face.area > cap_limit:
            continue
        point = face_point(face)
        if point is None:
            continue
        s_cap = dot(point, hole.axis)
        if (s_cap - s_cyl) * (s_center - s_cyl) <= 0:
            hole.is_boss = True
            return


def extract_holes(model: ModelBundle) -> list[HoleFeature]:
    """按零件提取同轴孔组，含深度与端面信息。"""
    face_map = model.face_map()
    adj = adjacency_map(model)
    out: list[HoleFeature] = []
    for part in model.parts:
        raw: list[tuple[Face, float, Vec3, Vec3]] = []
        for face in model.faces_of(part.part_id, "cylindrical"):
            if not _is_cylinder(face):
                continue
            axis = face_axis(face)
            radius = face_radius(face)
            point = face_point(face)
            if axis is None or radius is None or radius <= _EPS or point is None:
                continue
            # 部分圆柱（径向跨度 << 2r）是圆角而非孔，交给圆角类检查
            extent = radial_extent(face.bbox, axis)
            if extent is not None and extent < FULL_CYLINDER_RATIO * radius:
                continue
            raw.append((face, radius, axis, point))
        holes = _group_holes(part.part_id, raw)
        for hole in holes:
            _classify_hole_ends(hole, set(hole.face_ids), adj, face_map, part)
            _mark_boss(hole, part)
            # 有端面信息的孔组更可信
            hole.confidence = 0.45 if hole.ends else 0.3
        out.extend(holes)
    return out


# --------------------------------------------------------------------------
# 特征提取：槽
# --------------------------------------------------------------------------
def extract_slots(model: ModelBundle) -> list[SlotFeature]:
    """直槽粗筛：互相对置的内部平面壁 + 共同槽底；槽深取壁面沿槽底法向的跨度。"""
    face_map = model.face_map()
    adj = adjacency_map(model)
    out: list[SlotFeature] = []
    for part in model.parts:
        part_faces = model.faces_of(part.part_id)
        planes = [
            f for f in part_faces
            if face_normal(f) is not None and face_point(f) is not None
        ]
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
            nc = face_normal(bottom)
            if nc is None:
                continue
            spans = [
                span
                for span in (bbox_extent_along(a.bbox, nc), bbox_extent_along(b.bbox, nc))
                if span > _EPS
            ]
            depth = min(spans) if spans else 0.0
            location = ((pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0, (pa[2] + pb[2]) / 2.0)
            out.append(
                SlotFeature(
                    part_id=part.part_id,
                    width=width,
                    depth=depth,
                    normal=na,
                    up=nc,
                    location=location,
                    face_ids=[a.face_id, b.face_id, bottom.face_id],
                    confidence=0.45,
                )
            )
    return out


# --------------------------------------------------------------------------
# 特征提取：倒角 / 圆角 / 锐边 / 基准面
# --------------------------------------------------------------------------
def extract_chamfers(model: ModelBundle) -> list[ChamferFeature]:
    """倒角粗筛：与两个互垂平面相邻、法向介于两母平面之间的平面。"""
    face_map = model.face_map()
    adj = adjacency_map(model)
    out: list[ChamferFeature] = []
    for part in model.parts:
        for face in model.faces_of(part.part_id, "planar"):
            nf = face_normal(face)
            if nf is None or face_point(face) is None:
                continue
            parents: list[Face] = []
            for fid in sorted(adj.get(face.face_id, ())):
                candidate = face_map.get(fid)
                if candidate is None or face_normal(candidate) is None:
                    continue
                parents.append(candidate)
            found = False
            for p1, p2 in combinations(parents, 2):
                n1, n2 = face_normal(p1), face_normal(p2)
                if n1 is None or n2 is None:
                    continue
                if abs(dot(n1, n2)) > PERPENDICULAR_DOT:
                    continue
                # 与两个互垂母平面都相邻，且法向夹在中间（30°~60°）
                a1 = acute_angle_deg(nf, n1)
                a2 = acute_angle_deg(nf, n2)
                if not (30.0 <= a1 <= 60.0 and 30.0 <= a2 <= 60.0):
                    continue
                # 倒角面必然比它连接的两个母平面窄；否则是把大面误判成倒角
                # （例如顶面夹在两个镜像 45° 倒角之间，恰好满足法向条件）
                if (
                    face.area is not None
                    and p1.area is not None
                    and p2.area is not None
                    and face.area >= min(p1.area, p2.area)
                ):
                    continue
                size = min(face.bbox.size) if face.bbox is not None else 0.0
                out.append(
                    ChamferFeature(
                        part_id=part.part_id,
                        face=face,
                        angle_deg=(a1 + a2) / 2.0,
                        size_mm=size,
                        face_ids=[face.face_id, p1.face_id, p2.face_id],
                        confidence=0.4,
                    )
                )
                found = True
                break
            if found:
                continue
    return out


def extract_fillets(model: ModelBundle) -> list[FilletFeature]:
    """圆角粗筛：toroidal 面 + 部分圆柱面（径向跨度 < 1.8r），标注是否位于零件内部。"""
    parts_bbox = {p.part_id: p.bbox for p in model.parts}
    out: list[FilletFeature] = []
    for face in model.faces:
        radius = face_radius(face)
        point = face_point(face)
        if radius is None or radius <= _EPS or point is None:
            continue
        if _is_torus(face):
            confidence = 0.45
        elif _is_cylinder(face):
            axis = face_axis(face)
            extent = radial_extent(face.bbox, axis) if axis is not None else None
            if extent is None or extent >= FULL_CYLINDER_RATIO * radius:
                continue  # 完整圆柱按孔处理
            confidence = 0.35
        else:
            continue
        out.append(
            FilletFeature(
                part_id=face.part_id,
                face=face,
                radius=radius,
                interior=_bbox_interior(point, parts_bbox.get(face.part_id)),
                face_ids=[face.face_id],
                confidence=confidence,
            )
        )
    return out


def extract_sharp_edges(model: ModelBundle) -> list[SharpEdge]:
    """锐边粗筛：互垂平面直接相邻（中间无圆角面即锐边）。位置取两面点中点。"""
    face_map = model.face_map()
    adj = adjacency_map(model)
    out: list[SharpEdge] = []
    seen: set[tuple[str, str]] = set()
    for a, b in model.adjacency:
        key = (a, b) if a <= b else (b, a)
        if key in seen:
            continue
        seen.add(key)
        fa, fb = face_map.get(a), face_map.get(b)
        if fa is None or fb is None or fa.part_id != fb.part_id:
            continue
        na, nb = face_normal(fa), face_normal(fb)
        if na is None or nb is None:
            continue
        if abs(dot(na, nb)) > PERPENDICULAR_DOT:
            continue
        pa, pb = face_point(fa), face_point(fb)
        location = None
        if pa is not None and pb is not None:
            location = ((pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0, (pa[2] + pb[2]) / 2.0)
        out.append(SharpEdge(part_id=fa.part_id, face_ids=(a, b), location=location))
    return out


def base_planes(model: ModelBundle) -> dict[str, Face]:
    """每个零件面积最大的平面，作为角度铣削面的基准面。"""
    out: dict[str, Face] = {}
    for part in model.parts:
        best: Face | None = None
        for face in model.faces_of(part.part_id, "planar"):
            if face_normal(face) is None:
                continue
            if best is None or (face.area or 0.0) > (best.area or 0.0):
                best = face
        if best is not None:
            out[part.part_id] = best
    return out


def extract_features(model: ModelBundle) -> Features:
    """一次模型解析出孔、槽、倒角、圆角、锐边、基准面六类粗筛特征。"""
    feats = Features()
    feats.holes = extract_holes(model)
    feats.slots = extract_slots(model)
    feats.chamfers = extract_chamfers(model)
    feats.fillets = extract_fillets(model)
    feats.sharp_edges = extract_sharp_edges(model)
    feats.base_planes = base_planes(model)
    return feats


# --------------------------------------------------------------------------
# 几何小工具：线段到包围盒的距离（DFM-30 刀具包络用）
# --------------------------------------------------------------------------
def _point_bbox_distance(p: Vec3, box: BBox) -> float:
    dx = max(box.xmin - p[0], p[0] - box.xmax, 0.0)
    dy = max(box.ymin - p[1], p[1] - box.ymax, 0.0)
    dz = max(box.zmin - p[2], p[2] - box.zmax, 0.0)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def segment_bbox_distance(p0: Vec3, p1: Vec3, box: BBox, samples: int = 7) -> float:
    """线段到包围盒的近似最短距离（采样粗估，占位用）。"""
    if samples < 2:
        samples = 2
    best = float("inf")
    for i in range(samples):
        t = i / (samples - 1)
        p = (
            p0[0] + (p1[0] - p0[0]) * t,
            p0[1] + (p1[1] - p0[1]) * t,
            p0[2] + (p1[2] - p0[2]) * t,
        )
        best = min(best, _point_bbox_distance(p, box))
    return best


# --------------------------------------------------------------------------
# checker 基类与产出
# --------------------------------------------------------------------------
class MachiningChecker(BaseChecker):
    version = "0.1.0"
    owner = "M6 张百瑞"
    process_types = ("machining",)


def emit_finding(
    ctx,
    *,
    part_id: str,
    face_ids,
    message: str,
    measured: float | None,
    threshold: float | None,
    suggestion: str,
    feature_kind: str,
    confidence: float,
    location: Vec3 | None = None,
    severity: str | None = None,
    unit: str = "mm",
    coarse: bool = True,
    note: str = "",
    extra: dict | None = None,
):
    """统一产出 Finding。

    coarse=True（特征粗筛类）时置信度封顶 0.6 并打粗筛标记；
    coarse=False（直接测量类，如孔径比对）时允许高置信度。
    """
    if coarse:
        confidence = min(0.6, max(0.05, float(confidence)))
        default_note = "机加工粗筛：基于圆柱面/平面/包围盒的几何近似，需人工复核"
    else:
        confidence = min(0.95, max(0.05, float(confidence)))
        default_note = ""
    payload = {
        "coarse": coarse,
        "feature_kind": feature_kind,
    }
    if extra:
        payload.update(extra)
    return ctx.finding(
        severity=severity or ctx.rule.severity,
        message=message,
        part_refs=[part_id],
        location=location,
        measured_value=round(float(measured), 4) if measured is not None else None,
        threshold_value=round(float(threshold), 4) if threshold is not None else None,
        unit=unit,
        confidence=round(confidence, 3),
        suggestion_text=suggestion,
        face_ids=list(face_ids),
        note=note or default_note,
        extra=payload,
    )
