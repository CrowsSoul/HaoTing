# -*- coding: utf-8 -*-
"""标注集：一个模型上「标准答案」长什么样。

一条标注 = 一个检查项在某个位置的期望结果：
    expected="defect"  这里应该报出来（正样本）
    expected="ok"      这里不该报（负样本，用来量误报）

为什么一定要负样本：只有正样本时，一个「什么都报」的检查器 recall 是 100%，
但工程师会被误报淹没。负样本是唯一能压住这种刷分的办法。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..contracts import Vec3
from ..errors import ContractError
from ..version import SCHEMA_VERSION


@dataclass
class Label:
    """一条标准答案。"""

    label_id: str
    check_item_id: str
    expected: str = "defect"          # defect | ok
    part_refs: list[str] = field(default_factory=list)
    location: Vec3 | None = None
    tolerance_mm: float = 2.0
    face_ids: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "label_id": self.label_id,
            "check_item_id": self.check_item_id,
            "expected": self.expected,
            "part_refs": list(self.part_refs),
            "location": list(self.location) if self.location else None,
            "tolerance_mm": self.tolerance_mm,
            "face_ids": list(self.face_ids),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Label":
        loc = d.get("location")
        return cls(
            label_id=d.get("label_id") or "L?",
            check_item_id=d.get("check_item_id", ""),
            expected=d.get("expected", "defect"),
            part_refs=list(d.get("part_refs") or []),
            location=tuple(loc) if loc else None,
            tolerance_mm=float(d.get("tolerance_mm", 2.0)),
            face_ids=list(d.get("face_ids") or []),
            note=d.get("note", ""),
        )


@dataclass
class LabelSet:
    """一个模型的全部标注。"""

    model_id: str = ""
    annotator: str = ""
    created_at: str = ""
    schema_version: str = SCHEMA_VERSION
    labels: list[Label] = field(default_factory=list)

    # ---------------- 序列化 ----------------
    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "annotator": self.annotator,
            "created_at": self.created_at,
            "labels": [x.to_dict() for x in self.labels],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LabelSet":
        return cls(
            model_id=d.get("model_id", ""),
            annotator=d.get("annotator", ""),
            created_at=d.get("created_at", ""),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            labels=[Label.from_dict(x) for x in d.get("labels", [])],
        )

    @classmethod
    def load(cls, path: str) -> "LabelSet":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)

    # ---------------- 查询 ----------------
    @property
    def positives(self) -> list[Label]:
        return [x for x in self.labels if x.expected == "defect"]

    @property
    def negatives(self) -> list[Label]:
        return [x for x in self.labels if x.expected == "ok"]

    def items(self) -> set[str]:
        return {x.check_item_id for x in self.labels}

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for x in self.labels:
            out[x.check_item_id] = out.get(x.check_item_id, 0) + 1
        return out

    def validate(self) -> None:
        problems: list[str] = []
        ids = [x.label_id for x in self.labels]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            problems.append(f"label_id 重复: {sorted(dup)}")
        for x in self.labels:
            if not x.check_item_id:
                problems.append(f"{x.label_id}: 缺少 check_item_id")
            if x.expected not in ("defect", "ok"):
                problems.append(f"{x.label_id}: expected={x.expected!r} 只能是 defect 或 ok")
            if x.expected == "defect" and x.location is None and not x.face_ids and not x.part_refs:
                problems.append(
                    f"{x.label_id}: 正样本至少要给 location / face_ids / part_refs 之一，否则没法匹配")
        if problems:
            raise ContractError("标注集校验失败", problems)


def load_labels(path: str) -> LabelSet:
    s = LabelSet.load(path)
    s.validate()
    return s
