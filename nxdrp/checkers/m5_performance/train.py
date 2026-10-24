# -*- coding: utf-8 -*-
"""训练回归树、标定 80% 区间、在独立测试集上评估，并写出模型卡。

    python -m nxdrp.checkers.m5_performance.train

360 条样本按固定种子打乱后切成三段：

  * 训练集 240 条：拟合树；
  * 标定集 60 条：定 80% 区间的分位数；
  * 测试集 60 条：既不参与训练也不参与标定，只用来报误差和覆盖率。

早期版本是 300/60 两段，标定和评估用的是同一批验证样本，
覆盖率不能当成独立结果。现在拆成三段，模型卡里报的是测试集上的数。
"""

from __future__ import annotations

import math
import os
import random

from .physics import FEATURE_NAMES, RULE_PARAMS, feature_vector
from .samples import SAMPLES_PATH, load
from .tree_model import apply_interval, dump, fit, fit_interval, predict_temperature

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "data", "model.json")
CARD_PATH = os.path.join(HERE, "模型卡.md")
TRAIN_N = 240
CAL_N = 60
TEST_N = 60
SEED = 20261029

#: 区间和误差只看这一档温升。温升到上千度的样本是极端外推，不该主导指标。
BAND_LOW = 1.0
BAND_HIGH = 200.0

#: 自定的误差目标。计划书只写「误差在约定范围内」没说数，先按这个口径自查，
#: 等老师给出正式数值再照改（改这两个常数即可，模型卡会跟着变）。
TARGET_BAND_MEDIAN_AE_C = 2.0
TARGET_COVERAGE = 0.70


def _rows(samples: list[dict]) -> list[tuple[list[float], float]]:
    out = []
    for s in samples:
        x = feature_vector(s["area_mm2"], s["length_mm"], s["rho_ohm_m"], s["current_a"], s["h_w_m2k"])
        out.append((x, float(s["delta_t_c"])))
    return out


