# -*- coding: utf-8 -*-
"""精确测距代理：让 checker 能一次批量调用 NX 的最小距离，而不是逐对起进程。

起一个 NX 进程约 30 秒，逐对调用会把性能预算吃光。用法：

    pairs = [(a.tag, b.tag) for a, b in ctx.adjacency_pairs(min_gap)]
    ctx.nx.prefetch(pairs)              # 一次 NX 启动，全测完
    for a, b in ...:
        d = ctx.nx.distance(a.tag, b.tag)   # 走缓存，瞬时返回

没有 NX 环境（比如跑 Mock 数据）时 ``ctx.nx`` 是 None，checker 应当降级到包围盒粗筛
并在 Finding 里标明 ``粗筛``，不要假装有精确值。
"""

from __future__ import annotations

from typing import Iterable


class NxDistanceProxy:
    """把批量测距包装成「先预取、再查表」。"""

    def __init__(self, adapter, part_path: str, kind: str = "face"):
        self._adapter = adapter
        self._part = part_path
        self._kind = kind
        self._cache: dict[tuple[int, int], float | None] = {}

    @staticmethod
    def _key(a, b) -> tuple[int, int]:
        a, b = int(a), int(b)
        return (a, b) if a <= b else (b, a)

    def prefetch(self, pairs: Iterable[tuple[int, int]]) -> int:
        """把还没测过的配对一次性送给 NX，返回本次新测的数量。"""
        need = []
        for a, b in pairs:
            k = self._key(a, b)
            if k not in self._cache:
                need.append(k)
        if not need:
            return 0
        res = self._adapter.measure_distance(self._part, need, kind=self._kind)
        for item in res.get("pairs", []):
            self._cache[self._key(item["a"], item["b"])] = float(item["distance"])
        for err in res.get("errors", []):
            self._cache[self._key(err["a"], err["b"])] = None
        return len(need)

    def distance(self, a, b) -> float | None:
        """取缓存里的距离；没预取过返回 None（不会偷偷起一次 NX）。"""
        return self._cache.get(self._key(a, b))

    def missing(self, pairs: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
        return [p for p in pairs if self._key(*p) not in self._cache]

    def __len__(self) -> int:
        return len(self._cache)
