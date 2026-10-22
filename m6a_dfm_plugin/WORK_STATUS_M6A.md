# M6A 钣金 DFM 插件 — 工作完成情况

- 负责人：于大淇（M6A）
- 日期：2026-10-22
- 范围：DFM-19 ~ DFM-26（8 项钣金检查）
- 结论：**流程级验证通过**（插件发现 → 加载规则 → 执行检查 → 产出 Finding → 评测 → 报告），
  共享目录零改动。**未达到验收精度**，本轮目标本身也不是验收精度。

> 手头没有真实 NX 钣金 `.prt`，数据契约也没有料厚、弯曲线、翻边、凸台、槽等专有字段。
> 所有检查均为低置信度几何粗筛，Finding 带 `【粗筛】`、`coarse: true`、
> `confidence ≤ 0.6`，必须人工复核。

---

## 1. 交付物

```text
m6a_dfm_plugin/
├── _m6a_dfm_common.py          # 公共几何工具：料厚推断、圆柱分类、孔组、槽识别
├── dfm19_bend_radius.py        # 最小弯曲半径
├── dfm20_hole_edge.py          # 孔到边缘距离
├── dfm21_hole_spacing.py       # 孔间距
├── dfm22_hole_thickness.py     # 孔径与料厚比
├── dfm23_slot_width.py         # 槽的最小宽度
├── dfm24_bend_cutout.py        # 折弯与切口距离（二期占位）
├── dfm25_flange_height.py      # 翻边高度
├── dfm26_boss_height.py        # 冲压凸台高度（二期占位）
├── rules_m6a.json              # 插件专用 RuleBook（8 条）
├── README_M6A.md               # 用法、规则、限制、基线
├── WORK_STATUS_M6A.md          # 本文档
├── validation/
│   └── labels/                 # 5 份插件本地标注集（仅用于流程验证）
│       ├── bent_sheet.labels.json
│       ├── plate_holes.labels.json
│       ├── deep_slot.labels.json
│       ├── bosses.labels.json
│       └── board_a.labels.json
└── __tests__/                  # 双下划线目录，registry 整目录跳过
    ├── test_common.py
    ├── test_checkers.py
    ├── test_plugin_cli.py
    └── fixtures/bent_sheet.model.json
```

共享文件（`nxdrp/`、`rules/dfm_default.json`、`mockdata/`、`tests/`、`tools/`）零 diff。

---

## 2. 验证结果（按 `docs/` 的三个验证环节）

### 2.1 评测链路（`docs/LABELING.md`）

按标注规范新增 5 份插件本地标注集（正样本 + 负样本），执行
`nxdrp check` → `nxdrp eval`：

| 模型 | 标注（正/负） | 预测 | TP | FP | FN | macro-F1 | 误报率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `bent_sheet`（合成夹具） | 8 / 5 | 8 | 8 | 0 | 0 | 1.000 | 0.000 |
| `plate_holes` | 4 / 0 | 4 | 4 | 0 | 0 | 1.000 | 0.000 |
| `deep_slot` | 1 / 0 | 1 | 1 | 0 | 0 | 1.000 | 0.000 |
| `bosses` | 1 / 1 | 1 | 1 | 0 | 0 | 1.000 | 0.000 |
| `board_a` | 2 / 1 | 2 | 2 | 0 | 0 | 1.000 | 0.000 |

**重要说明**：这些标注是按夹具/Mock 的设计意图和几何尺寸人工整理的，位置与
face_id 与同一套粗筛几何同源。满分只能证明「标注 → 匹配 → 指标」链路跑通，
**不能证明验收精度**；`plate_holes` / `deep_slot` 只有正样本，负样本覆盖有限。

### 2.2 场景验证（`docs/DEMO_SCENE.md`）

在三个共享演示场景上同时加载内置 checker 与 M6A 插件，使用共享规则库和共享标注：

| 场景 | 总 Finding | 其中 M6A | checker 状态 | macro-F1 | P / R | 误报率 |
|---|---:|---:|---|---:|---:|---:|
| `demo_asm` | 35 | 24（20:6，22:6，26:12） | ok 7 / skipped 4 | 1.000 | 1.000 / 1.000 | 0.000 |
| `demo_normal` | 25 | 20（20:5，22:5，26:10） | ok 7 / skipped 4 | —（无正样本） | 0.000 / 0.000 | 0.000 |
| `demo_edge` | 22 | 16（20:4，22:4，26:8） | ok 7 / skipped 4 | 1.000 | 1.000 / 1.000 | 0.000 |
| `demo_large` | 120 | 96（20:24，22:24，26:48） | ok 7 / skipped 4 | 未标注 | — | — |

