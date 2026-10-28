# -*- coding: utf-8 -*-
"""M3 注塑 / 铸造类 DFM —— 负责人：代世航。"""

from .dfm08_min_wall import MinWallThicknessChecker
from .dfm09_uniform_wall import UniformWallThicknessChecker
from .dfm10_wall_variation import WallVariationChecker
from .dfm11_rib_design import RibDesignChecker
from .dfm12_mold_wall import MoldWallThicknessChecker
from .dfm13_draft_angle import DraftAngleChecker
from .dfm14_undercut import UndercutChecker
from .dfm15_boss_design import BossDesignChecker
from .dfm16_fillet_radius import FilletRadiusChecker
from .dfm17_multi_pull import MultiPullDirectionChecker
from .dfm18_sharp_corner import SharpCornerChecker

CHECKERS = [
    MinWallThicknessChecker(),
    UniformWallThicknessChecker(),
    WallVariationChecker(),
    RibDesignChecker(),
    MoldWallThicknessChecker(),
    DraftAngleChecker(),
    UndercutChecker(),
    BossDesignChecker(),
    FilletRadiusChecker(),
    MultiPullDirectionChecker(),
    SharpCornerChecker(),
]
