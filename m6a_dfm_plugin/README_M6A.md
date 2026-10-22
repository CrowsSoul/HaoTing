# M6A 钣金 DFM 插件（DFM-19 ~ DFM-26）

本目录是于大淇（M6A）负责的钣金检查项的**独立插件**，不修改 `nxdrp/`、
`rules/dfm_default.json`、`mockdata/`、`tests/`、`tools/` 中的任何文件。

当前目标：打通「插件发现 → 加载规则 → 执行 8 个 checker → 产出 Finding」的端到端流程，
**不追求验收精度**。数据契约没有料厚、弯曲线、翻边、凸台、槽等钣金专有字段，因此全部
采用低置信度几何粗筛；每条 Finding 都带 `【粗筛】` 前缀、`coarse: true`、料厚来源，
`confidence ≤ 0.6`，必须人工复核。

## 文件结构

```text
m6a_dfm_plugin/
├── _m6a_dfm_common.py          # 公共几何工具（下划线前缀，不会被注册为 checker）
├── dfm19_bend_radius.py        # 最小弯曲半径
├── dfm20_hole_edge.py          # 孔到边缘距离
├── dfm21_hole_spacing.py       # 孔间距
├── dfm22_hole_thickness.py     # 孔径与料厚比
├── dfm23_slot_width.py         # 槽的最小宽度
├── dfm24_bend_cutout.py        # 折弯与切口距离（二期占位）
├── dfm25_flange_height.py      # 翻边高度
├── dfm26_boss_height.py        # 冲压凸台高度（二期占位）
├── rules_m6a.json              # 插件专用 RuleBook（8 条）
├── README_M6A.md
├── WORK_STATUS_M6A.md          # 工作完成情况与流程级验证记录
├── validation/labels/          # 5 份插件本地标注集（仅用于流程验证）
└── __tests__/                  # 双下划线目录，registry 会整目录跳过
    ├── test_common.py
    ├── test_checkers.py
    ├── test_plugin_cli.py
    └── fixtures/bent_sheet.model.json   # 仅用于跑通折弯类流程的合成夹具
```

## 快速运行

```bash
# 1) 发现插件：应为 11 个 checker（3 个内置 + 8 个 M6A），0 加载错误
python -m nxdrp checkers --plugin m6a_dfm_plugin

# 2) 合成夹具跑全量 8 项（预期 8 条 finding）
python -m nxdrp check m6a_dfm_plugin/__tests__/fixtures/bent_sheet.model.json \
  --plugin m6a_dfm_plugin -r m6a_dfm_plugin/rules_m6a.json \
  --only DFM-19,DFM-20,DFM-21,DFM-22,DFM-23,DFM-24,DFM-25,DFM-26 \
  -o findings_m6a_bent.json

# 3) 现有 Mock 的单项验证
python -m nxdrp check mockdata/models/plate_holes.model.json \
  --plugin m6a_dfm_plugin -r m6a_dfm_plugin/rules_m6a.json --only DFM-22
python -m nxdrp check mockdata/models/deep_slot.model.json \
  --plugin m6a_dfm_plugin -r m6a_dfm_plugin/rules_m6a.json --only DFM-23
python -m nxdrp check mockdata/models/bosses.model.json \
  --plugin m6a_dfm_plugin -r m6a_dfm_plugin/rules_m6a.json --only DFM-26

# 4) 自检（使用共享规则库）
python -m nxdrp selftest --plugin m6a_dfm_plugin

# 5) 测试
python -m unittest discover -s m6a_dfm_plugin/__tests__ -p "test_*.py" -v
python -m unittest discover -s tests -v
```

**必须用 `m6a_dfm_plugin/rules_m6a.json`**：共享规则库给 DFM-19 固定了
`sheet_thickness_mm: 1.0`，会绕过料厚推断。

也可以用环境变量加载（不要同时用 `--plugin`，也不要指向仓库根目录）：

```bash
NXDRP_PLUGIN_PATH="D:/Code/Project/HaoTing/harting_drp/m6a_dfm_plugin" python -m nxdrp checkers
```

## 规则参数

| ID | 检查项 | params |
|---|---|---|
| DFM-19 | 最小弯曲半径 | `min_bend_radius_ratio: 0.5`, `sheet_thickness_mm: null` |
| DFM-20 | 孔到边缘距离 | `min_edge_distance_ratio: 1.5`, `sheet_thickness_mm: null` |
| DFM-21 | 孔间距 | `min_hole_spacing_ratio: 2.0`, `sheet_thickness_mm: null` |
| DFM-22 | 孔径与料厚比 | `min_hole_diameter_ratio: 1.0`, `sheet_thickness_mm: null` |
| DFM-23 | 槽的最小宽度 | `min_slot_width_ratio: 1.2`, `sheet_thickness_mm: null` |
| DFM-24 | 折弯与切口距离 | `bend_clearance_ratio: 3.0`, `bend_radius_override_mm: null`, `sheet_thickness_mm: null` |
| DFM-25 | 翻边高度 | `min_flange_height_ratio: 3.0`, `bend_radius_override_mm: null`, `sheet_thickness_mm: null` |
| DFM-26 | 冲压凸台高度 | `min_boss_height_ratio: 0.6`, `max_boss_height_ratio: 1.5`, `sheet_thickness_mm: null` |

