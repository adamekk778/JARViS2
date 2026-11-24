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
# USD per million tokens (in, out) by model family – for the spend shown in the notch and the daily limit
CLAUDE_PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-2": (8.0, 40.0), "claude-mythos-5-2": (8.0, 40.0), "claude-fable-5-1": (10.0, 50.0), "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0), "claude-opus-4": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0), "claude-sonnet-5": (2.0, 10.0), "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-5-5": (0.10, 0.50), "claude-haiku-4": (1.0, 5.0),
}


def claude_price(model: str) -> tuple[float, float]:
    m = (model or "").lower()
    best = max((k for k in CLAUDE_PRICES if m.startswith(k)), key=len, default="")
    return CLAUDE_PRICES.get(best, CLAUDE_PRICES["claude-opus-5-5"])


def claude_spend(rt: Any, day: str | None = None) -> dict:
    """Today's Claude spend in USD (an estimate: tokens counted from the text, thinking not included)."""
    ids = {p.id for p in rt.cfg.brain.providers if p.preset == "anthropic"}
    usage = getattr(rt, "usage", None)
    rows = [r for r in (usage.day(day) if usage is not None else []) if r["provider"] in ids]
    usd = 0.0
    for r in rows:
        pin, pout = claude_price(r["model"])
        usd += r["tok_in"] / 1e6 * pin + r["tok_out"] / 1e6 * pout
    limit = float(getattr(rt.cfg.limits, "claude_daily_usd", 0.0) or 0.0)
    return {"usd": round(usd, 3), "limit": limit, "calls": sum(int(r["calls"]) for r in rows),
            "over": bool(limit and usd >= limit), "estimate": True}


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
    b = rt.cfg.brain
    return {"id": p.id, "preset": p.preset, "label": PRESETS.get(p.preset, {}).get("label", p.id), "model": p.model,
            "only": bool(getattr(b, "only_primary", False)), "claude": claude_spend(rt),
            "split": {"on": bool(getattr(b, "split", False)), "easy": getattr(b, "split_easy", ""), "hard": getattr(b, "split_hard", "")}}


# 3.14 will a local model be quick here? (what fits in the graphics card is fast, the rest runs on the processor)
SPEED = {"GPU": "rychlý – celý v grafice", "GPU+CPU": "střední – část na procesoru", "CPU": "pomalý – jen procesor",
         "nevejde se": "nevejde se do paměti"}
MODE_CTX = {"eco": 4096, "balanced": 8192, "performance": 16384}


def _hardware() -> dict:
    from . import localai

    try:
        return localai.hardware()
    except Exception:  # noqa: BLE001 – unknown hardware: judge by an average PC
        return {"vram_gb": 0, "ram_gb": 16, "gpus": []}


def catalog(hw: dict, ctx: int, have: set[str]) -> list[dict]:
    """The models JARVIS knows that are not downloaded yet – with the speed they would have here, the best first."""
    from . import localai
    from .llm.local import MODELS, recommend

    rec = recommend({"gpus": hw.get("gpus") or [{"vram_gb": hw.get("vram_gb", 0)}], "ram_gb": hw.get("ram_gb", 8)})
    items = [{"name": m["name"], "size_gb": m["size_gb"], "params_b": localai.params_from_name(m["name"]) or 0, "label": m["label"],
              "vision": bool(m.get("vision")), "extra": m.get("note", "")} for m in MODELS if m["name"] not in have]
    fit = {m["name"]: m["where"] for m in localai.compatibility(items, hw.get("vram_gb", 0), hw.get("ram_gb", 8), ctx)}
    order = {"GPU": 0, "GPU+CPU": 1, "CPU": 2, "nevejde se": 3}
    out = [{"id": m["name"], "label": m["label"], "size_gb": m["size_gb"], "where": fit.get(m["name"], ""),
            "recommended": m["name"] in rec,
            "note": " · ".join(x for x in (f"{m['size_gb']} GB", SPEED.get(fit.get(m["name"], ""), ""),
                                           "vidí obrázky" if m["vision"] and "obráz" not in m["extra"] else "", m["extra"]) if x)} for m in items]
    return sorted(out, key=lambda x: (not x["recommended"], order.get(x["where"], 4), x["size_gb"]))


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


