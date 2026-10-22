# -*- coding: utf-8 -*-
"""检查项总目录（单一事实来源）。

来源：《2-附件1. 研发需求表》「检查项目」页，共 38 行 DFM 检查项；
安规项来自《研发方案》3.3；性能预测来自 3.4。

约定：
  * ``check_item_id`` 是全平台主键，规则、结果、报告、前端全部引用它。
  * ``owner_module`` 是开发归属（M3/M4/M6...），用于分工与覆盖率统计。
  * ``phase`` 一期 = 12 周内完成；二期 = 原型交付后补齐。
  * 新增检查项必须先改这里，再写 checker，禁止私下起 ID。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogItem:
    check_item_id: str
    name_cn: str
    name_en: str
    process_type: str          # 主工艺
    applies_to: tuple[str, ...]  # 适用工艺（可多个）
    difficulty: str            # L1 / L2 / L3
    owner_module: str
    phase: str                 # 一期 / 二期
    hint: str = ""             # 给开发者的判定要点提示

    @property
    def is_implemented(self) -> bool:
        return False


_RAW = [
    # ---------------- 装配类（M4 汪琪俊）----------------
    ("DFM-01", "干涉检测", "Interference Detection", "assembly", ("assembly",), "L3", "M4", "一期",
     "两两实体求交，体积>0；需区分硬干涉/临界间隙/碎面虚假干涉"),
    ("DFM-02", "最小间隙", "Minimum Clearance", "assembly", ("assembly",), "L1", "M4", "一期",
     "零件间最小距离 < 阈值（默认 0.2~0.5mm，可配）"),
    ("DFM-03", "孔对齐", "Hole Alignment", "assembly", ("assembly",), "L2", "M4", "一期",
     "跨零件孔轴线同轴度偏差 ≤ 允许值，且公称直径匹配"),
    ("DFM-04", "孔/槽对齐", "Slot to Hole Alignment", "assembly", ("assembly",), "L2", "M4", "一期",
     "槽中线与孔轴线偏差 ≤ 允许值"),
    ("DFM-05", "紧固件可达性", "Fastener Accessibility", "assembly", ("assembly",), "L3", "M4", "一期",
     "沿螺栓轴线扫掠工具包络，不得与周边件碰撞"),
    ("DFM-06", "紧固件间隙", "Fastener Clearance", "assembly", ("assembly",), "L2", "M4", "一期",
     "螺栓头/垫圈与周边件的轴向、径向间隙 ≥ 阈值"),
    ("DFM-07", "紧固件啮合长度", "Fastener Engagement Length", "assembly", ("assembly",), "L1", "M4", "一期",
     "螺纹旋合长度/公称直径 ≥ 1.0（钢）~1.5（铝/塑料）"),

    # ---------------- 注塑 / 铸造类（M3 代世航）----------------
    ("DFM-08", "最小壁厚", "Minimum Wall Thickness", "injection", ("injection", "casting"), "L2", "M3", "一期",
     "壁厚 < 材料最小壁厚（PC 1.5 / PA66 0.8 / PBT 0.8 …）"),
    ("DFM-09", "均匀壁厚", "Uniform Wall Thickness", "injection", ("injection", "casting"), "L2", "M3", "一期",
     "局部壁厚/名义壁厚超出 [0.8,1.25] 的面积占比 > 阈值"),
    ("DFM-10", "壁厚变化", "Wall Thickness Variation", "injection", ("injection", "casting"), "L2", "M3", "二期",
     "相邻区域壁厚梯度超过允许变化率"),
    ("DFM-11", "加强筋设计", "Rib Design", "injection", ("injection", "casting"), "L2", "M3", "一期",
     "筋根厚/名义壁厚 ≤ 0.5~0.6；筋高/根厚 ≤ 3~5"),
    ("DFM-12", "模具壁厚", "Mold Wall Thickness", "injection", ("injection", "casting"), "L3", "M3", "二期",
     "筋与筋、凸台与凸台之间模具钢厚度 ≥ 阈值"),
    ("DFM-13", "拔模角", "Draft Angle", "injection", ("injection", "casting"), "L1", "M3", "一期",
     "面法向与开模方向夹角 < 最小拔模角（0.5°~1°）"),
    ("DFM-14", "倒扣", "Undercuts", "injection", ("injection", "casting"), "L2", "M3", "一期",
     "沿开模方向存在遮挡（面在投影方向互相覆盖）"),
    ("DFM-15", "凸台设计", "Boss Design", "injection", ("injection", "casting"), "L2", "M3", "一期",
     "凸台根部 R/壁厚、顶部厚度、凸台与侧壁距离"),
    ("DFM-16", "圆角半径", "Fillet Radius", "injection", ("injection", "casting"), "L2", "M3", "一期",
     "内角缺 R 或 R<0.25t；外角 R<0.5t"),
    ("DFM-17", "多抽芯方向", "Multiple Pull Directions", "injection", ("injection", "casting"), "L2", "M3", "二期",
     "统计倒扣方向聚类，>1 个主方向则判定需多抽芯"),
    ("DFM-18", "尖角", "Sharp Corner", "injection", ("injection", "casting", "sheet_metal"), "L1", "M3", "一期",
     "相邻面二面角 < 阈值（如 60°）且非设计意图"),

    # ---------------- 钣金类（M6 张百瑞）----------------
    ("DFM-19", "最小弯曲半径", "Minimum Bend Radius", "sheet_metal", ("sheet_metal",), "L1", "M6A", "一期",
     "内 R/料厚 t < 材料下限（冷轧钢 0.5~1.0）"),
    ("DFM-20", "孔到边缘距离", "Hole to Edge Distance", "sheet_metal", ("sheet_metal",), "L1", "M6A", "一期",
     "孔边到板边距离 < 1.5t~2t"),
    ("DFM-21", "孔间距", "Hole Spacing", "sheet_metal", ("sheet_metal",), "L1", "M6A", "一期",
     "相邻孔净距 < 2t"),
    ("DFM-22", "孔径与料厚比", "Hole Diameter to Thickness Ratio", "sheet_metal", ("sheet_metal",), "L1", "M6A", "一期",
     "冲孔直径 < 料厚"),
    ("DFM-23", "槽的最小宽度", "Minimum Slot Width", "sheet_metal", ("sheet_metal",), "L1", "M6A", "一期",
     "槽宽 < 1.2t"),
    ("DFM-24", "折弯与切口距离", "Bend to Cutout Distance", "sheet_metal", ("sheet_metal",), "L2", "M6A", "二期",
     "切口/孔到折弯线距离 < 3t + R"),
    ("DFM-25", "翻边高度", "Flange Height", "sheet_metal", ("sheet_metal",), "L1", "M6A", "一期",
     "翻边高 < 3t + R（否则边缘撕裂）"),
    ("DFM-26", "冲压凸台高度", "Punch Boss Height", "sheet_metal", ("sheet_metal",), "L1", "M6A", "二期",
     "凸台高/t 超出允许区间"),

    # ---------------- 机加工类（M6 张百瑞）----------------
    ("DFM-27", "深孔", "Deep Holes", "machining", ("machining",), "L1", "M6", "一期",
     "孔深/孔径 > 4（标准钻）或 > 10（深孔）"),
    ("DFM-28", "深窄槽", "Deep and Narrow Slots", "machining", ("machining",), "L1", "M6", "一期",
     "槽深/槽宽 > 3~4"),
    ("DFM-29", "平底盲孔", "Flat Bottom Blind Holes", "machining", ("machining",), "L1", "M6", "一期",
     "盲孔底面为平面（无钻尖角），不利排屑"),
    ("DFM-30", "刀具可达性", "Tool Accessibility", "machining", ("machining",), "L3", "M6", "二期",
     "沿孔/槽轴线的刀具包络无遮挡"),
    ("DFM-31", "特征尺寸与刀具标准", "Feature Size vs Tool Standard", "machining", ("machining",), "L1", "M6", "一期",
     "孔径/槽宽落在标准刀具系列（Φ1/2/3/4/5/6/8/10/12…）内"),
    ("DFM-32", "底部圆角一致性", "Inconsistent Bottom Radius", "machining", ("machining",), "L1", "M6", "一期",
     "底面圆角半径种类数 > N（换刀次数过多）"),
    ("DFM-33", "顶部圆角", "Top Fillets", "machining", ("machining",), "L1", "M6", "一期",
     "顶边 R < 刀具最小 R 或缺失"),
    ("DFM-34", "内部倒角", "Internal Chamfers", "machining", ("machining",), "L1", "M6", "一期",
     "内角倒角角度/尺寸不在标准范围"),
    ("DFM-35", "深圆角转角", "Deep Radius Corners", "machining", ("machining",), "L2", "M6", "二期",
     "内腔转角 R < 刀具 R（刀具进不去）"),
    ("DFM-36", "角度铣削面", "Angular Milling Faces", "machining", ("machining",), "L1", "M6", "一期",
     "侧面与底面/基准面夹角非 90° 且非标准角"),
    ("DFM-37", "窄通道", "Narrow Passages", "machining", ("machining",), "L3", "M6", "二期",
     "通道宽度 < 最小刀具直径"),
    ("DFM-38", "孔的入刀/出刀面", "Entry/Exit Surface for Holes", "machining", ("machining",), "L1", "M6", "一期",
     "孔入口/出口面法向与孔轴夹角 > 阈值"),

    # ---------------- 安规（M2 宋馨雨）----------------
    ("SAF-01", "电气间隙", "Electric Clearance", "safety", ("safety",), "L2", "M2", "一期",
     "导体两两配对求最短空间直线距离，与 IEC 60664-1 限值比对；AutoCrear 结果作对照"),
    ("SAF-02", "爬电距离", "Creepage Distance", "safety", ("safety",), "L3", "M2", "一期",
     "沿绝缘表面求最短泄漏路径，处理沟槽/筋/倒角规则；AutoCrear 结果作对照"),
    ("SAF-03", "安规不合规归集", "Compliance Summary", "safety", ("safety",), "L1", "M2", "一期",
     "综合间隙与爬电结果，任一项低于限值即判不合规并分级"),
    ("SAF-04", "安规量化建议", "Clearance Suggestion", "safety", ("safety",), "L2", "M2", "二期",
     "输出目标尺寸：增大间隙到 X mm / 增加绝缘筋使爬电达到 Y mm"),

    # ---------------- 性能预测（M5 杜滨芳）----------------
    ("PERF-01", "载流-温升预测", "Current-Temperature Rise Prediction", "performance", ("performance",), "L3", "M5", "一期",
     "由几何/材料/工况特征预测稳态温升与允许载流，输出区间"),
    ("PERF-02", "插拔力预测", "Insertion Force Prediction", "performance", ("performance",), "L3", "M5", "二期",
     "由接触簧片几何/材料/过盈量预测插入力、拔出力"),
]

CATALOG: tuple[CatalogItem, ...] = tuple(CatalogItem(*row) for row in _RAW)
BY_ID: dict[str, CatalogItem] = {item.check_item_id: item for item in CATALOG}


def get(check_item_id: str) -> CatalogItem | None:
    return BY_ID.get(check_item_id)


def by_owner(module: str) -> list[CatalogItem]:
    return [i for i in CATALOG if i.owner_module == module]


def by_phase(phase: str) -> list[CatalogItem]:
    return [i for i in CATALOG if i.phase == phase]


def by_process(process_type: str) -> list[CatalogItem]:
    return [i for i in CATALOG if process_type in i.applies_to]


def stats() -> dict:
    total = len(CATALOG)
    by_diff: dict[str, int] = {}
    by_mod: dict[str, int] = {}
    by_phase: dict[str, int] = {}
    for i in CATALOG:
        by_diff[i.difficulty] = by_diff.get(i.difficulty, 0) + 1
        by_mod[i.owner_module] = by_mod.get(i.owner_module, 0) + 1
        by_phase[i.phase] = by_phase.get(i.phase, 0) + 1
    return {"total": total, "difficulty": by_diff, "owner": by_mod, "phase": by_phase}
