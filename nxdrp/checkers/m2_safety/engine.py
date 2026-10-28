# -*- coding: utf-8 -*-
"""M2 共用算法：网络识别、IEC 阈值、精确间隙和表面最短路。"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import re
import struct
import weakref
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Iterable

from ...contracts import BBox, Face, ModelBundle
from ...geom import bbox_gap, dist


class SafetyInputError(ValueError):
    """输入不足，调用方应跳过而不是猜测。"""


class ThresholdUnavailable(SafetyInputError):
    """当前规则表没有覆盖该标准组合。"""


@dataclass
class ElectricalNetwork:
    network_id: str
    part_ids: list[str] = field(default_factory=list)
    face_ids: list[str] = field(default_factory=list)
    potential_v: float | None = None
    contact_points: list[tuple[float, float, float]] = field(default_factory=list)


@dataclass
class SafetyMeasurement:
    kind: str
    network_a: str
    network_b: str
    measured_mm: float
    threshold_mm: float
    method: str
    confidence: float
    point_id: str = ""
    part_refs: list[str] = field(default_factory=list)
    face_ids: list[str] = field(default_factory=list)
    p1: tuple[float, float, float] | None = None
    p2: tuple[float, float, float] | None = None
    path_points: list[tuple[float, float, float]] = field(default_factory=list)
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def compliant(self) -> bool:
        return self.measured_mm + 1e-9 >= self.threshold_mm

    @property
    def deviation_mm(self) -> float:
        return self.measured_mm - self.threshold_mm

    @property
    def location(self) -> tuple[float, float, float] | None:
        if self.p1 is not None and self.p2 is not None:
            return tuple((a + b) / 2.0 for a, b in zip(self.p1, self.p2))
        if self.path_points:
            return self.path_points[len(self.path_points) // 2]
        return self.p1 or self.p2


_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_PROFILE_PATH = os.path.join(_PROJECT_ROOT, "rules", "iec_60664_1_profiles.json")
_MEASUREMENT_CACHE: dict[
    tuple[int, str, str],
    tuple[weakref.ReferenceType[ModelBundle], list[SafetyMeasurement]],
] = {}
_LATEST_CACHE: dict[
    tuple[int, str],
    tuple[weakref.ReferenceType[ModelBundle], list[SafetyMeasurement]],
] = {}


def _json_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _safety_meta(model: ModelBundle) -> dict:
    value = (model.meta or {}).get("safety", {})
    return value if isinstance(value, dict) else {}


def merged_safety_params(model: ModelBundle, params: dict) -> dict:
    """合并通用规则和模型工况；模型自身的安规 profile 优先。"""
    #通用规则参数rules/dfm_default.json
    merged = dict(params or {})
    #模型参数
    meta = _safety_meta(model)
    profile = meta.get("profile")
    if isinstance(profile, dict):
        merged.update(profile)
    return merged


def _profile_path(params: dict | None = None) -> str:
    configured = str((params or {}).get("iec_profile_path") or "").strip()
    if not configured:
        return _PROFILE_PATH
    if os.path.isabs(configured):
        return configured
    project_path = os.path.join(_PROJECT_ROOT, configured)
    if os.path.isfile(project_path):
        return project_path
    return os.path.abspath(configured)


def _load_profiles(params: dict | None = None) -> dict:
    path = _profile_path(params)
    if not os.path.isfile(path):
        raise ThresholdUnavailable(f"IEC 限值表不存在: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _select_row(rows: list[dict], key: str, value: float) -> dict:
    for row in rows:
        if value <= float(row[key]):
            return row
    raise ThresholdUnavailable(f"{value:g} V 超出当前 IEC 规则数据覆盖范围")


def _normalize_material_group(value: Any) -> str:
    group = str(value or "").replace(" ", "")
    aliases = {"IIIA": "IIIa", "IIIB": "IIIb", "3A": "IIIa", "3B": "IIIb"}
    upper = group.upper()
    return aliases.get(upper, upper if upper in ("I", "II") else group)


def _material_group(params: dict, profiles: dict) -> str:
    explicit = _normalize_material_group(params.get("material_group"))
    cti = params.get("cti")
    derived = ""
    if cti is not None:
        try:
            cti_value = float(cti)
        except (TypeError, ValueError) as exc:
            raise ThresholdUnavailable("CTI 必须是数值") from exc
        for row in profiles["material_groups"]["rows"]:
            lower = float(row["cti_min"])
            upper = row.get("cti_max_exclusive")
            if cti_value >= lower and (upper is None or cti_value < float(upper)):
                derived = str(row["group"])
                break
        if not derived:
            raise ThresholdUnavailable(f"CTI={cti_value:g} 超出材料组定义范围")
    if explicit and explicit not in ("I", "II", "IIIa", "IIIb"):
        raise ThresholdUnavailable("材料组别必须为 I/II/IIIa/IIIb")
    # RuleBook may carry a conservative material-group override alongside a
    # nominal CTI. The explicit controlled group is authoritative in that case.
    group = explicit or derived
    if not group:
        raise ThresholdUnavailable("缺少材料组别；请提供 material_group 或 cti")
    return group


def _numbers(value: Any) -> list[float]:
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(value or ""))]


def _rated_voltage_row(rows: list[dict], rated: float, params: dict) -> dict:
    voltage_to_earth = params.get("voltage_to_earth_v")
    if voltage_to_earth is not None:
        return _select_row(
            rows, "voltage_line_to_neutral_max_v", float(voltage_to_earth)
        )

    # Table F.1 also lists common nominal systems such as 230/400 V.
    # Prefer an exact nominal-system match before treating rated_voltage_v as
    # a line-to-neutral value.
    for row in rows:
        nominal = row.get("nominal_three_phase_v", []) + row.get(
            "nominal_single_phase_v", []
        )
        if any(abs(number - rated) <= 1e-9 for item in nominal for number in _numbers(item)):
            return row
    return _select_row(rows, "voltage_line_to_neutral_max_v", rated)


def _clearance_altitude_factor(
    profiles: dict, altitude: float, explicit: Any
) -> tuple[float, str]:
    if explicit is not None:
        factor = float(explicit)
        if factor <= 0:
            raise ThresholdUnavailable("altitude_correction_factor 必须大于 0")
        return factor, "explicit altitude_correction_factor"
    if altitude <= 2000:
        return 1.0, "Table F.2 (up to 2 000 m)"
    for row in profiles["tables"]["A.2"]["rows"]:
        if altitude <= float(row["altitude_m"]):
            return float(row["clearance_multiplication_factor"]), str(
                row["source_table"]
            )
    raise ThresholdUnavailable("海拔超过 Table A.2 的 20 000 m 覆盖范围")


def clearance_threshold_mm(params: dict) -> tuple[float, str]:
    #用户指定距离，不查表，直接返回
    direct = params.get("min_clearance_mm")
    if direct is not None:
        return float(direct), str(params.get("source_standard") or "RuleBook.min_clearance_mm")

    #查IEC表
    profiles = _load_profiles(params)
    tables = profiles["tables"]
    pollution = int(params.get("pollution_degree", 2))
    if pollution not in (1, 2, 3, 4):
        raise ThresholdUnavailable("污染等级必须为 1/2/3/4")
    rated = float(params.get("rated_voltage_v", 0))
    if rated <= 0:
        raise ThresholdUnavailable("额定电压 rated_voltage_v 必须大于 0")
    category = str(params.get("overvoltage_category", "")).upper()
    if category not in ("I", "II", "III", "IV"):
        raise ThresholdUnavailable("过电压类别必须为 I/II/III/IV")

    #根据额定电压和过压类型得到额定冲击耐受电压
    f1_row = _rated_voltage_row(tables["F.1"]["rows"], rated, params)
    impulse_v = float(f1_row["rated_impulse_withstand_v"][category])
    #根据额定冲击耐受电压、电场条件和污染等级得到基础距离
    f2_row = _select_row(
        tables["F.2"]["rows"], "required_impulse_withstand_kv", impulse_v / 1000.0
    )
    field = str(params.get("field_condition", "case_a")).strip().lower()
    field_aliases = {
        "a": "case_a",
        "case a": "case_a",
        "inhomogeneous": "case_a",
        "inhomogeneous field": "case_a",
        "b": "case_b",
        "case b": "case_b",
        "homogeneous": "case_b",
        "homogeneous field": "case_b",
    }
    field = field_aliases.get(field, field)
    if field not in ("case_a", "case_b"):
        raise ThresholdUnavailable(
            "场条件 field_condition 必须为 case_a/inhomogeneous 或 case_b/homogeneous"
        )
    base = float(f2_row[f"{field}_mm"][f"pd{pollution}"])

    altitude = float(params.get("altitude_m", 2000))
    factor, altitude_source = _clearance_altitude_factor(
        profiles, altitude, params.get("altitude_correction_factor")
    )
    value = base * factor
    #溯源
    source = (
        f"{profiles['standard']} / Table F.1 "
        f"({rated:g} V, category {category} -> {impulse_v / 1000:g} kV) / "
        f"Table F.2 ({field}, PD{pollution}) / "
        f"{altitude_source}, factor {factor:g}"
    )
    return round(value, 6), source


def _creepage_column(
    pollution: int, group: str, printed_wiring_material: bool
) -> str:
    if pollution == 1:
        return "pwm_pd1_all_mm" if printed_wiring_material else "pd1_all_mm"
    if pollution == 2:
        if printed_wiring_material:
            if group == "IIIb":
                raise ThresholdUnavailable(
                    "Table F.5 的印制线路材料污染等级 2 列不适用于材料组 IIIb"
                )
            return "pwm_pd2_except_IIIb_mm"
        suffix = "III" if group in ("IIIa", "IIIb") else group
        return f"pd2_{suffix}_mm"
    if pollution == 3:
        suffix = "III" if group in ("IIIa", "IIIb") else group
        return f"pd3_{suffix}_mm"
    raise ThresholdUnavailable(
        "污染等级 4 存在持续导电污染，IEC 60664-1:2020 4.5.3 不规定爬电距离尺寸"
    )


def _creepage_value(rows: list[dict], voltage: float, column: str, interpolate: bool) -> float:
    if voltage <= 0:
        raise ThresholdUnavailable("工作电压 working_voltage_v 必须大于 0")
    if voltage > float(rows[-1]["voltage_rms_v"]):
        raise ThresholdUnavailable(f"{voltage:g} V 超出 Table F.5 覆盖范围")

    upper_index = next(
        index for index, row in enumerate(rows)
        if voltage <= float(row["voltage_rms_v"])
    )
    upper = rows[upper_index]
    upper_value = upper.get(column)
    if upper_value is None:
        raise ThresholdUnavailable(
            f"Table F.5 在 {voltage:g} V 对应组合没有可用爬电距离数值"
        )
    #三种情况不需要插值，直接返回上界值
    if (
        not interpolate
        or upper_index == 0
        or abs(voltage - float(upper["voltage_rms_v"])) <= 1e-9
    ):
        return float(upper_value)

    lower = rows[upper_index - 1]
    lower_value = lower.get(column)
    if lower_value is None:
        return float(upper_value)
    low_v = float(lower["voltage_rms_v"])
    high_v = float(upper["voltage_rms_v"])
    ratio = (voltage - low_v) / (high_v - low_v)
    return float(lower_value) + ratio * (float(upper_value) - float(lower_value))


def creepage_threshold_mm(params: dict) -> tuple[float, str]:
    direct = params.get("min_creepage_mm")
    if direct is not None:
        return float(direct), str(params.get("source_standard") or "RuleBook.min_creepage_mm")

    profiles = _load_profiles(params)
    pollution = int(params.get("pollution_degree", 2))
    if pollution not in (1, 2, 3, 4):
        raise ThresholdUnavailable("污染等级必须为 1/2/3/4")
    voltage = float(params.get("working_voltage_v", params.get("rated_voltage_v", 0)))
    group = _material_group(params, profiles)
    printed = bool(params.get("printed_wiring_material", False))
    column = _creepage_column(pollution, group, printed)
    interpolate = bool(params.get("interpolate_creepage", True))
    #允许在两档之间线性插值
    value = _creepage_value(
        profiles["tables"]["F.5"]["rows"], voltage, column, interpolate
    )
    notes = []
    if group == "IIIb" and pollution == 3 and voltage > 630:
        notes.append("Table F.5 footnote b: group IIIb above 630 V is not recommended")
    if interpolate:
        notes.append("linear interpolation permitted by Table F.5 footnote e")
    suffix = " / " + " / ".join(notes) if notes else ""
    source = (
        f"{profiles['standard']} / Table F.5 "
        f"({voltage:g} V, PD{pollution}, group {group}, column {column}){suffix}"
    )
    return round(value, 6), source


def _point(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return None


def resolve_networks(model: ModelBundle, params: dict) -> list[ElectricalNetwork]:
    #外部规则没有就去模型元数据里找
    meta = _safety_meta(model)
    raw = params.get("networks")
    if raw is None:
        raw = meta.get("networks")

    #解析网络
    networks = []
    if isinstance(raw, list):
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            nid = str(item.get("network_id") or item.get("id") or f"N{idx + 1}")
            points = [_point(x) for x in item.get("contact_points", [])]
            networks.append(
                ElectricalNetwork(
                    network_id=nid,
                    part_ids=[str(x) for x in item.get("part_ids", [])],
                    face_ids=[str(x) for x in item.get("face_ids", [])],
                    potential_v=float(item["potential_v"]) if item.get("potential_v") is not None else None,
                    contact_points=[x for x in points if x is not None],
                )
            )
    if networks:
        return networks
    #若无图纸，靠常识
    # 仅对名称/材料明确的导体作保守推断，不把未知零件擅自当成带电体。
    conductive_materials = ("CU", "COPPER", "BRASS", "BRONZE", "ALUMIN", "STEEL", "铜", "铝")
    conductor_names = ("TERMINAL", "CONTACT", "PIN", "CONDUCTOR", "ELECTRODE", "端子", "触点", "插针")
    #遍历所有零件。把零件的名字、路径、材质拼成一个长字符串
    for part in model.parts:
        label = " ".join((part.name, part.occurrence_path, part.material)).upper()
        if not any(token in label for token in conductor_names + conductive_materials):
            continue
        #如果命中关键字，就把这个零件当成一个独立网络
        faces = [f.face_id for f in model.faces if f.part_id == part.part_id]
        networks.append(
            ElectricalNetwork(
                network_id=part.part_id,
                part_ids=[part.part_id],
                face_ids=faces,
                contact_points=[],
            )
        )
    return networks

#在找到的网络中，决定到底哪两个网络之间需要去测量距离
def network_pairs(networks: list[ElectricalNetwork], model: ModelBundle, params: dict) -> list[tuple[ElectricalNetwork, ElectricalNetwork]]:
    meta = _safety_meta(model)
    raw = params.get("network_pairs")
    if raw is None:
        raw = meta.get("network_pairs")
    by_id = {n.network_id: n for n in networks}
    out = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                a, b = item.get("a"), item.get("b")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                a, b = item[0], item[1]
            else:
                continue
            #找到了一组有效的配对，就把对应的网络对象组合成元组
            if str(a) in by_id and str(b) in by_id and str(a) != str(b):
                out.append((by_id[str(a)], by_id[str(b)]))
        if out:
            return out
    #如果没配置，就“自动两两配对”
    for a, b in combinations(networks, 2):
        #电压相同，不可能发生空气击穿，跳过
        if a.potential_v is not None and b.potential_v is not None and a.potential_v == b.potential_v:
            continue
        out.append((a, b))
    return out


def _network_faces(model: ModelBundle, network: ElectricalNetwork) -> list[Face]:
    face_ids = set(network.face_ids)
    part_ids = set(network.part_ids)
    return [
        face for face in model.faces
        if (face_ids and face.face_id in face_ids) or (not face_ids and face.part_id in part_ids)
    ]


def _network_evidence_face_ids(model: ModelBundle, network: ElectricalNetwork) -> list[str]:
    """Return explicit face IDs, or derive them from the network's part IDs."""
    if network.face_ids:
        return list(dict.fromkeys(network.face_ids))
    part_ids = set(network.part_ids)
    return list(dict.fromkeys(
        face.face_id for face in model.faces if face.part_id in part_ids
    ))


