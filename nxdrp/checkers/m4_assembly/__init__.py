# -*- coding: utf-8 -*-
"""M4 装配类 DFM —— 负责人：汪琪竣。"""

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
