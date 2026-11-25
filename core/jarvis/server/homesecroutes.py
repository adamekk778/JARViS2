"""3.20 Domácnost+ a Bezpečnost+ – HTTP routes:

- /canary/<token>(.png) – a bait file was opened (no login: the bait has to reach it; the token is unguessable)
- /s/<token> – a one-time secret: GET shows a button (link previews do not burn it), POST shows it once and deletes it
- /house-map – the house with live states (a page for the dashboard or the phone)
"""
from __future__ import annotations

import base64
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response

PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/6XZr4kAAAAASUVORK5CYII=")
NOSTORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"}


def register(app: FastAPI, rt: Any, require_auth: Callable[[Request], None]) -> None:
    from .. import homex, secx

    async def canary(token: str, request: Request):
        tok = token.removesuffix(".png")[:40]
        secx.canary_hit(rt, tok, request.client.host if request.client else "", request.headers.get("user-agent", "")[:120])
        if token.endswith(".png"):
            return Response(PIXEL, media_type="image/png", headers=NOSTORE)
        return HTMLResponse("<!doctype html><meta charset=utf-8><title>Chyba</title><p>Stránka není dostupná.</p>", 404, headers=NOSTORE)

    app.get("/canary/{token}")(canary)

    @app.get("/s/{token}")
    async def oneshot_view(token: str):
        return HTMLResponse(secx.oneshot_page(token[:40]), headers=NOSTORE)

    @app.post("/s/{token}")
    async def oneshot_reveal(token: str):
        text = secx.oneshot_reveal(rt, token[:40])
        return HTMLResponse(secx.oneshot_page(token[:40], revealed=text, gone=text is None), status_code=200 if text is not None else 410,
                            headers=NOSTORE)

    @app.get("/house-map")
    async def house_map(request: Request):
        require_auth(request)
        from ..homeplus import raw_states, rooms

        try:
            st = homex.norm(await raw_states(rt))
        except Exception as e:  # noqa: BLE001
            return HTMLResponse(f"<!doctype html><meta charset=utf-8><p>Home Assistant teď neodpovídá: {type(e).__name__}</p>", 503)
        try:
            rms = await rooms(rt)
        except Exception:  # noqa: BLE001
            rms = None
        c = rt.cfg.homex
        return HTMLResponse(homex.map_html(homex.house_map(st, rms, c.map_positions), c.floorplan), headers={"Cache-Control": "no-store"})