def _network_parts(model: ModelBundle, network: ElectricalNetwork):
    wanted = set(network.part_ids)
    return [part for part in model.parts if part.part_id in wanted]


def _nearest_bbox_points(a: BBox, b: BBox) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    def axis(a0, a1, b0, b1):
        if a1 < b0:
            return a1, b0
        if b1 < a0:
            return a0, b1
        mid = (max(a0, b0) + min(a1, b1)) / 2.0
        return mid, mid

    ax, bx = axis(a.xmin, a.xmax, b.xmin, b.xmax)
    ay, by = axis(a.ymin, a.ymax, b.ymin, b.ymax)
    az, bz = axis(a.zmin, a.zmax, b.zmin, b.zmax)
    return (ax, ay, az), (bx, by, bz)


def _explicit_measurements(model: ModelBundle, params: dict, key: str) -> list[dict]:
    meta = _safety_meta(model)
    raw = params.get(key)
    if raw is None:
        raw = meta.get(key)
    return [x for x in (raw or []) if isinstance(x, dict)]


def _measurement_from_dict(
    model: ModelBundle,
    item: dict,
    kind: str,
    threshold: float,
    networks: dict[str, ElectricalNetwork],
) -> SafetyMeasurement | None:
    try:
        value = float(item.get("distance_mm", item.get("measured_mm")))
    except (TypeError, ValueError):
        return None
    a = str(item.get("network_a") or item.get("a") or "")
    b = str(item.get("network_b") or item.get("b") or "")
    if not a or not b:
        return None
    na, nb = networks.get(a), networks.get(b)
    parts = list(dict.fromkeys((na.part_ids if na else []) + (nb.part_ids if nb else [])))
    faces = [str(x) for x in item.get("face_ids", [])]
    if not faces:
        faces = list(dict.fromkeys(
            (_network_evidence_face_ids(model, na) if na else [])
            + (_network_evidence_face_ids(model, nb) if nb else [])
        ))
    path = [_point(x) for x in item.get("path_points", [])]
    return SafetyMeasurement(
        kind=kind,
        network_a=a,
        network_b=b,
        measured_mm=value,
        threshold_mm=threshold,
        method=str(item.get("method") or "provided"),
        confidence=float(item.get("confidence", 1.0)),
        point_id=str(
            item.get("point_id")
            or item.get("measurement_id")
            or item.get("id")
            or ""
        ),
        part_refs=parts,
        face_ids=faces,
        p1=_point(item.get("p1")),
        p2=_point(item.get("p2")),
        path_points=[x for x in path if x is not None],
        note=str(item.get("note") or "由模型安规元数据提供"),
    )


