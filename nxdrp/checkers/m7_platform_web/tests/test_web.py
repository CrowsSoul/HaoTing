"""Integration checks: real pipeline, immutable rules, concurrent API, NX gating."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from fastapi.testclient import TestClient
from nxdrp.contracts import ModelBundle
from nxdrp.checkers.m7_platform_web.backend._server import create_app
from nxdrp.checkers.m7_platform_web.backend._service import MODULE, ROOT, Platform


class WebTests(unittest.TestCase):
    def setUp(self):
        (MODULE / "runtime").mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="web-test-", dir=MODULE / "runtime")
        self.directory = Path(self.tmp.name)
        self.app = create_app(self.directory)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.platform = self.app.state.platform
        self.book = self.client.get("/api/rulebooks").json()[0]

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def upload(self, name="board_a.model.json"):
        response = self.client.post("/api/models", files={"file": (name, (ROOT / "mockdata/models" / name).read_bytes(), "application/json")})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def submit(self, model, book=None, only=None):
        response = self.client.post("/api/tasks", json={"model_id": model, "rulebook_id": book or self.book["id"], "only": only or []})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["id"]

    def done(self, key):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            task = self.client.get(f"/api/tasks/{key}").json()
            if task["state"] in {"completed", "failed"}:
                return task
            time.sleep(.03)
        self.fail("Task did not finish")

    def test_upload_pipeline_and_reports(self):
        key = self.submit(self.upload())
        self.assertEqual(self.done(key)["state"], "completed")
        result = self.client.get(f"/api/tasks/{key}/result").json()
        self.assertEqual(len(result["findings"]), 4)
        self.assertEqual({r["status"] for r in result["results"]}, {"ok"})
        self.assertFalse(result["load_errors"])
        self.assertEqual(self.client.get(f"/api/tasks/{key}/model").json()["model_id"], "board_a")
        report = self.client.get(f"/api/tasks/{key}/reports/html")
        self.assertEqual(report.status_code, 200)
        self.assertIn("尚未实现", report.text)
        self.assertIn("DFM-31", report.text)
        self.assertEqual(self.client.get(f"/api/tasks/{key}/download").json(), result)
        self.assertEqual(self.client.post(f"/api/tasks/{key}/reports/pdf").status_code, 422)

    def test_rule_versions_change_results_without_mutating_history(self):
        model = self.upload()
        old_task = self.submit(model)
        self.assertEqual(self.done(old_task)["summary"]["findings"], 4)
        book = copy.deepcopy(self.book["book"])
        book["version"] = "clearance-disabled"
        rule = next(r for r in book["rules"] if r["check_item_id"] == "DFM-02")
        rule["params"]["min_clearance_mm"] = 0
        saved = self.client.post("/api/rulebooks", json=book)
        self.assertEqual(saved.status_code, 201, saved.text)
        new_task = self.submit(model, saved.json()["id"])
        self.assertEqual(self.done(new_task)["summary"]["findings"], 3)
        self.assertEqual(self.client.get(f"/api/tasks/{old_task}/rules").json(), self.book["book"])
        self.assertEqual(len(self.client.get(f"/api/tasks/{old_task}/result").json()["findings"]), 4)
        # The example checker includes the exact threshold boundary (<=).
        rule["params"]["min_clearance_mm"] = .15
        edge=self.client.post("/api/rulebooks",json=book).json()
        boundary=self.submit(model,edge["id"],["DFM-02"])
        self.assertEqual(self.done(boundary)["summary"]["findings"],1)

    def test_ten_concurrent_upload_submit_read_and_isolation(self):
        def user(index):
            payload = json.loads((ROOT / "mockdata/models/board_a.model.json").read_text(encoding="utf-8"))
            payload["model_id"] = f"concurrent-user-{index}"
            upload = self.client.post("/api/models", files={"file": ("same-name.json", json.dumps(payload).encode())})
            self.assertEqual(upload.status_code, 201)
            key = self.submit(upload.json()["id"])
            self.assertEqual(self.client.get("/api/health").status_code, 200)
            self.assertEqual(self.done(key)["state"], "completed")
            result = self.client.get(f"/api/tasks/{key}/result").json()
            self.assertEqual(result["model_id"], payload["model_id"])
            self.assertEqual(len(result["findings"]), 4)
            return key, upload.json()["id"]
        with ThreadPoolExecutor(max_workers=10) as pool:
            records = list(pool.map(user, range(10)))
        self.assertEqual(len({r[0] for r in records}), 10)
        self.assertEqual(len({r[1] for r in records}), 10)
        self.assertEqual(len(self.client.get("/api/tasks").json()), 10)

    def test_validation_and_cross_site_writes(self):
        self.assertEqual(self.client.post("/api/models", files={"file": ("bad.json", b"{}")} ).status_code, 422)
        self.assertEqual(self.client.post("/api/models", files={"file": ("bad.json", b"not json")} ).status_code, 422)
        self.assertEqual(self.client.post("/api/models", files={"file": ("a.exe", b"test")} ).status_code, 422)
        self.assertEqual(self.client.get("/api/tasks/../../secret").status_code, 404)
        self.assertEqual(self.client.post("/api/samples/board_a.model.json",headers={"Origin":"https://untrusted.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/tasks",json={"model_id":"../x","rulebook_id":self.book["id"]}).status_code,422)
        book=copy.deepcopy(self.book["book"])
        next(r for r in book["rules"] if r["check_item_id"]=="DFM-02")["params"]["min_clearance_mm"]="not-a-number"
        self.assertEqual(self.client.post("/api/rulebooks",json=book).status_code,422)

    def test_exported_nx_model_and_mesh_face_mapping(self):
        key=self.submit(self.upload("pressure_port.model.json"))
        self.assertEqual(self.done(key)["state"],"completed")
        model=self.client.get(f"/api/tasks/{key}/model").json()
        self.assertGreater(len(model["faces"]),0)
        mesh={"vertices":[[0,0,0],[1,0,0],[0,1,0]],"triangles":[[0,1,2]],"face_ids":[model["faces"][0]["face_id"]],"units":model["units"],"coordinate_space":"assembly"}
        self.assertEqual(self.client.post(f"/api/tasks/{key}/mesh",json=mesh).status_code,200)
        self.assertEqual(self.client.get(f"/api/tasks/{key}/mesh").json(),mesh)
        mesh["face_ids"]=["nonexistent-face"]
        self.assertEqual(self.client.post(f"/api/tasks/{key}/mesh",json=mesh).status_code,422)
        mesh["face_ids"]=[model["faces"][0]["face_id"]]
        mesh["triangles"]=[[0,1,99]]
        self.assertEqual(self.client.post(f"/api/tasks/{key}/mesh",json=mesh).status_code,422)

    def test_m8_adapter_receives_task_snapshots(self):
        key=self.submit(self.upload()); self.done(key)
        seen={}
        def generate_report(**kwargs):
            seen.update(kwargs)
            Path(kwargs["output_path"]).write_bytes(b"test-only-provider-output")
        with patch.dict("sys.modules",{"m7_test_provider":SimpleNamespace(generate_report=generate_report)}), patch.dict("os.environ",{"M7_REPORT_PROVIDER":"m7_test_provider:generate_report"}):
            response=self.client.post(f"/api/tasks/{key}/reports/pdf")
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(self.client.get(response.json()["download_url"]).content,b"test-only-provider-output")
        self.assertEqual(seen["rulebook"],self.book["book"])
        self.assertEqual(seen["model"]["model_id"],"board_a")
        self.assertEqual(len(seen["result"]["findings"]),4)

    def test_nx_missing_failure_does_not_break_next_task(self):
        upload=self.client.post("/api/models",files={"file":("single.prt",b"invalid NX file")}).json()
        with patch("nxdrp.adapters.nx_batch.NxBatchAdapter.available",return_value=False):
            key=self.submit(upload["id"])
            task=self.done(key)
            self.assertEqual(task["state"],"failed")
            self.assertIn("NX",task["error"])
        good=self.submit(self.upload())
        self.assertEqual(self.done(good)["state"],"completed")

    def test_nx_concurrency_gate(self):
        counter={"active":0,"peak":0}
        lock=threading.Lock()
        model=ModelBundle.load(str(ROOT / "mockdata/models/board_a.model.json"))
        class FakeNx:
            def __init__(self, config): pass
            def available(self): return True
            def load(self, path):
                with lock:
                    counter["active"]+=1
                    counter["peak"]=max(counter["peak"],counter["active"])
                time.sleep(.15)
                with lock: counter["active"]-=1
                return model
        with patch("nxdrp.adapters.nx_batch.NxBatchAdapter",FakeNx):
            ids=[]
            for i in range(4):
                m=self.client.post("/api/models",files={"file":("single.prt",b"fake")}).json()
                ids.append(self.submit(m["id"]))
            self.assertTrue(all(self.done(key)["state"]=="completed" for key in ids))
        self.assertEqual(counter["peak"],1)

    def test_capacity_is_bounded(self):
        entered=threading.Event(); release=threading.Event()
        p=Platform(self.directory / "bounded",workers=1,nx_slots=1,capacity=1)
        p.start()
        try:
            model=p.register_model("a.json",(ROOT / "mockdata/models/board_a.model.json").read_bytes())
            book=p.store.all("rulebooks")[0]["id"]
            def hold(key):
                p.store.update("tasks",key,state="checking")
                entered.set(); release.wait(5)
            with patch.object(p,"_execute",side_effect=hold):
                p.submit(model["id"],book,[]); self.assertTrue(entered.wait(2))
                pending=p.submit(model["id"],book,[])
                self.assertEqual(p.task(pending["id"])["queue_position"],1)
                with self.assertRaises(OverflowError): p.submit(model["id"],book,[])
                release.set(); p.jobs.join()
        finally:
            release.set(); p.stop()

    def test_single_process_lock_and_restart_history(self):
        key=self.submit(self.upload()); self.done(key)
        other=Platform(self.directory)
        with self.assertRaises(RuntimeError): other.start()
        self.platform.store.update("tasks",key,state="checking")
        self.client.__exit__(None,None,None)
        self.client=TestClient(create_app(self.directory))
        self.client.__enter__()
        task=self.client.get(f"/api/tasks/{key}").json()
        self.assertEqual(task["state"],"failed")
        self.assertIn("重启",task["error"])
        self.assertEqual(len(self.client.get("/api/rulebooks").json()),1)


if __name__ == "__main__":
    (MODULE / "runtime").mkdir(exist_ok=True)
    unittest.main()
