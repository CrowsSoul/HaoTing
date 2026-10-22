# -*- coding: utf-8 -*-
"""参考实现 —— 可读，但不要直接当最终交付。

这三个 checker 的作用是给 8 位同学示范「一个合格的 checker 长什么样」：
有参数、有跳过逻辑、有证据、有量化建议、有置信度、有可追溯的 detector。

    dfm31_tool_standard.py     DFM-31 非标刀具尺寸   （几何统计 + 查表）
    dfm32_fillet_uniformity.py DFM-32 圆角半径一致性 （一维聚类）
    dfm02_min_clearance.py     DFM-02 最小间隙粗筛   （多零件遍历 + 置信度）

注意：不要在 __init__.py 里再导出一次 CHECKERS —— 各子模块已经导出了，
重复导出虽然会被注册表去重，但会让「谁拥有这个检查项」变得不清楚。
"""

__all__ = []
