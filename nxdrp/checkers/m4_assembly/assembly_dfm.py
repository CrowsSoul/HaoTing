# -*- coding: utf-8 -*-
"""M4 装配 DFM 的兼容导出入口。

实际实现遵循 ``docs/HOW_TO_ADD_A_CHECKER.md``，每个检查项独立一个文件。
保留本模块是为了兼容已有导入路径。
"""

from ._assembly_base import AssemblyChecker
from .dfm01_interference import InterferenceChecker
from .dfm02_min_clearance import MinClearanceChecker
from .dfm03_hole_alignment import HoleAlignmentChecker
from .dfm04_hole_slot_alignment import HoleSlotAlignmentChecker
from .dfm05_fastener_accessibility import FastenerAccessibilityChecker
from .dfm06_fastener_clearance import FastenerClearanceChecker
from .dfm07_engagement_length import EngagementLengthChecker

CHECKERS = [
    InterferenceChecker(), MinClearanceChecker(), HoleAlignmentChecker(),
    HoleSlotAlignmentChecker(), FastenerAccessibilityChecker(),
    FastenerClearanceChecker(), EngagementLengthChecker(),
]

__all__ = [
    "AssemblyChecker", "InterferenceChecker", "MinClearanceChecker",
    "HoleAlignmentChecker", "HoleSlotAlignmentChecker",
    "FastenerAccessibilityChecker", "FastenerClearanceChecker",
    "EngagementLengthChecker", "CHECKERS",
]
