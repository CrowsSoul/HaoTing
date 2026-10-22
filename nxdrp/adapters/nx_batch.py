# -*- coding: utf-8 -*-
"""NX 批处理适配器 —— 通过 run_journal.exe 驱动本机 NX。

为什么用批处理而不是常驻 NX 会话：
  * NXOpen 只能在 NX 进程内使用，宿主 Python 无法直接 import；
  * 批处理天然隔离，崩溃不污染服务；代价是启动约 30~60 秒 —— 用缓存抵消；
  * 并发上限由 License 决定，因此这里做了进程级信号量（NXDRP_NX_MAX_CONCURRENCY）。

调用链：
    NxBatchAdapter.load()
      -> run_journal(journal="extract_geometry", request={part, ...})
      -> run_journal.exe <journal.py>   (NX 进程内执行)
      -> 读回 NXDRP_NX_RESPONSE 指向的 JSON
      -> ModelBundle.from_dict() + validate()

数据只通过文件 + 环境变量传递，避免中文路径在命令行编码上出问题。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field

from ..contracts import ModelBundle
from ..errors import JournalError, NxNotAvailableError
from .base import BaseModelSource

JOURNAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "journals")

#: 全局并发闸门：NX 实例数受 License 限制，默认 4
_SEMAPHORE = {"lock": threading.Lock(), "sem": None, "size": 0}

_CANDIDATE_ROOTS = (
    r"C:\Program Files\Siemens",
    r"C:\Program Files (x86)\Siemens",
    r"D:\Program Files\Siemens",
    r"D:\Siemens",
    r"E:\Siemens",
)


def _find_under(root: str) -> str | None:
    """在 Siemens 安装根目录下找 NXBIN/run_journal.exe（支持 NX* / Designcenter* 多版本）。"""
    if not os.path.isdir(root):
        return None
    try:
        names = sorted(os.listdir(root), reverse=True)
    except OSError:
        return None
    for name in names:
        exe = os.path.join(root, name, "NXBIN", "run_journal.exe")
        if os.path.isfile(exe):
            return exe
    return None


def detect_run_journal() -> str | None:
    """按 环境变量 -> 常见安装目录 的顺序定位 run_journal.exe。"""
    base = os.environ.get("UGII_BASE_DIR")
    if base:
        exe = os.path.join(base, "NXBIN", "run_journal.exe")
        if os.path.isfile(exe):
            return exe
    for root in _CANDIDATE_ROOTS:
        exe = _find_under(root)
        if exe:
            return exe
    return None


def detect_ugii_base_dir(run_journal: str | None = None) -> str:
    exe = run_journal or detect_run_journal()
    if not exe:
        return os.environ.get("UGII_BASE_DIR", "")
    return os.path.dirname(os.path.dirname(exe))


@dataclass
class NxConfig:
    run_journal: str | None = None
    ugii_base_dir: str = ""
    timeout_s: float = 900.0
    max_concurrency: int = 4
    cache_dir: str = ""
    journal_dir: str = JOURNAL_DIR
    extra_env: dict = field(default_factory=dict)

    def __post_init__(self):
        self.run_journal = self.run_journal or detect_run_journal()
        self.ugii_base_dir = self.ugii_base_dir or detect_ugii_base_dir(self.run_journal)
        if not self.cache_dir:
            self.cache_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                ".cache", "models",
            )
        if not self.max_concurrency:
            self.max_concurrency = int(os.environ.get("NXDRP_NX_MAX_CONCURRENCY", "4") or 4)

    def summary(self) -> dict:
        return {
            "run_journal": self.run_journal,
            "ugii_base_dir": self.ugii_base_dir,
            "timeout_s": self.timeout_s,
            "max_concurrency": self.max_concurrency,
            "cache_dir": self.cache_dir,
        }


def _semaphore(size: int):
    with _SEMAPHORE["lock"]:
        if _SEMAPHORE["sem"] is None or _SEMAPHORE["size"] != size:
            _SEMAPHORE["sem"] = threading.Semaphore(size)
            _SEMAPHORE["size"] = size
        return _SEMAPHORE["sem"]


class NxBatchAdapter(BaseModelSource):
    """通过 NX 批处理解析 .prt 模型。"""

    name = "nx-batch"

    def __init__(self, config: NxConfig | None = None):
        self.config = config or NxConfig()

    # ---------------- 可用性 ----------------
    def available(self) -> bool:
        return bool(self.config.run_journal and os.path.isfile(self.config.run_journal))

    def describe(self) -> dict:
        d = {"name": self.name, "available": self.available()}
        d.update(self.config.summary())
        return d

    def journal_path(self, name: str) -> str:
        path = os.path.join(self.config.journal_dir, f"{name}.py")
        if not os.path.isfile(path):
            raise NxNotAvailableError(f"找不到 journal: {path}")
        return path

    # ---------------- 通用 journal 执行 ----------------
    def run_journal(self, journal: str, request: dict, timeout_s: float | None = None) -> dict:
        """在 NX 进程内执行一个 journal，返回它写回的 JSON。

        任何扩展（例如 M2 需要的精确距离测量）都可以复用这一个方法：
        新增 ``nxdrp/journals/<name>.py``，然后 ``adapter.run_journal("<name>", {...})``。
        """
        if not self.available():
            raise NxNotAvailableError(
                "未找到 NX 的 run_journal.exe。请确认已安装 NX 并设置 UGII_BASE_DIR，"
                "或改用 Mock 数据：python -m nxdrp check mockdata/models/*.json"
            )

        exe = self.config.run_journal
        journal_file = self.journal_path(journal)
        timeout = timeout_s or self.config.timeout_s

        workdir = tempfile.mkdtemp(prefix="nxdrp_")
        req_path = os.path.join(workdir, "request.json")
        resp_path = os.path.join(workdir, "response.json")
        with open(req_path, "w", encoding="utf-8") as fh:
            json.dump(request, fh, ensure_ascii=False)

        env = os.environ.copy()
        env["NXDRP_NX_REQUEST"] = req_path
        env["NXDRP_NX_RESPONSE"] = resp_path
        if self.config.ugii_base_dir:
            env["UGII_BASE_DIR"] = self.config.ugii_base_dir
        env.update({k: str(v) for k, v in (self.config.extra_env or {}).items()})
        # 保证 NX 的 DLL 与 python 运行时优先被找到
        nxbin = os.path.join(self.config.ugii_base_dir, "NXBIN")
        if os.path.isdir(nxbin):
            env["PATH"] = nxbin + os.pathsep + env.get("PATH", "")

        sem = _semaphore(self.config.max_concurrency)
        t0 = time.perf_counter()
        with sem:
            try:
                proc = subprocess.run(
                    [exe, journal_file],
                    env=env,
                    cwd=workdir,
                    capture_output=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                raise JournalError(
                    f"NX journal {journal} 执行超过 {timeout:.0f}s 被终止。"
                    f"常见原因：模型过大、License 被占用、NX 弹出了不可见的对话框。",
                    {"journal": journal, "timeout_s": timeout},
                )
        elapsed = time.perf_counter() - t0

        if not os.path.isfile(resp_path):
            stderr = (proc.stderr or b"").decode("utf-8", "replace")[-2000:]
            stdout = (proc.stdout or b"").decode("utf-8", "replace")[-2000:]
            raise JournalError(
                "NX journal 没有产生响应文件",
                {
                    "journal": journal,
                    "returncode": proc.returncode,
                    "stdout_tail": stdout,
                    "stderr_tail": stderr,
                    "elapsed_s": round(elapsed, 1),
                },
            )

        with open(resp_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        payload.setdefault("diagnostics", {})["journal_elapsed_s"] = round(elapsed, 1)
        payload["diagnostics"]["returncode"] = proc.returncode

        if not payload.get("ok"):
            raise JournalError(
                f"NX journal {journal} 报告失败: {payload.get('error', '未知错误')}",
                payload.get("diagnostics", {}),
            )
        return payload

    # ---------------- 批量精确测距 ----------------
    def measure_distance(self, part_path: str, pairs, kind: str = "face") -> dict:
        """一次 NX 启动测完所有配对。pairs = [(tagA, tagB), ...]。

        起一个 NX 进程约 28 秒，所以必须批量：把要测的配对一次性传进去。
        """
        pairs = [(int(a), int(b)) for a, b in pairs]
        if not pairs:
            return {"pairs": [], "errors": []}
        payload = self.run_journal("measure_distance", {
            "part": os.path.abspath(part_path),
            "kind": kind,
            "pairs": [[a, b] for a, b in pairs],
        })
        return {"pairs": payload.get("pairs", []), "errors": payload.get("errors", [])}

# ---------------- 模型解析 ----------------
    def cache_key(self, part_path: str) -> str:
        st = os.stat(part_path)
        raw = f"{os.path.abspath(part_path)}|{st.st_size}|{int(st.st_mtime)}|{self.config.ugii_base_dir}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def load(self, part_path: str, use_cache: bool = True, **options) -> ModelBundle:
        # 环境不可用优先报出来，否则用户会以为是模型路径的问题
        if not self.available():
            raise NxNotAvailableError(
                "未找到 NX 的 run_journal.exe，无法解析 .prt。"
                "请设置 UGII_BASE_DIR，或改用已解析的 ModelBundle JSON："
                "python -m nxdrp check mockdata/models/board_a.model.json"
            )
        if not os.path.isfile(part_path):
            raise NxNotAvailableError(f"模型文件不存在: {part_path}")

        os.makedirs(self.config.cache_dir, exist_ok=True)
        key = self.cache_key(part_path)
        cache_file = os.path.join(self.config.cache_dir, f"{key}.json")

        if use_cache and os.path.isfile(cache_file):
            bundle = ModelBundle.load(cache_file)
            bundle.meta.setdefault("cache", "hit")
            return bundle

        request = {
            "part": os.path.abspath(part_path),
            "model_id": os.path.splitext(os.path.basename(part_path))[0],
            "options": {
                "measure_faces": options.get("measure_faces", True),
                "max_faces": options.get("max_faces", 20000),
                "collect_edges": options.get("collect_edges", True),
                "collect_assembly": options.get("collect_assembly", True),
            },
        }
        payload = self.run_journal("extract_geometry", request)
        bundle = ModelBundle.from_dict(payload["model"])
        bundle.meta.setdefault("cache", "miss")
        bundle.validate()

        if use_cache:
            bundle.save(cache_file)
        return bundle
