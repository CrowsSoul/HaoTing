# -*- coding: utf-8 -*-
"""Checker 的基类与运行上下文 —— 学生只需要继承它并实现 check()。

设计目标是「即插即用」：
  * 一个 checker = 一个文件 + 一个类 + 一个 CHECKERS 导出；
  * 不需要改任何核心代码，不需要在总表里登记；
  * 自动被注册表发现、自动被管线调度、自动带上契约字段。

最小示例见 nxdrp/checkers/_template.py.txt，真实示例见 nxdrp/checkers/examples/。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .. import catalog
from ..contracts import (
    BBox,
    Detector,
    Edge,
    Evidence,
    Face,
    Finding,
    ModelBundle,
    Part,
    Rule,
    Suggestion,
    Vec3,
)

#: 数据能力声明 -> 判断函数。checker 通过 ``requires`` 声明依赖，
#: 数据缺失时管线会跳过并给出原因，而不是让它算出错误结果。
REQUIREMENTS = {
    "faces": lambda m: len(m.faces) > 0,
    "edges": lambda m: len(m.edges) > 0,
    "adjacency": lambda m: len(m.adjacency) > 0,
    "occurrences": lambda m: len(m.occurrences) > 0,
    "multiple_parts": lambda m: len(m.parts) > 1,
    "normals": lambda m: any(f.normal is not None for f in m.faces),
    "axes": lambda m: any(f.axis is not None for f in m.faces),
    "cylindrical_faces": lambda m: any(f.solid_face_type == "cylindrical" for f in m.faces),
    "toroidal_faces": lambda m: any(f.solid_face_type == "toroidal" for f in m.faces),
    "face_bbox": lambda m: any(f.bbox is not None for f in m.faces),
    "face_area": lambda m: any(f.area is not None for f in m.faces),
    "face_radius": lambda m: any(f.radius_diameter is not None for f in m.faces),
}


class BaseChecker:
    """所有检查器的基类。

    子类必须覆盖：
        check_item_id   对应 nxdrp.catalog 的 ID，例如 "DFM-31"
        name            中文名
        check(ctx)      返回 list[Finding]

    子类可选覆盖：
        version         算法版本，进了报告，便于追溯
        owner           负责人（模块编号 + 姓名），覆盖率报表用
        process_types   适用的工艺，留空表示不限制
        requires        数据能力声明，见 REQUIREMENTS
        default_params  默认阈值，规则库里的 params 会覆盖它
        applies()       自定义跳过逻辑（例如只对塑胶件生效）
    """

    check_item_id: str = ""
    name: str = ""
    version: str = "0.1.0"
    owner: str = ""
    process_types: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    default_params: dict = {}

    # ---------------- 供管线调用 ----------------
    def merged_params(self, rule_params: dict | None) -> dict:
        params = dict(self.default_params or {})
        params.update(rule_params or {})
        return params

    def applies(self, model: ModelBundle, params: dict) -> tuple[bool, str]:
        """返回 (是否执行, 不执行的原因)。"""
        return True, ""

    def check(self, ctx: "CheckContext") -> list[Finding]:  # pragma: no cover - 抽象
        raise NotImplementedError(f"{type(self).__name__} 必须实现 check()")

    # ---------------- 身份 ----------------
    @property
    def module_name(self) -> str:
        return f"{type(self).__module__}.{type(self).__name__}"

    def catalog_item(self) -> catalog.CatalogItem | None:
        return catalog.get(self.check_item_id)

    def describe(self) -> dict:
        item = self.catalog_item()
        return {
            "check_item_id": self.check_item_id,
            "name": self.name or (item.name_cn if item else ""),
            "version": self.version,
            "owner": self.owner,
            "process_types": list(self.process_types),
            "requires": list(self.requires),
            "module": self.module_name,
            "in_catalog": item is not None,
            "phase": item.phase if item else "",
            "difficulty": item.difficulty if item else "",
        }


@dataclass
class CheckContext:
    """一次检查执行时传给 checker 的全部上下文。

    约定：checker 只能读 ctx，不能改 ctx.model —— 结果一律通过 ctx.finding() 产出。
    """

    model: ModelBundle
    rule: Rule
    params: dict
    checker: BaseChecker
    nx: Any = None                      # 可选：回 NX 做精确测量的代理
    started: float = field(default_factory=time.perf_counter)

    _seq: int = 0
    _findings: list[Finding] = field(default_factory=list)

    # ---------------- 数据访问 ----------------
    def param(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)

    def parts(self, body_type: str | None = None) -> list[Part]:
        if body_type is None:
            return list(self.model.parts)
        return [p for p in self.model.parts if p.body_type == body_type]

    def faces(self, part_id: str | None = None, face_type: str | tuple[str, ...] | None = None) -> list[Face]:
        return self.model.faces_of(part_id, face_type)

    def edges(self, part_id: str | None = None) -> list[Edge]:
        if part_id is None:
            return list(self.model.edges)
        return [e for e in self.model.edges if e.part_id == part_id]

    def part(self, part_id: str) -> Part | None:
        for p in self.model.parts:
            if p.part_id == part_id:
                return p
        return None

    def face(self, face_id: str) -> Face | None:
        for f in self.model.faces:
            if f.face_id == face_id:
                return f
        return None

    def adjacency_pairs(self) -> list[tuple[Face, Face]]:
        out: list[tuple[Face, Face]] = []
        fmap = self.model.face_map()
        for a, b in self.model.adjacency:
            fa, fb = fmap.get(a), fmap.get(b)
            if fa and fb:
                out.append((fa, fb))
        return out

    # ---------------- 产出 ----------------
    def next_finding_id(self) -> str:
        self._seq += 1
        return f"{self.checker.check_item_id}-{self._seq:04d}"

    def finding(
        self,
        *,
        severity: str | None = None,
        message: str = "",
        part_refs: Iterable[str] = (),
        location: Vec3 | None = None,
        bbox: BBox | None = None,
        path_points: Iterable[Vec3] = (),
        measured_value: float | None = None,
        threshold_value: float | None = None,
        unit: str = "mm",
        confidence: float = 1.0,
        suggestion_text: str = "",
        suggestion_delta: dict | None = None,
        face_ids: Iterable[str] = (),
        edge_ids: Iterable[str] = (),
        note: str = "",
        extra: dict | None = None,
    ) -> Finding:
        """创建一条 Finding。所有契约字段自动填好，checker 只关心业务字段。"""
        item = self.checker.catalog_item()
        f = Finding(
            finding_id=self.next_finding_id(),
            check_item_id=self.checker.check_item_id,
            check_item_name=self.checker.name or (item.name_cn if item else ""),
            process_type=(item.process_type if item else (self.checker.process_types[0] if self.checker.process_types else "")),
            severity=severity or self.rule.severity or "P2",
            confidence=float(confidence),
            part_refs=list(part_refs),
            location=location,
            bbox=bbox,
            path_points=list(path_points),
            measured_value=measured_value,
            unit=unit,
            threshold_value=threshold_value,
            deviation=(measured_value - threshold_value)
            if (measured_value is not None and threshold_value is not None) else None,
            evidence=Evidence(face_ids=list(face_ids), edge_ids=list(edge_ids), note=note),
            suggestion=Suggestion(text=suggestion_text, param_delta=suggestion_delta or {}, rule_ref=self.rule.rule_id),
            detector=Detector(
                module=self.checker.module_name,
                version=self.checker.version,
                runtime_ms=(time.perf_counter() - self.started) * 1000.0,
            ),
            message=message,
            extra=extra or {},
        )
        f.validate()
        self._findings.append(f)
        return f
