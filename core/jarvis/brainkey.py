"""3.12 Mozek jen z API klíče: paste a key, JARVIS recognises the service by the key itself, sets up everything else
(address, models) on its own, puts it first and tries it at once – no server, no localhost, no settings to fill in.
"""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from . import secrets
from .llm.presets import PRESETS

# the start of the key → the service (the order matters: sk-ant- / sk-or- before plain sk-)
RULES: list[tuple[str, str]] = [("gsk_", "groq"), ("AIza", "gemini"), ("sk-ant-", "anthropic"), ("sk-or-", "openrouter"),
                                ("sk-", "openai")]
LABEL = {"groq": "Groq", "gemini": "Google Gemini", "anthropic": "Anthropic Claude", "openrouter": "OpenRouter", "openai": "OpenAI"}
HELP = ("Nepoznám, od koho klíč je. Funguje klíč od Groq (začíná gsk_), Google Gemini (AIza…), OpenAI (sk-…), "
        "Anthropic (sk-ant-…) nebo OpenRouter (sk-or-…). Zdarma ho dostaneš na console.groq.com nebo aistudio.google.com.")


def clean(key: str) -> str:
    """Pasted keys often carry spaces, line breaks or quotes – a key never has any."""
    return re.sub(r"[\s\"'“”„‚‘’`]", "", key or "")


def detect(key: str) -> str | None:
    for prefix, preset in RULES:
        if key.startswith(prefix):
            return preset
    return None


def explain(err: str) -> tuple[bool, str]:
    """The error of a test in plain words; (True, …) when the key itself is fine (only a limit / a busy service)."""
    e = err.lower()
    if re.search(r"\b429\b|rate.?limit|quota|too many|resource.?exhausted", e):
        return True, "Klíč funguje – služba teď jen hlásí limit. Za chvíli to půjde, JARVIS mezitím zkusí jiný mozek."
    if re.search(r"\b40[13]\b|unauthori|invalid.{0,20}(key|api)|incorrect api key|permission|api key not valid|authentication", e):
        return False, "Služba klíč odmítla. Je zkopírovaný celý? Zkus ho na stránce služby zkopírovat znovu (nebo vytvořit nový)."
    if re.search(r"timed? ?out|timeout", e):
        return False, "Služba neodpověděla včas. Je PC připojené k internetu?"
    if re.search(r"connect|name or service|getaddrinfo|network|unreachable|ssl", e):
        return False, "Nejde se spojit se službou. Je PC připojené k internetu (a nic ho neblokuje – antivir, VPN)?"
    return False, f"Nepovedlo se: {err[:160]}"


async def apply(rt: Any, key: str, test: Callable[[str], Awaitable[dict]]) -> dict:
    """Save the key for the right service, make that service the first brain and try it."""
    key = clean(key)
    if len(key) < 20:
        return {"ok": False, "message": "Tohle nevypadá jako celý API klíč – zkopíruj ho celý."}
    preset = detect(key)
    if not preset:
        return {"ok": False, "message": HELP}
    pr = PRESETS[preset]
    provs = [p.model_dump() for p in rt.cfg.brain.providers]
    found = next((p for p in provs if p.get("preset") == preset), None)
    if found is None:
        pid, n = preset, 2
        while any(p["id"] == pid for p in provs):
            pid, n = f"{preset}{n}", n + 1
        found = {"id": pid, "preset": preset, "base_url": pr["base_url"], "model": pr.get("model", ""),
                 "vision_model": pr.get("vision_model", ""), "fast_model": pr.get("fast_model", ""), "enabled": True}
        provs.append(found)
    else:                                           # an old, broken setup of the same service: back to what works
        found.update(base_url=pr["base_url"], enabled=True)
        found["model"] = found.get("model") or pr.get("model", "")
    pid = found["id"]
    secrets.set(pid, key)
    if preset == "groq":
        if pid != "groq":
            secrets.set("groq", key)               # speech recognition (voice, subtitles) looks for it here
        from .voice.stt import Transcriber

        Transcriber._groq_seen = (0.0, False)      # the voice uses Groq from now on, no waiting
    chain = [pid] + [c for c in rt.cfg.brain.chain if c != pid]
    rt.update_config({"brain": {"providers": provs, "chain": chain}})
    r = await test(pid)
    out = {"ok": bool(r.get("ok")), "provider": pid, "label": LABEL.get(preset, preset), "ms": r.get("ms")}
    if r.get("ok"):
        out["message"] = f"Hotovo – mozek je {out['label']} a funguje ({r.get('ms', 0)} ms)."
    else:
        ok, msg = explain(str(r.get("message", "")))
        out.update(ok=ok, message=msg)
    return out
