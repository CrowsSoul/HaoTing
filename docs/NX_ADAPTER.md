# NX 集成说明

**这份文档给谁看：只有要改「NX 解析」那一层的人需要读。写 checker 不用看。**

下面记的是这台机器上实测到的 NX 行为。改这里的 API 调用前，先按第 8 节的方法复核一遍，
不要凭记忆写。

---

## 1. 环境（实测）

| 项 | 值 |
|---|---|
| 产品 | Siemens Designcenter 2606（NX 2606） |
| 安装目录 | `C:\Program Files\Siemens\Designcenter2606` |
| 环境变量 | `UGII_BASE_DIR` 已设置 |
| 批处理入口 | `%UGII_BASE_DIR%\NXBIN\run_journal.exe` |
| NX 内 Python | 3.12.13（`NXBIN\python\python312.dll` + `NXOpen.pyd`） |
| License | `SPLM_LICENSE_SERVER=C:\ProgramData\Siemens\siemens_SSQ.dat` |

**宿主 Python（3.12）不能 `import NXOpen`。** 必须把代码送进 NX 进程内执行。

---

## 2. 为什么要起一个 NX 进程，而不是常驻

宿主 Python 不能 `import NXOpen`，代码必须送进 NX 进程里执行。
常驻会话要额外的远程调用组件和 License 管理，崩溃还会拖垮服务，所以选了批处理：
每次起一个 NX 进程，跑完就退。

代价是每次启动约 28 秒。这用**缓存**抵消：解析结果按「模型路径 + 大小 + 修改时间 + NX 版本」落盘，
同一个模型第二次检查直接读缓存。

实测数据：

| 场景 | 耗时 |
|---|---|
| NX 进程启动 + 打开 Part + 提取 13 个面 | 28.9 s |
| 同上，其中 **NX 内部**真正干活的时间 | **1.26 s** |
| 命中缓存后的加载 | < 50 ms |

结论：**启动是固定成本，解析本身很快**。所以缓存和并发池比优化算法更重要。

---

## 3. 调用链

```
NxBatchAdapter.load(part_path)
  │
  ├─ cache_key = sha1(path|size|mtime|ugii_base_dir)
  ├─ 命中 .cache/models/<key>.json  → 直接返回 ModelBundle
  │
  └─ run_journal("extract_geometry", request)
       ├─ 写 request.json（含 part 路径与选项）
       ├─ 设环境变量 NXDRP_NX_REQUEST / NXDRP_NX_RESPONSE
       ├─ subprocess: run_journal.exe nxdrp/journals/extract_geometry.py
       │     └─ NX 进程内：import NXOpen → 打开 Part → 遍历 body/face/edge
       │                     → Measurement 测量 → 写 response.json
       └─ 读 response.json → ModelBundle.from_dict() → validate() → 落缓存
```

**数据只通过文件和环境变量传递**，不拼接命令行。这样中文路径、空格、超长路径
都不会因为 argv 编码出问题。

---

## 4. 已验证的 NXOpen API（NX 2606）

### 4.1 打开零件

```python
session = NXOpen.Session.GetSession()
part = session.Parts.OpenBaseDisplay(path)[0]   # 返回元组
part.Close(NXOpen.BasePart.CloseWholeTree.FalseValue,
           NXOpen.BasePart.CloseModified.CloseModified, None)
```

### 4.2 遍历拓扑

```python
for body in part.Bodies:
    body.IsSheetBody              # bool
    body.JournalIdentifier        # "EXTRUDE(3)"
    body.MassProperties           # ❌ 不存在，用 Measurement
    for face in body.GetFaces():
        face.Tag                  # int
        face.SolidFaceType        # 枚举成员，int() 会 TypeError，要 str() 再转
        face.GetEdges()
    for edge in body.GetEdges():
        edge.GetFaces()           # 相邻面，用于建 adjacency
```

### 4.3 测量（本项目最常用的三个）

```python
m = session.Measurement

# 面属性：面积/周长/半径/重心
area, perim, radius_or_diameter, cog, min_r, err, anchor, is_approx = \
    m.GetFaceProperties([face], 0.99, alternate_solution, False)

# 体属性：massProps 列表（[0]=面积 [1]=体积 [6]=质量）
props = m.GetBodyProperties([body], 0.99, False)

# 包围盒
box = m.GetBoundingBoxProperties([body], 0, NXOpen.Point3d(0, 0, 0), True)
# box[0] 是 8 个 Point3d 角点
```

### 4.4 面类型：以 UF 类型为准

