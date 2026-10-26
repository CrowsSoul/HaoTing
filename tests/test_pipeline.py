# -*- coding: utf-8 -*-
"""管线测试：过滤、跳过、异常隔离、结果契约。"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nxdrp.checkers.base import BaseChecker  # noqa: E402
from nxdrp.contracts import ModelBundle, Rule, RuleBook  # noqa: E402
from nxdrp.pipeline import coverage, run  # noqa: E402
from nxdrp.registry import Registry, discover  # noqa: E402


def load_mock():
    return ModelBundle.load(os.path.join(ROOT, "mockdata", "models", "board_a.model.json"))


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.model = load_mock()
        self.reg = discover()
        self.book = RuleBook.load(os.path.join(ROOT, "rules", "dfm_default.json"))

    def test_expected_findings(self):
        result = run(self.model, self.book, self.reg)
        got = {}
        for f in result.findings:
            got[f.check_item_id] = got.get(f.check_item_id, 0) + 1
        self.assertEqual(got.get("DFM-31"), 2)
        self.assertEqual(got.get("DFM-32"), 1)
        self.assertEqual(got.get("DFM-02"), 1)

    def test_findings_are_valid_contracts(self):
        result = run(self.model, self.book, self.reg)
        for f in result.findings:
            f.validate()
            self.assertTrue(f.finding_id)
            self.assertIn(f.severity, ("P0", "P1", "P2", "P3"))
            self.assertTrue(f.evidence.face_ids or f.extra, f"{f.finding_id} 没有可追溯证据")

    def test_only_filter(self):
        result = run(self.model, self.book, self.reg, only=["DFM-31"])
        self.assertTrue(all(f.check_item_id == "DFM-31" for f in result.findings))
        statuses = {r.check_item_id: r.status for r in result.results}
        self.assertEqual(statuses["DFM-32"], "filtered")

    def test_skip_filter(self):
        result = run(self.model, self.book, self.reg, skip=["DFM-31"])
        self.assertFalse(any(f.check_item_id == "DFM-31" for f in result.findings))

    def test_disabled_rule_skipped(self):
        book = RuleBook.load(os.path.join(ROOT, "rules", "dfm_default.json"))
        for r in book.rules:
            if r.check_item_id == "DFM-31":
                r.enabled = False
        result = run(self.model, book, self.reg)
        self.assertFalse(any(f.check_item_id == "DFM-31" for f in result.findings))
        st = {r.check_item_id: r.status for r in result.results}
        self.assertEqual(st["DFM-31"], "skipped")

    def test_exception_isolated(self):
        reg = Registry()

        class Boom(BaseChecker):
            check_item_id = "DFM-01"
            name = "会爆的检查器"

            def check(self, ctx):
                raise ValueError("boom")

        class Good(BaseChecker):
            check_item_id = "DFM-31"
            name = "正常检查器"
            requires = ("cylindrical_faces",)
            default_params = {"standard_diameters": [8.0], "tolerance_mm": 0.01,
                              "max_hole_diameter_mm": 20.0, "min_hole_diameter_mm": 0.5}

            def check(self, ctx):
                for f in ctx.faces(face_type="cylindrical"):
                    d = f.radius_diameter * 2 if f.is_radius else f.radius_diameter
                    ctx.finding(part_refs=[f.part_id], measured_value=d, threshold_value=8.0,
                                message="x")
                return []

        reg.register(Boom(), "t")
        reg.register(Good(), "t")
        result = run(self.model, self.book, reg)
        st = {r.check_item_id: r.status for r in result.results}
        self.assertEqual(st["DFM-01"], "error")
        self.assertEqual(st["DFM-31"], "ok")
        self.assertGreater(len(result.findings), 0)

    def test_missing_data_skipped(self):
        reg = Registry()

        class NeedsNormals(BaseChecker):
            check_item_id = "DFM-13"
            name = "拔模角"
            requires = ("normals",)

            def check(self, ctx):
                raise AssertionError("不应被执行")

        reg.register(NeedsNormals(), "t")
        # 把法向抹掉，模拟「数据能力缺失」的模型
        model = load_mock()
        for f in model.faces:
            f.normal = None
            f.axis = None
        result = run(model, self.book, reg)
        r = result.results[0]
        self.assertEqual(r.status, "missing_data")
        self.assertIn("normals", r.reason)

    def test_coverage(self):
        cov = coverage(self.reg)
        self.assertGreaterEqual(cov["implemented"], 3)
        self.assertEqual(cov["total"], len(cov["rows"]))
        self.assertIn("M4", cov["by_owner"])
        self.assertEqual(cov["by_owner"]["M4"]["done"], 7)  # M4 DFM-01～DFM-07 已完成


class TestRealModelRegression(unittest.TestCase):
    """真实 NX 模型回归：用已解析的 ModelBundle 保证算法不漂移。

    样本来自 NX 2606 自带 Pressure Port.prt（已缓存为 JSON，无需 NX）。
    """

    def test_pressure_port(self):
        path = os.path.join(ROOT, "mockdata", "models", "pressure_port.model.json")
        if not os.path.isfile(path):
            self.skipTest("缺少 pressure_port 样本")
        model = ModelBundle.load(path)
        reg = discover()
        book = RuleBook.load(os.path.join(ROOT, "rules", "dfm_default.json"))
        result = run(model, book, reg)
        found = [x for x in result.findings if x.check_item_id == "DFM-31"]
        self.assertGreaterEqual(len(found), 1, "Pressure Port 上应能报出非标孔")
        self.assertAlmostEqual(found[0].measured_value, 7.65, places=2)
        for f in found:
            self.assertGreater(f.measured_value, 0.5)
            self.assertLess(f.measured_value, 30.0)
            self.assertIsNotNone(f.threshold_value)


class TestAssemblyModel(unittest.TestCase):
    """装配解析回归：两个组件、各自零件、变换矩阵带位移。"""

    def test_two_component_assembly(self):
        path = os.path.join(ROOT, "mockdata", "models", "asm_test.model.json")
        if not os.path.isfile(path):
            self.skipTest("缺少装配样本")
        m = ModelBundle.load(path)
        self.assertEqual(len(m.parts), 2)
        self.assertEqual(len(m.occurrences), 2)
        self.assertTrue(all(p.occurrence_path for p in m.parts))
        xs = sorted(round(o.transform[0][3], 1) for o in m.occurrences)
        self.assertIn(120.0, xs, "PART_B 应被放在 x=120")
        self.assertIn(0.0, xs)
        self.assertGreater(len(m.faces), 0)


class TestDemoScene(unittest.TestCase):
    """六组件场景：位置、间距、检查器产出都要对得上。"""

    def setUp(self):
        self.path = os.path.join(ROOT, "mockdata", "models", "demo_asm.model.json")
        if not os.path.isfile(self.path):
            self.skipTest("缺少 demo 场景样本")
        self.model = ModelBundle.load(self.path)

    def test_structure(self):
        self.assertEqual(len(self.parts if False else self.model.parts), 6)
        self.assertEqual(len(self.model.occurrences), 6)
        self.assertEqual(len(self.model.faces), 78)

    def test_placements(self):
        xs = {p.occurrence_path: round(p.bbox.xmin, 2) for p in self.model.parts}
        self.assertAlmostEqual(xs["A_BASE"], 0.0, places=2)
        self.assertAlmostEqual(xs["B_NEAR"], 30.15, places=2)
        self.assertAlmostEqual(xs["F_ALONE"], 150.0, places=2)

    def test_gap_between_a_and_b(self):
        parts = {p.occurrence_path: p for p in self.model.parts}
        gap = parts["B_NEAR"].bbox.xmin - parts["A_BASE"].bbox.xmax
        self.assertAlmostEqual(gap, 0.15, places=2)

    def test_checkers_fire(self):
        reg = discover()
        book = RuleBook.load(os.path.join(ROOT, "rules", "dfm_default.json"))
        result = run(self.model, book, reg)
        by_item = {}
        for f in result.findings:
            by_item[f.check_item_id] = by_item.get(f.check_item_id, 0) + 1
        self.assertGreaterEqual(by_item.get("DFM-02", 0), 3, "应报出多组间隙/干涉")
        # 每个零件有一个 Ø7.65 的非标孔；另一个 Ø4.45 落在 4.5±0.05 内，不报
        self.assertEqual(by_item.get("DFM-31", 0), 6, "6 个零件各 1 个非标孔")


class TestSceneVariants(unittest.TestCase):
    """纯负样本场景与阈值边界场景。"""

    def _run(self, name):
        path = os.path.join(ROOT, "mockdata", "models", name + ".model.json")
        if not os.path.isfile(path):
            self.skipTest("缺少 %s" % name)
        model = ModelBundle.load(path)
        book = RuleBook.load(os.path.join(ROOT, "rules", "dfm_default.json"))
        return model, run(model, book, discover())

    def test_normal_scene_has_no_clearance_alarm(self):
        """间距全是 20 mm，DFM-02 一条都不该报。"""
        model, result = self._run("demo_normal")
        self.assertEqual(len(model.parts), 5)
        gaps = [f for f in result.findings if f.check_item_id == "DFM-02"]
        self.assertEqual(gaps, [], "纯负样本场景出现误报")

    def test_edge_scene_straddles_threshold(self):
        """0.299 / 0.300 该报，0.302 不该报。"""
        model, result = self._run("demo_edge")
        self.assertEqual(len(model.parts), 4)
        gaps = sorted(f.measured_value for f in result.findings if f.check_item_id == "DFM-02")
        self.assertEqual(len(gaps), 2, gaps)
        self.assertAlmostEqual(gaps[0], 0.299, places=3)
        self.assertAlmostEqual(gaps[1], 0.300, places=3)
        self.assertTrue(all(g <= 0.3001 for g in gaps), "0.302 那一对不该被报出来")


if __name__ == "__main__":
    unittest.main(verbosity=2)
