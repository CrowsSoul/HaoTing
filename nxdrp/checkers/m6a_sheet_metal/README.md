# M6A 钣金类 DFM（8 项）

**负责人**：于大淇　　**目录**：`nxdrp/checkers/m6a_sheet_metal/`

DFM-19 ~ DFM-26 已实现。数据契约没有料厚、弯曲线、翻边、凸台、槽等钣金专有字段，
当前实现为**低置信度几何粗筛**：所有 Finding 带 `【粗筛】`、`coarse: true`、
`confidence ≤ 0.6`，必须人工复核。完整验证记录见 `docs/M6A_WORK_STATUS.md`。

## 检查项

| ID | 名称 | 测量 | 阈值 |
|---|---|---|---|
| `DFM-19` | 最小弯曲半径 | 折弯圆柱半径 `R`，`R/t` | `min_bend_radius_ratio × t` |
| `DFM-20` | 孔到边缘距离 | 孔中心到零件 bbox 的板面内最小边距 − 孔半径 | `min_edge_distance_ratio × t` |
| `DFM-21` | 孔间距 | 平行孔组中心距 − 两孔半径 | `min_hole_spacing_ratio × t` |
| `DFM-22` | 孔径与料厚比 | 孔组最小孔径 `2×r_min` | `min_hole_diameter_ratio × t` |
| `DFM-23` | 槽的最小宽度 | 对置内部平面壁间距（需共同槽底） | `min_slot_width_ratio × t` |
| `DFM-24` | 折弯与切口距离 | 孔轴线到折弯轴线公垂线距离 − 孔半径 | `bend_clearance_ratio × t + R` |
| `DFM-25` | 翻边高度 | 折弯腿面沿 `axis×normal` 的包围盒跨度 | `min_flange_height_ratio × t + R` |
| `DFM-26` | 冲压凸台高度 | 凸台轴向跨度，`h/t` | `[min_boss_height_ratio, max_boss_height_ratio] × t` |

## 规则参数

阈值在 `rules/dfm_default.json`（R-DFM-19 ~ R-DFM-26），代码里只保留
`default_params`。`sheet_thickness_mm: null` 表示允许推断料厚；正数表示显式覆盖。
料厚推断优先级：规则值 → `2×volume/area`（不超过 `1.5×min(bbox)`）→
`min(bbox)`。`bend_radius_override_mm` 为二期占位参数。

## 运行

```bash
# 发现（应为 11 个 checker：3 内置示例 + 8 M6A）
python -m nxdrp checkers

# 合成夹具跑 8 项
python -m nxdrp check tests/fixtures/bent_sheet.model.json \
  -r rules/dfm_default.json \
  --only DFM-19,DFM-20,DFM-21,DFM-22,DFM-23,DFM-24,DFM-25,DFM-26

# 单项示例
python -m nxdrp check mockdata/models/plate_holes.model.json \
  -r rules/dfm_default.json --only DFM-22

# M6A 测试
python -m unittest discover -s tests -p "test_m6a_*.py" -v
```

## 已知限制

- 料厚是规则值、平均体积/面积或包围盒估计，不是真实板厚。
- 折弯只识别圆柱面，弯曲线用轴线代替真实切线；翻边高度包含弯区。
- 孔只支持圆孔；槽只支持直槽 + 平面槽底；异形孔/槽会漏检。
- 孔到边缘距离用零件包围盒代替真实板边，异形板件有偏差。
- DFM-24 / DFM-26 为二期占位实现；真实 NX 钣金 `.prt` 到位后需重新验证精度。
- 非钣金件上的圆柱面也可能被归为孔/凸台，演示场景中的 M6A 结果未计分。
