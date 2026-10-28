# -*- coding: utf-8 -*-
"""M2 模块测试：正例、负例、阈值边界和表面路径。"""

from __future__ import annotations

import unittest
from pathlib import Path

from ...contracts import BBox, Face, ModelBundle, Part, Rule, RuleBook
from ...pipeline import run
from ...registry import Registry
from .autocrear_compare import compare
from .engine import (
    ThresholdUnavailable,
    clearance_threshold_mm,
    creepage_threshold_mm,
    merged_safety_params,
)
from .measure_safety import measure
from .saf01_clearance import ClearanceChecker
from .saf02_creepage import CreepageChecker
from .saf03_compliance import SafetyComplianceChecker
from .saf04_suggestion import SafetySuggestionChecker


def safety_model(clearance_mm=2.5, path_length=4.0):
    model = ModelBundle(model_id="m2-test", nx_version="mock", units="mm")
    model.parts = [
        Part("P01", name="HV_TERMINAL", material="Cu", bbox=BBox(0, 0, 0, 1, 1, 1)),
        Part("P02", name="LV_TERMINAL", material="Cu", bbox=BBox(4, 0, 0, 5, 1, 1)),
        Part("P03", name="INSULATOR", material="PA66", bbox=BBox(0, -1, -1, 5, 2, 0)),
    ]
    model.faces = [
        Face("F1", "P01", tag=1, solid_face_type="planar", cog=(1, 0, 0),
             bbox=BBox(1, 0, 0, 1, 1, 1), edge_count=4),
        Face("F2", "P02", tag=2, solid_face_type="planar", cog=(4, 0, 0),
             bbox=BBox(4, 0, 0, 4, 1, 1), edge_count=4),
        Face("F3", "P03", tag=3, solid_face_type="planar", cog=(2.5, 0, 0),
             bbox=BBox(0, -1, 0, 5, 2, 0), edge_count=4),
    ]
    model.meta["safety"] = {
        "networks": [
            {"network_id": "HV", "part_ids": ["P01"], "face_ids": ["F1"], "potential_v": 400},
            {"network_id": "LV", "part_ids": ["P02"], "face_ids": ["F2"], "potential_v": 0},
        ],
        "network_pairs": [["HV", "LV"]],
        "clearance_measurements": [
            {
                "network_a": "HV", "network_b": "LV", "distance_mm": clearance_mm,
                "p1": [1, 0, 0], "p2": [4, 0, 0], "face_ids": ["F1", "F2"],
                "method": "unit-test",
            }
        ],
        "surface_graph": {
            "nodes": [[0, 0, 0], [path_length / 2, 0, 0], [path_length, 0, 0]],
            "edges": [[0, 1], [1, 2]],
            "terminals": {"HV": [0], "LV": [2]},
        },
    }
    return model


def execute_all(model, clearance=3.0, creepage=5.0, margin=0.5):
    registry = Registry()
    for checker in (
        ClearanceChecker(), CreepageChecker(),
        SafetyComplianceChecker(), SafetySuggestionChecker(),
    ):
        registry.register(checker, "test")
    rules = RuleBook(rules=[
        Rule("R-SAF-01", "SAF-01", process_type="safety", severity="P0",
             params={"min_clearance_mm": clearance}),
        Rule("R-SAF-02", "SAF-02", process_type="safety", severity="P0",
             params={"min_creepage_mm": creepage}),
        Rule("R-SAF-03", "SAF-03", process_type="safety", severity="P1",
             params={"min_clearance_mm": clearance, "min_creepage_mm": creepage}),
        Rule("R-SAF-04", "SAF-04", process_type="safety", severity="P2",
             params={
                 "min_clearance_mm": clearance,
                 "min_creepage_mm": creepage,
                 "target_margin_mm": margin,
             }),
    ])
    return run(model, rules, registry)


def execute(model, checker, params):
    registry = Registry()
    registry.register(checker, "test")
    rule = Rule(
        rule_id=f"R-{checker.check_item_id}",
        check_item_id=checker.check_item_id,
        process_type="safety",
        severity="P0",
        params=params,
    )
    return run(model, RuleBook(rules=[rule]), registry)


