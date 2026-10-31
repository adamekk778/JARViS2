"""Wave F1 by voice: watched webs and certificates (708/709), the line's loss history (719), programs over time (305),
disks over time (309), waiting Windows updates (013) and what Mochi reacted to lately (085)."""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Annotated

from .base import ToolResult, tool

MOOD_CS = {"idle": "klid", "listening": "poslouchá", "thinking": "přemýšlí", "working": "pracuje", "speaking": "mluví",
           "waiting": "čeká", "success": "hotovo", "error": "chyba", "joy": "radost", "sleeping": "spí", "focus": "soustředění",
           "limit": "limit", "offline": "bez internetu", "notify": "upozornění", "dancing": "tančí"}


def _hm(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%d.%m. %H:%M")


@tool("web_watch", "Hlídání webů: přidá / odebere web, který JARVIS každých 10 minut zkontroluje (jestli běží, jak rychle "
      "odpovídá a kdy vyprší certifikát HTTPS), nebo vypíše stav hlídaných. Ozve se jen při změně (spadl, zase jede, "
      "certifikát brzy vyprší). Na „hlídej mi web…“, „běží moje stránky?“, „přestaň hlídat…“.", category="síť", perm="network")
async def web_watch(ctx, action: Annotated[str, "add | remove | list | check"] = "list",
                    url: Annotated[str, "adresa webu (u add/remove/check)"] = "") -> ToolResult:
    nw = ctx.netwatch
    if action == "add":
        r = nw.add(url)
        if not r["ok"]:
            return ToolResult(False, r["error"])
        res = await nw.check(r["url"])
        nw.apply(res)
        state = f"teď běží ({res['ms']} ms)" if res["up"] else f"teď NEBĚŽÍ ({res.get('status') or 'neodpovídá'})"
        cert = f", certifikát platí ještě {res['days_left']} dní" if res.get("days_left") is not None else ""
        return ToolResult(True, f"{'Už hlídám' if r.get('already') else 'Hlídám'} {r['url']}: {state}{cert}. Ozvu se, jen když se něco změní.", data=res)
    if action == "remove":
        nw.remove(url)
        return ToolResult(True, f"{url} už nehlídám.")
    if action == "check":
        from ..netwatch import norm_url

        urls = [norm_url(url)] if url else [r["url"] for r in nw.list()]
        out = [await nw.check(u) for u in urls if u]
        if not out:
            return ToolResult(False, "Nehlídám žádný web – řekni třeba „hlídej mi web mojefirma.cz“.")
        return ToolResult(True, "; ".join(f"{r['url']}: " + (f"běží {r['ms']} ms" if r["up"] else "NEBĚŽÍ")
                                          + (f", certifikát {r['days_left']} dní" if r.get("days_left") is not None else "") for r in out) + ".",
                          data={"results": out})
    rows = nw.list()
    if not rows:
        return ToolResult(True, "Zatím nehlídám žádný web.", data={"watched": []})
    parts = []
    for r in rows:
        s = "běží" if r["up"] else "NEBĚŽÍ" if r["up"] is False else "zatím nezkontrolováno"
        if r["uptime_24h"] is not None:
            s += f", za 24 h dostupný {r['uptime_24h']} %"
        if r["days_left"] is not None:
            s += f", certifikát {r['days_left']} dní"
        parts.append(f"{r['url']}: {s}")
    return ToolResult(True, "; ".join(parts) + ".", data={"watched": rows})


@tool("line_history", "Historie internetové linky: odezva a ztráta paketů za posledních N hodin (JARVIS měří každých "
      "10 minut), výpadky a nejhorší chvíle. Na „padal mi včera internet?“, „jak často se ztrácí pakety“.", category="síť")
async def line_history(ctx, hours: Annotated[float, "kolik hodin zpět"] = 24) -> ToolResult:
    s = ctx.netwatch.loss_summary(hours)
    if not s["samples"]:
        return ToolResult(False, "Zatím nemám žádná měření linky – JARVIS je zapisuje každých 10 minut.")
    txt = (f"Za {hours:g} h ({s['samples']} měření): průměrná ztráta {s['loss_avg']} % (nejvíc {s['loss_max']} %), "
           f"odezva průměrně {s['ms_avg']} ms (nejhůř {s['ms_max']} ms)")
    if s["outages"]:
        txt += f", {s['outages']}× internet úplně neodpověděl"
    if s["loss_max"]:
        txt += f"; nejhorší to bylo {_hm(s['worst_ts'])}"
    return ToolResult(True, txt + ".", data={**s, "series": ctx.netwatch.loss_series(hours)})


@tool("process_profile", "Programy v čase: které programy nejvíc zatěžovaly procesor a paměť za posledních N hodin "
      "(z měření každých 5 minut), nebo průběh jednoho programu. Na „co mi celý den žere procesor?“, "
      "„jak moc jel Chrome odpoledne?“.", category="systém")
async def process_profile(ctx, hours: Annotated[float, "kolik hodin zpět"] = 24,
                          name: Annotated[str, "jen tenhle program (volitelné)"] = "") -> ToolResult:
    p = ctx.perf.proc_profile(hours, name)
    if name:
        ser = p["series"]
        if not ser:
            return ToolResult(False, f"{name} jsem za {hours:g} h mezi nejnáročnějšími programy neviděl.")
        avg = sum(r["cpu"] for r in ser) / len(ser)
        peak = max(ser, key=lambda r: r["cpu"])
        return ToolResult(True, f"{name}: v {len(ser)} měřeních průměrně {avg:.1f} % procesoru, nejvíc {peak['cpu']} % ({_hm(peak['ts'])}), "
                                f"paměť až {max(r['ram_mb'] for r in ser):.0f} MB.", data=p)
    if not p["top"]:
        return ToolResult(False, "Zatím nemám profil programů – JARVIS ho zapisuje každých 5 minut, zkus to později.")
    return ToolResult(True, f"Za {hours:g} h ({p['samples']} měření) nejvíc zatěžovaly: " + "; ".join(
        f"{r['name']} průměrně {r['cpu_avg']} % (špička {r['cpu_max']} %, paměť ~{r['ram_avg']} MB)" for r in p["top"][:5]) + ".", data=p)


@tool("disk_activity", "Disky v čase: čtení a zápis každého disku za posledních N hodin (měření každých 5 minut) a kdy "
      "byl disk nejvytíženější. Na „co mi v noci tak hrabe na disku?“.", category="systém")
async def disk_activity(ctx, hours: Annotated[float, "kolik hodin zpět"] = 24) -> ToolResult:
    d = ctx.perf.disk_series(hours)
    if not d:
        return ToolResult(False, "Zatím nemám historii disků – JARVIS ji zapisuje každých 5 minut.")
    parts = []
    for disk, rows in d.items():
        peak = max(rows, key=lambda r: r["read"] + r["write"])
        avg = sum(r["read"] + r["write"] for r in rows) / len(rows)
        parts.append(f"{disk}: průměrně {avg:.2f} MB/s, nejvíc {peak['read'] + peak['write']:.1f} MB/s ({_hm(peak['ts'])})")
    return ToolResult(True, "; ".join(parts) + ".", data={"disks": d})


@tool("windows_updates", "Čekající aktualizace Windows: co ještě není nainstalované (bezpečnostní nejdřív), velikost a "
      "jestli se čeká na restart. Jen zjišťuje – instaluje Windows Update. Na „mám nějaké aktualizace?“.",
      category="systém", perm="system")
async def windows_updates(ctx) -> ToolResult:
    from .. import winupd

    r = await asyncio.to_thread(winupd.pending)
    return ToolResult(not (r.get("error") and not r.get("updates")), winupd.summary(r), data=r)


@tool("mochi_history", "Co Mochi (postavička v notchi) v poslední době dělal: reakce (hlasitost, radost, upozornění…) "
      "a nálady, kterými prošel, s časem. Jen v paměti, po restartu se maže. Na „proč byl Mochi smutný?“, "
      "„co se dělo v notchi?“.", category="systém")
async def mochi_history(ctx, limit: Annotated[int, "kolik záznamů"] = 15) -> ToolResult:
    rows = ctx.mood.history(max(1, min(100, int(limit))))
    if not rows:
        return ToolResult(True, "Od spuštění se nic nestalo.", data={"history": []})
    def line(r):
        if r["kind"] == "mood":
            why = r["detail"].get("why")
            return f"{_hm(r['ts'])} nálada: {MOOD_CS.get(r['name'], r['name'])}" + (f" ({why})" if why else "")
        return f"{_hm(r['ts'])} reakce: {r['name']}"
    return ToolResult(True, "; ".join(line(r) for r in rows) + ".", data={"history": rows})
