"""Persistent jobs and bounded workers; no dependency on a Web framework."""
from __future__ import annotations

import copy
import html
import importlib
import json
import math
import os
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from contextlib import contextmanager

from nxdrp import catalog
from nxdrp.contracts import ModelBundle, RuleBook
from nxdrp.pipeline import run, coverage
from nxdrp.registry import discover

MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parents[2]
TERMINAL = {"completed", "failed"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def uid() -> str:
    return uuid.uuid4().hex


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


@dataclass
class Task:
    id: str
    model_id: str
    filename: str
    rulebook_id: str
    created_at: str
    only: list[str]
    state: str = "queued"
    stage: str = "等待执行"
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_ms: float = 0
    completed_items: int = 0
    total_items: int = 0
    current_item: str = ""
    error: str = ""
    report_state: str = "unavailable"
    report_error: str = ""
    queue_position: int = 0
    summary: dict[str, Any] | None = None


@dataclass
class DisplayMesh:
    vertices: list[tuple[float, float, float]]
    triangles: list[tuple[int, int, int]]
    face_ids: list[str]
    units: str = "mm"
    coordinate_space: str = "assembly"


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.db = directory / "platform.sqlite3"
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, payload TEXT, PRIMARY KEY(kind,id))")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, kind: str, key: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
        if row is None:
            raise KeyError(f"找不到 {kind}: {key}")
        return json.loads(row[0])

    def put(self, kind: str, key: str, value: dict):
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload", (kind, key, encode(value)))

    def all(self, kind: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM records WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def update(self, kind: str, key: str, **changes):
        with self.lock:
            value = self.get(kind, key)
            value.update(changes)
            self.put(kind, key, value)


def validate_rulebook(payload: dict) -> RuleBook:
    if not isinstance(payload, dict) or not isinstance(payload.get("rules"), list):
        raise ValueError("规则库必须包含 rules 列表")
    known = {item.check_item_id for item in catalog.CATALOG}
    defaults = RuleBook.load(str(ROOT / "rules/dfm_default.json")).by_item()
    if not isinstance(payload.get("name"), str) or not payload["name"].strip() or not isinstance(payload.get("version"), str) or not payload["version"].strip():
        raise ValueError("规则库名称和版本不能为空")
    for rule in payload["rules"]:
        if not isinstance(rule, dict) or rule.get("check_item_id") not in known:
            raise ValueError("规则的检查项 ID 不存在")
        if not isinstance(rule.get("rule_id"), str) or not rule["rule_id"].strip():
            raise ValueError("rule_id 不能为空")
        if type(rule.get("enabled", True)) is not bool:
            raise ValueError("规则启用状态必须为布尔值")
        if not isinstance(rule.get("params"), dict):
            raise ValueError("params 必须是参数对象")
        for key, value in rule["params"].items():
            if not isinstance(key, str) or not key:
                raise ValueError("参数名不能为空")
            if isinstance(value, (float, int)) and not isinstance(value, bool) and not math.isfinite(value):
                raise ValueError("参数不能为 NaN 或无穷大")
            reference = defaults.get(rule["check_item_id"])
            expected = reference.params.get(key) if reference else None
            if type(expected) in (int, float) and (type(value) not in (int, float) or (type(expected) is int and int(value) != value)):
                raise ValueError(f"{key} 必须是{'整数' if type(expected) is int else '数字'}")
            if isinstance(expected, str) and not isinstance(value, str):
                raise ValueError(f"{key} 必须是文本")
            if isinstance(expected, list) and (not isinstance(value, list) or not value or any(type(v) not in (int,float) or not math.isfinite(v) for v in value)):
                raise ValueError(f"{key} 必须是非空数字列表")
            if key == "pull_direction" and (not isinstance(value,list) or len(value)!=3 or not any(value)):
                raise ValueError("拔模方向必须是非零三维向量")
    encode(payload)  # also rejects nested non-finite values
    book = RuleBook.from_dict(payload)
    book.validate()
    return book


class Platform:
    def __init__(self, directory: Path, workers: int = 4, nx_slots: int = 1, capacity: int = 100):
        if not 1 <= nx_slots <= workers <= 16 or capacity < 1:
            raise ValueError("要求 1 <= NX 并发 <= worker 数 <= 16，队列容量为正数")
        self.store = Store(directory)
        self.workers = workers
        self.nx_slots = nx_slots
        self.capacity = capacity
        self.jobs: queue.Queue = queue.Queue(capacity)
        self.nx_gate = threading.Semaphore(nx_slots)
        self.guard = threading.RLock()
        self.threads: list[threading.Thread] = []
        self.stopping = threading.Event()
        self.instance_file = None

    def start(self):
        # NX concurrency and job ownership require exactly one service process.
        self.instance_file = open(self.store.directory / "service.lock", "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.instance_file.seek(0)
                if not self.instance_file.read(1):
                    self.instance_file.write(b"0")
                    self.instance_file.flush()
                self.instance_file.seek(0)
                msvcrt.locking(self.instance_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.instance_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.instance_file.close()
            self.instance_file = None
            raise RuntimeError("同一数据目录已有 M7 服务，请使用单进程启动")
        for task in self.store.all("tasks"):
            if task["state"] not in TERMINAL:
                self.store.update("tasks", task["id"], state="failed", stage="服务中断", finished_at=now(), error="服务重启，原任务已中断；请重新提交")
            if task.get("report_state") == "generating":
                self.store.update("tasks", task["id"], report_state="failed", report_error="报告生成被服务重启中断，请重试")
        if not self.store.all("rulebooks"):
            self.save_rulebook(RuleBook.load(str(ROOT / "rules/dfm_default.json")).to_dict())
        self.stopping.clear()
        for i in range(self.workers):
            thread = threading.Thread(target=self._worker, name=f"m7-worker-{i}", daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self):
        self.stopping.set()
        for thread in self.threads:
            thread.join()  # don't release process lock while NX is still active
        self.threads.clear()
        if self.instance_file:
            self.instance_file.close()
            self.instance_file = None

    def save_rulebook(self, payload: dict) -> dict:
        book = validate_rulebook(payload)
        book.updated_at = now()
        key = uid()
        record = {"id": key, "created_at": now(), "book": book.to_dict()}
        self.store.put("rulebooks", key, record)
        return record

    def model_path(self, key: str) -> Path:
        record = self.store.get("models", key)
        return self.store.directory / "models" / record["id"] / ("source" + record["extension"])

    def register_model(self, filename: str, data: bytes) -> dict:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".json", ".prt"}:
            raise ValueError("仅支持 ModelBundle .json 和单零件 .prt 文件")
        if not data:
            raise ValueError("上传文件不能为空")
        if suffix == ".json":
            payload = json.loads(data.decode("utf-8-sig"))
            if not isinstance(payload, dict) or not isinstance(payload.get("model_id"), str) or not payload["model_id"].strip():
                raise ValueError("模型必须包含非空 model_id")
            model = ModelBundle.from_dict(payload)
            model.validate()
            encode(model.to_dict())
        key = uid()
        folder = self.store.directory / "models" / key
        folder.mkdir(parents=True)
        (folder / ("source" + suffix)).write_bytes(data)
        record = {"id": key, "filename": filename.replace("\\", "/").split("/")[-1], "extension": suffix, "size": len(data), "created_at": now()}
        self.store.put("models", key, record)
        return record

    def submit(self, model_id: str, rulebook_id: str, only: list[str]) -> dict:
        model = self.store.get("models", model_id)
        book = self.store.get("rulebooks", rulebook_id)
        known = {item.check_item_id for item in catalog.CATALOG}
        if set(only) - known:
            raise ValueError("包含未知检查项")
        with self.guard:
            if self.stopping.is_set() or self.jobs.full():
                raise OverflowError("任务队列已满或服务正在停止，请稍后重试")
            key = uid()
            task = asdict(Task(key, model_id, model["filename"], rulebook_id, now(), list(dict.fromkeys(only))))
            folder = self.store.directory / "tasks" / key
            folder.mkdir(parents=True)
            self._write(folder / "rules.json", book["book"])
            self.store.put("tasks", key, task)
            self.jobs.put_nowait(key)
        return self.task(key)

    def task(self, key: str) -> dict:
        task = self.store.get("tasks", key)
        waiting = [t["id"] for t in self.store.all("tasks") if t["state"] == "queued"]
        task["queue_position"] = waiting.index(key) + 1 if key in waiting else 0
        if task["started_at"] and task["state"] not in TERMINAL:
            task["elapsed_ms"] = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(task["started_at"])).total_seconds() * 1000)
        return task

    def _write(self, path: Path, payload):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(encode(payload), encoding="utf-8")
        temporary.replace(path)

    def artifact(self, key: str, name: str) -> Path:
        self.store.get("tasks", key)
        return self.store.directory / "tasks" / key / name

    def _worker(self):
        while not self.stopping.is_set():
            try:
                key = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._execute(key)
            except Exception as exc:
                self.store.update("tasks", key, state="failed", stage="执行失败", error=str(exc), finished_at=now())
            finally:
                self.jobs.task_done()

    def _execute(self, key: str):
        task = self.store.get("tasks", key)
        path = self.model_path(task["model_id"])
        is_nx = path.suffix == ".prt"
        acquired = False
        t0 = time.perf_counter()
        update = lambda **kw: self.store.update("tasks", key, **kw)
        try:
            if is_nx:
                update(state="waiting_nx", stage="等待 NX 许可槽位")
                while not self.stopping.is_set():
                    if self.nx_gate.acquire(timeout=0.2):
                        acquired = True
                        break
                if not acquired:
                    raise RuntimeError("服务停止，任务尚未取得 NX 槽位")
            update(state="extracting", stage="解析模型", started_at=now())
            proxy = None
            if is_nx:
                from nxdrp.adapters.nx_batch import NxBatchAdapter, NxConfig
                from nxdrp.checkers.proxy import NxDistanceProxy
                adapter = NxBatchAdapter(NxConfig(max_concurrency=self.nx_slots, cache_dir=str(self.store.directory / "nx_cache")))
                if not adapter.available():
                    raise RuntimeError("未检测到 NX，请先上传 .model.json，或配置 NX 安装环境")
                model = adapter.load(str(path))
                proxy = NxDistanceProxy(adapter, str(path))
            else:
                model = ModelBundle.load(str(path))
            model.validate()
            self._write(self.artifact(key, "model.json"), model.to_dict())
            reg = discover()
            planned = [c.check_item_id for c in reg.all() if not task["only"] or c.check_item_id in task["only"]]
            completed = []
            update(state="checking", stage="执行检查", total_items=len(planned))

            def progress(index, total, checker):
                if checker.check_item_id in planned:
                    update(current_item=checker.check_item_id, completed_items=len(completed))
                    completed.append(checker.check_item_id)

            result = run(model, RuleBook.load(str(self.artifact(key, "rules.json"))), reg, only=task["only"], nx=proxy, progress=progress)
            payload = result.to_dict()
            self._write(self.artifact(key, "result.json"), payload)
            update(state="completed", stage="检查结束", current_item="", completed_items=len(planned), finished_at=now(), elapsed_ms=(time.perf_counter()-t0)*1000, summary=result.summary(), report_state="available")
        except Exception as exc:
            update(state="failed", stage="执行失败", error=f"{type(exc).__name__}: {exc}", finished_at=now(), elapsed_ms=(time.perf_counter()-t0)*1000)
        finally:
            if acquired:
                self.nx_gate.release()

    def result(self, key: str) -> dict:
        task = self.store.get("tasks", key)
        if task["state"] != "completed":
            raise ValueError("检查尚未完成")
        return json.loads(self.artifact(key, "result.json").read_text(encoding="utf-8"))

    def attach_mesh(self, key: str, payload: dict) -> dict:
        self.result(key)
        model = ModelBundle.load(str(self.artifact(key, "model.json")))
        if set(payload) != {"vertices", "triangles", "face_ids", "units", "coordinate_space"}:
            raise ValueError("网格必须包含 vertices、triangles、face_ids、units、coordinate_space")
        vertices, triangles, faces = payload["vertices"], payload["triangles"], payload["face_ids"]
        if payload["coordinate_space"] != "assembly" or payload["units"] != model.units:
            raise ValueError("网格必须使用装配全局坐标，单位必须与 ModelBundle 一致")
        if not isinstance(vertices,list) or not 3 <= len(vertices) <= 200000:
            raise ValueError("网格顶点数须在 3～200000 之间")
        if not isinstance(triangles,list) or not 1 <= len(triangles) <= 400000 or not isinstance(faces,list) or len(faces)!=len(triangles):
            raise ValueError("三角形数须在 1～400000 之间，每个三角形必须对应一个面 ID")
        known = {f.face_id for f in model.faces}
        for point in vertices:
            if not isinstance(point,list) or len(point)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point):
                raise ValueError("网格顶点必须为有限三维坐标")
        for tri, face in zip(triangles,faces):
            if not isinstance(tri,list) or len(tri)!=3 or any(type(v) is not int or not 0<=v<len(vertices) for v in tri):
                raise ValueError("三角形索引无效")
            if not isinstance(face,str) or face not in known:
                raise ValueError("网格包含 ModelBundle 中不存在的面 ID")
        with self.guard:
            self._write(self.artifact(key,"mesh.json"),payload)
        return payload

    def report(self, key: str) -> Path:
        """Standalone review report. Word/PDF belongs to the M8 provider."""
        result = self.result(key)
        task = self.task(key)
        esc = lambda x: html.escape(str(x if x is not None else "—"))
        rows = []
        for f in result["findings"]:
            rows.append("<tr>" + "".join(f"<td>{esc(x)}</td>" for x in [f["severity"], f["check_item_id"], f["message"], ', '.join(f["evidence"]["face_ids"]), f["location"], f["measured_value"], f["threshold_value"], f["deviation"], f["unit"], f["suggestion"]["text"]]) + "</tr>")
        statuses = ''.join(f"<tr><td>{esc(r['check_item_id'])}</td><td>{esc(r['status'])}</td><td>{esc(r['reason'])}</td></tr>" for r in result["results"])
        cov = coverage(discover())
        implemented = {r["check_item_id"] for r in result["results"]}
        missing = [r["check_item_id"] for r in cov["rows"] if r["check_item_id"] not in implemented and (not task['only'] or r['check_item_id'] in task['only'])]
        page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>设计检查报告</title>
