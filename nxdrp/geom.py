# -*- coding: utf-8 -*-
"""几何工具函数。只做「不需要回 NX 重算」的轻量运算。

重要边界：
    这里的运算是近似且廉价的（包围盒、平面距离、聚类）。
    精确距离、干涉体积、真实壁厚必须回 NX 计算，见 nxdrp.checkers.proxy。
"""

from __future__ import annotations

import math

from .contracts import BBox, Face, Vec3


# --------------------------------------------------------------------------
# 向量
# --------------------------------------------------------------------------
def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a: Vec3) -> Vec3:
    n = math.sqrt(dot(a, a))
    return (0.0, 0.0, 0.0) if n == 0 else (a[0] / n, a[1] / n, a[2] / n)


def length(a: Vec3) -> float:
    return math.sqrt(dot(a, a))


def dist(a: Vec3, b: Vec3) -> float:
    return length(sub(a, b))


def angle_between_deg(a: Vec3, b: Vec3) -> float:
    na, nb = norm(a), norm(b)
    c = max(-1.0, min(1.0, dot(na, nb)))
    return math.degrees(math.acos(c))


def cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def round_vec(a: Vec3, nd: int = 4) -> Vec3:
    return (round(a[0], nd), round(a[1], nd), round(a[2], nd))


# --------------------------------------------------------------------------
# 包围盒
# --------------------------------------------------------------------------
def bbox_gap(a: BBox | None, b: BBox | None) -> float:
    """两个包围盒之间的最短间隙（相交返回 0）。廉价下界，用于预筛。"""
    if a is None or b is None:
        return float("inf")
    dx = max(a.xmin - b.xmax, b.xmin - a.xmax, 0.0)
    dy = max(a.ymin - b.ymax, b.ymin - a.ymax, 0.0)
    dz = max(a.zmin - b.zmax, b.zmin - a.zmax, 0.0)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def bbox_overlap(a: BBox | None, b: BBox | None) -> bool:
    if a is None or b is None:
        return False
    return not (a.xmax < b.xmin or b.xmax < a.xmin or
                a.ymax < b.ymin or b.ymax < a.ymin or
                a.zmax < b.zmin or b.zmax < a.zmin)


def bbox_extent_along(box: BBox | None, direction: Vec3) -> float:
    """包围盒在某方向上的投影长度。用于估算孔深等。"""
    if box is None:
        return 0.0
    d = norm(direction)
    corners = [
        (box.xmin, box.ymin, box.zmin), (box.xmax, box.ymin, box.zmin),
        (box.xmin, box.ymax, box.zmin), (box.xmax, box.ymax, box.zmin),
        (box.xmin, box.ymin, box.zmax), (box.xmax, box.ymin, box.zmax),
        (box.xmin, box.ymax, box.zmax), (box.xmax, box.ymax, box.zmax),
    ]
    proj = [dot(c, d) for c in corners]
    return max(proj) - min(proj)


# --------------------------------------------------------------------------
# 半径 / 聚类
# --------------------------------------------------------------------------
def face_radius(face: Face) -> float | None:
    """统一取半径（不论数据源给的是半径还是直径）。"""
    if face.radius_diameter is None:
        return None
    return face.radius_diameter if face.is_radius else face.radius_diameter / 2.0


def cluster_values(values: list[float], tol: float) -> list[float]:
    """一维聚类：把相差 <= tol 的值归为一个代表值。返回升序代表值列表。"""
    if not values:
        return []
    vals = sorted(values)
    reps = [vals[0]]
    for v in vals[1:]:
        if abs(v - reps[-1]) > tol:
            reps.append(v)
    return reps


def is_standard_drill(diameter: float, series: list[float], tol: float = 0.05) -> bool:
    return any(abs(diameter - s) <= tol for s in series)


# --------------------------------------------------------------------------
# 平面 / 拔模
# --------------------------------------------------------------------------
def face_normal(face: Face) -> Vec3 | None:
    """平面法向（已归一化）；非平面或数据缺失返回 None。"""
    return norm(face.normal) if face.normal else None


def face_axis(face: Face) -> Vec3 | None:
    """回转面轴向（圆柱/圆锥/球/环面），已归一化。"""
    return norm(face.axis) if face.axis else None


def is_planar(face: Face) -> bool:
    return face.normal is not None


def is_rotational(face: Face) -> bool:
    return face.axis is not None


def angle_to_dir(face: Face, direction: Vec3) -> float | None:
    """面法向与给定方向的无符号夹角（度）。"""
    n = face_normal(face)
    if n is None:
        return None
    a = angle_between_deg(n, direction)
    return a if a <= 90.0 else 180.0 - a


def draft_angle_deg(face: Face, pull_dir: Vec3) -> float | None:
    """拔模角 = 90° - 面法向与开模方向的夹角。

    开模方向取 +Z 时：与 Z 轴夹角 90° 的竖直面拔模角为 0；夹角 87° 的斜面为 3°。
    """
    n = face_normal(face)
    if n is None:
        return None
    return abs(90.0 - angle_between_deg(n, pull_dir))


def plane_point(face: Face) -> Vec3 | None:
    return face.point
