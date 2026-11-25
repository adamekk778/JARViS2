"""3.20 Přístupnost+ – HTTP routes:

- /api/i18n/<lang> – the interface dictionary Czech → that language (built-in starter words + your / the community's pack)
- /translate – a page for translators: every Czech text of the UI, the English one for reference, your translation;
  saved into the data folder and used at once (461, 462, 478, 487)
- /api/predict?q=… – the next words from your own writing (476)
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

NOSTORE = {"Cache-Control": "no-store"}

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Překlad JARVISe</title>
<style>:root{color-scheme:dark}body{margin:0;font:15px system-ui;background:#0b1118;color:#e8f1f8;padding:20px;max-width:1100px;margin:auto}
h1{color:#5fd3ff;font-size:22px}table{width:100%;border-collapse:collapse}td{border-bottom:1px solid #1c2a36;padding:6px;vertical-align:top}
td.src{width:38%}td.en{width:24%;color:#8aa0b2}input{width:100%;box-sizing:border-box;font:inherit;padding:6px;border-radius:8px;
border:1px solid #2a3a4a;background:#0f1922;color:inherit}button,select{font:inherit;padding:8px 14px;border-radius:10px;border:1px solid #2a3a4a;
background:#13202c;color:inherit}.bar{display:flex;gap:10px;align-items:center;position:sticky;top:0;background:#0b1118;padding:10px 0}
.muted{color:#8aa0b2}</style>
<h1>Překlad rozhraní JARVISe</h1>
<p class=muted>Vlevo český text, uprostřed anglický pro orientaci, vpravo tvůj překlad. Uloží se do tohoto PC a rozhraní ho hned použije;
soubor pak můžeš poslat ostatním (Stáhnout).</p>
<div class=bar><select id=lang><option value=sk>Slovenčina</option><option value=de>Deutsch</option><option value=pl>Polski</option>
<option value=uk>Українська</option></select><input id=filter placeholder="Hledat…" style="max-width:260px"><span id=count class=muted></span>
<button id=save>Uložit</button><button id=dl>Stáhnout</button></div><table id=t></table>
<script>
const $ = (id) => document.getElementById(id);
let keys = [], en = {}, pack = {};
async function load() {
  const lang = $('lang').value;
  [keys, en, pack] = await Promise.all([fetch('/api/i18n-keys').then(r => r.json()), fetch('/api/i18n/en').then(r => r.json()),
    fetch('/api/i18n/' + lang).then(r => r.json())]);
  draw();
}
function draw() {
  const f = $('filter').value.toLowerCase(), t = $('t'); t.replaceChildren();
  let done = 0;
  for (const k of keys) {
    if (pack[k]) done++;
    if (f && !k.toLowerCase().includes(f)) continue;
    const tr = document.createElement('tr');
    const a = document.createElement('td'); a.className = 'src'; a.textContent = k;
    const b = document.createElement('td'); b.className = 'en'; b.textContent = en[k] || '';
    const c = document.createElement('td'); const i = document.createElement('input'); i.value = pack[k] || '';
    i.oninput = () => { pack[k] = i.value; }; c.appendChild(i); tr.append(a, b, c); t.appendChild(tr);
  }
  $('count').textContent = `${done} / ${keys.length} přeloženo`;
}
$('lang').onchange = load; $('filter').oninput = draw;
$('save').onclick = async () => {
  const r = await fetch('/api/i18n/' + $('lang').value, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(pack)});
  $('count').textContent = r.ok ? 'Uloženo ✓' : 'Nepovedlo se uložit';
};
$('dl').onclick = () => {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(pack, null, 1)], {type: 'application/json'}));
  a.download = $('lang').value + '.json'; a.click();
};
load();
</script>"""


def register(app: FastAPI, rt: Any, require_auth: Callable[[Request], None]) -> None:
    from .. import accessx

    @app.get("/api/i18n-keys")
    async def i18n_keys(request: Request):
        require_auth(request)
        return JSONResponse(accessx.ui_keys(), headers=NOSTORE)

    @app.get("/api/i18n/{lang}")
    async def i18n_pack(lang: str, request: Request):
        require_auth(request)
        if lang == "en":
            from .. import paths

            import json

            f = paths.web_dist() / "i18n-en.json"
            try:
                return JSONResponse(json.loads(f.read_text(encoding="utf-8")), headers=NOSTORE)
            except (OSError, ValueError):
                return JSONResponse({}, headers=NOSTORE)
        if lang not in accessx.UI_LANGS:
            raise HTTPException(404, "Neznámý jazyk")
        return JSONResponse(accessx.ui_pack(lang), headers=NOSTORE)

    @app.post("/api/i18n/{lang}")
    async def i18n_save(lang: str, request: Request):
        require_auth(request)
        try:
            n = accessx.save_pack(lang, await request.json())
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        rt.bus.publish("lang_changed", lang=lang)
        return {"ok": True, "saved": n}

    @app.get("/translate")
    async def translate_page(request: Request):
        require_auth(request)
        return HTMLResponse(PAGE, headers=NOSTORE)

    @app.get("/api/predict")
    async def predict(q: str, request: Request):
        require_auth(request)
        return {"words": accessx.predictor(rt).next(q[-300:], 3)}
