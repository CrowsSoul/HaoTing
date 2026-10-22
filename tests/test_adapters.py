# -*- coding: utf-8 -*-
"""适配器测试：Mock 加载、NX 探测、缓存键、路径分派。"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nxdrp.adapters import MockAdapter, get_adapter, load_any  # noqa: E402
from nxdrp.adapters.mock import synthesize  # noqa: E402
from nxdrp.adapters.nx_batch import NxBatchAdapter, NxConfig, detect_run_journal  # noqa: E402
from nxdrp.errors import NxNotAvailableError  # noqa: E402


class TestMockAdapter(unittest.TestCase):
    def test_load_board(self):
        p = os.path.join(ROOT, "mockdata", "models", "board_a.model.json")
        m = MockAdapter().load(p)
        self.assertEqual(m.model_id, "board_a")
        self.assertEqual(len(m.parts), 2)

    def test_synthesize(self):
        m = synthesize("s1", faces=8)
        self.assertEqual(len(m.parts), 2)
        self.assertEqual(len(m.faces), 16)
        m.validate()

    def test_load_any_json(self):
        p = os.path.join(ROOT, "mockdata", "models", "minimal.model.json")
        self.assertEqual(load_any(p).model_id, "minimal")

    def test_load_any_unknown_ext(self):
        with self.assertRaises(ValueError):
            load_any("x.step")


class TestNxAdapter(unittest.TestCase):
    def test_detect_run_journal(self):
        exe = detect_run_journal()
        if exe:
            self.assertTrue(os.path.isfile(exe))
            self.assertTrue(exe.lower().endswith("run_journal.exe"))

    def test_config_defaults(self):
        cfg = NxConfig()
        self.assertGreater(cfg.timeout_s, 0)
        self.assertGreaterEqual(cfg.max_concurrency, 1)
        self.assertTrue(cfg.cache_dir)

    def test_cache_key_stable_and_sensitive(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.prt")
            with open(p, "wb") as fh:
                fh.write(b"0000")
            adapter = NxBatchAdapter(NxConfig(run_journal="x", cache_dir=d))
            k1 = adapter.cache_key(p)
            k2 = adapter.cache_key(p)
            self.assertEqual(k1, k2)
            with open(p, "wb") as fh:
                fh.write(b"00000")
            os.utime(p, (1, 1))
            self.assertNotEqual(k1, adapter.cache_key(p))

    def test_unavailable_raises_clear_error(self):
        adapter = NxBatchAdapter(NxConfig(run_journal="C:/nope/run_journal.exe"))
        self.assertFalse(adapter.available())
        with self.assertRaises(NxNotAvailableError) as ctx:
            adapter.load("x.prt")
        self.assertIn("NX", str(ctx.exception))

    def test_missing_model_file(self):
        adapter = NxBatchAdapter(NxConfig(run_journal="x"))
        with self.assertRaises(NxNotAvailableError):
            adapter.load("C:/definitely/missing.prt")

    def test_get_adapter_fallback(self):
        adapter = get_adapter("auto")
        self.assertIn(adapter.name, ("nx-batch", "mock"))


@unittest.skipUnless(detect_run_journal(), "本机没有 NX，跳过真实解析测试")
class TestRealNx(unittest.TestCase):
    """只有装了 NX 的机器才会跑；耗时约 30 秒。"""

    def test_extract_cached_sample(self):
        base = os.environ.get("UGII_BASE_DIR", "")
        part = os.path.join(base, "NXPARTS", "feature template", "resource", "Metric", "Pressure Port.prt")
        if not os.path.isfile(part):
            self.skipTest("没有 NX 自带样例")
        adapter = NxBatchAdapter()
        model = adapter.load(part)
        self.assertGreater(len(model.faces), 0)
        self.assertEqual(model.nx_version.lower().startswith("v"), True)
        self.assertTrue(any(f.solid_face_type == "cylindrical" for f in model.faces))


if __name__ == "__main__":
    unittest.main(verbosity=2)
