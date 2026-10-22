# -*- coding: utf-8 -*-
"""打分：逐检查项的 P / R / F1，以及整体指标。"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import Finding
from .labels import LabelSet
from .match import MatchResult, match


@dataclass
class ItemScore:
    check_item_id: str
    positives: int = 0        # 标注里的正样本数
    tp: int = 0
    fp: int = 0               # 误报（含落在负样本位置上的）
    fn: int = 0               # 漏报
    negatives: int = 0        # 标注里的负样本数

    @property
    def precision(self) -> float | None:
        denom = self.tp + self.fp
        return self.tp / denom if denom else None

    @property
    def recall(self) -> float | None:
        denom = self.tp + self.fn
        return self.tp / denom if denom else None

    @property
    def f1(self) -> float | None:
        # 没有正样本的检查项不参与评分
        if self.positives == 0:
            return None
        # 该报却没报出任何东西：F1 记 0，不能因为「精确率无定义」而逃过统计
        if self.tp == 0:
            return 0.0
        p, r = self.precision, self.recall
        if p is None or r is None or (p + r) == 0:
            return 0.0
        return 2 * p * r / (p + r)

    def to_dict(self) -> dict:
        return {
            "check_item_id": self.check_item_id,
            "positives": self.positives,
            "negatives": self.negatives,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": None if self.precision is None else round(self.precision, 4),
            "recall": None if self.recall is None else round(self.recall, 4),
            "f1": None if self.f1 is None else round(self.f1, 4),
        }


@dataclass
class ScoreReport:
    model_id: str = ""
    items: dict[str, ItemScore] = field(default_factory=dict)
    unscored_items: list[str] = field(default_factory=list)   # 报了但没标注的检查项
    match_detail: dict = field(default_factory=dict)

    # ---------------- 汇总 ----------------
    @property
    def tp(self) -> int:
        return sum(i.tp for i in self.items.values())

    @property
    def fp(self) -> int:
        return sum(i.fp for i in self.items.values())

    @property
    def fn(self) -> int:
        return sum(i.fn for i in self.items.values())

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def false_positive_rate(self) -> float:
        """误报率 = FP / (TP + FP)，即 1 - precision。"""
        d = self.tp + self.fp
        return self.fp / d if d else 0.0

    @property
    def macro_f1(self) -> float | None:
        """逐项 F1 的平均。纯负样本场景没有可算的项，返回 None 而不是 0。"""
        vals = [i.f1 for i in self.items.values() if i.f1 is not None]
        return sum(vals) / len(vals) if vals else None

    def high_risk_recall(self, item_ids) -> float | None:
        sub = [self.items[i] for i in item_ids if i in self.items]
        tp = sum(i.tp for i in sub)
        fn = sum(i.fn for i in sub)
        return tp / (tp + fn) if (tp + fn) else None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "overall": {
                "tp": self.tp, "fp": self.fp, "fn": self.fn,
                "precision": round(self.precision, 4),
                "recall": round(self.recall, 4),
                "f1": round(self.f1, 4),
                "macro_f1": None if self.macro_f1 is None else round(self.macro_f1, 4),
                "false_positive_rate": round(self.false_positive_rate, 4),
            },
            "items": {k: v.to_dict() for k, v in sorted(self.items.items())},
            "unscored_items": self.unscored_items,
            "match_detail": self.match_detail,
        }

    def table(self) -> str:
        """命令行用的文本表。"""
        rows = []
        head = f"{'检查项':<9}{'标注':>4}{'TP':>4}{'FP':>4}{'FN':>4}{'P':>8}{'R':>8}{'F1':>8}"
        rows.append(head)
        rows.append("-" * len(head.encode("gbk", "replace")))
        for k in sorted(self.items):
            i = self.items[k]
            fmt = lambda v: "  —  " if v is None else f"{v:6.3f}"
            rows.append(f"{k:<9}{i.positives:>4}{i.tp:>4}{i.fp:>4}{i.fn:>4}"
                        f"{fmt(i.precision):>8}{fmt(i.recall):>8}{fmt(i.f1):>8}")
        rows.append("-" * len(head.encode("gbk", "replace")))
        rows.append(f"{'合计':<9}{sum(i.positives for i in self.items.values()):>4}"
                    f"{self.tp:>4}{self.fp:>4}{self.fn:>4}"
                    f"{self.precision:>8.3f}{self.recall:>8.3f}{self.f1:>8.3f}")
        return "\n".join(rows)


def score(label_set: LabelSet, findings: list[Finding], default_radius: float = 2.0,
          high_risk_items=None) -> ScoreReport:
    """跑一遍匹配并汇总。"""
    res: MatchResult = match(label_set, findings, default_radius)
    rep = ScoreReport(model_id=label_set.model_id, match_detail=res.to_dict())

    counts = label_set.counts()
    for cid in counts:
        rep.items[cid] = ItemScore(check_item_id=cid)
    for lab in label_set.labels:
        it = rep.items[lab.check_item_id]
        if lab.expected == "defect":
            it.positives += 1
        else:
            it.negatives += 1

    for lab, _f in res.matched:
        rep.items[lab.check_item_id].tp += 1
    for lab in res.missed:
        rep.items[lab.check_item_id].fn += 1
    for lab, _f in res.negative_hits:
        rep.items[lab.check_item_id].fp += 1

    labelled = set(counts)
    for f in res.extra:
        if f.check_item_id in rep.items:
            rep.items[f.check_item_id].fp += 1
        elif f.check_item_id not in labelled:
            if f.check_item_id not in rep.unscored_items:
                rep.unscored_items.append(f.check_item_id)

    if high_risk_items:
        rep.match_detail["high_risk_recall"] = (
            None if rep.high_risk_recall(high_risk_items) is None
            else round(rep.high_risk_recall(high_risk_items), 4)
        )
    return rep
