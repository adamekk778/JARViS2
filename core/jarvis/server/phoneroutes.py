"""3.20 Telefon + Hodinky – HTTP routes (nápady 121–160):

- /api/watch/events – the watch's long-poll: vibration codes, timers, routes, the silent alarm, "find the watch"
- /api/watch/action, /api/phone/action – PC controls from the wrist and the phone's quick tiles (mute, lock, volume, slides)
- /api/watch/hr, /api/watch/workout, /api/watch/fall, /api/watch/route, /api/watch/complication
- /api/phone/loc (a time-limited location share), /share/loc/<token> (the page you send – unguessable, it expires)
- /api/phone/cam + /api/phonecam.mjpg (the phone as a webcam), /api/phone/scan (pages → one PDF)
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return body if isinstance(body, dict) else {}


def register(app: FastAPI, rt: Any, require_auth: Callable[[Request], None]) -> None:
    from .. import phonex

    @app.get("/api/watch/events")
    async def watch_events(request: Request, wait: float = 25.0):
        require_auth(request)
        phonex.seen(rt, "watch", _ip(request))
        return {"events": await phonex.watch(rt).poll(max(0.0, min(wait, 50.0)))}

    async def _action(request: Request) -> dict:
        require_auth(request)
        body = await _json(request)
        ok, msg = await phonex.pc_action(rt, str(body.get("action") or ""))
        return {"ok": ok, "message": msg}

    app.post("/api/watch/action")(_action)
    app.post("/api/phone/action")(_action)

    @app.post("/api/watch/hr")
    async def watch_hr(request: Request):
        require_auth(request)
        body = await _json(request)
        raw = body.get("samples")
        samples: list = raw[:120] if isinstance(raw, list) else [body]
        out: list[dict] = []
        for s in samples:
            try:
                out.append(phonex.add_hr(rt, int(s.get("bpm") or 0), str(body.get("source") or "watch"), str(s.get("ctx") or ""),
                                         float(s["ts"]) / (1000 if float(s["ts"]) > 1e11 else 1) if s.get("ts") else None))
            except (ValueError, TypeError, AttributeError):
                continue
        return {"ok": bool(out), "saved": len(out)}

    @app.post("/api/watch/workout")
    async def watch_workout(request: Request):
        require_auth(request)
        b = await _json(request)
        try:
            w = phonex.add_workout(rt, str(b.get("kind") or "other"), float(b.get("minutes") or 0), float(b.get("km") or 0),
                                   int(b.get("hr_avg") or 0), int(b.get("hr_max") or 0), str(b.get("note") or ""))
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e)) from None
        return {"ok": True, **w}

    @app.post("/api/watch/fall")
    async def watch_fall(request: Request):
        require_auth(request)
        b = await _json(request)
        lat, lon = b.get("lat"), b.get("lon")
        r = await phonex.on_fall(rt, float(lat) if lat is not None else None, float(lon) if lon is not None else None)
        return {"ok": True, **r}

    @app.post("/api/watch/route")
    async def watch_route(request: Request):
        require_auth(request)
        b = await _json(request)
        try:
            return await phonex.route(rt, float(b["lat"]), float(b["lon"]), str(b.get("to") or "")[:120], str(b.get("mode") or "foot"))
        except (KeyError, ValueError, TypeError):
            raise HTTPException(400, "Chybí poloha nebo cíl.") from None
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "message": f"Trasa nejde spočítat: {e}"}

    @app.get("/api/watch/complication")
    async def watch_complication(request: Request):
        require_auth(request)
        return phonex.complication(rt)

    # ---------- the phone
    @app.post("/api/phone/loc")
    async def phone_loc(request: Request):
        require_auth(request)
        b = await _json(request)
        try:
            ok = phonex.share_update(rt, str(b.get("token") or ""), float(b["lat"]), float(b["lon"]),
                                     float(b["acc"]) if b.get("acc") is not None else None)
        except (KeyError, ValueError, TypeError):
            raise HTTPException(400, "Špatná poloha.") from None
        return {"ok": ok, "stop": not ok}           # the share ended → the phone stops sending

    @app.get("/share/loc/{token}")
    async def share_loc(token: str):
        page = phonex.share_page(rt, token[:40])
        if page is None:
            return HTMLResponse("<!doctype html><meta charset=utf-8><p>Sdílení polohy skončilo.</p>", status_code=404)
        return HTMLResponse(page, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"})

    @app.post("/api/phone/cam")
    async def phone_cam(request: Request):
        require_auth(request)
        data = await request.body()
        try:
            phonex.camfeed(rt).put(data)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return {"ok": True}

    @app.get("/api/phonecam.mjpg")
    async def phone_cam_stream(request: Request):
        require_auth(request)
        feed = phonex.camfeed(rt)

        async def frames():
            last = 0.0
            idle = 0
            while idle < 600:                      # the stream ends 60 s after the phone stops sending
                if feed.ts != last and feed.frame:
                    last = feed.ts
                    idle = 0
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + feed.frame + b"\r\n"
                else:
                    idle += 1
                await asyncio.sleep(0.1)

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store"})

    @app.post("/api/phone/scan")
    async def phone_scan(request: Request):
        """Pages already uploaded (/api/upload) → one PDF in the files (and its link back to the phone)."""
        require_auth(request)
        b = await _json(request)
        paths = []
        for aid in (b.get("aids") or [])[:40]:
            att = rt.store.get(str(aid))
            if att and Path(att.path).exists():
                paths.append(Path(att.path))
        if not paths:
            raise HTTPException(400, "Žádné stránky.")
        import time as _t

        out = Path(rt.store.root) / "scans" / f"sken-{_t.strftime('%Y%m%d-%H%M%S')}.pdf"
        try:
            await asyncio.to_thread(phonex.scan_pdf, paths, out, str(b.get("mode") or "doc"))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Sken se nepovedl: {e}") from None
        att = await rt.store.save_path(out, "application/pdf", conv_id=rt.memory.current_conversation)
        return {"ok": True, "pages": len(paths), **att.public()}
