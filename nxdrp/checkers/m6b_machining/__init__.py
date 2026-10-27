# -*- coding: utf-8 -*-
"""M6 机加工类 DFM（12 项） —— 负责人：张百瑞

数据契约没有孔深、槽深、倒角、型腔等机加工专有字段，本包全部采用
低置信度几何粗筛；Finding 带【粗筛】标记，需人工复核。

DFM-31 / DFM-32 由 nxdrp/checkers/examples/ 的内置参考实现交付
（被 selftest 与 Pressure Port 回归锚定），本包不重复注册。
"""

from .dfm27_deep_hole import DeepHoleChecker
from .dfm28_deep_narrow_slot import DeepNarrowSlotChecker
from .dfm29_flat_bottom_blind_hole import FlatBottomBlindHoleChecker
from .dfm30_tool_accessibility import ToolAccessibilityChecker
from .dfm33_top_fillet import TopFilletChecker
from .dfm34_internal_chamfer import InternalChamferChecker
from .dfm35_deep_radius_corner import DeepRadiusCornerChecker
from .dfm36_angular_milling import AngularMillingChecker
from .dfm37_narrow_passage import NarrowPassageChecker
from .dfm38_hole_entry_exit import HoleEntryExitChecker

CHECKERS = [
    DeepHoleChecker(),
    DeepNarrowSlotChecker(),
    FlatBottomBlindHoleChecker(),
    ToolAccessibilityChecker(),
    TopFilletChecker(),
    InternalChamferChecker(),
    DeepRadiusCornerChecker(),
    AngularMillingChecker(),
    NarrowPassageChecker(),
    HoleEntryExitChecker(),
]
