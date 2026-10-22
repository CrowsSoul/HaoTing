# -*- coding: utf-8 -*-
"""M6A 钣金类 DFM（8 项） —— 负责人：于大淇

数据契约没有料厚、弯曲线、翻边、凸台、槽等钣金专有字段，本包全部采用
低置信度几何粗筛；Finding 带【粗筛】标记，需人工复核。
"""

from .dfm19_bend_radius import BendRadiusChecker
from .dfm20_hole_edge import HoleEdgeDistanceChecker
from .dfm21_hole_spacing import HoleSpacingChecker
from .dfm22_hole_thickness import HoleDiameterThicknessChecker
from .dfm23_slot_width import SlotWidthChecker
from .dfm24_bend_cutout import BendCutoutDistanceChecker
from .dfm25_flange_height import FlangeHeightChecker
from .dfm26_boss_height import PunchBossHeightChecker

CHECKERS = [
    BendRadiusChecker(),
    HoleEdgeDistanceChecker(),
    HoleSpacingChecker(),
    HoleDiameterThicknessChecker(),
    SlotWidthChecker(),
    BendCutoutDistanceChecker(),
    FlangeHeightChecker(),
    PunchBossHeightChecker(),
]