<style>body{{font:14px sans-serif;margin:40px;color:#172d39}}table{{border-collapse:collapse;width:100%;margin:20px 0}}td,th{{border:1px solid #ced7dd;padding:9px;text-align:left;overflow-wrap:anywhere}}h1{{color:#006b63}}@media print{{body{{margin:10px}}}}</style>
<h1>连接器设计检查报告</h1><p>模型：{esc(task['filename'])} · 任务：{esc(key)}</p><p>规则版本：{esc(result['rulebook_version'])} · 快照：{esc(task['rulebook_id'])} · 完成时间：{esc(task['finished_at'])}</p>
<p>本报告仅反映实际执行的检查；无缺陷不代表全部检查项合格。3D 精确截图待 NX 网格映射与 M8 接入。</p>
<h2>缺陷明细（{len(rows)} 条）</h2><table><thead><tr>{''.join('<th>'+h+'</th>' for h in ['严重度','检查项','问题','面 ID','位置','实测','阈值','偏差','单位','修改建议'])}</tr></thead><tbody>{''.join(rows) or '<tr><td colspan="10">本次已执行项目未发现缺陷</td></tr>'}</tbody></table>
<h2>执行状态</h2><table><tr><th>检查项</th><th>状态</th><th>原因</th></tr>{statuses}</table><p>尚未实现：{esc(', '.join(missing) or '无')}</p><p>插件加载错误：{esc(result['load_errors'])}</p><p>可用浏览器打印功能保存为 PDF。</p></html>'''
        path = self.artifact(key, "report.html")
        with self.guard:
            path.write_text(page, encoding="utf-8")
        return path

    def generate_external_report(self, key: str, fmt: str) -> Path:
        """M8 callable: generate_report(result, model, rulebook, output_path)."""
        provider = os.environ.get("M7_REPORT_PROVIDER", "")
        if not provider:
            raise ValueError("尚未配置 M8 报告生成器，请先下载 HTML 报告")
        if fmt not in {"pdf", "docx"}:
            raise ValueError("格式必须为 pdf 或 docx")
        self.result(key)
        with self.guard:
            if self.task(key)["report_state"] == "generating":
                raise OverflowError("该任务的报告正在生成")
            self.store.update("tasks", key, report_state="generating", report_error="")
        try:
            module, function = provider.split(":", 1)
            fn = getattr(importlib.import_module(module), function)
            output = self.artifact(key, "report." + fmt)
            result = self.result(key)
            model = json.loads(self.artifact(key, "model.json").read_text(encoding="utf-8"))
            rules = json.loads(self.artifact(key, "rules.json").read_text(encoding="utf-8"))
            fn(result=result, model=model, rulebook=rules, output_path=str(output))
            if not output.is_file() or output.stat().st_size == 0:
                raise ValueError("M8 未产生有效报告文件")
            self.store.update("tasks", key, report_state="available")
            return output
        except Exception as exc:
            self.store.update("tasks", key, report_state="failed", report_error=str(exc))
            raise