def has_clearance_input(model: ModelBundle, params: dict) -> bool:
    if _explicit_measurements(model, params, "clearance_measurements"):
        return True
    if params.get("allow_bbox_fallback"):
        return True
    return bool(model.source and model.source.lower().endswith(".prt") and os.path.isfile(model.source))


def has_creepage_input(model: ModelBundle, params: dict) -> bool:
    if _explicit_measurements(model, params, "creepage_measurements"):
        return True
    meta = _safety_meta(model)
    return bool(
        params.get("surface_graph")
        or meta.get("surface_graph")
        or params.get("surface_mesh_path")
        or meta.get("surface_mesh_path")
    )


def clearance_input_issue(model: ModelBundle, params: dict) -> str:
    #如果有测量数据
    explicit = _explicit_measurements(model, params, "clearance_measurements")
    if explicit:
        by_id = {network.network_id: network for network in resolve_networks(model, params)}
        for item in explicit:
            try:
                float(item.get("distance_mm", item.get("measured_mm")))
            except (TypeError, ValueError):
                continue
            a = str(item.get("network_a") or item.get("a") or "")
            b = str(item.get("network_b") or item.get("b") or "")
            if a not in by_id or b not in by_id:
                continue
            faces = [str(x) for x in item.get("face_ids", [])]
            if not faces:
                faces = (
                    _network_evidence_face_ids(model, by_id[a])
                    + _network_evidence_face_ids(model, by_id[b])
                )
            if faces:
                return ""
        return "clearance_measurements 缺少有效距离、网络配对或证据面"
    #没有现成数据，安排NX去算距离
    networks = resolve_networks(model, params)
    for na, nb in network_pairs(networks, model, params):
        if not (
            _network_evidence_face_ids(model, na)
            and _network_evidence_face_ids(model, nb)
        ):
            return f"网络 {na.network_id}/{nb.network_id} 缺少可定位的 face_ids"
    return ""


