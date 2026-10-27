# M6 机加工类 DFM（12 项）

**负责人**：张百瑞　　**目录**：`nxdrp/checkers/m6b_machining/`

## 这个模块在解决什么

孔太深钻头会断、圆角太小刀具进不去、孔径不在标准刀具系列还得定制刀。
这 12 项把「加工做不出来或者成本高」的地方标出来。

## 检查项与交付位置

| ID | 名称 | 难度 | 期次 | 判定要点 |
|---|---|---|---|---|
| `DFM-27` | 深孔 | L1 | 一期 | 同轴孔组逐段深径比 > 4；> 10 升 P1 |
| `DFM-28` | 深窄槽 | L1 | 一期 | 槽深/槽宽 > 3（对置内壁 + 共同槽底） |
| `DFM-29` | 平底盲孔 | L1 | 一期 | 盲孔底为平面（锥底 = 钻尖，豁免） |
| `DFM-30` | 刀具可达性 | L3 | 二期 | 占位粗筛：孔口包络与其他零件包围盒相交 |
| `DFM-31` | 特征尺寸与刀具标准 | L1 | 一期 | 孔径不在标准钻头系列内 |
| `DFM-32` | 底部圆角一致性 | L1 | 一期 | 圆角半径种类数 > 3 |
| `DFM-33` | 顶部圆角 | L1 | 一期 | 顶区锐边（缺圆角）/ 顶边 R < 0.5 |
| `DFM-34` | 内部倒角 | L1 | 一期 | 倒角角度/尺寸不在标准系列 |
| `DFM-35` | 深圆角转角 | L2 | 二期 | 内部转角 R < 最小刀尖圆角（未评估腔深） |
| `DFM-36` | 角度铣削面 | L1 | 一期 | 平面与基准面夹角非标准（0/30/45/60/90） |
| `DFM-37` | 窄通道 | L3 | 二期 | 槽宽 < 最小刀具直径（未做遮挡分析） |
| `DFM-38` | 孔的入刀/出刀面 | L1 | 一期 | 孔口面法向与孔轴夹角 > 5° |

**DFM-31 / DFM-32 由 `nxdrp/checkers/examples/` 的内置参考实现交付**
（被 selftest 与 Pressure Port 回归锚定），本包交付其余 10 项，不重复注册。

## 粗筛声明

数据契约没有孔深、槽深、倒角、型腔等机加工专有字段，本包全部采用低置信度
几何粗筛：Finding 带 `【粗筛】` 前缀、`coarse: true`、置信度 ≤ 0.6，
必须人工复核。已知限制共 9 条，见 `docs/M6B_WORK_STATUS.md` 引用的
README 清单。

## 公共几何库

`_m6b_machining_common.py`（文件名以 `_` 开头，registry 不加载）：

- 孔组：同轴圆柱合并、逐段深度、孔口/孔底分类（大面规则）、凸台甄别
- 槽：对置内壁 + 共同槽底，宽/深估计
- 倒角（比母平面窄的 30°~60° 面）、圆角（toroidal + 部分圆柱）、
  锐边（互垂平面直接相邻）、基准面（最大平面）
- 刀具库读取：`rules/tool_library.json`，取值顺序
  **规则 params > tool_library.json > 代码兜底**

## 阈值在哪改（改表即改判定）

- 单项阈值：`rules/dfm_default.json` 的 DFM-27~38 段（每条注明依据）；
- 刀具系列：`rules/tool_library.json`（钻头/立铣刀/倒角/角度，含来源）。

## 三个命令

```powershell
python -m nxdrp checkers                                   # M6 12/12，零加载错误
python -m nxdrp check mockdata/models/board_a.model.json --only DFM-31
python -m unittest discover -s tests                       # 含 test_m6b_*.py
```

## 测试与评测资产

- 合成夹具：`tests/fixtures/machining_syn.model.json`
  （每项正/负/边界例，生成器 `tools/gen_m6b_fixture.py`）
- 测试：`tests/test_m6b_common.py` / `test_m6b_checkers.py` / `test_m6b_cli.py`
- 标注集：`mockdata/labels/m6b/`（5 份）
- 完成度报告：`docs/M6B_WORK_STATUS.md`

## 交之前自查

- [ ] 在 Mock 模型**和**至少一个真实 NX 模型上都跑出正确结果
- [ ] 每条结果带 `face_ids`，工程师能点回 3D 现场
- [ ] 建议能照着改（给目标尺寸或结构动作），不是「请注意检查」
- [ ] 阈值写在 `rules/` 里，代码里只有默认值
- [ ] 数据不够时跳过并说明缺什么，不产出假结果
- [ ] 正例 / 负例 / 边界三个测试都有
