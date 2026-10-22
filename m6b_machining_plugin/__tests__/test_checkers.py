# -*- coding: utf-8 -*-
"""12 个 M6B checker 的流程基线 + 逐项正例/负例/边界测试。

预期矩阵与夹具设计一一对应（见 build_fixtures.py 头注释）；
实现改动时先更新这里再改代码。
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parent
for _path in (str(REPO_ROOT), str(PLUGIN_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from nxdrp.contracts import BBox, Face, ModelBundle, Part, Rule, RuleBook
from nxdrp.pipeline import run
from nxdrp.registry import Registry, discover

FIXTURE = PLUGIN_ROOT / "__tests__" / "fixtures" / "machining_syn.model.json"
MODELS = REPO_ROOT / "mockdata" / "models"
M6B_IDS = [f"DFM-{i}" for i in range(27, 39)]


def plugin_registry() -> Registry:
    """内置 + 本插件一起加载（DFM-31/32 由内置参考实现提供，插件交付其余 10 项）。"""
    return discover([str(PLUGIN_ROOT)])


REGISTRY = plugin_registry()
RULEBOOK = RuleBook.load(str(PLUGIN_ROOT / "rules_m6b.json"))


def run_m6b(model: ModelBundle, only=None, rulebook=None):
    return run(model, rulebook or RULEBOOK, REGISTRY, only=only or M6B_IDS)


def counts(result) -> dict[str, int]:
    out = {cid: 0 for cid in M6B_IDS}
    for finding in result.findings:
        out[finding.check_item_id] += 1
    return out


def statuses(result) -> dict[str, str]:
    return {r.check_item_id: r.status for r in result.results}


# --------------------------------------------------------------------------
# 微型模型构造
# --------------------------------------------------------------------------
def plane(fid, pid, normal, point, area, bbox):
    return Face(face_id=fid, part_id=pid, solid_face_type="planar", uf_face_type=16,
                normal=normal, point=point, area=area, bbox=bbox)


def cyl(fid, pid, radius, axis, point, bbox, area=100.0):
    return Face(face_id=fid, part_id=pid, solid_face_type="cylindrical", uf_face_type=17,
                axis=axis, point=point, radius_diameter=radius, is_radius=True,
                area=area, bbox=bbox)


def cone(fid, pid, axis, point, bbox, area=10.0):
    return Face(face_id=fid, part_id=pid, solid_face_type="conical", uf_face_type=18,
                axis=axis, point=point, area=area, bbox=bbox)


def torus(fid, pid, radius, axis, point, bbox, area=10.0):
    return Face(face_id=fid, part_id=pid, solid_face_type="toroidal", uf_face_type=20,
                axis=axis, point=point, radius_diameter=radius, is_radius=True,
                area=area, bbox=bbox)


def micro(parts, faces, adjacency=()):
    return ModelBundle(
        model_id="micro", parts=list(parts), faces=list(faces),
        adjacency=[tuple(a) for a in adjacency],
    )


def block_part(pid="P1", bbox=BBox(0, 0, 0, 50, 50, 50)):
    return Part(part_id=pid, bbox=bbox, body_type="solid")


def slot_faces(wid, x0, x1, z_bottom, z_top, y0=10, y1=40):
    """构造一对槽壁 + 槽底（宽度 wid，沿 x 对置，槽口朝 +z）。"""
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    cz = (z_bottom + z_top) / 2.0
    return (
        [
            plane("W1", "P1", (1, 0, 0), (x0, cy, cz), (y1 - y0) * (z_top - z_bottom),
                  BBox(x0, y0, z_bottom, x0, y1, z_top)),
            plane("W2", "P1", (-1, 0, 0), (x0 + wid, cy, cz), (y1 - y0) * (z_top - z_bottom),
                  BBox(x0 + wid, y0, z_bottom, x0 + wid, y1, z_top)),
            plane("SB", "P1", (0, 0, 1), (x0 + wid / 2, cy, z_bottom), wid * (y1 - y0),
                  BBox(x0, y0, z_bottom, x0 + wid, y1, z_bottom)),
        ],
        [("W1", "SB"), ("W2", "SB")],
    )


# --------------------------------------------------------------------------
# 合成夹具预期矩阵
# --------------------------------------------------------------------------
class FixtureMatrixTests(unittest.TestCase):
    """合成夹具 machining_syn：每个 checker 的正/负/边界例，见 build_fixtures.py。"""

    EXPECTED = {
        "DFM-27": 2,   # H1 深孔 5.5（P2）+ H2 超深孔 10.71（P1）
        "DFM-28": 1,   # S1 深宽比 3.25
        "DFM-29": 2,   # H1 / H5 平底盲孔（H6/H7 锥底豁免）
        "DFM-30": 0,   # 单零件 → missing_data
        "DFM-31": 2,   # Ø2.8 / Ø5.3（内置参考实现，槽宽比对留待平台合并时启用）
        "DFM-32": 1,   # 4 种圆角 > 3
        "DFM-33": 2,   # 顶区锐边归并 + T4 顶边 R0.3
        "DFM-34": 1,   # C2 尺寸 0.7 非标准
        "DFM-35": 1,   # T5 内部转角 R0.3
        "DFM-36": 1,   # F7 斜面 20°
        "DFM-37": 1,   # S2 宽 0.8
        "DFM-38": 1,   # H7 孔口面斜 20°
    }

    @classmethod
    def setUpClass(cls):
        cls.model = ModelBundle.load(str(FIXTURE))
        cls.result = run_m6b(cls.model)

    def test_expected_counts(self):
        actual = counts(self.result)
        for cid in M6B_IDS:
            self.assertEqual(
                actual[cid], self.EXPECTED[cid],
                f"{cid} 期望 {self.EXPECTED[cid]} 条，实际 {actual[cid]} 条",
            )

    def test_no_error_status(self):
        errors = [r for r in self.result.results if r.status == "error"]
        self.assertEqual(errors, [])

    def test_statuses(self):
        status = statuses(self.result)
        for cid in M6B_IDS:
            expected = "missing_data" if cid == "DFM-30" else "ok"
            self.assertEqual(status[cid], expected, cid)

    def test_severity_upgrade_for_very_deep_hole(self):
        by_threshold = {f.threshold_value: f for f in self.result.findings if f.check_item_id == "DFM-27"}
        self.assertEqual(by_threshold[4.0].severity, "P2")
        self.assertEqual(by_threshold[10.0].severity, "P1")

    def test_findings_contract(self):
        for f in self.result.findings:
            with self.subTest(finding=f.finding_id):
                self.assertTrue(f.evidence.face_ids, "必须带 face_ids")
                self.assertTrue(f.suggestion.text, "建议不能为空")
                self.assertIn(f.severity, ("P0", "P1", "P2", "P3"))
                self.assertTrue(0.0 <= f.confidence <= 0.95)
                if f.extra.get("coarse"):
                    self.assertLessEqual(f.confidence, 0.6, "粗筛置信度封顶 0.6")


# --------------------------------------------------------------------------
# 共享 Mock 模型预期矩阵
# --------------------------------------------------------------------------
class MockModelMatrixTests(unittest.TestCase):
    EXPECTED_COUNTS = {
        "plate_holes": {"DFM-27": 1, "DFM-31": 4, "DFM-33": 1},
        "deep_slot": {"DFM-28": 1, "DFM-33": 1},
        "bosses": {},                                   # 凸台不应误报为孔
        "board_a": {"DFM-31": 2, "DFM-32": 1},
        "thin_wall": {"DFM-33": 1},
        "minimal": {},
        "demo_asm": {"DFM-27": 6, "DFM-30": 3, "DFM-31": 6},
        "asm_test": {"DFM-27": 2, "DFM-31": 2},
    }

    def test_expected_counts(self):
        for name, expected in self.EXPECTED_COUNTS.items():
            with self.subTest(model=name):
                model = ModelBundle.load(str(MODELS / f"{name}.model.json"))
                result = run_m6b(model)
                actual = counts(result)
                for cid in M6B_IDS:
                    self.assertEqual(
                        actual[cid], expected.get(cid, 0),
                        f"{name} {cid} 期望 {expected.get(cid, 0)} 条，实际 {actual[cid]} 条",
                    )
                self.assertFalse(
                    [r for r in result.results if r.status == "error"],
                    f"{name} 存在 error 状态的 checker",
                )


# --------------------------------------------------------------------------
# 逐项边界测试（微型模型）
# --------------------------------------------------------------------------
class Dfm27BoundaryTests(unittest.TestCase):
    def make(self, depth):
        faces = [
            plane("B", "P1", (0, 0, -1), (10, 10, 0), 400.0, BBox(0, 0, 0, 20, 20, 0)),
            plane("T", "P1", (0, 0, 1), (10, 10, 20), 400.0, BBox(0, 0, 20, 20, 20, 20)),
            cyl("H", "P1", 2.0, (0, 0, -1), (10, 10, 20 - depth / 2),
                BBox(8, 8, 20 - depth, 12, 12, 20)),
        ]
        return micro([block_part(bbox=BBox(0, 0, 0, 20, 20, 20))], faces,
                     [("H", "T"), ("H", "B")])

    def test_ratio_just_over_threshold_reports(self):
        result = run_m6b(self.make(16.04), only=["DFM-27"])  # 16.04/4 = 4.01 > 4
        self.assertEqual(len(result.findings), 1)

    def test_ratio_exactly_threshold_silent(self):
        result = run_m6b(self.make(16.0), only=["DFM-27"])   # 恰 4.0
        self.assertEqual(len(result.findings), 0)

    def test_ratio_below_threshold_silent(self):
        result = run_m6b(self.make(8.0), only=["DFM-27"])    # 2.0
        self.assertEqual(len(result.findings), 0)


class Dfm28BoundaryTests(unittest.TestCase):
    def make(self, width, depth):
        faces, adj = slot_faces(width, 10, 10 + width, 20 - depth, 20)
        return micro([block_part()], faces, adj)

    def test_ratio_just_over_reports(self):
        result = run_m6b(self.make(4.0, 12.04), only=["DFM-28"])  # 3.01
        self.assertEqual(len(result.findings), 1)

    def test_ratio_exactly_threshold_silent(self):
        result = run_m6b(self.make(4.0, 12.0), only=["DFM-28"])   # 恰 3.0
        self.assertEqual(len(result.findings), 0)

    def test_shallow_slot_silent(self):
        result = run_m6b(self.make(4.0, 4.0), only=["DFM-28"])    # 1.0
        self.assertEqual(len(result.findings), 0)


class Dfm30Tests(unittest.TestCase):
    """刀具可达性（占位粗筛）：跨零件包络遮挡。"""

    def make(self, p2_bbox):
        p1 = block_part("P1", BBox(0, 0, 0, 20, 20, 10))
        faces = [
            plane("A_TOP", "P1", (0, 0, 1), (10, 10, 10), 400.0, BBox(0, 0, 10, 20, 20, 10)),
            plane("A_BOT", "P1", (0, 0, -1), (10, 10, 0), 400.0, BBox(0, 0, 0, 20, 20, 0)),
            cyl("H", "P1", 3.0, (0, 0, -1), (10, 10, 5), BBox(7, 7, 0, 13, 13, 10)),
        ]
        parts = [p1, Part(part_id="P2", bbox=p2_bbox, body_type="solid")]
        return micro(parts, faces, [("H", "A_TOP"), ("H", "A_BOT")])

    def test_blocked_envelope_reports(self):
        # P2 悬在孔口正上方 4 mm 处（包络半径 5 mm）→ 遮挡
        result = run_m6b(self.make(BBox(5, 5, 14, 15, 15, 30)), only=["DFM-30"])
        self.assertEqual(len(result.findings), 1)
        self.assertIn("P2", result.findings[0].extra["blockers"])

    def test_clear_envelope_silent(self):
        # P2 在 100 mm 外 → 无遮挡
        result = run_m6b(self.make(BBox(100, 100, 100, 110, 110, 120)), only=["DFM-30"])
        self.assertEqual(len(result.findings), 0)

    def test_single_part_skips(self):
        model = micro([block_part()], [])
        result = run_m6b(model, only=["DFM-30"])
        self.assertEqual(statuses(result)["DFM-30"], "missing_data")


class Dfm31OverrideTests(unittest.TestCase):
    """改表即改判定：规则参数覆盖标准刀具系列。"""

    @classmethod
    def setUpClass(cls):
        cls.model = ModelBundle.load(str(FIXTURE))

    def test_custom_series_clears_nonstandard_hole(self):
        custom = RuleBook(rules=[
            Rule(rule_id="X-31", check_item_id="DFM-31", severity="P2",
                 params={"standard_diameters": [5.3], "check_slot_widths": False}),
        ])
        result = run_m6b(self.model, only=["DFM-31"], rulebook=custom)
        # Ø5.3 已入列 → 不再报；其余孔径距 5.3 全部超差 → 6 条
        messages = [f.message for f in result.findings]
        self.assertEqual(len(result.findings), 6)
        self.assertFalse(any("Ø5.30" in m for m in messages), "改表后 Ø5.3 应判为标准")

    def test_empty_rule_uses_tool_library(self):
        result = run_m6b(self.model, only=["DFM-31"])
        self.assertEqual(len(result.findings), 2)  # 与预期矩阵一致（内置参考实现）


class Dfm32BoundaryTests(unittest.TestCase):
    def make(self, radii):
        faces = [
            torus(f"T{i}", "P1", r, (1, 0, 0), (10 + i * 5, 0, 5),
                  BBox(5 + i * 5, 0, 4, 15 + i * 5, 1, 6))
            for i, r in enumerate(radii)
        ]
        return micro([block_part()], faces)

    def test_three_kinds_silent(self):
        result = run_m6b(self.make([0.5, 1.0, 2.0]), only=["DFM-32"])
        self.assertEqual(len(result.findings), 0)

    def test_four_kinds_reports(self):
        result = run_m6b(self.make([0.5, 1.0, 2.0, 3.0]), only=["DFM-32"])
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].measured_value, 4.0)

    def test_cluster_tolerance_merges_close_radii(self):
        result = run_m6b(self.make([0.5, 0.55, 1.0, 2.0]), only=["DFM-32"])
        self.assertEqual(len(result.findings), 0)  # 0.5 与 0.55 聚为一类 → 3 种


class Dfm33Tests(unittest.TestCase):
    def test_sharp_edge_below_top_region_silent(self):
        faces = [
            plane("S", "P1", (1, 0, 0), (10, 10, 5), 100.0, BBox(10, 0, 0, 10, 20, 10)),
            plane("B", "P1", (0, 0, -1), (10, 10, 0), 400.0, BBox(0, 0, 0, 20, 20, 0)),
        ]
        model = micro([block_part(bbox=BBox(0, 0, 0, 20, 20, 10))], faces, [("S", "B")])
        result = run_m6b(model, only=["DFM-33"])
        self.assertEqual(len(result.findings), 0)

    def test_sharp_edge_in_top_region_reports(self):
        faces = [
            plane("T", "P1", (0, 0, 1), (10, 10, 10), 400.0, BBox(0, 0, 10, 20, 20, 10)),
            plane("S", "P1", (1, 0, 0), (20, 10, 5), 100.0, BBox(20, 0, 0, 20, 20, 10)),
        ]
        model = micro([block_part(bbox=BBox(0, 0, 0, 20, 20, 10))], faces, [("T", "S")])
        result = run_m6b(model, only=["DFM-33"])
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].extra["feature_kind"], "sharp_edge")

    def test_small_top_fillet_boundary(self):
        def model_with_fillet(radius):
            faces = [
                plane("T", "P1", (0, 0, 1), (10, 10, 10), 400.0, BBox(0, 0, 10, 20, 20, 10)),
                torus("FT", "P1", radius, (1, 0, 0), (10, 20, 9.5),
                      BBox(0, 19.5, 9, 20, 20, 10)),
            ]
            return micro([block_part(bbox=BBox(0, 0, 0, 20, 20, 10))], faces)

        self.assertEqual(
            len(run_m6b(model_with_fillet(0.49), only=["DFM-33"]).findings), 1)
        self.assertEqual(
            len(run_m6b(model_with_fillet(0.5), only=["DFM-33"]).findings), 0)  # 恰 0.5 不报


class Dfm35BoundaryTests(unittest.TestCase):
    def make(self, radius, point=(10, 10, 10)):
        faces = [
            torus("CT", "P1", radius, (1, 0, 0), point,
                  BBox(point[0] - 5, point[1] - 0.3, point[2] - 0.3,
                       point[0] + 5, point[1], point[2])),
            plane("PA", "P1", (0, 1, 0), (10, 10, 5), 100.0, BBox(0, 10, 0, 20, 10, 10)),
            plane("PB", "P1", (0, 0, 1), (10, 15, 10), 100.0, BBox(0, 10, 10, 20, 20, 10)),
        ]
        return micro([block_part()], faces, [("CT", "PA"), ("CT", "PB")])

    def test_interior_small_radius_reports(self):
        result = run_m6b(self.make(0.49), only=["DFM-35"])
        self.assertEqual(len(result.findings), 1)

    def test_interior_radius_at_threshold_silent(self):
        result = run_m6b(self.make(0.5), only=["DFM-35"])
        self.assertEqual(len(result.findings), 0)

    def test_exterior_fillet_silent(self):
        result = run_m6b(self.make(0.3, point=(0, 10, 10)), only=["DFM-35"])
        self.assertEqual(len(result.findings), 0)


class Dfm36BoundaryTests(unittest.TestCase):
    def make(self, angle_deg):
        rad = math.radians(angle_deg)
        faces = [
            plane("BASE", "P1", (0, 0, -1), (25, 25, 0), 5000.0, BBox(0, 0, 0, 50, 50, 0)),
            plane("TILT", "P1", (math.sin(rad), 0, math.cos(rad)), (25, 25, 25), 500.0,
                  BBox(10, 10, 20, 40, 40, 30)),
        ]
        return micro([block_part()], faces)

    def test_nonstandard_angle_reports(self):
        result = run_m6b(self.make(88.9), only=["DFM-36"])  # 距 90° 1.1° > 容差 1.0
        self.assertEqual(len(result.findings), 1)

    def test_within_tolerance_of_90_silent(self):
        result = run_m6b(self.make(89.5), only=["DFM-36"])  # 距 90° 0.5° < 容差 1.0
        self.assertEqual(len(result.findings), 0)

    def test_standard_45_silent(self):
        result = run_m6b(self.make(45.0), only=["DFM-36"])
        self.assertEqual(len(result.findings), 0)


class Dfm37BoundaryTests(unittest.TestCase):
    def make(self, width):
        faces, adj = slot_faces(width, 10, 10 + width, 18, 20)
        return micro([block_part()], faces, adj)

    def test_width_below_min_reports(self):
        result = run_m6b(self.make(0.99), only=["DFM-37"])
        self.assertEqual(len(result.findings), 1)

    def test_width_at_min_silent(self):
        result = run_m6b(self.make(1.0), only=["DFM-37"])
        self.assertEqual(len(result.findings), 0)

    def test_wide_channel_silent(self):
        result = run_m6b(self.make(5.0), only=["DFM-37"])
        self.assertEqual(len(result.findings), 0)


class Dfm38BoundaryTests(unittest.TestCase):
    def make(self, angle_deg):
        rad = math.radians(angle_deg)
        faces = [
            cyl("H", "P1", 2.0, (0, 0, -1), (10, 10, 25), BBox(8, 8, 20, 12, 12, 30)),
            cone("HC", "P1", (0, 0, -1), (10, 10, 19.5), BBox(8, 8, 19, 12, 12, 20)),
            plane("OPEN", "P1", (math.sin(rad), 0, math.cos(rad)), (10, 10, 30), 1000.0,
                  BBox(0, 0, 28, 20, 20, 32)),
        ]
        return micro([block_part(bbox=BBox(0, 0, 0, 20, 20, 32))], faces,
                     [("H", "HC"), ("H", "OPEN")])

    def test_slanted_opening_reports(self):
        result = run_m6b(self.make(5.1), only=["DFM-38"])
        self.assertEqual(len(result.findings), 1)

    def test_opening_at_threshold_silent(self):
        result = run_m6b(self.make(5.0), only=["DFM-38"])  # 恰 5.0° 不报
        self.assertEqual(len(result.findings), 0)

    def test_perpendicular_opening_silent(self):
        result = run_m6b(self.make(0.0), only=["DFM-38"])
        self.assertEqual(len(result.findings), 0)


if __name__ == "__main__":
    unittest.main()
