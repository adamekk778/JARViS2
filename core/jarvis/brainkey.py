"""3.12 Mozek jen z API klíče: paste a key, JARVIS recognises the service by the key itself, sets up everything else
(address, models) on its own, puts it first and tries it at once – no server, no localhost, no settings to fill in.
"""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from . import secrets
from .llm.presets import PRESETS

# the start of the key → the service (the order matters: sk-ant- / sk-or- before plain sk-)
RULES: list[tuple[str, str]] = [("gsk_", "groq"), ("AIza", "gemini"), ("AQ.", "gemini"), ("csk-", "cerebras"), ("nvapi-", "nvidia"), ("hf_", "huggingface"), ("github_pat_", "github"), ("ghp_", "github"), ("sk-ant-", "anthropic"), ("sk-or-", "openrouter"),
                                ("sk-", "openai")]
LABEL = {"cerebras": "Cerebras", "mistral": "Mistral", "nvidia": "NVIDIA", "github": "GitHub Models", "huggingface": "Hugging Face", "sambanova": "SambaNova", "cohere": "Cohere", "deepseek": "DeepSeek", "groq": "Groq", "gemini": "Google Gemini", "anthropic": "Anthropic Claude", "openrouter": "OpenRouter", "openai": "OpenAI"}
HELP = ("Nepoznám, od koho klíč je. Funguje klíč od Groq (gsk_…), Cerebras (csk-…), Google Gemini (AIza…), NVIDIA (nvapi-…), GitHub (github_pat_…), OpenAI (sk-…), "
        "Anthropic (sk-ant-…) nebo OpenRouter (sk-or-…). Zdarma ho dostaneš na console.groq.com nebo aistudio.google.com.")


BLOCKED = ("Klíč je v pořádku, ale Windows nebo antivir zakazuje JARVISu připojit se na internet (chyba 10013). "
           "Otevři Diagnostika → Zkontrolovat → Opravit síť pro JARVIS (a pokud máš antivir, povol v něm JARVIS).")


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
    if re.search(r"10013|zakázan|forbidden by its access permissions|access permissions", e):
        return False, BLOCKED
    if re.search(r"\b(503|529)\b|overloaded|high demand|unavailable|server is busy", e):
        return True, "Klíč funguje – služba má teď jen přetížený model (\u201ehigh demand\u201c). JARVIS zkusí jiný model nebo jinou AI, za chvíli to půjde."
    if re.search(r"\b429\b|rate.?limit|quota|too many|resource.?exhausted", e):
        return True, "Klíč funguje – služba teď jen hlásí limit. Za chvíli to půjde, JARVIS mezitím zkusí jiný mozek."
    if re.search(r"\b40[13]\b|unauthori|invalid.{0,20}(key|api)|incorrect api key|permission|api.?key not valid|"
                  r"valid api.?key|api_key_invalid|authentication|missing.{0,20}(api.?key|authorization)|odmítl|nesedí.{0,30}klíč", e):
        return False, "Služba klíč odmítla. Je zkopírovaný celý? Zkus ho na stránce služby zkopírovat znovu (nebo vytvořit nový)."
    if re.search(r"timed? ?out|timeout", e):
        return False, "Služba neodpověděla včas. Je PC připojené k internetu?"
    if re.search(r"connect|name or service|getaddrinfo|network|unreachable|ssl", e):
        return False, "Nejde se spojit se službou. Je PC připojené k internetu (a nic ho neblokuje – antivir, VPN)?"
    msg = re.sub(r"^(\w[\w-]*:\s*)+", "", err.strip())          # "groq: groq: …" → the message itself
    return False, f"Nepovedlo se: {msg[:160]}"


