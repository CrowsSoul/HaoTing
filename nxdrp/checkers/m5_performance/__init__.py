# -*- coding: utf-8 -*-
"""M5 智能性能预测 —— 负责人：杜滨芳

PERF-01 载流–温升在本期交付。PERF-02 插拔力是二期，这里不注册。
"""

from .perf01_current_temp import CurrentTempChecker

CHECKERS = [CurrentTempChecker()]
