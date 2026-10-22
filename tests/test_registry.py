# -*- coding: utf-8 -*-
"""插件机制测试：内置发现、外部目录加载、重名冲突、坏插件隔离。"""

import os
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nxdrp.checkers.base import BaseChecker  # noqa: E402
from nxdrp.registry import Registry, discover  # noqa: E402


PLUGIN_SRC = """
from nxdrp.checkers.base import BaseChecker

class MyCustomChecker(BaseChecker):
    check_item_id = "DFM-33"
    name = "顶部圆角（外部插件）"
    version = "9.9"
    default_params = {"hola": 1}

    def check(self, ctx):
        return []

CHECKERS = [MyCustomChecker()]
"""


class TestBuiltinDiscovery(unittest.TestCase):
    def test_examples_found(self):
        reg = discover()
        ids = reg.ids()
        for cid in ("DFM-02", "DFM-31", "DFM-32"):
            self.assertIn(cid, ids)
        self.assertEqual(len(reg.errors), 0, [e.message for e in reg.errors])

    def test_dedupe_same_impl(self):
        """包 __init__ 和子模块各导出一次同一实例时不应报冲突。"""
        reg = Registry()
        c = reg.__class__  # noqa: F841
        from nxdrp.checkers.examples.dfm32_fillet_uniformity import FilletUniformityChecker

        inst = FilletUniformityChecker()
        reg.register(inst, "a")
        reg.register(FilletUniformityChecker(), "b")
        self.assertEqual(len(reg), 1)
        self.assertEqual(len(reg.errors), 0)

    def test_conflict_different_impl(self):
        reg = Registry()

        class A(BaseChecker):
            check_item_id = "DFM-99"

        class B(BaseChecker):
            check_item_id = "DFM-99"

        reg.register(A(), "a")
        reg.register(B(), "b")
        self.assertEqual(len(reg), 1)
        self.assertEqual(len(reg.errors), 1)
        self.assertIn("重复", reg.errors[0].message)

    def test_missing_id_rejected(self):
        reg = Registry()

        class NoId(BaseChecker):
            pass

        reg.register(NoId(), "x")
        self.assertEqual(len(reg), 0)
        self.assertEqual(len(reg.errors), 1)


class TestExternalPlugins(unittest.TestCase):
    def test_load_from_directory(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "my_plugin.py"), "w", encoding="utf-8") as fh:
                fh.write(textwrap.dedent(PLUGIN_SRC))
            reg = discover([d])
            self.assertIn("DFM-33", reg.ids())
            self.assertEqual(reg.get("DFM-33").version, "9.9")

    def test_env_var_plugin_path(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "p.py"), "w", encoding="utf-8") as fh:
                fh.write(textwrap.dedent(PLUGIN_SRC))
            old = os.environ.get("NXDRP_PLUGIN_PATH")
            os.environ["NXDRP_PLUGIN_PATH"] = d
            try:
                reg = discover()
                self.assertIn("DFM-33", reg.ids())
            finally:
                if old is None:
                    os.environ.pop("NXDRP_PLUGIN_PATH", None)
                else:
                    os.environ["NXDRP_PLUGIN_PATH"] = old

    def test_broken_plugin_isolated(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "bad.py"), "w", encoding="utf-8") as fh:
                fh.write("raise RuntimeError('boom')\n")
            reg = discover([d])
            self.assertGreaterEqual(len(reg.errors), 1)
            # 坏插件不能影响内置插件
            self.assertIn("DFM-31", reg.ids())

    def test_nonexistent_dir_reported(self):
        reg = discover(["C:/definitely/not/a/dir"])
        self.assertTrue(any("不存在" in e.message for e in reg.errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
