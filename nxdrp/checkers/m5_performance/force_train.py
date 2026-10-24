# -*- coding: utf-8 -*-
"""训练插拔力回归树、标定区间、在独立测试集上评估，并写出模型卡。

    python -m nxdrp.checkers.m5_performance.force_train

切法和 PERF-01 一致：训练 240 / 标定 60 / 测试 60。
"""

from __future__ import annotations

import math
import os
import random

from .force_model import MODEL_PATH, predict_force, predict_withdrawal
from .force_physics import FEATURE_NAMES, RULE_PARAMS, feature_vector
from .force_samples import SAMPLES_PATH, load
from .tree_model import apply_interval, dump, fit, fit_interval

HERE = os.path.dirname(os.path.abspath(__file__))
CARD_PATH = os.path.join(HERE, "PERF02模型卡.md")
TRAIN_N = 240
CAL_N = 60
TEST_N = 60
SEED = 20261029
BAND_LOW = 1.0
BAND_HIGH = 100.0
TARGET_BAND_MEDIAN_AE_N = 1.0
TARGET_COVERAGE = 0.70


def _rows(samples: list[dict]) -> list[tuple[list[float], float, float]]:
    out = []
    for s in samples:
        x = feature_vector(
            s["length_mm"], s["width_mm"], s["thickness_mm"], s["overlap_mm"], s["e_gpa"], s["friction_coeff"]
        )
        out.append((x, float(s["insertion_n"]), float(s["withdrawal_n"])))
    return out


