# M6A 钣金 DFM — 工作完成情况（已合并入内置子包）

- 负责人：于大淇（M6A）
- 日期：2026-10-22
- 范围：DFM-19 ~ DFM-26（8 项钣金检查）
- 位置：`nxdrp/checkers/m6a_sheet_metal/`
- 结论：**流程级验证通过**（发现 → 规则 → 检查 → Finding → 评测 → 报告），
  已合并进共享框架。**未达到验收精度**，本轮目标本身也不是验收精度。

> 独立插件 `m6a_dfm_plugin/` 已在合并时退役（历史见 commit `ea694ac`）。
> 手头没有真实 NX 钣金 `.prt`，数据契约也没有料厚、弯曲线、翻边、凸台、槽等专有
> 字段。所有检查为低置信度几何粗筛，Finding 带 `【粗筛】`、`coarse: true`、
> `confidence ≤ 0.6`，必须人工复核。

---

## 1. 合并后的文件位置

```text
nxdrp/checkers/m6a_sheet_metal/
├── __init__.py                 # 导出 8 个 checker
├── _m6a_dfm_common.py          # 料厚推断、圆柱分类、孔组、槽识别
├── dfm19_bend_radius.py        # 最小弯曲半径
├── dfm20_hole_edge.py          # 孔到边缘距离
├── dfm21_hole_spacing.py       # 孔间距
├── dfm22_hole_thickness.py     # 孔径与料厚比
├── dfm23_slot_width.py         # 槽的最小宽度
├── dfm24_bend_cutout.py        # 折弯与切口距离（二期占位）
├── dfm25_flange_height.py      # 翻边高度
├── dfm26_boss_height.py        # 冲压凸台高度（二期占位）
└── README.md

rules/dfm_default.json          # R-DFM-19 ~ R-DFM-26 参数（v0.2）
tests/test_m6a_common.py        # 公共几何工具测试
tests/test_m6a_checkers.py      # 8 项流程基线测试
tests/test_m6a_cli.py           # 发现、规则一致性、CLI 端到端测试
tests/fixtures/bent_sheet.model.json   # 合成夹具
mockdata/labels/m6a/*.labels.json      # 5 份流程验证标注集
docs/M6A_WORK_STATUS.md         # 本文档
```

`tools/gen_rules.py` 的 `PARAM_SKELETON` 已同步 DFM-19~26，重新生成规则库不会
丢失合并参数。

---

## 2. 验证结果（按 `docs/` 的三个验证环节）

### 2.1 评测链路（`docs/LABELING.md`）

按标注规范整理 5 份标注集（正样本 + 负样本），执行
`nxdrp check` → `nxdrp eval`：

| 模型 | 标注（正/负） | 预测 | TP | FP | FN | macro-F1 | 误报率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `bent_sheet`（合成夹具） | 8 / 5 | 8 | 8 | 0 | 0 | 1.000 | 0.000 |
| `plate_holes` | 4 / 0 | 4 | 4 | 0 | 0 | 1.000 | 0.000 |
| `deep_slot` | 1 / 0 | 1 | 1 | 0 | 0 | 1.000 | 0.000 |
| `bosses` | 1 / 1 | 1 | 1 | 0 | 0 | 1.000 | 0.000 |
| `board_a` | 2 / 1 | 2 | 2 | 0 | 0 | 1.000 | 0.000 |

**重要说明**：标注按夹具/Mock 的设计意图和几何尺寸人工整理，与同一套粗筛几何
同源。满分只证明「标注 → 匹配 → 指标」链路跑通，**不能证明验收精度**；
`plate_holes` / `deep_slot` 只有正样本，负样本覆盖有限。

### 2.2 场景验证（`docs/DEMO_SCENE.md`）

在三个共享演示场景上运行完整检查（含 M6A），使用共享规则和共享标注：

| 场景 | 总 Finding | 其中 M6A | checker 状态 | macro-F1 | P / R | 误报率 |
|---|---:|---:|---|---:|---:|---:|
| `demo_asm` | 35 | 24（20:6，22:6，26:12） | ok 7 / skipped 4 | 1.000 | 1.000 / 1.000 | 0.000 |
| `demo_normal` | 25 | 20（20:5，22:5，26:10） | ok 7 / skipped 4 | —（无正样本） | 0.000 / 0.000 | 0.000 |
| `demo_edge` | 22 | 16（20:4，22:4，26:8） | ok 7 / skipped 4 | 1.000 | 1.000 / 1.000 | 0.000 |
| `demo_large` | 120 | 96（20:24，22:24，26:48） | ok 7 / skipped 4 | 未标注 | — | — |

- 现有 DFM-02 / DFM-31 / DFM-32 的共享标注指标未被破坏。
- 演示场景是 Pressure Port 模型，不是钣金件；M6A 结果在共享标注中按
  `unscored_items` 处理，上表 M6A 计数属于**场景外噪声**，不能作为精度结论。
