# -*- coding: utf-8 -*-
"""生成 Mock 模型（ModelBundle JSON）。

为什么需要它：8 个人里只有一两个人手上有 NX。其余人必须先能开发、能跑测试、
能自测自己的 checker，否则整个并行计划会卡在「等我装好 NX」上。

生成的 board_a.model.json 故意踩中三个示例 checker 的触发条件，
用来验证「解析 -> 检查 -> 结果」全链路是通的。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nxdrp.adapters.mock import synthesize  # noqa: E402
from nxdrp.contracts import BBox, Face, ModelBundle, Occurrence, Part  # noqa: E402
from nxdrp.version import SCHEMA_VERSION  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "mockdata", "models")


def build_board_a() -> ModelBundle:
    bundle = ModelBundle(
        model_id="board_a",
        source="mock://board_a.prt",
        nx_version="mock-2606",
        units="mm",
        generator="tools.gen_mock",
        schema_version=SCHEMA_VERSION,
    )

    housing_bbox = BBox(0.0, 0.0, 0.0, 40.0, 25.0, 12.0)
    terminal_bbox = BBox(40.15, 5.0, 3.0, 55.0, 20.0, 9.0)

    bundle.parts.append(
        Part(part_id="P01", name="HOUSING", journal_id="EXTRUDE(3)", material="PA66",
             body_type="solid", is_sheet=False, volume=12000.0, mass=13.7, area=4200.0,
             bbox=housing_bbox, face_count=18, edge_count=36, occurrence_path="ROOT/HOUSING(1)")
    )
    bundle.parts.append(
        Part(part_id="P02", name="TERMINAL", journal_id="EXTRUDE(17)", material="CuSn6",
             body_type="solid", is_sheet=False, volume=640.0, mass=5.7, area=980.0,
             bbox=terminal_bbox, face_count=10, edge_count=20, occurrence_path="ROOT/TERMINAL(2)")
    )

    fid = 0

    UF = {"planar": 16, "cylindrical": 17, "conical": 18, "spherical": 19, "toroidal": 20}
    NORMAL = {"planar": (0.0, 0.0, 1.0)}

    def add(part_id, ftype, code, *, area=None, perim=None, radius=None, cog=None, bbox=None, edges=4):
        nonlocal fid
        fid += 1
        bundle.faces.append(
            Face(
                face_id=f"F{fid}", part_id=part_id, tag=40000 + fid,
                solid_face_type=ftype, solid_face_code=code,
                uf_face_type=UF.get(ftype, 0),
                point=cog,
                normal=NORMAL.get(ftype),
                axis=(0.0, 0.0, 1.0) if ftype in ("cylindrical", "conical", "toroidal") else None,
                area=area, perimeter=perim,
                radius_diameter=radius, is_radius=True,
                cog=cog, bbox=bbox, edge_count=edges,
            )
        )
        return f"F{fid}"

    # ---- P01 外壳：平面 + 若干孔 + 若干圆角 ----
    for k in range(4):
        add("P01", "planar", 1, area=1000.0, perim=130.0,
            cog=(20.0, 12.5, 0.0 if k < 2 else 12.0), bbox=housing_bbox, edges=4)

    # 孔径：Ø3.0(标准) / Ø3.7(非标) / Ø6.3(非标) / Ø8.0(标准)
    for d in (3.0, 3.7, 6.3, 8.0):
        add("P01", "cylindrical", 2, area=3.1416 * d * 12.0, perim=3.1416 * d,
            radius=d / 2.0, cog=(10.0, 10.0, 6.0), bbox=housing_bbox, edges=2)

    # 圆角：6 种半径 -> 触发 DFM-32
    for r in (0.4, 0.5, 0.8, 1.0, 1.5, 2.0):
        add("P01", "toroidal", 5, area=6.2832 * r * 1.2, perim=6.2832 * r,
            radius=r, cog=(5.0, 5.0, 1.0), bbox=housing_bbox, edges=2)

    # ---- P02 端子：与 P01 包围盒间隙 0.15mm -> 触发 DFM-02 ----
    for k in range(4):
        add("P02", "planar", 1, area=240.0, perim=68.0,
            cog=(47.0, 12.5, 3.0 + k * 2.0), bbox=terminal_bbox, edges=4)
    for d in (2.0, 4.0):
        add("P02", "cylindrical", 2, area=3.1416 * d * 6.0, perim=3.1416 * d,
            radius=d / 2.0, cog=(47.5, 12.5, 6.0), bbox=terminal_bbox, edges=2)

    # ---- 邻接关系（供 DFM-18 尖角、DFM-16 圆角使用）----
    ids = [f.face_id for f in bundle.faces]
    bundle.adjacency = [(ids[i], ids[i + 1]) for i in range(0, len(ids) - 1, 2)]

    # ---- 装配实例 ----
    bundle.occurrences = [
        Occurrence(occurrence_id="O0001", name="HOUSING(1)", part_ref="P01", parent="",
                   transform=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], bbox=housing_bbox),
        Occurrence(occurrence_id="O0002", name="TERMINAL(2)", part_ref="P02", parent="",
                   transform=[[1, 0, 0, 40.15], [0, 1, 0, 5.0], [0, 0, 1, 3.0], [0, 0, 0, 1]], bbox=terminal_bbox),
    ]

    bundle.meta.update({
        "has_normals": True,
        "has_axes": True,
        "note": "Mock 模型，用于无 NX 环境下的开发与回归",
        "expected_findings": {"DFM-31": 2, "DFM-32": 1, "DFM-02": 1},
    })
    bundle.diagnostics = {"counts": {"bodies": len(bundle.parts), "faces": len(bundle.faces)}}
    bundle.validate()
    return bundle


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    a = build_board_a()
    pa = os.path.join(OUT_DIR, "board_a.model.json")
    a.save(pa)
    print(f"已生成 {pa}  ({len(a.parts)} 零件 / {len(a.faces)} 面)")

    m = synthesize("minimal")
    pm = os.path.join(OUT_DIR, "minimal.model.json")
    m.save(pm)
    print(f"已生成 {pm}  ({len(m.parts)} 零件 / {len(m.faces)} 面)")


if __name__ == "__main__":
    main()
