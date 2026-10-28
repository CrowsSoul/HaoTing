from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from nxdrp.pipeline import coverage
from nxdrp.registry import discover
from ._service import Platform, MODULE, ROOT


class NewTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    rulebook_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    only: list[str] = Field(default_factory=list, max_length=44)


def create_app(directory: Path | None = None, workers: int = 4, nx_slots: int = 1, capacity: int = 100, max_upload: int = 100 * 1024 * 1024) -> FastAPI:
    service = Platform(directory or MODULE / "runtime", workers, nx_slots, capacity)

    @asynccontextmanager
    async def lifespan(app):
        service.start()
        yield
        service.stop()

    app = FastAPI(title="NXDRP M7 Web", version="0.1.0", lifespan=lifespan)
    app.state.platform = service

    @app.middleware("http")
    async def headers(request: Request, call_next):
        # Requests from another origin cannot change local files/tasks.
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            from urllib.parse import urlsplit
            allowed = {request.headers.get("host"), "127.0.0.1:5173", "localhost:5173"}
            if urlsplit(origin).netloc not in allowed:
                return JSONResponse({"detail": "拒绝跨站写入请求"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(OverflowError)
    async def busy(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=429)

    @app.get("/api/health")
    def health():
        from nxdrp.adapters.nx_batch import NxBatchAdapter
        return {"status": "ok", "nx_available": NxBatchAdapter().available(), "workers": workers, "nx_slots": nx_slots, "queue_capacity": capacity, "m8_available": bool(os.environ.get("M7_REPORT_PROVIDER")), "visualization": "bbox"}

    @app.get("/api/catalog")
    def catalog():
        return coverage(discover())

    @app.get("/api/samples")
    def samples():
        return [p.name for p in sorted((ROOT / "mockdata/models").glob("*.model.json"))]

    @app.post("/api/samples/{name}", status_code=201)
    def sample(name: str):
        allowed = {p.name: p for p in (ROOT / "mockdata/models").glob("*.model.json")}
        if name not in allowed:
            raise HTTPException(404, "示例不存在")
        return service.register_model(name, allowed[name].read_bytes())

    @app.post("/api/models", status_code=201)
    def upload(file: UploadFile):
        data = file.file.read(max_upload + 1)
        if len(data) > max_upload:
            raise HTTPException(413, "文件超过大小限制")
        try:
            return service.register_model(file.filename or "", data)
        except Exception as exc:
            raise HTTPException(422, f"模型无效：{exc}") from exc
        finally:
            file.file.close()

    @app.get("/api/rulebooks")
    def rulebooks():
        return service.store.all("rulebooks")[::-1]

    @app.post("/api/rulebooks", status_code=201)
    def save_rulebook(payload: dict):
        try:
            return service.save_rulebook(payload)
        except Exception as exc:
            raise HTTPException(422, f"规则无效：{exc}") from exc

    @app.post("/api/tasks", status_code=202)
    def submit(payload: NewTask):
        return service.submit(payload.model_id, payload.rulebook_id, payload.only)

    @app.get("/api/tasks")
    def tasks():
        return [service.task(t["id"]) for t in service.store.all("tasks")[::-1]]

    @app.get("/api/tasks/{key}")
    def task(key: str):
        return service.task(key)

    @app.get("/api/tasks/{key}/result")
    def result(key: str):
        return service.result(key)

    @app.get("/api/tasks/{key}/model")
    def geometry(key: str):
        path = service.artifact(key, "model.json")
        if not path.is_file():
            raise HTTPException(409, "模型尚未解析完成")
        return FileResponse(path, media_type="application/json")

    @app.get("/api/tasks/{key}/rules")
    def snapshot(key: str):
        return FileResponse(service.artifact(key, "rules.json"), media_type="application/json", filename="rules-snapshot.json")

    @app.post("/api/tasks/{key}/mesh")
    def attach_mesh(key: str, payload: dict):
        return service.attach_mesh(key, payload)

    @app.get("/api/tasks/{key}/mesh")
    def get_mesh(key: str):
        path = service.artifact(key,"mesh.json")
        if not path.is_file():
            raise HTTPException(404,"尚未附加带面 ID 的显示网格")
        return FileResponse(path,media_type="application/json")

    @app.get("/api/tasks/{key}/download")
    def download(key: str):
        service.result(key)
        return FileResponse(service.artifact(key, "result.json"), media_type="application/json", filename=f"{key}-result.json")

    @app.get("/api/tasks/{key}/reports/html")
    def report(key: str):
        return FileResponse(service.report(key), media_type="text/html", filename=f"{key}-report.html")

    @app.post("/api/tasks/{key}/reports/{fmt}")
    def external_report(key: str, fmt: str):
        # Starlette runs synchronous routes in its thread pool, away from the event loop.
        service.generate_external_report(key, fmt)
        return {"download_url": f"/api/tasks/{key}/reports/{fmt}"}

    @app.get("/api/tasks/{key}/reports/{fmt}")
    def download_external_report(key: str, fmt: str):
        if fmt not in {"pdf", "docx"}:
            raise HTTPException(404, "格式不存在")
        path = service.artifact(key, "report." + fmt)
        if not path.is_file() or service.task(key)["report_state"] != "available":
            raise HTTPException(409, "报告尚未生成")
        return FileResponse(path, filename=path.name)

    dist = MODULE / "frontend/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    else:
        @app.get("/")
        def index():
            return {"message": "请先构建前端，或使用 Vite 开发服务器", "docs": "/docs"}
    return app
