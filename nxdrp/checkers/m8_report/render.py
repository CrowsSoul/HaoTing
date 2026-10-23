"""HTML 评审模板与所有导出格式共用的问题字段。"""
import base64
import html
import json
from pathlib import Path
from .core import fmt, SEVERITY

def esc(value):
    return html.escape(str(value), quote=True)

def details(f):
    raw = f["source"]
    unit = raw.get("unit", "未提供")
    pos = ", ".join(fmt(x) for x in f["position"]) if f["position"] else "缺少位置数据"
    return [
        ("位置", pos + "；坐标单位：" + str(f.get("coordinate_units", "未提供"))),
        ("位置来源", f["position_origin"]),
        ("零件", ", ".join(map(str, raw.get("part_refs", []))) or "未提供"),
        ("面编号", ", ".join(raw["evidence"].get("face_ids", [])) or "未提供"),
        ("实测值", fmt(raw.get("measured_value"))+" "+unit),
        ("阈值", fmt(raw.get("threshold_value"))+" "+unit),
        ("偏差量", fmt(f["deviation"])+" "+unit+("（由实测减阈值计算）" if f["deviation_derived"] else "（源结果）")),
        ("严重程度", f["severity"]+" "+SEVERITY.get(f["severity"], "待补充")),
        ("置信度", fmt(f["confidence"])),
        ("整改建议", f["suggestion"]),
        ("建议来源", "M8 模板兜底，待工艺确认" if f["suggestion_fallback"] else "检测模块原始建议"),
        ("目标参数", json.dumps(f["param_delta"], ensure_ascii=False) if f["param_delta"] else "未提供，按所列结构动作处理并确认目标"),
        ("规则依据", f["rule_source"]),
        ("检测器", str(raw["detector"].get("module") or "未提供")+" / "+str(raw["detector"].get("version") or "未提供")),
        ("证据说明", raw["evidence"].get("note") or "未提供"),
        ("截图类型", f["image_kind"]),
    ]

CSS = """
:root{--ink:#20394b;--muted:#687d8d;--line:#dce4eb;--accent:#126d73}*{box-sizing:border-box}
body{margin:0;background:#eef2f5;color:var(--ink);font:15px/1.7 'Microsoft YaHei','Segoe UI',sans-serif}
main{max-width:1080px;margin:32px auto;background:white;padding:48px 58px;border:1px solid var(--line)}
h1{font-size:32px;line-height:1.4;margin:12px 0 14px}h2{font-size:22px;margin-top:32px}h3{font-size:18px}
.eyebrow{letter-spacing:3px;color:var(--accent);font-size:12px}.muted,small{color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);border-block:1px solid var(--line);margin:26px 0}
.metric{padding:20px 8px}.metric b{display:block;font-size:30px;font-weight:600}.metric span{color:var(--muted)}
.notice{color:#9a4926}.badge{font-size:12px;border-radius:4px;padding:3px 7px;background:#eef2f5;white-space:nowrap}
.issues,.error,.missing_data{background:#fcebe5;color:#ae452a}.clear{background:#e5f3ed;color:#226b50}
table{width:100%;border-collapse:collapse;margin:16px 0;font-size:13px}th,td{padding:9px 11px;border:1px solid var(--line);text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#f1f5f7;font-weight:600}
tr:nth-child(even){background:#fafcfd}a{color:var(--accent)}.issue{margin:24px 0 36px;padding-top:12px;border-top:2px solid var(--line)}
.issue img{width:100%;max-height:460px;object-fit:contain;background:#f3f6fa}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
dl{display:grid;grid-template-columns:110px 1fr;gap:9px 18px}.tools{display:flex;gap:16px;justify-content:flex-end}button{border:1px solid #b8ccd5;padding:8px 16px;background:white;color:var(--ink);border-radius:5px;cursor:pointer}
footer{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:22px;overflow-wrap:anywhere}.section{scroll-margin-top:20px}
@media(max-width:700px){main{margin:0;padding:25px 18px}.metrics{grid-template-columns:repeat(2,1fr)}dl{grid-template-columns:85px 1fr}table{font-size:11px}th,td{padding:6px}}
@media print{body{background:white;font-size:10pt}main{border:0;padding:0;margin:0;max-width:none}.tools{display:none}a{color:inherit}thead{display:table-header-group}tr{break-inside:avoid}.issue img{max-height:75mm}.issue h3{break-after:avoid}h2,h3{color:black;break-after:avoid}h1{color:black}@page{size:A4;margin:16mm}}
"""

