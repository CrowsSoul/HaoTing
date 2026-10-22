# -*- coding: utf-8 -*-
"""检查管线：把 ModelBundle + RuleBook 送进所有已注册 checker，收集 Finding。

三条硬规则：
  1. 单个 checker 崩溃不影响其它 checker（异常被捕获并记入 results，状态 error）。
  2. 数据不满足 ``requires`` 时跳过而不是硬算，避免产出看似合理的错误结论。
  3. 结果按 check_item_id 稳定排序，便于报告 diff 与回归对比。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import catalog
from .checkers.base import REQUIREMENTS, CheckContext, BaseChecker
from .contracts import Finding, ModelBundle, Rule, RuleBook
from .registry import Registry
from .version import __version__


STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_FILTERED = "filtered"
STATUS_ERROR = "error"
STATUS_MISSING_DATA = "missing_data"


@dataclass
class CheckerResult:
    check_item_id: str
    name: str = ""
    module: str = ""
    version: str = ""
    owner: str = ""
    status: str = STATUS_OK
    reason: str = ""
    runtime_ms: float = 0.0
    finding_count: int = 0

    def to_dict(self) -> dict:
        return {
            "check_item_id": self.check_item_id,
            "name": self.name,
            "module": self.module,
            "version": self.version,
            "owner": self.owner,
            "status": self.status,
            "reason": self.reason,
            "runtime_ms": round(self.runtime_ms, 2),
            "finding_count": self.finding_count,
        }


@dataclass
class CheckRun:
    model_id: str
    started_at: str = ""
    finished_at: str = ""
    elapsed_ms: float = 0.0
    findings: list[Finding] = field(default_factory=list)
    results: list[CheckerResult] = field(default_factory=list)
    load_errors: list[dict] = field(default_factory=list)
    rulebook: str = ""
    rulebook_version: str = ""
    framework_version: str = __version__

    # ---------------- 输出 ----------------
    def to_dict(self) -> dict:
        return {
            "framework_version": self.framework_version,
            "model_id": self.model_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "rulebook": self.rulebook,
            "rulebook_version": self.rulebook_version,
            "findings": [f.to_dict() for f in self.findings],
            "results": [r.to_dict() for r in self.results],
            "load_errors": self.load_errors,
        }

    def save(self, path: str) -> None:
        import json

        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)

    def summary(self) -> dict:
        by_sev: dict[str, int] = {}
        by_item: dict[str, int] = {}
        for f in self.findings:
            by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
            by_item[f.check_item_id] = by_item.get(f.check_item_id, 0) + 1
        statuses: dict[str, int] = {}
        for r in self.results:
            statuses[r.status] = statuses.get(r.status, 0) + 1
        return {
            "model_id": self.model_id,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "checkers": len(self.results),
            "statuses": statuses,
            "findings": len(self.findings),
            "by_severity": by_sev,
            "by_item": by_item,
        }


def _resolve_rule(rulebook: RuleBook, checker: BaseChecker) -> Rule:
    rule = rulebook.get(checker.check_item_id)
    if rule is not None:
        return rule
    item = checker.catalog_item()
    return Rule(
        rule_id=f"{checker.check_item_id}-default",
        check_item_id=checker.check_item_id,
        process_type=item.process_type if item else "",
        name=item.name_cn if item else checker.name,
        severity="P2",
        params={},
        notes="规则库中未定义该检查项，使用 checker 默认参数",
    )


def _missing_requirements(model: ModelBundle, requires: tuple[str, ...]) -> list[str]:
    missing = []
    for key in requires or ():
        probe = REQUIREMENTS.get(key)
        if probe is None:
            missing.append(f"{key}(未定义的能力声明)")
            continue
        try:
            if not probe(model):
                missing.append(key)
        except Exception:
            missing.append(key)
    return missing


def run(
    model: ModelBundle,
    rulebook: RuleBook | None = None,
    registry: Registry | None = None,
    only: list[str] | None = None,
    skip: list[str] | None = None,
    nx=None,
    progress=None,
) -> CheckRun:
    """执行全部检查。

    only / skip：按 check_item_id 过滤，便于单点调试（例如 python -m nxdrp check ... --only DFM-31）。
    nx：可选的回 NX 测量代理，注入到 ctx.nx，供需要精确距离的 checker 使用。
    progress：可选回调 fn(index, total, checker)。
    """
    from .registry import discover

    rulebook = rulebook or RuleBook()
    registry = registry or discover()
    only_set = set(only or [])
    skip_set = set(skip or [])

    run_ = CheckRun(
        model_id=model.model_id,
        started_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        rulebook=rulebook.name,
        rulebook_version=rulebook.version,
        load_errors=[e.to_dict() for e in registry.errors],
    )

    t_start = time.perf_counter()
    checkers = registry.all()
    for idx, checker in enumerate(checkers):
        cid = checker.check_item_id
        if progress:
            progress(idx, len(checkers), checker)

        res = CheckerResult(
            check_item_id=cid,
            name=checker.name,
            module=checker.module_name,
            version=checker.version,
            owner=checker.owner,
        )

        if only_set and cid not in only_set:
            res.status, res.reason = STATUS_FILTERED, "未在 --only 列表内"
            run_.results.append(res)
            continue
        if cid in skip_set:
            res.status, res.reason = STATUS_FILTERED, "在 --skip 列表内"
            run_.results.append(res)
            continue

        rule = _resolve_rule(rulebook, checker)
        if not rule.enabled:
            res.status, res.reason = STATUS_SKIPPED, "规则已禁用"
            run_.results.append(res)
            continue

        params = checker.merged_params(rule.params)

        missing = _missing_requirements(model, getattr(checker, "requires", ()))
        if missing:
            res.status = STATUS_MISSING_DATA
            res.reason = "模型缺少所需数据: " + ", ".join(missing)
            run_.results.append(res)
            continue

        try:
            ok, reason = checker.applies(model, params)
        except Exception as exc:
            # applies() 抛异常是代码 bug，不能当成「跳过」糊过去
            ok, reason = False, f"applies() 异常: {exc!r}"
            res.status = STATUS_ERROR
            res.reason = reason
            run_.results.append(res)
            continue
        if not ok:
            res.status, res.reason = STATUS_SKIPPED, reason or "applies() 返回 False"
            run_.results.append(res)
            continue

        ctx = CheckContext(model=model, rule=rule, params=params, checker=checker, nx=nx)
        t0 = time.perf_counter()
        try:
            produced = list(checker.check(ctx) or [])
            # ctx.finding() 会顺手把结果记进 ctx；学生即使忘了 return 也不该丢结果
            seen = {f.finding_id for f in produced}
            for f in ctx._findings:
                if f.finding_id not in seen:
                    produced.append(f)
            for f in produced:
                f.validate()
            run_.findings.extend(produced)
            res.status = STATUS_OK
            res.finding_count = len(produced)
        except Exception as exc:
            res.status = STATUS_ERROR
            res.reason = f"{type(exc).__name__}: {exc}"
        res.runtime_ms = (time.perf_counter() - t0) * 1000.0
        run_.results.append(res)

    run_.elapsed_ms = (time.perf_counter() - t_start) * 1000.0
    run_.finished_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    run_.findings.sort(key=lambda f: (f.check_item_id, f.finding_id))
    return run_


def coverage(registry: Registry) -> dict:
    """已实现 / 待实现覆盖率，按模块统计。给学生看进度用。"""
    implemented = set(registry.ids())
    rows = []
    for item in catalog.CATALOG:
        rows.append(
            {
                "check_item_id": item.check_item_id,
                "name_cn": item.name_cn,
                "owner_module": item.owner_module,
                "difficulty": item.difficulty,
                "phase": item.phase,
                "implemented": item.check_item_id in implemented,
            }
        )
    by_owner: dict[str, dict] = {}
    for r in rows:
        bucket = by_owner.setdefault(r["owner_module"], {"total": 0, "done": 0})
        bucket["total"] += 1
        bucket["done"] += 1 if r["implemented"] else 0
    return {
        "total": len(rows),
        "implemented": sum(1 for r in rows if r["implemented"]),
        "by_owner": dict(sorted(by_owner.items())),
        "rows": rows,
    }
