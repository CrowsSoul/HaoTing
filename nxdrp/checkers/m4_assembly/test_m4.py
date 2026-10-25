# -*- coding: utf-8 -*-
"""M4 装配 DFM 的正例、负例、边界与降级测试。"""

from __future__ import annotations

import unittest
from pathlib import Path

from nxdrp.checkers.base import CheckContext
from nxdrp.contracts import BBox, Face, ModelBundle, Occurrence, Part, Rule, RuleBook
from nxdrp.eval import load_labels, score
from nxdrp.pipeline import run
from nxdrp.registry import discover

from .dfm01_interference import InterferenceChecker
from .dfm02_min_clearance import MinClearanceChecker
from .dfm03_hole_alignment import HoleAlignmentChecker
from .dfm04_hole_slot_alignment import HoleSlotAlignmentChecker
from .dfm05_fastener_accessibility import FastenerAccessibilityChecker
from .dfm06_fastener_clearance import FastenerClearanceChecker
from .dfm07_engagement_length import EngagementLengthChecker

ROOT = Path(__file__).resolve().parents[3]


def model_with_gap(gap: float = 0.1, meta: dict | None = None) -> ModelBundle:
    a = BBox(0, 0, 0, 10, 10, 10)
    b = BBox(10 + gap, 0, 0, 20 + gap, 10, 10)
    return ModelBundle(
        model_id="m4-test",
        parts=[Part("A", bbox=a), Part("B", bbox=b)],
        faces=[
            Face("A-F1", "A", tag=101, solid_face_type="cylindrical", axis=(0, 0, 1),
                 point=(5, 5, 0), radius_diameter=2, bbox=a, area=10),
            Face("B-F1", "B", tag=202, solid_face_type="cylindrical", axis=(0, 0, 1),
                 point=(5, 5, 0), radius_diameter=2, bbox=b, area=10),
            Face("B-S1", "B", tag=203, solid_face_type="planar", normal=(1, 0, 0),
                 point=(5, 5, 0), bbox=b, area=10),
        ],
        meta={"assembly_features": meta or {}},
    )


def run_checker(checker, model: ModelBundle, params: dict | None = None, nx=None):
    merged = checker.merged_params(params or {})
    rule = Rule(rule_id="test", check_item_id=checker.check_item_id,
                process_type="assembly", severity="P2", params=merged)
    findings = list(checker.check(CheckContext(model=model, rule=rule, params=merged,
                                                checker=checker, nx=nx)) or [])
    for finding in findings:
        finding.validate()
    return findings


def hole_rows(offset: float = 0.0, diameter_b: float = 4.0):
    return [
        {"feature_id": "HA", "mate_id": "M1", "part_id": "A", "center": [5, 5, 0],
         "axis": [0, 0, 1], "diameter_mm": 4.0, "face_ids": ["A-F1"]},
        {"feature_id": "HB", "mate_id": "M1", "part_id": "B", "center": [5 + offset, 5, 0],
         "axis": [0, 0, 1], "diameter_mm": diameter_b, "face_ids": ["B-F1"]},
    ]


def fastener_row(**updates):
    row = {
        "feature_id": "M4-bolt", "part_id": "A", "face_ids": ["A-F1"],
        "axis": [0, 0, 1], "head_center": [5, 5, 10],
        "nominal_diameter_mm": 4.0, "engagement_length_mm": 4.0,
        "material": "steel", "available_tool_diameter_mm": 10.0,
        "available_tool_height_mm": 40.0, "radial_clearance_mm": 0.5,
        "axial_clearance_mm": 0.5, "accessible": True,
    }
    row.update(updates)
    return row


class _NxStub:
    def __init__(self, distance):
        self.value = distance
        self.prefetched = []
        self.prefetch_calls = 0

    def prefetch(self, pairs):
        self.prefetch_calls += 1
        self.prefetched.extend(pairs)
        return len(pairs)

    def distance(self, a, b):
        if isinstance(self.value, dict):
            return self.value.get(tuple(sorted((a, b))))
        return self.value


