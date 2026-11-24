"""3.14 Výběr mozku jedním klikem: Claude, Ollama, Groq, Gemini… – click one and it answers from now on; under it the
models it has, switchable right in JARVIS (Nastavení → Mozek, the brain chip in the chat, or by voice: "přepni na
Ollamu", "použij Claude Sonnet").

- a service you have not set up yet is added with its usual settings (Claude still needs its API key)
- Ollama lists the models you have downloaded on this PC; the others the models their service offers
- "Jen tento mozek": nothing else answers (no backup AIs) – without it the others stay as a backup when this one fails
"""
from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Any

from .llm.presets import PRESETS

# the Claude models to pick from (Anthropic's current ones; the first is the default). Prices: USD per million tokens
# in / out (Anthropic's price list, Nov 2026) – shown so the choice is not a surprise on the bill
CLAUDE_MODELS: list[dict] = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "note": "nejlepší pro většinu věcí – výchozí · $4 / $20"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "note": "rychlejší a levnější, pořád velmi chytrý · $2 / $10"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "note": "nejrychlejší a nejlevnější · $0,10 / $0,50"},
    {"id": "claude-fable-5-2", "label": "Claude Fable 5.2", "note": "nejschopnější, přemýšlí déle · $8 / $40"},
]
# the services shown as tiles (in this order); anything else stays in Pokročilé
TILES = ["anthropic", "ollama", "groq", "gemini", "openai", "openrouter", "omniroute", "lmstudio"]
SAY = {"anthropic": ("claude", "anthropic", "antropic", "klod"), "ollama": ("ollama", "olama", "ollamu", "olamu", "lokalni", "offline"),
       "groq": ("groq", "grok"), "gemini": ("gemini", "dzemini"), "openai": ("openai", "chatgpt", "gpt"),
       "openrouter": ("openrouter",), "omniroute": ("omniroute",), "lmstudio": ("lm studio", "lmstudio")}


def _norm(x: str) -> str:
    t = unicodedata.normalize("NFKD", (x or "").lower())
    return " ".join(re.sub(r"[^a-z0-9.:/ -]", " ", "".join(c for c in t if not unicodedata.combining(c))).split())


def find(rt: Any, key: str):
    """A provider by its id, else the first one of that service (preset)."""
    key = (key or "").strip().lower()
    provs = list(rt.cfg.brain.providers)
    return next((p for p in provs if p.id == key), None) or next((p for p in provs if p.preset == key), None)


def preset_from_words(text: str) -> str:
    t = _norm(text)
    for preset, words in SAY.items():
        if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words):
            return preset
    return ""


def claude_model_from_words(text: str) -> str:
    t = _norm(text)
    for m in CLAUDE_MODELS:
        fam = m["id"].split("-")[1]                   # opus / sonnet / haiku / fable
        if fam in t:
            return m["id"]
    return ""


def has_key(rt: Any, pid: str, preset: str) -> bool:
    if not PRESETS.get(preset, {}).get("needs_key"):
        return True
    from . import secrets

    try:
        return bool(secrets.get(pid))
    except Exception:  # noqa: BLE001
        return False


def current(rt: Any) -> dict:
    """The brain that answers first now."""
    provs = rt.router.providers() if getattr(rt, "router", None) else []
    p = provs[0] if provs else None
    if not p:
        return {"id": "", "preset": "", "label": "", "model": "", "only": bool(getattr(rt.cfg.brain, "only_primary", False))}
    return {"id": p.id, "preset": p.preset, "label": PRESETS.get(p.preset, {}).get("label", p.id), "model": p.model,
            "only": bool(getattr(rt.cfg.brain, "only_primary", False))}


def tiles(rt: Any) -> list[dict]:
    cur = current(rt)
    out = []
    for preset in TILES:
        p = find(rt, preset)
        meta = PRESETS[preset]
        out.append({"preset": preset, "id": p.id if p else preset, "label": meta["label"], "local": bool(meta.get("local")),
                    "added": p is not None, "enabled": bool(p and p.enabled), "model": (p.model if p else meta.get("model", "")),
                    "key": has_key(rt, p.id if p else preset, preset), "needs_key": bool(meta.get("needs_key")),
                    "active": bool(p and cur["id"] == p.id)})
    return out