def creepage_input_issue(model: ModelBundle, params: dict) -> str:
    """Validate creepage data so incomplete input is skipped with a reason."""
    explicit = _explicit_measurements(model, params, "creepage_measurements")
    if explicit:
        by_id = {network.network_id: network for network in resolve_networks(model, params)}
        for item in explicit:
            try:
                float(item.get("distance_mm", item.get("measured_mm")))
            except (TypeError, ValueError):
                continue
            a = str(item.get("network_a") or item.get("a") or "")
            b = str(item.get("network_b") or item.get("b") or "")
            if a not in by_id or b not in by_id:
                continue
            faces = [str(x) for x in item.get("face_ids", [])]
            if not faces:
                faces = (
                    _network_evidence_face_ids(model, by_id[a])
                    + _network_evidence_face_ids(model, by_id[b])
                )
            if faces:
                return ""
        return "creepage_measurements 缺少有效距离、网络配对或证据面"

    meta = _safety_meta(model)
    graph = params.get("surface_graph") or meta.get("surface_graph")
    if isinstance(graph, dict):
        try:
            nodes, adjacency, terminals, _ = _graph_from_config(graph)
            networks = resolve_networks(model, params)
            pairs = network_pairs(networks, model, params)
            nearest_count = int(params.get("terminal_vertex_count", 3))
            for na, nb in pairs:
                if not (
                    _network_evidence_face_ids(model, na)
                    and _network_evidence_face_ids(model, nb)
                ):
                    raise SafetyInputError(
                        f"网络 {na.network_id}/{nb.network_id} 缺少可定位的 face_ids"
                    )
                starts = _terminal_nodes(
                    terminals.get(na.network_id, []), len(nodes), na.network_id
                )
                goals = _terminal_nodes(
                    terminals.get(nb.network_id, []), len(nodes), nb.network_id
                )
                if not starts:
                    starts = _nearest_nodes(nodes, na.contact_points, nearest_count)
                if not goals:
                    goals = _nearest_nodes(nodes, nb.contact_points, nearest_count)
                _dijkstra(nodes, adjacency, starts, goals)
        except (SafetyInputError, TypeError, ValueError) as exc:
            return str(exc)
        return ""

    mesh_path = params.get("surface_mesh_path") or meta.get("surface_mesh_path")
    if mesh_path:
        if not os.path.isabs(mesh_path):
            base = os.path.dirname(model.source) if model.source else os.getcwd()
            mesh_path = os.path.abspath(os.path.join(base, mesh_path))
        if not os.path.isfile(mesh_path):
            return f"绝缘体 STL 不存在: {mesh_path}"
        networks = resolve_networks(model, params)
        if any(not network.contact_points for network in networks):
            return "STL 爬电计算要求每个电气网络提供 contact_points"
        if any(not _network_evidence_face_ids(model, network) for network in networks):
            return "STL 爬电计算要求每个电气网络可关联 face_ids"
    return ""

