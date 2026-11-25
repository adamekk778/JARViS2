"""3.20 Zábava+ – the quiz on the guests' phones (347, 355):

- /quiz/<token> – the player's page (no login: the token is the invitation; each player gets their own key for answers)
- /quiz/<token>/host – the big screen on the PC (login / this PC only): the QR to join, the question, who answered, the scores
"""
from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

NOSTORE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"}

STYLE = ("<style>:root{color-scheme:dark}body{margin:0;font:18px system-ui;background:#0b1118;color:#e8f1f8;padding:20px;max-width:760px;"
         "margin:auto}h1{font-size:22px;color:#5fd3ff}button{font:inherit;padding:14px;border-radius:12px;border:1px solid #2a3a4a;"
         "background:#13202c;color:inherit;width:100%;margin:6px 0;text-align:left}button.ok{background:#11402a;border-color:#2fbf71}"
         "button.bad{background:#401818}input{font:inherit;padding:12px;border-radius:10px;border:1px solid #2a3a4a;background:#0f1922;"
         "color:inherit;width:100%;box-sizing:border-box}.muted{color:#8aa0b2;font-size:15px}.row{display:flex;justify-content:space-between;"
         "padding:6px 0;border-bottom:1px solid #1c2a36}</style>")

PLAYER_JS = """
const tok = location.pathname.split('/')[2];
let me = JSON.parse(localStorage.getItem('jq_'+tok) || 'null');
const $ = (id) => document.getElementById(id);
async function join() {
  const r = await fetch(`/api/quiz/${tok}/join`, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: $('name').value})});
  if (!r.ok) { $('msg').textContent = 'Nepovedlo se připojit.'; return; }
  me = await r.json(); localStorage.setItem('jq_'+tok, JSON.stringify(me)); draw();
}
async function answer(i) {
  await fetch(`/api/quiz/${tok}/answer`, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({who: me.name, key: me.key, pick: i})});
  poll();
}
let last = null;
async function poll() {
  const r = await fetch(`/api/quiz/${tok}`); if (!r.ok) { $('msg').textContent = 'Kvíz skončil.'; return; }
  last = await r.json(); draw();
}
function draw() {
  $('join').hidden = !!me; $('play').hidden = !me; if (!me || !last) return;
  $('who').textContent = me.name;
  const box = $('opts'); box.replaceChildren();
  if (last.done) { $('q').textContent = 'Konec! Výsledky jsou na velké obrazovce.'; }
  else if (!last.q) { $('q').textContent = 'Čekáme na první otázku…'; }
  else {
    $('q').textContent = last.q.q + (last.q.music ? ' 🎵' : '');
    const mine = last.answered.includes(me.name);
    last.q.a.forEach((a, i) => {
      const b = document.createElement('button'); b.textContent = `${'ABCD'[i]}  ${a}`;
      b.disabled = mine || !last.open;
      if (!last.open && last.ok === i) b.className = 'ok';
      b.onclick = () => answer(i); box.appendChild(b);
    });
    $('msg').textContent = mine && last.open ? 'Odpověď odeslána.' : '';
  }
  const pts = (last.players.find((p) => p[0] === me.name) || [0, 0])[1];
  $('pts').textContent = `${pts} bodů`;
}
$('go').onclick = join; setInterval(poll, 1500); poll();
"""

HOST_JS = """
const tok = location.pathname.split('/')[2];
const $ = (id) => document.getElementById(id);
let lastI = -2;
async function poll() {
  const r = await fetch(`/api/quiz/${tok}/host-state`); if (!r.ok) return;
  const s = await r.json();
  $('n').textContent = s.done ? 'Konec' : (s.i < 0 ? 'Připojte se' : `Otázka ${s.i + 1} / ${s.n}`);
  $('q').textContent = s.q ? s.q.q : (s.done ? '🏆 Výsledky' : 'Naskenujte QR kód telefonem');
  const box = $('opts'); box.replaceChildren();
  if (s.q) s.q.a.forEach((a, i) => { const d = document.createElement('div'); d.className = 'row';
    d.textContent = `${'ABCD'[i]}  ${a}` + (!s.open && s.ok === i ? '  ✔' : ''); box.appendChild(d); });
  $('ans').textContent = s.q && s.open ? `Odpověděli: ${s.answered.length} / ${s.players.length}` : '';
  const sc = $('score'); sc.replaceChildren();
  s.players.forEach(([name, pts], i) => { const d = document.createElement('div'); d.className = 'row';
    const a = document.createElement('span'); a.textContent = `${i + 1}. ${name}`; const b = document.createElement('b'); b.textContent = pts;
    d.append(a, b); sc.appendChild(d); });
  $('next').textContent = s.i < 0 ? 'Začít' : (s.open ? 'Ukázat odpověď a další' : 'Další otázka');
  $('next').hidden = s.done;
  if (s.i !== lastI && s.q && s.q.music) { const au = $('clip'); au.src = `/api/quiz/${tok}/clip#t=${s.q.start || 30}`; au.play().catch(() => {});
    setTimeout(() => au.pause(), 12000); }
  lastI = s.i;
}
$('next').onclick = async () => { await fetch(`/api/quiz/${tok}/next`, {method: 'POST'}); poll(); };
setInterval(poll, 1200); poll();
"""