class TestClearanceChecker(unittest.TestCase):
    def test_reports_below_threshold(self):
        result = execute(safety_model(clearance_mm=2.5), ClearanceChecker(), {"min_clearance_mm": 3.0})
        self.assertEqual(len(result.findings), 1)
        self.assertAlmostEqual(result.findings[0].measured_value, 2.5)
        self.assertEqual(result.findings[0].evidence.face_ids, ["F1", "F2"])

    def test_does_not_report_above_threshold(self):
        result = execute(safety_model(clearance_mm=3.1), ClearanceChecker(), {"min_clearance_mm": 3.0})
        self.assertEqual(result.findings, [])

    def test_equal_threshold_is_compliant(self):
        result = execute(safety_model(clearance_mm=3.0), ClearanceChecker(), {"min_clearance_mm": 3.0})
        self.assertEqual(result.findings, [])

    def test_derives_face_ids_from_network_parts(self):
        model = safety_model(clearance_mm=2.5)
        for network in model.meta["safety"]["networks"]:
            network.pop("face_ids")
        model.meta["safety"]["clearance_measurements"][0].pop("face_ids")
        result = execute(model, ClearanceChecker(), {"min_clearance_mm": 3.0})
        self.assertEqual(result.findings[0].evidence.face_ids, ["F1", "F2"])


class TestCreepageChecker(unittest.TestCase):
    def test_reports_and_returns_path(self):
        result = execute(safety_model(path_length=4.0), CreepageChecker(), {"min_creepage_mm": 5.0})
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(len(result.findings[0].path_points), 3)
        self.assertAlmostEqual(result.findings[0].measured_value, 4.0)

    def test_does_not_report_above_threshold(self):
        result = execute(safety_model(path_length=5.1), CreepageChecker(), {"min_creepage_mm": 5.0})
        self.assertEqual(result.findings, [])

    def test_equal_threshold_is_compliant(self):
        result = execute(safety_model(path_length=5.0), CreepageChecker(), {"min_creepage_mm": 5.0})
        self.assertEqual(result.findings, [])

    def test_applies_explicit_feature_edge_adjustment(self):
        model = safety_model(path_length=4.0)
        model.meta["safety"]["surface_graph"]["edges"] = [
            {"a": 0, "b": 1, "kind": "groove", "length_factor": 1.5},
            {"a": 1, "b": 2, "kind": "chamfer"},
        ]
        result = execute(model, CreepageChecker(), {"min_creepage_mm": 6.0})
        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertAlmostEqual(finding.measured_value, 5.0)
        self.assertEqual(finding.extra["path_rules"]["adjusted_edge_count"], 1)
        self.assertEqual(finding.extra["path_rules"]["feature_kinds"], ["chamfer", "groove"])

    def test_disconnected_surface_graph_is_skipped_with_reason(self):
        model = safety_model(path_length=4.0)
        model.meta["safety"]["surface_graph"]["edges"] = [
            [0, 1],
            {"a": 1, "b": 2, "kind": "rib", "blocked": True},
        ]
        result = execute(model, CreepageChecker(), {"min_creepage_mm": 5.0})
        self.assertEqual(result.findings, [])
        self.assertEqual(result.results[0].status, "skipped")
        self.assertIn("路径", result.results[0].reason)


class TestSummaryAndSuggestion(unittest.TestCase):
    def test_four_checkers_work_together(self):
        result = execute_all(safety_model(clearance_mm=2.5, path_length=4.0))
        by_item = {item.check_item_id: item for item in result.findings}
        self.assertEqual(set(by_item), {"SAF-01", "SAF-02", "SAF-03", "SAF-04"})
        suggestion = by_item["SAF-04"].suggestion
        self.assertAlmostEqual(suggestion.param_delta["target_clearance_mm"], 3.5)
        self.assertAlmostEqual(suggestion.param_delta["target_creepage_mm"], 5.5)

    def test_saf03_has_no_finding_when_all_items_comply(self):
        result = execute_all(safety_model(clearance_mm=3.1, path_length=5.1))
        self.assertNotIn("SAF-03", {item.check_item_id for item in result.findings})

    def test_saf03_exact_threshold_is_compliant(self):
        result = execute_all(safety_model(clearance_mm=3.0, path_length=5.0))
        self.assertNotIn("SAF-03", {item.check_item_id for item in result.findings})

    def test_saf04_reports_quantitative_targets_for_failure(self):
        result = execute_all(safety_model(clearance_mm=2.5, path_length=4.0))
        finding = next(item for item in result.findings if item.check_item_id == "SAF-04")
        self.assertAlmostEqual(finding.suggestion.param_delta["clearance_increase_mm"], 1.0)
        self.assertAlmostEqual(finding.suggestion.param_delta["creepage_increase_mm"], 1.5)

    def test_saf04_has_no_finding_when_all_items_comply(self):
        result = execute_all(safety_model(clearance_mm=3.1, path_length=5.1))
        self.assertNotIn("SAF-04", {item.check_item_id for item in result.findings})

    def test_saf04_exact_threshold_needs_no_suggestion(self):
        result = execute_all(safety_model(clearance_mm=3.0, path_length=5.0))
        self.assertNotIn("SAF-04", {item.check_item_id for item in result.findings})