class RegistryTests(unittest.TestCase):
    def test_all_seven_m4_checkers_registered_without_conflict(self):
        registry = discover()
        self.assertTrue(set(f"DFM-{n:02d}" for n in range(1, 8)) <= set(registry.ids()))
        self.assertFalse(registry.errors, [e.message for e in registry.errors])
        for cid in (f"DFM-{n:02d}" for n in range(1, 8)):
            self.assertEqual("M4 汪琪竣", registry.get(cid).owner)

    def test_nx_occurrence_part_ref_is_filename_not_part_id(self):
        model = model_with_gap(0.1)
        model.parts[0].occurrence_path = "ROOT/PART_A"
        model.parts[1].occurrence_path = "ROOT/PART_B"
        model.occurrences = [
            Occurrence("O1", name="PART_A", part_ref="assembly_part_a",
                       transform=[[1, 0, 0, 0], [0, 1, 0, 0],
                                  [0, 0, 1, 0], [0, 0, 0, 1]]),
            Occurrence("O2", name="PART_B", part_ref="assembly_part_b",
                       transform=[[1, 0, 0, 10.1], [0, 1, 0, 0],
                                  [0, 0, 1, 0], [0, 0, 0, 1]]),
        ]
        self.assertEqual((True, ""), MinClearanceChecker().applies(model, {}))

    def test_invalid_occurrence_transform_is_rejected(self):
        model = model_with_gap(0.1)
        model.parts[0].occurrence_path = "ROOT/PART_A"
        model.occurrences = [Occurrence("O1", name="PART_A", part_ref="part_a",
                                        transform=[[1, 0], [0, 1]])]
        ok, reason = MinClearanceChecker().applies(model, {})
        self.assertFalse(ok)
        self.assertIn("4×4", reason)

    def test_all_m4_default_thresholds_are_in_rulebook(self):
        rulebook = RuleBook.load(str(ROOT / "rules" / "dfm_default.json"))
        registry = discover()
        for check_id in (f"DFM-{n:02d}" for n in range(1, 8)):
            checker = registry.get(check_id)
            rule = rulebook.get(check_id)
            self.assertIsNotNone(rule, check_id)
            self.assertEqual(checker.default_params, rule.params, check_id)
            self.assertTrue(rule.source_standard, check_id)


class InterferenceTests(unittest.TestCase):
    def test_positive_negative_and_threshold_boundary(self):
        checker = InterferenceChecker()
        positive = model_with_gap(-1.0)
        findings = run_checker(checker, positive)
        self.assertEqual(1, len(findings))
        self.assertTrue({"A-F1", "B-F1"} <= set(findings[0].evidence.face_ids))
        self.assertTrue(findings[0].extra["coarse"])

        self.assertEqual([], run_checker(checker, model_with_gap(0.0)))  # 仅接触、无体积
        boundary = model_with_gap(1.0, {
            "interferences": [{"part_ids": ["A", "B"], "volume_mm3": 0.01,
                               "face_ids": ["A-F1", "B-F1"]}],
        })
        self.assertEqual([], run_checker(checker, boundary))


class ClearanceTests(unittest.TestCase):
    def test_positive_negative_and_boundary(self):
        checker = MinClearanceChecker()
        self.assertEqual(1, len(run_checker(checker, model_with_gap(0.1))))
        self.assertEqual(1, len(run_checker(checker, model_with_gap(0.3))))
        self.assertEqual([], run_checker(checker, model_with_gap(0.301)))

    def test_nx_exact_distance_overrides_bbox_and_is_batched(self):
        checker = MinClearanceChecker()
        proxy = _NxStub(0.4)
        self.assertEqual([], run_checker(checker, model_with_gap(0.1), nx=proxy))
        self.assertEqual([(101, 202), (101, 203)], proxy.prefetched)
        self.assertEqual(1, proxy.prefetch_calls)

        proxy = _NxStub({(101, 202): 0.4, (101, 203): 0.2})
        finding = run_checker(checker, model_with_gap(0.1), nx=proxy)[0]
        self.assertEqual("nx_minimum_distance", finding.extra["method"])
        self.assertEqual(["A-F1", "B-S1"], finding.evidence.face_ids)
        self.assertEqual(2, finding.extra["candidate_face_pair_count"])
        self.assertGreaterEqual(finding.confidence, 0.95)


class AlignmentTests(unittest.TestCase):
    def test_hole_alignment_positive_negative_and_boundary(self):
        checker = HoleAlignmentChecker()
        bad = model_with_gap(1.0, {"holes": hole_rows(offset=0.2)})
        self.assertEqual(1, len(run_checker(checker, bad)))
        good = model_with_gap(1.0, {"holes": hole_rows(offset=0.0)})
        self.assertEqual([], run_checker(checker, good))
        boundary = model_with_gap(1.0, {"holes": hole_rows(offset=0.1, diameter_b=4.1)})
        self.assertEqual([], run_checker(checker, boundary))

    def test_hole_slot_alignment_positive_negative_and_boundary(self):
        checker = HoleSlotAlignmentChecker()

        def make(offset):
            return model_with_gap(1.0, {
                "holes": [hole_rows()[0]],
                "slots": [{"feature_id": "S", "mate_id": "M1", "part_id": "B",
                           "center": [5 + offset, 5, 0], "axis": [0, 0, 1],
                           "width_mm": 5, "face_ids": ["B-S1"]}],
            })

        self.assertEqual(1, len(run_checker(checker, make(0.3))))
        self.assertEqual([], run_checker(checker, make(0.0)))
        self.assertEqual([], run_checker(checker, make(0.2)))


