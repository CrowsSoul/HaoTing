# -*- coding: utf-8 -*-
"""训练回归树、标定 80% 区间，并写出模型卡。

    python -m nxdrp.checkers.m5_performance.train

先有 data/samples.json。训练用前 300 条打乱后的样本，其余做验证。
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
TRAIN_N = 300
SEED = 20261029


def _rows(samples: list[dict]) -> list[tuple[list[float], float]]:
    out = []
    for s in samples:
        x = feature_vector(s["area_mm2"], s["length_mm"], s["rho_ohm_m"], s["current_a"], s["h_w_m2k"])
        out.append((x, float(s["delta_t_c"])))
    return out


def _metrics(model: dict, val_rows: list[tuple[list[float], float]], q_low: float, q_high: float) -> dict:
    abs_err = []
    band_err = []
    covered = 0
    band_n = 0
    for x, y in val_rows:
        pred = predict_temperature(model, x)
        low, high = apply_interval(pred, q_low, q_high)
        abs_err.append(abs(pred - y))
        if 1.0 <= y <= 200.0:
            band_n += 1
            band_err.append(abs(pred - y))
            if low <= y <= high:
                covered += 1
    abs_err.sort()
    band_err.sort()
    n = len(abs_err)
    return {
        "mae_c": sum(abs_err) / n,
        "median_ae_c": abs_err[n // 2],
        "band_median_ae_c": band_err[len(band_err) // 2] if band_err else None,
        "coverage": (covered / band_n) if band_n else None,
        "n": n,
        "band_n": band_n,
    }


def render_card(info: dict) -> str:
    materials = "、".join(f"{k}（ρ={v['rho_ohm_m']:.3e} Ω·m）" for k, v in RULE_PARAMS["materials"].items())
    return f"""# PERF-01 模型卡：载流–温升

## 这个模型预测什么

给定端子截面积、导体长度、材料电阻率、电流和对流换热系数，预测稳态温升 ΔT（°C）。
同时给出置信度 {info["confidence"]:.0%} 的区间，以及让温升回到允许值以下的电流。

允许温升不是模型学出来的，默认 {RULE_PARAMS["max_rise_c"]:.0f} °C，放在 `rules/dfm_default.json` 的 `max_rise_c`。

## 数据从哪来

共 {info["count"]} 条，训练 {info["train_n"]} 条，验证 {info["val_n"]} 条。随机种子 {SEED}。

标签**不是** NX 热仿真。当前仓库没有热仿真入口，标签用圆柱导体集总对流模型生成：

- 发热 P = I² ρ L / A
- 散热面积 = 侧面 π d L + 两端 2A
- ΔT = P / (h · 散热面积)

再乘一个标准差 0.08 的对数正态系数（截断在 0.75～1.30），用来代表仿真散差。
材料电阻率初值：{materials}。纯铜取 IACS 100% 的 1.724×10⁻⁸ Ω·m，其余三种是弹簧材料的量级，工程师可以在规则表里改。

平台方若提供仿真或实测温升：保留特征列，替换 `delta_t_c`，再运行 `python -m nxdrp.checkers.m5_performance.train`。

## 模型

回归树不直接拟合温升，只拟合「样本温升 / 集总公式」的对数修正。
点预测 = 集总公式 × exp(修正)。深度最多 4，叶节点至少 6 条，避免把散差背下来。
当前这批标签只有随机散差、没有另一套仿真，所以修正系数接近 1。
换成真实仿真温升之后，同一棵树会学到公式和仿真之间的差别。
特征是截面积、长度、电阻率、电流、换热系数的对数。
环境温度不进入温升模型。它只和温升相加得到绝对温度，并用来判断工况是否超出训练范围。

验证集中位绝对误差 {info["median_ae_c"]:.2f} °C。平均绝对误差 {info["mae_c"]:.2f} °C，
这个平均数被少数上千度的极端样本拉高，不代表 45 °C 附近的误差。
温升在 1–200 °C 的验证样本上，中位绝对误差 {info["band_median_ae_c"]:.2f} °C。

{info["confidence"]:.0%} 区间只用这档温升的验证样本标定（名义覆盖 {info["coverage"]:.1%}）。
验证集只有几十条，而且标定和覆盖用的是同一批，所以这个覆盖率不能当成独立考试成绩。
换一批仿真数据后要重新训练、重新看区间。

## 适用范围