#当前模型 + 当前这些参数如果算过，直接用
def _cache_key(model: ModelBundle, kind: str, params: dict) -> tuple[int, str, str]:
    relevant = {
        key: params.get(key)
        for key in (
            "networks", "network_pairs", "clearance_measurements", "creepage_measurements",
            "surface_graph", "surface_mesh_path", "allow_bbox_fallback",
            "min_clearance_mm", "min_creepage_mm", "rated_voltage_v", "working_voltage_v",
            "pollution_degree", "material_group", "overvoltage_category", "altitude_m",
        )
    }
    relevant["meta"] = _safety_meta(model)
    return id(model), kind, _json_digest(relevant)


def latest_measurements(model: ModelBundle, kind: str) -> list[SafetyMeasurement]:
    key = (id(model), kind)
    cached = _LATEST_CACHE.get(key)
    if cached is None:
        return []
    owner, values = cached
    if owner() is not model:
        _LATEST_CACHE.pop(key, None)
        return []
    return list(values)


def _store_measurements(model: ModelBundle, kind: str, key, values: list[SafetyMeasurement]):
    cached = (weakref.ref(model), list(values))
    _MEASUREMENT_CACHE[key] = cached
    _LATEST_CACHE[(id(model), kind)] = cached
    return list(values)


def clearance_measurements(ctx, threshold: float) -> list[SafetyMeasurement]:
    model, params = ctx.model, merged_safety_params(ctx.model, ctx.params)
    #查缓存
    key = _cache_key(model, "clearance", params)
    cached = _MEASUREMENT_CACHE.get(key)
    if cached is not None and cached[0]() is model:
        return list(cached[1])
    _MEASUREMENT_CACHE.pop(key, None)

    networks = resolve_networks(model, params)
    pairs = network_pairs(networks, model, params)
    by_id = {n.network_id: n for n in networks}
    if len(networks) < 2 or not pairs:
        raise SafetyInputError("至少需要两个不同电位的电气网络")

    #去JSON里找有没有提前写好的，有，解析成标准格式，存入缓存，直接返回
    explicit = [
        _measurement_from_dict(model, item, "clearance", threshold, by_id)
        for item in _explicit_measurements(model, params, "clearance_measurements")
    ]
    explicit = [x for x in explicit if x is not None]
    if explicit:
        return _store_measurements(model, "clearance", key, explicit)

    pair_candidates = {}
    all_tag_pairs = []
    max_pairs = int(params.get("max_exact_face_pairs", 5000))
    for na, nb in pairs:
        candidates = []
        #拿 HV 的所有面
        for fa in _network_faces(model, na):
            #拿 LV 的所有面
            for fb in _network_faces(model, nb):
                if fa.tag is None or fb.tag is None:
                    continue
                #用包围盒（bbox）先粗略算一下这俩面离多远
                gap = bbox_gap(fa.bbox, fb.bbox)
                candidates.append((gap, fa, fb))
        #按粗略距离从小到大排序
        candidates.sort(key=lambda x: x[0])
        #只留前 5000 个离得最近的，最危险的
        candidates = candidates[:max_pairs]
        pair_candidates[(na.network_id, nb.network_id)] = candidates
        all_tag_pairs.extend((fa.tag, fb.tag) for _, fa, fb in candidates)

    exact = {}
    exact_method = ""
    if ctx.nx is not None and hasattr(ctx.nx, "prefetch") and hasattr(ctx.nx, "distance"):
        #5000对给NX
        ctx.nx.prefetch(all_tag_pairs)
        for candidates in pair_candidates.values():
            for _, fa, fb in candidates:
                exact[(int(fa.tag), int(fb.tag))] = {
                    "distance": ctx.nx.distance(fa.tag, fb.tag),
                    "p1": None,
                    "p2": None,
                }
        exact_method = "nx-prefetch"
    #用真实的 .prt 文件计算
    elif model.source and model.source.lower().endswith(".prt") and os.path.isfile(model.source):
        from ...adapters.nx_batch import NxBatchAdapter

        adapter = NxBatchAdapter()
        if adapter.available() and all_tag_pairs:
            payload = adapter.measure_distance(model.source, all_tag_pairs, kind="face")
            for item in payload.get("pairs", []):
                exact[(int(item["a"]), int(item["b"]))] = {
                    "distance": float(item["distance"]),
                    "p1": _point(item.get("p1")),
                    "p2": _point(item.get("p2")),
                }
            exact_method = "nx-batch"

    results = []
    for na, nb in pairs:
        candidates = pair_candidates.get((na.network_id, nb.network_id), [])
        best = None
        for _, fa, fb in candidates:
            item = exact.get((int(fa.tag), int(fb.tag))) or exact.get((int(fb.tag), int(fa.tag)))
            if item is None or item["distance"] is None:
                continue
            if best is None or float(item["distance"]) < best[0]:
                best = (float(item["distance"]), fa, fb, item)
        if best is not None:
            value, fa, fb, item = best
            results.append(
                SafetyMeasurement(
                    kind="clearance",
                    network_a=na.network_id,
                    network_b=nb.network_id,
                    measured_mm=value,
                    threshold_mm=threshold,
                    method=exact_method,
                    confidence=0.99,
                    part_refs=list(dict.fromkeys(na.part_ids + nb.part_ids)),
                    face_ids=[fa.face_id, fb.face_id],
                    p1=item["p1"] or fa.cog or (fa.bbox.center if fa.bbox else None),
                    p2=item["p2"] or fb.cog or (fb.bbox.center if fb.bbox else None),
                    note="NX Measurement.GetMinimumDistance 批量精确测距",
                )
            )
            continue

        if not params.get("allow_bbox_fallback"):
            continue
        bbox_best = None
        for pa in _network_parts(model, na):
            for pb in _network_parts(model, nb):
                if pa.bbox is None or pb.bbox is None:
                    continue
                value = bbox_gap(pa.bbox, pb.bbox)
                if bbox_best is None or value < bbox_best[0]:
                    bbox_best = (value, pa, pb)
        if bbox_best is None:
            continue
        value, pa, pb = bbox_best
        p1, p2 = _nearest_bbox_points(pa.bbox, pb.bbox)
        faces = []
        fa = _network_faces(model, na)
        fb = _network_faces(model, nb)
        if fa:
            faces.append(fa[0].face_id)
        if fb:
            faces.append(fb[0].face_id)
        results.append(
            SafetyMeasurement(
                kind="clearance",
                network_a=na.network_id,
                network_b=nb.network_id,
                measured_mm=value,
                threshold_mm=threshold,
                method="bbox-lower-bound",
                confidence=float(params.get("bbox_confidence", 0.55)),
                part_refs=[pa.part_id, pb.part_id],
                face_ids=faces,
                p1=p1,
                p2=p2,
                note="包围盒粗筛下界，必须由 NX 或 AutoCrear 复核",
            )
        )
    return _store_measurements(model, "clearance", key, results)


