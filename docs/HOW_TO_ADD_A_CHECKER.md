# 怎么加一个检查项

你负责的检查项在 `nxdrp/checkers/<你的包>/` 里，一个文件一项，互不干扰。

这份文档只讲三件事：**你手上有什么数据、怎么写判定、怎么知道自己写对了。**

---

## 一、先看自己分到哪几项

```powershell
python -m nxdrp items --owner M4        # 换成你的模块号
```

---

## 二、你手上已经有的数据（平台给的，不用自己算）

### Face：面

| 字段 | 含义 | 什么时候有 |
|---|---|---|
| `face_id` | `F<tag>` | 总是 |
| `solid_face_type` | `planar` / `cylindrical` / `conical` / `spherical` / `bspline` … | 总是 |
| `uf_face_type` | NX UF 类型码 | 总是（判类型以它为准） |
| `normal` | 平面法向 | 平面 |
| `axis` | 回转面轴向 | 圆柱 / 圆锥 / 球 / 环面 |
| `point` | 面上一点（回转面是轴线上一点） | 平面 / 回转面 |
| `area` / `perimeter` | mm² / mm | 总是 |
| `radius_diameter` + `is_radius` | 半径或直径 | 圆形面 |
| `cog` | 重心 | 总是 |
| `bbox` | 包围盒（装配下已换算到装配坐标系） | 总是 |
| `edge_count` | 面上边的数量 | 总是 |

**取用一律走 `nxdrp.geom`，别自己写 `*2` `/2`：**

```python
from ...geom import face_min_radius, face_normal, face_axis, draft_angle_deg

r = face_min_radius(face)                # 半径，自动处理 is_radius
n = face_normal(face)                    # 单位法向，非平面返回 None
a = face_axis(face)                      # 单位轴向，非回转面返回 None
deg = draft_angle_deg(face, (0, 0, 1))   # 拔模角，需要法向
```

### Edge：边

| 字段 | 含义 |
|---|---|
| `edge_id` | `E<tag>` |
| `curve_type` | `line` / `arc` / …（实测：72 直线 / 42 圆弧） |
| `length` | 边长 mm（实测全部有值，13.98–30.32） |
| `face_ids` | 相邻的两个面，用来算二面角、判圆角 |
| `bbox` | 边包围盒 |

**边长是判断「小圆角」「短边」「尖角」的直接依据**，不要再自己用包围盒对角线估。

### Part：零件 / 装配组件

| 字段 | 含义 |
|---|---|
| `part_id` | `P01`、`P02`… |
| `occurrence_path` | 装配里的组件名（单零件为空） |
| `material` | 材料（从零件属性读；读不到就是空，**别自己填默认值**） |
| `bbox` / `volume` / `mass` | 已经在装配坐标系下 |
| `faces` / `edges` | 用 `model.faces_of(part_id)` 取 |

### 装配

`model.occurrences` 里每个组件带 4×4 变换矩阵 `transform`，`model.parts[].bbox` 已经应用过它。
**你在装配坐标系下算距离就行，不用自己乘矩阵。**

### 能力声明（`requires`）

```python
requires = ("faces", "normals")     # 需要法向
requires = ("faces", "axes")        # 需要回转轴向
requires = ("edges", "adjacency")   # 需要边与邻接
```

数据缺失时管线会**跳过**你的检查项并说明原因，不会给你错误输入。
目前 `normals` / `axes` / `edges` 都已具备。

---

## 三、三种判定写法，按检查项性质挑

### 写法 1：读表判定（大多数 DFM 项都该这样写）

阈值放 `rules/dfm_default.json`，代码里只有比较逻辑。

```python
class MyChecker(BaseChecker):
    check_item_id = "DFM-31"
    requires = ("faces", "cylindrical_faces")

    def check(self, ctx):
        tol = float(ctx.param("tolerance_mm", 0.05))
        std = [float(x) for x in ctx.param("standard_diameters", [])]
        for f in ctx.faces("cylindrical"):
            d = face_radius(f) * 2
            nearest = min(std, key=lambda s: abs(s - d))
            if abs(nearest - d) > tol:
                yield ctx.finding(
                    check_item_id="DFM-31",
                    part_refs=[f.part_id],
                    location=f.cog,
                    message=f"孔直径 {d:.2f} 不在标准刀具系列内",
                    measured_value=round(d, 4),
                    threshold_value=nearest,
                )
```

完整实现看 `examples/dfm31_tool_standard.py`。

### 写法 2：几何计算（需要法向、边长、面积）

```python
for f in ctx.faces("planar"):
    deg = draft_angle_deg(f, pull_dir=(0, 0, 1))
    if deg is None:
        continue
    if deg < 1.0:
        yield ctx.finding(
            check_item_id="DFM-13",
            part_refs=[f.part_id],
            location=f.cog,
            message=f"拔模角 {deg:.2f}°，脱模会拉伤",
            measured_value=round(deg, 3),
            threshold_value=1.0,
        )
```

