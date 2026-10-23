"""M8 合同、结果真实性、导出和归档回归测试。"""
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from .core import normalize, finalize_quality, knowledge, load_json
from .service import generate_report, list_archives, verify_archive, search_cases, report_directory
from .images import read_stl
from ...catalog import BY_ID

def finding(**overrides):
    data = {"finding_id": "DFM-31-0001", "check_item_id": "DFM-31", "severity": "P2", "confidence": 0,
            "measured_value": 7.65, "threshold_value": 8.0, "unit": "mm", "location": [0,0,0],
            "part_refs": ["P1"], "evidence": {"face_ids": ["F1"]},
            "suggestion": {"text": "将孔径改为 8 mm", "param_delta": {"diameter_mm": 8.0}},
            "message": "非标孔径", "extra": {}, "detector": {"module": "fixture", "version": "1"}}
    data.update(overrides)
    return data

def payload(fs=None):
    return {"model_id": "test", "findings": [finding()] if fs is None else fs,
            "results": [{"check_item_id": "DFM-31", "status": "ok", "finding_count": 1}]}

class NormalizationTests(unittest.TestCase):
    def test_all_44_are_addressable_and_missing_not_pass(self):
        report = normalize(payload())
        self.assertEqual({s["id"] for s in report["sections"]}, set(BY_ID))
        self.assertEqual(len({s["anchor"] for s in report["sections"]}), 44)
        self.assertEqual(report["sections"][0]["status"], "not_run")

    def test_zero_confidence_position_and_no_mutation(self):
        data = payload()
        before = copy.deepcopy(data)
        f = normalize(data)["findings"][0]
        self.assertEqual(f["position"], [0,0,0])
        self.assertEqual(f["confidence"], 0)
        self.assertAlmostEqual(f["deviation"], -.35)
        self.assertEqual(data, before)

    def test_boundary_deviation_is_zero(self):
        f = normalize(payload([finding(measured_value=8)]))["findings"][0]
        self.assertEqual(f["deviation"], 0)

    def test_no_findings_with_ok_is_clear(self):
        p = payload([])
        p["results"][0]["finding_count"] = 0
        r = normalize(p)
        self.assertEqual(next(s for s in r["sections"] if s["id"] == "DFM-31")["status"], "clear")

    def test_missing_and_skip_error_filter_are_distinct(self):
        p = payload([])
        p["results"] = [{"check_item_id": f"DFM-{i:02}", "status": status, "reason": "test"}
                        for i,status in enumerate(("missing_data", "skipped", "error", "filtered"), 1)]
        self.assertEqual([x["status"] for x in normalize(p)["sections"][:4]],
                         ["missing_data", "skipped", "error", "filtered"])

    def test_result_count_conflict_cannot_pass(self):
        p = payload([])
        r = normalize(p)
        self.assertEqual(next(s for s in r["sections"] if s["id"] == "DFM-31")["status"], "unconfirmed")
        self.assertTrue(r["warnings"])

    def test_template_fallback_has_action_without_fabricated_target(self):
        r = normalize(payload([finding(suggestion={})]))
        f = r["findings"][0]
        self.assertTrue(f["suggestion_fallback"])
        self.assertTrue(f["suggestion"])
        self.assertEqual(f["param_delta"], {})
        self.assertEqual(set(knowledge()["items"]), set(BY_ID))

    def test_bad_numeric_id_and_duplicates_rejected(self):
        for fs in ([finding(measured_value=float("nan"))], [finding(), finding()],
                   [finding(check_item_id="OTHER")], [finding(location=[1,2])],
                   [finding(bbox={"xmin": 2})]):
            with self.subTest(fs=fs), self.assertRaises(ValueError):
                normalize(payload(fs))

    def test_missing_evidence_visible(self):
        f = normalize(payload([finding(location=None, evidence={})]))["findings"][0]
        self.assertTrue(any("位置" in q for q in f["quality"]))
        self.assertTrue(any("面编号" in q for q in f["quality"]))

    def test_source_deviation_preserved_and_conflict_flagged(self):
        f = normalize(payload([finding(deviation=20)]))["findings"][0]
        self.assertEqual(f["deviation"], 20)
        self.assertTrue(any("不一致" in q for q in f["quality"]))

    def test_model_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            normalize(payload(), {"model_id": "other"})

    def test_findings_only_never_claim_44_passed(self):
        r = finalize_quality(normalize([finding()]))
        self.assertEqual(r["summary"]["executed_count"], 0)
        self.assertFalse(r["summary"]["review_ready"])

    def test_complete_execution_can_be_review_ready(self):
        p = {"model_id": "test", "findings": [], "results": [
            {"check_item_id": cid, "status": "ok", "finding_count": 0} for cid in BY_ID]}
        report = finalize_quality(normalize(p))
        self.assertEqual(report["summary"]["clear_count"], 44)
        self.assertTrue(report["summary"]["review_ready"])
        p["results"][0].update(status="skipped", reason="")
        self.assertFalse(finalize_quality(normalize(p))["summary"]["review_ready"])

    def test_missing_execution_status_with_issues_is_warning(self):
        p = payload()
        p["results"] = []
        self.assertTrue(normalize(p)["warnings"])

