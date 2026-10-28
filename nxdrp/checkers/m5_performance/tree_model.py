# -*- coding: utf-8 -*-
"""纯标准库的回归树。样本只有几百条，不引入第三方库。

点预测是叶节点的平均温升。区间不用叶内残差（那会偏窄），
而用验证集上 y/预测 的分位数，对应规则里的区间置信度。
"""

from __future__ import annotations

import json
import math
from typing import Iterable

from .physics import FEATURE_NAMES

MIN_LEAF = 6
MAX_DEPTH = 10
_CANDIDATE_QS = tuple(i / 16 for i in range(1, 16))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _sse(values: list[float]) -> float:
    mu = _mean(values)
    return sum((v - mu) ** 2 for v in values)


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _best_split(rows: list[tuple[list[float], float]]):
    n_feat = len(rows[0][0])
    parent = _sse([y for _, y in rows])
    best = None
    for fi in range(n_feat):
        vals = sorted({x[fi] for x, _ in rows})
        if len(vals) < 2:
            continue
        candidates = []
        for q in _CANDIDATE_QS:
            idx = min(int(q * (len(vals) - 1)), len(vals) - 2)
            thr = 0.5 * (vals[idx] + vals[idx + 1])
            candidates.append(thr)
        for thr in candidates:
            left = [y for x, y in rows if x[fi] <= thr]
            right = [y for x, y in rows if x[fi] > thr]
            if len(left) < MIN_LEAF or len(right) < MIN_LEAF:
                continue
            score = _sse(left) + _sse(right)
            if best is None or score < best[0]:
                best = (score, fi, thr)
    if best is None or best[0] >= parent * 0.985:
        return None
    return best[1], best[2]


def _build(rows: list[tuple[list[float], float]], depth: int) -> dict:
    ys = [y for _, y in rows]
    if depth <= 0 or len(rows) < MIN_LEAF * 2:
        return {"leaf": True, "value": _mean(ys), "n": len(rows)}
    split = _best_split(rows)
    if split is None:
        return {"leaf": True, "value": _mean(ys), "n": len(rows)}
    fi, thr = split
    left = [r for r in rows if r[0][fi] <= thr]
    right = [r for r in rows if r[0][fi] > thr]
    return {
        "leaf": False,
        "feature": fi,
        "threshold": thr,
        "left": _build(left, depth - 1),
        "right": _build(right, depth - 1),
    }


def fit(rows: Iterable[tuple[list[float], float]], depth: int = MAX_DEPTH) -> dict:
    data = [(list(x), float(y)) for x, y in rows]
    if len(data) < MIN_LEAF:
        raise ValueError(f"训练样本太少：{len(data)}")
    return _build(data, depth)


def predict_one(tree: dict, features: list[float]) -> float:
    node = tree
    while not node["leaf"]:
        if features[node["feature"]] <= node["threshold"]:
            node = node["left"]
        else:
            node = node["right"]
    return float(node["value"])


def predict_temperature(model: dict, features: list[float]) -> float:
    """返回 °C。log_correction 模型输出的是相对集总公式的修正系数。"""
    raw = predict_one(model["tree"], features)
    if model.get("target") == "log_correction":
        from .physics import delta_t_c

        area, length, rho, current, h = (math.exp(v) for v in features)
        return delta_t_c(area, length, rho, current, h) * math.exp(raw)
    if model.get("target") == "log_delta_t_c":
        return math.exp(raw)
    return raw


def fit_interval(predictions: list[float], actuals: list[float], confidence: float) -> tuple[float, float]:
    """验证集上实际值/预测值的两侧分位数。置信度 0.8 对应 10% 与 90%。"""
    tail = (1.0 - float(confidence)) / 2.0
    ratios = []
    for pred, actual in zip(predictions, actuals):
        if pred <= 1e-6:
            continue
        ratios.append(actual / pred)
    if len(ratios) < 5:
        raise ValueError("验证样本太少，无法标定预测区间")
    ratios.sort()
    return _quantile(ratios, tail), _quantile(ratios, 1.0 - tail)


def apply_interval(point: float, q_low: float, q_high: float) -> tuple[float, float]:
    low = max(0.0, point * q_low)
    high = max(low, point * q_high)
    return low, high


def dump(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        model = json.load(fh)
    names = tuple(model.get("feature_names") or ())
    if names != FEATURE_NAMES:
        raise ValueError(f"模型特征与当前代码不一致：{names}")
    return model
