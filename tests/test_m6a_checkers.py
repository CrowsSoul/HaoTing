# -*- coding: utf-8 -*-
"""八个 M6A checker 的流程基线测试（含现有 Mock 与合成夹具）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nxdrp.contracts import ModelBundle, RuleBook
from nxdrp.pipeline import run
from nxdrp.registry import discover

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "bent_sheet.model.json"
MODELS = REPO_ROOT / "mockdata" / "models"
M6A_IDS = [f"DFM-{i}" for i in range(19, 27)]

REGISTRY = discover()
RULEBOOK = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))


def model_path(name: str) -> str:
    if name == "bent_sheet":
        return str(FIXTURE)
    return str(MODELS / f"{name}.model.json")


def run_m6a(name: str):
    model = ModelBundle.load(model_path(name))
    return run(model, RULEBOOK, REGISTRY, only=M6A_IDS)


def counts(result) -> dict[str, int]:
    out = {cid: 0 for cid in M6A_IDS}
    for finding in result.findings:
        out[finding.check_item_id] += 1
    return out


def statuses(result) -> dict[str, str]:
    return {r.check_item_id: r.status for r in result.results if r.check_item_id in M6A_IDS}


class ExpectedMatrixTests(unittest.TestCase):
    """与计划中的预期矩阵一致；实现改动时先更新这里再改代码。"""

    EXPECTED_COUNTS = {
        "plate_holes": {"DFM-22": 4},
        "deep_slot": {"DFM-23": 1},
        "bosses": {"DFM-26": 1},
        "thin_wall": {},
        "board_a": {"DFM-20": 1, "DFM-22": 1},
        "bent_sheet": {
            "DFM-19": 1,
            "DFM-20": 1,
            "DFM-21": 1,
            "DFM-22": 3,
            "DFM-24": 1,
            "DFM-25": 1,
        },
    }

    def test_expected_counts(self):
        for name, expected in self.EXPECTED_COUNTS.items():
            with self.subTest(model=name):
                result = run_m6a(name)
                actual = counts(result)
                for cid in M6A_IDS:
                    self.assertEqual(
                        actual[cid], expected.get(cid, 0),
                        f"{name} {cid} 期望 {expected.get(cid, 0)} 条，实际 {actual[cid]} 条",
                    )
                self.assertFalse(
                    [r for r in result.results if r.status == "error"],
                    f"{name} 存在 error 状态的 checker",
                )

    def test_no_load_errors(self):
        self.assertEqual([e.to_dict() for e in REGISTRY.errors], [])


class StatusTests(unittest.TestCase):
    def test_bent_sheet_bend_checks_run(self):
        status = statuses(run_m6a("bent_sheet"))
        for cid in ("DFM-19", "DFM-20", "DFM-21", "DFM-22", "DFM-24", "DFM-25"):
            self.assertEqual(status[cid], "ok", cid)
        self.assertEqual(status["DFM-23"], "skipped")
        self.assertEqual(status["DFM-26"], "skipped")

    def test_plate_holes(self):
        status = statuses(run_m6a("plate_holes"))
        self.assertEqual(status["DFM-19"], "skipped")
        self.assertEqual(status["DFM-20"], "ok")
        self.assertEqual(status["DFM-21"], "ok")
        self.assertEqual(status["DFM-22"], "ok")
        self.assertEqual(status["DFM-23"], "skipped")

    def test_missing_cylinder_data_is_reported(self):
        for name in ("deep_slot", "thin_wall"):
            status = statuses(run_m6a(name))
            with self.subTest(model=name):
                for cid in ("DFM-19", "DFM-20", "DFM-21", "DFM-22", "DFM-24", "DFM-25", "DFM-26"):
                    self.assertEqual(status[cid], "missing_data", cid)
                self.assertEqual(status["DFM-23"], "ok")

    def test_bosses_and_board_a(self):
        self.assertEqual(statuses(run_m6a("bosses"))["DFM-26"], "ok")
        board = statuses(run_m6a("board_a"))
        self.assertEqual(board["DFM-20"], "ok")
        self.assertEqual(board["DFM-22"], "ok")
        self.assertEqual(board["DFM-19"], "skipped")


class FindingContractTests(unittest.TestCase):
    def test_all_findings_are_low_confidence_and_traceable(self):
        for name in ("plate_holes", "deep_slot", "bosses", "thin_wall", "board_a", "bent_sheet"):
            result = run_m6a(name)
            for finding in result.findings:
                with self.subTest(model=name, finding=finding.finding_id):
                    self.assertTrue(finding.message.startswith("【粗筛】"))
                    self.assertLessEqual(finding.confidence, 0.6)
                    self.assertGreaterEqual(finding.confidence, 0.0)
                    self.assertEqual(finding.severity, "P2")
                    self.assertTrue(finding.evidence.face_ids)
                    self.assertTrue(finding.suggestion.text)
                    self.assertIsNotNone(finding.measured_value)
                    self.assertIsNotNone(finding.threshold_value)
                    self.assertTrue(finding.extra.get("coarse"))
                    self.assertIn("feature_kind", finding.extra)
                    self.assertIsNotNone(finding.extra.get("thickness_mm"))
                    self.assertIn(
                        finding.extra.get("thickness_source"),
                        ("rule", "2V/A", "bbox_min"),
                    )


if __name__ == "__main__":
    unittest.main()
