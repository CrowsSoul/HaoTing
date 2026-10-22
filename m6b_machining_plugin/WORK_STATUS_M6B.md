# M6B 机加工 DFM 插件 — 工作完成情况

- 负责人：张百瑞（M6）
- 日期：2026-10-22
- 分支：`develop_zbr`
- 范围：DFM-27 ~ DFM-38（12 项机加工检查）
- 结论：**流程级验证通过**（插件发现 → 加载规则 → 执行检查 → 产出 Finding → 评测），
  共享目录零改动、零加载错误、selftest 通过。**未达到验收精度**，
  本轮目标本身也不是验收精度。

> 手头没有真实 NX 机加工 `.prt`，数据契约也没有孔深、槽深、倒角、型腔等专有字段。
> 所有特征类检查均为低置信度几何粗筛，Finding 带 `【粗筛】`、`coarse: true`、
> `confidence ≤ 0.6`，必须人工复核。

---

## 1. 交付物

```text
m6b_machining_plugin/
├── _m6b_machining_common.py      # 公共几何工具（约 600 行）
├── dfm27_deep_hole.py            # 深孔（逐段深径比，>4 报 / >10 升 P1）
├── dfm28_deep_narrow_slot.py     # 深窄槽（深宽比 > 3）
├── dfm29_flat_bottom_blind_hole.py  # 平底盲孔（锥底豁免）
├── dfm30_tool_accessibility.py   # 刀具可达性（二期占位：跨零件包络遮挡）
├── dfm33_top_fillet.py           # 顶部圆角（顶区锐边 / 顶边小圆角）
├── dfm34_internal_chamfer.py     # 内部倒角（角度/尺寸非标准）
├── dfm35_deep_radius_corner.py   # 深圆角转角（二期粗筛）
├── dfm36_angular_milling.py      # 角度铣削面（非标准平面角）
├── dfm37_narrow_passage.py       # 窄通道（二期粗筛）
├── dfm38_hole_entry_exit.py      # 孔的入刀/出刀面（孔口面斜 > 5°）
├── rules_m6b.json                # 12 条规则（每条注明阈值依据）
├── tool_library.json             # 标准刀具库（钻头/立铣刀/倒角/角度系列，含来源）
├── README_M6B.md                 # 用法、限制、命令
├── WORK_STATUS_M6B.md            # 本文档
├── validation/labels/            # 5 份标注集
│   ├── machining_syn.labels.json     # 15 正 / 14 负
│   ├── plate_holes.labels.json       # 6 正 / 3 负
│   ├── deep_slot.labels.json         # 2 正 / 2 负
│   ├── bosses.labels.json            # 0 正 / 4 负（纯负样本：凸台不应误报为孔）
│   └── board_a.labels.json           # 3 正 / 2 负
└── __tests__/                    # 65 个单测
    ├── build_fixtures.py         # 合成夹具生成器（39 面 / 41 邻接对，手工布线）
    ├── fixtures/machining_syn.model.json
    ├── test_common.py            # 公共库 25 例
    ├── test_checkers.py          # 预期矩阵 + 逐项正/负/边界 30 例
    └── test_plugin_cli.py        # 注册/规则/刀具库 10 例
```

**DFM-31 / DFM-32 由内置参考实现交付**（`nxdrp/checkers/examples/`）。
这两个文件的平台锚定面很广（selftest 期望、74 个共享单测、Pressure Port
回归 `measured ≈ 7.65`），插件若重复导出同 ID 会触发注册表冲突并使
`selftest --plugin` 失败。本插件原样复用，并对二者做了兼容性验证
（fixture / board_a / plate_holes / demo_asm 上行为与共享锚点一致）。

共享文件（`nxdrp/`、`rules/`、`mockdata/`、`tests/`、`tools/`）**零 diff**。

---

## 2. 验证结果

### 2.1 评测链路（`docs/LABELING.md`）

