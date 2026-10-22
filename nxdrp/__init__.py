# -*- coding: utf-8 -*-
"""HARTING 连接器 AI 智能设计检查平台 —— 核心框架包。

分层与职责（与《研发方案》第 3 章的五层架构对应）：

    Layer 2  模型解析与特征提取  ->  nxdrp.adapters  +  nxdrp.journals
    Layer 3  规则引擎与检查       ->  nxdrp.checkers  （学生插件）
    Layer 4  AI 推理服务          ->  nxdrp.checkers.m5_performance
    Layer 5  报告与交互           ->  由 M7 / M8 模块实现

核心约束：所有模块只通过 nxdrp.contracts 里的三份契约交换数据。
"""

from .version import __version__, SCHEMA_VERSION

__all__ = ["__version__", "SCHEMA_VERSION"]
