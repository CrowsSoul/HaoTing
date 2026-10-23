"""生成、事务归档、历史检索与校验。仅在调用方指定的目录写入。"""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from .core import normalize, finalize_quality, load_json, dump_json, now
from .images import attach_images
from .render import html_report

ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}-[a-f0-9]{12}$")

def capabilities():
    return {"html": True, "png": importlib.util.find_spec("PIL") is not None,
            "pdf": importlib.util.find_spec("reportlab") is not None,
            "docx": importlib.util.find_spec("docx") is not None}

def generate_report(payload, output_root, model=None, rules=None, screenshots=None, mesh=None,
                    title="连接器设计检查报告", formats=("html", "pdf", "docx"), require_complete=False):
    """只读上游数据；成功后返回目录，不覆盖任何既有归档。"""
    caps = capabilities()
    for fmt in formats:
        if fmt not in {"html", "pdf", "docx"}:
            raise ValueError(f"不支持导出格式 {fmt}")
        if not caps[fmt]:
            raise RuntimeError(f"缺少 {fmt} 导出依赖，请安装本模块 requirements.txt")
    if not caps["png"]:
        raise RuntimeError("缺少 Pillow，请安装本模块 requirements.txt")
    source = payload.to_dict() if hasattr(payload, "to_dict") else copy.deepcopy(payload)
    if isinstance(source, list):
        source = {"findings": [f.to_dict() if hasattr(f, "to_dict") else f for f in source]}
    model = model.to_dict() if hasattr(model, "to_dict") else (model or {})
    rules = rules.to_dict() if hasattr(rules, "to_dict") else (rules or {})
    report = normalize(source, model, rules, title)
    rid = now().replace("-", "").replace(":", "")[:15]+"-"+uuid.uuid4().hex[:12]
    report["report_id"] = rid
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".building-", dir=root))
    destination = root/rid
    try:
        dump_json(staging/"source_findings.json", source)
        if model:
            dump_json(staging/"model.json", model)
        if rules:
            dump_json(staging/"rules.json", rules)
        if mesh:
            shutil.copyfile(mesh, staging/"source_mesh.stl")
        attach_images(report, model, staging/"images", screenshots, mesh)
        finalize_quality(report)
        if require_complete and not report['acceptance']['data_complete']:
            raise ValueError('正式报告检查未通过：请补齐 44 项执行记录及问题的位置、偏差、严重程度和整改证据；草稿模式可导出验收清单。')
        # sections 与 findings 引用同一记录，截图与质量信息同步。
        dump_json(staging/"report.json", report)
        dump_json(staging/"acceptance.json", report['acceptance'])
        dump_json(staging/"image_evidence.json", [f['image_evidence'] for f in report['findings']])
        dump_json(staging/"quality.json", {"summary": report["summary"], "warnings": report["warnings"],
                                          "findings": [{"finding_id": f["finding_id"], "quality": f["quality"]} for f in report["findings"]]})
        (staging/"report.html").write_text(html_report(report, staging), encoding="utf-8")
        if "pdf" in formats:
            from .export import export_pdf
            export_pdf(report, staging)
        if "docx" in formats:
            from .export import export_docx
            export_docx(report, staging)
        # 保存当次模板快照，后续修改建议库不会改变历史版本。
        shutil.copyfile(Path(__file__).with_name("knowledge.json"), staging/"knowledge_snapshot.json")
        files = {p.relative_to(staging).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(staging.rglob("*")) if p.is_file()}
        dump_json(staging/"manifest.json", {"report_id": rid, "created_at": report["created_at"], "files": files})
        # ZIP 不包含自己；清单可用于下载后校验。
        with zipfile.ZipFile(staging/"archive.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(staging.rglob("*")):
                if p.is_file() and p.name != "archive.zip":
                    z.write(p, p.relative_to(staging).as_posix())
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging)
        raise
    return {"report_id": rid, "directory": str(destination), "summary": report["summary"],
            "files": [p.name for p in destination.iterdir() if p.is_file()]}

def report_directory(root, report_id):
    if not ID_PATTERN.fullmatch(report_id):
        raise ValueError("归档编号无效")
    root = Path(root).resolve()
    directory = (root/report_id).resolve()
    if directory.parent != root or not directory.is_dir():
        raise FileNotFoundError("归档不存在")
    return directory

def list_archives(root, query="", severity="", item=""):
    rows = []
    root = Path(root)
    if not root.exists():
        return rows
    for folder in sorted(root.iterdir(), reverse=True):
        if not ID_PATTERN.fullmatch(folder.name) or not (folder/"report.json").is_file():
            continue
        r = load_json(folder/"report.json")
        findings = [f for f in r["findings"] if (not severity or f["severity"] == severity)
                    and (not item or f["check_item_id"] == item)]
        searchable = json.dumps({"model": r["model_id"], "title": r["title"], "id": r["report_id"], "findings": findings}, ensure_ascii=False)
        if (severity or item) and not findings:
            continue
        if query.casefold() not in searchable.casefold():
            continue
        rows.append({k: r[k] for k in ("report_id", "title", "model_id", "created_at", "summary")})
    return rows

def search_cases(root, query="", severity="", item=""):
    hits = []
    for archive in list_archives(root, severity=severity, item=item):
        report = load_json(Path(root)/archive["report_id"]/"report.json")
        for f in report["findings"]:
            if severity and f["severity"] != severity or item and f["check_item_id"] != item:
                continue
            if query.casefold() not in json.dumps(f, ensure_ascii=False).casefold():
                continue
            hits.append({"report_id": report["report_id"], "model_id": report["model_id"],
                         "finding_id": f["finding_id"], "item": f["check_item_id"], "severity": f["severity"],
                         "message": f["source"].get("message", ""), "suggestion": f["suggestion"], "anchor": f["anchor"]})
    return hits

def verify_archive(directory):
    directory = Path(directory).resolve()
    manifest = load_json(directory/"manifest.json")
    failures = []
    for name, expected in manifest["files"].items():
        path = (directory/name).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            failures.append(name+" 缺失或路径无效")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            failures.append(name+" 校验失败")
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    extra = actual - set(manifest["files"]) - {"manifest.json", "archive.zip"}
    failures += [name+" 为未登记文件" for name in sorted(extra)]
    try:
        with zipfile.ZipFile(directory/'archive.zip') as z:
            expected_names = set(manifest['files']) | {'manifest.json'}
            names = z.namelist()
            if len(names) != len(set(names)) or set(names) != expected_names:
                failures.append('archive.zip 成员清单不一致或存在重复项')
            for name in expected_names & set(names):
                expected = (hashlib.sha256((directory/'manifest.json').read_bytes()).hexdigest()
                            if name == 'manifest.json' else manifest['files'][name])
                if hashlib.sha256(z.read(name)).hexdigest() != expected:
                    failures.append('archive.zip 内 '+name+' 校验失败')
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as error:
        failures.append('archive.zip 无法读取：'+str(error))
    return {"ok": not failures, "checked_files": len(manifest["files"]), "failures": failures}
