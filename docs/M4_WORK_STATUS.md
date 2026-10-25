# M4 装配 DFM — 工作完成情况

- 负责人：汪琪竣（M4）
- 日期：2026-10-25
- 范围：DFM-01 ～ DFM-07（7 项装配检查）
- 位置：`nxdrp/checkers/m4_assembly/`
- 结论：**流程级开发与回归验证通过；尚不能宣称 7 项全部达到真实工程验收精度。**

现有仓库模型足以验证 DFM-01/02；DFM-03～07 已完成检查逻辑、正例、负例、
阈值边界和缺数据跳过测试，但仓库没有真实孔槽配合与紧固件装配语义，因此仍需
真实产品装配或经工艺人员确认的标注完成最终验收。

---

## 1. 实现范围

| ID | 检查项 | 当前实现 | 无可靠数据时的行为 |
|---|---|---|---|
| DFM-01 | 干涉检测 | 优先读取 NX 实体求交结果；否则使用包围盒重叠粗筛 | 低置信度并标记需 NX 复核 |
| DFM-02 | 最小间隙 | 包围盒预筛；有 NX 代理时一次批量测量全部候选面配对 | 包围盒下界粗筛 |
| DFM-03 | 孔对齐 | 圆柱轴线/直径/中心偏差与孔配对标注 | 无可靠跨零件配对孔时跳过 |
| DFM-04 | 孔/槽对齐 | 孔轴线与槽中线偏差 | 无槽语义或配对关系时跳过 |
| DFM-05 | 紧固件可达性 | 工具包络尺寸、可达性和遮挡件判定 | 无工具包络测量时跳过 |
| DFM-06 | 紧固件间隙 | 径向与轴向间隙判定 | 无间隙测量时跳过 |
| DFM-07 | 紧固件啮合长度 | 按材料检查有效啮合长度与公称直径之比 | 无直径或啮合长度时跳过 |

所有检查项均满足以下结果契约：

- `location` 或 `bbox` 至少一个；
- `evidence.face_ids` 可回溯到模型面；
- 包含实测值、阈值、偏差和可执行建议；
- 粗筛结论置信度低于 0.9，并在消息和 `extra.coarse` 中明确说明。

---

## 2. 文件结构

```text
nxdrp/checkers/m4_assembly/
├── __init__.py
├── _assembly_base.py
├── _assembly_common.py
├── assembly_dfm.py                    # 旧导入路径兼容入口
├── dfm01_interference.py
├── dfm02_min_clearance.py
├── dfm03_hole_alignment.py
├── dfm04_hole_slot_alignment.py
├── dfm05_fastener_accessibility.py
├── dfm06_fastener_clearance.py
├── dfm07_engagement_length.py
├── README.md
└── test_m4.py

tests/test_m4_assembly.py               # 团队统一测试发现入口
rules/dfm_default.json                  # DFM-01～07 阈值与来源说明
```

---

## 3. 已解决的问题

1. NX 转码中的 `Occurrence.part_ref` 是原型文件名，并不总等于 `Part.part_id`。
   现按实例名、零件名和 `occurrence_path` 联合校验，避免合法装配被全部跳过。
2. 面类型统一以 `uf_face_type` 为准。旧版 `SolidFaceType` 映射曾把平面、圆柱和
   B 曲面混淆；M4 孔识别不再受该旧映射影响。
3. DFM-02 不再只测一个包围盒最近面，而是一次批量预取全部候选面配对，再从
   NX 精确结果中取真正的最小距离。
4. 包围盒间隙属于下界而非精确值；相关 Finding 已统一标记“粗筛”、降低置信度，
   并要求 NX 复核。
5. 装配间隙是两零件/两面之间的关系，不再伪造单点位置，改用 `bbox + face_ids`
   定位并兼容现有评测标注。
6. 姓名已由“汪琪俊”统一修正为“汪琪竣”。

---

## 4. 验证结果

### 4.1 M4 专项测试

```powershell
python -m unittest nxdrp.checkers.m4_assembly.test_m4 -v
```

