# -*- coding: utf-8 -*-
"""分档看误差：按材料、按截面积、以及训练时没见过的材料各算一遍。

    python -m nxdrp.checkers.m5_performance.evaluate
"""

from __future__ import annotations

import math
import random

from .physics import RULE_PARAMS, feature_vector
from .samples import SAMPLES_PATH, load
from .tree_model import apply_interval, fit, fit_interval, predict_temperature

TRAIN_N = 240
CAL_N = 60
TEST_N = 60
SEED = 20261029
BAND_LOW = 1.0
BAND_HIGH = 200.0
AREA_EDGES = (0.5, 2.0, 5.0, 10.0, 20.0)


def load_split(samples_path: str = SAMPLES_PATH):
    payload = load(samples_path)
    samples = list(payload["samples"])
    need = TRAIN_N + CAL_N + TEST_N
    if len(samples) < need:
        raise SystemExit(f"样本只有 {len(samples)} 条，至少需要 {need} 条")
    rng = random.Random(SEED)
    rng.shuffle(samples)
    return samples[:TRAIN_N], samples[TRAIN_N:TRAIN_N + CAL_N], samples[TRAIN_N + CAL_N:TRAIN_N + CAL_N + TEST_N]


def rows_of(samples):
    out = []
    for s in samples:
        x = feature_vector(s["area_mm2"], s["length_mm"], s["rho_ohm_m"], s["current_a"], s["h_w_m2k"])
        out.append((x, float(s["delta_t_c"]), s))
    return out


def fit_tree(train_samples, depth=4):
    rows = []
    for s in train_samples:
        clean = float(s["delta_t_clean_c"])
        observed = float(s["delta_t_c"])
        x = feature_vector(s["area_mm2"], s["length_mm"], s["rho_ohm_m"], s["current_a"], s["h_w_m2k"])
        rows.append((x, math.log(max(observed, 1e-6) / max(clean, 1e-6))))
    return fit(rows, depth=depth)


def make_model(train_samples, cal_samples):
    tree = fit_tree(train_samples)
    model = {
        "target": "log_correction",
        "interval_confidence": float(RULE_PARAMS["interval_confidence"]),
        "q_low": 1.0,
        "q_high": 1.0,
        "tree": tree,
    }
    pred = []
    actual = []
    for x, y, _s in rows_of(cal_samples):
        if BAND_LOW <= y <= BAND_HIGH:
            pred.append(predict_temperature(model, x))
            actual.append(y)
    model["q_low"], model["q_high"] = fit_interval(pred, actual, model["interval_confidence"])
    return model


def score(model, sample_rows):
    errs = []
    band_errs = []
    covered = 0
    band_n = 0
    for x, y, _s in sample_rows:
        p = predict_temperature(model, x)
        low, high = apply_interval(p, model["q_low"], model["q_high"])
        errs.append(abs(p - y))
        if BAND_LOW <= y <= BAND_HIGH:
            band_n += 1
            band_errs.append(abs(p - y))
            if low <= y <= high:
                covered += 1
    errs.sort()
    band_errs.sort()
    return {
        "n": len(errs),
        "median": errs[len(errs) // 2] if errs else float("nan"),
        "band_n": band_n,
        "band_median": band_errs[len(band_errs) // 2] if band_errs else float("nan"),
        "coverage": (covered / band_n) if band_n else float("nan"),
    }


def _line(label, s):
    cov = f"{s['coverage']:.0%}" if s["band_n"] else "—"
    return f"{label:<22} n={s['n']:>3}  中位 {s['median']:>7.2f} °C   {BAND_LOW:.0f}–{BAND_HIGH:.0f} °C 档 {s['band_median']:>6.2f} °C   覆盖 {cov}"


def main():
    train_s, cal_s, test_s = load_split()
    model = make_model(train_s, cal_s)
    test_rows = rows_of(test_s)

    print("PERF-01 分档误差（测试集不参与训练，也不参与区间标定）")
    print()
    print(_line("全部测试集", score(model, test_rows)))
    print()

    print("按材料：")
    for material in RULE_PARAMS["materials"]:
        sub = [r for r in test_rows if r[2]["material"] == material]
        if sub:
            print(_line("  " + material, score(model, sub)))
    print()

    print("按截面积（mm²）：")
    for lo, hi in zip(AREA_EDGES, AREA_EDGES[1:]):
        sub = [r for r in test_rows if lo <= r[2]["area_mm2"] < hi]
        if sub:
            print(_line(f"  {lo}–{hi}", score(model, sub)))
    print()

    print("留一材料：")
    for material in RULE_PARAMS["materials"]:
        train2 = [s for s in train_s if s["material"] != material]
        cal2 = [s for s in cal_s if s["material"] != material]
        test2 = [s for s in test_s if s["material"] == material]
        if len(test2) < 3:
            continue
        m2 = make_model(train2, cal2)
        s2 = score(m2, rows_of(test2))
        print(_line(f"  未参与训练 {material}", s2))


if __name__ == "__main__":
    main()