def _graph_from_config(
    config: dict,
) -> tuple[list[tuple[float, float, float]], list[list[tuple[int, float]]], dict, dict]:
    points = [_point(x) for x in config.get("nodes", [])]
    if not points or any(x is None for x in points):
        raise SafetyInputError("surface_graph.nodes 必须是三维坐标数组")
    nodes = [x for x in points if x is not None]
    adjacency = [[] for _ in nodes]

    edges = config.get("edges", [])
    if not edges and config.get("triangles"):
        seen = set()
        for tri in config["triangles"]:
            if not isinstance(tri, (list, tuple)) or len(tri) < 3:
                continue
            for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
                seen.add(tuple(sorted((int(a), int(b)))))
        edges = [list(x) for x in sorted(seen)]

    rule_info = {
        "adjusted_edge_count": 0,
        "excluded_edge_count": 0,
        "feature_kinds": [],
    }
    for item in edges:
        kind = ""
        if isinstance(item, dict):
            a, b = item.get("a"), item.get("b")
            kind = str(item.get("kind") or "").strip().lower()
            if item.get("blocked") or item.get("ignored") or item.get("eligible") is False:
                rule_info["excluded_edge_count"] += 1
                if kind:
                    rule_info["feature_kinds"].append(kind)
                continue
            if a is None or b is None:
                continue
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            a, b = item[0], item[1]
        else:
            continue

        a, b = int(a), int(b)
        if not (0 <= a < len(nodes) and 0 <= b < len(nodes)) or a == b:
            continue
        geometric_weight = dist(nodes[a], nodes[b])
        if isinstance(item, dict):
            base_weight = float(item.get("weight_mm", geometric_weight))
            factor = float(item.get("length_factor", 1.0))
            extra = float(item.get("extra_length_mm", 0.0))
            weight = base_weight * factor + extra
            if (
                "weight_mm" in item
                or abs(factor - 1.0) > 1e-12
                or abs(extra) > 1e-12
            ):
                rule_info["adjusted_edge_count"] += 1
            if kind:
                rule_info["feature_kinds"].append(kind)
        else:
            weight = float(item[2]) if len(item) >= 3 else geometric_weight
        if not math.isfinite(weight) or weight < 0:
            raise SafetyInputError(f"surface_graph 边 {a}-{b} 的权重必须是非负有限数")
        adjacency[a].append((b, weight))
        adjacency[b].append((a, weight))
    if not any(adjacency):
        raise SafetyInputError("surface_graph 没有可用于爬电计算的有效边")
    rule_info["feature_kinds"] = sorted(set(rule_info["feature_kinds"]))
    return nodes, adjacency, config.get("terminals", {}) or {}, rule_info