结果：16 项通过。覆盖注册、规则一致性、正例、负例、阈值边界、NX 批量测距、
装配实例关联、共享演示场景和用户新增 NX 缓存文件。

### 4.2 共享场景

| 场景 | DFM-01 | DFM-02 | DFM-02 P/R/F1 | 说明 |
|---|---:|---:|---|---|
| `demo_asm` | 3 | 5 | 1.0 / 1.0 / 1.0 | 混合：重叠、临界间隙、正常件 |
| `demo_normal` | 0 | 0 | 无正样本 | 纯负样本，M4 零误报 |
| `demo_edge` | 0 | 2 | 1.0 / 1.0 / 1.0 | 0.299、0.300 报；0.302 不报 |
| `demo_large` | 0 | 0 | 未标注 | 24 组件性能场景，M4 检查约 10 ms |

### 4.3 用户新增 `.cache` 模型

`.cache/models/d398d69c30eca2f03d5f1cd6551000229780154c.json` 契约校验通过：

- Pressure Port，1 个零件、13 个面、19 条边；
- UF 类型为 2 平面、3 圆柱、1 球面、7 B 曲面；
- 无解析告警，内容摘要 `5ab50baa6e91d4ce`；
- 因为是单零件且没有 occurrence，DFM-01～07 正确返回 `missing_data: multiple_parts`。

该文件能验证 NX 转码契约和基础几何，不能验证装配检查。`.cache/` 是可再生缓存，
已被 `.gitignore` 排除，不应提交。

### 4.4 全量回归

团队统一命令：

```powershell
python -m unittest discover -s tests -v
```

M8 报告测试额外需要：

```powershell
python -m pip install -r nxdrp/checkers/m8_report/requirements-test.txt
```

若缺少 `pypdf`，会有两个 M8 测试报 `ModuleNotFoundError`，与 M4 无关。
安装测试依赖后，本地结果为 **146 项通过、1 项因未调用真实 NX 而跳过**。

---

## 5. 现有模型审计与验收缺口

仓库有 50 个 `.prt`，其中 41 个是同一 Pressure Port 的完全相同副本，仅文件名和
装配位置不同。现有模型用途如下：

- `demo_asm` / `demo_normal` / `demo_edge`：DFM-01/02 正例、负例和边界；
- `asm_test`：组件展开和 4×4 变换矩阵；
- `demo_large`：24 组件性能；
- `plate_holes` / `deep_slot` / `bosses` / `thin_wall`：单零件钣金或机加工夹具；
- `board_a`：无 NX 环境下的全链路 Mock；
- `pcb_standoff`：NX 解析探索样例，但没有 occurrence、轴线或紧固件语义；
- `bent_sheet` / `machining_syn`：其他模块的合成 JSON 夹具。

当前没有以下工程证据：

1. 经确认的跨零件配对孔；
2. 孔与槽组成的真实装配；
3. 螺钉/螺栓/螺母及其工具包络；
4. 紧固件径向、轴向间隙；
5. 公称直径、有效啮合长度和被连接件材料；
6. NX 精确实体求交标注。

因此，DFM-03/04 可以利用现有零件重新构造专用装配夹具；DFM-05～07 需要新增
真实紧固件装配，或由工艺人员确认的 `model.meta.assembly_features` 标注。

---

## 6. 复现命令

```powershell
python -m nxdrp doctor
python -m nxdrp checkers
python -m nxdrp selftest
python -m unittest nxdrp.checkers.m4_assembly.test_m4 -v
python -m unittest discover -s tests -v
```

只跑 M4 场景：

```powershell
python -m nxdrp check mockdata/models/demo_asm.model.json `
  -r rules/dfm_default.json `
  --only DFM-01,DFM-02,DFM-03,DFM-04,DFM-05,DFM-06,DFM-07
```

---

## 7. 当前验收判断

- 插件注册、规则读取、检查执行、Finding 契约、评测和回归链路：通过；
- DFM-01/02 共享场景行为：通过；
- DFM-03～07 合成语义行为：通过；
- DFM-03～07 真实装配工程精度：尚未验证；
- 最终结论：**可作为 M4 流程级交付，不应表述为全部工程精度验收完成。**
