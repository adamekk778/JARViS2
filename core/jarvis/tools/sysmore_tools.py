"""Diagnostics and media by voice: partitions (289), disks Windows does not see + USB bridges (698 / 693 / 694),
gaming (313), a decision simulator (005), every connection checked at once (586 / 587), subtitles from a video (128)
and a spoken summary as an audio file (268)."""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Annotated

from .base import ToolResult, tool
from .files import resolve


@tool("disk_partitions", "Oddíly disků: písmeno, název, souborový systém, velikost, volné místo, k čemu slouží (systém, EFI, "
      "obnova, data) a stav.", category="systém", perm="system")
async def disk_partitions(ctx) -> ToolResult:
    from .. import sysmore

    d = await asyncio.to_thread(sysmore.disk_probe)
    parts = sysmore.partitions_summary(d)
    if not parts:
        return ToolResult(False, "Oddíly jde přečíst jen ve Windows.")
    return ToolResult(True, "; ".join(f"disk {p['disk']} {p['letter'] + ':' if p['letter'] else ''}{' ' + p['label'] if p['label'] else ''} "
                                      f"{p['fs']} {p['gb']} GB ({p['role']}" + (f", volno {p['free_gb']} GB" if p['free_gb'] is not None else "") + ")"
                                      for p in parts), data=parts)


@tool("disk_triage", "Disk, který Windows nevidí nebo neukazuje: zařízení s chybou, disky offline / RAW / neinicializované a "
      "jaký převodník (JMicron, ASMedia, Realtek…) je v USB rámečku, s radou. Nic nemění.", category="systém", perm="system")
async def disk_triage(ctx) -> ToolResult:
    from .. import sysmore

    d = await asyncio.to_thread(sysmore.disk_probe)
    if not d:
        return ToolResult(False, "Disky jde zkontrolovat jen ve Windows.")
    f = sysmore.invisible_disks(d)
    if not f:
        return ToolResult(True, "Všechny disky, které Windows zná, jsou připojené a v pořádku.", data=[])
    return ToolResult(True, " ".join(f"{x['text']} {x['fix']}" for x in f[:6]), data=f)


@tool("gaming_stats", "Herní statistiky: kolik hodin denně hraješ, které hry nejvíc, nejdelší souvislé hraní a hraní v noci "
      "(22–6). Z měření času v aplikacích, nic se neposílá.", category="systém")
async def gaming_stats(ctx, days: int = 7) -> ToolResult:
    from .. import sysmore

    try:
        rows = ctx.db.all("SELECT day, hour, app, seconds FROM app_hours WHERE day>=?", ((dt.date.today() - dt.timedelta(days=days)).isoformat(),))
    except Exception:  # noqa: BLE001 – the table appears after the first measured hour
        rows = []
    r = sysmore.gaming_sessions(rows, max(1, days))
    if not r["total_h"]:
        return ToolResult(True, f"Za posledních {days} dní jsem žádné hraní nezaznamenal.", data=r)
    txt = f"Za {days} dní {r['total_h']} h (průměrně {r['avg_h']} h denně); nejvíc {', '.join(f'{t['app']} {t['hours']} h' for t in r['top'][:3])}"
    if r["longest_h"] >= 3:
        txt += f"; nejdelší kus v kuse {r['longest_h']} h – dej si pauzu aspoň po hodině"
    if r["late_h"]:
        txt += f"; v noci (22–6) {r['late_h']} h"
    return ToolResult(True, txt + ".", data=r)


@tool("simulate_decision", "Simulátor rozhodnutí: pro každou možnost zadej zisk a náklady (min, nejpravděpodobnější, max) a šanci "
      "na úspěch – 20 000 náhodných průběhů ukáže očekávaný výsledek, riziko ztráty a dobrý / špatný případ.", category="produktivita")
async def simulate_decision(ctx, options: Annotated[dict[str, dict], "název → {gain: [min, typ, max], cost: [min, typ, max], p_success: 0–1}"]) -> ToolResult:
    from .. import sysmore

    if not options:
        return ToolResult(False, "Zadej aspoň jednu možnost.")
    try:
        r = sysmore.simulate_decision(options)
    except (TypeError, ValueError, IndexError) as e:
        return ToolResult(False, f"Možnosti zadej jako gain/cost [min, typ, max] a p_success: {e}")
    lines = [f"{k}: očekávaně {v['expected']:+g}, riziko ztráty {v['p_loss']} %, špatný případ {v['bad_case']:+g}, dobrý {v['good_case']:+g}"
             for k, v in r["options"].items()]
    return ToolResult(True, "; ".join(lines) + f". Nejvyšší očekávaný výsledek: {r['best_expected']}, nejbezpečnější: {r['safest']}.", data=r)


@tool("connections_health", "Zkontroluje najednou všechna připojení: AI poskytovatele, místní modely, e-mail, Home Assistant, "
      "telefon, MCP servery – co funguje, co ne a proč.", category="systém")
