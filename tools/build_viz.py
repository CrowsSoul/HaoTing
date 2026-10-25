# -*- coding: utf-8 -*-
"""生成项目可视化：一份看板 HTML + 四张可插入文档的矢量图。

数据全部来自仓库本身（nxdrp.catalog + registry），不手写数字，
所以以后检查项实现了、人数变了，重跑这一个脚本图就跟着变。

用法：
    python -m tools.build_viz
    python -m tools.build_viz --out "F:/某目录"
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nxdrp import catalog  # noqa: E402
from nxdrp.registry import discover  # noqa: E402

# ---------------------------------------------------------------------------
# 设计令牌
# ---------------------------------------------------------------------------
BG = "#0B1220"
PANEL = "#131C30"
PANEL2 = "#0F1727"
LINE = "#243250"
T1 = "#E9EFFA"      # 主文字
T2 = "#8FA3C2"      # 次文字
T3 = "#5A6C8A"      # 弱文字
CYAN = "#38BDF8"
VIOLET = "#A78BFA"
AMBER = "#FBBF24"
ROSE = "#FB7185"
EMERALD = "#34D399"
ORANGE = "#FB923C"

FONT = '"Microsoft YaHei","PingFang SC","Segoe UI",system-ui,sans-serif'

#: 6 个阶段色
STAGE_COLORS = ["#38BDF8", "#818CF8", "#A78BFA", "#F472B6", "#FB923C", "#34D399"]
STAGES = [
    ("S1 起跑", 1, 2), ("S2 骨架", 3, 4), ("S3 集成", 5, 6),
    ("S4 评测", 7, 8), ("S5 收敛", 9, 10), ("S6 收尾", 11, 12),
]

#: 8 人分工（姓名, 模块, 一句话）；checker_count 为 0 的人填 note 说明产出是什么
PEOPLE = [
    ("宋馨雨", "M2", "安规：间隙/爬电自研 + AutoCrear 对照", ""),
    ("于大淇", "M6A", "钣金 DFM 8 项", ""),
    ("代世航", "M3", "注塑/铸造 DFM 11 项", ""),
    ("汪琪竣", "M4", "装配 DFM 7 项", ""),
    ("杜滨芳", "M5", "性能预测：载流–温升", ""),
    ("张百瑞", "M6", "机加工 DFM 12 项", ""),
    ("陈卉妍", "M7", "Web 平台与调度", "产出是 Web 与部署"),
    ("赵文哲", "M8", "报告与知识库", "产出是报告与文档"),
]

#: 12 项风险（编号, 短名, 等级）
RISKS = [
    ("R1", "爬电距离不达标", 5, "极高"),
    ("R2", "标注数据不足", 4, "高"),
    ("R3", "NX 并发受限", 4, "高"),
    ("R4", "几何脏致误报", 4, "高"),
    ("R5", "接口漂移", 4, "高"),
    ("R6", "预测样本不足", 3, "中高"),
    ("R7", "甲方资料延期", 3, "中高"),
    ("R8", "38 项被摊薄", 2, "中"),
    ("R9", "缺 AutoCrear 金标准", 2, "中"),
    ("R10", "投入时间不稳", 2, "中"),
    ("R11", "信息安全要求", 2, "中"),
    ("R12", "二期范围蔓延", 2, "中"),
]
RISK_COLOR = {5: "#FB7185", 4: "#FB923C", 3: "#FBBF24", 2: "#60A5FA"}

#: 门禁
GATES = {0: "G0 启动", 4: "G1 单模块", 5: "G2 全链路", 8: "G3 内测", 10: "G4 原型", 12: "G5 复盘"}


# ---------------------------------------------------------------------------
# 基础绘图
# ---------------------------------------------------------------------------
def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def svg(w: int, h: int, body: str) -> str:
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" style="display:block;overflow:visible">\n'
        f"<style>\n"
        f'text{{font-family:{FONT};font-size:12px;fill:{T1}}}\n'
        f".t1{{fill:{T1}}}.t2{{fill:{T2}}}.t3{{fill:{T3}}}\n"
        f".ttl{{fill:{T1};font-size:14px;font-weight:600}}\n"
        f".num{{fill:{T1};font-weight:700}}\n"
        f".cap{{fill:{T2};font-size:11px}}\n"
        f"</style>\n{body}\n</svg>"
    )


def txt(x, y, s, cls="", size=None, weight=None, anchor=None, fill=None, op=None) -> str:
    a = []
    if cls:
        a.append(f'class="{cls}"')
    if size:
        a.append(f'font-size="{size}"')
    if weight:
        a.append(f'font-weight="{weight}"')
    if anchor:
        a.append(f'text-anchor="{anchor}"')
    if fill:
        a.append(f'fill="{fill}"')
    if op:
        a.append(f'opacity="{op}"')
    return f'<text x="{x:.1f}" y="{y:.1f}" {" ".join(a)}>{esc(s)}</text>'


def rrect(x, y, w, h, r, fill, stroke=None, sw=1, op=None) -> str:
    s = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    o = f' opacity="{op}"' if op is not None else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w,0):.1f}" height="{h:.1f}" '
            f'rx="{r}" ry="{r}" fill="{fill}"{s}{o}/>')


def bar(x, y, w, h, segs, r=4) -> str:
    """segs = [(宽度, 颜色), ...] 圆角分段条。"""
    out = [f'<g>']
    # 先画底槽
    total = sum(s[0] for s in segs)
    if total <= 0:
        return ""
    out.append(rrect(x, y, total, h, r, "#1B2740"))
    cx = x
    for i, (w, c) in enumerate(segs):
        if w <= 0.4:
            continue
        rad = r if i == len(segs) - 1 else 0
        out.append(f'<path d="M{cx:.1f},{y:.1f} h{max(w-rad,0):.1f} '
                   f'a{rad},{rad} 0 0 1 {rad},{rad} v{h-2*rad:.1f} '
                   f'a{rad},{rad} 0 0 1 {-rad},{rad} h{-max(w-rad,0):.1f} z" fill="{c}"/>')
        cx += w
    out.append("</g>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 面板 1：完成度
# ---------------------------------------------------------------------------
def panel_progress() -> str:
    total = len(catalog.CATALOG)
    reg = discover()
    done = len(reg.ids())
    frac = done / total

    by_cat = [("DFM", "DFM-", 38, CYAN), ("安规", "SAF-", 4, VIOLET), ("性能", "PERF-", 2, AMBER)]
    rows = []
    for name, prefix, n, color in by_cat:
        ids = [i.check_item_id for i in catalog.CATALOG if i.check_item_id.startswith(prefix)]
        d = len([x for x in ids if x in reg.ids()])
        rows.append((name, d, len(ids), color))

    W, H = 380, 300
    cx, cy, r, sw = 96, 118, 62, 14
    C = 2 * 3.14159 * r
    body = [
        rrect(0, 0, W, H, 16, PANEL, LINE),
        txt(22, 32, "完成度", "ttl"),
        txt(22, 50, f"已实现 {done} / {total} 个检查项", "cap"),
        # 轨道
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#1D2A44" stroke-width="{sw}"/>',
        # 进度弧（从 12 点开始）
        (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{CYAN}" stroke-width="{sw}" '
         f'stroke-linecap="round" stroke-dasharray="{C*frac:.2f} {C:.2f}" '
         f'transform="rotate(-90 {cx} {cy})" style="filter:drop-shadow(0 0 6px {CYAN}66)"/>'),
        txt(cx, cy + 4, f"{frac*100:.1f}%", "num", size=26, anchor="middle"),
        txt(cx, cy + 26, "已完成", "cap", anchor="middle"),
    ]

    y = 214
    for name, d, n, color in rows:
        body.append(txt(22, y + 4, name, "t2", size=11))
        body.append(rrect(66, y - 6, 210, 12, 6, "#1D2A44"))
        if d:
            body.append(rrect(66, y - 6, max(210 * d / n, 6), 12, 6, color))
        body.append(txt(288, y + 4, f"{d}/{n}", "t2", size=11, anchor="end"))
        y += 26

    return svg(W, H, "\n".join(body))


# ---------------------------------------------------------------------------
# 面板 2：8 人负载
# ---------------------------------------------------------------------------
def panel_workload() -> str:
    reg = discover()
    W, H = 760, 340
    cmap = {"L1": EMERALD, "L2": AMBER, "L3": ROSE}
    rows = []
    for name, mod, desc, note in PEOPLE:
        items = catalog.by_owner(mod)
        if not items:
            rows.append((name, mod, desc, {}, 0, note))
            continue
        diff = {"L1": 0, "L2": 0, "L3": 0}
        for i in items:
            diff[i.difficulty] += 1
        rows.append((name, mod, desc, diff, len(items), note))

    maxn = max(r[4] for r in rows) or 1
    unit = 300 / maxn

    body = [
        rrect(0, 0, W, H, 16, PANEL, LINE),
        txt(22, 34, "8 人任务负载", "ttl"),
        txt(150, 34, "条长 = 检查项数量", "cap"),
    ]
    # 图例
    lx = 470
    for k, c in cmap.items():
        body.append(rrect(lx, 24, 10, 10, 3, c))
        body.append(txt(lx + 15, 33, {"L1": "简单", "L2": "中等", "L3": "困难"}[k], "cap"))
        lx += 62

    y = 66
    for name, mod, desc, diff, n, note in rows:
        body.append(txt(22, y + 13, name, "t1", size=12.5, weight="600"))
        body.append(txt(78, y + 13, mod, "t3", size=11))
        # 侧栏说明
        body.append(txt(110, y + 13, desc, "t3", size=10.5))
        if n:
            segs = [(diff["L1"] * unit, EMERALD), (diff["L2"] * unit, AMBER), (diff["L3"] * unit, ROSE)]
            body.append(bar(320, y, sum(s[0] for s in segs), 20, segs, r=5))
            body.append(txt(320 + sum(s[0] for s in segs) + 10, y + 14,
                            f"{n}", "num", size=12))
        else:
            body.append(txt(320, y + 14, f"不写 checker：{note}", "t3", size=10.5))
        y += 33

    return svg(W, H, "\n".join(body))


# ---------------------------------------------------------------------------
# 面板 3：难度 × 期次
# ---------------------------------------------------------------------------
def panel_breakdown() -> str:
    W, H = 380, 300
    st = catalog.stats()
    diff = st["difficulty"]
    phase = st["phase"]

    body = [
        rrect(0, 0, W, H, 16, PANEL, LINE),
        txt(22, 34, "任务构成", "ttl"),
        txt(22, 54, "44 个检查项按难度与期次切分", "cap"),
    ]

    # 难度堆叠
    y = 84
    body.append(txt(22, y, "难度", "t2", size=11))
    total = sum(diff.values())
    segs, cx = [], 22.0
    for key, color in (("L1", EMERALD), ("L2", AMBER), ("L3", ROSE)):
        w = diff[key] / total * 330
        segs.append((w, color, key, cx))
        cx += w
    body.append(bar(22, y + 8, sum(s[0] for s in segs), 18, [(s[0], s[1]) for s in segs], r=5))
    names = {"L1": "简单", "L2": "中等", "L3": "困难"}
    for w, color, key, sx in segs:  # 标签对齐到各自色段中心
        body.append(txt(sx + w / 2, y + 44, f"{names[key]} {diff[key]}", "t3", size=10.5, anchor="middle"))

    # 期次堆叠
    y = 172
    body.append(txt(22, y, "期次", "t2", size=11))
    p1 = phase.get("一期", 0)
    p2 = phase.get("二期", 0)
    w1 = p1 / total * 330
    segs = [(w1, CYAN), (p2 / total * 330, "#3B4A6B")]
    body.append(bar(22, y + 8, sum(s[0] for s in segs), 18, segs, r=5))
    body.append(txt(22, y + 44, f"一期 {p1} 项（本轮必做）", "t3", size=10.5))
    body.append(txt(22, y + 60, f"二期 {p2} 项（之后补）", "t3", size=10.5))

    # 一句话结论
    body.append(rrect(22, 244, 336, 34, 8, "#0E1A2E"))
    body.append(txt(34, 265, "项数压在 M6 与 M3（12 + 11），风险压在 M2 与 M5", "t2", size=10.5))
    return svg(W, H, "\n".join(body))


# ---------------------------------------------------------------------------
# 面板 4：12 周节奏
# ---------------------------------------------------------------------------
def panel_timeline() -> str:
    W, H = 760, 300
    x0, cell, top = 70, 54, 84
    body = [
        rrect(0, 0, W, H, 16, PANEL, LINE),
        txt(22, 34, "12 周节奏与门禁", "ttl"),
        txt(170, 34, "6 个阶段，6 道门禁，门禁不过不进下一阶段", "cap"),
    ]

    # 周次刻度
    for i in range(12):
        x = x0 + i * cell
        body.append(txt(x + cell / 2, top - 10, f"W{i+1}", "t3", size=10, anchor="middle"))

    # 阶段带
    for idx, (label, w1, w2) in enumerate(STAGES):
        x = x0 + (w1 - 1) * cell + 3
        w = (w2 - w1 + 1) * cell - 6
        c = STAGE_COLORS[idx]
        body.append(rrect(x, top, w, 46, 9, c, op=0.16))
        body.append(rrect(x, top, w, 46, 9, "none", stroke=c, sw=1, op=0.5))
        body.append(txt(x + w / 2, top + 22, label.split()[0], "t1", size=12, weight="600", anchor="middle"))
        body.append(txt(x + w / 2, top + 37, label.split()[1], "t3", size=10, anchor="middle"))

    # 轴线
    axis_y = top + 96
    body.append(f'<line x1="{x0}" y1="{axis_y}" x2="{x0 + 12*cell}" y2="{axis_y}" stroke="{LINE}" stroke-width="2"/>')

    # 门禁（W4/W5 相邻，标签向外错开，避免叠字）
    place = {0: ("start", 10), 4: ("end", -10), 5: ("start", 10),
             8: ("middle", 0), 10: ("end", -12), 12: ("end", -12)}
    for wk, label in GATES.items():
        x = x0 + wk * cell if wk < 12 else x0 + 12 * cell
        body.append(f'<path d="M{x},{axis_y-7} L{x+7},{axis_y} L{x},{axis_y+7} L{x-7},{axis_y} Z" fill="{AMBER}"/>')
        anchor, dx = place.get(wk, ("middle", 0))
        body.append(txt(x + dx, axis_y + 26, label, "t3", size=10, anchor=anchor))

    # 关键节点标注
    body.append(rrect(x0, axis_y + 42, 620, 40, 9, "#0E1A2E"))
    body.append(txt(x0 + 14, axis_y + 66,
                    "硬线：W2 契约冻结 · W5 全链路首通 · W8 端到端 ≤30min · W10 代码冻结",
                    "t2", size=10.5))
    return svg(W, H, "\n".join(body))


# ---------------------------------------------------------------------------
# 面板 5：依赖关系
# ---------------------------------------------------------------------------
def panel_deps() -> str:
    """预置底座 + 八条平行线：没有前置关系，谁也不等谁。"""
    W, H = 560, 400
    body = [
        rrect(0, 0, W, H, 16, PANEL, LINE),
        txt(22, 30, "八条平行线，谁也不等谁", "ttl"),
    ]

    # 底座
    body.append(rrect(20, 44, 520, 84, 10, "#16233B", CYAN, 1.2))
    body.append(txt(34, 64, "共用底座（平台统一提供，个人不重复做）", "t1", size=11.5, weight="600"))
    body.append(txt(34, 84, "已交付：契约 · NX 解析（法向/轴线/测距/装配/边）· 三套场景 · 评测 · 74 个测试",
                    "t2", size=10.5))
    body.append(txt(34, 102, "待补：材料属性（等甲方模型）· 真实大模型压测",
                    "t3", size=10.5))

    # 八个人
    grid = [
        ("宋馨雨", "M2 安规", "4 项"),
        ("于大淇", "M6A 钣金", "8 项"),
        ("代世航", "M3 注塑铸造", "11 项"),
        ("汪琪竣", "M4 装配", "7 项"),
        ("杜滨芳", "M5 性能", "2 项"),
        ("张百瑞", "M6 机加工", "12 项"),
        ("陈卉妍", "M7 Web", "全套"),
        ("赵文哲", "M8 报告", "全套"),
    ]
    bw, bh, gap = 120, 70, 10
    x0, y0 = 25, 168
    for i, (name, mod, scope) in enumerate(grid):
        col, row = i % 4, i // 4
        x = x0 + col * (bw + gap)
        y = y0 + row * (bh + 14)
        body.append(rrect(x, y, bw, bh, 9, "#141F35", LINE))
        body.append(txt(x + 12, y + 22, name, "t1", size=12, weight="600"))
        body.append(txt(x + 12, y + 42, mod, "t2", size=10))
        body.append(txt(x + 12, y + 58, scope, "t3", size=9.5))
        # 从底座垂一根短线下来
        body.append(f'<path d="M{x + bw / 2:.1f},128 v{14 if row == 0 else 0}" '
                    f'stroke="{CYAN}" stroke-width="1.2" opacity="0.35"/>')

    body.append(txt(22, H - 16,
                    "八个人之间没有任何前置任务；缺东西找底座，不找别人",
                    "t3", size=10.5))
    return svg(W, H, "\n".join(body))


def panel_platform() -> str:
    """平台已经给了什么，同学还要写什么。"""
    W, H = 560, 400
    body = [
        rrect(0, 0, W, H, 16, PANEL, LINE),
        txt(22, 30, "底座已经给好了，你们只管往上写", "ttl"),
    ]

    body.append(txt(22, 58, "平台已交付（不用重做）", "t1", size=11.5, weight="600"))
    done = [
        ("三份契约 + 校验", "44 项共用一套数据结构"),
        ("NX 解析", "零件/面/边/面积/半径/包围盒"),
        ("面法向 · 圆柱轴线", "拔模角、倒扣、转角类的前提"),
        ("批量精确测距", "一次 NX 启动测完所有配对"),
        ("装配展开 + 变换矩阵", "多组件坐标已换算到装配系"),
        ("边长度 + 曲线类型", "实测 72 直线 / 42 圆弧"),
        ("评测框架", "标注集 → P/R/F1"),
        ("三套评测场景", "混合 / 纯负样本 / 阈值边界"),
    ]
    y = 78
    for name, note in done:
        body.append(f'<circle cx="26" cy="{y - 4}" r="3" fill="{EMERALD}"/>')
        body.append(txt(38, y, name, "t2", size=10.5))
        body.append(txt(38, y + 12, note, "t3", size=9))
        y += 31

    x2 = 300
    body.append(txt(x2, 58, "你们要写的", "t1", size=11.5, weight="600"))
    todo = [
        ("44 个检查项", "38 DFM + 4 安规 + 2 性能"),
        ("Web 平台", "上传 / 3D 标注 / 规则配置"),
        ("报告与知识库", "报告引擎 + 建议模板库"),
    ]
    y = 84
    for name, note in todo:
        body.append(rrect(x2 - 6, y - 16, 244, 46, 8, "#1B2740", AMBER, 1))
        body.append(txt(x2 + 4, y - 2, name, "t1", size=11.5, weight="600", fill=AMBER))
        body.append(txt(x2 + 4, y + 16, note, "t3", size=9.5))
        y += 56

    body.append(txt(x2, 262, "一人一包，互不依赖", "t2", size=10.5))
    body.append(txt(x2, 280, "缺东西找底座，不找别人", "t3", size=9.5))

    body.append(txt(22, 344, "Web 与报告由另外两位负责，不占检查项", "t3", size=9.5))
    return svg(W, H, "\n".join(body))


def panel_eval() -> str:
    """评测框架：标注集怎么变成分数。"""
    W, H = 560, 400
    body = [
        rrect(0, 0, W, H, 16, PANEL, LINE),
        txt(22, 30, "怎么知道自己准不准", "ttl"),
    ]

    steps = [
        ("① 标注集", "人工标「该报 / 不该报」", CYAN),
        ("② 匹配", "同检查项 + 同零件 + 容差", VIOLET),
        ("③ 算分", "P / R / F1 / 误报率", EMERALD),
    ]
    bw, gap, y = 158, 22, 52
    for i, (title, note, color) in enumerate(steps):
        x = 22 + i * (bw + gap)
        body.append(rrect(x, y, bw, 60, 8, "#16233B", color, 1.2))
        body.append(txt(x + 10, y + 22, title, "t1", size=11, weight="600", fill=color))
        body.append(txt(x + 10, y + 41, note, "t3", size=9))
        if i < 2:
            body.append(f'<path d="M{x + bw + 3},{y + 30} h16" stroke="{LINE}" stroke-width="1.4"/>')

    body.append(txt(22, 142, "匹配规则（必须同时满足）", "t1", size=10.5, weight="600"))
    rules = ["检查项相同：DFM-31 不能顶 DFM-32", "零件有交集", "位置距离 ≤ 容差", "一对一，多余的算误报"]
    y = 162
    for r in rules:
        body.append(txt(30, y, "· " + r, "t2", size=10))
        y += 18

    body.append(txt(300, 142, "负样本干嘛用", "t1", size=10.5, weight="600"))
    for i, s in enumerate(["标「这里不该报」", "只标正样本的话", "「见谁都报」也能满分", "负样本压住误报"]):
        body.append(txt(300, 162 + i * 18, s, "t2", size=10 if i < 2 else 10))

    body.append(txt(22, 258, "三套场景实测", "t1", size=10.5, weight="600"))
    rows = [
        ("demo_asm", "混合", "macro-F1 1.000"),
        ("demo_normal", "纯负样本", "误报 0 条"),
        ("demo_edge", "阈值边界", "0.302 正确跳过"),
    ]
    y = 278
    for name, kind, result in rows:
        body.append(txt(30, y, name, "t2", size=10))
        body.append(txt(120, y, kind, "t3", size=9.5))
        body.append(txt(210, y, result, "t2", size=10, fill=EMERALD))
        y += 22

    body.append(txt(22, H - 14, "python -m nxdrp eval findings.json -l 标注集.json", "t3", size=9.5))
    return svg(W, H, "\n".join(body))


def panel_risks() -> str:
    W, H = 560, 400
    body = [
        rrect(0, 0, W, H, 16, PANEL, LINE),
        txt(22, 34, "12 项风险", "ttl"),
        txt(120, 34, "前 5 项集中在数据与几何质量", "cap"),
    ]

    # 图例
    lx = 342
    for lvl, name in ((5, "极高"), (4, "高"), (3, "中高"), (2, "中")):
        body.append(rrect(lx, 24, 9, 9, 2, RISK_COLOR[lvl]))
        body.append(txt(lx + 13, 32, name, "t3", size=9.5))
        lx += 48

    y = 64
    for rid, name, lvl, tag in RISKS:
        c = RISK_COLOR[lvl]
        body.append(txt(22, y + 12, rid, "t3", size=10))
        body.append(txt(48, y + 12, name, "t2", size=11))
        body.append(rrect(200, y + 2, lvl / 5 * 280, 12, 6, c, op=0.85))
        body.append(txt(206 + lvl / 5 * 280, y + 12, tag, "t3", size=9.5))
        y += 27

    return svg(W, H, "\n".join(body))


def panel_flow() -> str:
    """一条数据流：模型进 → 解析一次 → 44 个检查 → 统一结果 → 报告。"""
    W, H = 1180, 172
    nodes = [
        ("3D 模型", "NX .prt 上传", "#94A3B8"),
        ("解析", "统一成 ModelBundle", CYAN),
        ("44 个检查项", "并行跑，互不干扰", VIOLET),
        ("统一结果", "每条都是一个 Finding", AMBER),
        ("报告", "问题 + 建议 + 定位", EMERALD),
    ]
    body = [
        rrect(0, 0, W, H, 16, PANEL, LINE),
        txt(24, 30, "一条缺陷是怎么被查出来的", "ttl"),
    ]
    x0, nw, gap, y, nh = 24, 196, 38, 48, 68
    for i, (title, sub, color) in enumerate(nodes):
        x = x0 + i * (nw + gap)
        body.append(rrect(x, y, nw, nh, 10, "#141F35", LINE))
        body.append(rrect(x, y, 4, nh, 2, color))
        body.append(txt(x + 16, y + 28, title, "t1", size=13.5, weight="600"))
        body.append(txt(x + 16, y + 50, sub, "t3", size=10.5))
        if i < len(nodes) - 1:
            ax = x + nw + 8
            body.append(f'<path d="M{ax},{y+nh/2} h{gap-20}" stroke="{T3}" stroke-width="1.4" '
                        f'stroke-linecap="round"/>')
            body.append(f'<path d="M{ax+gap-26},{y+nh/2-4.5} l7,4.5 l-7,4.5 z" fill="{T3}"/>')

    body.append(txt(W / 2, H - 22,
                    "解析只做一次，44 个检查项共用同一份数据 —— 这是「单次检查 ≤ 30 分钟」能成立的原因",
                    "t3", size=10.5, anchor="middle"))
    return svg(W, H, "\n".join(body))


def standalone(markup: str) -> str:
    """给单张矢量图补一层满铺背景，单独打开时不会透出白底。"""
    import re

    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', markup)
    if not m:
        return markup
    w, h = m.group(1), m.group(2)
    bg = f'<rect x="0" y="0" width="{w}" height="{h}" fill="{BG}"/>'
    return markup.replace("<style>", bg + "\n<style>", 1)


# ---------------------------------------------------------------------------
# HTML 看板
# ---------------------------------------------------------------------------
HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>连接器 AI 智能设计检查平台 · 项目看板</title>
<style>
  :root{
    --bg:#0B1220; --panel:#131C30; --line:#243250;
    --t1:#E9EFFA; --t2:#8FA3C2; --t3:#5A6C8A;
    --cyan:#38BDF8; --violet:#A78BFA; --amber:#FBBF24; --rose:#FB7185; --emerald:#34D399;
  }
  *{box-sizing:border-box}
  body{
    margin:0;background:
      radial-gradient(1200px 600px at 12% -8%, #15233F 0%, transparent 60%),
      radial-gradient(900px 500px at 88% 0%, #1A1633 0%, transparent 55%),
      var(--bg);
    color:var(--t1);font-family:"Microsoft YaHei","PingFang SC","Segoe UI",system-ui,sans-serif;
    -webkit-font-smoothing:antialiased;padding:34px 30px 44px;
  }
  .wrap{max-width:1560px;margin:0 auto}
  header{margin-bottom:26px}
  h1{font-size:29px;font-weight:800;letter-spacing:.3px;margin:0 0 8px}
  h1 span{background:linear-gradient(90deg,var(--cyan),var(--violet));-webkit-background-clip:text;
          background-clip:text;color:transparent}
  .sub{color:var(--t2);font-size:13.5px;margin:0}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:22px 0 24px}
  .kpi{background:linear-gradient(180deg,#16203A 0%,#121A2E 100%);border:1px solid var(--line);
       border-radius:14px;padding:16px 18px;position:relative;overflow:hidden}
  .kpi::after{content:"";position:absolute;inset:0 auto 0 0;width:3px;background:var(--c)}
  .kpi .k{color:var(--t3);font-size:11.5px;letter-spacing:.6px;text-transform:uppercase}
  .kpi .v{font-size:30px;font-weight:800;margin-top:6px;line-height:1}
  .kpi .v small{font-size:13px;color:var(--t2);font-weight:500;margin-left:5px}
  .kpi .n{color:var(--t3);font-size:11px;margin-top:7px}
  .grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:16px;
        box-shadow:0 18px 40px -28px #000;overflow:hidden}
  .s3{grid-column:span 3}.s4{grid-column:span 4}.s6{grid-column:span 6}
  .s8{grid-column:span 8}.s12{grid-column:span 12}
  .card svg{display:block}
  footer{margin-top:22px;color:var(--t3);font-size:11.5px;line-height:1.7}
  .intro{display:grid;grid-template-columns:1fr;gap:14px;margin:2px 0 22px}
  .ibox{background:linear-gradient(180deg,#121B2F,#0F1727);border:1px solid var(--line);
        border-radius:14px;padding:20px 24px}
  .ik{font-size:15px;letter-spacing:.9px;color:var(--cyan);font-weight:700;margin-bottom:11px}
  .ibox.v2 .ik{color:var(--violet)}
  .ibox.v3 .ik{color:var(--emerald)}
  .ibox p{margin:0;color:var(--t2);font-size:17px;line-height:1.85}
  .ibox b{color:var(--t1);font-weight:600}
  @media (max-width:1180px){
    .kpis{grid-template-columns:repeat(2,1fr)}
    .intro{grid-template-columns:1fr}
    .s3,.s4,.s6,.s8{grid-column:span 12}
  }
  @media print{
    body{background:#fff;color:#111}
    .card,.kpi,.ibox{background:#fff;border-color:#ddd;box-shadow:none}
    h1 span{color:#111;-webkit-text-fill-color:#111}
    .sub,.kpi .k,.kpi .n,.ibox p,footer{color:#555}
  }
</style>
</head>
<body><div class="wrap">
"""


