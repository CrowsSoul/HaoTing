"""只读结果归一化；派生字段仅存在于 M8 报告，不写回 Finding。"""
from __future__ import annotations
import copy
import hashlib
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from ...catalog import CATALOG, BY_ID

HERE = Path(__file__).resolve().parent
STATUS = {"issues": "发现问题", "clear": "已执行无问题", "skipped": "已跳过",
          "filtered": "未纳入本次检查", "error": "执行失败", "missing_data": "缺少数据",
          "not_run": "未执行", "unconfirmed": "执行状态待确认"}
SEVERITY = {"P0": "阻断", "P1": "严重", "P2": "一般", "P3": "提示"}

def usable_suggestion(text):
    """仅排除明显占位文字；工程可执行性仍需工艺人员确认。"""
    return isinstance(text, str) and text.strip().strip('。.!！ ') not in {
        '', '请注意检查', '请检查', '待补充', '待定', '建议优化', '优化设计', 'N/A', '无'}

def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")

def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False).encode("utf-8")).hexdigest()

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"非法数值 {x}")))

def dump_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

def vec(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(number(x) for x in value)

def bbox(value):
    return (isinstance(value, dict) and all(number(value.get(k)) for k in
            ("xmin", "ymin", "zmin", "xmax", "ymax", "zmax")) and
            all(value[a+"min"] <= value[a+"max"] for a in "xyz"))

def fmt(value):
    if value is None:
        return "未提供"
    if number(value):
        return f"{value:.6g}"
    return str(value)

def knowledge():
    return load_json(HERE / "knowledge.json")

def normalize(payload, model=None, rules=None, title="连接器设计检查报告"):
    """支持 CheckRun / CheckRun.to_dict() / Finding 列表，保留源结果不变。"""
    if hasattr(payload, "to_dict"):
        payload = payload.to_dict()
    if isinstance(payload, list):
        payload = {"findings": [f.to_dict() if hasattr(f, "to_dict") else f for f in payload]}
    if not isinstance(payload, dict) or "findings" not in payload:
        raise ValueError("请输入含 findings 数组的检查结果，或 Finding 数组；模型文件不等于检查结果。")
    source = copy.deepcopy(payload)
    findings, results = source["findings"], source.get("results", [])
    if not isinstance(findings, list) or not isinstance(results, list):
        raise ValueError("findings 和 results 必须是数组")
    model = model.to_dict() if hasattr(model, "to_dict") else (model or {})
    rules = rules.to_dict() if hasattr(rules, "to_dict") else (rules or {})
    if not isinstance(model, dict) or not isinstance(rules, dict):
        raise ValueError("模型和规则必须是 JSON 对象")
    if source.get("model_id") and model.get("model_id") and source["model_id"] != model["model_id"]:
        raise ValueError("模型 ID 与检查结果不一致，不能生成定位图")
    templates = knowledge()
    if set(templates["items"]) != set(BY_ID):
        raise ValueError("建议库必须完整覆盖目录中的 44 项")
    result_map, warnings = {}, []
    for result in results:
        if not isinstance(result, dict) or result.get("check_item_id") not in BY_ID:
            raise ValueError("results 包含未知检查项或非对象记录")
        cid = result["check_item_id"]
        if cid in result_map:
            raise ValueError(f"重复执行状态：{cid}")
        if result.get("status") not in {"ok", "skipped", "filtered", "error", "missing_data"}:
            raise ValueError(f"未知执行状态：{cid}")
        count = result.get("finding_count")
        if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 0):
            raise ValueError(f"{cid} 的 finding_count 必须是非负整数")
        result_map[cid] = result
    face_map = {f["face_id"]: f for f in model.get("faces", [])}
    part_map = {p["part_id"]: p for p in model.get("parts", [])}
    rule_map = {r["check_item_id"]: r for r in rules.get("rules", [])}
    seen, normalized = set(), []
    for index, raw in enumerate(findings, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index} 条问题不是对象")
        f = copy.deepcopy(raw)
        fid, cid = f.get("finding_id"), f.get("check_item_id")
        if not isinstance(fid, str) or not fid.strip() or fid in seen:
            raise ValueError(f"问题编号缺失或重复：{fid}")
        if cid not in BY_ID:
            raise ValueError(f"未知检查项：{cid}")
        seen.add(fid)
        issues, advisories = [], []
        for key in ("measured_value", "threshold_value", "deviation", "confidence"):
            if f.get(key) is not None and not number(f[key]):
                raise ValueError(f"{fid} 的 {key} 必须是有限数字或 null")
        if f.get("confidence") is not None and not 0 <= f["confidence"] <= 1:
            raise ValueError(f"{fid} 的 confidence 越界")
        if f.get("severity") not in SEVERITY:
            issues.append("缺少有效严重程度")
        for key in ("evidence", "suggestion", "extra", "detector"):
            f[key] = f.get(key) or {}
            if not isinstance(f[key], dict):
                raise ValueError(f"{fid} 的 {key} 必须是对象")
        refs = f["evidence"].get("face_ids", [])
        if not isinstance(refs, list) or not all(isinstance(x, str) for x in refs):
            raise ValueError(f"{fid} 的 face_ids 必须是字符串数组")
        if not refs:
            issues.append("未提供面编号，需补充可追溯证据")
        elif model and any(x not in face_map for x in refs):
            issues.append("部分面编号在所附模型中不存在")
        if not isinstance(f.get("part_refs", []), list) or not all(isinstance(x, str) for x in f.get("part_refs", [])):
            raise ValueError(f"{fid} 的 part_refs 必须是字符串数组")
        if model and any(x not in part_map for x in f.get("part_refs", [])):
            issues.append("部分零件编号在所附模型中不存在")
        if f.get("location") is not None and not vec(f["location"]):
            raise ValueError(f"{fid} 的 location 必须是三个有限数字")
        if f.get("bbox") is not None and not bbox(f["bbox"]):
            raise ValueError(f"{fid} 的 bbox 无效")
        if not all(vec(p) for p in f.get("path_points", [])):
            raise ValueError(f"{fid} 的路径点无效")
        position, box, origin = f.get("location"), f.get("bbox"), "检查结果"
        if not position and not box and model:
            candidates = [face_map[x].get("bbox") for x in refs if x in face_map]
            if not candidates:
                candidates = [part_map[x].get("bbox") for x in f.get("part_refs", []) if x in part_map]
            candidates = [b for b in candidates if bbox(b)]
            if candidates:
                box = {a+s: (min if s == "min" else max)(b[a+s] for b in candidates)
                       for a in "xyz" for s in ("min", "max")}
                origin = "由引用几何包围盒推导"
        if not position and box:
            position = [(box[a+"min"]+box[a+"max"])/2 for a in "xyz"]
            origin += "的中心"
        if not position and not box:
            issues.append("缺少位置坐标或包围盒")
        deviation, derived = f.get("deviation"), False
        if number(f.get("measured_value")) and number(f.get("threshold_value")):
            calculated = f["measured_value"] - f["threshold_value"]
            if deviation is None:
                deviation, derived = calculated, True
            elif not math.isclose(deviation, calculated, rel_tol=1e-6, abs_tol=1e-8):
                issues.append("源偏差与实测减阈值不一致，保留源值待复核")
        if deviation is None:
            issues.append("缺少偏差量，需检测模块补充或说明不适用")
        if not number(f.get("measured_value")) or not number(f.get("threshold_value")):
            issues.append("缺少实测值或阈值，无法核对偏差依据")
        if not isinstance(f.get("unit"), str) or not f["unit"].strip():
            issues.append("未提供量测单位")
        suggestion = f["suggestion"]
        text = suggestion.get("text") or ""
        if not isinstance(text, str):
            raise ValueError(f"{fid} 的 suggestion.text 必须是字符串")
        fallback = not text.strip()
        if fallback:
            text = templates["items"][cid]
        if not usable_suggestion(text):
            issues.append("整改建议仍是占位文字，需提供目标尺寸或具体结构动作")
        delta = suggestion.get("param_delta") or {}
        if not isinstance(delta, dict):
            raise ValueError(f"{fid} 的 param_delta 必须是对象")
        if not delta:
            advisories.append("未提供数值目标参数，请由工艺人员确认所列结构动作是否可执行")
        if f.get("confidence") is None:
            issues.append("未提供置信度")
        rule = rule_map.get(cid, {})
        normalized.append({"source": f, "finding_id": fid, "check_item_id": cid,
                           "anchor": f"finding-{index:04d}", "name": BY_ID[cid].name_cn,
                           "severity": f['severity'] if f.get('severity') in SEVERITY else '未提供', "confidence": f.get("confidence"),
                           "position": position, "bbox": box, "position_origin": origin,
                           "coordinate_units": f["extra"].get("coordinate_units") or model.get("units") or "未提供",
                           "deviation": deviation, "deviation_derived": derived,
                           "suggestion": text, "param_delta": delta, "suggestion_fallback": fallback,
                           "rule_source": rule.get("source_standard") or "未提供规则依据",
                           "quality": issues, "advisories": advisories, "image": None, "image_kind": "缺少真实截图"})
    normalized.sort(key=lambda f: (f["check_item_id"], f["severity"], f["finding_id"]))
    sections = []
    for item in CATALOG:
        cid = item.check_item_id
        fs = [f for f in normalized if f["check_item_id"] == cid]
        res = result_map.get(cid)
        if fs:
            state = "issues"
            if res is None:
                warnings.append(f"{cid} 有问题记录但没有执行状态，需确认检查是否完整结束")
            if res and res["status"] != "ok":
                warnings.append(f"{cid} 有问题记录但执行状态为 {res['status']}，结果可能不完整")
        else:
            state = ("clear" if res["status"] == "ok" else res["status"]) if res else "not_run"
        if res and res.get("finding_count") is None:
            warnings.append(f"{cid} 未提供 finding_count，无法核对结果是否完整")
            if state == "clear":
                state = "unconfirmed"
        if res and res.get("finding_count") is not None and res["finding_count"] != len(fs):
            warnings.append(f"{cid} 的 finding_count 与实际条数不一致")
            if state == "clear":
                state = "unconfirmed"
        sections.append({"id": cid, "name": item.name_cn, "owner": item.owner_module,
                         "phase": item.phase, "anchor": "item-"+cid, "status": state,
                         "status_label": STATUS[state], "count": len(fs),
                         "reason": res.get("reason", "") if res else "未提供该项执行记录",
                         "findings": fs})
    if source.get("load_errors"):
        warnings.append("检查平台存在插件加载错误，请查看原始结果 load_errors")
    return {"schema_version": "m8-report-1.0", "title": str(title), "created_at": now(),
            "model_id": source.get("model_id") or model.get("model_id") or "未提供模型标识",
            "model_source": model.get("source", "未附模型"), "model_units": model.get("units", "未提供"),
            "is_mock": str(model.get("source", "")).startswith("mock:") or "mock" in str(model.get("nx_version", "")).lower(),
            "source_digest": digest(source), "model_digest": digest(model) if model else None,
            "rule_digest": digest(rules) if rules else None, "knowledge_version": templates["version"],
            "run_meta": {k: source.get(k) for k in ("framework_version", "started_at", "finished_at", "elapsed_ms", "rulebook", "rulebook_version")},
            "sections": sections, "findings": normalized, "warnings": warnings,
            "summary": {"catalog_count": len(sections), "finding_count": len(normalized),
                        "executed_count": sum(r["status"] == "ok" for r in results),
                        "clear_count": sum(s["status"] == "clear" for s in sections),
                        "issue_item_count": sum(s["status"] == "issues" for s in sections),
                        "not_run_count": sum(s["status"] == "not_run" for s in sections),
                        "by_severity": {k: sum(f["severity"] == k for f in normalized) for k in SEVERITY}}}

def finalize_quality(report):
    for f in report["findings"]:
        if f["image_kind"] not in {"真实三维截图", "网格三维定位图"}:
            f["quality"].append("待补真实三维截图；当前定位示意不等同 NX 截图")
        if f.get("coordinate_units", "未提供") == "未提供":
            f["quality"].append("未提供位置坐标单位，请附模型数据或 extra.coordinate_units")
    report["summary"]["quality_issue_count"] = sum(len(f["quality"]) for f in report["findings"])
    report["summary"]["review_ready"] = (
        all(s["status"] in {"issues", "clear", "skipped"} for s in report["sections"])
        and all(s["status"] != "skipped" or bool(s["reason"].strip()) for s in report["sections"])
        and not report["warnings"] and not report["summary"]["quality_issue_count"])
    from .acceptance import audit_report
    report["acceptance"] = audit_report(report)
    return report