| 量 | 范围 |
|---|---|
| 截面积 | {RULE_PARAMS["area_mm2_min"]}–{RULE_PARAMS["area_mm2_max"]} mm² |
| 导体长度 | {RULE_PARAMS["length_mm_min"]}–{RULE_PARAMS["length_mm_max"]} mm |
| 电流 | {RULE_PARAMS["current_a_min"]}–{RULE_PARAMS["current_a_max"]} A |
| 环境温度 | {RULE_PARAMS["ambient_temp_c_min"]}–{RULE_PARAMS["ambient_temp_c_max"]} °C |
| 对流换热系数 | {RULE_PARAMS["h_w_m2k_min"]}–{RULE_PARAMS["h_w_m2k_max"]} W/(m²·K) |
| 材料 | Cu、CuSn6、CuZn37、CuBe2 |
| 区间置信度 | {info["confidence"]}（模型只标定了这一档） |

截面积取零件上半径最小的圆柱面，A = πr²，长度由该圆柱侧面面积反推。这是载流瓶颈，不是整个零件的包围盒。

## 超出范围为什么不能用

树在训练范围外会落到边缘的叶子上，数字看起来正常，其实是外推。
电流、尺寸、材料、换热系数或置信度对不上时，检查项直接跳过，并写明缺什么，不编一个温升。

绝缘件（例如 PA66 外壳）和没有材料字段的零件也不预测。没有圆柱面就无法估计截面积，同样跳过。
"""


def train(samples_path: str = SAMPLES_PATH, model_path: str = MODEL_PATH, card_path: str = CARD_PATH) -> dict:
    payload = load(samples_path)
    samples = list(payload["samples"])
    if len(samples) < TRAIN_N + 30:
        raise SystemExit(f"样本只有 {len(samples)} 条，至少需要 {TRAIN_N + 30} 条才留得出验证集")
    rng = random.Random(SEED)
    rng.shuffle(samples)
    train_rows = []
    for sample in samples[:TRAIN_N]:
        clean = float(sample["delta_t_clean_c"])
        observed = float(sample["delta_t_c"])
        x = feature_vector(
            sample["area_mm2"], sample["length_mm"], sample["rho_ohm_m"], sample["current_a"], sample["h_w_m2k"]
        )
        train_rows.append((x, math.log(max(observed, 1e-6) / max(clean, 1e-6))))
    val_rows = _rows(samples[TRAIN_N:])
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
    val_pred = [predict_temperature(model, x) for x, _ in val_rows]
    band_pred = []
    band_actual = []
    for pred, (_, actual) in zip(val_pred, val_rows):
        if 1.0 <= actual <= 200.0:
            band_pred.append(pred)
            band_actual.append(actual)
    q_low, q_high = fit_interval(band_pred, band_actual, confidence)
    model["q_low"] = q_low
    model["q_high"] = q_high
    metrics = _metrics(model, val_rows, q_low, q_high)
    model.update({
        "interval_confidence": confidence,
        "q_low": q_low,
        "q_high": q_high,
        "tree": tree,
        "train_size": len(train_rows),
        "val_size": len(val_rows),
        "sample_count": len(samples),
        "label_source": payload.get("label_source", ""),
        "metrics": metrics,
        "scope": {
            "area_mm2": [RULE_PARAMS["area_mm2_min"], RULE_PARAMS["area_mm2_max"]],
            "length_mm": [RULE_PARAMS["length_mm_min"], RULE_PARAMS["length_mm_max"]],
            "current_a": [RULE_PARAMS["current_a_min"], RULE_PARAMS["current_a_max"]],
            "ambient_temp_c": [RULE_PARAMS["ambient_temp_c_min"], RULE_PARAMS["ambient_temp_c_max"]],
            "h_w_m2k": [RULE_PARAMS["h_w_m2k_min"], RULE_PARAMS["h_w_m2k_max"]],
            "materials": list(RULE_PARAMS["materials"]),
        },
    })
    dump(model_path, model)
    card = render_card(
        {
            "confidence": confidence,
            "count": len(samples),
            "train_n": len(train_rows),
            "val_n": len(val_rows),
            "mae_c": metrics["mae_c"],
            "median_ae_c": metrics["median_ae_c"],
            "band_median_ae_c": metrics["band_median_ae_c"],
            "coverage": metrics["coverage"],
        }
    )
    with open(card_path, "w", encoding="utf-8") as fh:
        fh.write(card)
    print(
        f"训练 {len(train_rows)} / 验证 {len(val_rows)}，"
        f"MAE {metrics['mae_c']:.2f} °C，区间覆盖 {metrics['coverage']:.1%}"
    )
    print(f"模型 {model_path}")
    print(f"模型卡 {card_path}")
    return model


def main() -> None:
    train()


if __name__ == "__main__":
    main()
