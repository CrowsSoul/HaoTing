# 连接器 AI 智能设计检查平台

一句话：把连接器的 3D 模型丢进去，自动查出设计问题，出一份能直接拿去评审的报告。

- 甲方：浩亭（珠海）制造有限公司
- 乙方：哈尔滨工业大学计算学部
- 当前版本：框架 v0.1.0，数据契约 v1.0.0

---

## 一、这个平台要解决什么

浩亭的工程师现在怎么干活：

- 连接器设计完，要在 NX 里**逐项人工点** 38 项可制造性检查（DFM），一个人一下午，还容易漏；
- 电气间隙、爬电距离要手工操作 AutoCrear 量，靠经验判断；
- 载流、温升、插拔力这些性能，只能靠算、靠经验、靠试做样品。

一条产品走完，光检查就是 1~2 个工作日，性能验证还要 5 天。

平台要做的事：**模型上传 → 自动跑完全部检查 → 出一份报告**。报告里每条问题都要说清四件事——在哪儿、差多少、多严重、怎么改。

本期（12 个月）落地的三件事：

| 做什么 | 做到什么程度 |
|---|---|
| 智能 DFM 检查 | 38 个检查项，缺陷识别准确率 ≥ 90% |
| 智能安规检查 | 电气间隙 + 爬电距离，精度不低于 AutoCrear |
| 智能性能预测 | 选一项（建议载流–温升）做 AI 预测 |

外加两条硬指标：**单次完整检查 ≤ 30 分钟**、**支持 10 人并发**。

---

## 二、你在其中做什么

8 个人分 8 块，你负责其中一块。先看 [`docs/TEAM_TASKS.md`](docs/TEAM_TASKS.md) 找到你自己。

简单说：**平台骨架和标准已经搭好了，你往里面填检查项**。填一个检查项大约几十行代码，不用碰框架的其他部分。

---

## 三、一条缺陷是怎么被查出来的

这一节理解了，后面所有术语都能对上号。

假设工程师上传一个外壳模型，想知道壁厚够不够。

1. **读模型** — NX 把 `.prt` 拆开：3 个零件、32 个面，每个面的面积、半径、位置、包围盒都量出来。
2. **装进一个盒子** — 这些数字存成一个 JSON，叫 `ModelBundle`。**同一个模型只解析一次**，后面几十个检查项都读这一份，不再碰 NX。
3. **逐条规则去查** — 每个检查项对应一个 checker（就是一段代码）。最小壁厚那个 checker 从盒子里挑出所有平面，量出厚度，跟规则里的 0.8 mm 比。
4. **吐出统一格式的记录** — 薄了的地方变成一条 `Finding`：零件 P01、面 F40181、实测 0.62 mm、阈值 0.8 mm、差 −0.18 mm、建议加厚到 0.8。
5. **拼成报告** — 报告模块把所有 Finding 按检查项分组，配上 3D 定位图，导出 Word/PDF。

**你要写的，就是第 3 步里的那一个 checker。** 第 1、2 步是框架做的，第 4、5 步的格式也已经定好了，你照着填就行。

---

## 四、六个词，认识就够了

| 术语 | 大白话 | 你什么时候会碰到 |
|---|---|---|
| `ModelBundle` | 一个 JSON，装着模型的所有几何数据 | 你的 checker 从这里取面、取零件 |
| checker | 一个检查项的实现，就是一个类 | **你要写的** |
| `Finding` | 查出来的一条问题记录 | 你的 checker 产出它 |
| 规则库（`rules/*.json`） | 阈值配置表，多少算合格写这里 | 调阈值时改它，不用改代码 |
| 管线（pipeline） | 调度器，把注册好的 checker 挨个跑一遍 | 一般不用管 |
| 注册表（registry） | 自动发现"谁写了 checker"的名单 | 你导出 `CHECKERS` 就自动登记 |

其余名词（IEC 60664-1、爬电距离、拔模角……）在你自己那份任务说明里有解释。

---

## 五、三分钟跑起来

要求：**Python 3.12+，零第三方依赖**。没装 NX 也能开发。

```powershell
cd harting_drp

# 1) 体检：NX 在不在、插件能加载几个
python -m nxdrp doctor

# 2) 自检：契约 + 插件 + 管线 + Mock 全链路
python -m nxdrp selftest

# 3) 用 Mock 模型跑一次完整检查
python -m nxdrp check mockdata/models/board_a.model.json -r rules/dfm_default.json
```

第 3 步跑完应该看到 4 条 finding：2 条非标刀具、1 条圆角种类过多、1 条间隙偏小。

装了 NX 的机器再跑第 4 步：

```powershell
python -m nxdrp extract "C:\path\to\housing.prt" -o housing.model.json
```

首次约 30 秒（NX 要启动），之后走缓存，几十毫秒。

---

## 六、目录结构

