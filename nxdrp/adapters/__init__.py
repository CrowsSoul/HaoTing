# -*- coding: utf-8 -*-
"""模型来源适配器。

    nx_batch.NxBatchAdapter   真 NX，通过 run_journal.exe 批处理
    mock.MockAdapter          从 JSON 读 ModelBundle，无需 NX

对上层只暴露 nxdrp.adapters.base.load_any()。
"""

from .base import BaseModelSource, ModelSource, load_any
from .mock import MockAdapter, synthesize

__all__ = ["BaseModelSource", "ModelSource", "load_any", "MockAdapter", "synthesize"]


def get_adapter(kind: str = "auto", **kwargs):
    """按名字取适配器；auto 优先真 NX，环境不可用时回退 Mock。"""
    kind = (kind or "auto").lower()
    if kind in ("nx", "nx-batch", "nx_batch"):
        from .nx_batch import NxBatchAdapter

        return NxBatchAdapter(**kwargs)
    if kind in ("mock", "json"):
        return MockAdapter(**kwargs)
    from .nx_batch import NxBatchAdapter

    adapter = NxBatchAdapter()
    if adapter.available():
        return adapter
    return MockAdapter()
