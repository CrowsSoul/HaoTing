# M6B 机加工 DFM — 工作完成情况

- 负责人：张百瑞（M6）
- 日期：2026-10-23（合并入内置子包；插件期交付 2026-10-22）
- 分支：`develop_zbr`
- 范围：DFM-27 ~ DFM-38（12 项机加工检查）
- 结论：**已按平台 M6A 同款路径合并进内置子包** `nxdrp/checkers/m6b_machining/`，
  独立插件退役。流程级验证通过（发现 → 规则 → 执行 → Finding → 评测），
  全量测试 171 个通过、零加载错误、selftest 通过。**未达到验收精度**，
  本轮目标本身也不是验收精度。

> 手头没有真实 NX 机加工 `.prt`，数据契约也没有孔深、槽深、倒角、型腔等专有字段。
> 所有特征类检查均为低置信度几何粗筛，Finding 带 `【粗筛】`、`coarse: true`、
> `confidence ≤ 0.6`，必须人工复核。

---

## 1. 交付物（合并后布局）

```text
nxdrp/checkers/m6b_machining/
├── __init__.py                   # CHECKERS 导出（10 个）
├── README.md                     # 模块说明（判定表/粗筛声明/命令/自查）
├── _m6b_machining_common.py      # 公共几何工具
├── dfm27_deep_hole.py            # 深孔（逐段深径比，>4 报 / >10 升 P1）
├── dfm28_deep_narrow_slot.py     # 深窄槽（深宽比 > 3）
├── dfm29_flat_bottom_blind_hole.py  # 平底盲孔（锥底豁免）
├── dfm30_tool_accessibility.py   # 刀具可达性（二期占位：跨零件包络遮挡）
├── dfm33_top_fillet.py           # 顶部圆角（顶区锐边 / 顶边小圆角）
├── dfm34_internal_chamfer.py     # 内部倒角（角度/尺寸非标准）
├── dfm35_deep_radius_corner.py   # 深圆角转角（二期粗筛）
├── dfm36_angular_milling.py      # 角度铣削面（非标准平面角）
├── dfm37_narrow_passage.py       # 窄通道（二期粗筛）
└── dfm38_hole_entry_exit.py      # 孔的入刀/出刀面（孔口面斜 > 5°）

rules/
├── dfm_default.json              # v0.3：DFM-27~38 段并入（params/依据/severity）
└── tool_library.json             # 标准刀具库（钻头/立铣刀/倒角/角度系列，含来源）

tools/
├── gen_rules.py                  # PARAM_SKELETON 已同步 DFM-27~38 全部参数键
└── gen_m6b_fixture.py            # 合成夹具生成器

tests/
├── fixtures/machining_syn.model.json   # 合成夹具（39 面手工布线）
├── test_m6b_common.py            # 公共库 25 例
├── test_m6b_checkers.py          # 预期矩阵 + 逐项正/负/边界 30 例
└── test_m6b_cli.py               # 注册/共享规则/刀具库 12 例

mockdata/labels/m6b/              # 5 份标注集（流程验证用）
docs/M6B_WORK_STATUS.md           # 本文档
```

**DFM-31 / DFM-32 由内置参考实现交付**（`nxdrp/checkers/examples/`）。
这两个文件的平台锚定面很广（selftest 期望、共享单测、Pressure Port 回归
`measured ≈ 7.65`），重复注册同 ID 会触发注册表冲突。本包对二者做了
兼容性验证（fixture / board_a / plate_holes / demo_asm 上行为与共享锚点一致）。

---

## 2. 合并对共享区的影响（对照 M6A 集成模板）

| 改动 | 说明 |
|---|---|
| `nxdrp/checkers/m6b_machining/` | 10 个 checker + 公共库迁入，平铺导入改相对导入 |
| `rules/dfm_default.json` | v0.2 → v0.3；DFM-27~38 共 12 条参数/依据并入 |
| `rules/tool_library.json` | 新增（标准刀具库，原插件期文件） |
| `tools/gen_rules.py` | PARAM_SKELETON 同步 DFM-27~38 全部参数键 |
| `tools/gen_m6b_fixture.py` | 新增（夹具生成器，原插件期构建脚本） |
| `tests/test_m6b_*.py` | 3 个测试文件迁入共享测试目录 |
| `tests/fixtures/` | 合成夹具迁入 |
| `tests/test_registry.py` | 外部插件测试改用未占用 ID「DFM-99」（原测试占用了 DFM-33，与本包冲突；测试意图不变） |
| `mockdata/labels/m6b/` | 5 份标注集迁入 |
| `docs/M6B_WORK_STATUS.md` | 本文档（原插件 WORK_STATUS_M6B.md） |
| `m6b_machining_plugin/` | **整个目录退役删除** |

DFM-31/32 的增强点（槽宽比对立铣刀系列、刀具库外置链已在 34/36/37 落地、
阶梯孔分段已在 27 落地）中，仅剩「31 槽宽比对」未启用，记录在 README。

---

## 3. 验证结果

### 3.1 测试与仓库卫生

