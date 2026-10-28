# -*- coding: utf-8 -*-
"""M5 智能性能预测 —— 负责人：杜滨芳

PERF-01 载流–温升，温升走模拟 NX 仿真。
PERF-02 插拔力，标签为悬臂梁摩擦公式。
"""

from .perf01_current_temp import CurrentTempChecker
from .perf02_insertion_force import InsertionForceChecker

CHECKERS = [CurrentTempChecker(), InsertionForceChecker()]
