# -*- coding: utf-8 -*-
"""PERF-01：会报、不报、刚好等于允许温升，以及 Mock / 真实模型。"""

import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nxdrp.checkers.m5_performance.perf01_current_temp import predict_raw  # noqa: E402
from nxdrp.contracts import BBox, Face, ModelBundle, Part, RuleBook  # noqa: E402
from nxdrp.pipeline import run  # noqa: E402
from nxdrp.registry import discover  # noqa: E402


def _pin(radius_mm: float, length_mm: float, material: str, model_id: str = "pin") -> ModelBundle:
    area = 2.0 * math.pi * radius_mm * length_mm
    return ModelBundle(
        model_id=model_id,
        parts=[
            Part(
                part_id="P01",
                name="TERMINAL",
                material=material,
                body_type="solid",
                bbox=BBox(0.0, -radius_mm, -radius_mm, length_mm, radius_mm, radius_mm),
            )
        ],
        faces=[
            Face(
                face_id="F1",
                part_id="P01",
                solid_face_type="cylindrical",
                radius_diameter=radius_mm,
                is_radius=True,
                area=area,
                axis=(1.0, 0.0, 0.0),
                cog=(length_mm / 2.0, 0.0, 0.0),
                point=(length_mm / 2.0, 0.0, 0.0),
            )
        ],
    )


class TestPerf01(unittest.TestCase):
    def setUp(self):
        self.reg = discover()
        self.book = RuleBook.load(os.path.join(ROOT, "rules", "dfm_default.json"))
        self.params = self.book.get("PERF-01").params

    def _run(self, model, book=None):
        return run(model, book or self.book, self.reg, only=["PERF-01"])

    def _status(self, result):
        return next(r for r in result.results if r.check_item_id == "PERF-01")

    def test_registered(self):
        self.assertIn("PERF-01", self.reg)
        bad = [e for e in self.reg.errors if "m5_performance" in e.source]
        self.assertEqual(bad, [])

    def test_alarm_when_rise_exceeds_limit(self):
        """细青铜端子在默认 16 A 下，温升应高于允许值 45 °C。"""
        model = _pin(0.5, 30.0, "CuSn6", "hot")
        pred = predict_raw(
            math.pi * 0.5 ** 2,
            30.0,
            self.params["materials"]["CuSn6"]["rho_ohm_m"],
            self.params["current_a"],
            self.params["convection_h_w_m2k"],
        )
        self.assertGreaterEqual(pred["delta_t_c"], self.params["max_rise_c"])
        result = self._run(model)
        self.assertEqual(self._status(result).status, "ok")
        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertEqual(finding.unit, "°C")
        self.assertEqual(finding.evidence.face_ids, ["F1"])
        self.assertIn("area_mm2", finding.suggestion.param_delta)
        self.assertIn("current_a", finding.suggestion.param_delta)
        self.assertLess(finding.extra["delta_t_low_c"], finding.extra["delta_t_high_c"])
        self.assertGreaterEqual(finding.measured_value, finding.threshold_value)

    def test_no_alarm_when_rise_is_under_limit(self):
        """粗铜端子、小电流，温升应低于 45 °C，不产出 Finding。"""
        model = _pin(2.2, 10.0, "Cu", "cold")
        pred = predict_raw(
            math.pi * 2.2 ** 2,
            10.0,
            self.params["materials"]["Cu"]["rho_ohm_m"],
            self.params["current_a"],
            self.params["convection_h_w_m2k"],
        )
        self.assertLess(pred["delta_t_c"], self.params["max_rise_c"])
        result = self._run(model)
        self.assertEqual(self._status(result).status, "ok")
        self.assertEqual(result.findings, [])

    def test_boundary_equal_to_limit_is_reported(self):
        """预测温升正好等于允许值时要报，比允许值略低时不报。"""
        model = _pin(1.2, 15.0, "CuZn37", "edge")
        pred = predict_raw(
            math.pi * 1.2 ** 2,
            15.0,
            self.params["materials"]["CuZn37"]["rho_ohm_m"],
            self.params["current_a"],
            self.params["convection_h_w_m2k"],
        )
        book = RuleBook.load(os.path.join(ROOT, "rules", "dfm_default.json"))
        book.get("PERF-01").params["max_rise_c"] = pred["delta_t_c"]
        result = self._run(model, book)
        self.assertEqual(len(result.findings), 1)

        book.get("PERF-01").params["max_rise_c"] = pred["delta_t_c"] + 0.05
        result = self._run(model, book)
        self.assertEqual(result.findings, [])

    def test_threshold_is_taken_from_rules(self):
        model = _pin(2.2, 10.0, "Cu", "cold-rule")
        book = RuleBook.load(os.path.join(ROOT, "rules", "dfm_default.json"))
        book.get("PERF-01").params["max_rise_c"] = 0.01
        result = self._run(model, book)
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].threshold_value, 0.01)

    def test_board_a_mock_runs(self):
        model = ModelBundle.load(os.path.join(ROOT, "mockdata", "models", "board_a.model.json"))
        result = self._run(model)
        status = self._status(result)
        self.assertEqual(status.status, "ok", status.reason)
        self.assertTrue(result.findings)
        finding = result.findings[0]
        self.assertEqual(finding.part_refs, ["P02"])
        self.assertTrue(finding.evidence.face_ids)
        self.assertEqual(finding.unit, "°C")

    def test_pressure_port_skips_without_material(self):
        model = ModelBundle.load(os.path.join(ROOT, "mockdata", "models", "pressure_port.model.json"))
        result = self._run(model)
        status = self._status(result)
        self.assertEqual(status.status, "skipped")
        self.assertIn("材料", status.reason)
        self.assertEqual(result.findings, [])

    def test_missing_cylinder_skips(self):
        model = ModelBundle(
            model_id="no-cyl",
            parts=[Part(part_id="P01", name="TERMINAL", material="Cu", body_type="solid")],
            faces=[Face(face_id="F1", part_id="P01", solid_face_type="planar")],
        )
        result = self._run(model)
        status = self._status(result)
        self.assertEqual(status.status, "skipped")
        self.assertIn("圆柱", status.reason)


if __name__ == "__main__":
    unittest.main()
