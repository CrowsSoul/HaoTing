# M6B 机加工 DFM 插件（DFM-27 ~ DFM-38）

**负责人**：张百瑞（M6）　**形式**：仓库根目录独立插件，框架零改动
**分支**：`develop_zbr`

孔太深钻头会断、圆角太小刀具进不去、孔径不在标准刀具系列还得定制刀。
本插件把这 12 项「加工做不出来或者做出来很贵」的检查做成可跑的 checker。

> **粗筛声明**：数据契约里没有孔深、槽深、倒角、型腔等机加工专有字段，
> 本插件全部采用低置信度几何粗筛。粗筛结果带 `【粗筛】` 前缀、
> `coarse: true`、置信度 ≤ 0.6，必须人工复核。只有 DFM-31/32 这类
> 直接测量项给出高置信度（0.8~0.9）。

---

## 一、12 项检查的分工

| ID | 名称 | 交付位置 | 判定逻辑（粗筛） |
|---|---|---|---|
| DFM-27 | 深孔 | 本插件 `dfm27_deep_hole.py` | 同轴孔组逐段深径比 > 4；> 10 升 P1 |
| DFM-28 | 深窄槽 | `dfm28_deep_narrow_slot.py` | 槽深/槽宽 > 3（对置内壁 + 共同槽底） |
| DFM-29 | 平底盲孔 | `dfm29_flat_bottom_blind_hole.py` | 盲孔底为平面（锥底=钻尖，豁免） |
| DFM-30 | 刀具可达性（二期占位） | `dfm30_tool_accessibility.py` | 孔口沿轴包络圆柱与其他零件包围盒相交 |
| DFM-31 | 特征尺寸与刀具标准 | **内置参考实现** `nxdrp/checkers/examples/dfm31_tool_standard.py` | 孔径不在钻头系列内 |
| DFM-32 | 底部圆角一致性 | **内置参考实现** `nxdrp/checkers/examples/dfm32_fillet_uniformity.py` | 圆角半径种类数 > 3 |
| DFM-33 | 顶部圆角 | `dfm33_top_fillet.py` | 顶区锐边（缺圆角）/ 顶边 R < 0.5 |
| DFM-34 | 内部倒角 | `dfm34_internal_chamfer.py` | 倒角角度/尺寸不在标准系列 |
| DFM-35 | 深圆角转角（二期粗筛） | `dfm35_deep_radius_corner.py` | 内部转角 R < 最小刀尖圆角（未评估腔深） |
| DFM-36 | 角度铣削面 | `dfm36_angular_milling.py` | 平面与基准面夹角非标准（0/30/45/60/90） |
| DFM-37 | 窄通道（二期粗筛） | `dfm37_narrow_passage.py` | 槽宽 < 最小刀具直径（未做遮挡分析） |
| DFM-38 | 孔的入刀/出刀面 | `dfm38_hole_entry_exit.py` | 孔口面法向与孔轴夹角 > 5° |

**为什么是 10 + 2**：DFM-31/32 在 `nxdrp/checkers/examples/` 已有平台验证过的
参考实现（自检、74 个共享单测、Pressure Port 回归都锚定它们的行为）。插件
原样复用，不重复注册（注册表禁止同 ID 重复）。本插件对 31/32 的增强
（槽宽比对立铣刀系列、阶梯孔分段、刀具库外置链）已做成代码并验证，
**留待平台合并时随 `_m6b_machining_common.py` 一起启用**，见 WORK_STATUS。

## 二、目录

```text
m6b_machining_plugin/
├── _m6b_machining_common.py      # 公共几何：孔组（同轴合并/深度/孔口孔底/凸台甄别）、
│                                 #   槽（宽/深）、倒角、圆角、锐边、基准面、刀具库读取
├── dfm27_deep_hole.py            # …共 10 个 checker 文件
├── rules_m6b.json                # 12 条规则（每条注明阈值依据）
├── tool_library.json             # 标准刀具库（钻头/立铣刀/倒角/角度系列，含来源）
├── README_M6B.md                 # 本文档
├── WORK_STATUS_M6B.md            # 验证结果与实测基线
├── validation/labels/            # 5 份标注集（流程验证用）
└── __tests__/                    # 65 个单测（registry 跳过该目录）
    ├── build_fixtures.py         # 合成夹具生成器（每个 checker 的正/负/边界例）
    ├── fixtures/machining_syn.model.json
    ├── test_common.py / test_checkers.py / test_plugin_cli.py
```

## 三、常用命令

```powershell
# 环境：conda env nxdrp（Python 3.12），仓库根目录
python -m nxdrp checkers --plugin m6b_machining_plugin     # M6 12/12，零加载错误
python -m nxdrp selftest --plugin m6b_machining_plugin     # 自检通过
python -m unittest discover -s m6b_machining_plugin/__tests__ -p "test_*.py"
python -m unittest discover -s tests                       # 共享 74 个不破坏

# 单模型检查 + 评测（以合成夹具为例）
python -m nxdrp check m6b_machining_plugin/__tests__/fixtures/machining_syn.model.json `
  --plugin m6b_machining_plugin -r m6b_machining_plugin/rules_m6b.json `
  --only DFM-27,DFM-28,DFM-29,DFM-30,DFM-31,DFM-32,DFM-33,DFM-34,DFM-35,DFM-36,DFM-37,DFM-38 `
  -o .cache/m6b_validation/machining_syn.findings.json
python -m nxdrp eval .cache/m6b_validation/machining_syn.findings.json `
  -l m6b_machining_plugin/validation/labels/machining_syn.labels.json --no-high-risk
```

## 四、改阈值（改表即改判定，不用碰代码）

- **规则参数**：`rules_m6b.json` 每条规则的 `params` 直接覆盖默认值。
  例：把深孔阈值从 4 改成 3.5 → 改 `R-DFM-27.params.deep_hole_ratio`。
- **刀具系列**：`tool_library.json` 整表替换即可换成甲方厂内刀具库；
  也可在规则里用 `standard_diameters` 等参数临时覆盖。
- 取值顺序统一为：**规则 params > tool_library.json > 代码兜底**。

## 五、已知限制（粗筛边界）

1. 孔深/槽深用包围盒跨度近似，盲孔钻尖段计入孔深，结果偏保守。
2. 凸台/销钉与孔的甄别基于「小端盖在圆柱背向主体一侧」启发，
   异形凸台（多台阶、非圆截面）可能误判。
3. 槽只支持直槽 + 平面槽底；斜槽、异形槽漏检。
4. DFM-30/35/37 为二期粗筛/占位：未做包络扫掠求交、未评估腔深、
   未做空间遮挡，误报漏报都可能存在。
5. DFM-33 的「顶」按建模 +Z（可用 `up_direction` 参数改）；装夹方向
   与建模方向不一致的零件需人工确认。
6. DFM-34 倒角尺寸取倒角面最小包围盒尺寸（≈ 腿宽），斜倒角会偏差。
7. DFM-36 以最大平面为基准面，多基准箱体类零件可能选错基准。
8. 孔口在曲面上（无法向）时 DFM-38 不判定。
9. 没有真实 NX 机加工 `.prt`，精度未在真实件上验证；本轮验证的是流程。
