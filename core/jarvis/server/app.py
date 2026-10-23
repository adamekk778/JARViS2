"""FastAPI app: WebSocket, files API, pairing, static web UI."""
from __future__ import annotations

import hmac
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, paths
from .pairing import pairing_info
from .ws import Connection

log = logging.getLogger(__name__)
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _is_local(host: str | None) -> bool:
    return (host or "") in LOCAL_HOSTS


def _token_ok(rt: Any, supplied: str | None) -> bool:
    return bool(supplied) and hmac.compare_digest(supplied, rt.cfg.phone.token)


def _req_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return request.query_params.get("token")


def create_app(rt: Any, *, manage_runtime: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if manage_runtime:
            await rt.start()
        yield
        if manage_runtime:
            await rt.stop()

    app = FastAPI(title="JARVIS 2", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def require_auth(request: Request) -> None:
        if _is_local(request.client.host if request.client else None):
            return
        if not _token_ok(rt, _req_token(request)):
            raise HTTPException(401, "Chybí nebo je špatný token – spáruj telefon znovu.")

    @app.get("/api/health")
    async def health():
        return {"ok": True, "name": "JARVIS", "version": __version__}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        host = ws.client.host if ws.client else None
        local = _is_local(host)
        if not local and not _token_ok(rt, ws.query_params.get("token")):
            await ws.close(code=4401)
            return
        await ws.accept()
        await Connection(ws, rt, local).run()

    @app.post("/api/upload")
    async def upload(request: Request, file: UploadFile):
        require_auth(request)
        limit = rt.cfg.memory.max_upload_mb * 2**20
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"Soubor je větší než {rt.cfg.memory.max_upload_mb} MB")
        mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
        att = await rt.store.save(file.filename or "soubor", data, mime, conv_id=rt.memory.current_conversation)
        return att.public()

    @app.get("/api/files/{aid}")
    async def get_file(aid: str, request: Request, download: int = 0):
        require_auth(request)
        att = rt.store.get(aid)
        if not att or not Path(att.path).exists():
            raise HTTPException(404, "Soubor nenalezen")
        return FileResponse(att.path, media_type=att.mime, filename=att.name,
                            content_disposition_type="attachment" if download else "inline")

    @app.get("/api/files/{aid}/thumb")
    async def get_thumb(aid: str, request: Request):
        require_auth(request)
        p = rt.store.thumb_path(aid)
        if not p:
            raise HTTPException(404, "Bez náhledu")
        return FileResponse(p)

    @app.get("/api/pairing")
    async def pairing(request: Request):
        if not _is_local(request.client.host if request.client else None):
            raise HTTPException(403, "Jen z tohoto počítače")
        return pairing_info(rt.cfg.phone.token, rt.cfg.phone.port)

    dist = paths.web_dist()

    def page(name: str):
        p = dist / name
        if p.exists():
            return FileResponse(p, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(f"<h1>JARVIS</h1><p>Web UI není sestavené ({p}).</p>", status_code=503)

    @app.get("/")
    async def index():
        return page("index.html")

    @app.get("/notch")
    async def notch():
        return page("notch.html")

    @app.get("/mobile")
    async def mobile():
        return page("mobile.html")

    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    for extra in ("icons", "sounds"):
        if (dist / extra).exists():
            app.mount(f"/{extra}", StaticFiles(directory=dist / extra), name=extra)

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        f = dist / request.url.path.lstrip("/")
        if request.url.path.count("..") == 0 and f.is_file():
            return FileResponse(f)
        return JSONResponse({"detail": getattr(exc, "detail", "Not found")}, status_code=404)

    return app