| 检查 | 结果 |
|---|---|
| `python -m nxdrp checkers`（无 --plugin，纯内置） | 21 个 checker（3 示例 + 8 M6A + 10 M6B），**0 加载错误**，M6 12/12、M6A 8/8 |
| `python -m nxdrp selftest` | 通过 |
| `python -m unittest discover -s tests` | **171 个通过**（1 skipped；含 M6B 67 例） |
| 合成夹具再生成 | `python tools/gen_m6b_fixture.py` 与提交版本一致 |
| 共享规则完整性 | M6B 12 条全部 enabled、注明依据、参数键覆盖 checker 默认值 |

### 3.2 评测链路（`docs/LABELING.md`，内置 + 共享规则）

| 模型 | 标注（正/负） | 预测 | TP | FP | FN | macro-F1 | 误报率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `machining_syn`（合成夹具） | 15 / 14 | 15 | 15 | 0 | 0 | 1.000 | 0.000 |
| `plate_holes` | 6 / 3 | 6 | 6 | 0 | 0 | 1.000 | 0.000 |
| `deep_slot` | 2 / 2 | 2 | 2 | 0 | 0 | 1.000 | 0.000 |
| `bosses` | 0 / 4 | 0 | 0 | 0 | 0 | —（无正样本） | 0.000 |
| `board_a` | 3 / 2 | 3 | 3 | 0 | 0 | 1.000 | 0.000 |

**重要说明**（同 M6A 口径）：标注与预测同源（同一套粗筛几何），满分只能
证明「标注 → 匹配 → 指标」链路跑通，**不能证明验收精度**。

### 3.3 实测基线与性能

8 个共享 Mock/装配模型 × 12 项的状态矩阵、代表性正确判定抽查，与插件期
一致（合并未改变任何判定逻辑，仅改位置与导入）。

性能（`pipeline.run` 重复 20 次，12 项全开）：`board_a` 1.1 ms、
`demo_asm` 7.5 ms、`demo_large`（312 面）34 ms。合同 ≤ 30 分钟，余量极大。

---

## 4. 插件期发现并已修复的问题

1. **凸台误判为孔**：`_mark_boss` 甄别（小端盖在圆柱背向主体一侧 → is_boss），
   bosses 模型全项零误报。
2. **斜面孔口误分类为孔底**：改「大面规则」（面积 > 4πr² 一律判孔口）。
3. **顶面被误判为倒角**：新增「倒角面必须比两个母平面窄」约束。
4. **阶梯孔深径比虚高**：DFM-27 改逐段计算取最恶劣段。
5. **DFM-31/32 重复注册**：插件期改为复用内置参考实现；合并后保持该分工。
6. **共享测试 ID 冲突**：`test_registry.py` 外部插件测试 ID DFM-33 → DFM-99。

---

## 5. 已知限制（粗筛边界）

1. 孔深/槽深用包围盒跨度近似，盲孔钻尖段计入孔深，结果偏保守。
2. 凸台/销钉与孔的甄别为启发式，异形凸台（多台阶、非圆截面）可能误判。
3. 槽只支持直槽 + 平面槽底；斜槽、异形槽漏检。
4. DFM-30/35/37 为二期粗筛/占位：未做包络扫掠求交、未评估腔深、未做空间遮挡。
5. DFM-33 的「顶」按建模 +Z（规则参数 `up_direction` 可改）。
6. DFM-34 倒角尺寸取倒角面最小包围盒尺寸（≈ 腿宽），斜倒角有偏差。
7. DFM-36 以最大平面为基准面，多基准箱体类零件可能选错基准。
8. 孔口在曲面上（无法向）时 DFM-38 不判定。
9. 没有真实 NX 机加工 `.prt`，精度未在真实件上验证。

---

## 6. 复现命令

```bash
# 纯内置（无需 --plugin）
python -m nxdrp checkers          # 21 个 checker，0 加载错误，M6 12/12
python -m nxdrp selftest
python -m unittest discover -s tests

# 评测（以合成夹具为例；输出放 .cache）
mkdir -p .cache/m6b_validation
python -m nxdrp check tests/fixtures/machining_syn.model.json -r rules/dfm_default.json \
  --only DFM-27,DFM-28,DFM-29,DFM-30,DFM-31,DFM-32,DFM-33,DFM-34,DFM-35,DFM-36,DFM-37,DFM-38 \
  -o .cache/m6b_validation/machining_syn.findings.json
python -m nxdrp eval .cache/m6b_validation/machining_syn.findings.json \
  -l mockdata/labels/m6b/machining_syn.labels.json --no-high-risk
# 其余模型：plate_holes / deep_slot / bosses / board_a（路径换 mockdata/models/）

# 夹具再生成
python tools/gen_m6b_fixture.py
```

---

## 7. 下一步

1. 拿到真实 NX 机加工 `.prt` 后直接用内置包验证；重点校准凸台甄别、
   槽识别与 DFM-33 的顶区启发。
2. DFM-31 槽宽比对立铣刀系列：待 examples 退役或平台确认后启用
   （逻辑已在插件期验证，代码在合并提交的历史中可查）。
3. 数据契约补充孔深、槽深、倒角、型腔字段后，替换粗筛逻辑并解除置信度上限。
4. DFM-30/35/37 二期：刀具包络扫掠 + 实体求交、腔深评估、空间遮挡分析。
