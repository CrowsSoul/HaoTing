"""将原验收条款映射为可核对清单；不替代工程师的内容评审。"""
import math
from ...catalog import BY_ID
from .core import number, vec, bbox, usable_suggestion, SEVERITY


def audit_report(report):
    rows = []
    for f in report['findings']:
        raw = f['source']
        measured, threshold, deviation = raw.get('measured_value'), raw.get('threshold_value'), f.get('deviation')
        criteria = {
            'position': bool((vec(f.get('position')) or bbox(f.get('bbox')))
                             and f.get('coordinate_units', '未提供') != '未提供'
                             and raw.get('evidence', {}).get('face_ids')
                             and f.get('image') and f.get('image_kind') in {'真实三维截图', '网格三维定位图'}
                             and not any('不存在' in q for q in f['quality'])),
            'deviation': bool(all(number(x) for x in (measured, threshold, deviation))
                              and math.isclose(deviation, measured-threshold, rel_tol=1e-6, abs_tol=1e-8)
                              and isinstance(raw.get('unit'), str) and raw['unit'].strip()),
            'severity': f.get('severity') in SEVERITY,
            'recommendation': usable_suggestion(f.get('suggestion')),
        }
        rows.append({'finding_id': f['finding_id'], 'check_item_id': f['check_item_id'],
                     'criteria': criteria, 'four_fields_complete': all(criteria.values()),
                     'quality': f['quality'], 'advisories': f.get('advisories', []),
                     'result_location': {'html': '#'+f['anchor'], 'item_anchor': 'item-'+f['check_item_id']}})
    sections = report['sections']
    catalog_complete = len(sections) == len(BY_ID) and {s['id'] for s in sections} == set(BY_ID)
    index = [{'check_item_id': s['id'], 'status': s['status'], 'reason': s['reason'], 'finding_count': s['count'],
              'result_location': {'html': '#'+s['anchor'], 'pdf_bookmark': s['anchor'], 'word_bookmark': s['anchor'].replace('-', '_')}} for s in sections]
    complete = bool(report['summary']['review_ready'] and catalog_complete and all(r['four_fields_complete'] for r in rows))
    return {'version': '1.0', 'scope': 'M8 报告数据完整性检查，不代表检测算法正确或产品合格',
            'requires_human_review': True, 'catalog_complete': catalog_complete,
            'four_fields_complete_count': sum(r['four_fields_complete'] for r in rows),
            'finding_count': len(rows), 'data_complete': complete,
            'status': '数据完整，待人工评审' if complete else '草稿，待补充检查结果或证据',
            'criteria_labels': {'position': '位置与三维图及面编号', 'deviation': '实测、阈值、单位及一致偏差',
                                'severity': '有效严重程度', 'recommendation': '非占位整改建议'},
            'findings': rows, 'items': index, 'warnings': report['warnings']}
