"""Notetaker and dictation tools (3.0): "nahraj tenhle hovor", "co jsme si řekli na posledním hovoru"."""
from __future__ import annotations

from typing import Literal

from .base import ToolResult, tool


@tool("record_call", "Nahrávání hovoru (mikrofon + zvuk PC) s přepisem po lidech, shrnutím a úkoly. "
      "action: start, stop, cancel (zahodit bez přepisu). Ostatní v hovoru je potřeba upozornit, že se nahrává.",
      category="systém", perm="system", danger_if=lambda a, ctx=None: a.get("action", "start") == "start")
async def record_call(ctx, action: Literal["start", "stop", "cancel"] = "start") -> ToolResult:
    nt = getattr(ctx, "notetaker", None)
    if nt is None:
        return ToolResult(False, "Nahrávání hovorů tady není dostupné.")
    res = nt.start() if action == "start" else nt.stop(cancel=action == "cancel")
    if not res.get("ok"):
        return ToolResult(False, res.get("message", "Nepovedlo se."))
    msg = {"start": "Nahrávám hovor. Nezapomeň říct ostatním, že nahráváš.",
           "stop": "Nahrávání skončilo, dělám přepis a shrnutí (najdeš ho v Diktování → Nahrávání hovorů).",
           "cancel": "Nahrávka zahozena."}[action]
    return ToolResult(True, msg, data=res)


@tool("call_notes", "Přepisy a shrnutí nahraných hovorů. Bez id vrátí seznam, s id celý zápis (shrnutí, body, úkoly, přepis).",
      category="systém", perm="system")
async def call_notes(ctx, id: str = "") -> ToolResult:
    nt = getattr(ctx, "notetaker", None)
    if nt is None:
        return ToolResult(False, "Nahrávání hovorů tady není dostupné.")
    if not id:
        items = nt.list()[:20]
        if not items:
            return ToolResult(True, "Zatím žádné nahrané hovory.", data=[])
        return ToolResult(True, "\n".join(f"{i['id']}: {i['title']} ({round((i['seconds'] or 0) / 60)} min, {i['status']})" for i in items), data=items)
    n = nt.get(id)
    if not n:
        return ToolResult(False, "Takový zápis neexistuje.")
    body = [f"# {n['title']}", n["summary"] or "", "", "Body:", *[f"- {p}" for p in n["points"]],
            "", "Úkoly:", *[f"- {t}" for t in n["todos"]], "", "Přepis:",
            *[f"{ln['who']}: {ln['text']}" for ln in n["transcript"]]]
    return ToolResult(True, "\n".join(body)[:12000], data={k: n[k] for k in ("id", "title", "summary", "points", "todos")})
