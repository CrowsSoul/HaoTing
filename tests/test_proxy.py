# -*- coding: utf-8 -*-
"""精确测距代理测试：批量预取、缓存、方向归一、缺失不偷偷起 NX。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nxdrp.checkers import NxDistanceProxy


class StubAdapter:
    """假 NX：记录调用次数，返回固定距离。"""

    def __init__(self, dist=0.15):
        self.calls = []
        self.dist = dist

    def measure_distance(self, part_path, pairs, kind="face"):
        self.calls.append((part_path, list(pairs), kind))
        return {
            "pairs": [{"a": a, "b": b, "distance": self.dist} for a, b in pairs],
            "errors": [],
        }


class TestProxy(unittest.TestCase):
    def test_prefetch_once(self):
        ad = StubAdapter()
        px = NxDistanceProxy(ad, "a.prt")
        n = px.prefetch([(1, 2), (3, 4)])
        self.assertEqual(n, 2)
        self.assertEqual(len(ad.calls), 1, "应当只起一次 NX")
        self.assertAlmostEqual(px.distance(1, 2), 0.15)

    def test_direction_normalized(self):
        ad = StubAdapter()
        px = NxDistanceProxy(ad, "a.prt")
        px.prefetch([(2, 1)])
        self.assertAlmostEqual(px.distance(1, 2), 0.15, msg="(a,b) 与 (b,a) 应命中同一条缓存")
        self.assertAlmostEqual(px.distance(2, 1), 0.15)

    def test_second_prefetch_skips_cached(self):
        ad = StubAdapter()
        px = NxDistanceProxy(ad, "a.prt")
        px.prefetch([(1, 2)])
        n = px.prefetch([(1, 2), (5, 6)])
        self.assertEqual(n, 1, "已缓存的配对不该重测")
        self.assertEqual(len(ad.calls), 2)

    def test_missing_returns_none(self):
        ad = StubAdapter()
        px = NxDistanceProxy(ad, "a.prt")
        self.assertIsNone(px.distance(9, 9), "没预取过应返回 None")
        self.assertEqual(ad.calls, [], "不许偷偷起 NX")

    def test_error_pair_cached_as_none(self):
        class ErrAdapter:
            def measure_distance(self, part_path, pairs, kind="face"):
                return {"pairs": [], "errors": [{"a": pairs[0][0], "b": pairs[0][1], "error": "bad"}]}

        px = NxDistanceProxy(ErrAdapter(), "a.prt")
        px.prefetch([(7, 8)])
        self.assertIsNone(px.distance(7, 8))
        self.assertEqual(px.missing([]), [])

    def test_missing_list(self):
        px = NxDistanceProxy(StubAdapter(), "a.prt")
        px.prefetch([(1, 2)])
        self.assertEqual(px.missing([(1, 2), (3, 4)]), [(3, 4)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
