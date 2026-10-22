# -*- coding: utf-8 -*-
"""预测与标注的配对规则。

一条预测算「命中」，必须同时满足：
    1. 检查项相同（DFM-31 不能顶 DFM-32）
    2. 零件有交集（同一个零件上）
    3. 位置距离 ≤ 容差（标注里可单独指定，默认 2 mm）
    4. 一条标注只能被一条预测命中；一条预测也只能算一次

不做类别之外的语义判断。类型对不对是标注本身的事，不是匹配器的事。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import Finding, Vec3
from .labels import Label, LabelSet


def _dist(a: Vec3 | None, b: Vec3 | None) -> float | None:
    if a is None or b is None:
        return None
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _part_ok(label: Label, finding: Finding) -> bool:
    if not label.part_refs:
        return True
    return bool(set(label.part_refs) & set(finding.part_refs))


def _locate_ok(label: Label, finding: Finding, default_radius: float) -> bool:
    """位置匹配：优先按坐标距离，退而按 face_id 交集。"""
    if label.face_ids and set(label.face_ids) & set(finding.evidence.face_ids):
        return True
    radius = label.tolerance_mm or default_radius
    d = _dist(label.location, finding.location)
    if d is None:
        # 两边都没坐标时，只要零件和检查项对上就算命中（粗匹配）
        return label.location is None and finding.location is None
    return d <= radius


@dataclass
class MatchResult:
    """一次配对的结果。"""

    matched: list[tuple[Label, Finding]] = field(default_factory=list)
    missed: list[Label] = field(default_factory=list)        # 漏报
    extra: list[Finding] = field(default_factory=list)       # 误报
    negative_hits: list[tuple[Label, Finding]] = field(default_factory=list)  # 在「不该报」的地方报了

    def to_dict(self) -> dict:
        return {
            "matched": len(self.matched),
            "missed": [l.label_id for l in self.missed],
            "extra": [f.finding_id for f in self.extra],
            "negative_hits": [
                {"label": l.label_id, "finding": f.finding_id} for l, f in self.negative_hits
            ],
        }


def match(label_set: LabelSet, findings: list[Finding], default_radius: float = 2.0) -> MatchResult:
    res = MatchResult()
    used: set[str] = set()

    # 正样本：就近贪心匹配（同一检查项 + 同零件 + 在容差内）
    for label in label_set.positives:
        best = None
        best_d = None
        for f in findings:
            if f.finding_id in used:
                continue
            if f.check_item_id != label.check_item_id:
                continue
            if not _part_ok(label, f):
                continue
            if not _locate_ok(label, f, default_radius):
                continue
            d = _dist(label.location, f.location)
            score = d if d is not None else 0.0
            if best is None or score < best_d:
                best, best_d = f, score
        if best is None:
            res.missed.append(label)
        else:
            used.add(best.finding_id)
            res.matched.append((label, best))

    # 负样本：落在「不该报」的位置上的预测，记一笔
    for label in label_set.negatives:
        for f in findings:
            if f.finding_id in used:
                continue
            if f.check_item_id != label.check_item_id:
                continue
            if not _part_ok(label, f):
                continue
            if not _locate_ok(label, f, default_radius):
                continue
            used.add(f.finding_id)
            res.negative_hits.append((label, f))
            break

    # 剩下的预测都是误报
    res.extra = [f for f in findings if f.finding_id not in used]
    return res
