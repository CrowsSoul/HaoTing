# M7 Web 平台

负责人：陈卉妍。所有新增代码和依赖位于本目录，未修改公共契约、管线、适配器和其他成员模块。M7 不注册 checker。

## 快速启动

要求 Python 3.12+、Node.js 20.19+ 或 22.12+。从仓库根目录执行：

```powershell
# 首次安装、构建并启动
.\nxdrp\checkers\m7_platform_web\start.ps1 -Install

# 当前开发环境已经安装并构建，以后直接运行
.\nxdrp\checkers\m7_platform_web\start.ps1
```

打开 http://127.0.0.1:8000 。接口说明：http://127.0.0.1:8000/docs 。Ctrl+C 停止服务。

若 PowerShell 不允许执行脚本，可直接启动（已安装依赖并构建后）：

```powershell
.\nxdrp\checkers\m7_platform_web\.venv\Scripts\python.exe -m nxdrp.checkers.m7_platform_web
```

不要使用多个 Uvicorn 进程。同一数据目录有进程锁，重复启动会被拒绝。`--workers` 指后台任务线程，不是 HTTP 服务进程。默认仅监听本机；当前版本没有用户登录和权限体系，用于本地演示和集成。面向团队网络部署前需接入认证和访问控制。

## 演示步骤

1. 模型检查页面选择 `board_a.model.json`，保留默认规则，不勾选检查项表示运行所有已接入项目。
2. 点击“开始检查”，任务进入后台；完成后应显示 4 条缺陷，包含 DFM-02、DFM-31、DFM-32。
3. 点击缺陷，查看位置、面 ID、实测值、阈值、偏差、修改建议和 3D 包围盒定位。部分示例 Finding 没有面 ID，页面会明确显示“未提供”。
4. 点击“下载报告”获取独立 HTML 报告；也可下载结果 JSON 和规则快照。HTML 可在浏览器打印为 PDF，这不等同于 M8 原生 PDF 报告。
5. 打开规则配置，搜索 DFM-02，把 `min_clearance_mm` 从 0.3 改为 0，保存为新版本。
6. 用新版本再次检查同一模型，应得到 3 条缺陷；原任务仍保持 4 条，规则快照保持原值。
7. 可选择 `pressure_port.model.json` 等仓库已有的真实 NX 导出数据验证，不需要本机安装 NX。

刷新页面和重启服务后任务记录仍存在。服务重启时，未完成检查和报告会标记为中断，可以重新提交。

## 功能与依赖边界

| 功能 | 当前情况 |
|---|---|
| JSON / 单零件 PRT 上传 | 已实现，模型文件最大 100 MB，生成独立存储路径 |
| 检查执行 | 直接调用现有 Python 管线，自动发现新增 checker |
| 队列与进度 | 持久化任务、有限队列、阶段与当前检查项、失败原因 |
| 并发 | 默认 4 个后台线程、1 个 NX 槽位、最多 100 个待处理任务 |
| 规则编辑 | 数字、文本、布尔、数字列表表单，启停规则、严重度、新版本保存 |
| 规则追溯 | 每个任务独立保存提交时的规则快照 |
| 结果展示 | 缺陷搜索、严重度筛选、执行明细、未实现项目清单 |
| 3D 区域定位 | 零件/缺陷包围盒、位置点和路径，明确标注示意模式 |
| 精确面高亮 | 支持附加 face_id 网格并显示；真实 NX 网格需公共适配层提供 |
| 报告 | 独立 HTML 和 JSON 可用；M8 的 PDF/DOCX 通过生成器接入 |
| 真实 NX 解析 | 已接适配器和精确测距代理；本机未检测到 NX，PRT 未完成实测 |

“已完成”表示管线执行结束；单项仍可能 error、missing_data、skipped、filtered。页面和报告单独列出，未实现项目不会显示为通过。

PRT 上传目前支持单零件。装配文件的引用子零件不会随上传自动传输；装配演示先用完整导出的 ModelBundle。装配包上传需与 NX 负责人另行约定引用与打包方式。

## 目录

```text
m7_platform_web/
├── __main__.py                 命令入口
├── backend/_server.py          HTTP 接口和静态资源
├── backend/_service.py         SQLite、队列、快照、管线、报告适配
├── frontend/src/App.vue        检查与规则页面
├── frontend/src/Viewer.vue     Three.js 视图
├── frontend/src/generated/     自动生成的 TypeScript 契约
├── contracts/                  本模块导出的基础和补充 Schema
├── generate_types.py           从公共数据类生成类型与 Schema
├── tests/test_web.py           后端集成测试
├── requirements.lock.txt       已验证的 Python 依赖版本
├── start.ps1                   安装、构建、启动
└── runtime/                    SQLite、上传、快照、结果、缓存（不提交）
```

后端实现文件以 `_` 开头，避免公共插件发现逻辑导入 FastAPI 等可选依赖；公共自检和测试可继续使用原来的零依赖 Python 环境。

## 开发与类型生成

```powershell
# 终端一：仓库根目录
.\nxdrp\checkers\m7_platform_web\.venv\Scripts\python.exe -m nxdrp.checkers.m7_platform_web

# 终端二
cd nxdrp/checkers/m7_platform_web/frontend
npm ci
npm run dev
# 访问 http://127.0.0.1:5173，API 代理至 8000

# 修改后构建
npm run build
```

