# 数据契约

**这是一份工具书。写 checker 时你只需要看两处：§1 的 Face 表（你能取到什么数据）、§3 的 Finding 表（你要产出什么）。**

三份数据，各管一段：

| 契约 | 谁产出 | 谁消费 | 一句话 |
|---|---|---|---|
| `ModelBundle` | 解析层（NX 适配器） | 全部 checker | 模型长什么样 |
| `RuleBook` | 工艺工程师 / 规则维护界面 | 全部 checker | 多少算合格 |
| `Finding` | 全部 checker | 报告、前端、评测、知识库 | 发现了什么问题 |

模块之间只认这三份结构。不要 import 别人的 checker，不要自己造中间格式，
不要在 `ModelBundle` 里塞私有字段（`meta` 和 `extra` 是留给自由扩展的口子）。

要加字段：先提出来评审，改完同步升级 `nxdrp/version.py` 里的 `SCHEMA_VERSION`。

---

## 1. ModelBundle

一次模型解析的完整产物。一个装配模型解析一次，所有 checker 共享这一份。

```jsonc
{
  "schema_version": "1.0.0",
  "model_id": "Pressure Port",
  "source": "D:/models/pressure_port.prt",
  "nx_version": "v2606",
  "units": "mm",
  "parts": [...],
  "faces": [...],
  "edges": [...],
  "occurrences": [...],
  "adjacency": [["F1", "F2"], ...],
  "diagnostics": {...},
  "meta": {"has_normals": false}
}
```

### Part

| 字段 | 类型 | 说明 |
|---|---|---|
| `part_id` | str | 主键，`P01`/`P02`…；checker 里用它过滤 |
| `name` / `journal_id` | str | NX 里的名字与特征标识，便于回溯 |
| `material` | str | 材料牌号（从零件属性读，读不到为空；**不要自己填默认值**） |
| `body_type` | `solid`\|`sheet`\|`unknown` | 实体 / 片体 |
| `is_sheet` | bool | NX `IsSheetBody` |
| `volume` / `mass` / `area` | float | mm³ / g / mm²，来自 NX 质量属性 |
| `bbox` | BBox | 包围盒，mm |
| `face_count` / `edge_count` | int | 拓扑统计 |
| `occurrence_path` | str | 装配中的路径，单零件为空 |

### Face

| 字段 | 类型 | 说明 |
|---|---|---|
| `face_id` | str | 主键，格式 `F<tag>` |
| `part_id` | str | 所属零件 |
| `tag` | int | NX 对象 tag，**回 NX 做精确测量时必须用它** |
| `solid_face_type` | str | `planar` / `cylindrical` / `conical` / `spherical` / `toroidal` / `general` / `bsurface` / `blend` / `offset` |
| `solid_face_code` | int | 原始枚举值，类型对不上时用它排查 |
| `uf_face_type` | int | NX UF 面类型：16 平面 / 17 圆柱 / 18 圆锥 / 19 球 / 20 环面 / 22 B 曲面。**判类型以它为准** |
| `point` | [x,y,z]? | 面上的点；回转面为轴线上一点 |
| `normal` | [x,y,z]? | 平面法向（朝外）。非平面为 `null` |
| `axis` | [x,y,z]? | 回转面轴向（圆柱 / 圆锥 / 球 / 环面） |
| `area` / `perimeter` | float | mm² / mm |
| `radius_diameter` | float? | 回转面半径或直径，**由 `is_radius` 决定是哪一个** |
| `is_radius` | bool | `true` = 上面那个字段是半径 |
| `cog` | [x,y,z] | 面重心 |
| `bbox` | BBox | 面包围盒 |
| `edge_count` | int | 面上边的数量 |

> 取半径统一用 `nxdrp.geom.face_radius(face)`，别自己写 `*2` 或 `/2`。

### Edge

| 字段 | 类型 | 说明 |
|---|---|---|
| `edge_id` | str | `E<tag>` |
| `part_id` | str | |
| `face_ids` | [str] | 相邻面（一般 2 个）。用于二面角、圆角、尖角判定 |
| `curve_type` | str | `line` / `arc` / …（以 UF 类型码映射） |
| `length` | float | 边长 mm（实测全部有值） |
| `bbox` | BBox | 边包围盒 |

### adjacency