async def connections_health(ctx, ai: Annotated[bool, "otestovat i odpověď AI (stojí pár tokenů)"] = False) -> ToolResult:
    out: list[dict] = []
    if ai:
        from .. import secrets
        from ..llm.router import Router

        for p in ctx.cfg.brain.providers:
            brain = ctx.cfg.brain.model_copy(deep=True)
            brain.chain, brain.providers = [p.id], [p]
            t0 = time.time()
            try:
                await asyncio.wait_for(Router(brain, secrets.get, ctx.router.transport).complete([{"role": "user", "content": "Odpověz jen: ok"}]), 30)
                out.append({"name": f"AI {p.id}", "ok": True, "note": f"{round((time.time() - t0) * 1000)} ms"})
            except Exception as e:  # noqa: BLE001
                out.append({"name": f"AI {p.id}", "ok": False, "note": str(e)[:120]})
    else:
        out.append({"name": "AI", "ok": bool(ctx.cfg.brain.providers), "note": f"{len(ctx.cfg.brain.providers)} poskytovatelů (test odpovědi: ai=true)"})
    try:
        async with ctx.http() as c:
            r = await c.get(f"{ctx.local.base}/api/tags", timeout=3)
        out.append({"name": "Místní modely (Ollama)", "ok": r.status_code == 200, "note": f"{len(r.json().get('models', []))} modelů"})
    except Exception:  # noqa: BLE001
        out.append({"name": "Místní modely (Ollama)", "ok": None, "note": "neběží (nepovinné)"})
    try:
        for a in ctx.mail.status():
            out.append({"name": f"E-mail {a['address']}", "ok": a["connected"] or not a["error"], "note": a["error"] or "připojeno"})
    except Exception:  # noqa: BLE001
        pass
    from .. import home

    if home.configured(ctx):
        try:
            n = len(await ctx.home.states(fresh=True))
            out.append({"name": "Home Assistant", "ok": True, "note": f"{n} zařízení"})
        except Exception as e:  # noqa: BLE001
            out.append({"name": "Home Assistant", "ok": False, "note": str(e)[:120]})
    phones = [c for c in ctx.clients.values() if c.get("client") == "mobile"]
    out.append({"name": "Telefon", "ok": bool(phones) or None, "note": "připojený" if phones else "teď nepřipojený"})
    if getattr(ctx, "mcp", None):
        for s in ctx.mcp.status():
            out.append({"name": f"MCP {s['name']}", "ok": s.get("ok"), "note": s.get("error") or f"{s.get('tools', 0)} nástrojů"})
    bad = [x for x in out if x["ok"] is False]
    head = "Všechno, co je nastavené, funguje." if not bad else "Nefunguje: " + "; ".join(f"{x['name']} ({x['note']})" for x in bad) + "."
    return ToolResult(True, head + " " + ", ".join(f"{x['name']} {'✓' if x['ok'] else '–' if x['ok'] is None else '✗'}" for x in out), data=out)


@tool("make_subtitles", "Titulky k videu nebo nahrávce: přepíše řeč (místně nebo přes nastavený přepis) a uloží .srt vedle "
      "souboru – řádky do 42 znaků, nejvýš 2 řádky, rozumná délka zobrazení.", category="média", perm="files_write")
async def make_subtitles(ctx, file: str) -> ToolResult:
    from .. import media

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    stt = getattr(ctx.voice, "transcriber", None) if getattr(ctx, "voice", None) else None
    if stt is None:
        return ToolResult(False, "Rozpoznávání řeči teď neběží (hlasový modul je vypnutý).")
    segs = await asyncio.to_thread(stt.segments, str(p))
    subs = shape_subtitles(segs)
    if not subs:
        return ToolResult(False, "V nahrávce jsem nenašel řeč.")
    out = p.with_suffix(".srt")
    out.write_text(media.to_srt(subs), encoding="utf-8")
    return ToolResult(True, f"{len(subs)} titulků uloženo do {out.name}.", data={"path": str(out), "count": len(subs)}, attachments=[str(out)])


def shape_subtitles(segs: list[tuple[float, float, str]], max_chars: int = 84, min_s: float = 1.0, max_s: float = 6.0) -> list[dict]:
    """Recognizer segments → readable subtitles: long ones split at word boundaries by time share, 2 lines of ≤ 42."""
    from .. import media

    out = []
    for a, b, text in segs:
        words = text.split()
        if not words:
            continue
        chunks, cur = [], []
        for w in words:
            if len(" ".join(cur + [w])) > max_chars and cur:
                chunks.append(cur)
                cur = [w]
            else:
                cur.append(w)
        chunks.append(cur)
        total = sum(len(" ".join(c)) for c in chunks) or 1
        t = a
        for c in chunks:
            dur = (b - a) * len(" ".join(c)) / total
            out.append({"start": round(t, 3), "end": round(t + max(min_s, min(max_s, dur)), 3), "text": media.wrap(" ".join(c))})
            t += dur
    for x, y in zip(out, out[1:]):
        if x["end"] > y["start"]:
            x["end"] = round(max(x["start"] + 0.3, y["start"] - 0.04), 3)
    return out


@tool("audio_summary", "Namluví text nebo shrnutí (zprávy, report, poznámky) do zvukového souboru WAV, který si pustíš "
      "kdykoli – v autě, při běhu.", category="média", perm="files_write")
async def audio_summary(ctx, text: str = "", file: str = "", title: str = "shrnuti") -> ToolResult:
    import re

    from ..fileuniverse import doc_text

    if file:
        text = await asyncio.to_thread(doc_text, resolve(file), 20000)
    text = (text or "").strip()
    if not text:
        return ToolResult(False, "Dej mi text nebo soubor.")
    if not getattr(ctx, "speaker", None):
        return ToolResult(False, "Hlas teď není k dispozici.")
    audio, mime = await ctx.speaker.synth(text[:6000])
    from .. import paths

    d = paths.sub("vystupy")
    d.mkdir(parents=True, exist_ok=True)
    ext = ".mp3" if "mpeg" in mime else ".ogg" if "ogg" in mime else ".wav"
    out = d / f"{re.sub(r'[^\w-]+', '_', title)[:40]}_{dt.datetime.now():%Y%m%d_%H%M}{ext}"
    out.write_bytes(audio)
    return ToolResult(True, f"Namluveno do {out.name} ({len(audio) / 2**20:.1f} MB).", data={"path": str(out)}, attachments=[str(out)])