- 非钣金件上的圆柱面也会被归类为孔/凸台。数据契约补充钣金专有字段后，应以
  真实钣金件重新校准。

### 2.3 性能（`docs/PERF.md`）

同一台机器，CLI 含 Python 启动与 findings JSON 写出，每规模重复 5 次；
单进程内 `pipeline.run` 重复 20 次：

| 模型 | 面数 | CLI 墙钟（min/median/max） | 检查逻辑（min/median/max） |
|---|---:|---|---|
| `bent_sheet` | 8 | 133 / 136 / 138 ms | 1 / 1 / 1 ms |
| `board_a` | 20 | 134 / 135 / 139 ms | 1 / 1 / 1 ms |
| `demo_asm` | 78 | 142 / 144 / 153 ms | 6 / 7 / 8 ms |
| `demo_large` | 312 | 173 / 178 / 181 ms | 28 / 28 / 30 ms |

- `python -c pass` 启动基线：23 / 24 / 24 ms。
- 合同要求：单次完整检查 ≤ 30 分钟、报告输出 ≤ 1 分钟。当前 8 项检查即使含
  启动也只有 **0.13–0.18 s**，余量极大。
- 解析（NX 起进程）本机无法实测：没有 NX 与真实 `.prt`。可复用
  `docs/PERF.md` 的基线（固定 31 s + 5.6 ms/面），但需真实模型最终确认。

---

## 3. 实测基线（6 个模型 × 8 项）

`ok:N` = 产出 N 条 Finding；`skip` = 模型无对应特征；`missing` = 模型缺
`axes` / `cylindrical_faces` / `face_radius` 等能力，管线判为 `missing_data`。

| 模型 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 |
|---|---|---|---|---|---|---|---|---|
| `plate_holes` | skip | ok:0 | ok:0 | **ok:4** | skip | skip | skip | skip |
| `deep_slot` | missing | missing | missing | missing | **ok:1** | missing | missing | missing |
| `bosses` | skip | skip | skip | skip | skip | skip | skip | **ok:1** |
| `thin_wall` | missing | missing | missing | missing | ok:0 | missing | missing | missing |
| `board_a` | skip | **ok:1** | ok:0 | **ok:1** | skip | skip | skip | skip |
| `bent_sheet`（合成） | **ok:1** | **ok:1** | **ok:1** | **ok:3** | skip | **ok:1** | **ok:1** | skip |

---

## 4. 测试与仓库卫生

| 检查 | 结果 |
|---|---|
| `python -m nxdrp checkers` | 11 个 checker（3 内置示例 + 8 M6A），0 加载错误 |
| `python -m nxdrp selftest` | 通过 |
| `python -m unittest discover -s tests -p "test_m6a_*.py"` | 30 个通过 |
| `python -m unittest discover -s tests` | 104 个通过（1 skipped） |
| 共享规则库 | R-DFM-19~26 与 checker `default_params` 一致（由测试保证） |

---

## 5. 已知限制

1. 料厚是规则值、`2V/A` 或包围盒估计，不是真实板厚；置信度 0.2–0.4。
2. 折弯只识别圆柱面，弯曲线用轴线代替真实切线；翻边高度包含弯区。
3. 孔只支持圆孔；槽只支持直槽 + 平面槽底；异形孔/槽会漏检。
4. 孔到边缘距离用零件包围盒代替真实板边，异形板件有偏差。
5. DFM-24 / DFM-26 为二期占位实现，仅供流程验证。
6. 非钣金演示场景上的 M6A 结果是场景外噪声，未计分。
7. 没有真实 NX 钣金 `.prt`，精度未验证；本轮只验证流程。

---

## 6. 复现命令

```bash
# 发现与自检
python -m nxdrp checkers
python -m nxdrp selftest

# 测试
python -m unittest discover -s tests -p "test_m6a_*.py" -v
python -m unittest discover -s tests -v

# 单模型评测（以 bent_sheet 为例；输出放 .cache，避免污染仓库根目录）
mkdir -p .cache/m6a_validation
python -m nxdrp check tests/fixtures/bent_sheet.model.json \
  -r rules/dfm_default.json \
  --only DFM-19,DFM-20,DFM-21,DFM-22,DFM-23,DFM-24,DFM-25,DFM-26 \
  -o .cache/m6a_validation/bent_sheet.findings.json
python -m nxdrp eval .cache/m6a_validation/bent_sheet.findings.json \
  -l mockdata/labels/m6a/bent_sheet.labels.json \
  --no-high-risk -o .cache/m6a_validation/bent_sheet.eval.json

# 其余标注模型：plate_holes / deep_slot / bosses / board_a
# 将模型路径与标注文件名替换即可。

# 共享目录检查
git status --porcelain
```

---

## 7. 下一步

1. 拿到真实 NX 钣金 `.prt` 后，用内置 M6A 子包直接验证。
2. 数据契约补充料厚、弯曲线、翻边、凸台、槽等字段后，替换对应粗筛逻辑。
3. 验收精度达标后再更新本文档的基线数据。
