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

    @app.get("/learn/tuner")
    async def learn_tuner(request: Request):
        """3.20 (361) a tuner and a metronome (the microphone stays in the browser, nothing is sent)."""
        require_auth(request)
        from .. import learnx

        return HTMLResponse(learnx.tuner_page())

    @app.get("/learn/typing")
    async def learn_typing(request: Request):
        require_auth(request)
        from .. import learnx

        return HTMLResponse(learnx.typing_page())

    @app.post("/api/learn/typing")
    async def learn_typing_score(request: Request):
        require_auth(request)
        import time as _t

        from .. import learnx

        try:
            b = await request.json()
            learnx.db(rt).exec("INSERT INTO ln_typing VALUES (?,?,?)", (_t.time(), float(b.get("wpm") or 0), float(b.get("accuracy") or 0)))
        except Exception:  # noqa: BLE001
            return {"ok": False}
        return {"ok": True}

    @app.get("/family-calendar")
    async def family_calendar(request: Request):
        require_auth(request)
        import datetime as _dt

        from .. import familyx

        today = _dt.date.today()
        return HTMLResponse(familyx.week_html(rt, today - _dt.timedelta(days=today.weekday())), headers={"Cache-Control": "no-store"})

    @app.get("/write")
    async def write_page(request: Request):
        """3.20 (273) distraction-free writing (kept in this browser only)."""
        require_auth(request)
        from .. import workx

        return HTMLResponse(workx.write_page())

    @app.get("/board")
    async def board_page(request: Request):
        require_auth(request)
        from .. import workx

        return HTMLResponse(workx.board_html(rt), headers={"Cache-Control": "no-store"})

    @app.post("/api/board/move")
    async def board_move(request: Request):
        require_auth(request)
        from .. import workx

        try:
            b = await request.json()
            return {"ok": workx.board_move(rt, int(b.get("id") or 0), str(b.get("col") or ""))}
        except Exception:  # noqa: BLE001
            return {"ok": False}

    @app.get("/team/{token}")
    async def team_page(token: str):
        """3.20 (294) a small team's tasks – the link is the key (unguessable)."""
        from .. import bizx

        tasks = bizx.team_tasks(rt, token[:40])
        if tasks is None:
            return HTMLResponse("<!doctype html><meta charset=utf-8><p>Tým nenalezen.</p>", 404)
        return HTMLResponse(bizx.team_page(token[:40], tasks), headers=NOSTORE)

    @app.post("/team/{token}")
    async def team_add(token: str, request: Request):
        from urllib.parse import parse_qs

        from .. import bizx

        form = parse_qs((await request.body()).decode("utf-8", "replace")[:2000])
        bizx.team_add(rt, token[:40], (form.get("who") or [""])[0], (form.get("task") or [""])[0])
        tasks = bizx.team_tasks(rt, token[:40])
        if tasks is None:
            return HTMLResponse("<!doctype html><meta charset=utf-8><p>Tým nenalezen.</p>", 404)
        return HTMLResponse(bizx.team_page(token[:40], tasks), headers=NOSTORE)

    @app.post("/team/{token}/done/{tid}")
    async def team_done(token: str, tid: int):
        from .. import bizx

        bizx.team_done(rt, token[:40], tid)
        tasks = bizx.team_tasks(rt, token[:40]) or []
        return HTMLResponse(bizx.team_page(token[:40], tasks), headers=NOSTORE)

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
