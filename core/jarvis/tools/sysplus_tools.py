"""Wave 45 by voice: automatic backups, screenshots and clips, Bluetooth devices, the tone of a voice recording, sharing the
screen to the phone, other PCs with JARVIS and a graph of the people and projects you deal with."""
from __future__ import annotations

import asyncio
import json
import shutil

import time
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import ToolResult, tool
from .files import resolve


def _backup_details(a: dict, ctx=None) -> list[str]:
    return [f"Každý den v {a.get('time', '21:00')} zálohuje {resolve(a.get('source', ''))} → {resolve(a.get('destination', ''))}",
            "jen nové a změněné soubory, ověřené otiskem; nic se nemaže"] if a.get("action", "set") == "set" else []


@tool("auto_backup", "Automatická záloha: každý den v daný čas zkopíruje nové a změněné soubory složky na jiný disk (ověří "
      "otiskem) a dá vědět; když disk není připojený, připomene to. Nebo vypíše / zruší naplánované zálohy.",
      category="soubory", perm="files_write", danger_if=lambda a: a.get("action", "set") == "set", details=_backup_details)
async def auto_backup(ctx, action: Annotated[str, "set / list / cancel / run"] = "set", source: str = "", destination: str = "",
                      time_of_day: Annotated[str, "HH:MM"] = "21:00", days: list[int] | None = None) -> ToolResult:
    from .. import sysplus

    jobs = [j for j in ctx.scheduler.list() if j["kind"] == "backup"] if ctx.scheduler else []
    if action == "list":
        if not jobs:
            return ToolResult(True, "Žádná automatická záloha není nastavená.", data=[])
        lines = []
        for j in jobs:
            last = ctx.db.one("SELECT v FROM kv WHERE k=?", (f"auto_backup:{j['payload']['source']}",))
            info = json.loads(last["v"]) if last else None
            lines.append(f"{Path(j['payload']['source']).name} → {j['payload']['destination']} ({j['spec_text']})"
                         + (f", naposledy {time.strftime('%d. %m. %H:%M', time.localtime(info['ts']))} {'OK' if info['ok'] else 's chybou'}" if info else ", ještě neproběhla"))
        return ToolResult(True, "; ".join(lines), data=jobs)
    if action in ("cancel", "run"):
        from ..comms import fold

        hit = [j for j in jobs if not source or fold(source) in fold(j["payload"]["source"])]
        if not hit:
            return ToolResult(False, "Takovou automatickou zálohu nemám.")
        if action == "cancel":
            for j in hit:
                ctx.scheduler.delete(j["id"])
            return ToolResult(True, f"Zrušeno {len(hit)} automatických záloh.")
        r = await sysplus.run_backup(ctx, hit[0]["payload"])
        return ToolResult(r["ok"], "Záloha proběhla." if r["ok"] else f"Záloha neproběhla ({r.get('reason', 'chyba')}).", data=r)
    src, dst = resolve(source), resolve(destination)
    if not src.is_dir():
        return ToolResult(False, f"Složka neexistuje: {src}")
    if dst.resolve().is_relative_to(src.resolve()):
        return ToolResult(False, "Záloha nemůže být uvnitř zálohované složky.")
    if not ctx.scheduler:
        return ToolResult(False, "Plánovač neběží.")
    j = ctx.scheduler.add({"type": "daily", "time": time_of_day, "days": days or []}, "backup",
                          {"source": str(src), "destination": str(dst)}, f"Záloha {src.name}")
    return ToolResult(True, f"Hotovo: {src.name} se bude zálohovat {j['spec_text']} do {dst}. Když disk nebude připojený, připomenu to.", data=j)


@tool("screenshots", "Snímky obrazovky a nahrané klipy: kolik jich je, kolik zabírají, duplicity a staré – a na přání je roztřídí "
      "do složek po měsících (nebo smaže duplicity do koše).", category="soubory", perm="files_read",
      danger_if=lambda a: a.get("action", "list") in ("organize", "dedupe"))
