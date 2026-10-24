"""3.3 everyday powers as tools: selected text, clipboard history, screen time, website watching, clean-up,
speed test, e-mail drafts."""
from __future__ import annotations

import asyncio
import urllib.parse
from typing import Annotated, Literal

from .base import ToolResult, tool


def _act(ctx):
    return getattr(ctx, "activity", None)


# ---------- selected text anywhere ----------
@tool("selected_text", "Přečte text, který má uživatel právě OZNAČENÝ v jakékoli aplikaci (Word, prohlížeč, e-mail…). "
      "Použij, když mluví o „označeném“, „vybraném“ textu nebo „tomhle textu“. Pro úpravu pak zavolej replace_selected_text.",
      category="schránka", perm="input")
async def selected_text(ctx) -> ToolResult:
    from .. import powers

    text, win = await asyncio.to_thread(powers.grab_selection, ctx)
    ctx.selection = {"text": text, "window": win}
    if not text.strip():
        return ToolResult(False, "Nic není označené. Ať si uživatel text nejdřív označí myší (nebo Ctrl+A) a řekne to znovu.")
    return ToolResult(True, f"Označený text ({len(text)} znaků) z {win.get('app') or 'aplikace'}", data=text[:12000])


@tool("replace_selected_text", "Nahradí označený text v aplikaci novým textem (opravený pravopis, překlad, přepis…). "
      "Volej až po selected_text.", category="schránka", perm="input")
async def replace_selected_text(ctx, text: Annotated[str, "nový text, který se vloží místo označeného"]) -> ToolResult:
    from .. import powers

    win = (getattr(ctx, "selection", None) or {}).get("window")
    ok = await asyncio.to_thread(powers.replace_selection, ctx, text, win)
    return ToolResult(ok, "Hotovo, text je nahrazený." if ok else "Okno s textem už není otevřené.")


# ---------- clipboard history ----------
@tool("clipboard_history", "Historie schránky: co uživatel nedávno kopíroval (posledních 30 textů, jen v paměti). "
      "Hesla se neukládají.", category="schránka", perm="files_read")
async def clipboard_history(ctx, query: Annotated[str, "hledat (prázdné = vše)"] = "", count: int = 10) -> ToolResult:
    act = _act(ctx)
    if act is None or not ctx.cfg.powers.clipboard_history:
        return ToolResult(False, "Historie schránky je vypnutá (Nastavení → Stark → Schopnosti).")
    items = [c for c in act.clips if query.lower() in c["text"].lower()][: max(1, min(30, count))]
    if not items:
        return ToolResult(True, "Nic takového jsem v historii schránky nenašel.", data=[])
    return ToolResult(True, "\n".join(f"{i + 1}. {c['text'][:160]}" for i, c in enumerate(items)),
                      data=[{"index": i + 1, "text": c["text"][:4000], "app": c["app"]} for i, c in enumerate(items)])


@tool("clipboard_restore", "Vrátí do schránky text z historie schránky (číslo z clipboard_history).", category="schránka", perm="files_read")
async def clipboard_restore(ctx, index: int = 1) -> ToolResult:
    act = _act(ctx)
    items = list(act.clips) if act else []
    if not 1 <= index <= len(items):
        return ToolResult(False, "Takovou položku v historii nemám.")
    await asyncio.to_thread(ctx.platform.clipboard_set, items[index - 1]["text"])
    return ToolResult(True, "Je zpátky ve schránce, stačí Ctrl+V.")


# ---------- screen time ----------
@tool("screen_time", "Čas u PC podle aplikací (dnes, včera nebo týden): kolik hraje, kolik pracuje, v čem tráví čas.",
      category="systém", perm="apps")
async def screen_time(ctx, period: Literal["today", "yesterday", "week"] = "today") -> ToolResult:
    import datetime as dt

    act = _act(ctx)
    if act is None or not ctx.cfg.powers.screen_time:
        return ToolResult(False, "Sledování času u PC je vypnuté (Nastavení → Stark → Schopnosti).")
    today = dt.date.today()
    if period == "yesterday":
        rows = act.screen_time(1, today - dt.timedelta(days=1))
    else:
        rows = act.screen_time(7 if period == "week" else 1, today)
    if not rows:
        return ToolResult(True, "Zatím nemám žádná data.", data=[])
    total = sum(r["minutes"] for r in rows)
    fmt = lambda m: f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"
    head = {"today": "Dnes", "yesterday": "Včera", "week": "Za týden"}[period]
    return ToolResult(True, f"{head} celkem {fmt(total)}. " + ", ".join(f"{r['app']} {fmt(r['minutes'])}" for r in rows[:6]) + ".",
                      data={"total_minutes": total, "apps": rows[:15]})


# ---------- website watching ----------
@tool("watch_website", "Hlídá webovou stránku a dá vědět (notch, hlas, telefon): buď až se na ní objeví zadaný text "
      "(„skladem“, „vyprodáno“ zmizí…), nebo při jakékoli změně. Kontroluje každých N minut.", category="web", perm="network")