`[[face_a, face_b], ...]`，由边反推的面-面共边关系。用 `ctx.adjacency_pairs()`
可以直接拿到 `(Face, Face)` 对象对，省得自己查表。

### meta / diagnostics

- `meta.has_normals` / `meta.has_axes`：解析完自动置位。要法向或轴线的 checker 在
  `requires` 里声明 `"normals"` / `"axes"`，数据缺失时管线会跳过它并说明原因。
- `diagnostics`：解析过程中的告警、计数、耗时。排查「为什么这个面没数据」时先看它。

---

## 2. RuleBook

规则是**数据**，不是代码。合同第 7 条要求甲方工程师免编程维护，所以阈值一律放在
`rules/*.json`，checker 里只写「怎么算」。

```jsonc
{
  "name": "dfm_default",
  "version": "0.1",
  "rules": [
    {
      "rule_id": "R-DFM-31",
      "check_item_id": "DFM-31",
      "process_type": "machining",
      "name": "特征尺寸与刀具标准",
      "enabled": true,
      "severity": "P2",
      "params": {"standard_diameters": [1.0, 2.0, ...], "tolerance_mm": 0.05},
      "source_standard": "甲方刀具库 / 标准钻头系列",
      "notes": "孔径不在标准系列内即报"
    }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `check_item_id` | **同一检查项只能有一条规则**（重复会校验失败） |
| `enabled` | `false` 时该 checker 不执行，状态记为 `skipped` |
| `severity` | `P0` 阻断 / `P1` 严重 / `P2` 一般 / `P3` 提示；checker 可以覆盖 |
| `params` | 任意键值，会**覆盖** checker 的 `default_params` |
| `source_standard` | 阈值依据（标准号 + 表号 + 条款），验收时要能追溯 |

规则库由 `python -m tools.gen_rules` 从 `catalog.py` 生成骨架，人工填 `params`。

---

## 3. Finding

全平台唯一的结果契约。**38 个 DFM + 4 个安规 + 2 个性能预测全部吐这一个结构**，
所以报告、前端高亮、评测、知识库四件事才能解耦。

```jsonc
{
  "finding_id": "DFM-31-0001",
  "check_item_id": "DFM-31",
  "check_item_name": "特征尺寸与刀具标准",
  "process_type": "machining",
  "severity": "P2",
  "confidence": 0.9,
  "part_refs": ["P01"],
  "location": [12.3, 44.1, 5.0],
  "bbox": {...},
  "path_points": [],
  "measured_value": 7.65,
  "unit": "mm",
  "threshold_value": 8.0,
  "deviation": -0.35,
  "evidence": {"face_ids": ["F40181"], "edge_ids": [], "note": "..."},
  "suggestion": {"text": "将孔径改为 Ø8.0", "param_delta": {"diameter_mm": 8.0}, "rule_ref": "R-DFM-31"},
  "detector": {"module": "...ToolStandardChecker", "version": "0.1.0", "runtime_ms": 12.4},
  "message": "孔直径 Ø7.65 不在标准刀具系列内",
  "extra": {}
}
```

### 四条硬性要求（评测脚本会检查）

1. **有位置**：`location` 或 `bbox` 至少一个，否则报告里点不到 3D 现场。
2. **有证据**：`evidence.face_ids` 不能空（除非 `extra` 里给了等价的追溯信息）。
3. **有量化建议**：`suggestion.text` 必须让人能照着改，最好带 `param_delta` 目标值。
4. **有置信度**：粗筛类结论必须 `confidence < 0.9`，并在 `message` 里写清楚是粗筛。

### severity 的用法

| 级别 | 含义 | 示例 |
|---|---|---|
| `P0` | 阻断，必须改 | 安规间隙不达标 |
| `P1` | 严重，评审必须处理 | 硬干涉、壁厚严重不足 |
| `P2` | 一般，建议改 | 非标刀具、圆角种类过多 |
| `P3` | 提示，可豁免 | 包围盒粗筛出的疑似干涉 |

---

## 4. 版本与兼容

- `SCHEMA_VERSION` 在 `nxdrp/version.py`。破坏性变更（删字段、改语义）必须升大版本。
- `ModelBundle.from_dict` 遇到不认识的字段会直接报错。所以加字段必须走评审，不能先加后说。
- 每份契约都有对应的 JSON Schema：`python -m nxdrp schema -o contracts/schema`，
  M7 的前端用它生成 TypeScript 类型，不用手写接口。
