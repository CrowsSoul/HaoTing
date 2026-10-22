# -*- coding: utf-8 -*-
"""插件级基线：注册、规则库、刀具库、与内置参考实现的分工。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parent
for _path in (str(REPO_ROOT), str(PLUGIN_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from nxdrp import catalog
from nxdrp.contracts import RuleBook
from nxdrp.registry import Registry, discover

M6B_IDS = [f"DFM-{i}" for i in range(27, 39)]
#: 本插件直接交付的检查项；DFM-31/32 由 nxdrp/checkers/examples/ 的内置参考实现交付
PLUGIN_IDS = [cid for cid in M6B_IDS if cid not in ("DFM-31", "DFM-32")]
BUILTIN_IDS = ["DFM-31", "DFM-32"]


def plugin_only_registry() -> Registry:
    reg = Registry()
    reg._discover_dir(str(PLUGIN_ROOT))
    return reg


class PluginDiscoveryTests(unittest.TestCase):
    def test_plugin_only_loads_10_checkers_zero_errors(self):
        reg = plugin_only_registry()
        self.assertEqual([e.to_dict() for e in reg.errors], [])
        self.assertEqual(reg.ids(), sorted(PLUGIN_IDS))

    def test_full_discovery_covers_all_12_m6b_items_zero_errors(self):
        """内置参考实现（DFM-31/32）+ 本插件（10 项）= M6 全部 12 项，无加载错误。"""
        reg = discover([str(PLUGIN_ROOT)])
        self.assertEqual([e.to_dict() for e in reg.errors], [])
        for cid in M6B_IDS:
            self.assertIn(cid, reg, cid)

    def test_all_ids_in_catalog_and_owned(self):
        reg = discover([str(PLUGIN_ROOT)])
        for cid in M6B_IDS:
            checker = reg.get(cid)
            self.assertIsNotNone(checker, cid)
            item = catalog.get(cid)
            self.assertIsNotNone(item, f"{cid} 不在总目录")
            self.assertEqual(item.owner_module, "M6")
            self.assertEqual(checker.owner, "M6 张百瑞")

    def test_builtin_reference_implementations_present(self):
        reg = discover([str(PLUGIN_ROOT)])
        for cid in BUILTIN_IDS:
            checker = reg.get(cid)
            self.assertIn("nxdrp.checkers.examples", checker.module_name, cid)


class RuleBookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rulebook = RuleBook.load(str(PLUGIN_ROOT / "rules_m6b.json"))

    def test_twelve_enabled_rules(self):
        self.assertEqual(len(self.rulebook.rules), 12)
        for rule in self.rulebook.rules:
            self.assertTrue(rule.enabled, rule.check_item_id)
            self.assertIn(rule.check_item_id, M6B_IDS)
            self.assertIn(rule.severity, ("P0", "P1", "P2", "P3"))

    def test_every_rule_documents_source(self):
        for rule in self.rulebook.rules:
            self.assertTrue(rule.source_standard, f"{rule.check_item_id} 缺少阈值依据")

    def test_rule_ids_unique_and_match_checkers(self):
        reg = discover([str(PLUGIN_ROOT)])
        for rule in self.rulebook.rules:
            self.assertIsNotNone(reg.get(rule.check_item_id), rule.check_item_id)


class ToolLibraryFileTests(unittest.TestCase):
    def test_tool_library_json_valid(self):
        with open(PLUGIN_ROOT / "tool_library.json", encoding="utf-8") as fh:
            lib = json.load(fh)
        self.assertGreater(len(lib["drill_diameters_mm"]), 10)
        self.assertGreater(len(lib["endmill_diameters_mm"]), 5)
        for key, ref in lib["sources"].items():
            self.assertIn(key, lib, f"sources 里的 {key} 没有对应数据字段")
            self.assertTrue(ref, f"{key} 缺少来源说明")


if __name__ == "__main__":
    unittest.main()