`sheet_thickness_mm: null` 表示允许推断料厚；正数表示该检查项显式使用这个值。
`bend_radius_override_mm` 为二期占位参数，`null` 时使用实际圆柱半径。

## 判定摘要

料厚 t 的优先级：

1. 规则参数 `sheet_thickness_mm`（置信度 0.9）；
2. `2*volume/area`，且不超过 `1.5*min(bbox.size)`（置信度 0.4）；
3. `min(bbox.size)`（置信度 0.2）；
4. 都没有则跳过该零件。

圆柱面分类（优先级从高到低）：

- **凸台**：存在与轴平行、面积不超过 `1.5*πr²` 的相邻平面端盖；高度取圆柱面包围盒沿轴向跨度。
- **折弯**：至少两个互不平行、且法向与轴垂直（`|dot| ≤ 0.2`）的相邻平面；弯曲线取圆柱轴线。
- **孔**：其余圆柱；轴向跨度约等于料厚或与零件轴向跨度同量级时提高置信度。
- 同轴（`|dot| ≥ 0.98`）且径向偏移很小的圆柱合并为孔组，避免沉孔被当成多个孔。

| ID | 测量 | 阈值 |
|---|---|---|
| 19 | 折弯圆柱半径 R，`R/t` | `min_bend_radius_ratio * t` |
| 20 | 孔中心到零件 bbox 在板面两方向的最小边距 − 孔半径 | `min_edge_distance_ratio * t` |
| 21 | 平行孔组中心距 − 两孔半径 | `min_hole_spacing_ratio * t` |
| 22 | 孔组最小孔径 `2*r_min` | `min_hole_diameter_ratio * t` |
| 23 | 对置平面壁间距（需共同内部平面槽底） | `min_slot_width_ratio * t` |
| 24 | 孔轴线到折弯轴线公垂线距离 − 孔半径 | `bend_clearance_ratio * t + R` |
| 25 | 折弯腿面沿 `axis×normal` 方向包围盒跨度 | `min_flange_height_ratio * t + R` |
| 26 | 凸台轴向跨度，`h/t` | `[min_boss_height_ratio, max_boss_height_ratio]` |

## 已知限制

- 料厚是规则值、平均体积/面积或包围盒估计，不是真实板厚。
- 折弯只识别圆柱面，弯曲线用轴线代替真实切线；翻边高度包含弯区。
- 孔只支持圆孔；槽只支持直槽 + 平面槽底；异形孔/槽会漏检。
- 孔到边缘距离用零件包围盒代替真实板边，异形板件有偏差。
- DFM-24 / DFM-26 为二期占位实现，仅供流程验证。
- 现有 Mock 模型不是真实钣金件；真实 NX 钣金 `.prt` 到位后可直接用同一插件验证，
  无需修改框架。

## 实测基线（2026-10-22）

`ok` 后数字为该检查项产出的 finding 数。

| 模型 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 |
|---|---|---|---|---|---|---|---|---|
| `plate_holes` | skip | ok:0 | ok:0 | **ok:4** | skip | skip | skip | skip |
| `deep_slot` | missing | missing | missing | missing | **ok:1** | missing | missing | missing |
| `bosses` | skip | skip | skip | skip | skip | skip | skip | **ok:1** |
| `thin_wall` | missing | missing | missing | missing | ok:0 | missing | missing | missing |
| `board_a` | skip | **ok:1** | ok:0 | **ok:1** | skip | skip | skip | skip |
| `bent_sheet`（合成） | **ok:1** | **ok:1** | **ok:1** | **ok:3** | skip | **ok:1** | **ok:1** | skip |

状态说明：`skip` = 模型里没有对应特征（applies 返回 False）；`missing` = 模型缺
`axes`/`cylindrical_faces`/`face_radius` 等能力，管线判为 `missing_data`。

插件测试 30 个全部通过；共享 `tests/` 74 个测试保持通过。

## 验证记录

按 `docs/LABELING.md` / `docs/DEMO_SCENE.md` / `docs/PERF.md` 的流程级验证见
`WORK_STATUS_M6A.md`。摘要：

- 5 个标注模型（bent_sheet / plate_holes / deep_slot / bosses / board_a）
  macro-F1 均为 1.000，误报率 0.000；
- 共享演示场景加载插件后，DFM-02 / DFM-31 / DFM-32 指标不变，M6A 结果未计分；
- 8 项检查 CLI 墙钟 0.12–0.17 s（8–312 面），远低于合同时间指标。

上述满分来自按夹具/Mock 设计意图整理的本地标注，只能证明「标注 → 匹配 → 指标」
链路跑通，**不代表验收精度**；真实钣金件到位后需重新标注验证。

## 集成说明

本插件用于个人开发与验证。最终集成由平台方决定：可将 checker 文件合并进
`nxdrp/checkers/m6a_sheet_metal/`（平铺导入改为相对导入），并把 `rules_m6a.json`
中的参数合并到共享规则库。集成前请保持本目录独立，避免与其它协作者冲突。
