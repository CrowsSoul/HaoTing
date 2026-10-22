# -*- coding: utf-8 -*-
"""插件发现与注册。

发现顺序（后者无法覆盖前者的同 ID checker，重名直接报错，避免悄悄失效）：
    1. 内置包 nxdrp.checkers（含各人子包 m2_safety / m3_injection / ...）
    2. 环境变量 NXDRP_PLUGIN_PATH 里的目录（os.pathsep 分隔）
    3. 调用方显式传入的目录（CLI --plugin）

「分布式开发」靠的就是第 2、3 条：同学可以在自己的目录里开发、在自己的仓库里提交，
只要目录里有导出 CHECKERS 的 .py 文件，框架就能加载，核心代码零改动。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
import sys
import traceback
from dataclasses import dataclass, field

from .checkers.base import BaseChecker


@dataclass
class LoadError:
    source: str
    message: str
    traceback: str = ""

    def to_dict(self) -> dict:
        return {"source": self.source, "message": self.message}


@dataclass
class Registry:
    checkers: dict[str, BaseChecker] = field(default_factory=dict)
    errors: list[LoadError] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    # ---------------- 查询 ----------------
    def get(self, check_item_id: str) -> BaseChecker | None:
        return self.checkers.get(check_item_id)

    def all(self) -> list[BaseChecker]:
        return [self.checkers[k] for k in sorted(self.checkers)]

    def ids(self) -> list[str]:
        return sorted(self.checkers)

    def __len__(self) -> int:
        return len(self.checkers)

    def __contains__(self, item: str) -> bool:
        return item in self.checkers

    # ---------------- 注册 ----------------
    def register(self, checker: BaseChecker, source: str = "") -> None:
        cid = getattr(checker, "check_item_id", "") or ""
        if not cid:
            self.errors.append(LoadError(source, f"{type(checker).__name__} 缺少 check_item_id，已跳过"))
            return
        if cid in self.checkers:
            old = self.checkers[cid]
            if old.module_name == checker.module_name:
                # 同一实现被包 __init__ 和子模块各导出一次，静默去重，不算冲突
                return
            self.errors.append(
                LoadError(
                    source,
                    f"check_item_id {cid} 重复：{old.module_name} 与 {checker.module_name}。"
                    f"同一检查项只能有一个 checker，请改用新的 ID 或删除旧实现。",
                )
            )
            return
        self.checkers[cid] = checker

    # ---------------- 发现 ----------------
    def discover(self, plugin_paths: list[str] | None = None) -> "Registry":
        self._discover_builtin()
        for path in self._resolve_paths(plugin_paths):
            self._discover_dir(path)
        return self

    def _resolve_paths(self, plugin_paths: list[str] | None) -> list[str]:
        paths: list[str] = []
        env = os.environ.get("NXDRP_PLUGIN_PATH", "")
        if env:
            paths.extend(p for p in env.split(os.pathsep) if p.strip())
        paths.extend(plugin_paths or [])
        out: list[str] = []
        for p in paths:
            ap = os.path.abspath(p)
            if os.path.isdir(ap):
                out.append(ap)
            else:
                self.errors.append(LoadError(p, "插件目录不存在，已忽略"))
        return out

    def _discover_builtin(self) -> None:
        try:
            pkg = importlib.import_module("nxdrp.checkers")
        except Exception as exc:  # pragma: no cover
            self.errors.append(LoadError("nxdrp.checkers", repr(exc), traceback.format_exc()))
            return
        self.sources.append(os.path.dirname(pkg.__file__))
        for mod_info in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
            if mod_info.name.rsplit(".", 1)[-1].startswith("_"):
                continue
            self._load_module_named(mod_info.name)

    def _discover_dir(self, directory: str) -> None:
        self.sources.append(directory)
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith((".", "__"))]
            for name in sorted(files):
                if not name.endswith(".py") or name.startswith("_"):
                    continue
                path = os.path.join(root, name)
                self._load_module_from_path(path)

    def _load_module_named(self, dotted: str) -> None:
        try:
            mod = importlib.import_module(dotted)
        except Exception as exc:
            self.errors.append(LoadError(dotted, repr(exc), traceback.format_exc()))
            return
        self._collect(mod, dotted)

    def _load_module_from_path(self, path: str) -> None:
        safe = "".join(ch if ch.isalnum() else "_" for ch in os.path.abspath(path))
        modname = f"nxdrp_ext_{abs(hash(safe)) % 10**10}_{os.path.splitext(os.path.basename(path))[0]}"
        try:
            spec = importlib.util.spec_from_file_location(modname, path)
            if spec is None or spec.loader is None:
                raise ImportError("无法创建模块 spec")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[modname] = mod
            # 允许插件目录内的相对导入
            if os.path.dirname(path) not in sys.path:
                sys.path.insert(0, os.path.dirname(path))
            spec.loader.exec_module(mod)
        except Exception as exc:
            self.errors.append(LoadError(path, repr(exc), traceback.format_exc()))
            return
        self._collect(mod, path)

    def _collect(self, mod, source: str) -> None:
        found = False
        for attr in ("CHECKERS", "CHECKER"):
            obj = getattr(mod, attr, None)
            if obj is None:
                continue
            if isinstance(obj, (list, tuple, set)):
                for c in obj:
                    self.register(c, source)
                    found = True
            elif isinstance(obj, BaseChecker):
                self.register(obj, source)
                found = True
            else:
                self.errors.append(LoadError(source, f"{attr} 不是 BaseChecker 实例或实例列表，已忽略"))
        if found:
            return
        # 兜底：模块里定义的 BaseChecker 子类（需要无参可实例化）
        for name in dir(mod):
            obj = getattr(mod, name, None)
            if isinstance(obj, type) and issubclass(obj, BaseChecker) and obj is not BaseChecker:
                if obj.__module__ != mod.__name__:
                    continue
                try:
                    self.register(obj(), source)
                except Exception as exc:
                    self.errors.append(LoadError(source, f"{name} 实例化失败: {exc!r}"))


def discover(plugin_paths: list[str] | None = None) -> Registry:
    """便捷函数：发现并返回注册表。"""
    return Registry().discover(plugin_paths)
