# M8 报告与知识库插件

此模块接收已有平台的统一检查结果，生成评审报告和知识归档，不提供检测算法，不注册 checker。公共契约、调度器、注册表与其他同学的目录均未修改。

## 1.1.0 验收补强

完整复盘见本目录“验收复盘.md”。当前新增：

- 每份归档包含 acceptance.json，逐条核对位置、偏差、严重程度、建议，列出 44 项结果位置。它检查数据完整性，不替代工程评审。
- image_evidence.json 记录截图与模型哈希、问题编号、面编号、坐标和来源的对应关系。
- Word 的 44 项索引支持内部链接；PDF 的 44 个索引链接定位到详情标题。
- 团队统一测试命令会自动执行 M8 测试；安装测试依赖：python -m pip install -r nxdrp/checkers/m8_report/requirements-test.txt。
- “评审前检查完整性”勾选后，数据不完整则停止生成；默认仍允许生成草稿以展示待补内容。
- 两份可查看和复现的样张位于本目录 samples/board_a 与 samples/plate_holes；包含原始输入、图片、Word/PDF/HTML、验收清单和完整归档，可直接验证。

```powershell
# 检查归档内容是否被损坏（包括下载 ZIP）
python -m nxdrp.checkers.m8_report verify nxdrp/checkers/m8_report/samples/plate_holes
# 检查验收数据；样张含未执行项，退出码 1 为如实提示，不是程序失败
python -m nxdrp.checkers.m8_report audit nxdrp/checkers/m8_report/samples/plate_holes
# 正式生成模式，只有数据完整时才成功
python -m nxdrp.checkers.m8_report generate findings.json --model model.json --rules rules/dfm_default.json --require-complete
```

M7 直接调用 generate_report 时可传 require_complete=True；返回前会检查数据完整性，失败不会留下半份归档。未提供数字目标时，允许保留具体结构动作并列为人工确认项，不自动编造尺寸。缺少实测、阈值、单位或有效严重程度，以及占位建议，均会阻止严格生成。

## 快速使用

在 harting_drp 目录双击“启动M8报告插件.cmd”。本机使用已具备依赖的 Codex Python；换电脑时安装 Python 3.12+ 并执行：

```powershell
python -m pip install -r nxdrp/checkers/m8_report/requirements.txt
python -m nxdrp.checkers.m8_report serve
```

打开 http://127.0.0.1:8768。选择“基础流程样例”或“离线三维模型样例”后点“运行示例”，可直接预览与下载报告。后者使用压缩包自带的 NX 导出几何与 STL，不代表本机重新执行了 NX。

自己的数据：选择平台输出的 findings.json，可附同一模型的 model.json、规则库 JSON 和截图，点“生成报告并归档”。截图支持 PNG/JPG，多选时文件名必须是问题编号，例如 DFM-31-0001.png。截图内容需由提交者确认是对应问题的三维现场。STL 必须与模型 JSON 使用相同坐标系和单位，当前自动渲染突出问题位置与包围盒，不能取代 NX 精确选面。

## 功能和验收对应

| 要求 | 已实现行为 |
|---|---|
| 结果归一 | 消费 CheckRun 对象、字典或 Finding 数组；保留原始输入，派生偏差不写回上游 |
| 每条问题说明位置 | 坐标、包围盒、零件和面编号，配问题图片；来源明确，缺失有提示 |
| 偏差量 | 展示实测、阈值、单位、偏差；无偏差且两值存在时按实测减阈值计算；源偏差冲突保留并告警 |
| 严重程度 | P0/P1/P2/P3 与对应中文说明、置信度 |
| 整改建议 | 优先原检测建议与 param_delta，缺建议时使用 44 项动作模板；不编造尺寸 |
| 四十四项结果位置 | HTML 锚点、PDF 书签、Word 的 §检查项编号；无问题项同样列出状态 |
| 报告模板 | HTML 自包含图片、PDF、可编辑 Word，共用同一份归一化结果 |
| 三维截图 | 导入真实三维截图，或从 STL 自动生成深度缓冲三维定位图；没有网格时明确显示包围盒示意 |
| 建议和知识库 | knowledge.json 覆盖全部 44 项，界面支持模板检索与历史问题检索 |
| 归档 | 独立版本目录、原始输入、模型/规则快照、截图、模板快照、报告与 SHA256 清单，支持 ZIP 下载和完整性校验 |

状态分别展示为发现问题、已执行无问题、已跳过、未纳入检查、执行失败、缺少数据、未执行、执行状态待确认。只有 results 中明确 status=ok 且不存在问题/数量冲突时，才能显示已执行无问题。Finding 数组无法证明所有检查已执行。

“完整性检查通过”仅表示数据完整，不等于工程合格。需所有项目均有已完成或有理由跳过的状态，所有问题具备必要证据且没有冲突警告。项目尚未实现的 41 项在样例中如实显示未执行。

