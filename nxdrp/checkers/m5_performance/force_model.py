# -*- coding: utf-8 -*-
"""PERF-02 模型的读写与点预测。

树只学「实测插入力 / 公式插入力」的对数修正；拔出力用同一个修正系数。
"""

from __future__ import annotations

import json
import math
import os

from .force_physics import FEATURE_NAMES, insertion_force_n, withdrawal_force_n
from .tree_model import predict_one

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "data", "perf02_model.json")


def load(path: str = MODEL_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        model = json.load(fh)
    names = tuple(model.get("feature_names") or ())
    if names != FEATURE_NAMES:
        raise ValueError(f"模型特征与当前代码不一致：{names}")
    return model


def _unpack(features: list[float]) -> tuple[float, float, float, float, float, float]:
    length, width, thick, overlap, e_gpa, mu = (math.exp(v) for v in features)
    return length, width, thick, overlap, e_gpa, mu


def predict_force(model: dict, features: list[float]) -> float:
    """插入力点预测，单位 N。"""
    raw = predict_one(model["tree"], features)
    length, width, thick, overlap, e_gpa, mu = _unpack(features)
    clean = insertion_force_n(
        length, width, thick, overlap, e_gpa,
        model.get("contacts", 4.0), model.get("lead_angle_deg", 30.0), mu,
    )
    return max(0.0, clean * math.exp(raw))


def predict_withdrawal(model: dict, features: list[float]) -> float:
    """拔出力点预测，单位 N。和插入力共用同一个对数修正。"""
    raw = predict_one(model["tree"], features)
    length, width, thick, overlap, e_gpa, mu = _unpack(features)
    clean = withdrawal_force_n(length, width, thick, overlap, e_gpa, model.get("contacts", 4.0), mu)
    return max(0.0, clean * math.exp(raw))
