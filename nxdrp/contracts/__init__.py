# -*- coding: utf-8 -*-
"""契约包：只导出数据结构与校验，不含任何业务逻辑。"""

from .core import (
    BBox,
    Detector,
    Edge,
    Evidence,
    Face,
    Finding,
    ModelBundle,
    Occurrence,
    Part,
    Rule,
    RuleBook,
    Suggestion,
    PROCESS_TYPES,
    SEVERITIES,
    Vec3,
    schema_documents,
)

__all__ = [
    "BBox", "Detector", "Edge", "Evidence", "Face", "Finding", "ModelBundle",
    "Occurrence", "Part", "Rule", "RuleBook", "Suggestion",
    "PROCESS_TYPES", "SEVERITIES", "Vec3", "schema_documents",
]
