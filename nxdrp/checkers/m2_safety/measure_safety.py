# -*- coding: utf-8 -*-
"""导出全部安规测量点，供 AutoCrear 对照，不只导出不合格项。"""

from __future__ import annotations

import argparse
import json
import os
import sys

from ...adapters.base import load_any
from ...checkers.base import CheckContext
from ...checkers.proxy import NxDistanceProxy
from ...contracts import Rule, RuleBook
from .engine import (
    SafetyInputError,
    clearance_measurements,
    clearance_threshold_mm,
    creepage_measurements,
    creepage_threshold_mm,
    merged_safety_params,
)
from .saf01_clearance import ClearanceChecker
from .saf02_creepage import CreepageChecker


def _rule(book: RuleBook, check_item_id: str, name: str) -> Rule:
    return book.get(check_item_id) or Rule(
        rule_id=f"R-{check_item_id}",
        check_item_id=check_item_id,
        process_type="safety",
        name=name,
        severity="P0",
    )


def _row(item, index: int) -> dict:
    return {
        "point_id": item.point_id or f"{item.kind}-{index:04d}",
        "kind": item.kind,
        "network_a": item.network_a,
        "network_b": item.network_b,
        "measured_mm": item.measured_mm,
        "threshold_mm": item.threshold_mm,
        "compliant": item.compliant,
        "method": item.method,
        "confidence": item.confidence,
        "part_refs": item.part_refs,
        "face_ids": item.face_ids,
        "p1": list(item.p1) if item.p1 else None,
        "p2": list(item.p2) if item.p2 else None,
        "path_points": [list(point) for point in item.path_points],
        "note": item.note,
    }


def measure(model_path: str, rules_path: str = "") -> dict:
    model = load_any(model_path)
    book = RuleBook.load(rules_path) if rules_path else RuleBook()
    nx = None
    if model.source and model.source.lower().endswith(".prt") and os.path.isfile(model.source):
        from ...adapters.nx_batch import NxBatchAdapter

        adapter = NxBatchAdapter()
        if adapter.available():
            nx = NxDistanceProxy(adapter, model.source)

    clearance_checker = ClearanceChecker()
    clearance_rule = _rule(book, "SAF-01", clearance_checker.name)
    clearance_params = merged_safety_params(
        model, clearance_checker.merged_params(clearance_rule.params)
    )
    clearance_ctx = CheckContext(
        model=model,
        rule=clearance_rule,
        params=clearance_params,
        checker=clearance_checker,
        nx=nx,
    )
    clearance_threshold, clearance_source = clearance_threshold_mm(clearance_params)
    clearance = clearance_measurements(clearance_ctx, clearance_threshold)

    creepage_checker = CreepageChecker()
    creepage_rule = _rule(book, "SAF-02", creepage_checker.name)
    creepage_params = merged_safety_params(
        model, creepage_checker.merged_params(creepage_rule.params)
    )
    creepage_ctx = CheckContext(
        model=model,
        rule=creepage_rule,
        params=creepage_params,
        checker=creepage_checker,
        nx=nx,
    )
    creepage_threshold, creepage_source = creepage_threshold_mm(creepage_params)
    creepage = creepage_measurements(creepage_ctx, creepage_threshold)

    rows = []
    for index, item in enumerate(clearance + creepage, 1):
        rows.append(_row(item, index))
    point_ids = [row["point_id"] for row in rows]
    duplicates = sorted({value for value in point_ids if point_ids.count(value) > 1})
    if duplicates:
        raise SafetyInputError(
            f"测量点 point_id 必须唯一，重复值: {', '.join(duplicates)}"
        )
    return {
        "model_id": model.model_id,
        "sources": {
            "clearance": clearance_source,
            "creepage": creepage_source,
        },
        "measurements": rows,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="导出 M2 全部安规测量点")
    parser.add_argument("model", help="ModelBundle JSON 或 NX .prt")
    parser.add_argument("-r", "--rules", default="", help="RuleBook JSON")
    parser.add_argument("-o", "--output", default="safety_measurements.json")
    args = parser.parse_args(argv)
    try:
        result = measure(args.model, args.rules)
    except (SafetyInputError, OSError, ValueError) as exc:
        print(f"M2 测量导出失败：{exc}", file=sys.stderr)
        return 2
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"已写出 {args.output}，共 {len(result['measurements'])} 个测量点")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
