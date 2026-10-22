# M8 报告生成与知识库（不放 checker）

**负责人**：赵文哲　　**目录**：`nxdrp/checkers/m8_report/`

## 这个模块在解决什么

报告是甲方唯一能直接拿到手的东西。前面 44 个检查项做得再好，报告看不懂、说不出所以然，这个项目就是没交付。

## 你负责的检查项

| ID | 名称 | 难度 | 期次 | 判定要点 |
|---|---|---|---|---|
| — | 本模块不提供 checker | — | — | 见 docs/TEAM_TASKS.md |

## 从哪开始

先出样张，再谈自动化。第 4 周前把 `mockdata` 跑出来的结果渲染成一份能给甲方看的报告。

## 三个命令

```powershell
python -m nxdrp checkers                                   # 确认自己被认出来了
python -m nxdrp check mockdata/models/board_a.model.json --only <你的ID>
python -m unittest discover -s tests
```

## 几个提醒

- 本目录不注册 checker，只放报告模板、渲染器与知识库。
- 报告只读 `nxdrp check` 产出的 findings.json，不要反向依赖 checker。

## 交之前自查

- [ ] 在 Mock 模型**和**至少一个真实 NX 模型上都跑出正确结果
- [ ] 每条结果带 `face_ids`，工程师能点回 3D 现场
- [ ] 建议能照着改（给目标尺寸或结构动作），不是「请注意检查」
- [ ] 阈值写在 `rules/` 里，代码里只有默认值
- [ ] 数据不够时跳过并说明缺什么，不产出假结果
- [ ] 正例 / 负例 / 边界三个测试都有

写法细节见 `docs/HOW_TO_ADD_A_CHECKER.md`。