def _read_stl(path: str) -> list[tuple[tuple[float, float, float], ...]]:
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) >= 84:
        count = struct.unpack("<I", raw[80:84])[0]
        if 84 + count * 50 == len(raw):
            triangles = []
            offset = 84
            for _ in range(count):
                coords = struct.unpack("<9f", raw[offset + 12:offset + 48])
                triangles.append(tuple(tuple(float(coords[i + j]) for j in range(3)) for i in (0, 3, 6)))
                offset += 50
            return triangles

    text = raw.decode("utf-8", "ignore")
    vertices = []
    for line in text.splitlines():
        fields = line.strip().split()
        if len(fields) == 4 and fields[0].lower() == "vertex":
            vertices.append(tuple(float(x) for x in fields[1:4]))
    return [tuple(vertices[i:i + 3]) for i in range(0, len(vertices) - 2, 3)]


def _graph_from_stl(path: str, weld_tol: float) -> tuple[list, list]:
    triangles = _read_stl(path)
    if not triangles:
        raise SafetyInputError(f"STL 中没有三角面片: {path}")
    scale = 1.0 / max(weld_tol, 1e-9)
    node_map = {}
    nodes = []
    edges = set()

    def node_id(point):
        key = tuple(int(round(v * scale)) for v in point)
        if key not in node_map:
            node_map[key] = len(nodes)
            nodes.append(tuple(float(v) for v in point))
        return node_map[key]

    for tri in triangles:
        ids = [node_id(p) for p in tri]
        for a, b in ((ids[0], ids[1]), (ids[1], ids[2]), (ids[2], ids[0])):
            if a != b:
                edges.add(tuple(sorted((a, b))))
    adjacency = [[] for _ in nodes]
    for a, b in edges:
        weight = dist(nodes[a], nodes[b])
        adjacency[a].append((b, weight))
        adjacency[b].append((a, weight))
    return nodes, adjacency


def _nearest_nodes(nodes: list[tuple[float, float, float]], points: Iterable[tuple[float, float, float]], count: int) -> list[int]:
    ranked = []
    #遍历绝缘体上的每一个网格点
    for idx, node in enumerate(nodes):
        #计算当前网格点，到每一个金属触点的距离，取最小
        best = min((dist(node, point) for point in points), default=float("inf"))
        ranked.append((best, idx))
    return [idx for _, idx in sorted(ranked)[:max(1, count)] if math.isfinite(_)]


def _terminal_nodes(values: Any, node_count: int, network_id: str) -> list[int]:
    if values in (None, []):
        return []
    if not isinstance(values, (list, tuple)):
        raise SafetyInputError(f"网络 {network_id} 的 terminals 必须是节点编号数组")
    out = []
    for value in values:
        try:
            node = int(value)
        except (TypeError, ValueError) as exc:
            raise SafetyInputError(f"网络 {network_id} 包含无效 terminal 节点") from exc
        if not 0 <= node < node_count:
            raise SafetyInputError(f"网络 {network_id} 的 terminal 节点 {node} 越界")
        out.append(node)
    return list(dict.fromkeys(out))


def _dijkstra(nodes, adjacency, starts: Iterable[int], goals: Iterable[int]) -> tuple[float, list[int]]:
    starts, goals = list(dict.fromkeys(starts)), set(goals)
    if not starts or not goals:
        raise SafetyInputError("爬电路径缺少起点或终点")
    queue = []
    best = {}
    previous = {}
    for start in starts:
        best[start] = 0.0
        heapq.heappush(queue, (0.0, start))
    target = None
    while queue:
        cost, node = heapq.heappop(queue)
        if cost != best.get(node):
            continue
        if node in goals:
            target = node
            break
        for nxt, weight in adjacency[node]:
            new_cost = cost + weight
            if new_cost < best.get(nxt, float("inf")):
                best[nxt] = new_cost
                previous[nxt] = node
                heapq.heappush(queue, (new_cost, nxt))
    if target is None:
        raise SafetyInputError("绝缘表面图中不存在连通的爬电路径")
    path = [target]
    while path[-1] not in starts:
        path.append(previous[path[-1]])
    path.reverse()
    return best[target], path