def _metrics(model: dict, rows: list[tuple[list[float], float]], q_low: float, q_high: float) -> dict:
    abs_err = []
    band_err = []
    covered = 0
    band_n = 0
    for x, y in rows:
        pred = predict_temperature(model, x)
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
        "mae_c": sum(abs_err) / n if n else None,
        "median_ae_c": abs_err[n // 2] if n else None,
        "band_median_ae_c": band_err[len(band_err) // 2] if band_err else None,
        "coverage": (covered / band_n) if band_n else None,
        "n": n,
        "band_n": band_n,
    }


def render_card(info: dict) -> str:
    materials = "、".join(f"{k}（ρ={v['rho_ohm_m']:.3e} Ω·m）" for k, v in RULE_PARAMS["materials"].items())
    return f"""# PERF-01 模型卡：载流–温升

## 预测

输入：截面积、导体长度、材料电阻率、电流、对流换热系数。  
输出：稳态温升 ΔT（°C），置信度 {info["confidence"]:.0%} 的区间，以及温升回到允许值以下的电流。

允许温升默认 {RULE_PARAMS["max_rise_c"]:.0f} °C，在 `rules/dfm_default.json` 的 `max_rise_c`。

## 数据来源

共 {info["count"]} 条，随机种子 {SEED}。

| 用途 | 条数 | 用途说明 |
|---|---|---|
| 训练 | {info["train_n"]} | 拟合回归树 |
| 标定 | {info["cal_n"]} | 定区间分位数 |
| 测试 | {info["test_n"]} | 只报误差和覆盖率 |

温升由模拟 NX 仿真 `thermal_solver.simulate_nx_delta_t` 生成。  
在集总对流之外含辐射、电阻率随温度、端部接触电阻。

集总公式：

- 发热 P = I² ρ L / A
- 散热面积 = 侧面 π d L + 两端 2A
- ΔT = P / (h · 散热面积)

材料电阻率：{materials}。纯铜为 1.724×10⁻⁸ Ω·m。  
替换 `delta_t_c` 后运行 `python -m nxdrp.checkers.m5_performance.train`。

## 模型

回归树拟合「样本温升 / 集总公式」的对数。  
点预测 = 集总公式 × exp(修正)。最大深度 4，叶节点至少 6 条。  
特征：截面积、长度、电阻率、电流、换热系数的对数。  
环境温度用于绝对温度和范围判断，不作为特征。

## 误差

测试集 {info["test_n"]} 条，未参与训练，未参与标定。

| 指标 | 数值 |
|---|---|
| 中位绝对误差 | {info["median_ae_c"]:.2f} °C |
| 平均绝对误差 | {info["mae_c"]:.2f} °C |
| 温升 {BAND_LOW:.0f}–{BAND_HIGH:.0f} °C 档中位绝对误差 | {info["band_median_ae_c"]:.2f} °C |
| {info["confidence"]:.0%} 区间覆盖率 | {info["coverage"]:.1%} |

平均绝对误差含上千度样本。标定集分位数 q_low = {info["q_low"]:.4f}，q_high = {info["q_high"]:.4f}。  
自查线：{BAND_LOW:.0f}–{BAND_HIGH:.0f} °C 档中位绝对误差 ≤ {TARGET_BAND_MEDIAN_AE_C:.1f} °C，覆盖率 ≥ {TARGET_COVERAGE:.0%}。  
本次：{info["band_median_ae_c"]:.2f} °C，覆盖率 {info["coverage"]:.1%}。

## 范围

| 量 | 范围 |
|---|---|
| 截面积 | {RULE_PARAMS["area_mm2_min"]}–{RULE_PARAMS["area_mm2_max"]} mm² |
| 导体长度 | {RULE_PARAMS["length_mm_min"]}–{RULE_PARAMS["length_mm_max"]} mm |
| 电流 | {RULE_PARAMS["current_a_min"]}–{RULE_PARAMS["current_a_max"]} A |
| 环境温度 | {RULE_PARAMS["ambient_temp_c_min"]}–{RULE_PARAMS["ambient_temp_c_max"]} °C |
| 对流换热系数 | {RULE_PARAMS["h_w_m2k_min"]}–{RULE_PARAMS["h_w_m2k_max"]} W/(m²·K) |
| 材料 | Cu、CuSn6、CuZn37、CuBe2 |
| 区间置信度 | {info["confidence"]} |

截面积取半径最小的圆柱面，A = πr²，长度由该圆柱侧面面积反推。

## 范围外

电流、尺寸、材料、换热系数或置信度超出上表时，检查项跳过并写明缺项。  
无材料、绝缘材料（如 PA66）、无圆柱面时同样跳过。

## 局限

- 模拟 NX 含对流、辐射、电阻随温度和端部接触。不含壳体导热，不含网格。
- 0.5–2 mm² 的中位误差含高温点。分档见 `python -m nxdrp.checkers.m5_performance.evaluate`。
- 未参与训练的材料，覆盖率下降。
"""


def train(samples_path: str = SAMPLES_PATH, model_path: str = MODEL_PATH, card_path: str = CARD_PATH) -> dict:
    payload = load(samples_path)
    samples = list(payload["samples"])
    need = TRAIN_N + CAL_N + TEST_N
    if len(samples) < need:
        raise SystemExit(f"样本只有 {len(samples)} 条，至少需要 {need} 条才切得出训练/标定/测试三段")

    rng = random.Random(SEED)
    rng.shuffle(samples)
    train_s = samples[:TRAIN_N]
    cal_s = samples[TRAIN_N:TRAIN_N + CAL_N]
    test_s = samples[TRAIN_N + CAL_N:TRAIN_N + CAL_N + TEST_N]

    train_rows = []
    for sample in train_s:
        clean = float(sample["delta_t_clean_c"])
        observed = float(sample["delta_t_c"])
        x = feature_vector(
            sample["area_mm2"], sample["length_mm"], sample["rho_ohm_m"], sample["current_a"], sample["h_w_m2k"]
        )
        train_rows.append((x, math.log(max(observed, 1e-6) / max(clean, 1e-6))))

    tree = fit(train_rows, depth=4)
    confidence = float(RULE_PARAMS["interval_confidence"])
    model = {
        "schema": "perf01-tree-v1",
        "feature_names": list(FEATURE_NAMES),
        "target": "log_correction",
        "interval_confidence": confidence,
        "q_low": 1.0,
        "q_high": 1.0,
        "tree": tree,
    }

    cal_rows = _rows(cal_s)
    cal_pred = [predict_temperature(model, x) for x, _ in cal_rows]
    band_pred = []
    band_actual = []
    for pred, (_, actual) in zip(cal_pred, cal_rows):
        if BAND_LOW <= actual <= BAND_HIGH:
            band_pred.append(pred)
            band_actual.append(actual)
    q_low, q_high = fit_interval(band_pred, band_actual, confidence)

    test_rows = _rows(test_s)
    model.update({
        "interval_confidence": confidence,
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
            "area_mm2": [RULE_PARAMS["area_mm2_min"], RULE_PARAMS["area_mm2_max"]],
            "length_mm": [RULE_PARAMS["length_mm_min"], RULE_PARAMS["length_mm_max"]],
            "current_a": [RULE_PARAMS["current_a_min"], RULE_PARAMS["current_a_max"]],
            "ambient_temp_c": [RULE_PARAMS["ambient_temp_c_min"], RULE_PARAMS["ambient_temp_c_max"]],
            "h_w_m2k": [RULE_PARAMS["h_w_m2k_min"], RULE_PARAMS["h_w_m2k_max"]],
            "materials": list(RULE_PARAMS["materials"]),
        },
        "targets": {
            "band_median_ae_c": TARGET_BAND_MEDIAN_AE_C,
            "coverage": TARGET_COVERAGE,
        },
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
            "mae_c": metrics["mae_c"],
            "median_ae_c": metrics["median_ae_c"],
            "band_median_ae_c": metrics["band_median_ae_c"],
            "coverage": metrics["coverage"],
            "q_low": q_low,
            "q_high": q_high,
        }
    )
    with open(card_path, "w", encoding="utf-8") as fh:
        fh.write(card)
    print(
        f"训练 {len(train_rows)} / 标定 {len(cal_rows)} / 测试 {len(test_rows)}，"
        f"测试集中位误差 {metrics['median_ae_c']:.2f} °C，"
        f"{BAND_LOW:.0f}–{BAND_HIGH:.0f} °C 档 {metrics['band_median_ae_c']:.2f} °C，"
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
