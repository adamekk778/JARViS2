"""3.14 AI sekretářka a volání za tebe – Twilio's webhooks (/twilio/<key>/…).

Twilio reaches them through the public HTTPS address set in Nastavení → Telefon. Each request must carry the key in
the path AND Twilio's signature made with your Twilio token – anything else gets 403.
"""
from __future__ import annotations

import hmac
from typing import Any
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response


def register(app: FastAPI, rt: Any) -> None:
    from .. import callagent

    async def form(request: Request, key: str) -> dict:
        if not hmac.compare_digest(key, callagent.hook_key(rt)):
            raise HTTPException(403)
        body = (await request.body())[:20000].decode("utf-8", "replace")
        params = dict(parse_qsl(body, keep_blank_values=True))
        pq = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        algo = request.headers.get("X-Twilio-Webhooks-Signature-Settings", "")
        if "algorithm=" in algo and "HMAC_SHA1" not in algo.upper():
            raise HTTPException(403)          # signed with a Twilio shared key, not the Auth Token JARVIS has
        if not callagent.verify(rt, pq, params, request.headers.get("X-Twilio-Signature", "")):
            raise HTTPException(403)
        return params

    def xml(text: str) -> Response:
        return Response(f'<?xml version="1.0" encoding="UTF-8"?>{text}', media_type="application/xml")

    def base(key: str) -> str:
        return f"{callagent.public_url(rt)}/twilio/{key}"

    @app.post("/twilio/{key}/voice")
    async def twilio_voice(key: str, request: Request):
        p = await form(request, key)
        return xml(callagent.incoming(rt, p.get("CallSid", ""), p.get("From", ""), base(key)))

    @app.post("/twilio/{key}/gather")
    async def twilio_gather(key: str, request: Request):
        p = await form(request, key)
        return xml(await callagent.heard(rt, request.query_params.get("c", ""), p.get("SpeechResult", ""), base(key)))

    @app.post("/twilio/{key}/out")
    async def twilio_out(key: str, request: Request):
        p = await form(request, key)
        return xml(callagent.answered(rt, request.query_params.get("c", ""), p.get("AnsweredBy", ""), base(key)))

    @app.post("/twilio/{key}/status")
    async def twilio_status(key: str, request: Request):
        p = await form(request, key)
        cid = request.query_params.get("c", "") or p.get("CallSid", "")
        if p.get("CallStatus") in ("completed", "busy", "no-answer", "failed", "canceled") and cid in callagent.calls(rt):
            c = callagent.calls(rt)[cid]
            if p.get("CallStatus") != "completed" and not c.get("result"):
                c["result"] = {"busy": "Obsazeno.", "no-answer": "Nikdo to nevzal.", "failed": "Hovor se nespojil.",
                               "canceled": "Hovor zrušen."}.get(p["CallStatus"], "")
            await callagent.finish(rt, cid)
        return Response(status_code=204)