def creepage_measurements(ctx, threshold: float) -> list[SafetyMeasurement]:
    model, params = ctx.model, merged_safety_params(ctx.model, ctx.params)
    key = _cache_key(model, "creepage", params)
    cached = _MEASUREMENT_CACHE.get(key)
    if cached is not None and cached[0]() is model:
        return list(cached[1])
    _MEASUREMENT_CACHE.pop(key, None)

    networks = resolve_networks(model, params)
    pairs = network_pairs(networks, model, params)
    by_id = {n.network_id: n for n in networks}
    if len(networks) < 2 or not pairs:
        raise SafetyInputError("至少需要两个不同电位的电气网络")

    explicit = [
        _measurement_from_dict(model, item, "creepage", threshold, by_id)
        for item in _explicit_measurements(model, params, "creepage_measurements")
    ]
    explicit = [x for x in explicit if x is not None]
    if explicit:
        return _store_measurements(model, "creepage", key, explicit)

    meta = _safety_meta(model)
    graph = params.get("surface_graph") or meta.get("surface_graph")
    terminals = {}
    path_rule_info = {}
    if isinstance(graph, dict):
        nodes, adjacency, terminals, path_rule_info = _graph_from_config(graph)
        method = "surface-graph-dijkstra"
    else:
        mesh_path = params.get("surface_mesh_path") or meta.get("surface_mesh_path")
        if not mesh_path:
            raise SafetyInputError("缺少 surface_graph 或绝缘体 surface_mesh_path")
        if not os.path.isabs(mesh_path):
            base = os.path.dirname(model.source) if model.source else os.getcwd()
            mesh_path = os.path.abspath(os.path.join(base, mesh_path))
        nodes, adjacency = _graph_from_stl(mesh_path, float(params.get("mesh_weld_tolerance_mm", 0.001)))
        method = "stl-edge-dijkstra"

    nearest_count = int(params.get("terminal_vertex_count", 3))
    results = []
    #遍历每一对需要测试的网络
    for na, nb in pairs:
        starts = _terminal_nodes(
            terminals.get(na.network_id, []), len(nodes), na.network_id
        )
        goals = _terminal_nodes(
            terminals.get(nb.network_id, []), len(nodes), nb.network_id
        )
        if not starts:
            starts = _nearest_nodes(nodes, na.contact_points, nearest_count)
        if not goals:
            goals = _nearest_nodes(nodes, nb.contact_points, nearest_count)
        value, path_ids = _dijkstra(nodes, adjacency, starts, goals)
        path = [nodes[i] for i in path_ids]
        faces = list(dict.fromkeys(
            _network_evidence_face_ids(model, na)
            + _network_evidence_face_ids(model, nb)
        ))
        rule_note = ""
        if path_rule_info.get("adjusted_edge_count") or path_rule_info.get("excluded_edge_count"):
            rule_note = (
                f"；显式特征边规则：调整 {path_rule_info['adjusted_edge_count']} 条，"
                f"排除 {path_rule_info['excluded_edge_count']} 条"
            )
        results.append(
            SafetyMeasurement(
                kind="creepage",
                network_a=na.network_id,
                network_b=nb.network_id,
                measured_mm=value,
                threshold_mm=threshold,
                method=method,
                confidence=float(params.get("creepage_confidence", 0.9)),
                part_refs=list(dict.fromkeys(na.part_ids + nb.part_ids)),
                face_ids=faces,
                p1=path[0],
                p2=path[-1],
                path_points=path,
                note=(
                    "沿绝缘表面图的最短路径；沟槽、绝缘筋和倒角仅按显式边元数据处理"
                    + rule_note
                ),
                extra={"path_rules": dict(path_rule_info)},
            )
        )
    return _store_measurements(model, "creepage", key, results)


def combined_measurements(ctx) -> tuple[list[SafetyMeasurement], list[str]]:
    """供 SAF-03/04 使用：优先复用 SAF-01/02 已算结果。"""
    missing = []
    clearance = latest_measurements(ctx.model, "clearance")
    creepage = latest_measurements(ctx.model, "creepage")
    params = merged_safety_params(ctx.model, ctx.params)

    if not clearance:
        try:
            threshold, _ = clearance_threshold_mm(params)
            if has_clearance_input(ctx.model, params):
                issue = clearance_input_issue(ctx.model, params)
                if issue:
                    missing.append(issue)
                else:
                    clearance = clearance_measurements(ctx, threshold)
            else:
                missing.append("电气间隙输入")
        except SafetyInputError as exc:
            missing.append(str(exc))
    if not creepage:
        try:
            threshold, _ = creepage_threshold_mm(params)
            if has_creepage_input(ctx.model, params):
                issue = creepage_input_issue(ctx.model, params)
                if issue:
                    missing.append(issue)
                else:
                    creepage = creepage_measurements(ctx, threshold)
            else:
                missing.append("爬电路径输入")
        except SafetyInputError as exc:
            missing.append(str(exc))
    return clearance + creepage, missing


def grouped_by_pair(measurements: Iterable[SafetyMeasurement]) -> dict[tuple[str, str], list[SafetyMeasurement]]:
    out = {}
    for item in measurements:
        key = tuple(sorted((item.network_a, item.network_b)))
        out.setdefault(key, []).append(item)
    return out
