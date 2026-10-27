# -*- coding: utf-8 -*-
"""生成 M6B 合成测试夹具 machining_syn.model.json。

夹具是一个 100×60×30 的方块，里面按设计埋下每个 checker 的正例 / 负例 / 边界例，
全部几何量（点、法向、包围盒、邻接）手工布线，确保预期 Finding 矩阵稳定：

| 特征 | 面 | 命中 |
|---|---|---|
| H1 盲孔 Ø4 深 22 平底 | F10/F11 | DFM-27(P2, 5.5)、DFM-29 |
| H2 通孔 Ø2.8 深 30 | F12 | DFM-27(P1, 10.71)、DFM-31(Ø2.8) |
| H3 通孔 Ø8 深 30 | F13 | 负例（3.75 ≤ 4，Ø8 标准） |
| H4 盲孔 Ø6 深 24 锥底 | F14/F14B | 边界（深径比恰 4.0，不报；Ø6 标准；锥底不报 29） |
| H5 盲孔 Ø5.3 深 10 平底 | F15/F16 | DFM-31(Ø5.3)、DFM-29 |
| H6 盲孔 Ø5.04 深 10 锥底 | F17/F18 | 边界（Ø 偏差 0.04 ≤ 0.05；锥底不报 29） |
| H7 斜面入口盲孔 Ø5 深 10 锥底 | F19/F20 | DFM-38（孔口面 F7 斜 20°） |
| S1 槽 宽4 深13 | F21/F22/F23 | DFM-28（3.25 > 3） |
| S2 槽 宽0.8 深2 | F24/F25/F26 | DFM-37（0.8 < 1）、DFM-31(槽宽) |
| S3 槽 宽10 深2 | F27/F28/F29 | 负例（0.2 ≤ 3） |
| S4 槽 宽5 深15 | F30/F31/F32 | 边界（深宽比恰 3.0，不报） |
| C1 倒角 C0.5×45° | F33 | 负例（角度/尺寸均标准） |
| C2 倒角 C0.7×45° | F34 | DFM-34（尺寸 0.7 非标准） |
| C3 倒角 C0.6×45° | F35 | 边界（偏差恰 0.1 = 容差，不报） |
| F7 斜面 20° | F7 | DFM-36（非标准角） |
| T1~T4 圆角 R0.5/1.0/2.0/0.3 | T1~T4 | DFM-32（4 种 > 3）；T4 顶区 R0.3 → DFM-33 |
| T5 槽底内角 R0.3 | T5 | DFM-35（内部转角 R < 0.5） |
| 顶面锐边 13 条 | 邻接对 | DFM-33（缺顶边圆角，归并 1 条） |

运行：python tools/gen_m6b_fixture.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "machining_syn.model.json"

SQRT2_2 = math.sqrt(0.5)  # cos45°
SIN20, COS20 = math.sin(math.radians(20.0)), math.cos(math.radians(20.0))


def plane(fid, normal, point, area, bbox):
    return {
        "face_id": fid, "part_id": "P01", "solid_face_type": "planar",
        "uf_face_type": 16, "normal": list(normal), "point": list(point),
        "area": area, "bbox": _bbox(*bbox),
    }


def cylinder(fid, radius, axis, point, bbox, area):
    return {
        "face_id": fid, "part_id": "P01", "solid_face_type": "cylindrical",
        "uf_face_type": 17, "axis": list(axis), "point": list(point),
        "radius_diameter": radius, "is_radius": True, "area": area, "bbox": _bbox(*bbox),
    }


def cone(fid, axis, point, bbox, area):
    return {
        "face_id": fid, "part_id": "P01", "solid_face_type": "conical",
        "uf_face_type": 18, "axis": list(axis), "point": list(point),
        "area": area, "bbox": _bbox(*bbox),
    }


def torus(fid, radius, axis, point, bbox, area):
    return {
        "face_id": fid, "part_id": "P01", "solid_face_type": "toroidal",
        "uf_face_type": 20, "axis": list(axis), "point": list(point),
        "radius_diameter": radius, "is_radius": True, "area": area, "bbox": _bbox(*bbox),
    }


def _bbox(xmin, ymin, zmin, xmax, ymax, zmax):
    return {"xmin": xmin, "ymin": ymin, "zmin": zmin,
            "xmax": xmax, "ymax": ymax, "zmax": zmax}


FACES = [
    # ---- 方块 6 面 + 1 斜面 ----
    plane("F1", (0, 0, -1), (50, 30, 0), 6000.0, (0, 0, 0, 100, 60, 0)),
    plane("F2", (0, 0, 1), (50, 30, 30), 5900.0, (0, 0, 30, 100, 60, 30)),
    plane("F3", (-1, 0, 0), (0, 30, 15), 1790.0, (0, 0, 0, 0, 60, 30)),
    plane("F4", (1, 0, 0), (100, 30, 15), 1790.0, (100, 0, 0, 100, 60, 30)),
    plane("F5", (0, -1, 0), (50, 0, 15), 2990.0, (0, 0, 0, 100, 0, 30)),
    plane("F6", (0, 1, 0), (50, 60, 15), 3000.0, (0, 60, 0, 100, 60, 30)),
    plane("F7", (SIN20, 0, COS20), (90, 45, 29.4), 640.0, (80, 30, 28, 100, 60, 30)),
    # ---- H1 深盲孔 Ø4 深22 平底 ----
    cylinder("F10", 2.0, (0, 0, -1), (20, 20, 19), (18, 18, 8, 22, 22, 30), 276.5),
    plane("F11", (0, 0, 1), (20, 20, 8), 12.57, (18, 18, 8, 22, 22, 8)),
    # ---- H2 超深通孔 Ø2.8 深30 ----
    cylinder("F12", 1.4, (0, 0, -1), (40, 20, 15), (38.6, 18.6, 0, 41.4, 21.4, 30), 263.9),
    # ---- H3 通孔 Ø8 深30（负例） ----
    cylinder("F13", 4.0, (0, 0, -1), (60, 20, 15), (56, 16, 0, 64, 24, 30), 754.0),
    # ---- H4 盲孔 Ø6 深24 锥底（深径比边界 4.0，Ø6 标准） ----
    cylinder("F14", 3.0, (0, 0, -1), (80, 20, 18), (77, 17, 6, 83, 23, 30), 452.4),
    cone("F14B", (0, 0, -1), (80, 20, 5.5), (77, 17, 5, 83, 23, 6), 31.3),
    # ---- H5 盲孔 Ø5.3 深10 平底 ----
    cylinder("F15", 2.65, (0, 0, -1), (20, 45, 25), (17.35, 42.35, 20, 22.65, 47.65, 30), 166.5),
    plane("F16", (0, 0, 1), (20, 45, 20), 22.06, (17.35, 42.35, 20, 22.65, 47.65, 20)),
    # ---- H6 盲孔 Ø5.04 深10 锥底（DFM-31 容差边界 / DFM-29 钻尖豁免） ----
    cylinder("F17", 2.52, (0, 0, -1), (40, 45, 25), (37.48, 42.48, 20, 42.52, 47.52, 30), 158.3),
    cone("F18", (0, 0, -1), (40, 45, 19.5), (37.48, 42.48, 19, 42.52, 47.52, 20), 22.0),
    # ---- H7 斜面入口盲孔 Ø5 深10 锥底 ----
    cylinder("F19", 2.5, (0, 0, -1), (85, 45, 23), (82.5, 42.5, 18, 87.5, 47.5, 28), 157.1),
    cone("F20", (0, 0, -1), (85, 45, 17.5), (82.5, 42.5, 17, 87.5, 47.5, 18), 21.6),
    # ---- S1 深窄槽 宽4 深13 ----
    plane("F21", (0, 1, 0), (30, 38, 23.5), 520.0, (10, 38, 17, 50, 38, 30)),
    plane("F22", (0, -1, 0), (30, 42, 23.5), 520.0, (10, 42, 17, 50, 42, 30)),
    plane("F23", (0, 0, 1), (30, 40, 17), 160.0, (10, 38, 17, 50, 42, 17)),
    # ---- S2 窄通道 宽0.8 深2 ----
    plane("F24", (1, 0, 0), (60, 50, 29), 40.0, (60, 40, 28, 60, 60, 30)),
    plane("F25", (-1, 0, 0), (60.8, 50, 29), 40.0, (60.8, 40, 28, 60.8, 60, 30)),
    plane("F26", (0, 0, 1), (60.4, 50, 28), 16.0, (60, 40, 28, 60.8, 60, 28)),
    # ---- S3 浅宽槽 宽10 深2（负例） ----
    plane("F27", (0, 1, 0), (85, 5, 29), 60.0, (70, 5, 28, 100, 5, 30)),
    plane("F28", (0, -1, 0), (85, 15, 29), 60.0, (70, 15, 28, 100, 15, 30)),
    plane("F29", (0, 0, 1), (85, 10, 28), 300.0, (70, 5, 28, 100, 15, 28)),
    # ---- S4 边界槽 宽5 深15（深宽比恰 3.0） ----
    plane("F30", (0, 1, 0), (15, 50, 22.5), 300.0, (5, 50, 15, 25, 50, 30)),
    plane("F31", (0, -1, 0), (15, 55, 22.5), 300.0, (5, 55, 15, 25, 55, 30)),
    plane("F32", (0, 0, 1), (15, 52.5, 15), 100.0, (5, 50, 15, 25, 55, 15)),
    # ---- 倒角 C1/C2/C3（均 45°，尺寸 0.5 / 0.7 / 0.6） ----
    plane("F33", (-SQRT2_2, 0, SQRT2_2), (99.65, 30, 29.65), 42.4, (99.5, 0, 29.5, 100, 60, 30)),
    plane("F34", (SQRT2_2, 0, SQRT2_2), (0.35, 30, 29.65), 59.4, (0, 0, 29.3, 0.7, 60, 30)),
    plane("F35", (0, SQRT2_2, SQRT2_2), (50, 0.3, 29.7), 84.9, (0, 0, 29.4, 100, 0.6, 30)),
    # ---- 圆角 T1~T5 ----
    torus("T1", 0.5, (1, 0, 0), (50, 60, 29.5), (0, 59.5, 29, 100, 60, 30), 30.0),
    torus("T2", 1.0, (1, 0, 0), (50, 0, 29.5), (0, 0, 28.5, 100, 1, 30), 60.0),
    torus("T3", 2.0, (0, 1, 0), (0, 30, 29), (0, 0, 27, 2, 60, 30), 80.0),
    torus("T4", 0.3, (0, 1, 0), (100, 30, 29.85), (99.7, 0, 29.7, 100, 60, 30), 12.0),
    torus("T5", 0.3, (1, 0, 0), (30, 38, 17), (10, 37.7, 16.7, 50, 38, 17.3), 8.0),
]

ADJACENCY = [
    # 孔
    ("F10", "F11"), ("F10", "F2"),
    ("F12", "F1"), ("F12", "F2"),
    ("F13", "F1"), ("F13", "F2"),
    ("F14", "F14B"), ("F14", "F2"),
    ("F15", "F16"), ("F15", "F2"),
    ("F17", "F18"), ("F17", "F2"),
    ("F19", "F20"), ("F19", "F7"),
    # 斜面与邻面
    ("F7", "F2"), ("F7", "F4"),
    # 槽
    ("F21", "F23"), ("F22", "F23"), ("F21", "F2"), ("F22", "F2"),
    ("F24", "F26"), ("F25", "F26"), ("F24", "F2"), ("F25", "F2"),
    ("F27", "F29"), ("F28", "F29"), ("F27", "F2"), ("F28", "F2"),
    ("F30", "F32"), ("F31", "F32"), ("F30", "F2"), ("F31", "F2"),
    # 倒角
    ("F33", "F2"), ("F33", "F4"),
    ("F34", "F2"), ("F34", "F3"),
    ("F35", "F2"), ("F35", "F5"),
    # 内角圆角
    ("T5", "F21"), ("T5", "F23"),
    # 顶面锐边（F2 与 F6 直接相交）
    ("F2", "F6"),
]

MODEL = {
    "schema_version": "1.0.0",
    "model_id": "machining_syn",
    "source": "synthetic fixture for M6B machining DFM",
    "units": "mm",
    "generator": "m6b build_fixtures.py",
    "parts": [{
        "part_id": "P01", "name": "machining_syn_block", "body_type": "solid",
        "volume": 175000.0, "area": 25000.0, "bbox": _bbox(0, 0, 0, 100, 60, 30),
    }],
    "faces": FACES,
    "edges": [],
    "occurrences": [],
    "adjacency": [list(pair) for pair in ADJACENCY],
    "diagnostics": {},
    "meta": {"fixture": "m6b_machining", "expected": "见 build_fixtures.py 头注释"},
}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(MODEL, fh, ensure_ascii=False, indent=1)
    print(f"written {OUT} ({len(FACES)} faces, {len(ADJACENCY)} adjacency pairs)")


if __name__ == "__main__":
    main()