async def watch_website(ctx, url: Annotated[str, "adresa stránky"], text: Annotated[str, "text, na který čekat (prázdné = jakákoli změna)"] = "",
                        minutes: Annotated[int, "jak často kontrolovat (min 5)"] = 30) -> ToolResult:
    from .. import powers

    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    if not ctx.scheduler:
        return ToolResult(False, "Plánovač neběží.")
    payload = {"url": url, "text": text.strip()}
    try:
        fire, msg, payload = await powers.check_watch(ctx, payload)   # baseline (and maybe already there)
    except Exception as e:
        return ToolResult(False, f"Stránku se nepodařilo načíst: {e}")
    if fire and payload.get("text"):
        return ToolResult(True, f"Už teď tam je: {msg}")
    title = f"Hlídám {urllib.parse.urlparse(url).netloc}" + (f": „{payload['text']}“" if payload.get("text") else " (změny)")
    job = ctx.scheduler.add({"type": "interval", "minutes": max(5, int(minutes))}, "watch", payload, title)
    return ToolResult(True, f"{title}, kontroluji každých {max(5, int(minutes))} min. Zrušíš to v Rutinách nebo hlasem.",
                      data={"id": job["id"]})


# ---------- disk ----------
@tool("storage_report", "Co zabírá místo na disku: velikost hlavních složek (Stažené, Plocha, Dokumenty, Videa…), "
      "největší soubory ve Stažených a volné místo.", category="soubory", perm="files_read")
async def storage_report(ctx) -> ToolResult:
    from .. import powers

    r = await asyncio.to_thread(powers.storage_report)
    f = powers.fmt_bytes
    lines = [f"Volné místo: {f(r['disk_free'])} z {f(r['disk_total'])}."]
    lines += [f"{x['name']}: {f(x['bytes'])}" for x in r["folders"][:6]]
    if r["big_downloads"]:
        lines.append("Největší ve Stažených: " + ", ".join(f"{x['path'].replace(chr(92), '/').rsplit('/', 1)[-1]} ({f(x['bytes'])})"
                                                           for x in r["big_downloads"][:4]))
    return ToolResult(True, "\n".join(lines), data=r)


def _clean_details(args: dict, ctx=None) -> list[str]:
    from .. import powers

    out = []
    if args.get("temp", True):
        size = sum(powers.folder_size(d, __import__("time").monotonic() + 3) for d in powers.temp_dirs())
        out.append(f"Dočasné soubory starší než den (teď mají dohromady {powers.fmt_bytes(size)})")
    if args.get("recycle_bin", True):
        out.append("Vysypat koš – soubory v něm budou nevratně smazané")
    return out


@tool("clean_pc", "Uklidí počítač: smaže dočasné soubory starší než den a vysype koš. Vždy se nejdřív zeptá.",
      danger=True, category="soubory", perm="files_write", details=_clean_details)
async def clean_pc(ctx, temp: bool = True, recycle_bin: bool = True) -> ToolResult:
    from .. import powers

    parts, freed = [], 0
    if temp:
        n, b = await asyncio.to_thread(powers.clean_temp, powers.temp_dirs())
        freed += b
        parts.append(f"{n} dočasných souborů")
    if recycle_bin:
        try:
            freed += await asyncio.to_thread(ctx.platform.empty_recycle_bin)
            parts.append("koš")
        except NotImplementedError:
            pass
    return ToolResult(True, f"Uklizeno: {', '.join(parts) or 'nic'}. Uvolněno {powers.fmt_bytes(freed)}.", data={"freed": freed})


# ---------- speed test ----------
@tool("speed_test", "Změří rychlost internetu: stahování, odesílání a odezvu (ping). Trvá asi 20 sekund.", category="web", perm="network")
async def speed_test(ctx) -> ToolResult:
    from .. import powers

    r = await powers.speed_test(ctx)
    if not r.get("down_mbps"):
        return ToolResult(False, "Test rychlosti se nepovedl – asi nejede internet.", data=r)
    up = f", odesílání {r['up_mbps']} Mb/s" if r.get("up_mbps") else ""
    ping = f", odezva {r['ping_ms']} ms" if r.get("ping_ms") else ""
    return ToolResult(True, f"Stahování {r['down_mbps']} Mb/s{up}{ping}.", data=r)


# ---------- e-mail drafts ----------
@tool("compose_email", "Připraví e-mail v poštovním programu uživatele (adresát, předmět, text). NEODEŠLE ho – "
      "uživatel ho jen zkontroluje a odešle sám.", category="aplikace", perm="apps")
async def compose_email(ctx, to: Annotated[str, "e-mailová adresa (může být prázdná)"] = "", subject: str = "",
                        body: Annotated[str, "celý text e-mailu"] = "") -> ToolResult:
    q = urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
    url = f"mailto:{urllib.parse.quote(to.strip(), safe='@,.+')}?{q}"
    await asyncio.to_thread(ctx.platform.open_url, url)
    return ToolResult(True, "E-mail je připravený v poště – zkontroluj ho a odešli.", data={"to": to, "subject": subject})
