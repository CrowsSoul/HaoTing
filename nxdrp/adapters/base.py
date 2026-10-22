# -*- coding: utf-8 -*-
"""模型来源抽象。

所有适配器都实现同一个入口：``load(part_path) -> ModelBundle``。
上层（管线、CLI、Web）只依赖这个接口，因此「用真 NX 跑」和「用 Mock 数据跑」
对下游 checker 完全透明 —— 这是 8 个人能并行开发的前提。
"""

from __future__ import annotations

import json
import os
from typing import Protocol, runtime_checkable

from ..contracts import ModelBundle


@runtime_checkable
class ModelSource(Protocol):
    name: str

    def available(self) -> bool: ...

    def load(self, part_path: str, **kwargs) -> ModelBundle: ...


class BaseModelSource:
    name = "base"

    def available(self) -> bool:
        return True

    def load(self, part_path: str, **kwargs) -> ModelBundle:  # pragma: no cover - 抽象
        raise NotImplementedError

    def describe(self) -> dict:
        return {"name": self.name, "available": self.available()}


def load_any(path: str, source: ModelSource | None = None, **kwargs) -> ModelBundle:
    """从任意路径加载模型。

    自动识别三种输入：
        *.json          已解析的 ModelBundle（Mock 或缓存）
        *.prt / *.prt+  原始 NX 模型，走 NX 批处理
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        return ModelBundle.load(path)
    if ext in (".prt", ".nx"):
        if source is None:
            from .nx_batch import NxBatchAdapter

            source = NxBatchAdapter()
        return source.load(path, **kwargs)
    raise ValueError(f"无法识别的模型文件类型: {path!r}（支持 .json / .prt）")


def dump_json(obj, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
