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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__, paths
from .pairing import pairing_info
from .ws import Connection
from ..tools.sites import safe_rel, site_path

log = logging.getLogger(__name__)
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _is_local(host: str | None) -> bool:
    return (host or "") in LOCAL_HOSTS


def _local_request(conn: Any, port: int) -> bool:
    """Local = from this PC AND not a web page from another origin (blocks drive-by sites and DNS rebinding)."""
    if not _is_local(conn.client.host if conn.client else None):
        return False
    host = (conn.headers.get("host") or "").lower()
    if host and host.split(":")[0] not in LOCAL_HOSTS | {"[::1]", "testserver"}:
        return False
    origin = conn.headers.get("origin")
    if origin and origin.rstrip("/").lower() not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}",
                                                      "http://testserver"}:
        return False
    return True


ACTIVE_MIME = ("text/html", "image/svg", "application/xhtml", "text/xml", "application/xml", "text/javascript",
               "application/javascript")


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

    def is_local(conn) -> bool:
        return _local_request(conn, rt.cfg.phone.port)

    def require_auth(request: Request) -> None:
        if is_local(request):
            return
        if not _token_ok(rt, _req_token(request)):
            raise HTTPException(401, "Chybí nebo je špatný token – spáruj telefon znovu.")

    @app.get("/api/health")
    async def health():
        return {"ok": True, "name": "JARVIS", "version": __version__}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        from .. import mobileplus

        local = is_local(ws)
        token = ws.query_params.get("token")
        guest = None if local or _token_ok(rt, token) else mobileplus.guest_for(rt, token)
        if not local and not _token_ok(rt, token) and not guest:
            await ws.accept()  # accept first so the client really sees code 4401 (→ "pair again")
            await ws.close(code=4401)
            return
        await ws.accept()
        await Connection(ws, rt, local, guest).run()

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
        active = att.mime.lower().startswith(ACTIVE_MIME) or att.name.lower().endswith((".html", ".htm", ".svg", ".xml", ".js"))
        return FileResponse(att.path, media_type="application/octet-stream" if active else att.mime, filename=att.name,
                            content_disposition_type="attachment" if (download or active) else "inline",
                            headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})

    @app.get("/api/files/{aid}/thumb")
    async def get_thumb(aid: str, request: Request):
        require_auth(request)
        p = rt.store.thumb_path(aid)
        if not p:
            raise HTTPException(404, "Bez náhledu")
        return FileResponse(p)

    @app.get("/api/pc_file")
    async def pc_file(request: Request, root: str, path: str):
        """OMEGA 415: a file from a folder shared with the phone (read-only; nothing outside the shared folders)."""
        from .. import mobileplus

        require_auth(request)
        try:
            f = mobileplus.shared_file(rt, root, path)
        except (PermissionError, FileNotFoundError) as e:
            raise HTTPException(404, str(e)) from e
        return FileResponse(f, filename=f.name)

    @app.get("/api/pairing")
    async def pairing(request: Request):
        if not is_local(request):
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

    @app.get("/chat")
    async def fullchat():
        return page("chat.html")

    @app.get("/hud")
    async def hud():
        return page("hud.html")

    @app.get("/sites/{site_id}/{rel:path}")
    async def site_file(site_id: str, rel: str = ""):
        """Websites JARVIS built. The unguessable id is the key; the sandbox CSP gives each page an opaque origin,
        so its scripts can never use this server's local trust."""
        root, rel = site_path(site_id), safe_rel(rel or "index.html")
        if root is None or rel is None:
            raise HTTPException(404, "Stránka nenalezena")
        f = (root / rel).resolve()
        if not f.is_relative_to(root.resolve()) or not f.is_file():
            raise HTTPException(404, "Stránka nenalezena")
        return FileResponse(f, headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff",
                                        "Content-Security-Policy": "sandbox allow-scripts allow-forms allow-modals allow-popups"})

    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    for extra in ("icons", "sounds"):
        if (dist / extra).exists():
            app.mount(f"/{extra}", StaticFiles(directory=dist / extra), name=extra)

    dist_root = dist.resolve()

    @app.post("/api/hooks/claude/{event}")
    async def claude_hook(event: str, request: Request):
        """Claude Code hooks (curl from ~/.claude/settings.json). Empty reply = no opinion."""
        if not is_local(request):
            raise HTTPException(403, "Jen z tohoto počítače")
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        res = await rt.claude.handle(event, payload if isinstance(payload, dict) else {})
        return JSONResponse(res) if res else Response(status_code=204)

    @app.get("/api/sounds/{name}")
    async def custom_sound(name: str, request: Request):
        """Your own interface sounds from the sounds folder (only names JARVIS knows)."""
        require_auth(request)
        fname = rt.custom_sounds().get(name)
        if not fname:
            raise HTTPException(404, "Žádný vlastní zvuk")
        return FileResponse(rt.sounds_dir() / fname)

    # ---------- 3.4 the phone app's background link ----------
    @app.get("/api/phone/poll")
    async def phone_poll(request: Request, wait: float = 25.0, battery: int | None = None, charging: int = 0):
        require_auth(request)
        if battery is not None:
            rt.phone.on_battery(battery, bool(charging))
        return {"commands": await rt.phone.poll(max(0.0, min(wait, 50.0)))}

    @app.post("/api/phone/ack")
    async def phone_ack(request: Request):
        require_auth(request)
        body = await request.json()
        rt.phone.ack(str(body.get("id", "")), str(body.get("state", "done")), str(body.get("detail", ""))[:2000])
        return {"ok": True}

    @app.post("/api/phone/notification")
    async def phone_notification(request: Request):
        require_auth(request)
        rt.phone.on_notification(await request.json())
        return {"ok": True}

    @app.post("/api/show")
    async def show(request: Request, view: str = "chat"):
        """A second launch of JARVIS.exe asks the running one to show its window."""
        if not is_local(request):
            raise HTTPException(403, "Jen z tohoto počítače")
        if rt.ui_hook:
            rt.ui_hook(view)
        return {"ok": True}

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        rel = request.url.path.lstrip("/")
        if rel and ":" not in rel and "\\" not in rel and ".." not in rel:
            f = (dist_root / rel).resolve()
            if f.is_relative_to(dist_root) and f.is_file():
                return FileResponse(f)
        return JSONResponse({"detail": getattr(exc, "detail", "Not found")}, status_code=404)

    return app