- 现有 DFM-02 / DFM-31 / DFM-32 的共享标注指标**未被插件破坏**（上表与无插件时一致）。
- 演示场景是 Pressure Port 模型，不是钣金件，M6A 结果在共享标注中按
  `unscored_items` 处理；上表 M6A 计数属于**场景外噪声**，不能作为精度结论。
- 这暴露了粗筛的边界：非钣金件上的圆柱面也会被归类为孔/凸台。数据契约补充钣金
  专有字段后，应以真实钣金件重新校准。

### 2.3 性能（`docs/PERF.md`）

同一台机器，CLI 含 Python 启动与 findings JSON 写出，每规模重复 5 次；
单进程内 `pipeline.run` 重复 20 次：

| 模型 | 面数 | CLI 墙钟（min/median/max） | 检查逻辑（min/median/max） |
|---|---:|---|---|
| `bent_sheet` | 8 | 118 / 119 / 121 ms | 1 / 1 / 1 ms |
| `board_a` | 20 | 113 / 118 / 123 ms | 1 / 1 / 1 ms |
| `demo_asm` | 78 | 125 / 128 / 138 ms | 6 / 7 / 8 ms |
| `demo_large` | 312 | 156 / 159 / 165 ms | 27 / 28 / 29 ms |

- `python -c pass` 启动基线：28 / 29 / 30 ms。
- 合同要求：单次完整检查 ≤ 30 分钟、报告输出 ≤ 1 分钟。当前 8 项检查即使含
  启动也只有 **0.12–0.17 s**，余量极大。
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
| `python -m nxdrp checkers --plugin m6a_dfm_plugin` | 11 个 checker（3 内置 + 8 M6A），0 加载错误 |
| `python -m nxdrp selftest --plugin m6a_dfm_plugin` | 通过 |
| `python -m unittest discover -s m6a_dfm_plugin/__tests__ -p "test_*.py"` | 30 个通过 |
| `python -m unittest discover -s tests` | 74 个通过（1 skipped） |
| `git diff --name-only -- nxdrp rules mockdata tests tools` | 空 |
| `git status --porcelain` | 仅 `m6a_dfm_plugin/` |

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
# 插件发现（应为 11 个 checker，0 加载错误）
python -m nxdrp checkers --plugin m6a_dfm_plugin

# 自检
python -m nxdrp selftest --plugin m6a_dfm_plugin

# 测试
python -m unittest discover -s m6a_dfm_plugin/__tests__ -p "test_*.py" -v
python -m unittest discover -s tests -v

# 单模型评测（以 bent_sheet 为例；输出放 .cache，避免污染仓库根目录）
mkdir -p .cache/m6a_validation
python -m nxdrp check m6a_dfm_plugin/__tests__/fixtures/bent_sheet.model.json \
  --plugin m6a_dfm_plugin -r m6a_dfm_plugin/rules_m6a.json \
  --only DFM-19,DFM-20,DFM-21,DFM-22,DFM-23,DFM-24,DFM-25,DFM-26 \
  -o .cache/m6a_validation/bent_sheet.findings.json
python -m nxdrp eval .cache/m6a_validation/bent_sheet.findings.json \
  -l m6a_dfm_plugin/validation/labels/bent_sheet.labels.json \
  --no-high-risk -o .cache/m6a_validation/bent_sheet.eval.json

# 其余标注模型：plate_holes / deep_slot / bosses / board_a
# 将上面的模型路径与标注文件名替换即可。

# 共享目录零 diff
git diff --name-only -- nxdrp rules mockdata tests tools
```

---

## 7. 下一步

1. 拿到真实 NX 钣金 `.prt` 后，用同一插件直接验证；不为真实件修改框架。
2. 数据契约补充料厚、弯曲线、翻边、凸台、槽等字段后，替换对应粗筛逻辑。
3. 验收精度达标后，由平台方将 checker 合并进 `nxdrp/checkers/m6a_sheet_metal/`
   （平铺导入改相对导入），并把 `rules_m6a.json` 参数并入共享规则库。
