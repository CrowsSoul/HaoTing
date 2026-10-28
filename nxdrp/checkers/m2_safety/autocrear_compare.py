# -*- coding: utf-8 -*-
"""自研结果与 AutoCrear/CCX 导出结果的精度对照。"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Iterable


@dataclass
class Comparison:
    kind: str
    network_a: str
    network_b: str
    point_id: str
    actual_mm: float
    reference_mm: float
    absolute_error_mm: float
    tolerance_mm: float
    within_tolerance: bool
    compliance_consistent: bool

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "network_a": self.network_a,
            "network_b": self.network_b,
            "point_id": self.point_id,
            "actual_mm": self.actual_mm,
            "reference_mm": self.reference_mm,
            "absolute_error_mm": self.absolute_error_mm,
            "tolerance_mm": self.tolerance_mm,
            "within_tolerance": self.within_tolerance,
            "compliance_consistent": self.compliance_consistent,
        }


def _key(item: dict) -> tuple[str, str, str, str]:
    a = str(item.get("network_a") or item.get("a") or "")
    b = str(item.get("network_b") or item.get("b") or "")
    point_id = str(item.get("point_id") or item.get("measurement_id") or item.get("id") or "")
    return str(item.get("kind") or ""), *sorted((a, b)), point_id


def _indexed(items: Iterable[dict], label: str) -> dict:
    out = {}
    for item in items:
        key = _key(item)
        if key in out:
            raise ValueError(
                f"{label} 中 {key[:3]} 存在多个点位；请给每条记录添加唯一 point_id"
            )
        out[key] = item
    return out


def compare(
    actual: Iterable[dict],
    reference: Iterable[dict],
    clearance_tolerance_mm: float = 0.05,
    creepage_tolerance_mm: float = 0.10,
) -> dict:
    """按“类型 + 网络配对”匹配，返回合同要求的三项统计。"""
    actual_map = _indexed(actual, "actual")
    reference_map = _indexed(reference, "reference")
    comparisons = []
    missing_actual = []
    missing_reference = []

    for key, ref in reference_map.items():
        got = actual_map.get(key)
        if got is None:
            missing_actual.append({
                "kind": key[0], "network_a": key[1], "network_b": key[2], "point_id": key[3],
            })
            continue
        kind = key[0]
        tolerance = clearance_tolerance_mm if kind == "clearance" else creepage_tolerance_mm
        actual_mm = float(got.get("measured_mm", got.get("distance_mm")))
        reference_mm = float(ref.get("measured_mm", ref.get("distance_mm")))
        threshold = ref.get("threshold_mm", got.get("threshold_mm"))
        if threshold is None:
            raise ValueError(f"{key} 缺少 threshold_mm，无法比较合规判定")
        threshold = float(threshold)
        error = abs(actual_mm - reference_mm)
        comparisons.append(
            Comparison(
                kind=kind,
                network_a=key[1],
                network_b=key[2],
                point_id=key[3],
                actual_mm=actual_mm,
                reference_mm=reference_mm,
                absolute_error_mm=error,
                tolerance_mm=tolerance,
                within_tolerance=error <= tolerance + 1e-12,
                compliance_consistent=(actual_mm >= threshold) == (reference_mm >= threshold),
            )
        )

    for key in actual_map:
        if key not in reference_map:
            missing_reference.append({
                "kind": key[0], "network_a": key[1], "network_b": key[2], "point_id": key[3],
            })

    count = len(comparisons)
    within = sum(item.within_tolerance for item in comparisons)
    consistent = sum(item.compliance_consistent for item in comparisons)
    by_kind = {}
    for kind in ("clearance", "creepage"):
        rows = [item for item in comparisons if item.kind == kind]
        by_kind[kind] = {
            "count": len(rows),
            "max_error_mm": max((item.absolute_error_mm for item in rows), default=None),
            "mean_error_mm": (
                sum(item.absolute_error_mm for item in rows) / len(rows) if rows else None
            ),
            "within_tolerance_rate": (
                sum(item.within_tolerance for item in rows) / len(rows) if rows else None
            ),
        }

    return {
        "count": count,
        "within_tolerance_rate": within / count if count else None,
        "compliance_consistency_rate": consistent / count if count else None,
        "passes_99_percent_distance": bool(count) and within / count >= 0.99,
        "passes_100_percent_compliance": bool(count) and consistent == count,
        "by_kind": by_kind,
        "missing_actual": missing_actual,
        "missing_reference": missing_reference,
        "comparisons": [item.to_dict() for item in comparisons],
    }


def _load(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        value = json.load(fh)
    if isinstance(value, list):
        return value
    for key in ("measurements", "results", "items"):
        if isinstance(value.get(key), list):
            return value[key]
    raise ValueError(f"{path} 必须是数组，或包含 measurements/results/items 数组")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="对照自研安规距离与 AutoCrear/CCX 结果")
    parser.add_argument("actual", help="自研结果 JSON")
    parser.add_argument("reference", help="AutoCrear/CCX 导出并整理后的 JSON")
    parser.add_argument("-o", "--output", default="", help="统计结果 JSON")
    args = parser.parse_args(argv)

    result = compare(_load(args.actual), _load(args.reference))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0 if result["passes_99_percent_distance"] and result["passes_100_percent_compliance"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
