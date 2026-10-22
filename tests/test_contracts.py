# -*- coding: utf-8 -*-
"""契约层测试：序列化、校验、边界。"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nxdrp.contracts import BBox, Face, Finding, ModelBundle, Part, Rule, RuleBook
from nxdrp.errors import ContractError


class TestModelBundle(unittest.TestCase):
    def _model(self):
        m = ModelBundle(model_id="t1", units="mm")
        m.parts.append(Part(part_id="P01", bbox=BBox(0, 0, 0, 10, 10, 10)))
        m.faces.append(Face(face_id="F1", part_id="P01", solid_face_type="planar"))
        m.validate()
        return m

    def test_roundtrip(self):
        m = self._model()
        again = ModelBundle.from_dict(json.loads(json.dumps(m.to_dict())))
        self.assertEqual(again.model_id, m.model_id)
        self.assertEqual(len(again.faces), 1)
        self.assertEqual(again.parts[0].bbox.xmax, 10)

    def test_bbox_helpers(self):
        b = BBox(0, 0, 0, 3, 4, 0)
        self.assertEqual(b.size, (3.0, 4.0, 0.0))
        self.assertAlmostEqual(b.diagonal, 5.0)

    def test_bbox_union(self):
        u = BBox.union([BBox(0, 0, 0, 1, 1, 1), BBox(2, 2, 2, 3, 3, 3)])
        self.assertEqual((u.xmin, u.xmax), (0, 3))

    def test_orphan_face_rejected(self):
        m = ModelBundle(model_id="t2")
        m.parts.append(Part(part_id="P01"))
        m.faces.append(Face(face_id="F1", part_id="P99"))
        with self.assertRaises(ContractError) as ctx:
            m.validate()
        self.assertIn("P99", str(ctx.exception))

    def test_duplicate_part_rejected(self):
        m = ModelBundle(model_id="t3")
        m.parts.extend([Part(part_id="P01"), Part(part_id="P01")])
        with self.assertRaises(ContractError):
            m.validate()

    def test_bad_units_rejected(self):
        m = ModelBundle(model_id="t4", units="furlong")
        with self.assertRaises(ContractError):
            m.validate()

    def test_unknown_field_rejected_on_load(self):
        with self.assertRaises(ContractError):
            ModelBundle.from_dict({"model_id": "x", "bogus_field": 1})

    def test_faces_of_filter(self):
        m = self._model()
        m.faces.append(Face(face_id="F2", part_id="P01", solid_face_type="cylindrical"))
        self.assertEqual(len(m.faces_of(face_type="cylindrical")), 1)
        self.assertEqual(len(m.faces_of("P01")), 2)
        self.assertEqual(len(m.faces_of("P02")), 0)

    def test_digest_stable(self):
        a = self._model().content_digest()
        b = self._model().content_digest()
        self.assertEqual(a, b)


class TestFinding(unittest.TestCase):
    def test_deviation_autofilled(self):
        f = Finding(finding_id="x", check_item_id="DFM-31", measured_value=7.65, threshold_value=8.0)
        f.validate()
        self.assertAlmostEqual(f.deviation, -0.35)

    def test_bad_severity_rejected(self):
        f = Finding(finding_id="x", check_item_id="DFM-31", severity="P9")
        with self.assertRaises(ContractError):
            f.validate()

    def test_confidence_range(self):
        f = Finding(finding_id="x", check_item_id="DFM-31", confidence=1.5)
        with self.assertRaises(ContractError):
            f.validate()

    def test_missing_check_item_rejected(self):
        f = Finding(finding_id="x", check_item_id="")
        with self.assertRaises(ContractError):
            f.validate()

    def test_roundtrip(self):
        f = Finding(finding_id="F-1", check_item_id="DFM-02", measured_value=0.15, threshold_value=0.3)
        f.validate()
        again = Finding.from_dict(json.loads(json.dumps(f.to_dict())))
        self.assertAlmostEqual(again.deviation, -0.15)


class TestRuleBook(unittest.TestCase):
    def test_duplicate_item_rejected(self):
        book = RuleBook(rules=[Rule("r1", "DFM-01"), Rule("r2", "DFM-01")])
        with self.assertRaises(ContractError):
            book.validate()

    def test_lookup(self):
        book = RuleBook(rules=[Rule("r1", "DFM-01", params={"min_clearance_mm": 0.5})])
        self.assertEqual(book.get("DFM-01").params["min_clearance_mm"], 0.5)
        self.assertIsNone(book.get("DFM-99"))

    def test_save_load(self):
        import tempfile

        book = RuleBook(name="t", rules=[Rule("r1", "DFM-01")])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.json")
            book.save(p)
            self.assertEqual(RuleBook.load(p).name, "t")


if __name__ == "__main__":
    unittest.main(verbosity=2)
