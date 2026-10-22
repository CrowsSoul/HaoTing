# 评测场景（demo scenes）

`mockdata/models/` 下三份装配数据，专门给检查器当靶子。

不是随便找的模型：**位置是刻意摆的**，所以「应该看到什么」有标准答案，可以手算复核。

| 场景 | 组件数 | 面数 | 用来测什么 |
|---|---|---|---|
| `demo_asm` | 6 | 78 | 混合：正常间距 / 0.15 贴近 / 重叠 / 独立 |
| `demo_normal` | 5 | — | **纯负样本**：间距全 20 mm，不该有任何间隙告警 |
| `demo_edge` | 4 | — | **阈值边界**：0.299 / 0.300 / 0.302 跨过 0.3 |

零件都是 `Pressure Port` 的副本，单个宽 30 mm、1 个实体、13 个面
（7 B 曲面 / 3 圆柱 / 2 平面 / 1 球面）。所以相邻件的关系完全由 X 位置决定。

---

## 一、demo_asm（混合场景）

| 组件 | X 位置 | 占位 | 意图 |
|---|---|---|---|
| `A_BASE` | 0 | 0 – 30 | 基准 |
| `B_NEAR` | 30.15 | 30.15 – 60.15 | 与 A 相距 **0.15 mm** |
| `C_FAR` | 60 | 60 – 90 | 与 B 重叠 0.15 mm |
| `D_NEAR2` | 90.3 | 90.3 – 120.3 | 与 C 相距 **0.3 mm**（正好等于阈值） |
| `E_OVERLAP` | 15 | 15 – 45 | 与 A、B 半重叠 |
| `F_ALONE` | 150 | 150 – 180 | 独立，谁的边都不沾 |

实测：`DFM-02` 出 5 条（0.15 / 0.3 / 0 三种情况都有），`DFM-31` 出 18 条（6 × 3 个非标孔）。
标注集 `mockdata/labels/demo_asm.labels.json`，打分 `macro-F1 = 1.000`。

---

## 二、demo_normal（纯负样本）

5 个组件，间距全部 20 mm：`A`=0、`B`=50、`C`=100、`D`=150、`E`=200。

**预期：`DFM-02` 一条都不报。**

这个场景不产出 F1（没有正样本可算，评测会显示 `macro-F1: -`），只看**误报率**。
它的价值是：任何"见谁都报"的检查器，一跑就露馅。

---

## 三、demo_edge（阈值边界）

4 个组件，间距卡在 `min_clearance_mm = 0.3` 两侧：

| 相邻对 | 间距 | 预期 |
|---|---|---|
| A – B | 0.299 | 报（小于阈值） |
| B – C | 0.300 | 报（**等于**阈值；判定是 `gap > 阈值` 才跳过，所以等于要报） |
| C – D | 0.302 | **不报**（已过阈值） |

实测正是 2 条：0.299 和 0.300，0.302 那对没有出现。

这个场景专治两类毛病：

- 条件写成 `>=` 的人，会漏掉 0.300 那条；
- 阈值读错或写死 0.5 的人，0.302 会误报。

---

## 四、能给哪些检查器用

| 检查器 | 能试什么 |
|---|---|
| DFM-02 最小间隙 | 三种间距 + 纯负样本 + 边界，几乎全覆盖 |
| DFM-01 干涉 | `demo_asm` 里 A↔E、B↔C、B↔E 三组重叠 |
| DFM-31 非标刀具 | 每个零件 3 个非标孔（Ø2.22 / Ø6.25 / Ø9.49） |
| DFM-32 圆角一致性 | 每件只有 1 个环面，种类不足，可当负样本 |
| 装配类（孔对齐、紧固件） | 多组件 + 真实变换矩阵，可以练配对 |

**不能测什么**：壁厚、拔模角、倒钩这类注塑项。这三个场景的零件是同一份文件复制的，
几何缺陷不在里面——要测那些，需要有缺陷的零件本身，不是装配。

---

## 五、跑一遍

```powershell
python -m nxdrp check mockdata/models/demo_asm.model.json    -o f_asm.json
python -m nxdrp check mockdata/models/demo_normal.model.json -o f_norm.json
python -m nxdrp check mockdata/models/demo_edge.model.json   -o f_edge.json

python -m nxdrp eval f_asm.json  -l mockdata/labels/demo_asm.labels.json
python -m nxdrp eval f_norm.json -l mockdata/labels/demo_normal.labels.json
python -m nxdrp eval f_edge.json -l mockdata/labels/demo_edge.labels.json
```

`demo_normal` 会显示 `macro-F1: -（本场景没有正样本，只看误报率）`，误报率应当是 0。

---

## 六、怎么重建或加场景

三个场景由**一次** NX 启动建出来：

```python
adapter.run_journal("build_demo_assembly", {
    "src": r"...\Pressure Port.prt",
    "dir": r"...\mockdata\scenes",
})
```

改 `nxdrp/journals/build_demo_assembly.py` 里三个 `SCENE_*` 常量即可；
`SCENE_EDGE` 那种把间距卡在阈值上下的写法，是加场景最划算的一种。

**一个坑**：NX 按**文件名**（不是路径）认零件，多个场景在同一会话里建时必须给零件名加场景前缀，
否则第二个场景会报 `File already exists`。脚本里已经用 `<场景名>_<组件名>.prt` 了。

---

## 七、还想更复杂的话

现在这批零件几何是同质的。要测 DFM 特征（薄壁、拔模、圆角），需要**真正带缺陷的零件**。
两条路：

1. 让甲方给 3~5 个真实产品模型（带已知缺陷）——最贴近验收；
2. 用 NX 建模 API 造带缺陷的块体——要专门写建模 journal，比搭装配麻烦得多。

第 1 条更值，这也是启动会要跟甲方要的东西之一。