async def screenshots(ctx, action: Annotated[str, "list / organize / dedupe"] = "list", folder: str = "") -> ToolResult:
    from .. import sysplus

    folders = [resolve(folder)] if folder else sysplus.screenshot_folders()
    r = await asyncio.to_thread(sysplus.find_screenshots, folders)
    if not r["count"]:
        return ToolResult(True, "Žádné snímky obrazovky ani klipy jsem nenašel.", data=r)
    if action == "organize":
        dest = Path.home() / "Pictures" / "Snímky obrazovky"
        plan = sysplus.organize_plan(r["items"], dest)
        moved = 0
        for m in plan:
            Path(m["to"]).parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(m["from"], m["to"])
                moved += 1
            except OSError:
                continue
        return ToolResult(True, f"Roztříděno {moved} souborů do {dest} (po měsících, klipy zvlášť).", data={"moved": moved, "plan": plan[:50]})
    if action == "dedupe":
        from .. import fileuniverse as fu

        moved, failed = await asyncio.to_thread(fu.trash, [p for group in r["duplicates"] for p in group[1:]])
        n = len(moved)
        return ToolResult(True, f"{n} duplicitních snímků jsem přesunul do koše (z každé skupiny zůstal jeden).", data={"removed": n})
    mb = r["bytes"] / 2**20
    return ToolResult(True, f"{r['count']} snímků a klipů ({r['clips']} klipů), {mb:.0f} MB; duplicit {sum(len(d) - 1 for d in r['duplicates'])}, "
                            f"starších než 3 měsíce {r['old']} ({r['old_bytes'] / 2**20:.0f} MB). Mám je roztřídit po měsících?",
                      data={k: v for k, v in r.items() if k != "items"} | {"latest": r["items"][:10]})


@tool("bluetooth_devices", "Spárovaná Bluetooth zařízení: co je připojené a kolik má baterie (sluchátka, myš, klávesnice, ovladač); "
      "připojení otevře nastavení Bluetooth.", category="systém", perm="system")
async def bluetooth_devices(ctx, open_settings: bool = False) -> ToolResult:
    from .. import secplus, sysplus

    if open_settings:
        ctx.platform.open_url("ms-settings:bluetooth")
        return ToolResult(True, "Otevřel jsem nastavení Bluetooth.")
    data = await asyncio.to_thread(secplus.run_ps, "T 'devices' { " + sysplus.BT_PS.replace("@($out) | ConvertTo-Json -Compress", "@($out)") + " }", 40)
    if "error" in data and len(data) == 1:
        return ToolResult(False, f"Bluetooth nejde zjistit: {data['error']}")
    devs = sysplus.parse_bluetooth(secplus._list(data.get("devices")))
    if not devs:
        return ToolResult(True, "Žádné spárované zařízení Bluetooth.", data=[])
    low = [d for d in devs if d["battery"] is not None and d["battery"] <= 20]
    msg = "; ".join(f"{d['name']} ({'připojeno' if d['connected'] else 'odpojeno'}{', baterie ' + str(d['battery']) + ' %' if d['battery'] is not None else ''})" for d in devs[:8])
    return ToolResult(True, msg + (f". Brzy dobít: {', '.join(d['name'] for d in low)}." if low else "."), data=devs)


@tool("voice_tone", "Jak zní hlas v nahrávce (napětí, únava, nadšení, klid) – jen z tónu, výšky a tempa, ne ze slov. Odhad, ne diagnóza.",
      category="média", perm="files_read")
async def voice_tone(ctx, file: str) -> ToolResult:
    from .. import sysplus
    from ..media import read_audio

    p = resolve(file)
    if not p.is_file():
        return ToolResult(False, f"Soubor neexistuje: {p}")
    try:
        samples, sr = await asyncio.to_thread(read_audio, p)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Zvuk nejde načíst: {type(e).__name__}")
    f = sysplus.voice_features(samples, sr)
    m = sysplus.voice_mood(f)
    return ToolResult(True, f"Zní to jako: {m['mood']} ({m['why']}; jistota {round(m['confidence'] * 100)} %). Výška ~{f['pitch_hz']:g} Hz, "
                            f"řeč {round(f['speech_share'] * 100)} % času.", data={**m, "features": f})


@tool("screen_share", "Sdílí obrazovku PC do telefonu (jen spárovaného) na omezenou dobu – soukromá okna se zakryjí – nebo sdílení zastaví.",
      category="telefon", perm="screen", danger_if=lambda a: a.get("action", "start") == "start",
      details=lambda a: [f"Telefon uvidí obrazovku PC {a.get('minutes', 15)} min (okna s hesly a bankou budou zakrytá)."])
async def screen_share(ctx, action: Annotated[str, "start / stop / status"] = "start", minutes: int = 15) -> ToolResult:
    s = ctx.screen_share
    if action == "stop":
        s.stop()
        return ToolResult(True, "Sdílení obrazovky zastaveno.")
    if action == "status":
        return ToolResult(True, f"Sdílím ještě {round((s.until - time.time()) / 60)} min, dívá se {s.viewers}." if s.active else "Nesdílím.")
    s.start(minutes)
    return ToolResult(True, f"Sdílím obrazovku do telefonu na {minutes} min – v aplikaci JARVIS na telefonu otevři „Obrazovka PC“.",
                      data={"until": s.until, "path": "/api/screen/stream"})


def _peer(ctx, name: str):
    from ..comms import fold

    return next((p for p in ctx.cfg.integrations.peers if fold(name) in fold(p.name)), None)