### 写法 3：精确测距（间隙、干涉、爬电）

**必须批量预取，绝不能逐对起 NX**——起一次 NX 约 30 秒。

```python
def check(self, ctx):
    if ctx.nx is None:
        return []                       # 没有 NX 环境（跑 Mock 数据时）
    pairs = [(a.tag, b.tag) for a, b in ctx.adjacency_pairs(max_gap=2.0)]
    ctx.nx.prefetch(pairs)              # 一次 NX 启动，全测完
    for a, b in ...:
        d = ctx.nx.distance(a.tag, b.tag)
        if d is None:
            continue                    # 没测到就跳过，不要猜
        ...
```

`ctx.nx.distance()` **不会偷偷起 NX**：没预取就返回 `None`。这是故意的。

---

## 四、写完怎么知道自己对了

### 第一步：跑起来

```powershell
python -m nxdrp check mockdata/models/demo_asm.model.json --only DFM-31
```

### 第二步：拿三套场景验证行为

| 场景 | 应该看到 |
|---|---|
| `demo_asm` | 混合场景，有缺陷也有正常区域 |
| `demo_normal` | **纯负样本**：装配类检查项一条都不该报 |
| `demo_edge` | 阈值边界：0.299 / 0.300 报，0.302 不报 |

```powershell
python -m nxdrp check mockdata/models/demo_normal.model.json -o f.json
```

如果你的检查项在 `demo_normal` 上报了东西，**先怀疑自己误报**，别急着说模型有问题。

### 第三步：打分

```powershell
python -m nxdrp eval f.json -l mockdata/labels/demo_asm.labels.json
```

输出会告诉你精确率、召回、F1、误报率，以及哪些预测「没有标注、未计分」。

**自己要补标注**：`docs/LABELING.md` 写了格式。每项至少 5 个正样本 + 2 个负样本，
否则 F1 是假的。拿自己的输出反标自己，只会得到 100 分和一个没用的检查器。

---

## 五、几条硬规矩

1. **只改自己的目录。** `contracts/`、`pipeline.py`、`registry.py`、`base.py`、`geom.py`
   是公共的，要改先跟平台方说。
2. **阈值不写死在代码里。** 一律进 `rules/dfm_default.json`，并注明依据（厂标？经验值？标准条款？）。
3. **不改契约字段。** 想加字段先提出来评审——框架会直接拒绝未知字段。
4. **数据缺失就跳过，别猜。** 拿不到法向就 `requires` 声明，不要用重心方向糊弄。
5. **粗筛结果必须标明。** 用包围盒算出来的间隙，Finding 里要写「粗筛」，不能说成精确值。

---

## 六、一个完整例子（DFM-13 拔模角）

```python
# -*- coding: utf-8 -*-
"""DFM-13 拔模角：平面法向与开模方向的夹角不足就报。"""

from typing import Iterable

from ...checkers.base import BaseChecker, CheckContext
from ...contracts import Finding
from ...geom import draft_angle_deg


class DraftAngleChecker(BaseChecker):
    check_item_id = "DFM-13"
    requires = ("faces", "normals")

    def applies(self, model) -> bool:
        return any(f.normal is not None for f in model.faces)

    def check(self, ctx: CheckContext) -> Iterable[Finding]:
        min_deg = float(ctx.param("min_draft_deg", 1.0))
        pull = (0.0, 0.0, 1.0)          # 开模方向，简单起见取 +Z
        for f in ctx.faces():
            deg = draft_angle_deg(f, pull)
            if deg is None or deg >= min_deg:
                continue
            yield ctx.finding(
                check_item_id=self.check_item_id,
                part_refs=[f.part_id],
                location=f.cog,
                message=f"面 {f.face_id} 拔模角 {deg:.2f}° < {min_deg:.1f}°",
                measured_value=round(deg, 3),
                threshold_value=min_deg,
                severity="P2",
                suggestion=f"把该面与开模方向夹角加到 {min_deg + 0.5:.1f}° 以上",
                evidence_face_ids=[f.face_id],
            )
```

规则表里加一行：

```json
{"check_item_id": "DFM-13", "params": {"min_draft_deg": 1.0}}
```

跑：

```powershell
python -m nxdrp check mockdata/models/pressure_port.model.json --only DFM-13
```

---

## 七、卡住了看哪份

| 想知道 | 看 |
|---|---|
| 数据字段什么意思 | `docs/CONTRACT.md` |
| NX 里怎么取数 | `docs/NX_ADAPTER.md` |
| 标注怎么标、分怎么算 | `docs/LABELING.md` |
| 有哪些场景可以试 | `docs/DEMO_SCENE.md` |
| 性能预算怎么算 | `docs/PERF.md` |