```python
uf_type, point, direction, bbox, radius, _angle, _ = ufs.Modeling.AskFaceData(tag)
```

`AskFaceData` 一次给出面的全部关键信息：

| 位置 | 含义 |
|---|---|
| `[0]` | UF 面类型码 |
| `[1]` | 面上的点；回转面为轴线上一点 |
| `[2]` | 平面 → 法向；回转面 → 轴向 |
| `[3]` | 包围盒 6 个数 |
| `[4]` | 半径（回转面） |

UF 类型码：

| 码 | 含义 | 码 | 含义 |
|---|---|---|---|
| 16 | `planar` | 20 | `toroidal` |
| 17 | `cylindrical` | 22 | `bspline` |
| 18 | `conical` | 28 | `blend` |
| 19 | `spherical` | 29 | `offset` |

> **踩过的坑**：`NXOpen.Face.SolidFaceType` 的数值和 UF 完全不是一套。
> 早期按 NXOpen 码猜「1=planar / 2=cylindrical」，结果把 7 个 B 曲面当成了平面、
> 把圆柱当成了圆锥，DFM-31 判孔全靠一个圆形平面的半径凑巧对上。
> 现在统一以 `uf_face_type` 判定，`solid_face_code` 只留作排查。

Pressure Port 实测分布：2 平面 / 7 B 曲面 / 3 圆柱 / 1 球面，与几何形态一致。

### 4.5 最小距离（已接入）

```python
distance, p1, p2, accuracy = m.GetMinimumDistance(object1, object2)
```
允许的输入：Curve / Edge / Face / Body / Plane / Csys。

适配器已封装成**批量**接口，一次 NX 启动测完所有配对：

```python
adapter.measure_distance(part_path, [(tagA, tagB), (tagC, tagD)])
# -> {"pairs": [{"a":..,"b":..,"distance":..,"p1":[..],"p2":[..]}], "errors": [...]}
```

无效 tag 不会整体失败，会单独进 `errors`。**不要逐对调用**——每对一次就是一次
28 秒的 NX 启动。

---

### 4.6 装配：组件展开与变换（已真机验证）

装配体本身**没有 body**，要先展开到组件，再取各组件的原型零件：

```
for child in root.GetChildren():
    proto = child.Prototype.OwningPart      # 原型零件
    for body in proto.Bodies: ...           # 几何在这里
    loc, ori = child.GetPosition()          # 注意：返回的是元组
```

四个坑，都踩过：

1. **`ComponentAssembly.Add` 不存在**，正确方法是
   `AddComponent(part, refset, name, basePoint, Matrix3x3, layer)`；
   加之前要 `session.Parts.SetWork(asm)`。
2. **`Component.Transform` / `.Position` 都不存在**，位置要从 `GetPosition()` 取。
3. **`GetPosition()` 返回 `(location, orientation)` 元组**，不是带 `.Location` 属性的对象。
   按对象取会静默拿到 `None`，变换矩阵就悄悄退化成了单位阵——看着有数据，其实全堆在原点。
4. **`GetBoundingBoxProperties(..., allowCache=True)` 会串数据**：缓存按 tag 走，
   多组件场景里每个零件都是同一份文件的副本、tag 相同，会把上一个面的盒子串给下一个零件。
   实测 `D_NEAR2` 的包围盒被写成了 4.45 mm 宽（一个孔的宽度），跟它自己的面数据对不上。
   **必须传 `allowCache=False`**。

自建测试装配（`mockdata/asm_test/`，两个 Pressure Port 副本，PART_B 在 x=120）实测：

```
PART_B  transform = [[1,0,0,120],[0,1,0,0],[0,0,1,0],[0,0,0,1]]   OK
PART_A  transform = [[1,0,0,0],  [0,1,0,0],[0,0,1,0],[0,0,0,1]]
parts: P01(PART_B, 13 面) / P02(PART_A, 13 面)
```

六组件评测场景（`mockdata/scenes/demo_asm/`，`mockdata/models/demo_asm.model.json`）实测：

```
6 组件 / 78 面 / 6 个 occurrence
零件包围盒已变换到装配坐标系：
  A_BASE    0.00 ->  30.00
  B_NEAR   30.15 ->  60.15
  C_FAR    60.00 ->  90.00
  D_NEAR2  90.30 -> 120.30
  E_OVERLAP 15.00 ->  45.00
  F_ALONE 150.00 -> 180.00
```