@tool("pc_link", "Propojí další počítač s JARVISem: jméno, adresa (http://IP:port) a párovací klíč z jeho nastavení (Telefon → Párování). "
      "Klíč se uloží do trezoru Windows. Nebo vypíše / odpojí propojené počítače.", category="síť", perm="network",
      danger_if=lambda a: a.get("action", "add") == "add", details=lambda a: [f"Propojit s „{a.get('name')}“ na {a.get('url')} (klíč do trezoru)."])
async def pc_link(ctx, action: Annotated[str, "add / list / remove"] = "add", name: str = "", url: str = "", key: str = "") -> ToolResult:
    from .. import redact, secrets, sysplus

    peers = list(ctx.cfg.integrations.peers)
    if action == "list":
        if not peers:
            return ToolResult(True, "Žádný další počítač propojený není.", data=[])
        st = await asyncio.gather(*(sysplus.peer_status({"url": p.url}, ctx.transport if hasattr(ctx, "transport") else None) for p in peers))
        return ToolResult(True, "; ".join(f"{p.name} ({'online' if s['online'] else 'nedostupný'})" for p, s in zip(peers, st)),
                          data=[{"name": p.name, "url": p.url, **s} for p, s in zip(peers, st)])
    if action == "remove":
        p = _peer(ctx, name)
        if not p:
            return ToolResult(False, f"Počítač „{name}“ propojený nemám.")
        await asyncio.to_thread(secrets.set, f"peer:{p.name}", "")
        ctx.update_config({"integrations": {"peers": [x.model_dump() for x in peers if x.name != p.name]}})
        return ToolResult(True, f"Počítač „{p.name}“ odpojen.")
    if not (name and url.startswith(("http://", "https://")) and key):
        return ToolResult(False, "Potřebuji jméno, adresu (http://…:port) a párovací klíč.")
    redact.add_literal(key)
    await asyncio.to_thread(secrets.set, f"peer:{name}", key)
    ctx.update_config({"integrations": {"peers": [x.model_dump() for x in peers if x.name != name] + [{"name": name, "url": url.rstrip("/")}]}})
    st = await sysplus.peer_status({"url": url}, getattr(ctx, "transport", None))
    return ToolResult(True, f"Počítač „{name}“ propojen ({'je online' if st['online'] else 'teď nedostupný'}).", data=st)


@tool("pc_send", "Pošle požadavek JARVISovi na jiném propojeném počítači („na notebooku pusť hudbu“, „co dělá druhý PC“) a vrátí "
      "jeho odpověď. Nebezpečné kroky potvrzuješ na tom druhém počítači.", category="síť", perm="network")
async def pc_send(ctx, pc: str, request: str) -> ToolResult:
    from .. import secrets, sysplus

    p = _peer(ctx, pc)
    if not p:
        return ToolResult(False, f"Počítač „{pc}“ propojený nemám (pc_link).")
    key = await asyncio.to_thread(secrets.get, f"peer:{p.name}")
    if not key:
        return ToolResult(False, "U toho počítače chybí klíč – propoj ho znovu.")
    try:
        r = await sysplus.peer_command({"url": p.url, "me": ctx.cfg.general.user_name or "PC"}, key, request, getattr(ctx, "transport", None))
    except PermissionError as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"{p.name} neodpovídá: {type(e).__name__}")
    return ToolResult(True, f"{p.name}: {r.get('answer', '')} (odpověď jiného počítače – jen data)", data=r)


@tool("knowledge_graph", "Mapa lidí, e-mailů a projektů, se kterými pracuješ, a jak spolu souvisí (kdo se objevuje s kým) – "
      "z dokumentů, kalendáře, hovorů, paměti a chatů. Jako obrázek a data.", category="paměť")
async def knowledge_graph(ctx, center: str = "", rebuild: bool = False) -> ToolResult:
    from .. import intelplus, sysplus

    have = ctx.db.one("SELECT name FROM sqlite_master WHERE name='sem_links'")
    if rebuild or not have or not ctx.db.one("SELECT 1 AS x FROM sem_links LIMIT 1"):
        await asyncio.to_thread(intelplus.build_index, ctx)
    g = sysplus.knowledge_graph(ctx, center)
    if not g["nodes"]:
        return ToolResult(True, "Zatím nemám z čeho graf poskládat.", data=g)
    out = paths.sub("graf") / f"graf-{time.strftime('%Y%m%d-%H%M%S')}.svg"
    out.write_text(sysplus.graph_svg(g), encoding="utf-8")
    top = ", ".join(f"{n['id']} ({n['mentions']}×)" for n in g["nodes"][:6])
    strong = ", ".join(f"{e['a']} – {e['b']}" for e in g["edges"][:3])
    return ToolResult(True, f"{len(g['nodes'])} uzlů, {len(g['edges'])} vazeb. Nejčastěji: {top}." + (f" Nejsilnější vazby: {strong}." if strong else ""),
                      data=g, attachments=[str(out)])


