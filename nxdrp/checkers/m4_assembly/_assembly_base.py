# -*- coding: utf-8 -*-
"""M4 装配检查器共享基类。"""

from __future__ import annotations

import math

from ...checkers.base import BaseChecker
from ...contracts import ModelBundle


class AssemblyChecker(BaseChecker):
    """先验证装配实例关联和变换矩阵，再执行几何判定。"""

    version = "1.0.0"
    owner = "M4 汪琪竣"
    process_types = ("assembly",)

    def applies(self, model: ModelBundle, params: dict) -> tuple[bool, str]:
        """接受 NX 的原型文件名 ``part_ref``，按实例名/路径关联展开零件。"""
        known_refs: set[str] = set()
        for part in model.parts:
            known_refs.add(part.part_id.casefold())
            if part.name:
                known_refs.add(part.name.casefold())
            if part.occurrence_path:
                path = part.occurrence_path.replace("\\", "/")
                known_refs.add(path.casefold())
                known_refs.add(path.rsplit("/", 1)[-1].casefold())

        for occurrence in model.occurrences:
            occurrence_refs = {
                value.casefold()
                for value in (occurrence.name, occurrence.part_ref)
                if value
            }
            if known_refs and occurrence_refs and not (known_refs & occurrence_refs):
                return False, (
                    f"实例 {occurrence.occurrence_id} 的路径 {occurrence.name} "
                    "未匹配任何展开零件的 occurrence_path"
                )
            matrix = occurrence.transform
            if (
                not isinstance(matrix, list)
                or len(matrix) != 4
                or any(not isinstance(row, list) or len(row) != 4 for row in matrix)
            ):
                return False, f"实例 {occurrence.occurrence_id} 的 transform 不是 4×4 矩阵"
            try:
                finite = all(math.isfinite(float(value)) for row in matrix for value in row)
            except (TypeError, ValueError):
                finite = False
            if not finite:
                return False, f"实例 {occurrence.occurrence_id} 的 transform 含非数值/非有限值"
        return True, ""
