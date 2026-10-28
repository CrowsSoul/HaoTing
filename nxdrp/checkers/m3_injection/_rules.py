# -*- coding: utf-8 -*-
"""从公共规则库读取 M3 默认参数，不在 checker 中保存阈值副本。"""

from __future__ import annotations

import copy
from pathlib import Path

from ...contracts import RuleBook


_ROOT = Path(__file__).resolve().parents[3]
_RULEBOOK = RuleBook.load(str(_ROOT / "rules" / "dfm_default.json"))


def m3_default_params(check_item_id: str) -> dict:
    rule = _RULEBOOK.get(check_item_id)
    if rule is None:
        return {}
    return copy.deepcopy(rule.params)
