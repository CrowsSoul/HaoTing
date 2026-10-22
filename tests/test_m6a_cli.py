# -*- coding: utf-8 -*-
"""插件发现、规则一致性与 CLI 端到端测试。"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nxdrp import cli
from nxdrp.checkers.base import REQUIREMENTS
from nxdrp.contracts import ModelBundle, RuleBook
from nxdrp.registry import discover

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "bent_sheet.model.json"
RULES = REPO_ROOT / "rules" / "dfm_default.json"
M6A_IDS = [f"DFM-{i}" for i in range(19, 27)]

REGISTRY = discover()
RULEBOOK = RuleBook.load(str(RULES))


class DiscoveryTests(unittest.TestCase):
    def test_eight_checkers_registered_without_errors(self):
        self.assertEqual([e.to_dict() for e in REGISTRY.errors], [])
        for cid in M6A_IDS:
            self.assertIn(cid, REGISTRY)
        self.assertGreaterEqual(len(REGISTRY), 11)  # 3 个内置 + 8 个 M6A
        for cid in M6A_IDS:
            checker = REGISTRY.get(cid)
            self.assertEqual(checker.owner, "M6A 于大淇")
            self.assertEqual(checker.process_types, ("sheet_metal",))

    def test_requires_keys_are_supported(self):
        for cid in M6A_IDS:
            for key in REGISTRY.get(cid).requires:
                with self.subTest(checker=cid, key=key):
                    self.assertIn(key, REQUIREMENTS)

    def test_defaults_match_shared_rulebook(self):
        RULEBOOK.validate()
        by_item = RULEBOOK.by_item()
        for cid in M6A_IDS:
            rule = by_item[cid]
            self.assertEqual(rule.process_type, "sheet_metal")
            self.assertEqual(rule.severity, "P2")
            self.assertEqual(rule.owner, "M6A")
            self.assertEqual(
                rule.params,
                REGISTRY.get(cid).default_params,
                f"{cid} 的规则参数与 default_params 不一致",
            )

    def test_fixture_is_valid_contract(self):
        model = ModelBundle.load(str(FIXTURE))
        model.validate()
        self.assertEqual(model.meta.get("expected_findings", {}).get("DFM-22"), 3)


class CliSmokeTests(unittest.TestCase):
    def test_cli_check_writes_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "findings.json"
            argv = [
                "check", str(FIXTURE),
                "-r", str(RULES),
                "--only", "DFM-22",
                "-o", str(out),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(argv)
            self.assertEqual(code, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["load_errors"], [])
            self.assertEqual(len(payload["findings"]), 3)
            for finding in payload["findings"]:
                self.assertEqual(finding["check_item_id"], "DFM-22")
                self.assertTrue(finding["message"].startswith("【粗筛】"))
                self.assertLessEqual(finding["confidence"], 0.6)
                self.assertTrue(finding["extra"]["coarse"])
                self.assertTrue(
                    finding["detector"]["module"].startswith("nxdrp.checkers.m6a_sheet_metal.")
                )


if __name__ == "__main__":
    unittest.main()
