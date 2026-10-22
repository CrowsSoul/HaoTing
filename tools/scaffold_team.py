# -*- coding: utf-8 -*-
"""生成 / 刷新 8 人插件子包骨架。

用法：
    python -m tools.scaffold_team            # 只补缺失的文件，已有文件不覆盖
    python -m tools.scaffold_team --force    # 连 README 一起重写（__init__.py 里已写的代码不会动）

设计意图：新人加入时只要能跑这一条命令，就能拿到自己那份「空但可运行」的目录，
里面已经写好了他该实现哪些 check_item_id、去哪看文档、怎么自测。
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nxdrp import catalog  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER_ROOT = os.path.join(ROOT, "nxdrp", "checkers")

TEAM = [
    {
        "pkg": "m2_safety",
        "module": "M2",
        "owner": "宋馨雨",
        "title": "智能安规检查（自研算法）",
        "problem": "连接器里两个带电部件离得太近，电压高的时候会击穿空气打火。\n"
                   "要自己算出所有导体配对之间的最短距离（电气间隙），以及沿绝缘表面走的最短路径（爬电距离），"
                   "对照 IEC 60664-1 的限值判定。另外装一个 AutoCrear，用它算出来的结果给自研算法做对照。",
        "guide": "先做 SAF-01 电气间隙——本质是两点距离，几何上有标准解法，把链路打通。\n"
                 "再攻 SAF-02 爬电距离——沿绝缘件曲面找最短路，这是全项目唯一需要科研攻关的地方。\n"
                 "同时把 AutoCrear 装起来，能独立跑出一次爬电结果，后面拿它当基准。",
        "notes": [
            "IEC 限值表放 `rules/`，每条注明标准表号，不要写进代码。",
            "AutoCrear 装好之后，先拿同一个模型跑一遍，把它的结果存下来当对照样例。",
            "爬电距离第 5 周（按两周节奏就是第 5 天）必须有一个能跑的 v0.1，跑不出来就启动降级方案。",
        ],
    },
    {
        "pkg": "m3_injection",
        "module": "M3",
        "owner": "代世航",
        "title": "注塑 / 铸造类 DFM",
        "problem": "塑料件设计出来，模具不一定做得出来：壁太薄注不满、壁厚不均会缩水、"
                   "拔模角不够会拉伤、有倒扣模具拔不出来。开一次模几十万，改设计不要钱——"
                   "这 11 项检查就是在开模之前把这些坑找出来。",
        "guide": "先做壁厚三件套（DFM-08 / 09 / 10），这一组是整块的地基。",
        "notes": [
            "拔模角、倒扣这类要面法向的项，M1 还没交付；先写算法骨架并声明 `requires=(\"normals\",)`，框架会跳过不会算错。",
            "「碎面与微小特征黑名单」要和 M4 / M6 共用，统一放 `rules/` 下。",
        ],
    },
    {
        "pkg": "m4_assembly",
        "module": "M4",
        "owner": "汪琪俊",
        "title": "装配类 DFM",
        "problem": "零件单看都没问题，装到一起就出事：两个件撞在一起（干涉）、孔对不上、"
                   "扳手伸不进去。这 7 项检查在装配层面找这些毛病。",
        "guide": "先做 DFM-02 最小间隙，把多零件遍历跑通；再做 DFM-01 干涉。",
        "notes": [
            "甲方对误报极敏感：报三次假的，他就不信这个平台了。工作量有一半在「过滤掉不该报的」。",
            "精确干涉体积必须回 NX 算，包围盒只能做预筛。",
        ],
    },
    {
        "pkg": "m5_performance",
        "module": "M5",
        "owner": "杜滨芳",
        "title": "智能性能预测",
        "problem": "载流能力、温升这些性能，现在只能靠算、靠经验、靠做样品试。"
                   "要训练一个模型，让工程师在设计阶段就能问：这个端子过 16 A，会热到多少度？",
        "guide": "第一周只做选型，别急着写模型。样本量只有几百条，难点在数据不在算法。",
        "notes": [
            "用 NX 参数化批量仿真造 ≥300 条样本——这是本项目最大的底牌，别浪费。",
            "结果要给区间，不要只给一个数；模型卡写清适用什么范围、超出范围为什么不能用。",
        ],
    },
    {
        "pkg": "m6a_sheet_metal",
        "module": "M6A",
        "owner": "于大淇",
        "title": "钣金类 DFM（8 项）",
        "problem": "钣金件折弯会裂、冲孔离板边太近会撕裂、翻边太高会拉断。\n"
                   "这 8 项就是在出图之前，把「做不出来或者做出来很贵」的地方标出来。",
        "guide": "这 8 项几乎都是同一个套路：量一个尺寸，除以料厚，跟经验比值比。\n"
                 "先搭一套读表执行的代码，再把 8 行阈值填进去。",
        "notes": [
            "料厚从 `ModelBundle.parts[].bbox` 或零件属性里取，取不到就声明 `requires` 并跳过。",
            "标准比值放 `rules/dfm_default.json` 的 DFM-19~26 段，不要写死在代码里。",
        ],
    },
    {
        "pkg": "m6b_machining",
        "module": "M6",
        "owner": "张百瑞",
        "title": "机加工类 DFM（12 项）",
        "problem": "孔太深钻头会断、圆角太小刀具进不去、孔径不在标准刀具系列还得定制刀。\n"
                   "这 12 项把「加工做不出来或者成本高」的地方标出来。",
        "guide": "同样是一套读表执行的代码 + 12 行阈值。\n"
                 "DFM-31/32 已有完整示例，照着往下铺。",
        "notes": [
            "标准刀具库放 `rules/tool_library.json`，不要写死在 checker 里。",
            "DFM-30 刀具可达性、DFM-37 窄通道要算空间遮挡，难度高一个量级，排二期。",
        ],
    },
    {
        "pkg": "m7_platform_web",
        "module": "M7",
        "owner": "陈卉妍",
        "title": "平台 Web 交互与服务（不放 checker）",
        "problem": "甲方评审时 90% 的时间在看界面。工程师打开网页，上传模型、点开始、看进度、"
                   "看 3D 上标红的缺陷、下载报告——这条主流程就是你要交付的东西。",
        "guide": "第一周就用 `mockdata/` 里的模型把「上传 → 任务 → 进度 → 报告」跑起来，别等后端。",
        "notes": [
            "本目录不注册 checker，只放 Web、网关、任务调度的代码与配置。",
            "规则配置界面必须让工程师不写代码就能改——这是合同指标，不是偏好。",
        ],
    },
    {
        "pkg": "m8_report",
        "module": "M8",
        "owner": "赵文哲",
        "title": "报告生成与知识库（不放 checker）",
        "problem": "报告是甲方唯一能直接拿到手的东西。前面 44 个检查项做得再好，"
                   "报告看不懂、说不出所以然，这个项目就是没交付。",
        "guide": "先出样张，再谈自动化。第 4 周前把 `mockdata` 跑出来的结果渲染成一份能给甲方看的报告。",
        "notes": [
            "本目录不注册 checker，只放报告模板、渲染器与知识库。",
            "报告只读 `nxdrp check` 产出的 findings.json，不要反向依赖 checker。",
        ],
    },
]

INIT_TEMPLATE = '''# -*- coding: utf-8 -*-
"""{module} {title} —— 负责人：{owner}

