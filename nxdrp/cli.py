# -*- coding: utf-8 -*-
"""命令行入口。

    python -m nxdrp doctor                      NX 环境诊断
    python -m nxdrp items                       列出检查项总目录
    python -m nxdrp checkers                    列出已注册的 checker 与覆盖率
    python -m nxdrp extract <a.prt> -o a.json   解析模型（真 NX）
    python -m nxdrp check <a.prt|a.json>        跑检查，输出 findings.json
    python -m nxdrp schema -o contracts/        导出三份 JSON Schema
    python -m nxdrp selftest                    自检（不需要 NX）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import catalog
from .contracts import RuleBook, schema_documents
from .errors import DrpError
from .pipeline import coverage, run
from .registry import discover
from .version import __version__


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _hr(title: str = "", width: int = 78) -> None:
    if title:
        print(f"\n{title}")
        print("─" * width)
    else:
        print("─" * width)


# ---------------------------------------------------------------------------
def cmd_doctor(args) -> int:
    from .adapters.nx_batch import NxBatchAdapter, NxConfig, detect_run_journal

    _hr("环境诊断")
    print(f"框架版本     : {__version__}")
    print(f"Python       : {sys.version.split()[0]}  ({sys.executable})")

    exe = detect_run_journal()
    cfg = NxConfig()
    adapter = NxBatchAdapter(cfg)
    print(f"UGII_BASE_DIR: {cfg.ugii_base_dir or '(未设置)'}")
    print(f"run_journal  : {exe or '(未找到)'}")
    print(f"NX 可用      : {'是' if adapter.available() else '否'}")
    print(f"并发上限     : {cfg.max_concurrency}  (NXDRP_NX_MAX_CONCURRENCY)")
    print(f"模型缓存目录 : {cfg.cache_dir}")

    journal = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journals", "extract_geometry.py")
    print(f"提取 journal : {'存在' if os.path.isfile(journal) else '缺失'}  {journal}")

    _hr("插件")
    reg = discover(getattr(args, "plugin", None))
    print(f"已注册 checker: {len(reg)}")
    for e in reg.errors:
        print(f"  [加载失败] {e.source}: {e.message}")

    _hr("建议")
    if not adapter.available():
        print("  · 未检测到 NX：仍可用 Mock 数据开发（mockdata/models/*.json）。")
        print("  · 需要在真模型上验证时，再确认 NX 安装并设置 UGII_BASE_DIR。")
    else:
        print("  · NX 已就绪。首次解析某个 .prt 会启动 NX 进程，约 30~60 秒，之后走缓存。")
    return 0


def cmd_items(args) -> int:
    items = catalog.CATALOG
    if args.owner:
        items = [i for i in items if i.owner_module == args.owner.upper()]
    if args.phase:
        items = [i for i in items if i.phase == args.phase]
    if args.process:
        items = [i for i in items if args.process in i.applies_to]

    _hr(f"检查项总目录（{len(items)} 项）")
    print(f"{'ID':<9}{'名称':<18}{'工艺':<12}{'难度':<6}{'期':<5}{'模块':<6}")
    for i in items:
        print(f"{i.check_item_id:<9}{i.name_cn:<18}{i.process_type:<12}{i.difficulty:<6}{i.phase:<5}{i.owner_module:<6}")

    st = catalog.stats()
    _hr("统计")
    print(f"总数 {st['total']}  难度 {st['difficulty']}  期次 {st['phase']}")
    print(f"按模块 {st['owner']}")
    return 0


def cmd_checkers(args) -> int:
    reg = discover(getattr(args, "plugin", None))
    cov = coverage(reg)

    _hr(f"已注册 checker（{len(reg)}）")
    if not reg:
        print("  （空）目前只有框架，还没有任何 checker。")
    for c in reg.all():
        d = c.describe()
        print(f"  {d['check_item_id']:<9}{d['name']:<20}v{d['version']:<8}{d['owner'] or '-':<14}{d['module']}")

    _hr("覆盖率（对照 catalog）")
    print(f"已实现 {cov['implemented']} / {cov['total']}")
    for mod, s in cov["by_owner"].items():
        bar = "█" * int(20 * s["done"] / max(s["total"], 1))
        print(f"  {mod:<4} {s['done']:>2}/{s['total']:<2} {bar:<20}")

    if reg.errors:
        _hr("插件加载错误")
        for e in reg.errors:
            print(f"  [{e.source}] {e.message}")
    return 0


def cmd_extract(args) -> int:
    from .adapters.base import load_any
    from .adapters.nx_batch import NxBatchAdapter

    path = args.model
    t0 = time.perf_counter()
    if path.lower().endswith(".prt"):
        adapter = NxBatchAdapter()
        if not adapter.available():
            print("未检测到 NX。可改用 Mock：python -m nxdrp extract mockdata/models/board_a.model.json")
            return 2
        bundle = adapter.load(path, use_cache=not args.no_cache)
    else:
        bundle = load_any(path)
    dt = time.perf_counter() - t0

    out = args.output or os.path.splitext(os.path.basename(path))[0] + ".model.json"
    bundle.save(out)

    _hr("解析完成")
    for k, v in bundle.summary().items():
        print(f"  {k:<12}: {v}")
    print(f"  耗时        : {dt:.1f}s")
    if bundle.diagnostics.get("warnings"):
        print(f"  警告        : {bundle.diagnostics['warnings']}")
    print(f"\n已写出 {out}")
    return 0


def cmd_check(args) -> int:
    from .adapters.base import load_any
    from .adapters.nx_batch import NxBatchAdapter

    path = args.model
    t0 = time.perf_counter()
    if path.lower().endswith(".prt"):
        adapter = NxBatchAdapter()
        bundle = adapter.load(path, use_cache=not args.no_cache)
    else:
        bundle = load_any(path)

    rulebook = RuleBook.load(args.rules) if args.rules else RuleBook()
    if args.rules:
        rulebook.validate()
    reg = discover(getattr(args, "plugin", None))

    only = [s.strip() for s in args.only.split(",")] if args.only else None
    skip = [s.strip() for s in args.skip.split(",")] if args.skip else None

    result = run(bundle, rulebook, reg, only=only, skip=skip)
    dt = time.perf_counter() - t0

    out = args.output or "findings.json"
    result.save(out)

    _hr(f"检查完成：{bundle.model_id}")
    s = result.summary()
    print(f"  checker 执行 : {s['checkers']} 个   状态 {s['statuses']}")
    print(f"  结果条数     : {s['findings']}   按严重度 {s['by_severity']}")
    print(f"  总耗时       : {dt:.2f}s")

    if result.findings:
        _hr("结果明细")
        for f in result.findings:
            print(f"  [{f.severity}] {f.check_item_id} {f.check_item_name}")
            print(f"        {f.message}")
            if f.suggestion.text:
                print(f"        建议: {f.suggestion.text}")

    problems = [r for r in result.results if r.status == "error"]
    if problems:
        _hr("执行失败")
        for r in problems:
            print(f"  {r.check_item_id} {r.name}: {r.reason}")

    if result.load_errors:
        _hr("插件加载错误")
        for e in result.load_errors:
            print(f"  [{e['source']}] {e['message']}")

    print(f"\n已写出 {out}")
    return 0 if not problems else 1


def cmd_eval(args) -> int:
    """拿标注集给检查结果打分。"""
    from .contracts import Finding
    from .eval import load_labels, score

    with open(args.findings, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    raw = payload.get("findings") if isinstance(payload, dict) else payload
    findings = [Finding.from_dict(x) for x in (raw or [])]

    labels = load_labels(args.labels)
    high_risk = None
    if not args.no_high_risk:
        high_risk = [i.check_item_id for i in catalog.CATALOG if i.difficulty == "L3"]

    rep = score(labels, findings, default_radius=args.radius, high_risk_items=high_risk)

    _hr(f"评测：{labels.model_id or '(未命名)'}")
    print(f"  标注 {len(labels.labels)} 条（正样本 {len(labels.positives)} / 负样本 {len(labels.negatives)}）")
    print(f"  预测 {len(findings)} 条")
    _hr()
    print(rep.table())
    _hr("整体")
    if rep.macro_f1 is None:
        print("  macro-F1      : -（本场景没有正样本，只看误报率）")
    else:
        print(f"  macro-F1      : {rep.macro_f1:.3f}")
    print(f"  精确率 / 召回 : {rep.precision:.3f} / {rep.recall:.3f}")
    print(f"  误报率        : {rep.false_positive_rate:.3f}")
    if high_risk and rep.match_detail.get("high_risk_recall") is not None:
        print(f"  高危项召回    : {rep.match_detail['high_risk_recall']:.3f}")
    if rep.unscored_items:
        print(f"  无标注、未计分: {', '.join(sorted(rep.unscored_items))}")

    out = args.output or "eval.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rep.to_dict(), fh, ensure_ascii=False, indent=2)
    print(f"\n已写出 {out}")
    return 0


def cmd_schema(args) -> int:
    out_dir = args.output or "contracts/schema"
    os.makedirs(out_dir, exist_ok=True)
    docs = schema_documents()
    for name, doc in docs.items():
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
        print(f"已写出 {path}")
    return 0


def cmd_selftest(args) -> int:
    """不依赖 NX 的自检：验证契约、插件、管线、Mock 全链路。"""
    from .adapters.mock import synthesize
    from .contracts import ModelBundle

    _hr("自检")
    ok = True

    mock = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "mockdata", "models", "board_a.model.json",
    )
    if os.path.isfile(mock):
        model = ModelBundle.load(mock)
        src = "mockdata/models/board_a.model.json"
    else:
        model = synthesize("selftest")
        src = "synthesize()"
    print(f"  契约        : {src} -> {len(model.parts)} 零件 / {len(model.faces)} 面  ✓")

    reg = discover(getattr(args, "plugin", None))
    print(f"  插件发现    : {len(reg)} 个 checker")
    for c in reg.all():
        print(f"                - {c.check_item_id} {c.name} ({c.version})")
    for e in reg.errors:
        print(f"                ! {e.source}: {e.message}")
        ok = False

    rulebook = RuleBook()
    rules_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "rules", "dfm_default.json")
    if os.path.isfile(rules_path):
        rulebook = RuleBook.load(rules_path)
        rulebook.validate()
        print(f"  规则库      : {rulebook.name} v{rulebook.version}（{len(rulebook.rules)} 条）✓")

    result = run(model, rulebook, reg)
    for r in result.results:
        mark = "✓" if r.status in ("ok", "skipped", "missing_data", "filtered") else "✗"
        print(f"  执行        : {mark} {r.check_item_id:<9}{r.status:<13}{r.reason[:44]}")
        if r.status == "error":
            ok = False

    print(f"  结果        : {len(result.findings)} 条 finding")
    expected = model.meta.get("expected_findings") or {}
    if expected:
        got: dict[str, int] = {}
        for f in result.findings:
            got[f.check_item_id] = got.get(f.check_item_id, 0) + 1
        for cid, n in expected.items():
            actual = got.get(cid, 0)
            mark = "✓" if actual == n else "✗"
            print(f"  期望        : {mark} {cid} 期望 {n} 条，实际 {actual} 条")
            if actual != n:
                ok = False

    if result.load_errors:
        ok = False
    _hr()
    print("自检通过 ✓" if ok else "自检失败 ✗")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nxdrp",
        description="连接器 AI 智能设计检查平台 · 开发框架 v" + __version__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python -m nxdrp doctor\n"
            "  python -m nxdrp checkers\n"
            "  python -m nxdrp check mockdata/models/board_a.model.json --only DFM-31\n"
            "  python -m nxdrp check \"D:/models/housing.prt\" -r rules/dfm_default.json\n"
        ),
    )
    p.add_argument("--plugin", action="append", default=[], metavar="DIR",
                   help="额外的插件目录（可重复）。也可放在子命令后面。")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_plugin_opt(sp):
        sp.add_argument("--plugin", action="append", default=argparse.SUPPRESS, metavar="DIR",
                        help="额外的插件目录（可重复）")
        return sp

    add_plugin_opt(sub.add_parser("doctor", help="NX 环境与插件诊断")).set_defaults(func=cmd_doctor)

    pi = add_plugin_opt(sub.add_parser("items", help="列出检查项总目录"))
    pi.add_argument("--owner", help="按模块过滤，如 M3")
    pi.add_argument("--phase", help="按期次过滤：一期 / 二期")
    pi.add_argument("--process", help="按工艺过滤：assembly/injection/machining/...")
    pi.set_defaults(func=cmd_items)

    add_plugin_opt(sub.add_parser("checkers", help="列出已注册 checker 与覆盖率")).set_defaults(func=cmd_checkers)

    pe = add_plugin_opt(sub.add_parser("extract", help="解析模型（.prt 走 NX，.json 直读）"))
    pe.add_argument("model")
    pe.add_argument("-o", "--output")
    pe.add_argument("--no-cache", action="store_true", help="强制重新解析，不用缓存")
    pe.set_defaults(func=cmd_extract)

    pc = add_plugin_opt(sub.add_parser("check", help="执行检查并输出 findings.json"))
    pc.add_argument("model")
    pc.add_argument("-r", "--rules", help="规则库 JSON 路径")
    pc.add_argument("-o", "--output", default="findings.json")
    pc.add_argument("--only", help="只跑指定检查项，逗号分隔")
    pc.add_argument("--skip", help="跳过指定检查项，逗号分隔")
    pc.add_argument("--no-cache", action="store_true")
    pc.set_defaults(func=cmd_check)

    pev = add_plugin_opt(sub.add_parser("eval", help="用标注集给结果打分（P/R/F1）"))
    pev.add_argument("findings", help="nxdrp check 产出的 findings.json")
    pev.add_argument("-l", "--labels", required=True, help="标注集 JSON")
    pev.add_argument("-o", "--output", default="eval.json")
    pev.add_argument("--radius", type=float, default=2.0, help="位置匹配容差 mm（默认 2）")
    pev.add_argument("--no-high-risk", action="store_true", help="不单独统计 L3 高危项召回")
    pev.set_defaults(func=cmd_eval)

    ps = sub.add_parser("schema", help="导出三份 JSON Schema")
    ps.add_argument("-o", "--output")
    ps.set_defaults(func=cmd_schema)

    add_plugin_opt(sub.add_parser("selftest", help="不依赖 NX 的自检")).set_defaults(func=cmd_selftest)
    return p


def main(argv=None) -> int:
    _utf8_stdout()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except DrpError as exc:
        print(f"\n[错误] {exc}", file=sys.stderr)
        diag = getattr(exc, "diagnostics", None)
        if diag:
            print("\n诊断信息：", file=sys.stderr)
            for k, v in diag.items():
                print(f"  {k}: {v}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
