# M7 平台 Web 交互与服务（不放 checker）

**负责人**：陈卉妍　　**目录**：`nxdrp/checkers/m7_platform_web/`

## 这个模块在解决什么

甲方评审时 90% 的时间在看界面。工程师打开网页，上传模型、点开始、看进度、看 3D 上标红的缺陷、下载报告——这条主流程就是你要交付的东西。

## 你负责的检查项

| ID | 名称 | 难度 | 期次 | 判定要点 |
|---|---|---|---|---|
| — | 本模块不提供 checker | — | — | 见 docs/TEAM_TASKS.md |

## 从哪开始

第一周就用 `mockdata/` 里的模型把「上传 → 任务 → 进度 → 报告」跑起来，别等后端。

## 三个命令

```powershell
python -m nxdrp checkers                                   # 确认自己被认出来了
python -m nxdrp check mockdata/models/board_a.model.json --only <你的ID>
python -m unittest discover -s tests
```

## 几个提醒

- 本目录不注册 checker，只放 Web、网关、任务调度的代码与配置。
- 规则配置界面必须让工程师不写代码就能改——这是合同指标，不是偏好。

## 交之前自查

- [ ] 在 Mock 模型**和**至少一个真实 NX 模型上都跑出正确结果
- [ ] 每条结果带 `face_ids`，工程师能点回 3D 现场
- [ ] 建议能照着改（给目标尺寸或结构动作），不是「请注意检查」
- [ ] 阈值写在 `rules/` 里，代码里只有默认值
- [ ] 数据不够时跳过并说明缺什么，不产出假结果
- [ ] 正例 / 负例 / 边界三个测试都有

写法细节见 `docs/HOW_TO_ADD_A_CHECKER.md`。
