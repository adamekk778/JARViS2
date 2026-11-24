"""3.14 JARVIS v celém domě – HTTP routes:

- /tts/<id>.mp3 – JARVIS's voice for a house speaker (Home Assistant's media player fetches it once; unguessable, 10 min)
- /ha/<key>/<room>/… – JARVIS as the brain of Home Assistant voice satellites (ESP32, HA Voice PE). Home Assistant →
  Integrace → Ollama → URL http://<PC>:8765/ha/<key>/<místnost>. It speaks Ollama's /api/tags and /api/chat (and the
  OpenAI-style /v1/chat/completions for other integrations). Only from the home network, only with the key.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import secrets as pysecrets
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

MODEL = "jarvis"
VOICE_RULE = ("Tohle přišlo z hlasového satelitu v místnosti a odpověď se přečte nahlas: odpověz 1–3 krátkými větami, "
              "bez Markdownu, odkazů a emoji.")


def satellite_key(rt: Any) -> str:
    key = getattr(rt.cfg.home, "satellite_key", "")
    if not key:
        key = pysecrets.token_urlsafe(12)
        rt.update_config({"home": {"satellite_key": key}})
    return key


def _home_net(request: Request) -> bool:
    try:
        ip = ipaddress.ip_address(request.client.host if request.client else "")
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
            return str(c or "").strip()
    return ""


async def answer(rt: Any, text: str, room: str) -> str:
    from .. import house

    house.of(rt).note_room(room)
    if not text:
        return ""
    where = f" Uživatel je v místnosti: {room}." if room and room != "-" else ""
    out = await rt.agent.handle(text, [], "satellite", extra_system=VOICE_RULE + where)
    return str(out or "").strip() or "Hotovo."


def register(app: FastAPI, rt: Any) -> None:
    @app.get("/tts/{name}")
    async def tts_audio(name: str):
        from .. import house

        got = house.audio_for(name.rsplit(".", 1)[0])
        if not got:
            raise HTTPException(404, "už neplatí")
        return Response(content=got[0], media_type=got[1])

    def check(request: Request, key: str) -> None:
        want = getattr(rt.cfg.home, "satellite_key", "")
        if not want or not hmac.compare_digest(key, want) or not _home_net(request):
            raise HTTPException(404, "Not Found")

    @app.get("/ha/{key}/{room}/api/version")
    async def sat_version(key: str, room: str, request: Request):
        check(request, key)
        return {"version": "0.9.0"}

    @app.get("/ha/{key}/{room}/api/tags")
    async def sat_tags(key: str, room: str, request: Request):
        check(request, key)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return {"models": [{"name": MODEL, "model": MODEL, "modified_at": now, "size": 0, "digest": "jarvis",
                            "details": {"family": "jarvis", "parameter_size": "", "quantization_level": ""}}]}

    @app.post("/ha/{key}/{room}/api/show")
    async def sat_show(key: str, room: str, request: Request):
        check(request, key)
        return {"modelfile": "", "parameters": "", "template": "", "details": {"family": "jarvis"}, "capabilities": ["completion"]}

    @app.post("/ha/{key}/{room}/api/chat")
    async def sat_chat(key: str, room: str, request: Request):
        check(request, key)
        body = await request.json()
        text = await answer(rt, last_user_text(body.get("messages") or []), room)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        msg = {"model": MODEL, "created_at": now, "message": {"role": "assistant", "content": text}, "done": True,
               "done_reason": "stop"}
        if body.get("stream", True):               # Ollama streams NDJSON by default: one chunk + the end
            async def gen():
                yield json.dumps({**msg, "done": False}, ensure_ascii=False) + "\n"
                yield json.dumps({"model": MODEL, "created_at": now, "message": {"role": "assistant", "content": ""},
                                  "done": True, "done_reason": "stop"}) + "\n"
            return StreamingResponse(gen(), media_type="application/x-ndjson")
        return JSONResponse(msg)

    @app.post("/ha/{key}/{room}/v1/chat/completions")
    async def sat_openai(key: str, room: str, request: Request):
        check(request, key)
        body = await request.json()
        text = await answer(rt, last_user_text(body.get("messages") or []), room)
        return {"id": "jarvis-" + pysecrets.token_hex(6), "object": "chat.completion", "created": int(time.time()), "model": MODEL,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}

    @app.get("/ha/{key}/{room}/v1/models")
    async def sat_models(key: str, room: str, request: Request):
        check(request, key)
        return {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "jarvis"}]}