## 命令行

```powershell
# 示例报告，HTML/Word/PDF 一次生成
python -m nxdrp.checkers.m8_report demo --out m8_archives
python -m nxdrp.checkers.m8_report demo --scene plate_holes --out m8_archives

# 消费真实检查结果
python -m nxdrp.checkers.m8_report generate findings.json --model model.json --rules rules/dfm_default.json --out m8_archives

# 添加真实截图或 STL
python -m nxdrp.checkers.m8_report generate findings.json --model model.json --screenshots shots.json --out m8_archives
python -m nxdrp.checkers.m8_report generate findings.json --model model.json --mesh model.stl --out m8_archives

# 仅导出 HTML（仍需 Pillow）
python -m nxdrp.checkers.m8_report generate findings.json --formats html

python -m nxdrp.checkers.m8_report list --query 圆角
python -m nxdrp.checkers.m8_report verify m8_archives/归档编号
```

shots.json 示例（路径相对映射文件）：

```json
{"DFM-31-0001": "screenshots/DFM-31-0001.png"}
```

## M7 直接调用接口

建议平台在已有检查任务结束后直接调用 Python 接口，不需要启动第二套 Web 服务：

```python
from nxdrp.checkers.m8_report import generate_report

artifact = generate_report(
    check_run,                         # CheckRun 或 check_run.to_dict()
    output_root="m8_archives",          # 调用方控制归档目录
    model=model_bundle,                # ModelBundle 或 dict，可省略
    rules=rulebook,                     # RuleBook 或 dict，可省略
    screenshots={"DFM-31-0001": "shots/DFM-31-0001.png"},
    # mesh="model.stl",                # 可选；同模型同坐标系 STL
    title="连接器设计检查报告",
    formats=("html", "pdf", "docx"),
)
# 返回 report_id / directory / summary / files。
# 对应任务保存 artifact，提供 report.html、report.pdf、report.docx、archive.zip 下载。
```

历史接口：service.list_archives(root, query, severity, item)、search_cases(root, query, severity, item)、verify_archive(directory)。数据格式与例子可直接查看归档中的 report.json。

本地 HTTP 接口：GET /api/info、/api/knowledge?q=、/api/archives?q=&severity=&item=、/api/cases?q=&severity=&item=；POST /api/generate、/api/demo、/api/verify。写接口需要本地页面中的 X-M8-Token，监听地址固定 127.0.0.1，不用于外网部署。M7 优先调用上面的 Python 接口。

POST /api/generate 请求结构：findings（结果对象或数组）、model（模型对象，可选）、rules（规则对象，可选）、title、screenshots（数组，每项 finding_id/base64）、mesh_base64（可选）。单次请求上限 32 MB。下载地址为 /reports/{report_id}/report.html 等。

## 修改模板和建议

HTML 模板：render.py；PDF/Word：export.py；业务动作模板：knowledge.json。新增或修订动作后更新 version。不要在模板中填写未经确认的尺寸阈值，不要将建议动作当成检测结论。已归档报告保存当次模板快照，不会随未来修改改变。

## 验证与已知边界

```powershell
python -m unittest discover -s tests
# M8 测试额外需要 pypdf：python -m pip install pypdf
python -m unittest nxdrp.checkers.m8_report.test_m8 -v
```

现有 74 项测试（1 项跳过）及新增 26 项 M8 测试通过。检查了零值、边界偏差、缺数据、重复编号、偏差冲突、模型错配、目录定位、三种导出、截图/网格、事务回滚、HTML 转义、归档检索与篡改检测。报告已渲染检查，Web 页面完成示例生成、检索和归档操作检查。

本机未找到 NX，尚未完成“在本机 NX 新解析模型 → 完整检测 → 报告”的现场联调。当前离线三维示例使用随包的 NX 几何快照与 STL。最终验收需接入各模块真实结果，完成全部检查项并补齐上游缺失证据。

归档以文件系统保存，适合本地演示和 M7 嵌入调用；不包含多用户权限管理和数据库。SHA256 用于内容一致性检查，不提供数字签名或防恶意篡改保证。STL 不带面编号，自动定位图突出坐标和包围盒；精确面高亮需 M7/NX 提供截图。

补充验证边界：1.0 界面已完成实际操作检查；1.1 新增控件的浏览器复核因自动审批额度不足未执行，当前以静态检查、服务接口和自动测试验证为准，需人工打开页面补一次确认。

启动位置说明：模块合并包只包含 M8 功能，解压后不能作为完整平台单独运行。请将 nxdrp 与 tests 按原目录名合并到 HaoTing 仓库根目录，再使用仓库根目录的启动文件；需要独立演示时使用完整交付包中的 harting_drp。启动器会先检查公共平台文件是否齐全。