| 模型 | 标注（正/负） | 预测 | TP | FP | FN | macro-F1 | 误报率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `machining_syn`（合成夹具） | 15 / 14 | 15 | 15 | 0 | 0 | 1.000 | 0.000 |
| `plate_holes` | 6 / 3 | 6 | 6 | 0 | 0 | 1.000 | 0.000 |
| `deep_slot` | 2 / 2 | 2 | 2 | 0 | 0 | 1.000 | 0.000 |
| `bosses` | 0 / 4 | 0 | 0 | 0 | 0 | —（无正样本） | 0.000 |
| `board_a` | 3 / 2 | 3 | 3 | 0 | 0 | 1.000 | 0.000 |

**重要说明**（与 M6A 相同口径）：标注与预测同源（同一套粗筛几何），满分只能
证明「标注 → 匹配 → 指标」链路跑通，**不能证明验收精度**；`bosses` 是纯负
样本场景，验证的是「凸台不被误报为孔」。

### 2.2 实测基线（8 个共享模型 × 12 项）

`ok:N` = 产出 N 条；`skip` = 模型无对应特征；`miss` = 缺数据能力（missing_data）。

| 模型 | 27 | 28 | 29 | 30 | 31 | 32 | 33 | 34 | 35 | 36 | 37 | 38 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| plate_holes | ok:1 | skip | ok:0 | miss | ok:4 | miss | ok:1 | skip | skip | ok:0 | skip | ok:0 |
| deep_slot | miss | ok:1 | miss | miss | miss | miss | ok:1 | skip | miss | ok:0 | ok:0 | miss |
| bosses | skip | skip | skip | miss | ok:0 | miss | ok:0 | skip | skip | ok:0 | skip | skip |
| thin_wall | miss | ok:0 | miss | miss | miss | miss | ok:1 | skip | miss | ok:0 | ok:0 | miss |
| board_a | ok:0 | skip | skip | ok:0 | ok:2 | ok:1 | ok:0 | skip | ok:0 | ok:0 | skip | skip |
| minimal | ok:0 | miss | miss | miss | ok:0 | miss | ok:0 | miss | miss | ok:0 | miss | miss |
| asm_test | ok:2 | skip | ok:0 | ok:0 | ok:2 | ok:0 | ok:0 | skip | ok:0 | ok:0 | skip | ok:0 |
| demo_asm | ok:6 | skip | ok:0 | ok:3 | ok:6 | ok:0 | ok:0 | skip | ok:0 | ok:0 | skip | ok:0 |

抽查确认的代表性正确判定：

- `plate_holes` DFM-27 只报 Ø2.2 深孔（4.55 > 4），Ø3.7 的 2.7 不误报；DFM-31 四个非标孔 Ø3.7/6.25/5.2/2.2 全中。
- `bosses` 两个凸台在全部钻孔类检查中零误报（凸台甄别生效）。
- `asm_test` 阶梯盲孔锥底 → DFM-29 零误报；Ø4.46 距 Ø4.5 仅 0.04 → DFM-31 不误报。
- 共享锚点未被破坏：`board_a` DFM-31:2 / DFM-32:1，`demo_asm` DFM-31:6，
  与无插件时内置参考实现的数值完全一致。

### 2.3 性能（`docs/PERF.md`）

单进程内 `pipeline.run` 重复 20 次（12 项检查全开）：

| 模型 | 面数 | 检查逻辑（min/median/max） |
|---|---:|---|
| `board_a` | 20 | 1.1 / 1.1 / 1.6 ms |
| `demo_asm` | 78 | 7.3 / 7.5 / 7.8 ms |
| `demo_large` | 312 | 33.8 / 34.3 / 35.1 ms |

合同要求单次完整检查 ≤ 30 分钟，当前 12 项合计 < 0.05 s，余量极大。

### 2.4 测试与仓库卫生

| 检查 | 结果 |
|---|---|
| `python -m nxdrp checkers --plugin m6b_machining_plugin` | 13 个 checker（3 内置 + 10 M6B），**0 加载错误**，M6 覆盖率 12/12 |
| `python -m nxdrp selftest --plugin m6b_machining_plugin` | 通过 |
| `python -m unittest discover -s m6b_machining_plugin/__tests__ -p "test_*.py"` | 65 个通过 |
| `python -m unittest discover -s tests` | 74 个通过（1 skipped） |
| `git diff --name-only -- nxdrp rules mockdata tests tools` | 空 |
| `git status --porcelain` | 仅 `m6b_machining_plugin/` |

