# -*- coding: utf-8 -*-
"""检查器插件包。

目录约定（一人一个子包，互不干扰）：

    checkers/
      base.py                框架提供，不要改
      examples/              参考实现（可读不可作为最终交付）
      m2_safety/             宋馨雨   安规（SAF-*）
      m3_injection/          代世航   注塑/铸造 DFM（DFM-08 ~ DFM-18）
      m4_assembly/           汪琪俊   装配 DFM（DFM-01 ~ DFM-07）
      m5_performance/        杜滨芳   性能预测（PERF-*）
      m6a_sheet_metal/       于大淇   钣金 DFM（DFM-19 ~ DFM-26）
      m6b_machining/         张百瑞   机加工 DFM（DFM-27 ~ DFM-38）
      m7_platform_web/       陈卉妍   （不放 checker，放 Web 与调度）
      m8_report/             赵文哲   （不放 checker，放报告与知识库）

每个子包的 __init__.py 里导出：

    from .my_checker import MyChecker
    CHECKERS = [MyChecker()]

框架会自动发现，不需要改任何核心文件。
新增一个检查项的完整步骤见 docs/HOW_TO_ADD_A_CHECKER.md。
"""

from .base import BaseChecker, CheckContext  # noqa: F401

from .proxy import NxDistanceProxy

__all__ = ["NxDistanceProxy"]