def ensure(rt: Any, key: str) -> str:
    """The provider id of this service – added (enabled, at the end of the chain) when it is not set up yet."""
    key = (key or "").strip().lower()
    p = find(rt, key)
    if p is not None:
        if not p.enabled:
            rt.update_config({"brain": {"providers": [{**x.model_dump(), "enabled": True} if x.id == p.id else x.model_dump()
                                                      for x in rt.cfg.brain.providers]}})
        return p.id
    if key not in PRESETS:
        raise ValueError(f"Takový mozek neznám: {key}")
    meta = PRESETS[key]
    provs = [x.model_dump() for x in rt.cfg.brain.providers]
    pid, n = key, 2
    while any(x["id"] == pid for x in provs):
        pid, n = f"{key}{n}", n + 1
    provs.append({"id": pid, "preset": key, "base_url": meta.get("base_url", ""), "model": meta.get("model", ""),
                  "vision_model": "", "fast_model": "", "enabled": True})
    rt.update_config({"brain": {"providers": provs, "chain": list(rt.cfg.brain.chain) + [pid]}})
    return pid


def split(rt: Any, on: bool, easy: str = "", hard: str = "") -> dict:
    """3.14 chytré rozdělení: easy questions to one brain (e.g. Ollama, free), hard tasks to another (e.g. Claude)."""
    patch: dict = {"split": bool(on)}
    notes = []
    for field, key in (("split_easy", easy), ("split_hard", hard)):
        if key:
            pid = ensure(rt, key)
            patch[field] = pid
            p = find(rt, pid)
            if p is not None and not has_key(rt, pid, p.preset):
                notes.append(f"{PRESETS[p.preset]['label']}: chybí API klíč (Nastavení → Mozek).")
            if p is not None and PRESETS.get(p.preset, {}).get("local"):
                patch["local_enabled"] = True
    if on and (patch.get("split_hard") or rt.cfg.brain.split_hard) and rt.cfg.brain.offline_only:
        hard_p = find(rt, patch.get("split_hard") or rt.cfg.brain.split_hard)
        if hard_p is not None and not PRESETS.get(hard_p.preset, {}).get("local"):
            patch["offline_only"] = False
            notes.append("Vypnul jsem režim „Jen offline“, jinak by těžké úkoly nesměly do internetu.")
    rt.update_config({"brain": patch})
    b = rt.cfg.brain
    return {"on": b.split, "easy": b.split_easy, "hard": b.split_hard, "notes": notes}


async def split_for(rt: Any, tier: str) -> str:
    """Which brain this request should try first ("" = the usual order)."""
    b = rt.cfg.brain
    if not getattr(b, "split", False):
        return ""
    pid = b.split_hard if tier == "strong" else b.split_easy
    p = find(rt, pid) if pid else None
    if p is None or not p.enabled:
        return ""
    if PRESETS.get(p.preset, {}).get("local"):
        ready = getattr(rt.router, "local_ready", None)
        try:
            if ready is not None and not await ready():
                return ""                           # Ollama is not running: the usual order rather than a wait
        except Exception:  # noqa: BLE001
            return ""
    elif not has_key(rt, p.id, p.preset):
        return ""
    return p.id


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
        hw = await asyncio.to_thread(_hardware)
        ctx = MODE_CTX.get(getattr(rt.cfg.brain, "local_mode", "balanced"), 8192)
        fit = {m["name"]: m["where"] for m in localai.compatibility(have, hw["vram_gb"], hw["ram_gb"], ctx)}
        out["models"] = [{"id": m["name"], "label": m["name"], "where": fit.get(m["name"], ""),
                          "note": " · ".join(x for x in (f"{m['size_gb']} GB", SPEED.get(fit.get(m["name"], ""), "")) if x)}
                         for m in have if not m.get("embedding")]
        out["catalog"] = catalog(hw, ctx, {m["name"] for m in have})
        if not out["models"]:
            out["error"] = "V Ollamě zatím nemáš žádný model – stáhni si ho tady pod tím."
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