async def apply(rt: Any, key: str, test: Callable[[str], Awaitable[dict]], hint: str | None = None) -> dict:
    """Save the key for the right service, make that service the first brain and try it. `hint`: the service the
    wizard asked for (its step says "Klíč pro Google Gemini") – a key whose start JARVIS does not know (a new format
    of the service's keys) is then tried with that service instead of being refused."""
    key = clean(key)
    if len(key) < 20:
        return {"ok": False, "message": "Tohle nevypadá jako celý API klíč – zkopíruj ho celý."}
    preset = detect(key) or (hint if hint in LABEL else None)
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
        # a key pasted again = a fresh start: the models JARVIS knows work today (an old saved one may be switched off)
        found.update(base_url=pr["base_url"], enabled=True, model=pr.get("model", "") or found.get("model", ""),
                     fast_model=pr.get("fast_model", "") or found.get("fast_model", ""),
                     vision_model=pr.get("vision_model", "") or found.get("vision_model", ""))
    pid = found["id"]
    secrets.set(pid, key)
    if preset == "groq":
        if pid != "groq":
            secrets.set("groq", key)               # speech recognition (voice, subtitles) looks for it here
        from .voice.stt import Transcriber

        Transcriber._groq_seen = (0.0, False)      # the voice uses Groq from now on, no waiting
    rest = [c for c in rt.cfg.brain.chain if c != pid]
    local = {p["id"] for p in provs if PRESETS.get(p.get("preset", ""), {}).get("local")}
    chain = ([pid] + [c for c in rest if c != "omniroute" and c not in local]        # your keys first, then the gateway,
             + [c for c in rest if c == "omniroute"] + [c for c in rest if c in local])   # the AI on this PC always last
    # a key for an AI on the internet = you want that AI: "Jen offline" (which hides every cloud AI and also stops song
    # lyrics and covers) is switched off, and you are told so
    was_offline = bool(rt.cfg.brain.offline_only)
    rt.update_config({"brain": {"providers": provs, "chain": chain, "offline_only": False}})
    if was_offline:
        try:
            from . import nowplaying

            nowplaying.refresh(rt)                 # the song playing now gets its lyrics and cover straight away
        except Exception:  # noqa: BLE001
            pass
    r = await test(pid)
    out = {"ok": bool(r.get("ok")), "provider": pid, "label": LABEL.get(preset, preset), "ms": r.get("ms")}
    if r.get("ok"):
        out["message"] = f"Hotovo – mozek je {out['label']} a funguje ({r.get('ms', 0)} ms)." + (
            " Režim „Jen offline“ jsem vypnul (s ním by se AI z internetu ani texty písní nepoužily)." if was_offline else "")
    else:
        ok, msg = explain(str(r.get("message", "")))
        out.update(ok=ok, message=msg)
    return out


async def provider_test(rt: Any, pid: str) -> dict:
    """Ask one AI one short question (its own router: only that provider). A saved model that no longer exists there is
    replaced by the one that answered."""
    import asyncio
    import time

    from .llm.router import Router

    brain = rt.cfg.brain.model_copy(deep=True)
    brain.chain = [pid]
    brain.providers = [p for p in brain.providers if p.id == pid]
    if not brain.providers:
        return {"id": pid, "ok": False, "message": "Poskytovatel nenalezen"}
    r = Router(brain, secrets.get, rt.router.transport)
    t0 = time.time()
    try:
        text = await asyncio.wait_for(r.complete([{"role": "user", "content": "Odpověz jen slovem: funguju"}]), 60)
        out = {"id": pid, "ok": True, "message": text.strip()[:200] or "funguju", "ms": round((time.time() - t0) * 1000)}
        found = r.resolved_models.get(pid)
        if found:          # the saved model no longer exists there (e.g. Groq's Llama 3.3): keep the one that answered
            provs = [p.model_dump() for p in rt.cfg.brain.providers]
            for p in provs:
                if p["id"] == pid:
                    p["model"] = found
            rt.update_config({"brain": {"providers": provs}})
            out["model"] = found
            out["message"] = f"{out['message']} · model přepnut na {found}"
        return out
    except Exception as e:  # noqa: BLE001
        return {"id": pid, "ok": False, "message": str(e)[:300]}
