# -*- coding: utf-8 -*-
"""评测框架测试：命中、漏报、误报、负样本、容差边界。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nxdrp.contracts import Evidence, Finding
from nxdrp.eval import Label, LabelSet, match, score


def F(fid, item, loc, parts=("P01",), faces=()):
    return Finding(
        finding_id=fid, check_item_id=item, part_refs=list(parts),
        location=loc, evidence=Evidence(face_ids=list(faces)),
    )


def L(lid, item, loc=None, expected="defect", parts=("P01",), tol=2.0, faces=()):
    return Label(label_id=lid, check_item_id=item, expected=expected,
                 part_refs=list(parts), location=loc, tolerance_mm=tol, face_ids=list(faces))


class TestMatch(unittest.TestCase):
    def test_perfect(self):
        ls = LabelSet(model_id="m", labels=[L("L1", "DFM-31", (0, 0, 0))])
        res = match(ls, [F("F1", "DFM-31", (0, 0, 0))])
        self.assertEqual(len(res.matched), 1)
        self.assertEqual(res.missed, [])
        self.assertEqual(res.extra, [])

    def test_missed(self):
        ls = LabelSet(model_id="m", labels=[L("L1", "DFM-31", (0, 0, 0))])
        res = match(ls, [])
        self.assertEqual(len(res.missed), 1)

    def test_extra(self):
        ls = LabelSet(model_id="m", labels=[])
        res = match(ls, [F("F1", "DFM-31", (0, 0, 0))])
        self.assertEqual(len(res.extra), 1)

    def test_wrong_item_not_matched(self):
        ls = LabelSet(model_id="m", labels=[L("L1", "DFM-31", (0, 0, 0))])
        res = match(ls, [F("F1", "DFM-32", (0, 0, 0))])
        self.assertEqual(len(res.missed), 1)
        self.assertEqual(len(res.extra), 1)

    def test_part_mismatch(self):
        ls = LabelSet(model_id="m", labels=[L("L1", "DFM-31", (0, 0, 0), parts=("P01",))])
        res = match(ls, [F("F1", "DFM-31", (0, 0, 0), parts=("P02",))])
        self.assertEqual(len(res.missed), 1)

    def test_tolerance_boundary(self):
        ls = LabelSet(model_id="m", labels=[L("L1", "DFM-31", (0, 0, 0), tol=1.0)])
        inside = match(ls, [F("F1", "DFM-31", (0.6, 0.6, 0.0))])
        outside = match(ls, [F("F2", "DFM-31", (1.0, 1.0, 0.0))])
        self.assertEqual(len(inside.matched), 1)     # 0.85 < 1.0
        self.assertEqual(len(outside.missed), 1)     # 1.41 > 1.0

    def test_one_label_one_finding(self):
        """两条预测抢一条标注时，只算一次命中，另一条算误报。"""
        ls = LabelSet(model_id="m", labels=[L("L1", "DFM-31", (0, 0, 0))])
        res = match(ls, [F("F1", "DFM-31", (0.1, 0, 0)), F("F2", "DFM-31", (0.2, 0, 0))])
        self.assertEqual(len(res.matched), 1)
        self.assertEqual(len(res.extra), 1)

    def test_negative_hit(self):
        ls = LabelSet(model_id="m", labels=[L("N1", "DFM-31", (0, 0, 0), expected="ok", tol=1.0)])
        res = match(ls, [F("F1", "DFM-31", (0.2, 0, 0))])
        self.assertEqual(len(res.negative_hits), 1)
        self.assertEqual(res.extra, [])

    def test_face_id_match(self):
        ls = LabelSet(model_id="m", labels=[L("L1", "DFM-31", None, faces=("F1",))])
        res = match(ls, [F("F1", "DFM-31", (99, 99, 99), faces=("F1",))])
        self.assertEqual(len(res.matched), 1)


class TestScore(unittest.TestCase):
    def test_metrics(self):
        ls = LabelSet(model_id="m", labels=[
            L("L1", "DFM-31", (0, 0, 0)),
            L("L2", "DFM-31", (5, 0, 0)),
        ])
        rep = score(ls, [F("F1", "DFM-31", (0, 0, 0))])
        it = rep.items["DFM-31"]
        self.assertEqual((it.tp, it.fp, it.fn), (1, 0, 1))
        self.assertAlmostEqual(it.precision, 1.0)
        self.assertAlmostEqual(it.recall, 0.5)
        self.assertAlmostEqual(it.f1, 2 / 3, places=4)

    def test_false_positive_rate(self):
        ls = LabelSet(model_id="m", labels=[L("L1", "DFM-31", (0, 0, 0))])
        rep = score(ls, [F("F1", "DFM-31", (0, 0, 0)), F("F2", "DFM-31", (50, 0, 0))])
        self.assertEqual(rep.fp, 1)
        self.assertAlmostEqual(rep.false_positive_rate, 0.5)

    def test_unscored_items(self):
        ls = LabelSet(model_id="m", labels=[L("L1", "DFM-31", (0, 0, 0))])
        rep = score(ls, [F("F1", "DFM-31", (0, 0, 0)), F("F9", "DFM-99", (0, 0, 0))])
        self.assertIn("DFM-99", rep.unscored_items)

    def test_macro_f1(self):
        ls = LabelSet(model_id="m", labels=[
            L("L1", "DFM-31", (0, 0, 0)),
            L("L2", "DFM-32", (9, 9, 9)),
        ])
        rep = score(ls, [F("F1", "DFM-31", (0, 0, 0))])
        # DFM-31 F1=1，DFM-32 F1=0 -> macro 0.5
        self.assertAlmostEqual(rep.macro_f1, 0.5)

    def test_high_risk_recall(self):
        ls = LabelSet(model_id="m", labels=[L("L1", "DFM-31", (0, 0, 0)), L("L2", "DFM-02", (1, 1, 1))])
        rep = score(ls, [F("F1", "DFM-31", (0, 0, 0))], high_risk_items=["DFM-02"])
        self.assertAlmostEqual(rep.match_detail["high_risk_recall"], 0.0)

    def test_empty(self):
        rep = score(LabelSet(model_id="m"), [])
        self.assertEqual(rep.tp, 0)
        self.assertIsNone(rep.macro_f1, "没有正样本时 macro-F1 应为 None，不是 0")

    def test_pure_negative_scene(self):
        """纯负样本场景：没有正样本可算，但误报率必须能算。"""
        ls = LabelSet(model_id="m", labels=[
            L("N1", "DFM-02", (0, 0, 0), expected="ok"),
            L("N2", "DFM-02", (50, 0, 0), expected="ok"),
        ])
        rep = score(ls, [])
        self.assertIsNone(rep.macro_f1)
        self.assertEqual(rep.false_positive_rate, 0.0)
        self.assertEqual(rep.fp, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