def player_page() -> str:
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Kvíz</title>" + STYLE +
            "<h1>Kvíz</h1><div id=join><p>Jak ti máme říkat?</p><input id=name maxlength=20 autocomplete=off>"
            "<button id=go>Připojit se</button></div><div id=play hidden><p class=muted><span id=who></span> · <span id=pts></span></p>"
            "<h2 id=q></h2><div id=opts></div></div><p id=msg class=muted></p><script>" + PLAYER_JS + "</script>")


def host_page(join_url: str) -> str:
    import qrcode

    img = qrcode.make(join_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr = base64.b64encode(buf.getvalue()).decode()
    return ("<!doctype html><meta charset=utf-8><title>Kvíz – obrazovka</title>" + STYLE.replace("max-width:760px", "max-width:1100px") +
            "<div style='display:grid;grid-template-columns:2fr 1fr;gap:28px'><div><p id=n class=muted></p><h1 id=q style='font-size:34px'></h1>"
            "<div id=opts style='font-size:24px'></div><p id=ans class=muted></p><button id=next style='text-align:center'>Začít</button>"
            "<audio id=clip></audio></div><div><img alt='QR kód pro připojení' style='width:100%;background:#fff;border-radius:12px' "
            f"src='data:image/png;base64,{qr}'><p class=muted style='word-break:break-all'>{join_url}</p><h1>Pořadí</h1><div id=score></div>"
            "</div></div><script>" + HOST_JS + "</script>")


def register(app: FastAPI, rt: Any, require_auth: Callable[[Request], None]) -> None:
    from .. import funx

    def get(tok: str) -> dict:
        d = funx.quiz_get(rt, tok[:20])
        if d is None:
            raise HTTPException(404, "Kvíz neexistuje")
        return d

    @app.get("/quiz/{tok}")
    async def quiz_player(tok: str):
        get(tok)
        return HTMLResponse(player_page(), headers=NOSTORE)

    @app.get("/api/quiz/{tok}")
    async def quiz_state(tok: str):
        return JSONResponse(funx.quiz_public(get(tok)), headers=NOSTORE)

    @app.post("/api/quiz/{tok}/join")
    async def quiz_join(tok: str, request: Request):
        get(tok)
        body = await request.json()
        try:
            name, key = funx.quiz_join(rt, tok[:20], str(body.get("name", ""))[:40])
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return {"name": name, "key": key}

    @app.post("/api/quiz/{tok}/answer")
    async def quiz_answer(tok: str, request: Request):
        body = await request.json()
        try:
            pick = int(body.get("pick", -1))
        except (TypeError, ValueError):
            pick = -1
        return {"ok": funx.quiz_answer(rt, tok[:20], str(body.get("who", ""))[:40], pick, str(body.get("key", ""))[:40])}

    @app.get("/quiz/{tok}/host")
    async def quiz_host(tok: str, request: Request):
        require_auth(request)
        get(tok)
        base = str(getattr(rt.cfg.phone_link, "public_url", "") or "").rstrip("/")
        if not base:
            from ..house import lan_ip

            base = f"http://{lan_ip()}:{rt.cfg.phone.port}"
        return HTMLResponse(host_page(f"{base}/quiz/{tok[:20]}"), headers=NOSTORE)

    @app.get("/api/quiz/{tok}/host-state")
    async def quiz_host_state(tok: str, request: Request):
        require_auth(request)
        d = get(tok)
        out = funx.quiz_public(d, host=True)
        cur = d["q"][d["i"]] if 0 <= d["i"] < len(d["q"]) else None
        if cur and out.get("q") is not None:
            out["q"]["start"] = cur.get("start", 30)
        return JSONResponse(out, headers=NOSTORE)

    @app.post("/api/quiz/{tok}/next")
    async def quiz_next(tok: str, request: Request):
        require_auth(request)
        get(tok)
        return funx.quiz_public(funx.quiz_next(rt, tok[:20]), host=True)

    @app.get("/api/quiz/{tok}/clip")
    async def quiz_clip(tok: str, request: Request):
        require_auth(request)
        d = get(tok)
        cur = d["q"][d["i"]] if 0 <= d["i"] < len(d["q"]) else None
        if not cur or not cur.get("clip"):
            raise HTTPException(404, "Žádná ukázka")
        f = Path(cur["clip"])
        roots = [Path(x).expanduser().resolve() for x in rt.cfg.funx.music_dirs]
        if not f.is_file() or not any(f.resolve().is_relative_to(r) for r in roots):
            raise HTTPException(403, "Mimo složky s hudbou")
        return FileResponse(f)