def html_report(report, directory):
    s = report["summary"]
    rows = "".join(f'<tr><td><a href="#{x["anchor"]}">{x["id"]}</a></td><td>{esc(x["name"])}</td><td><span class="badge {x["status"]}">{x["status_label"]}</span></td><td>{x["count"]}</td><td><a href="#{x["anchor"]}">第 {i} 项详情</a></td></tr>' for i,x in enumerate(report["sections"], 1))
    sections = []
    for item in report["sections"]:
        block = f'<section class="section" id="{item["anchor"]}"><h2>{item["id"]} {esc(item["name"])}</h2><p><span class="badge {item["status"]}">{item["status_label"]}</span>　{esc(item["owner"])} · {esc(item["phase"])}</p>'
        if item["reason"]:
            block += f'<p class="muted">{esc(item["reason"])}</p>'
        for f in item["findings"]:
            image = ""
            if f["image"]:
                encoded = base64.b64encode((Path(directory)/f["image"]).read_bytes()).decode()
                image = f'<img alt="{esc(f["image_kind"])}" src="data:image/png;base64,{encoded}"><small>{esc(f["image_kind"])} · {esc(f.get("image_source", ""))}</small>'
            fields = "".join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k,v in details(f))
            quality = ''.join(f'<li>{esc(q)}</li>' for q in f["quality"])
            block += f'<article class="issue" id="{f["anchor"]}"><h3>{esc(f["finding_id"])}　{esc(f["severity"])}</h3><p>{esc(f["source"].get("message", ""))}</p>{image}<dl>{fields}</dl>'
            if quality:
                block += f'<p class="notice">待补充或复核</p><ul class="notice">{quality}</ul>'
            if f.get('advisories'):
                block += '<p class="muted">人工确认：'+esc('；'.join(f['advisories']))+'</p>'
            block += '<a href="#catalog">返回 44 项目录 ↑</a></article>'
        sections.append(block+'</section>')
    warnings = ''.join(f'<li>{esc(w)}</li>' for w in report['warnings'])
    state = "完整性检查已通过，仍需人工评审确认" if s["review_ready"] else "报告已生成，仍有未执行项或证据待补充"
    acceptance = report['acceptance']
    state += f"。问题四要素完整 {acceptance['four_fields_complete_count']}/{acceptance['finding_count']} 条；数据完整性不代表产品合格。"
    demo = '<p class="notice">开发示例数据，用于验证报告流程，不代表产品检测结论。</p>' if report["is_mock"] else ''
    meta = report["run_meta"]
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(report['title'])}</title><style>{CSS}</style></head><body><main>
<div class="tools"><button onclick="window.print()">打印或另存 PDF</button></div><div class="eyebrow">M8 · DESIGN REVIEW</div><h1>{esc(report['title'])}</h1><p class="muted">模型 {esc(report['model_id'])}　·　{esc(report['created_at'])}<br>归档编号 {esc(report.get('report_id', ''))}　·　坐标单位 {esc(report['model_units'])}</p>
<p>{state}</p>{demo}<div class="metrics"><div class="metric"><b>{s['catalog_count']}</b><span>检查项目录</span></div><div class="metric"><b>{s['executed_count']}</b><span>成功执行项</span></div><div class="metric"><b>{s['finding_count']}</b><span>问题记录</span></div><div class="metric"><b>{s['quality_issue_count']}</b><span>证据待补充点</span></div></div>
<p>P0 阻断 {s['by_severity']['P0']}　P1 严重 {s['by_severity']['P1']}　P2 一般 {s['by_severity']['P2']}　P3 提示 {s['by_severity']['P3']}</p>
<p class="muted">偏差量统一展示为实测值减阈值，正负号不单独代表是否合格，判定沿用检测模块结果。未提供执行记录的项目列为未执行。</p><ul class="notice">{warnings}</ul>
<h2 id="catalog">四十四项结果索引</h2><table><thead><tr><th>检查项</th><th>名称</th><th>状态</th><th>问题数</th><th>结果位置</th></tr></thead><tbody>{rows}</tbody></table>
{''.join(sections)}<footer>模型来源 {esc(report['model_source'])}<br>规则库 {esc(meta.get('rulebook'))} / {esc(meta.get('rulebook_version'))}　建议库 {esc(report['knowledge_version'])}<br>原始结果 SHA256 {report['source_digest']}<br>本报告保留原始判定；模板建议须由工艺负责人确认。附件包括原始结果、归一结果、定位图与校验清单。</footer></main></body></html>'''