每个 checker 均有正例 / 负例 / 边界三组测试（协作规则第 3 条）；
DFM-31 另有「改表即改判定」测试：规则参数改 `standard_diameters` 后
Ø5.3 立即转为合格（`Dfm31OverrideTests`）。

---

## 3. 开发中发现并修复的问题

1. **凸台误判为孔**（bosses 模型 DFM-29 曾报 3 条）：新增 `_mark_boss`
   甄别——端盖面积 ≈ πr² 且位于圆柱背向零件主体一侧 → 标记 `is_boss`，
   全部钻孔类检查跳过。
2. **斜面孔口被误分类为孔底**：内部性测试对斜面失效（斜面重心总在包围盒
   内部）。改为「大面规则」：面积 > 4πr² 的端面一律判孔口，与朝向无关。
3. **顶面被误判为倒角**：顶面夹在两个镜像 45° 倒角之间时恰好满足法向条件。
   新增约束——倒角面必须比两个母平面都窄。
4. **阶梯孔深径比虚高**：asm_test 沉孔按总深/最小径会高估。DFM-27 改为
   逐段计算取最恶劣段。
5. **DFM-31/32 插件重复注册**导致 selftest 失败：插件改为复用内置参考实现，
   增强版本留待平台合并（见下）。

---

## 4. 已知限制

见 `README_M6B.md` 第五节（粗筛边界 9 条）。重点是：没有真实 NX 机加工
`.prt`，精度未验证；DFM-30/35/37 为二期粗筛/占位。

---

## 5. 复现命令

```bash
# 插件发现（13 个 checker，0 加载错误，M6 12/12）
python -m nxdrp checkers --plugin m6b_machining_plugin

# 自检与测试
python -m nxdrp selftest --plugin m6b_machining_plugin
python -m unittest discover -s m6b_machining_plugin/__tests__ -p "test_*.py"
python -m unittest discover -s tests

# 评测（5 个标注模型；输出放 .cache，避免污染仓库根目录）
mkdir -p .cache/m6b_validation
python -m nxdrp check m6b_machining_plugin/__tests__/fixtures/machining_syn.model.json \
  --plugin m6b_machining_plugin -r m6b_machining_plugin/rules_m6b.json \
  --only DFM-27,DFM-28,DFM-29,DFM-30,DFM-31,DFM-32,DFM-33,DFM-34,DFM-35,DFM-36,DFM-37,DFM-38 \
  -o .cache/m6b_validation/machining_syn.findings.json
python -m nxdrp eval .cache/m6b_validation/machining_syn.findings.json \
  -l m6b_machining_plugin/validation/labels/machining_syn.labels.json --no-high-risk
# 其余模型：plate_holes / deep_slot / bosses / board_a（路径换 mockdata/models/）

# 共享目录零 diff
git diff --name-only -- nxdrp rules mockdata tests tools
```

---

## 6. 下一步

1. 拿到真实 NX 机加工 `.prt` 后，用同一插件直接验证；重点校准凸台甄别、
   槽识别与 DFM-33 的顶区启发。
2. 平台合并时：10 个插件 checker 并入 `nxdrp/checkers/m6b_machining/`
   （平铺导入改相对导入），`rules_m6b.json` 参数并入共享规则库；
   DFM-31/32 的增强点（槽宽比对立铣刀系列、阶梯孔分段已在 27 落地、
   刀具库 `tool_library.json` 外置链）随 `_m6b_machining_common.py`
   一并启用并替换内置参考实现。
3. 数据契约补充孔深、槽深、倒角、型腔字段后，替换对应粗筛逻辑，
   置信度上限同步解除。
4. DFM-30/35/37 二期：刀具包络扫掠 + 实体求交、腔深评估、空间遮挡分析。
