# -*- coding: utf-8 -*-
"""三份数据契约：ModelBundle / RuleBook / Finding。

这是 8 个人并行开发不打架的唯一保障。任何模块只能通过这三份结构交换数据，
禁止私有格式、禁止 checker 之间直接 import。

设计取舍（为什么不用 pydantic）：
    运行环境只有 Python 3.12 + numpy，没有 pydantic / pyyaml / jsonschema。
    为了让人人都能一条命令跑起来，这里只用标准库 dataclasses，并自带校验。
    对外仍然导出 JSON Schema（见 schema_documents），方便前端/工具生成类型。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

from ..errors import ContractError
from ..version import SCHEMA_VERSION

Vec3 = tuple[float, float, float]

#: 严重度：P0 阻断 / P1 严重 / P2 一般 / P3 提示
SEVERITIES = ("P0", "P1", "P2", "P3")
#: 工艺术语表（与《研发需求表》检查项目页的工艺列一致）
PROCESS_TYPES = ("assembly", "injection", "casting", "sheet_metal", "machining", "safety", "performance")


# --------------------------------------------------------------------------
# 基础几何结构
# --------------------------------------------------------------------------
@dataclass
class BBox:
    """轴对齐包围盒，单位与模型一致（本平台统一换算为 mm）。"""

    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float

    @property
    def size(self) -> Vec3:
        return (self.xmax - self.xmin, self.ymax - self.ymin, self.zmax - self.zmin)

    @property
    def center(self) -> Vec3:
        return (
            (self.xmax + self.xmin) / 2.0,
            (self.ymax + self.ymin) / 2.0,
            (self.zmax + self.zmin) / 2.0,
        )

    @property
    def diagonal(self) -> float:
        dx, dy, dz = self.size
        return (dx * dx + dy * dy + dz * dz) ** 0.5

    def is_valid(self) -> bool:
        return self.xmin <= self.xmax and self.ymin <= self.ymax and self.zmin <= self.zmax

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "BBox | None":
        if not d:
            return None
        try:
            return cls(float(d["xmin"]), float(d["ymin"]), float(d["zmin"]),
                       float(d["xmax"]), float(d["ymax"]), float(d["zmax"]))
        except (KeyError, TypeError, ValueError):
            return None

    @classmethod
    def union(cls, boxes: Iterable["BBox"]) -> "BBox | None":
        boxes = [b for b in boxes if b is not None]
        if not boxes:
            return None
        return cls(
            min(b.xmin for b in boxes), min(b.ymin for b in boxes), min(b.zmin for b in boxes),
            max(b.xmax for b in boxes), max(b.ymax for b in boxes), max(b.zmax for b in boxes),
        )


# --------------------------------------------------------------------------
# ModelBundle —— 解析层向下游提供的唯一几何数据契约
# --------------------------------------------------------------------------
@dataclass
class Part:
    """零件（NX 中的一个 body 或一个装配组件）。"""

    part_id: str
    name: str = ""
    journal_id: str = ""
    part_file: str = ""
    material: str = ""
    body_type: str = "solid"          # solid | sheet | unknown
    is_sheet: bool = False
    volume: float | None = None        # mm^3
    mass: float | None = None          # g
    area: float | None = None          # mm^2
    bbox: BBox | None = None
    face_count: int = 0
    edge_count: int = 0
    occurrence_path: str = ""          # 装配中的路径，如 "ROOT/SUB(1)"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bbox"] = self.bbox.to_dict() if self.bbox else None
        return d

    @classmethod
    def from_dict(cls, d) -> "Part":
        d = dict(d)
        d["bbox"] = BBox.from_dict(d.get("bbox"))
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class Face:
    """面。已经过测量，下游 checker 不需要再回 NX 取面积/半径。"""

    face_id: str
    part_id: str
    tag: int | None = None             # NX 对象 tag，回 NX 做精确测量时要用
    solid_face_type: str = "unknown"   # planar/cylindrical/conical/spherical/toroidal/general/...
    solid_face_code: int = 0           # NX 原始枚举值，便于回溯
    uf_face_type: int = 0              # NX UF 面类型（16 平面 / 17 圆柱 / 18 圆锥 / 20 环面 …）
    point: Vec3 | None = None          # 面上的点；回转面为轴线上一点
    normal: Vec3 | None = None         # 平面法向（朝外）
    axis: Vec3 | None = None           # 回转面轴向（圆柱/圆锥/环面）
    area: float | None = None          # mm^2
    perimeter: float | None = None     # mm
    radius_diameter: float | None = None  # 回转面半径（直径模式下需 /2）
    is_radius: bool = True             # radius_diameter 字段是半径还是直径
    cog: Vec3 | None = None            # 面重心
    bbox: BBox | None = None
    edge_count: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bbox"] = self.bbox.to_dict() if self.bbox else None
        for key in ("cog", "point", "normal", "axis"):
            v = getattr(self, key)
            d[key] = list(v) if v else None
        return d

    @classmethod
    def from_dict(cls, d) -> "Face":
        d = dict(d)
        d["bbox"] = BBox.from_dict(d.get("bbox"))
        for key in ("cog", "point", "normal", "axis"):
            v = d.get(key)
            d[key] = tuple(v) if v else None
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class Edge:
    edge_id: str
    part_id: str
    tag: int | None = None
    curve_type: str = "unknown"
    length: float | None = None
    bbox: BBox | None = None
    face_ids: tuple[str, ...] = ()     # 相邻面（一般为 2 个），用于二面角/圆角判定

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bbox"] = self.bbox.to_dict() if self.bbox else None
        d["face_ids"] = list(self.face_ids)
        return d

    @classmethod
    def from_dict(cls, d) -> "Edge":
        d = dict(d)
        d["bbox"] = BBox.from_dict(d.get("bbox"))
        d["face_ids"] = tuple(d.get("face_ids") or ())
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class Occurrence:
    """装配实例：一个零件在装配中的一次引用。transform 为 4x4 行主序矩阵。"""

    occurrence_id: str
    name: str = ""
    part_ref: str = ""
    parent: str = ""
    transform: list[list[float]] = field(default_factory=lambda: [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
    bbox: BBox | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bbox"] = self.bbox.to_dict() if self.bbox else None
        return d

    @classmethod
    def from_dict(cls, d) -> "Occurrence":
        d = dict(d)
        d["bbox"] = BBox.from_dict(d.get("bbox"))
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class ModelBundle:
    """一次模型解析的完整产物。下游全部 checker 共享同一份。"""

    model_id: str
    source: str = ""                     # 原始 .prt 路径
    nx_version: str = ""
    units: str = "mm"
    created_at: str = ""
    generator: str = "nxdrp"
    schema_version: str = SCHEMA_VERSION
    parts: list[Part] = field(default_factory=list)
    faces: list[Face] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    occurrences: list[Occurrence] = field(default_factory=list)
    adjacency: list[tuple[str, str]] = field(default_factory=list)  # 面-面共边关系
    diagnostics: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    # ---------------- 序列化 ----------------
    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "source": self.source,
            "nx_version": self.nx_version,
            "units": self.units,
            "created_at": self.created_at,
            "generator": self.generator,
            "parts": [p.to_dict() for p in self.parts],
            "faces": [f.to_dict() for f in self.faces],
            "edges": [e.to_dict() for e in self.edges],
            "occurrences": [o.to_dict() for o in self.occurrences],
            "adjacency": [list(a) for a in self.adjacency],
            "diagnostics": self.diagnostics,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ModelBundle":
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ContractError("ModelBundle 含未知字段", [f"未知字段: {sorted(unknown)}"])
        return cls(
            model_id=d.get("model_id") or "unnamed",
            source=d.get("source", ""),
            nx_version=d.get("nx_version", ""),
            units=d.get("units", "mm"),
            created_at=d.get("created_at", ""),
            generator=d.get("generator", "nxdrp"),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            parts=[Part.from_dict(x) for x in d.get("parts", [])],
            faces=[Face.from_dict(x) for x in d.get("faces", [])],
            edges=[Edge.from_dict(x) for x in d.get("edges", [])],
            occurrences=[Occurrence.from_dict(x) for x in d.get("occurrences", [])],
            adjacency=[tuple(x) for x in d.get("adjacency", [])],
            diagnostics=d.get("diagnostics", {}) or {},
            meta=d.get("meta", {}) or {},
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "ModelBundle":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    # ---------------- 便捷访问 ----------------
    def face_map(self) -> dict[str, Face]:
        return {f.face_id: f for f in self.faces}

    def part_map(self) -> dict[str, Part]:
        return {p.part_id: p for p in self.parts}

    def faces_of(self, part_id: str | None = None, face_type: str | None = None) -> list[Face]:
        out = self.faces
        if part_id is not None:
            out = [f for f in out if f.part_id == part_id]
        if face_type is not None:
            types = {face_type} if isinstance(face_type, str) else set(face_type)
            out = [f for f in out if f.solid_face_type in types]
        return out

    @property
    def bbox(self) -> BBox | None:
        return BBox.union([p.bbox for p in self.parts if p.bbox])

    def summary(self) -> dict:
        types: dict[str, int] = {}
        for f in self.faces:
            types[f.solid_face_type] = types.get(f.solid_face_type, 0) + 1
        return {
            "model_id": self.model_id,
            "nx_version": self.nx_version,
            "units": self.units,
            "parts": len(self.parts),
            "faces": len(self.faces),
            "edges": len(self.edges),
            "occurrences": len(self.occurrences),
            "face_types": dict(sorted(types.items(), key=lambda kv: -kv[1])),
        }

    def content_digest(self) -> str:
        h = hashlib.sha256()
        h.update(self.model_id.encode("utf-8"))
        h.update(self.nx_version.encode("utf-8"))
        h.update(str(len(self.parts)).encode())
        for p in self.parts:
            h.update(p.part_id.encode("utf-8"))
        for f in self.faces:
            h.update(f.face_id.encode("utf-8"))
            h.update(f.solid_face_type.encode("utf-8"))
        return h.hexdigest()[:16]

    # ---------------- 校验 ----------------
    def validate(self) -> None:
        problems: list[str] = []
        if not self.model_id:
            problems.append("model_id 不能为空")
        if self.units not in ("mm", "inch"):
            problems.append(f"units 必须是 mm 或 inch，当前 {self.units!r}")
        part_ids = [p.part_id for p in self.parts]
        dup = {x for x in part_ids if part_ids.count(x) > 1}
        if dup:
            problems.append(f"part_id 重复: {sorted(dup)}")
        known = set(part_ids)
        bad = sorted({f.part_id for f in self.faces if f.part_id not in known})
        if bad:
            problems.append(f"face.part_id 未在 parts 中定义: {bad[:5]}")
        bad = sorted({e.part_id for e in self.edges if e.part_id not in known})
        if bad:
            problems.append(f"edge.part_id 未在 parts 中定义: {bad[:5]}")
        face_ids = [f.face_id for f in self.faces]
        dupf = {x for x in face_ids if face_ids.count(x) > 1}
        if dupf:
            problems.append(f"face_id 重复: {sorted(dupf)[:5]}")
        for e in self.edges:
            for fid in e.face_ids:
                if fid not in set(face_ids):
                    problems.append(f"edge {e.edge_id} 引用了不存在的面 {fid}")
                    break
        for p in self.parts:
            if p.bbox and not p.bbox.is_valid():
                problems.append(f"part {p.part_id} 的 bbox 非法")
        if problems:
            raise ContractError("ModelBundle 校验失败", problems)


# --------------------------------------------------------------------------
# RuleBook —— 规则侧契约
# --------------------------------------------------------------------------
@dataclass
class Rule:
    """一条检查规则。阈值全部是数据，不写在代码里（合同第 7 条要求）。"""

    rule_id: str
    check_item_id: str
    process_type: str = ""
    name: str = ""
    enabled: bool = True
    params: dict = field(default_factory=dict)
    version: str = "1.0"
    source_standard: str = ""
    severity: str = "P2"
    notes: str = ""
    owner: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "Rule":
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class RuleBook:
    """一次检查所用的全部规则。"""

    name: str = "default"
    version: str = "1.0"
    schema_version: str = SCHEMA_VERSION
    updated_at: str = ""
    rules: list[Rule] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "version": self.version,
            "updated_at": self.updated_at,
            "rules": [r.to_dict() for r in self.rules],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RuleBook":
        return cls(
            name=d.get("name", "default"),
            version=d.get("version", "1.0"),
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            updated_at=d.get("updated_at", ""),
            rules=[Rule.from_dict(x) for x in d.get("rules", [])],
        )

    @classmethod
    def load(cls, path: str) -> "RuleBook":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)

    def by_item(self) -> dict[str, Rule]:
        return {r.check_item_id: r for r in self.rules}

    def get(self, check_item_id: str) -> Rule | None:
        for r in self.rules:
            if r.check_item_id == check_item_id:
                return r
        return None

    def validate(self) -> None:
        problems: list[str] = []
        ids = [r.check_item_id for r in self.rules]
        dup = {x for x in ids if ids.count(x) > 1}
        if dup:
            problems.append(f"check_item_id 重复: {sorted(dup)}")
        for r in self.rules:
            if r.severity not in SEVERITIES:
                problems.append(f"{r.check_item_id}: severity={r.severity!r} 非法")
        if problems:
            raise ContractError("RuleBook 校验失败", problems)


# --------------------------------------------------------------------------
# Finding —— 全平台唯一的结果契约
# --------------------------------------------------------------------------
@dataclass
class Evidence:
    """几何证据：能让人工复核回到现场。"""

    face_ids: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)
    screenshot_ref: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "Evidence":
        d = dict(d or {})
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class Suggestion:
    """优化建议。必须可落地：要么给出目标尺寸，要么给出结构动作。"""

    text: str = ""
    param_delta: dict = field(default_factory=dict)
    rule_ref: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "Suggestion":
        d = dict(d or {})
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class Detector:
    """产生该结果的 checker 元信息，用于性能归因与责任追溯。"""

    module: str = ""
    version: str = "1.0"
    runtime_ms: float = 0.0
    params_digest: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "Detector":
        d = dict(d or {})
        return cls(**{k: d[k] for k in d if k in cls.__dataclass_fields__})


@dataclass
class Finding:
    """一条缺陷结果。38 个 DFM checker + 安规 + 性能预测全部吐出这个结构。"""

    finding_id: str
    check_item_id: str
    check_item_name: str = ""
    process_type: str = ""
    severity: str = "P2"
    confidence: float = 1.0
    part_refs: list[str] = field(default_factory=list)
    location: Vec3 | None = None
    bbox: BBox | None = None
    path_points: list[Vec3] = field(default_factory=list)
    measured_value: float | None = None
    unit: str = "mm"
    threshold_value: float | None = None
    deviation: float | None = None
    evidence: Evidence = field(default_factory=Evidence)
    suggestion: Suggestion = field(default_factory=Suggestion)
    detector: Detector = field(default_factory=Detector)
    message: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "check_item_id": self.check_item_id,
            "check_item_name": self.check_item_name,
            "process_type": self.process_type,
            "severity": self.severity,
            "confidence": self.confidence,
            "part_refs": list(self.part_refs),
            "location": list(self.location) if self.location else None,
            "bbox": self.bbox.to_dict() if self.bbox else None,
            "path_points": [list(p) for p in self.path_points],
            "measured_value": self.measured_value,
            "unit": self.unit,
            "threshold_value": self.threshold_value,
            "deviation": self.deviation,
            "evidence": self.evidence.to_dict(),
            "suggestion": self.suggestion.to_dict(),
            "detector": self.detector.to_dict(),
            "message": self.message,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        d = dict(d)
        loc = d.get("location")
        return cls(
            finding_id=d.get("finding_id") or "F-000000",
            check_item_id=d.get("check_item_id", ""),
            check_item_name=d.get("check_item_name", ""),
            process_type=d.get("process_type", ""),
            severity=d.get("severity", "P2"),
            confidence=float(d.get("confidence", 1.0) or 1.0),
            part_refs=list(d.get("part_refs") or []),
            location=tuple(loc) if loc else None,
            bbox=BBox.from_dict(d.get("bbox")),
            path_points=[tuple(p) for p in (d.get("path_points") or [])],
            measured_value=d.get("measured_value"),
            unit=d.get("unit", "mm"),
            threshold_value=d.get("threshold_value"),
            deviation=d.get("deviation"),
            evidence=Evidence.from_dict(d.get("evidence")),
            suggestion=Suggestion.from_dict(d.get("suggestion")),
            detector=Detector.from_dict(d.get("detector")),
            message=d.get("message", ""),
            extra=d.get("extra") or {},
        )

    def validate(self) -> None:
        problems: list[str] = []
        if not self.check_item_id:
            problems.append("check_item_id 不能为空")
        if self.severity not in SEVERITIES:
            problems.append(f"severity={self.severity!r} 非法，应为 {SEVERITIES}")
        if not (0.0 <= float(self.confidence) <= 1.0):
            problems.append(f"confidence={self.confidence} 越界，应在 [0,1]")
        if self.measured_value is not None and self.threshold_value is not None and self.deviation is None:
            self.deviation = float(self.measured_value) - float(self.threshold_value)
        if problems:
            raise ContractError(f"Finding {self.finding_id} 校验失败", problems)


# --------------------------------------------------------------------------
# JSON Schema 导出（供前端/工具生成类型，不参与运行）
# --------------------------------------------------------------------------
def _face_schema() -> dict:
    return {
        "type": "object",
        "required": ["face_id", "part_id"],
        "properties": {
            "face_id": {"type": "string"},
            "part_id": {"type": "string"},
            "solid_face_type": {"type": "string"},
            "solid_face_code": {"type": "integer"},
            "area": {"type": ["number", "null"]},
            "perimeter": {"type": ["number", "null"]},
            "radius_diameter": {"type": ["number", "null"]},
            "is_radius": {"type": "boolean"},
            "cog": {"type": ["array", "null"], "items": {"type": "number"}},
            "edge_count": {"type": "integer"},
        },
    }


def schema_documents() -> dict[str, dict]:
    """返回三份契约的 JSON Schema 文档。"""
    return {
        "model_bundle.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://harting.local/nxdrp/model_bundle.schema.json",
            "title": "ModelBundle",
            "type": "object",
            "required": ["model_id", "schema_version"],
            "properties": {
                "schema_version": {"type": "string"},
                "model_id": {"type": "string"},
                "source": {"type": "string"},
                "nx_version": {"type": "string"},
                "units": {"enum": ["mm", "inch"]},
                "parts": {"type": "array"},
                "faces": {"type": "array", "items": _face_schema()},
                "edges": {"type": "array"},
                "occurrences": {"type": "array"},
                "adjacency": {"type": "array"},
                "diagnostics": {"type": "object"},
                "meta": {"type": "object"},
            },
        },
        "rule_book.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://harting.local/nxdrp/rule_book.schema.json",
            "title": "RuleBook",
            "type": "object",
            "required": ["rules"],
            "properties": {
                "schema_version": {"type": "string"},
                "name": {"type": "string"},
                "version": {"type": "string"},
                "updated_at": {"type": "string"},
                "rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["rule_id", "check_item_id"],
                        "properties": {
                            "rule_id": {"type": "string"},
                            "check_item_id": {"type": "string"},
                            "process_type": {"type": "string"},
                            "enabled": {"type": "boolean"},
                            "params": {"type": "object"},
                            "source_standard": {"type": "string"},
                            "severity": {"enum": list(SEVERITIES)},
                        },
                    },
                },
            },
        },
        "finding.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://harting.local/nxdrp/finding.schema.json",
            "title": "Finding",
            "type": "object",
            "required": ["finding_id", "check_item_id", "severity"],
            "properties": {
                "finding_id": {"type": "string"},
                "check_item_id": {"type": "string"},
                "check_item_name": {"type": "string"},
                "process_type": {"type": "string"},
                "severity": {"enum": list(SEVERITIES)},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "part_refs": {"type": "array", "items": {"type": "string"}},
                "location": {"type": ["array", "null"], "items": {"type": "number"}},
                "measured_value": {"type": ["number", "null"]},
                "unit": {"type": "string"},
                "threshold_value": {"type": ["number", "null"]},
                "deviation": {"type": ["number", "null"]},
                "evidence": {"type": "object"},
                "suggestion": {"type": "object"},
                "detector": {"type": "object"},
                "message": {"type": "string"},
            },
        },
    }
