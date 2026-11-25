"""3.20 Mozek+ tools (nápady 21–40): styl odpovědí, slovník zkratek, tvůj styl psaní, vlastní malý model, úkol na noc,
odhad doby, co se JARVIS naučil, proč to udělal."""
from __future__ import annotations

import asyncio
import shutil
from typing import Literal

from .. import brainx
from .base import ToolResult, tool

STYLE_NAMES = {"auto": "automaticky", "brief": "stručně", "normal": "normálně", "detailed": "podrobně", "teacher": "jako učitel"}


@tool("brain_kit", "Jak JARVIS přemýšlí a odpovídá: styl odpovědí (action=style, value = brief / normal / detailed / teacher / "
      "auto), slovník tvých zkratek (glossary_add term+meaning, glossary_list, glossary_remove term), naučit se tvůj styl "
      "psaní z odeslané pošty nebo vložených textů (writing_learn, text), úkol na noc nejlevnějším mozkem (night, text), "
      "odhad, jak dlouho úkol potrvá (estimate, text), co se za týden naučil (learned), proč udělal poslední kroky (why), "
      "vlastní malý model z tvých ověřených povelů (train_reflex, value = základní model Ollama).", category="mozek")
async def brain_kit(ctx, action: Literal["style", "glossary_add", "glossary_list", "glossary_remove", "writing_learn",
                                         "writing_show", "night", "estimate", "learned", "why", "train_reflex"],
                    value: str = "", text: str = "", term: str = "", meaning: str = "") -> ToolResult:
    if action == "style":
        v = value if value in STYLE_NAMES else brainx.style_from_words(f"odpovidej {value or text}") or ""
        if not v:
            return ToolResult(False, "Styl může být: stručně, normálně, podrobně, jako učitel nebo automaticky.")
        ctx.update_config({"general": {"answer_style": v}})
        return ToolResult(True, f"Odpovídám {STYLE_NAMES[v]}.")
    if action == "glossary_add":
        try:
            g = brainx.glossary_add(ctx, term or value, meaning or text)
        except ValueError as e:
            return ToolResult(False, str(e))
        added = brainx._kv_get(ctx, "glossary_added", {}) or {}
        import time

        added[term or value] = time.time()
        brainx._kv_set(ctx, "glossary_added", added)
        return ToolResult(True, f"Zapamatováno: {term or value} = {meaning or text}. Zkratek mám {len(g)}.")
    if action == "glossary_remove":
        ok = brainx.glossary_remove(ctx, term or value)
        return ToolResult(ok, "Smazáno." if ok else "Takovou zkratku neznám.")
    if action == "glossary_list":
        g = brainx.glossary(ctx)
        return ToolResult(True, "\n".join(f"{k} = {v}" for k, v in g.items()) or "Zatím neznám žádné tvoje zkratky.", data=g)
    if action in ("writing_learn", "writing_show"):
        if action == "writing_show":
            p = brainx._kv_get(ctx, "writing_style", {}) or {}
            return ToolResult(True, brainx.style_prompt(p) or "Tvůj styl psaní zatím neznám – řekni „nauč se, jak píšu“.", data=p)
        texts = [t for t in (text or "").split("\n---\n") if t.strip()]
        if not texts:
            try:
                acc = ctx.mail.account()
                from .. import comms

                _inbox, sent = await asyncio.to_thread(comms.mailbox_pair, acc, 80)
                texts = [str(m.get("preview") or m.get("text") or "") for m in sent]
            except Exception as e:  # noqa: BLE001
                return ToolResult(False, f"Nemám z čeho se učit – připoj e-mail nebo mi vlož pár svých zpráv ({e}).")
        p = brainx.style_profile(texts)
        if not p:
            return ToolResult(False, "Na naučení stylu potřebuju aspoň pár delších zpráv.")
        brainx._kv_set(ctx, "writing_style", p)
        return ToolResult(True, f"Naučeno z {p['samples']} zpráv. " + brainx.style_prompt(p), data=p)
    if action == "night":
        if not text.strip():
            return ToolResult(False, "Co mám v noci udělat?")
        job = brainx.queue_night(ctx, text)
        return ToolResult(True, f"Udělám to v noci ({job.get('spec_text', '')}) nejlevnějším mozkem a ráno to najdeš v oznámeních.",
                          data=job)
    if action == "estimate":
        e = brainx.estimate(ctx, text or value)
        return ToolResult(True, f"Potrvá to {e['text']}.", data=e)
    if action == "learned":
        d = brainx.learned_week(ctx)
        return ToolResult(True, brainx.learned_text(d), data=d)
    if action == "why":
        return ToolResult(True, brainx.why_text(ctx))
    base = value or "qwen3:1.7b"
    try:
        path, n = brainx.write_modelfile(ctx, base)
    except ValueError as e:
        return ToolResult(False, str(e))
    exe = shutil.which("ollama")
    if not exe:
        return ToolResult(True, f"Připravil jsem model s {n} tvými povely ({path}). Ollama tu není – po instalaci spusť "
                                f"„ollama create jarvis-reflex -f {path}“.", data={"modelfile": str(path)})
    proc = await asyncio.create_subprocess_exec(exe, "create", "jarvis-reflex", "-f", str(path),
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(proc.communicate(), 600)
    if proc.returncode != 0:
        return ToolResult(False, f"Ollama model nevytvořila: {out.decode(errors='ignore')[-300:]}")
    ctx.update_config({"brain": {"reflex_model": "jarvis-reflex"}})
    return ToolResult(True, f"Hotovo – místní model „jarvis-reflex“ zná {n} tvých povelů a rozhoduje je hned, bez internetu.",
                      data={"modelfile": str(path), "examples": n})
