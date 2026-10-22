# -*- coding: utf-8 -*-
"""公共几何工具 _m6b_machining_common 的单元测试。"""

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

from nxdrp.contracts import BBox, Face, ModelBundle, Part

from _m6b_machining_common import (
    acute_angle_deg,
    base_planes,
    extract_chamfers,
    extract_fillets,
    extract_holes,
    extract_sharp_edges,
    extract_slots,
    nonnegative_number,
    positive_number,
    radial_extent,
    segment_bbox_distance,
    span_along,
    tool_library,
    tool_values,
)

FIXTURE = PLUGIN_ROOT / "__tests__" / "fixtures" / "machining_syn.model.json"
MODELS = REPO_ROOT / "mockdata" / "models"


def load_fixture() -> ModelBundle:
    return ModelBundle.load(str(FIXTURE))


class NumberParsingTests(unittest.TestCase):
    def test_positive_number(self):
        self.assertEqual(positive_number("2.5"), 2.5)
        self.assertEqual(positive_number(3), 3.0)
        self.assertIsNone(positive_number(None))
        self.assertIsNone(positive_number(True))
        self.assertIsNone(positive_number(0))
        self.assertIsNone(positive_number(-1))
        self.assertIsNone(positive_number("abc"))
        self.assertIsNone(positive_number(float("nan")))

    def test_nonnegative_number_allows_zero(self):
        self.assertEqual(nonnegative_number(0), 0.0)
        self.assertIsNone(nonnegative_number(-0.5))


class VectorGeometryTests(unittest.TestCase):
    def test_acute_angle(self):
        self.assertAlmostEqual(acute_angle_deg((0, 0, 1), (0, 0, -1)), 0.0)
        self.assertAlmostEqual(acute_angle_deg((0, 0, 1), (1, 0, 0)), 90.0)
        self.assertAlmostEqual(acute_angle_deg((0, 0, 1), (0.342, 0, 0.940)), 20.0, places=1)

    def test_span_along(self):
        boxes = [BBox(0, 0, 0, 4, 4, 10), BBox(0, 0, 8, 4, 4, 20)]
        self.assertAlmostEqual(span_along(boxes, (0, 0, 1)), 20.0)
        self.assertAlmostEqual(span_along([None], (0, 0, 1)), 0.0)

    def test_radial_extent_full_vs_partial(self):
        full = radial_extent(BBox(8, 8, 0, 12, 12, 10), (0, 0, 1))
        self.assertAlmostEqual(full, 4.0)  # 完整圆柱 2r
        quarter = radial_extent(BBox(10, 10, 0, 12, 12, 10), (0, 0, 1))
        self.assertAlmostEqual(quarter, 2.0)  # 四分之一圆弧 ≈ r

    def test_segment_bbox_distance(self):
        box = BBox(0, 0, 12, 10, 10, 20)
        # 线段穿过包围盒 → 0
        self.assertAlmostEqual(segment_bbox_distance((5, 5, 0), (5, 5, 30), box), 0.0)
        # 线段在包围盒上方 5 mm
        self.assertAlmostEqual(
            segment_bbox_distance((5, 5, 25), (5, 5, 35), box), 5.0, places=6
        )


class ToolLibraryTests(unittest.TestCase):
    def test_library_loads_with_required_keys(self):
        lib = tool_library()
        for key in (
            "drill_diameters_mm",
            "endmill_diameters_mm",
            "standard_chamfer_angles_deg",
            "standard_chamfer_sizes_mm",
            "standard_plane_angles_deg",
            "min_tool_diameter_mm",
        ):
            self.assertIn(key, lib, key)
        self.assertIn(6.0, lib["drill_diameters_mm"])

    def test_tool_values_priority(self):
        class _Ctx:
            def __init__(self, params):
                self._params = params

            def param(self, key, default=None):
                return self._params.get(key, default)

        # 规则参数优先
        self.assertEqual(
            tool_values(_Ctx({"standard_diameters": [9.9]}), "standard_diameters", "drill_diameters_mm", []),
            [9.9],
        )
        # 其次刀具库
        self.assertIn(
            6.0, tool_values(_Ctx({}), "standard_diameters", "drill_diameters_mm", [])
        )
        # 最后兜底
        self.assertEqual(
            tool_values(_Ctx({}), "nope", "also_nope", [1.0]), [1.0]
        )


class HoleExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_fixture()
        cls.holes = extract_holes(cls.model)
        cls.by_face = {h.face_ids[0]: h for h in cls.holes}

    def test_finds_all_seven_holes(self):
        self.assertEqual(len(self.holes), 7)
        self.assertFalse(any(h.is_boss for h in self.holes))

    def test_depth_and_segments(self):
        h1 = self.by_face["F10"]
        self.assertAlmostEqual(h1.depth, 22.0)
        self.assertEqual(h1.segments[0][1], 2.0)
        self.assertAlmostEqual(h1.segments[0][2], 22.0)

    def test_opening_and_bottom_classification(self):
        h1 = self.by_face["F10"]
        ends = {e.face.face_id: e.kind for e in h1.ends}
        self.assertEqual(ends["F11"], "bottom")      # 小平底 → 盲孔底
        self.assertEqual(ends["F2"], "opening")      # 大面 → 孔口
        h2 = self.by_face["F12"]
        self.assertEqual({e.kind for e in h2.ends}, {"opening"})  # 通孔两个孔口

    def test_cone_bottom_is_bottom(self):
        h6 = self.by_face["F17"]
        ends = {e.face.face_id: e.kind for e in h6.ends}
        self.assertEqual(ends["F18"], "bottom")

    def test_slanted_big_face_is_opening(self):
        h7 = self.by_face["F19"]
        ends = {e.face.face_id: e.kind for e in h7.ends}
        self.assertEqual(ends["F7"], "opening")      # 斜面也是孔口（大面规则）

    def test_boss_detection_on_bosses_model(self):
        bosses = ModelBundle.load(str(MODELS / "bosses.model.json"))
        holes = extract_holes(bosses)
        self.assertEqual(len(holes), 2)
        self.assertTrue(all(h.is_boss for h in holes), "凸台不应被当成孔")

    def test_plate_holes_are_not_bosses(self):
        plate = ModelBundle.load(str(MODELS / "plate_holes.model.json"))
        holes = extract_holes(plate)
        self.assertEqual(len(holes), 4)
        self.assertFalse(any(h.is_boss for h in holes))


class SlotExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slots = extract_slots(load_fixture())

    def test_finds_four_slots(self):
        self.assertEqual(len(self.slots), 4)

    def test_width_and_depth(self):
        by_bottom = {s.face_ids[2]: s for s in self.slots}
        self.assertAlmostEqual(by_bottom["F23"].width, 4.0)
        self.assertAlmostEqual(by_bottom["F23"].depth, 13.0)
        self.assertAlmostEqual(by_bottom["F26"].width, 0.8)
        self.assertAlmostEqual(by_bottom["F26"].depth, 2.0)
        self.assertAlmostEqual(by_bottom["F32"].width, 5.0)
        self.assertAlmostEqual(by_bottom["F32"].depth, 15.0)

    def test_deep_slot_mock_model(self):
        model = ModelBundle.load(str(MODELS / "deep_slot.model.json"))
        slots = extract_slots(model)
        self.assertEqual(len(slots), 1)
        self.assertGreater(slots[0].depth / slots[0].width, 3.0)


class ChamferFilletEdgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_fixture()

    def test_chamfers(self):
        chamfers = extract_chamfers(self.model)
        sizes = sorted(round(c.size_mm, 2) for c in chamfers)
        self.assertEqual(sizes, [0.5, 0.6, 0.7])
        for c in chamfers:
            self.assertAlmostEqual(c.angle_deg, 45.0, places=1)

    def test_fillets_and_interior_flag(self):
        fillets = extract_fillets(self.model)
        self.assertEqual(len(fillets), 5)
        interior = [f for f in fillets if f.interior]
        self.assertEqual([f.face.face_id for f in interior], ["T5"])

    def test_sharp_edges(self):
        edges = extract_sharp_edges(self.model)
        self.assertEqual(len(edges), 17)  # 13 顶区 + 4 槽底（被顶区过滤）

    def test_base_plane_is_largest(self):
        bases = base_planes(self.model)
        self.assertEqual(bases["P01"].face_id, "F1")


if __name__ == "__main__":
    unittest.main()
