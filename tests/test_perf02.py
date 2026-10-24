# -*- coding: utf-8 -*-
"""PERF-02 插拔力：会报、不报、正好卡在上限，以及缺少材料/尺寸越界时跳过。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nxdrp.checkers.m5_performance.force_model import MODEL_PATH, load  # noqa: E402
from nxdrp.checkers.m5_performance.force_physics import FEATURE_NAMES  # noqa: E402
from nxdrp.checkers.m5_performance.perf02_insertion_force import predict_insertion  # noqa: E402
from nxdrp.contracts import BBox, ModelBundle, Part, RuleBook  # noqa: E402
from nxdrp.pipeline import run  # noqa: E402
from nxdrp.registry import discover  # noqa: E402


def _spring(length_mm: float, width_mm: float, thickness_mm: float, material: str, model_id: str = "spring") -> ModelBundle:
    return ModelBundle(
        model_id=model_id,
        parts=[
            Part(
                part_id="P01",
                name="CONTACT_SPRING",
                material=material,
                body_type="solid",
                bbox=BBox(0.0, 0.0, 0.0, length_mm, width_mm, thickness_mm),
            )
        ],
        faces=[],
    )


class TestPerf02(unittest.TestCase):
    def setUp(self):
        self.reg = discover()
        self.book = RuleBook.load(os.path.join(ROOT, "rules", "dfm_default.json"))
        self.params = self.book.get("PERF-02").params

    def _run(self, model, book=None):
        return run(model, book or self.book, self.reg, only=["PERF-02"])

    def _status(self, result):
        return next(r for r in result.results if r.check_item_id == "PERF-02")

    def test_registered(self):
        self.assertIn("PERF-02", self.reg)
        bad = [e for e in self.reg.errors if "m5_performance" in e.source]
        self.assertEqual(bad, [])

    def test_alarm_when_insertion_too_high(self):
        """粗短簧片：正压力大，插入力应超过上限。"""
        model = _spring(6.0, 4.0, 0.6, "CuSn6", "stiff")
        result = self._run(model)
        status = self._status(result)
        self.assertEqual(status.status, "ok", status.reason)
        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertEqual(finding.unit, "N")
        self.assertGreaterEqual(finding.measured_value, finding.threshold_value)
        # 减过盈量或者加长簧片，两条建议至少给出一条，且都要能落到 params 上
        self.assertTrue({"overlap_mm", "length_mm"} & set(finding.suggestion.param_delta))
        self.assertIn("insertion_force_low_n", finding.extra)
        self.assertTrue(finding.evidence.face_ids or finding.extra)

    def test_no_alarm_in_working_range(self):
        """中等刚度：插入力低于上限、拔出力高于下限，一条都不报。"""
        model = _spring(8.0, 2.0, 0.5, "CuSn6", "normal")
        result = self._run(model)
        status = self._status(result)
        self.assertEqual(status.status, "ok", status.reason)
        self.assertEqual(result.findings, [])

    def test_boundary_equal_to_limit_is_reported(self):
        """预测插入力正好等于上限时要报，比上限略高（更宽松）时不报。"""
        model = _spring(8.0, 2.0, 0.5, "CuSn6", "edge")
        pred = predict_insertion(8.0, 2.0, 0.5, "CuSn6", self.params)
        self.assertTrue(pred["ok"], pred.get("reason"))

        book = RuleBook.load(os.path.join(ROOT, "rules", "dfm_default.json"))
        book.get("PERF-02").params["insertion_force_max_n"] = pred["insertion_force_n"]
        result = self._run(model, book)
        self.assertEqual(len(result.findings), 1)

        book.get("PERF-02").params["insertion_force_max_n"] = pred["insertion_force_n"] + 0.01
        result = self._run(model, book)
        self.assertEqual(result.findings, [])

    def test_threshold_is_taken_from_rules(self):
        model = _spring(8.0, 2.0, 0.5, "CuSn6", "tight-rule")
        book = RuleBook.load(os.path.join(ROOT, "rules", "dfm_default.json"))
        book.get("PERF-02").params["insertion_force_max_n"] = 0.01
        result = self._run(model, book)
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].threshold_value, 0.01)

    def test_withdrawal_too_low_is_reported(self):
        """太软的簧片：插入力合格但拔出力不足，应报 P3。"""
        model = _spring(15.0, 1.0, 0.2, "CuSn6", "soft")
        result = self._run(model)
        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertEqual(finding.severity, "P3")
        self.assertLess(finding.measured_value, finding.threshold_value)
        self.assertEqual(finding.unit, "N")

    def test_predict_returns_numbers(self):
        out = predict_insertion(8.0, 2.0, 0.5, "CuSn6", self.params)
        self.assertTrue(out["ok"], out.get("reason"))
        self.assertGreater(out["insertion_force_n"], 0.0)
        self.assertGreater(out["withdrawal_force_n"], 0.0)
        self.assertLess(out["insertion_force_low_n"], out["insertion_force_high_n"])
        self.assertFalse(out["alarm"])

    def test_predict_rejects_unknown_material(self):
        out = predict_insertion(8.0, 2.0, 0.5, "PA66", self.params)
        self.assertFalse(out["ok"])
        self.assertIn("材料", out["reason"])

    def test_predict_rejects_out_of_range(self):
        out = predict_insertion(80.0, 2.0, 0.5, "CuSn6", self.params)
        self.assertFalse(out["ok"])
        self.assertIn("长度", out["reason"])

    def test_skips_without_material(self):
        model = _spring(8.0, 2.0, 0.5, "", "no-mat")
        result = self._run(model)
        status = self._status(result)
        self.assertEqual(status.status, "skipped")
        self.assertIn("材料", status.reason)
        self.assertEqual(result.findings, [])

    def test_skips_when_dimension_out_of_range(self):
        model = _spring(100.0, 100.0, 100.0, "CuSn6", "huge")
        result = self._run(model)
        status = self._status(result)
        self.assertEqual(status.status, "skipped")
        self.assertIn("厚度", status.reason)

    def test_model_split_is_three_way(self):
        self.assertTrue(os.path.isfile(MODEL_PATH))
        model = load(MODEL_PATH)
        self.assertEqual(tuple(model["feature_names"]), FEATURE_NAMES)
        split = model["split"]
        self.assertGreater(split["test"], 0)
        self.assertGreater(split["cal"], 0)
        self.assertLess(model["q_low"], model["q_high"])
        self.assertIn("coverage", model["metrics"])


if __name__ == "__main__":
    unittest.main()
