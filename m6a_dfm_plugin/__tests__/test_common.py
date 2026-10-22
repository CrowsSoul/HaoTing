# -*- coding: utf-8 -*-
"""公共几何工具的单元测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parent
for _path in (str(REPO_ROOT), str(PLUGIN_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from nxdrp.contracts import BBox, Edge, Face, ModelBundle, Part

from _m6a_dfm_common import (
    adjacency_map,
    extract_features,
    line_line_distance,
    positive_number,
    resolve_thickness,
)

FIXTURE = PLUGIN_ROOT / "__tests__" / "fixtures" / "bent_sheet.model.json"
MODELS = REPO_ROOT / "mockdata" / "models"


def load_model(name: str) -> ModelBundle:
    if name == "bent_sheet":
        return ModelBundle.load(str(FIXTURE))
    return ModelBundle.load(str(MODELS / f"{name}.model.json"))


class ThicknessTests(unittest.TestCase):
    def test_rule_value_wins(self):
        part = load_model("plate_holes").parts[0]
        t = resolve_thickness(part, {"sheet_thickness_mm": 1.25})
        self.assertAlmostEqual(t.value, 1.25)
        self.assertEqual(t.source, "rule")
        self.assertEqual(t.confidence, 0.9)

    def test_volume_over_area_estimate(self):
        part = load_model("plate_holes").parts[0]
        t = resolve_thickness(part, {})
        self.assertAlmostEqual(t.value, 2 * 47335.29789936264 / 12812.125905270359, places=6)
        self.assertEqual(t.source, "2V/A")
        self.assertEqual(t.confidence, 0.4)

    def test_rejects_implausible_volume_estimate(self):
        part = Part(
            part_id="X",
            volume=1e9,
            area=1.0,
            bbox=BBox(0, 0, 0, 1, 1, 1),
        )
        t = resolve_thickness(part, {})
        self.assertEqual(t.source, "bbox_min")
        self.assertAlmostEqual(t.value, 1.0)
        self.assertEqual(t.confidence, 0.2)

    def test_bbox_fallback_and_unknown(self):
        part = Part(part_id="X", bbox=BBox(0, 0, 0, 10, 20, 30))
        t = resolve_thickness(part, {})
        self.assertEqual((t.value, t.source, t.confidence), (10.0, "bbox_min", 0.2))

        unknown = resolve_thickness(Part(part_id="Y"), {})
        self.assertIsNone(unknown.value)
        self.assertEqual(unknown.source, "unknown")

    def test_positive_number(self):
        self.assertEqual(positive_number("1.5"), 1.5)
        self.assertIsNone(positive_number(None))
        self.assertIsNone(positive_number(0))
        self.assertIsNone(positive_number(-2))
        self.assertIsNone(positive_number("abc"))
        self.assertIsNone(positive_number(True))


class AdjacencyTests(unittest.TestCase):
    def test_merges_adjacency_and_edges(self):
        model = ModelBundle(
            model_id="adj_test",
            parts=[Part(part_id="P1")],
            faces=[Face("F1", "P1"), Face("F2", "P1"), Face("F3", "P1")],
            edges=[Edge("E1", "P1", face_ids=("F1", "F2"))],
            adjacency=[("F2", "F3")],
        )
        adj = adjacency_map(model)
        self.assertEqual(adj["F1"], {"F2"})
        self.assertEqual(adj["F2"], {"F1", "F3"})
        self.assertEqual(adj["F3"], {"F2"})


class LineDistanceTests(unittest.TestCase):
    def test_skew_lines(self):
        distance = line_line_distance((0, 0, 0), (1, 0, 0), (0, 5, 3), (0, 0, 1))
        self.assertAlmostEqual(distance, 5.0)

    def test_parallel_lines(self):
        distance = line_line_distance((0, 0, 0), (1, 0, 0), (0, 4, 0), (2, 0, 0))
        self.assertAlmostEqual(distance, 4.0)

    def test_degenerate_direction(self):
        self.assertIsNone(line_line_distance((0, 0, 0), (0, 0, 0), (1, 1, 1), (1, 0, 0)))


class FixtureFeatureTests(unittest.TestCase):
    def setUp(self):
        self.model = load_model("bent_sheet")
        self.features = extract_features(self.model, {})

    def test_fixture_is_valid_contract(self):
        self.model.validate()

    def test_thickness(self):
        t = self.features.thickness["P01"]
        self.assertAlmostEqual(t.value, 2.0)
        self.assertEqual(t.source, "2V/A")

    def test_one_bend_with_two_legs(self):
        self.assertEqual(len(self.features.bends), 1)
        bend = self.features.bends[0]
        self.assertEqual(bend.face.face_id, "F5")
        self.assertAlmostEqual(bend.radius, 0.6)
        self.assertEqual({leg.face_id for leg in bend.legs}, {"F1", "F4"})

    def test_three_single_holes(self):
        self.assertEqual(len(self.features.holes), 3)
        self.assertEqual(
            sorted(tuple(round(c, 3) for c in hole.center[:2]) for hole in self.features.holes),
            [(2.0, 15.0), (5.5, 15.0), (35.0, 15.0)],
        )
        for hole in self.features.holes:
            self.assertAlmostEqual(hole.r_min, 0.8)
            self.assertAlmostEqual(hole.r_max, 0.8)

    def test_no_slots_or_bosses(self):
        self.assertEqual(self.features.slots, [])
        self.assertEqual(self.features.bosses, [])


class MockFeatureTests(unittest.TestCase):
    def test_deep_slot(self):
        feats = extract_features(load_model("deep_slot"), {})
        self.assertEqual(len(feats.slots), 1)
        slot = feats.slots[0]
        self.assertAlmostEqual(slot.width, 2.0)
        self.assertEqual(set(slot.face_ids), {"F38954", "F38956", "F38955"})

    def test_bosses(self):
        feats = extract_features(load_model("bosses"), {})
        self.assertEqual(feats.bends, [])
        self.assertEqual(feats.holes, [])
        self.assertEqual(sorted(round(b.height, 3) for b in feats.bosses), [4.0, 8.0])

    def test_board_a_groups_counterbores(self):
        feats = extract_features(load_model("board_a"), {})
        by_part = {hole.part_id: hole for hole in feats.holes}
        self.assertEqual(set(by_part), {"P01", "P02"})
        self.assertAlmostEqual(by_part["P01"].r_min, 1.5)
        self.assertAlmostEqual(by_part["P01"].r_max, 4.0)
        self.assertEqual(len(by_part["P01"].face_ids), 4)
        self.assertAlmostEqual(by_part["P02"].r_min, 1.0)
        self.assertAlmostEqual(by_part["P02"].r_max, 2.0)
        self.assertEqual(feats.bends, [])
        self.assertEqual(feats.bosses, [])

    def test_thin_wall_slots_are_wide(self):
        feats = extract_features(load_model("thin_wall"), {})
        t = feats.thickness["P01"].value
        self.assertTrue(feats.slots)
        for slot in feats.slots:
            self.assertGreaterEqual(slot.width, 1.2 * t)


if __name__ == "__main__":
    unittest.main()