本包由 tools/scaffold_team.py 生成。往下面导出你的 checker：

    from .my_checker import MyChecker
    CHECKERS = [MyChecker()]

导出后框架自动发现，不用改任何核心文件。
写法见 docs/HOW_TO_ADD_A_CHECKER.md
"""

# 还没写 checker 时保持空列表，框架不会报错。
CHECKERS = []
'''

README_TEMPLATE = """# {module} {title}

**负责人**：{owner}　　**目录**：`nxdrp/checkers/{pkg}/`

## 这个模块在解决什么

{problem}

## 你负责的检查项

| ID | 名称 | 难度 | 期次 | 判定要点 |
|---|---|---|---|---|
{rows}

## 从哪开始

{guide}

## 三个命令

```powershell
python -m nxdrp checkers                                   # 确认自己被认出来了
python -m nxdrp check mockdata/models/board_a.model.json --only <你的ID>
python -m unittest discover -s tests
```

## 几个提醒

{notes}

## 交之前自查

- [ ] 在 Mock 模型**和**至少一个真实 NX 模型上都跑出正确结果
- [ ] 每条结果带 `face_ids`，工程师能点回 3D 现场
- [ ] 建议能照着改（给目标尺寸或结构动作），不是「请注意检查」
- [ ] 阈值写在 `rules/` 里，代码里只有默认值
- [ ] 数据不够时跳过并说明缺什么，不产出假结果
- [ ] 正例 / 负例 / 边界三个测试都有

写法细节见 `docs/HOW_TO_ADD_A_CHECKER.md`。
"""


def render_rows(module: str) -> str:
    items = catalog.by_owner(module)
    if not items:
        return "| — | 本模块不提供 checker | — | — | 见 docs/TEAM_TASKS.md |"
    return "\n".join(
        f"| `{i.check_item_id}` | {i.name_cn} | {i.difficulty} | {i.phase} | {i.hint} |" for i in items
    )


def write_if(path: str, content: str, force: bool = False) -> str:
    if os.path.isfile(path) and not force:
        return "skip"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return "write"


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成 8 人插件子包骨架")
    ap.add_argument("--force", action="store_true", help="覆盖已有的 README.md")
    args = ap.parse_args(argv)

    for t in TEAM:
        d = os.path.join(CHECKER_ROOT, t["pkg"])
        init_path = os.path.join(d, "__init__.py")
        readme_path = os.path.join(d, "README.md")

        if not os.path.isfile(init_path):
            write_if(init_path, INIT_TEMPLATE.format(**t))
            print(f"  创建 {t['pkg']}/__init__.py")
        elif "CHECKERS = []" not in open(init_path, encoding="utf-8").read() and "CHECKERS" not in open(
            init_path, encoding="utf-8"
        ).read():
            print(f"  跳过 {t['pkg']}/__init__.py（已有内容，未改动）")

        notes = "\n".join(f"- {n}" for n in t["notes"])
        content = README_TEMPLATE.format(
            module=t["module"], title=t["title"], owner=t["owner"], pkg=t["pkg"],
            problem=t["problem"], rows=render_rows(t["module"]), guide=t["guide"], notes=notes,
        )
        write_if(readme_path, content, force=args.force)
        print(f"  {t['pkg']}: {len(catalog.by_owner(t['module']))} 个检查项")

    print("\n完成。已生成目录：", CHECKER_ROOT)


if __name__ == "__main__":
    main()