class TestIecRuleTables(unittest.TestCase):
    def test_clearance_uses_f1_f2_for_all_pollution_degrees(self):
        base = {
            "rated_voltage_v": 50,
            "overvoltage_category": "I",
            "field_condition": "case_a",
            "altitude_m": 2000,
        }
        expected = {1: 0.01, 2: 0.2, 3: 0.8, 4: 1.6}
        for pollution, value in expected.items():
            with self.subTest(pollution=pollution):
                threshold, source = clearance_threshold_mm({
                    **base, "pollution_degree": pollution,
                })
                self.assertAlmostEqual(threshold, value)
                self.assertIn("Table F.1", source)
                self.assertIn("Table F.2", source)

    def test_creepage_uses_f5_for_pd1_pd2_pd3(self):
        expected = {1: 1.0, 2: 2.8, 3: 5.6}
        for pollution, value in expected.items():
            with self.subTest(pollution=pollution):
                threshold, source = creepage_threshold_mm({
                    "working_voltage_v": 400,
                    "pollution_degree": pollution,
                    "material_group": "II",
                })
                self.assertAlmostEqual(threshold, value)
                self.assertIn("Table F.5", source)

    def test_creepage_pd4_is_explicitly_unavailable(self):
        with self.assertRaisesRegex(ThresholdUnavailable, "4.5.3"):
            creepage_threshold_mm({
                "working_voltage_v": 400,
                "pollution_degree": 4,
                "material_group": "II",
            })

    def test_cti_derives_material_group(self):
        threshold, _ = creepage_threshold_mm({
            "working_voltage_v": 400,
            "pollution_degree": 2,
            "cti": 500,
        })
        self.assertAlmostEqual(threshold, 2.8)

    def test_model_profile_overrides_generic_rule_defaults(self):
        model = safety_model()
        model.meta["safety"]["profile"] = {
            "rated_voltage_v": 50,
            "pollution_degree": 1,
        }
        merged = merged_safety_params(model, {
            "rated_voltage_v": 400,
            "pollution_degree": 2,
            "iec_profile_path": "rules/iec_60664_1_profiles.json",
        })
        self.assertEqual(merged["rated_voltage_v"], 50)
        self.assertEqual(merged["pollution_degree"], 1)
        self.assertIn("iec_profile_path", merged)

    def test_controlled_mock_exports_measurements(self):
        root = Path(__file__).resolve().parents[3]
        result = measure(
            str(
                root / "nxdrp" / "checkers" / "m2_safety"
                / "m2_safety_mock.model.json"
            ),
            str(root / "rules" / "dfm_default.json"),
        )
        self.assertEqual(result["model_id"], "m2_safety")
        self.assertEqual(len(result["measurements"]), 2)
        clearance, creepage = result["measurements"]
        self.assertEqual(clearance["point_id"], "HV-LV-CLEARANCE-01")
        self.assertEqual(clearance["face_ids"], ["F101", "F202"])
        self.assertAlmostEqual(clearance["threshold_mm"], 3.0)
        self.assertFalse(clearance["compliant"])
        self.assertAlmostEqual(creepage["threshold_mm"], 2.8)
        self.assertTrue(creepage["compliant"])


class TestAutoCrearComparison(unittest.TestCase):
    def test_contract_accuracy_metrics(self):
        actual = [
            {
                "kind": "clearance", "network_a": "HV", "network_b": "LV",
                "measured_mm": 2.97, "threshold_mm": 3.0,
            },
            {
                "kind": "creepage", "network_a": "HV", "network_b": "LV",
                "measured_mm": 4.05, "threshold_mm": 5.0,
            },
        ]
        reference = [
            {
                "kind": "clearance", "network_a": "LV", "network_b": "HV",
                "measured_mm": 3.00, "threshold_mm": 3.0,
            },
            {
                "kind": "creepage", "network_a": "HV", "network_b": "LV",
                "measured_mm": 4.00, "threshold_mm": 5.0,
            },
        ]
        result = compare(actual, reference)
        self.assertTrue(result["passes_99_percent_distance"])
        self.assertFalse(result["passes_100_percent_compliance"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