场景怎么搭、能给谁用，见 `docs/DEMO_SCENE.md`。
生成脚本是 `nxdrp/journals/build_demo_assembly.py`，改 `DEFAULT_PLACEMENTS` 就能造新场景。

## 5. 当前限制（必须知道）

| 限制 | 原因 | 状态 |
|---|---|---|
| 面法向 / 圆柱轴线 | 已用 `ufs.Modeling.AskFaceData` 接入 | ✅ 已完成（Pressure Port 实测） |
| 批量精确测距 | 已接入 `measure_distance` journal | ✅ 已完成（实测 27.73 / 2.65 mm） |
| 面类型判定 | **以 UF 类型为准**（见 4.4），NXOpen 的 `SolidFaceType` 与之不对应 | ✅ 已修正 |
| 装配结构 | 已用自建两零件装配验证：组件展开、变换矩阵、原型引用全部正确 | ✅ 已完成（见 4.6） |
| 材料属性 | 已实现从零件属性读（MATERIAL / 材料 等），样例零件无属性 | 需甲方模型带材料属性 |
| 真实大模型未压测 | 实测 312 面 33.5 s，边际 5.6 ms/面 | 见 docs/PERF.md；需甲方给 1000 面以上模型 |

**对 checker 的影响**：需要尚未提取的数据时，请在 `requires` 里声明，
管线会跳过并说明原因。这就是为什么 `requires` 不是可选项。

---

## 6. 怎么新增一个测量（以最小距离为例）

框架已经把 journal 执行做成通用的了，加一个测量只要两步。
`nxdrp/journals/measure_distance.py` 就是照这个模式写的，可以直接对照。

```python
import json, os, traceback

REQ = os.environ["NXDRP_NX_REQUEST"]
RESP = os.environ["NXDRP_NX_RESPONSE"]

def emit(p):
    with open(RESP, "w", encoding="utf-8") as fh:
        json.dump(p, fh, ensure_ascii=False)

try:
    import NXOpen
    req = json.load(open(REQ, encoding="utf-8"))
    s = NXOpen.Session.GetSession()
    part = s.Parts.OpenBaseDisplay(req["part"])[0]
    objs = {o.Tag: o for o in part.Bodies}          # 也可以按 face tag 建索引

    pairs = []
    for a, b in req["pairs"]:
        d, p1, p2, acc = s.Measurement.GetMinimumDistance(objs[a], objs[b])
        pairs.append({"a": a, "b": b, "distance": float(d)})

    emit({"ok": True, "pairs": pairs})
except Exception as exc:
    emit({"ok": False, "error": repr(exc), "traceback": traceback.format_exc()})
```

### 第二步：加一个适配器方法

```python
def min_distance(self, part_path: str, pairs):
    return self.run_journal("measure_distance", {"part": part_path, "pairs": pairs})
```

> ⚠️ 注意：`run_journal` 每次都会新开一个 NX 进程（约 28 秒）。
> 批量测量务必**一次把多组配对传进去**，不要每组调一次。

然后在 checker 里通过 `ctx.nx` 使用它（管线会把适配器注入 `ctx.nx`）。

---

## 7. 并发与 License

NX 实例数是稀缺资源，所以适配器里有一个**进程级信号量**：

```powershell
$env:NXDRP_NX_MAX_CONCURRENCY = "4"   # 默认 4，按 License 数量调整
```

- 同一时刻最多 4 个 NX 进程，其余排队；
- 排队时不要给前端显示假进度，应当显示排队位次（M7 要注意）；
- 一次检查任务内，**只解析一次模型**，几十个 checker 共享同一份 ModelBundle
  ——这是满足「单次检查 ≤ 30 分钟」的关键，不是靠优化单个 checker。

---

## 8. 排障

| 现象 | 先看哪里 |
|---|---|
| `未找到 run_journal.exe` | `python -m nxdrp doctor`；确认 `UGII_BASE_DIR` |
| journal 超时 | 模型太大 / License 被占用 / NX 弹了不可见对话框 |
| `没有产生响应文件` | 看报错里的 `stdout_tail` / `stderr_tail`，通常是 journal 语法错误或 Part 打不开 |
| 面数据全空 | `model.diagnostics` 里的 `sections`，会写哪一段失败及原因 |
| 面类型是 `unknown_N` | 遇到了未收录的枚举值，把 `N` 加进 `FACE_TYPE_MAP` 并补验证 |

复核方法：把所有 `.prt` 换成你手上的真实模型，跑
`python -m nxdrp extract <model> --no-cache`，然后看输出的 `diagnostics`。
