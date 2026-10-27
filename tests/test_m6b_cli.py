# -*- coding: utf-8 -*-
"""M6B 包级基线：注册、共享规则、共享刀具库、与内置参考实现的分工。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nxdrp import catalog
from nxdrp.contracts import RuleBook
from nxdrp.registry import discover

M6B_IDS = [f"DFM-{i}" for i in range(27, 39)]
#: 本包直接交付的检查项；DFM-31/32 由 nxdrp/checkers/examples/ 的内置参考实现交付
PACKAGE_IDS = [cid for cid in M6B_IDS if cid not in ("DFM-31", "DFM-32")]
BUILTIN_IDS = ["DFM-31", "DFM-32"]

REGISTRY = discover()
RULEBOOK = RuleBook.load(str(REPO_ROOT / "rules" / "dfm_default.json"))


class DiscoveryTests(unittest.TestCase):
    def test_builtin_discovery_zero_errors(self):
        self.assertEqual([e.to_dict() for e in REGISTRY.errors], [])

    def test_all_12_m6b_items_registered(self):
        for cid in M6B_IDS:
            self.assertIn(cid, REGISTRY, cid)

    def test_package_exports_10_checkers(self):
        from nxdrp.checkers import m6b_machining

        self.assertEqual(len(m6b_machining.CHECKERS), 10)
        ids = sorted(c.check_item_id for c in m6b_machining.CHECKERS)
        self.assertEqual(ids, sorted(PACKAGE_IDS))

    def test_all_ids_in_catalog_and_owned(self):
        for cid in M6B_IDS:
            checker = REGISTRY.get(cid)
            self.assertIsNotNone(checker, cid)
            item = catalog.get(cid)
            self.assertIsNotNone(item, f"{cid} 不在总目录")
            self.assertEqual(item.owner_module, "M6")
            self.assertEqual(checker.owner, "M6 张百瑞")

    def test_builtin_reference_implementations_present(self):
        for cid in BUILTIN_IDS:
            checker = REGISTRY.get(cid)
            self.assertIn("nxdrp.checkers.examples", checker.module_name, cid)


class SharedRuleTests(unittest.TestCase):
    """共享规则库 rules/dfm_default.json 中 M6B 12 条的完整性。"""

    def _m6b_rules(self):
        return {r.check_item_id: r for r in RULEBOOK.rules if r.check_item_id in M6B_IDS}

    def test_twelve_enabled_rules(self):
        rules = self._m6b_rules()
        self.assertEqual(len(rules), 12)
        for rule in rules.values():
            self.assertTrue(rule.enabled, rule.check_item_id)
            self.assertIn(rule.severity, ("P0", "P1", "P2", "P3"))

    def test_every_rule_documents_source(self):
        for rule in self._m6b_rules().values():
            self.assertTrue(rule.source_standard, f"{rule.check_item_id} 缺少阈值依据")

    def test_rule_params_match_checker_defaults(self):
        """共享规则的参数键必须覆盖 checker 的默认参数键（改表即改判定的前提）。"""
        for cid in M6B_IDS:
            checker = REGISTRY.get(cid)
            rule = self._m6b_rules()[cid]
            for key in checker.default_params:
                self.assertIn(
                    key, rule.params,
                    f"{cid}: 默认参数 {key} 未在共享规则中，无法改表",
                )


class ToolLibraryFileTests(unittest.TestCase):
    def test_tool_library_json_valid(self):
        with open(REPO_ROOT / "rules" / "tool_library.json", encoding="utf-8") as fh:
            lib = json.load(fh)
        self.assertGreater(len(lib["drill_diameters_mm"]), 10)
        self.assertGreater(len(lib["endmill_diameters_mm"]), 5)
        for key, ref in lib["sources"].items():
            self.assertIn(key, lib, f"sources 里的 {key} 没有对应数据字段")
            self.assertTrue(ref, f"{key} 缺少来源说明")

    def test_tool_library_resolvable_from_package(self):
        from nxdrp.checkers.m6b_machining._m6b_machining_common import tool_library

        lib = tool_library()
        self.assertIn("drill_diameters_mm", lib)


if __name__ == "__main__":
    unittest.main()
