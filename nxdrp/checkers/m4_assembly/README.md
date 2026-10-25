# M4 装配类 DFM

**负责人**：汪琪竣　　**目录**：`nxdrp/checkers/m4_assembly/`

## 这个模块在解决什么

零件单看都没问题，装到一起就出事：两个件撞在一起（干涉）、孔对不上、扳手伸不进去。这 7 项检查在装配层面找这些毛病。

## 你负责的检查项

| ID | 名称 | 难度 | 期次 | 判定要点 |
|---|---|---|---|---|
| `DFM-01` | 干涉检测 | L3 | 一期 | 两两实体求交，体积>0；需区分硬干涉/临界间隙/碎面虚假干涉 |
| `DFM-02` | 最小间隙 | L1 | 一期 | 零件间最小距离 < 阈值（默认 0.2~0.5mm，可配） |
| `DFM-03` | 孔对齐 | L2 | 一期 | 跨零件孔轴线同轴度偏差 ≤ 允许值，且公称直径匹配 |
| `DFM-04` | 孔/槽对齐 | L2 | 一期 | 槽中线与孔轴线偏差 ≤ 允许值 |
| `DFM-05` | 紧固件可达性 | L3 | 一期 | 沿螺栓轴线扫掠工具包络，不得与周边件碰撞 |
| `DFM-06` | 紧固件间隙 | L2 | 一期 | 螺栓头/垫圈与周边件的轴向、径向间隙 ≥ 阈值 |
| `DFM-07` | 紧固件啮合长度 | L1 | 一期 | 螺纹旋合长度/公称直径 ≥ 1.0（钢）~1.5（铝/塑料） |

## 从哪开始

先做 DFM-02 最小间隙，把多零件遍历跑通；再做 DFM-01 干涉。

## 文件结构

遵循 `docs/HOW_TO_ADD_A_CHECKER.md` 的“一项一个文件”约定：

```text
m4_assembly/
├── _assembly_base.py                 # 装配实例/变换矩阵前置校验
├── _assembly_common.py               # 孔、槽、紧固件语义与几何工具
├── dfm01_interference.py             # DFM-01 干涉
├── dfm02_min_clearance.py            # DFM-02 最小间隙
├── dfm03_hole_alignment.py           # DFM-03 孔对齐
├── dfm04_hole_slot_alignment.py      # DFM-04 孔/槽对齐
├── dfm05_fastener_accessibility.py   # DFM-05 紧固件可达性
├── dfm06_fastener_clearance.py       # DFM-06 紧固件间隙
├── dfm07_engagement_length.py        # DFM-07 啮合长度
├── assembly_dfm.py                   # 旧导入路径兼容入口
└── test_m4.py                        # 正例/负例/边界/场景测试
```

## 三个命令

```powershell
python -m nxdrp checkers                                   # 确认自己被认出来了
python -m nxdrp check mockdata/models/board_a.model.json --only <你的ID>
python -m unittest discover -s tests
```

M4 自测（不依赖 NX）：

```powershell
python -m unittest nxdrp.checkers.m4_assembly.test_m4 -v
```

## 装配语义数据

`ModelBundle` 公共契约没有“配对孔、槽、紧固件”一级字段。M4 不修改公共契约，
而是读取可选的 `model.meta.assembly_features`：

- `holes`：`feature_id/mate_id/part_id/center/axis/diameter_mm/face_ids`
- `slots`：`feature_id/mate_id/part_id/center/axis/width_mm/face_ids`
- `fasteners`：`part_id/face_ids/nominal_diameter_mm/engagement_length_mm/material`，
  以及工具包络和轴向/径向间隙实测值
- `interferences`：NX 实体求交给出的 `part_ids/volume_mm3/face_ids/bbox`

没有这些可靠语义时：DFM-01/02 可输出明确标记的包围盒低置信度粗筛；
DFM-03 可由圆柱面做保守预筛；DFM-04～07 会说明缺失字段并跳过，避免假告警。

## 几个提醒

- 甲方对误报极敏感：报三次假的，他就不信这个平台了。工作量有一半在「过滤掉不该报的」。
- 精确干涉体积必须回 NX 算，包围盒只能做预筛。

## 交之前自查

- [ ] 在 Mock 模型**和**至少一个真实 NX 模型上都跑出正确结果
- [ ] 每条结果带 `face_ids`，工程师能点回 3D 现场
- [ ] 建议能照着改（给目标尺寸或结构动作），不是「请注意检查」
- [ ] 阈值写在 `rules/` 里，代码里只有默认值
- [ ] 数据不够时跳过并说明缺什么，不产出假结果
- [ ] 正例 / 负例 / 边界三个测试都有

写法细节见 `docs/HOW_TO_ADD_A_CHECKER.md`。
