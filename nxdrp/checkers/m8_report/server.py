"""仅监听本机的轻量界面及 M7 集成 API。"""
from __future__ import annotations
import base64
import json
import mimetypes
import secrets
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from .core import HERE, load_json, knowledge
from .service import (capabilities, generate_report, list_archives, search_cases,
                      report_directory, verify_archive)
from ...catalog import CATALOG
from . import __version__

MAX_BODY = 32*1024*1024

def serve(archive_root="m8_archives", port=8768, browser=True):
    archive = Path(archive_root).resolve()
    archive.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # 上传内容与本地路径不写日志。
            pass
        def send(self, status, data, mime="application/json; charset=utf-8"):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        def valid_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}
        def do_GET(self):
            if not self.valid_host():
                return self.send(403, {"error": "仅允许本机访问"})
            parsed = urlparse(self.path)
            path, query = unquote(parsed.path), parse_qs(parsed.query)
            q = lambda name: query.get(name, [""])[0]
            try:
                if path == "/":
                    content = (HERE/"web/index.html").read_text(encoding="utf-8").replace("__TOKEN__", token)
                    return self.send(200, content.encode("utf-8"), "text/html; charset=utf-8")
                if path == "/api/info":
                    return self.send(200, {"capabilities": capabilities(), "catalog_count": len(CATALOG), "version": __version__})
                if path == "/api/archives":
                    return self.send(200, list_archives(archive, q("q"), q("severity"), q("item")))
                if path == "/api/cases":
                    return self.send(200, search_cases(archive, q("q"), q("severity"), q("item")))
                if path == "/api/knowledge":
                    kb = knowledge()
                    rows = [{"id": i.check_item_id, "name": i.name_cn, "owner": i.owner_module,
                             "text": kb["items"][i.check_item_id]} for i in CATALOG]
                    rows = [r for r in rows if q("q").casefold() in json.dumps(r, ensure_ascii=False).casefold()]
                    return self.send(200, {"version": kb["version"], "source": kb["source"], "items": rows})
                if path.startswith("/reports/"):
                    parts = path.split("/")
                    if len(parts) < 4:
                        raise FileNotFoundError("文件不存在")
                    folder = report_directory(archive, parts[2])
                    target = (folder/"/".join(parts[3:])).resolve()
                    if not target.is_relative_to(folder) or not target.is_file():
                        raise FileNotFoundError("文件不存在")
                    return self.send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")
                return self.send(404, {"error": "接口不存在"})
            except (ValueError, OSError, KeyError) as e:
                return self.send(400, {"error": str(e)})
        def do_POST(self):
            if not self.valid_host() or self.headers.get("X-M8-Token") != token:
                return self.send(403, {"error": "页面验证已失效，请刷新本机页面"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BODY:
                    return self.send(413, {"error": "单次导入请控制在 32 MB 内"})
                payload = json.loads(self.rfile.read(size), parse_constant=lambda x: (_ for _ in ()).throw(ValueError("不允许非有限数值")))
                if not isinstance(payload, dict):
                    raise ValueError("请求必须是 JSON 对象")
                if self.path == "/api/demo":
                    from .cli import demo
                    caps = capabilities()
                    result = demo(archive, tuple(x for x in ("html", "pdf", "docx") if caps[x]), payload.get("scene", "board_a"))
                    return self.send(200, result)
                if self.path == "/api/generate":
                    with tempfile.TemporaryDirectory(prefix="m8-upload-") as temp:
                        temp = Path(temp)
                        shots = {}
                        for idx, shot in enumerate(payload.get("screenshots", [])):
                            fid = shot["finding_id"]
                            if fid in shots:
                                raise ValueError("同一问题不能重复提交截图")
                            file = temp/f"shot-{idx}.png"
                            file.write_bytes(base64.b64decode(shot["base64"], validate=True))
                            shots[fid] = file
                        mesh = None
                        if payload.get("mesh_base64"):
                            mesh = temp/"uploaded.stl"
                            mesh.write_bytes(base64.b64decode(payload["mesh_base64"], validate=True))
                        caps = capabilities()
                        result = generate_report(payload.get("findings"), archive, model=payload.get("model"), rules=payload.get("rules"),
                                                 screenshots=shots, mesh=mesh, title=payload.get("title") or "连接器设计检查报告",
                                                 formats=tuple(x for x in ("html", "pdf", "docx") if caps[x]),
                                                 require_complete=payload.get('require_complete') is True)
                    return self.send(200, result)
                if self.path == "/api/verify":
                    return self.send(200, verify_archive(report_directory(archive, payload["report_id"])))
                return self.send(404, {"error": "接口不存在"})
            except (ValueError, OSError, KeyError, TypeError, RuntimeError, ImportError) as e:
                return self.send(400, {"error": str(e)})
            except Exception:
                return self.send(500, {"error": "生成失败，请检查输入数据与导出依赖；原归档不受影响。"})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"M8 报告与知识库：http://127.0.0.1:{port}", flush=True)
    if browser:
        threading.Timer(.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