构建先生成类型，再执行 TypeScript 检查和 Vite 构建。普通 `python` 仅用于运行无依赖类型生成器。

基础三份 Schema 导出至本模块 `contracts/`。公共 Schema 缺少 bbox、path_points、详细 evidence 等字段，补充 Schema 和前端类型由公共 Python 数据类自动推导，覆盖 ModelBundle、RuleBook、Finding、CheckRun、Task、DisplayMesh，没有擅自修改公共契约。HTTP 参数 Schema 可在 `/openapi.json` 查看。

Python 精确版本安装：

```powershell
.\nxdrp\checkers\m7_platform_web\.venv\Scripts\python.exe -m pip install -r nxdrp/checkers/m7_platform_web/requirements.lock.txt
```

## HTTP 接口

| 方法与路径 | 用途 |
|---|---|
| GET `/api/health` | NX、线程、槽位、报告接入状态 |
| GET `/api/catalog` | 实现覆盖率与检查项目录 |
| GET `/api/samples` | 示例模型 |
| POST `/api/samples/{name}` | 导入白名单示例 |
| POST `/api/models` | multipart，字段名 `file` |
| GET / POST `/api/rulebooks` | 获取 / 保存独立规则版本 |
| POST `/api/tasks` | `{model_id, rulebook_id, only: []}`，立即返回任务 |
| GET `/api/tasks`、`/api/tasks/{id}` | 列表与状态 |
| GET `/api/tasks/{id}/result`、`/model` | CheckRun、解析模型 |
| GET `/api/tasks/{id}/rules`、`/download` | 下载快照、结果 JSON |
| GET / POST `/api/tasks/{id}/mesh` | 获取 / 附加网格 |
| GET `/api/tasks/{id}/reports/html` | 下载 HTML 报告 |
| POST `/api/tasks/{id}/reports/{pdf或docx}` | 调用 M8 生成器 |
| GET `/api/tasks/{id}/reports/{pdf或docx}` | 下载 M8 报告 |

状态：queued → extracting → checking → completed / failed。PRT 等待槽位时为 waiting_nx。JSON 不进入 NX；缺少 NX 时 PRT 明确失败。解析不显示虚假百分比，检查只显示已处理数和当前项目。

## NX 网格接入约定

NX 负责人输出独立 JSON，用户在任务详情“附加显示网格”，或调用 mesh 接口：

```json
{
  "units": "mm",
  "coordinate_space": "assembly",
  "vertices": [[0,0,0], [1,0,0], [0,1,0]],
  "triangles": [[0,1,2]],
  "face_ids": ["替换为当前模型中实际存在的面ID"]
}
```

此示例仅说明格式，不代表真实几何。三角形索引从 0 开始，每个三角形对应一个 face_id；坐标已转为装配全局坐标，单位与模型一致，前端不再应用 occurrence 变换。限制 20 万顶点、40 万三角形；网页附件限 30 MB。服务拒绝未知面、越界索引、非有限坐标和不一致单位。需核对模型版本，不能仅凭面 ID 相同认定几何一致。

有网格时按 Finding.evidence.face_ids 高亮；无网格时仅显示包围盒区域。M7 显式配置 `NxConfig(max_concurrency=...)`，不依赖适配器当前环境变量读取行为；完整 NX 任务（包括精确测距）共享槽位限制。

## M8 报告接入约定

M8 提供函数：

```python
def generate_report(*, result: dict, model: dict, rulebook: dict, output_path: str):
    # 后缀为 .pdf 或 .docx，生成非空文件。
    # result 是 CheckRun.to_dict()，rulebook 是任务提交快照。
    ...
```

启动前配置（替换成 M8 实际提供的模块）：

```powershell
$env:M7_REPORT_PROVIDER = 'nxdrp.checkers.m8_report.reporter:generate_report'
.\nxdrp\checkers\m7_platform_web\start.ps1
```

未配置时网页仅显示可用的 HTML 下载；配置后显示 PDF/Word 按钮。失败保留检查结果，单独记录 report_error。生成器在服务线程池执行，不阻塞事件循环；网页请求完成后开始下载。

## 验证

```powershell
# 仓库根目录
python -m unittest discover -s tests
.\nxdrp\checkers\m7_platform_web\.venv\Scripts\python.exe -m unittest discover -s nxdrp/checkers/m7_platform_web/tests -v

cd nxdrp/checkers/m7_platform_web/frontend
npm test
npm run build
```

2026-10-22：公共测试 74 项，1 项因无 NX 跳过，其余通过；M7 后端 10 项、前端组件交互 2 项通过；TypeScript 和生产构建通过。

覆盖：真实管线 4 条缺陷、改规则后 3 条与历史快照不变、0.15 mm 阈值、10 客户端并发上传/提交/查询且结果不混用、队列满拒绝、NX 缺失隔离、模拟 NX 槽位、独占与重启恢复、真实 NX 导出数据、网格映射校验、M8 适配协议。

并发验证针对本地 API 和 Mock/已导出模型，不等于 10 个真实 NX 同时运行的性能验收。当前无可用浏览器自动化连接，页面交互使用 happy-dom 验证，未进行实际浏览器视觉验收和 WebGL 截图。目标机仍需补做 PRT、真实显示网格、M8 正式报告及浏览器联调。