class ArchiveTests(unittest.TestCase):
    def test_exports_links_search_zip_and_tamper(self):
        from docx import Document
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory() as temp:
            result = generate_report(payload(), temp)
            folder = Path(result["directory"])
            self.assertTrue(verify_archive(folder)["ok"])
            self.assertEqual(len(list_archives(temp)), 1)
            self.assertEqual(len(search_cases(temp, "非标孔径", item="DFM-31", severity="P2")), 1)
            doc = Document(folder/"report.docx")
            doc_text = '\n'.join(p.text for p in doc.paragraphs)
            pdf = PdfReader(folder/"report.pdf")
            pdf_text = '\n'.join(p.extract_text() for p in pdf.pages)
            html = (folder/"report.html").read_text(encoding="utf-8")
            for cid in BY_ID:
                self.assertIn("§"+cid, doc_text)
                self.assertIn(cid, pdf_text)
                self.assertIn('id="item-'+cid+'"', html)
            self.assertIn("data:image/png;base64,", html)
            with zipfile.ZipFile(folder/"archive.zip") as z:
                self.assertIn("source_findings.json", z.namelist())
                self.assertIn("manifest.json", z.namelist())
            (folder/"source_findings.json").write_text("{}", encoding="utf-8")
            self.assertFalse(verify_archive(folder)["ok"])

    def test_atomic_failure_and_unique_history(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                generate_report(payload(), temp, screenshots={"unknown": "x"}, formats=("html",))
            self.assertEqual(list(Path(temp).iterdir()), [])
            a = generate_report(payload(), temp, formats=("html",))
            b = generate_report(payload(), temp, formats=("html",))
            self.assertNotEqual(a["report_id"], b["report_id"])
            with self.assertRaises(ValueError):
                report_directory(temp, "../outside")

    def test_attached_screenshot_and_html_escaping(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            shot = Path(temp)/"shot.png"
            Image.new("RGB", (100,100), "white").save(shot)
            p = payload([finding(message='<script>alert("x")</script>')])
            r = generate_report(p, Path(temp)/"out", screenshots={"DFM-31-0001": shot}, formats=("html",))
            report = load_json(Path(r["directory"])/"report.json")
            self.assertEqual(report["findings"][0]["image_kind"], "真实三维截图")
            html = (Path(r["directory"])/"report.html").read_text(encoding="utf-8")
            self.assertNotIn('<script>alert', html)
            self.assertIn('&lt;script&gt;', html)

    def test_ascii_stl_and_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"model.stl"
            path.write_text("solid s\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 10 0\nendloop\nendfacet\nendsolid")
            self.assertEqual(len(read_stl(path)), 1)
            result = generate_report(payload(), Path(temp)/"out", model={"model_id": "test", "units": "mm"}, mesh=path, formats=("html",))
            self.assertTrue((Path(result["directory"])/"source_mesh.stl").exists())

class AcceptanceTests(unittest.TestCase):
    def test_missing_counts_and_wrong_counts_cannot_pass(self):
        p = {'findings': [], 'results': [{'check_item_id': 'DFM-01', 'status': 'ok'}]}
        r = finalize_quality(normalize(p))
        self.assertEqual(r['sections'][0]['status'], 'unconfirmed')
        self.assertFalse(r['acceptance']['data_complete'])
        for invalid in (-1, True, 0.5, '0'):
            p['results'][0]['finding_count'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize(p)

    def test_placeholder_recommendation_rejected(self):
        p = payload([finding(suggestion={'text': '请注意检查', 'param_delta': {'target': 8}})])
        r = finalize_quality(normalize(p))
        self.assertFalse(r['acceptance']['findings'][0]['criteria']['recommendation'])

    def test_deviation_without_measurements_is_incomplete(self):
        r = finalize_quality(normalize(payload([finding(measured_value=None, threshold_value=None, deviation=1)])))
        self.assertFalse(r['acceptance']['findings'][0]['criteria']['deviation'])

    def test_structural_action_does_not_require_fabricated_dimension(self):
        p = payload([finding(extra={'coordinate_units':'mm'}, suggestion={'text':'移除刀具包络内遮挡结构，调整进刀方向', 'param_delta':{}})])
        r = normalize(p)
        r['findings'][0].update(image='test-only.png', image_kind='真实三维截图')
        r = finalize_quality(r)
        self.assertTrue(r['acceptance']['findings'][0]['four_fields_complete'])
        self.assertTrue(r['findings'][0]['advisories'])

    def test_invalid_severity_exports_visible_draft(self):
        with tempfile.TemporaryDirectory() as temp:
            r = generate_report(payload([finding(severity=None)]), temp, formats=('html',))
            report = load_json(Path(r['directory'])/'report.json')
            self.assertEqual(report['findings'][0]['severity'], '未提供')
            self.assertFalse(report['acceptance']['findings'][0]['criteria']['severity'])

    def test_strict_generation_rolls_back_incomplete_report(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, '正式报告检查未通过'):
                generate_report(payload(), temp, require_complete=True, formats=('html',))
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_44_item_format_fixture_and_document_navigation(self):
        """合成数据只验证 M8 格式，不验证任何检测器或工程判定。"""
        from PIL import Image, ImageDraw
        from lxml import etree
        from pypdf import PdfReader
        import hashlib
        fs = [finding(finding_id=cid+'-FORMAT-ONLY', check_item_id=cid,
                      message='M8 合成格式测试，不是工程检测结果', extra={'coordinate_units':'mm'}) for cid in BY_ID]
        p = {'model_id':'M8-FORMAT-ONLY', 'findings':fs,
             'results':[{'check_item_id':cid,'status':'ok','finding_count':1} for cid in BY_ID]}
        original = copy.deepcopy(p)
        with tempfile.TemporaryDirectory() as temp:
            shot = Path(temp)/'fixture.png'
            im = Image.new('RGB',(300,160),'white')
            ImageDraw.Draw(im).text((20,60), 'M8 FORMAT TEST ONLY', fill='black')
            im.save(shot)
            result = generate_report(p, Path(temp)/'out', model={'model_id':'M8-FORMAT-ONLY','units':'mm','source':'mock://format-fixture',
                'parts':[{'part_id':'P1'}], 'faces':[{'face_id':'F1'}]},
                screenshots={f['finding_id']:shot for f in fs}, require_complete=True,
                title='M8 合成格式测试  不代表工程检测')
            folder = Path(result['directory'])
            acceptance = load_json(folder/'acceptance.json')
            self.assertTrue(acceptance['data_complete'])
            self.assertTrue(acceptance['requires_human_review'])
            self.assertEqual(acceptance['four_fields_complete_count'], 44)
            self.assertEqual(len(acceptance['items']),44)
            evidence = load_json(folder/'image_evidence.json')
            self.assertEqual(len(evidence),44)
            self.assertEqual(evidence[0]['position'], [0,0,0])
            self.assertTrue(evidence[0]['model_sha256'])
            self.assertEqual(evidence[0]['image_sha256'],hashlib.sha256((folder/evidence[0]['image']).read_bytes()).hexdigest())
            with zipfile.ZipFile(folder/'report.docx') as z:
                xml = etree.fromstring(z.read('word/document.xml'))
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            bookmarks=set(xml.xpath('//w:bookmarkStart/@w:name',namespaces=ns))
            anchors=xml.xpath('//w:hyperlink/@w:anchor',namespaces=ns)
            self.assertEqual(len(anchors),44)
            self.assertTrue(set(anchors)<=bookmarks)
            pdf=PdfReader(folder/'report.pdf')
            links=[a.get_object() for page in pdf.pages for a in page.get('/Annots',[]) if a.get_object().get('/Subtype')=='/Link']
            self.assertEqual(len(links),44)
            self.assertEqual(len(pdf.outline),44)
            self.assertTrue(verify_archive(folder)['ok'])
        self.assertEqual(p,original)

    def test_corrupted_download_zip_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            r=generate_report(payload(),temp,formats=('html',))
            folder=Path(r['directory'])
            (folder/'archive.zip').write_bytes(b'broken download')
            self.assertFalse(verify_archive(folder)['ok'])


if __name__ == '__main__':
    unittest.main()