class FastenerTests(unittest.TestCase):
    def test_accessibility_positive_and_boundary(self):
        checker = FastenerAccessibilityChecker()
        bad = model_with_gap(1.0, {"fasteners": [fastener_row(available_tool_diameter_mm=9.9)]})
        self.assertEqual(1, len(run_checker(checker, bad)))
        boundary = model_with_gap(1.0, {"fasteners": [fastener_row()]})
        self.assertEqual([], run_checker(checker, boundary))

    def test_clearance_positive_and_boundary(self):
        checker = FastenerClearanceChecker()
        bad = model_with_gap(1.0, {"fasteners": [fastener_row(radial_clearance_mm=0.49)]})
        findings = run_checker(checker, bad)
        self.assertEqual(1, len(findings))
        self.assertEqual("radial", findings[0].extra["clearance_direction"])
        boundary = model_with_gap(1.0, {"fasteners": [fastener_row()]})
        self.assertEqual([], run_checker(checker, boundary))

    def test_engagement_steel_plastic_and_boundaries(self):
        checker = EngagementLengthChecker()
        steel_bad = model_with_gap(1.0, {"fasteners": [fastener_row(engagement_length_mm=3.9)]})
        self.assertEqual(1, len(run_checker(checker, steel_bad)))
        steel_boundary = model_with_gap(1.0, {"fasteners": [fastener_row(engagement_length_mm=4.0)]})
        self.assertEqual([], run_checker(checker, steel_boundary))
        plastic_bad = model_with_gap(1.0, {"fasteners": [fastener_row(
            material="plastic", engagement_length_mm=5.9)]})
        self.assertEqual(1, len(run_checker(checker, plastic_bad)))
        plastic_boundary = model_with_gap(1.0, {"fasteners": [fastener_row(
            material="plastic", engagement_length_mm=6.0)]})
        self.assertEqual([], run_checker(checker, plastic_boundary))


class SceneAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rulebook = RuleBook.load(str(ROOT / "rules" / "dfm_default.json"))
        cls.registry = discover()

    def _run_scene(self, name):
        model = ModelBundle.load(str(ROOT / "mockdata" / "models" / f"{name}.model.json"))
        return run(model, self.rulebook, self.registry,
                   only=["DFM-01", "DFM-02", "DFM-03", "DFM-04",
                         "DFM-05", "DFM-06", "DFM-07"])

    def test_demo_assembly_counts_and_dfm02_f1(self):
        result = self._run_scene("demo_asm")
        self.assertEqual(3, sum(f.check_item_id == "DFM-01" for f in result.findings))
        self.assertEqual(5, sum(f.check_item_id == "DFM-02" for f in result.findings))
        labels = load_labels(str(ROOT / "mockdata" / "labels" / "demo_asm.labels.json"))
        report = score(labels, [f for f in result.findings if f.check_item_id == "DFM-02"])
        self.assertEqual(1.0, report.items["DFM-02"].f1)

    def test_demo_normal_has_no_assembly_false_positive(self):
        result = self._run_scene("demo_normal")
        self.assertEqual([], result.findings)

    def test_demo_edge_threshold_and_dfm02_f1(self):
        result = self._run_scene("demo_edge")
        self.assertEqual(2, len(result.findings))
        labels = load_labels(str(ROOT / "mockdata" / "labels" / "demo_edge.labels.json"))
        report = score(labels, result.findings)
        self.assertEqual(1.0, report.items["DFM-02"].f1)

    def test_added_nx_cache_is_valid_but_not_an_assembly_fixture(self):
        cache = ROOT / ".cache" / "models" / "d398d69c30eca2f03d5f1cd6551000229780154c.json"
        if not cache.exists():
            self.skipTest("用户新增的 NX cache fixture 不在当前工作区")
        model = ModelBundle.load(str(cache))
        model.validate()
        self.assertEqual((1, 13, 19, 0),
                         (len(model.parts), len(model.faces), len(model.edges), len(model.occurrences)))
        result = run(model, self.rulebook, self.registry,
                     only=[f"DFM-{i:02d}" for i in range(1, 8)])
        m4_results = [r for r in result.results if r.check_item_id in
                      {f"DFM-{i:02d}" for i in range(1, 8)}]
        self.assertTrue(all(r.status == "missing_data" for r in m4_results))
        self.assertFalse(result.findings)


if __name__ == "__main__":
    unittest.main()
