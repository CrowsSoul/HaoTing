# -*- coding: utf-8 -*-
"""评测框架：拿标注集给 44 个检查项打分。

三段式：
    labels.py   标注集是什么、怎么校验
    match.py    预测结果与标注怎么配对
    metrics.py  P / R / F1，按检查项与整体算

为什么必须有这套东西：合同要求「DFM 识别准确率 ≥ 90%」。没有标注集和匹配规则，
每个人只能说「我这儿跑出来了」，说不出「准不准、差多少」。这套框架就是那把尺。
"""

from .labels import Label, LabelSet, load_labels
from .match import MatchResult, match
from .metrics import ItemScore, ScoreReport, score

__all__ = [
    "Label", "LabelSet", "load_labels",
    "MatchResult", "match",
    "ItemScore", "ScoreReport", "score",
]