```
harting_drp/
├── nxdrp/                      框架本体
│   ├── contracts/core.py       三份数据契约的定义
│   ├── catalog.py              44 个检查项的总目录（你的 ID 从这里来）
│   ├── checkers/base.py        你要继承的 BaseChecker
│   ├── checkers/examples/      3 个参考实现，照着改
│   ├── checkers/mX_xxx/        ★ 你的目录（进去先看 README）
│   ├── checkers/eval/          评测框架：标注集 → 匹配 → P/R/F1
│   ├── registry.py             插件发现
│   ├── pipeline.py             调度
│   ├── adapters/nx_batch.py    调本机 NX
│   └── journals/               在 NX 里跑的小脚本
├── rules/dfm_default.json      44 条规则的阈值
├── mockdata/
│   ├── models/                 三套评测场景 + Mock + 2 个真实 NX 零件
│   ├── labels/                 标注集（评测用）
│   └── scenes/                 场景的 .prt 原文件
├── tests/                      74 个单元测试
├── tools/                      生成骨架 / 规则 / Mock / 看板的小工具
├── contracts/schema/           三份 JSON Schema
└── docs/                       七份文档
```

进到自己的 checker 子包后先看那里的 `README.md`，写明了这个包负责哪几项、先做哪件。

---

## 七、常用命令

| 想干什么 | 命令 |
|---|---|
| 查我负责哪几项 | `python -m nxdrp items --owner M3` |
| 看我写的 checker 有没有被认出来 | `python -m nxdrp checkers` |
| 只跑我这一项，快 | `python -m nxdrp check 模型.json --only DFM-31` |
| 跑全量并出结果文件 | `python -m nxdrp check 模型.json -o out.json` |
| **给结果打分** | `python -m nxdrp eval out.json -l 标注集.json` |
| 解析一个新模型 | `python -m nxdrp extract a.prt -o a.json` |
| 跑测试 | `python -m unittest discover -s tests` |

---

## 八、现在有什么，还缺什么

**已经能用的，都在真模型上验证过**

| 能力 | 状态 |
|---|---|
| 调本机 NX 2606 读模型 | 3 个 NX 自带样例解析成功 |
| 几何数据提取（零件 / 面 / 边 / 面积 / 半径 / 包围盒 / 邻接） | 已验证 |
| **面法向 + 圆柱轴线**（拔模角、倒扣、转角类检查的前提） | Pressure Port 实测 13 个面（2 平面 / 7 B 曲面 / 3 圆柱 / 1 球面）全部带法向或轴向 |
| **批量精确测距**（`measure_distance`，一次 NX 启动测完所有配对） | 实测两对面：27.73 mm / 2.65 mm；无效 tag 优雅报错 |
| **装配结构解析**（组件展开 + 变换矩阵 + 装配坐标系） | 自建两零件装配实测：PART_B 位移 x=120 正确读出 |
| **三套评测场景**（混合 / 纯负样本 / 阈值边界） | `demo_asm` 6 组件 78 面出 5+18 条；`demo_normal` 零误报；`demo_edge` 只报 0.299 与 0.300，0.302 正确跳过 |
| **边长度 + 曲线类型** | demo_asm 114 条边全部带长度（13.98–30.32 mm），类型 72 直线 / 42 圆弧 |
| **精确测距代理**（NxDistanceProxy） | 批量预取 + 缓存，7 个单测；checker 不再逐对起 NX |
| **性能实测** | 312 面 33.5 s、检查 0.28 s；边际 5.6 ms/面（见 docs/PERF.md） |
| **评测框架**（标注集 → P/R/F1、macro-F1、高危项召回、误报率） | 三套场景共 32 条标注跑通，21 个单测覆盖 |
| 三份契约 + 校验 + 74 个单测 | 已验证 |
| 插件机制（内置目录 / 任意外部目录） | 外部放一个文件就能生效 |
| 检查管线（过滤、跳过、异常隔离、覆盖率） | 已验证 |
| 3 个参考 checker 在真模型上出结果 | 已验证 |
| 不装 NX、用 Mock 数据开发 | 已验证 |

**还缺的**

| 缺什么 | 影响 | 谁补 |
|---|---|---|
| 41 个检查项没实现 | 只有 3 个参考实现 | 8 个人分 |
| 标注集只有格式样例，没有人工标注 | 90% 准确率现在能算，但算的不是真数 | 8 个人边做边标 |

---

## 九、遇到问题查哪份文档

| 情况 | 看这份 |
|---|---|
| 不知道自己该干什么 | [`docs/TEAM_TASKS.md`](docs/TEAM_TASKS.md) |
| 想写第一个 checker | [`docs/HOW_TO_ADD_A_CHECKER.md`](docs/HOW_TO_ADD_A_CHECKER.md) |
| 想查数据里有哪些字段 | [`docs/CONTRACT.md`](docs/CONTRACT.md) |
| 要碰 NX 那一层 | [`docs/NX_ADAPTER.md`](docs/NX_ADAPTER.md) |
| 想知道自己准不准、怎么标 | [`docs/LABELING.md`](docs/LABELING.md) |
| 想找模型试手 / 看边界场景 | [`docs/DEMO_SCENE.md`](docs/DEMO_SCENE.md) |
| 想算性能预算 | [`docs/PERF.md`](docs/PERF.md) |

前两份先读，中间两份是工具书——**写 checker 时不用通读**，用到哪节查哪节。
后三份是「验证」环节的手册：写完不跑一遍，等于没写。