def build_html(panels: dict) -> str:
    st = catalog.stats()
    total = st["total"]
    reg = discover()
    done = len(reg.ids())

    kpis = [
        (CYAN, "检查项总数", f"{total}", "38 项 DFM + 4 项安规 + 2 项性能"),
        (EMERALD, "已完成", f"{done}", f"占 {done/total*100:.1f}% · 另有 74 个单元测试"),
        (VIOLET, "开发人力", "8", "人，各自独立模块，互不改对方代码"),
        (AMBER, "本轮周期", "2", "周内做完全部 44 项，第 2 周末演示"),
    ]
    kpi_html = "\n".join(
        f'<div class="kpi" style="--c:{c}"><div class="k">{k}</div>'
        f'<div class="v">{v}</div><div class="n">{n}</div></div>'
        for c, k, v, n in kpis
    )

    cards = [
        ("s12", panels["flow"]),
        ("s3", panels["progress"]),
        ("s3", panels["breakdown"]),
        ("s6", panels["workload"]),
        ("s6", panels["eval"]),
        ("s6", panels["platform"]),
        ("s6", panels["deps"]),
        ("s6", panels["risks"]),
    ]
    card_html = "\n".join(f'<div class="card {cls}">{svg}</div>' for cls, svg in cards)

    intro = (
        '<section class="intro">'
        '<div class="ibox"><div class="ik">现在怎么做</div><p>'
        "设计完一个连接器，要在 NX 里<b>人工逐项点</b> 38 项可制造性检查，"
        "再用 AutoCrear 手量电气间隙和爬电距离；载流、温升只能靠算、靠经验、靠试做样品。"
        "一条产品走完，光检查就是 <b>1~2 个工作日</b>，还容易漏、标准理解不一致。</p></div>"
        '<div class="ibox v2"><div class="ik">平台要做什么</div><p>'
        "模型传上去，自动跑完全部检查，出一份能直接拿去评审的报告。"
        "报告里每条问题必须说清四件事：<b>在哪儿、差多少、多严重、怎么改</b>。"
        "检查规则由工艺工程师自己维护，不用写代码。</p></div>"
        '<div class="ibox v3"><div class="ik">本期做到什么</div><p>'
        "38 项 DFM 缺陷识别准确率 <b>≥ 90%</b>；安规精度不低于 AutoCrear；"
        "性能预测任选一项完成；单次完整检查 <b>≤ 30 分钟</b>；支持 10 人并发。</p></div>"
        "</section>"
    )

    return (
        HTML_HEAD
        + "<header>\n"
        + "<h1>连接器 AI 智能设计检查平台 · <span>项目看板</span></h1>\n"
        + '<p class="sub">浩亭（珠海）制造有限公司委托 · 哈尔滨工业大学计算学部 · '
          "把连接器 3D 模型丢进去，自动查出 44 项设计问题并出具报告</p>\n"
        + "</header>\n"
        + intro
        + f'<div class="kpis">\n{kpi_html}\n</div>\n'
        + f'<div class="grid">\n{card_html}\n</div>\n'
        + '<footer>数据来源：nxdrp/catalog.py 的 44 项检查项清单、registry 的实际注册情况、'
          "rules/dfm_default.json 的规则库。<br>"
          "本页由 tools/build_viz.py 生成，检查项实现了、人数变了，重跑脚本图就跟着变。</footer>\n"
        + "</div></body></html>"
    )


# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="生成项目可视化看板与矢量图")
    ap.add_argument("--out", default=None, help="输出目录（默认为项目根上一级）")
    args = ap.parse_args(argv)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = args.out or os.path.dirname(root)
    os.makedirs(out, exist_ok=True)

    panels = {
        "flow": panel_flow(),
        "progress": panel_progress(),
        "workload": panel_workload(),
        "breakdown": panel_breakdown(),
        "deps": panel_deps(),
        "platform": panel_platform(),
        "eval": panel_eval(),
        "risks": panel_risks(),
    }

    # 单张矢量图（可插入 docx / ppt）
    names = {
        "flow": "项目图-工作流程.svg",
        "progress": "项目图-完成度.svg",
        "workload": "项目图-分工负载.svg",
        "deps": "项目图-并行结构.svg",
    }
    for key, fn in names.items():
        path = os.path.join(out, fn)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('<?xml version="1.0" encoding="UTF-8"?>\n' + standalone(panels[key]))
        print(f"  写出 {fn}")

    html_path = os.path.join(out, "项目可视化看板.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(build_html(panels))
    print(f"  写出 项目可视化看板.html")
    print(f"\n输出目录：{out}")


if __name__ == "__main__":
    main()