def _metrics(model: dict, rows: list[tuple[list[float], float, float]], q_low: float, q_high: float) -> dict:
    abs_err = []
    band_err = []
    covered = 0
    band_n = 0
    for x, y, _w in rows:
        pred = predict_force(model, x)
        low, high = apply_interval(pred, q_low, q_high)
        abs_err.append(abs(pred - y))
        if BAND_LOW <= y <= BAND_HIGH:
            band_n += 1
            band_err.append(abs(pred - y))
            if low <= y <= high:
                covered += 1
    abs_err.sort()
    band_err.sort()
    n = len(abs_err)
    return {
        "mae_n": sum(abs_err) / n if n else None,
        "median_ae_n": abs_err[n // 2] if n else None,
        "band_median_ae_n": band_err[len(band_err) // 2] if band_err else None,
        "coverage": (covered / band_n) if band_n else None,
        "n": n,
        "band_n": band_n,
    }


def render_card(info: dict) -> str:
    materials = "、".join(f"{k}（E={v['e_gpa']:.0f} GPa）" for k, v in RULE_PARAMS["materials"].items())
    return f"""# PERF-02 模型卡：插拔力

## 预测

输入：簧片长度、宽度、厚度、过盈量、弹性模量、摩擦系数、接触点数。  
输出：插入力、拔出力（N），置信度 {info["confidence"]:.0%} 的区间。

插入力上限 {RULE_PARAMS["insertion_force_max_n"]:.1f} N，拔出力下限 {RULE_PARAMS["withdrawal_force_min_n"]:.1f} N，在 `rules/dfm_default.json` 的 R-PERF-02。

## 数据来源

共 {info["count"]} 条，随机种子 {SEED}。

| 用途 | 条数 | 用途说明 |
|---|---|---|
| 训练 | {info["train_n"]} | 拟合回归树 |
| 标定 | {info["cal_n"]} | 定区间分位数 |
| 测试 | {info["test_n"]} | 只报误差和覆盖率 |

标签 = 悬臂梁摩擦公式 × 对数正态散差（标准差 0.08，截断 0.75–1.30）。`label_source` = `cantilever_friction_v1`。

- I = b t³ / 12
- k = 3 E I / L³
- Fn = k δ
- Fin = n · Fn · (μ + tanθ) / (1 − μ·tanθ)
- Fout = n · Fn · μ

弹性模量：{materials}。μ、θ、n 取规则默认值。材料表不含纯铜。  
替换 `insertion_n` / `withdrawal_n` 后运行 `python -m nxdrp.checkers.m5_performance.force_train`。

## 模型

回归树拟合「插入力 / 公式插入力」的对数。点预测 = 公式 × exp(修正)。  
最大深度 4，叶节点至少 6 条。  
特征：长度、宽度、厚度、过盈量、弹性模量、摩擦系数的对数。

## 误差

测试集 {info["test_n"]} 条。

| 指标 | 数值 |
|---|---|
| 中位绝对误差 | {info["median_ae_n"]:.3f} N |
| 平均绝对误差 | {info["mae_n"]:.3f} N |
| 插入力 {BAND_LOW:.0f}–{BAND_HIGH:.0f} N 档中位绝对误差 | {info["band_median_ae_n"]:.3f} N |
| {info["confidence"]:.0%} 区间覆盖率 | {info["coverage"]:.1%} |

q_low = {info["q_low"]:.4f}，q_high = {info["q_high"]:.4f}。  
自查线：{BAND_LOW:.0f}–{BAND_HIGH:.0f} N 档中位绝对误差 ≤ {TARGET_BAND_MEDIAN_AE_N:.1f} N，覆盖率 ≥ {TARGET_COVERAGE:.0%}。  
本次：{info["band_median_ae_n"]:.3f} N，覆盖率 {info["coverage"]:.1%}。

## 范围

| 量 | 范围 |
|---|---|
| 簧片长度 | {RULE_PARAMS["length_mm_min"]}–{RULE_PARAMS["length_mm_max"]} mm |
| 簧片宽度 | {RULE_PARAMS["width_mm_min"]}–{RULE_PARAMS["width_mm_max"]} mm |
| 簧片厚度 | {RULE_PARAMS["thickness_mm_min"]}–{RULE_PARAMS["thickness_mm_max"]} mm |
| 过盈量 | {RULE_PARAMS["overlap_mm_min"]}–{RULE_PARAMS["overlap_mm_max"]} mm |
| 摩擦系数 | {RULE_PARAMS["friction_min"]}–{RULE_PARAMS["friction_max"]} |
| 材料 | CuSn6、CuBe2、CuZn37 |
| 区间置信度 | {info["confidence"]} |

## 范围外

尺寸、过盈量、摩擦系数或材料超出上表时，检查项跳过并写明缺项。

## 局限

- 悬臂梁、小变形、线弹性。不含塑性、接触非线性、二次插入。
- 摩擦系数为常数。
- 不含壳体导向、锁扣、密封圈、对插偏斜。
- 几何取自零件包围盒，最短边为厚度。
"""


def train(samples_path: str = SAMPLES_PATH, model_path: str = MODEL_PATH, card_path: str = CARD_PATH) -> dict:
    payload = load(samples_path)
    samples = list(payload["samples"])
    need = TRAIN_N + CAL_N + TEST_N
    if len(samples) < need:
        raise SystemExit(f"样本只有 {len(samples)} 条，至少需要 {need} 条")

    rng = random.Random(SEED)
    rng.shuffle(samples)
    train_s = samples[:TRAIN_N]
    cal_s = samples[TRAIN_N:TRAIN_N + CAL_N]
    test_s = samples[TRAIN_N + CAL_N:TRAIN_N + CAL_N + TEST_N]

    train_rows = []
    for sample in train_s:
        clean = float(sample["insertion_clean_n"])
        observed = float(sample["insertion_n"])
        x = feature_vector(
            sample["length_mm"], sample["width_mm"], sample["thickness_mm"],
            sample["overlap_mm"], sample["e_gpa"], sample["friction_coeff"],
        )
        train_rows.append((x, math.log(max(observed, 1e-9) / max(clean, 1e-9))))

    tree = fit(train_rows, depth=4)
    confidence = float(RULE_PARAMS["interval_confidence"])
    model = {
        "schema": "perf02-tree-v1",
        "feature_names": list(FEATURE_NAMES),
        "target": "log_correction",
        "interval_confidence": confidence,
        "q_low": 1.0,
        "q_high": 1.0,
        "contacts": float(RULE_PARAMS["contacts"]),
        "lead_angle_deg": float(RULE_PARAMS["lead_angle_deg"]),
        "tree": tree,
    }

    cal_rows = _rows(cal_s)
    cal_pred = [predict_force(model, x) for x, _y, _w in cal_rows]
    band_pred = []
    band_actual = []
    for pred, (_x, actual, _w) in zip(cal_pred, cal_rows):
        if BAND_LOW <= actual <= BAND_HIGH:
            band_pred.append(pred)
            band_actual.append(actual)
    q_low, q_high = fit_interval(band_pred, band_actual, confidence)

    test_rows = _rows(test_s)
    model.update({
        "q_low": q_low,
        "q_high": q_high,
        "tree": tree,
        "train_size": len(train_rows),
        "cal_size": len(cal_rows),
        "test_size": len(test_rows),
        "split": {"train": len(train_rows), "cal": len(cal_rows), "test": len(test_rows)},
        "sample_count": len(samples),
        "label_source": payload.get("label_source", ""),
        "metrics": _metrics(model, test_rows, q_low, q_high),
        "cal_metrics": _metrics(model, cal_rows, q_low, q_high),
        "scope": {
            "length_mm": [RULE_PARAMS["length_mm_min"], RULE_PARAMS["length_mm_max"]],
            "width_mm": [RULE_PARAMS["width_mm_min"], RULE_PARAMS["width_mm_max"]],
            "thickness_mm": [RULE_PARAMS["thickness_mm_min"], RULE_PARAMS["thickness_mm_max"]],
            "overlap_mm": [RULE_PARAMS["overlap_mm_min"], RULE_PARAMS["overlap_mm_max"]],
            "friction_coeff": [RULE_PARAMS["friction_min"], RULE_PARAMS["friction_max"]],
            "materials": list(RULE_PARAMS["materials"]),
        },
        "targets": {"band_median_ae_n": TARGET_BAND_MEDIAN_AE_N, "coverage": TARGET_COVERAGE},
    })
    dump(model_path, model)

    metrics = model["metrics"]
    card = render_card(
        {
            "confidence": confidence,
            "count": len(samples),
            "train_n": len(train_rows),
            "cal_n": len(cal_rows),
            "test_n": len(test_rows),
            "mae_n": metrics["mae_n"],
            "median_ae_n": metrics["median_ae_n"],
            "band_median_ae_n": metrics["band_median_ae_n"],
            "coverage": metrics["coverage"],
            "q_low": q_low,
            "q_high": q_high,
        }
    )
    with open(card_path, "w", encoding="utf-8") as fh:
        fh.write(card)
    print(
        f"训练 {len(train_rows)} / 标定 {len(cal_rows)} / 测试 {len(test_rows)}，"
        f"测试集中位误差 {metrics['median_ae_n']:.3f} N，"
        f"{BAND_LOW:.0f}–{BAND_HIGH:.0f} N 档 {metrics['band_median_ae_n']:.3f} N，"
        f"独立覆盖率 {metrics['coverage']:.1%}"
    )
    print(f"区间分位 q_low={q_low:.4f}  q_high={q_high:.4f}")
    print(f"模型 {model_path}")
    print(f"模型卡 {card_path}")
    return model


def main() -> None:
    train()


if __name__ == "__main__":
    main()