def use(rt: Any, key: str, model: str = "", only: bool | None = None) -> dict:
    """Make this service (or provider id) the brain that answers; add it when it is not set up yet."""
    key = (key or "").strip().lower()
    p = find(rt, key)
    preset = p.preset if p else key
    if preset not in PRESETS:
        raise ValueError(f"Takový mozek neznám: {key}")
    provs = [x.model_dump() for x in rt.cfg.brain.providers]
    if p is None:
        pid, n = preset, 2
        while any(x["id"] == pid for x in provs):
            pid, n = f"{preset}{n}", n + 1
        meta = PRESETS[preset]
        provs.append({"id": pid, "preset": preset, "base_url": meta.get("base_url", ""), "model": meta.get("model", ""),
                      "vision_model": "", "fast_model": "", "enabled": True})
    else:
        pid = p.id
    chosen: dict = {}
    for x in provs:
        if x["id"] == pid:
            x["enabled"] = True
            if model:
                x["model"] = model.strip()[:120]
            chosen = x
    chain = [pid] + [i for i in rt.cfg.brain.chain if i != pid]
    chain += [x["id"] for x in provs if x["id"] not in chain]
    patch: dict = {"providers": provs, "chain": chain}
    local = bool(PRESETS[preset].get("local"))
    notes = []
    if local:
        patch["local_enabled"] = True
    elif rt.cfg.brain.offline_only:
        patch["offline_only"] = False             # you picked an AI from the internet: "Jen offline" would block it
        notes.append("Vypnul jsem režim „Jen offline“, jinak by tahle AI nesměla odpovídat.")
    if only is not None:
        patch["only_primary"] = bool(only)
    rt.update_config({"brain": patch})
    if not has_key(rt, pid, preset):
        notes.append(f"Chybí API klíč – vlož ho v Nastavení → Mozek u {PRESETS[preset]['label']}"
                     + (" (console.anthropic.com → API Keys)." if preset == "anthropic" else "."))
    return {"id": pid, "preset": preset, "label": PRESETS[preset]["label"], "model": chosen["model"],
            "key": has_key(rt, pid, preset), "notes": notes}


async def models(rt: Any, key: str) -> dict:
    """The models this brain can switch between."""
    p = find(rt, key)
    preset = p.preset if p else (key or "").strip().lower()
    if preset not in PRESETS:
        raise ValueError(f"Takový mozek neznám: {key}")
    current_model = p.model if p else PRESETS[preset].get("model", "")
    out: dict = {"id": p.id if p else preset, "preset": preset, "current": current_model, "models": [], "error": ""}
    if preset == "anthropic":
        out["models"] = [dict(m) for m in CLAUDE_MODELS]
        return out
    if preset == "ollama":
        from . import localai

        try:
            have = await asyncio.wait_for(localai.installed(rt), 6)
        except Exception as e:  # noqa: BLE001
            out["error"] = f"Ollama neběží nebo neodpovídá ({type(e).__name__}). Spusť Ollamu a zkus to znovu."
            return out
        out["models"] = [{"id": m["name"], "label": m["name"], "note": f"{m['size_gb']} GB" + (f" · {m['params_b']:g} mld. parametrů" if m.get("params_b") else "")}
                         for m in have if not m.get("embedding")]
        if not out["models"]:
            out["error"] = "V Ollamě zatím nemáš žádný model – stáhni si ho níž v kartě Lokální AI."
        return out
    if p is not None and has_key(rt, p.id, preset):
        from .llm.router import build_provider
        from . import secrets

        try:
            prov = build_provider(p, secrets.get(p.id) or "", rt.cfg.brain, getattr(rt.router, "transport", None))
            names = await asyncio.wait_for(prov.list_models(), 8) if hasattr(prov, "list_models") else []
        except Exception as e:  # noqa: BLE001
            names, out["error"] = [], f"Seznam modelů nejde načíst ({type(e).__name__})."
        out["models"] = [{"id": n, "label": n, "note": ""} for n in sorted(set(names))[:200]]
    if not out["models"] and current_model:
        out["models"] = [{"id": current_model, "label": current_model, "note": "nastavený"}]
    return out
