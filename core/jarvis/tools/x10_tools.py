"""3.20 Propojení+ (421–440), Spolehlivost+ (441–460) a Přístupnost+ (461–480) tools."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path
from typing import Literal

from .. import linkx
from ..connectors import guarded
from .base import ToolResult, tool

LINK_CHANGES = {"media_cmd"}


async def _ai(ctx, prompt: str) -> str:
    return await ctx.router.complete([{"role": "user", "content": prompt}], fast=True)


def _cfg(ctx):
    from ..config import LinkXCfg

    return getattr(ctx.cfg, "linkx", None) or LinkXCfg()


@tool("link_kit", "Propojení: škola z Bakalářů (school text=známky/úkoly/zprávy), trasa z Mapy.cz (route text=„z Brna do Jihlavy“, kind=auto/"
      "pěšky/kolo; place_add name+text, places), datová schránka – nové zprávy (databox), Strava (sport_sync) a soubory z Garminu "
      "(sport_import path .gpx/.csv), Plex / Jellyfin (media, media_cmd text=pauza/pokračuj/stop/další), Nextcloud (cloud_files text, "
      "cloud_events), Synology NAS (nas), výstrahy ČHMÚ (warnings text=kraj/okres), RSS (rss, rss_add url), YouTube kanály "
      "(youtube_add text=odkaz/ID, youtube), odečty elektřiny ze souboru distributora (meter path), Rohlík ze seznamu (rohlik), ČSFD "
      "(film text), co číst dál (books).", category="služby", perm="network", danger_if=lambda a: a.get("action") in LINK_CHANGES)
@guarded
async def link_kit(ctx, action: Literal["school", "route", "place_add", "places", "databox", "sport_sync", "sport_import", "media", "media_cmd",
                                        "cloud_files", "cloud_events", "nas", "warnings", "rss", "rss_add", "youtube_add", "youtube", "meter",
                                        "rohlik", "film", "books"],
                   text: str = "", name: str = "", path: str = "", kind: str = "") -> ToolResult:
    c = _cfg(ctx)
    today = dt.date.today()
    if action == "school":
        t = linkx.fold(text)
        if "edupage" in t:
            return ToolResult(False, linkx.EDUPAGE)
        if "ukol" in t or "homework" in t:
            items = linkx.parse_homework(await linkx.bakalari("homeworks", **{"from": today.isoformat()}), today)
            return ToolResult(True, "\n".join(f"• {h['subject']} do {h['due']}: {h['task'][:140]}" for h in items[:10]) or "Žádné úkoly.", data={"homework": items})
        if "zprav" in t or "komens" in t:
            msgs = linkx.parse_komens(await linkx.bakalari("komens/messages/received", method="POST"))
            unread = [m for m in msgs if not m["read"]] or msgs[:3]
            return ToolResult(True, "\n".join(f"• {m['date']} {m['from']}: {m['title']} – {m['text'][:160]}" for m in unread[:8]) or "Žádné zprávy.")
        marks = linkx.parse_marks(await linkx.bakalari("marks"), today - dt.timedelta(days=14))
        return ToolResult(True, "\n".join(f"• {m['date']} {m['subject']}: {m['mark']}" + (f" ({m['what']})" if m["what"] else "") for m in marks[:12])
                          or "Za 14 dní žádné nové známky.", data={"marks": marks})
    if action == "place_add":
        linkx.places_set(ctx, name, text)
        return ToolResult(True, f"Uloženo: „{name}“ = {text}.")
    if action == "places":
        saved = linkx.places_get(ctx)
        return ToolResult(True, "\n".join(f"• {k}: {v}" for k, v in saved.items()) or "Žádná oblíbená místa.")
    if action == "route":
        m = re.match(r"\s*(?:z|ze|od)\s+(.+?)\s+(?:do|na|k)\s+(.+)$", text, re.I)
        if not m:
            return ToolResult(False, "Řekni „z A do B“.")
        a = await linkx.mapy_geocode(linkx.resolve_place(ctx, m.group(1)))
        b = await linkx.mapy_geocode(linkx.resolve_place(ctx, m.group(2)))
        if not a or not b:
            return ToolResult(False, "Jedno z míst jsem na Mapy.cz nenašel.")
        r = await linkx.mapy_route(a, b, linkx.route_type(kind or text))
        h, mi = divmod(int(r["minutes"]), 60)
        return ToolResult(True, f"{a['name']} → {b['name']}: {r['km']:g} km, {f'{h} h ' if h else ''}{mi} min. {r['link']}", data=r)
    if action == "databox":
        msgs = await linkx.isds_received(30)
        new = linkx.seen_filter(ctx, "lx_isds", msgs) if msgs else []
        if not msgs:
            return ToolResult(True, "Za 30 dní nic nepřišlo.")
        return ToolResult(True, f"Za 30 dní {len(msgs)} zpráv" + (f", nových {len(new)}" if new else "") + ":\n"
                          + "\n".join(f"• {m['delivered'][:10]} {m['from']}: {m['subject']} ({m['status']})" for m in msgs[:10])
                          + "\nOtevři je v datové schránce – JARVIS je nečte.", data={"messages": msgs})
    if action == "sport_sync":
        from ..phonex import add_workout

        acts = await linkx.strava_activities(14)
        added = 0
        for a in linkx.seen_filter(ctx, "lx_strava", acts, keep=1000) if ctx.db.one("SELECT v FROM kv WHERE k='lx_strava'") else acts:
            try:
                start = dt.datetime.fromisoformat(str(a["start"]).replace("Z", "")).timestamp() if a["start"] else None
                add_workout(ctx, a["kind"] if a["kind"] in ("run", "walk", "bike", "gym", "swim") else "other", a["minutes"], a["km"],
                            int(a["hr"] or 0), note=f"Strava: {a['name']}"[:200], start=start)
                added += 1
            except ValueError:
                continue
        if not ctx.db.one("SELECT v FROM kv WHERE k='lx_strava'"):
            ctx.db.exec("INSERT OR REPLACE INTO kv VALUES ('lx_strava', ?)", (json.dumps([a["id"] for a in acts]),))
        return ToolResult(True, f"Ze Stravy {added} nových aktivit v přehledu tréninku ({len(acts)} za 14 dní).")
    if action == "sport_import":
        from ..phonex import add_workout
        from .files import resolve

        src = resolve(path)
        if not src.is_file():
            return ToolResult(False, "Pošli soubor .gpx nebo export aktivit z Garmin Connect (.csv).")
        txt = src.read_text(encoding="utf-8", errors="ignore")
        acts = [linkx.parse_gpx(txt) | {"kind": kind or "run", "name": src.stem}] if src.suffix.lower() == ".gpx" else linkx.parse_garmin_csv(txt)
        n = 0
        for a in acts:
            try:
                add_workout(ctx, a["kind"] if a["kind"] in ("run", "walk", "bike", "gym", "swim") else "other", a["minutes"] or 1, a["km"],
                            int(a.get("hr") or 0), note=f"Import: {a.get('name', '')}"[:200])
                n += 1
            except ValueError:
                continue
        return ToolResult(True, f"Importováno {n} aktivit.")
    if action in ("media", "media_cmd"):
        from ..connectors import configured

        sessions: list[dict] = []
        if configured("jellyfin"):
            sessions += [s | {"server": "jellyfin"} for s in linkx.parse_jellyfin_sessions(await linkx.jellyfin("/Sessions"))]
        if configured("plex"):
            sessions += [s | {"server": "plex"} for s in await linkx.plex_sessions()]
        if not sessions:
            return ToolResult(True, "Na Plexu ani Jellyfinu teď nic nehraje (nebo nejsou připojené).")
        if action == "media":
            return ToolResult(True, "\n".join(f"• {s['title']} – {s['device']} ({s['user']}, {s['state']})" for s in sessions), data={"sessions": sessions})
        cmd = next((v for k, v in linkx.JF_CMD.items() if k in linkx.fold(text)), "")
        jf = [s for s in sessions if s["server"] == "jellyfin"]
        if not cmd or not jf:
            return ToolResult(False, "Ovládat umím přehrávání na Jellyfinu: pauza, pokračuj, stop, další.")
        await linkx.jellyfin(f"/Sessions/{jf[0]['id']}/Playing/{cmd}", method="POST")
        return ToolResult(True, f"{jf[0]['device']}: {text}.")
    if action == "cloud_files":
        from ..connectors import value

        user = value("nextcloud", "username")
        xml = await linkx.nextcloud("SEARCH", "/", linkx.NC_SEARCH.format(user=user, q=text.replace("%", "")), depth="0")
        files = [f for f in linkx.parse_dav_files(xml, user) if f["path"]]
        return ToolResult(bool(files), "\n".join(f"• {f['path']}" for f in files[:15]) or f"„{text}“ v Nextcloudu není.", data={"files": files})
    if action == "cloud_events":
        from ..connectors import value

        now_utc = dt.datetime.now(dt.timezone.utc)
        xml = await linkx.nextcloud("REPORT", f"/calendars/{value('nextcloud', 'username')}/{c.nextcloud_calendar}/",
                                    linkx.NC_REPORT.format(a=now_utc.strftime("%Y%m%dT%H%M%SZ"),
                                                           b=(now_utc + dt.timedelta(days=7)).strftime("%Y%m%dT%H%M%SZ")))
        evs = linkx.parse_caldav_events(xml)
        return ToolResult(True, "\n".join(f"• {e['start'][:16].replace('T', ' ')} {e['title']}" for e in evs[:15]) or "Týden je volný.", data={"events": evs})
    if action == "nas":
        st = linkx.parse_syno_storage(await linkx.synology("SYNO.Storage.CGI.Storage", "load_info"))
        try:
            bk = linkx.parse_syno_backups(await linkx.synology("SYNO.Backup.Task", "list"), time.time())
        except Exception:  # noqa: BLE001 – Hyper Backup not installed
            bk = []
        lines = [f"Svazek {v['id']}: {v['status']}, plný na {v['used_pct']} % (volno {v['free_gb']} GB)" for v in st["volumes"]]
        lines += [f"Záloha {b['name']}: {b['result']}" + (f", před {b['days']:g} dny" if b["days"] is not None else "") for b in bk]
        problems = st["problems"] + [f"záloha {b['name']} je stará nebo selhala" for b in bk if b["bad"]]
        return ToolResult(True, ("⚠ " + "; ".join(problems) + "\n" if problems else "Vše v pořádku.\n") + "\n".join(lines), data={**st, "backups": bk})
    if action == "warnings":
        from ..connectors import http

        async with http() as cl:
            r = await cl.get(c.chmu_url or linkx.CHMU_CAP)
            r.raise_for_status()
        w = linkx.parse_cap(r.text, text or c.region)
        return ToolResult(True, "\n".join(f"• {x['event']} ({x['severity']} stupeň) {x['onset'][:16].replace('T', ' ')} – {x['expires'][:16].replace('T', ' ')}"
                                          for x in w[:8]) or f"Pro {text or c.region or 'Česko'} teď ČHMÚ nemá výstrahu.", data={"warnings": w})
    if action == "rss_add":
        feeds = list(dict.fromkeys([*c.rss, text.strip()]))
        ctx.update_config({"linkx": {"rss": feeds}})
        return ToolResult(True, f"Sleduju {len(feeds)} RSS zdrojů.")
    if action == "rss":
        from ..bizx import parse_feed
        from ..connectors import http

        news: list[dict] = []
        async with http() as cl:
            for url in c.rss[:20]:
                try:
                    r = await cl.get(url)
                    news += [i | {"src": url.split("/")[2]} for i in parse_feed(r.text)[:6]]
                except Exception:  # noqa: BLE001 – one dead feed does not stop the digest
                    continue
        if not news:
            return ToolResult(False, "Nemám RSS zdroje – přidej je („sleduj RSS https://…“).")
        listing = "\n".join(f"- {i['title']} ({i['src']}): {i['text'][:200]}" for i in news[:40])
        try:
            digest = await _ai(ctx, linkx.DIGEST_PROMPT.format(items=listing))
        except Exception:  # noqa: BLE001
            digest = "\n".join(f"• {i['title']} ({i['src']})" for i in news[:12])
        return ToolResult(True, digest.strip(), data={"items": news[:40]})
    if action == "youtube_add":
        ch = text.strip()
        if not linkx.youtube_feed_url(ch):
            from ..connectors import http

            url = ch if ch.startswith("http") else f"https://www.youtube.com/{ch if ch.startswith('@') else '@' + ch}"
            async with http() as cl:
                r = await cl.get(url, headers={"Accept-Language": "cs"})
            ch = linkx.channel_id_from_page(r.text)
            if not ch:
                return ToolResult(False, "Kanál jsem nenašel – pošli odkaz na něj.")
        chans = list(dict.fromkeys([*c.youtube, ch]))
        ctx.update_config({"linkx": {"youtube": chans}})
        return ToolResult(True, f"Sleduju {len(chans)} kanálů na YouTube – nová videa ti řeknu.")
    if action == "youtube":
        from ..connectors import http

        vids: list[dict] = []
        async with http() as cl:
            for ch in c.youtube[:30]:
                try:
                    r = await cl.get(linkx.youtube_feed_url(ch))
                    vids += linkx.parse_youtube_feed(r.text)[:5]
                except Exception:  # noqa: BLE001
                    continue
        week = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
        fresh = sorted([v for v in vids if v["published"] >= week], key=lambda v: v["published"], reverse=True)
        return ToolResult(True, "\n".join(f"• {v['channel']}: {v['title']} – {v['url']}" for v in fresh[:15]) or "Za týden nic nového.",
                          data={"videos": fresh})
    if action == "meter":
        from .files import resolve

        meter_file = resolve(path)
        if not meter_file.is_file():
            return ToolResult(False, "Stáhni z portálu distributora export spotřeby (CSV) a pošli mi cestu k souboru.")
        r = linkx.parse_meter_csv(meter_file.read_text(encoding="utf-8", errors="ignore"))
        return ToolResult(True, f"{r['from']} – {r['to']}: {r['total']:g} kWh, průměr {r['avg_day']:g} kWh/den, v noci {r['night_pct']} %. "
                                f"Špička {r['peak']['kwh']:g} kWh v {r['peak']['at'].replace('T', ' ')}.", data=r)
    if action == "rohlik":
        from .list_tools import items_of, list_name

        shopping = [i["item"] for i in items_of(ctx, list_name(text or "nákup"))]
        if not shopping:
            return ToolResult(False, "Nákupní seznam je prázdný.")
        for u in linkx.rohlik_links(shopping):
            ctx.platform.open_url(u)
        return ToolResult(True, f"Otevřel jsem Rohlík s hledáním {len(shopping[:15])} položek. Do košíku je dej sám – platbu vždy potvrzuješ ty "
                                "(Rohlík nemá veřejné rozhraní pro nákup).")
    if action == "film":
        ctx.platform.open_url(linkx.csfd_link(text))
        return ToolResult(True, f"Otevírám ČSFD pro „{text}“. Na seznam ke zhlédnutí ho dám, když řekneš „dej na seznam filmů {text}“.")
    from .. import learnx

    rows = [dict(r) for r in learnx.db(ctx).all("SELECT title, author, rating FROM ln_books WHERE status='přečteno' ORDER BY finished DESC LIMIT 25")]
    if not rows:
        return ToolResult(False, "Zatím nevím, co jsi četl – řekni „dočetl jsem …“ a ohodnoť to.")
    books = "; ".join(f"{r['title']} ({r['author']})" + (f" {r['rating']}/5" if r["rating"] else "") for r in rows)
    out = await _ai(ctx, linkx.BOOKS_PROMPT.format(books=books))
    return ToolResult(True, out.strip() + f"\nHodnocení najdeš na Databázi knih: {linkx.dbknih_link('')}")



@tool("sync_kit", "Synchronizace a poznámky: kalendář JARVISe ↔ Google Kalendář (calendar_sync), seznam ↔ Todoist / Microsoft To Do (list_sync "
      "name=seznam, kind=todoist/mstodo, text=projekt), Obsidian (notes text=hledat, note_add text [+name], tasks, task_add text, task_done "
      "text), Spotify (spotify text=pauza/pokračuj/další/předchozí, playlist text=název, like).", category="služby", perm="network",
      danger_if=lambda a: a.get("action") in ("calendar_sync", "list_sync"))
@guarded
async def sync_kit(ctx, action: Literal["calendar_sync", "list_sync", "notes", "note_add", "tasks", "task_add", "task_done", "spotify", "playlist",
                                        "like"],
                   text: str = "", name: str = "", kind: str = "") -> ToolResult:
    from .. import syncx

    c = _cfg(ctx)
    if action == "calendar_sync":
        from ..connectors import need

        need("google")
        st = await syncx.sync_calendar(ctx, *(await syncx.google_adapters()))
        ctx.update_config({"linkx": {"calendar_sync": True}})
        return ToolResult(True, f"Kalendář srovnán (a dál každých 15 minut): {st['pushed']} do Googlu, {st['pulled']} z Googlu, {st['paired']} spárováno, "
                                f"{st['deleted_remote'] + st['deleted_local']} smazáno, {st['updated_local']} posunuto.", data=st)
    if action == "list_sync":
        from ..connectors import need
        from .list_tools import list_name

        lst = list_name(name or "nákup")
        svc = "mstodo" if "micro" in linkx.fold(kind) or "todo" == linkx.fold(kind) or "mstodo" in linkx.fold(kind) else "todoist"
        need("microsoft" if svc == "mstodo" else "todoist")
        adapters = await (syncx.mstodo_adapters(text or lst) if svc == "mstodo" else syncx.todoist_adapters(text or lst))
        st = await syncx.sync_list(ctx, lst, svc, *adapters)
        ctx.update_config({"linkx": {"list_sync": {**c.list_sync, lst: f"{svc}:{text or lst}"}}})
        return ToolResult(True, f"„{lst}“ ↔ {'Microsoft To Do' if svc == 'mstodo' else 'Todoist'}: {st['pushed']} tam, {st['pulled']} sem, "
                                f"{st['paired']} spárováno. Dál se srovnává každých 15 minut.", data=st)
    if action in ("notes", "note_add", "tasks", "task_add", "task_done"):
        from pathlib import Path

        vault = Path(c.obsidian_vault).expanduser() if c.obsidian_vault else None
        if not vault or not vault.is_dir():
            return ToolResult(False, "Nastav složku trezoru Obsidianu (Nastavení → Propojení → Obsidian).")
        if action == "notes":
            hits = syncx.vault_search(vault, text)
            return ToolResult(bool(hits), "\n".join(f"• {h['note']}: {h['line']}" for h in hits) or "Nic takového v poznámkách.", data={"hits": hits})
        if action == "tasks":
            ts = syncx.vault_tasks(vault)
            return ToolResult(True, "\n".join(f"• {t['task']} ({t['note']})" for t in ts[:20]) or "Žádné otevřené úkoly.", data={"tasks": ts})
        if action == "task_done":
            r = syncx.vault_done(vault, text)
            return ToolResult(bool(r), f"Odškrtnuto: {r['task']} ({r['note']})." if r else "Takový otevřený úkol nemám.")
        try:
            p = syncx.vault_append(vault, text, name, task=action == "task_add")
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Zapsáno do {p.stem}.")
    from ..connectors import need

    need("spotify")
    if action == "playlist":
        lists = (await syncx.spotify("GET", "/me/playlists", limit=50)).get("items", [])
        best = syncx.best_playlist(lists, text)
        if not best:
            return ToolResult(False, f"Playlist „{text}“ mezi tvými nevidím.")
        await syncx.spotify("PUT", "/me/player/play", {"context_uri": best["uri"]})
        return ToolResult(True, f"Pouštím playlist {best['name']}.")
    if action == "like":
        from ..connectors import spotify as sp

        now = await sp.current()
        if not now:
            return ToolResult(False, "Teď nic nehraje.")
        cur = await syncx.spotify("GET", "/me/player/currently-playing")
        tid = ((cur or {}).get("item") or {}).get("id")
        await syncx.spotify("PUT", "/me/tracks", ids=tid)
        return ToolResult(True, f"{now['title']} je v Oblíbených.")
    cmd = next((v for k, v in syncx.SPOTIFY_CMD.items() if k in linkx.fold(text)), None)
    if not cmd:
        return ToolResult(False, "Umím pauzu, pokračuj, další a předchozí.")
    await syncx.spotify(*cmd)
    return ToolResult(True, "Hotovo.")


CARE_CHANGES = {"settings_restore", "safe_mode", "restore_drill"}


@tool("care_kit", "Spolehlivost JARVISe: skóre zdraví 0–100 s tím, co opravit (score), historie nastavení (settings_history, settings_restore "
      "text=den RRRR-MM-DD), přesný čas PC (clock), záloha fotek z telefonu (phone_backup), nouzový režim jen s jádrem (safe_mode text=on/"
      "off), rychlost odpovědí po týdnech (speed), UPS a výpadek proudu (ups), nácvik obnovy ze zálohy (restore_drill path+text=heslo), "
      "kontrola vlastních souborů (integrity), stres test (stress), kontrola nastavení (config_check), měsíční zpráva (report).",
      category="systém", danger_if=lambda a: a.get("action") in CARE_CHANGES)
async def care_kit(ctx, action: Literal["score", "settings_history", "settings_restore", "clock", "phone_backup", "safe_mode", "speed", "ups",
                                        "restore_drill", "integrity", "stress", "config_check", "report"],
                   text: str = "", path: str = "") -> ToolResult:
    import asyncio

    from .. import paths, reliax

    if action == "score":
        s = reliax.score(ctx)
        return ToolResult(True, f"Zdraví JARVISe: {s['score']}/100 ({s['word']}).\n" + "\n".join(
            f"• {p['what']} → {p['fix']}" for p in s["problems"][:8]) if s["problems"] else f"Zdraví JARVISe: {s['score']}/100 – vše v pořádku.", data=s)
    if action == "settings_history":
        h = reliax.history()
        return ToolResult(True, "Uložené dny: " + ", ".join(h[:20]) if h else "Historie nastavení se začne ukládat dnes v noci.", data={"days": h})
    if action == "settings_restore":
        try:
            day = reliax.restore_settings(ctx, text.strip() or dt.date.today().isoformat())
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Nastavení vráceno na {day}. Dnešní stav je v historii, kdyby to bylo potřeba vrátit.")
    if action == "clock":
        try:
            off = await asyncio.to_thread(reliax.sntp_offset)
        except (OSError, ValueError) as e:
            return ToolResult(False, f"Časový server nedostupný ({e}).")
        reliax.kv_set(ctx, "rx_clock", str(off))
        return ToolResult(True, reliax.clock_text(off), data={"offset": off})
    if action == "phone_backup":
        from ..photobackup import default_folder

        st = reliax.photo_backup_state(default_folder())
        return ToolResult(st["ok"], st["why"] or f"Záloha fotek z telefonu funguje ({st['files']} souborů, poslední před {st['days']:g} dny).", data=st)
    if action == "safe_mode":
        flag = paths.data_dir() / "SAFE_MODE"
        if linkx.fold(text) in ("off", "vypni", "konec", "ne", "vypnout"):
            flag.unlink(missing_ok=True)
            return ToolResult(True, "Nouzový režim vypnutý – po restartu JARVIS poběží celý.")
        flag.write_text("JARVIS poběží jen s jádrem, dokud tenhle soubor nesmažeš (nebo neřekneš „vypni nouzový režim“).\n", encoding="utf-8")
        return ToolResult(True, "Po restartu poběží jen jádro (bez dovedností, MCP a doplňkových smyček). Restartuj JARVISe.")
    if action == "speed":
        reliax.speed_record(ctx)
        weeks = reliax.speed_weeks(ctx)
        known = [w for w in weeks if w["ms"]]
        if not known:
            return ToolResult(True, "Měření rychlosti se teprve sbírá – za týden ukážu první čísla.")
        trend = known[-1]["ms"] - known[0]["ms"] if len(known) > 1 else 0
        return ToolResult(True, "Celá odpověď (medián) po týdnech: " + ", ".join(f"{w['week']} {w['ms']} ms" for w in known)
                          + (f". Trend {'+' if trend >= 0 else ''}{trend} ms." if len(known) > 1 else "."), data={"weeks": weeks})
    if action == "ups":
        try:
            import psutil

            b = psutil.sensors_battery()
        except Exception:  # noqa: BLE001
            b = None
        if b is None:
            return ToolResult(False, "Windows nevidí žádnou baterii ani UPS (UPS připoj přes USB kabel).")
        c = reliax.cfg(ctx)
        return ToolResult(True, f"{'Z UPS' if not b.power_plugged else 'Ze sítě'}, {b.percent:.0f} %." + (
            f" Vypnu při {c.ups_shutdown_pct} %." if c.ups and c.ups_shutdown_pct else " Hlídání UPS je vypnuté (Nastavení → Spolehlivost)." if not c.ups else ""))
    if action == "restore_drill":
        from .files import resolve

        b = resolve(path) if path else None
        if b is None or not b.is_file():
            backups = sorted(paths.data_dir().glob("**/*.jarvisvault"), key=lambda p: p.stat().st_mtime)
            b = backups[-1] if backups else None
        if b is None:
            return ToolResult(False, "Nemám zálohu (.jarvisvault) – vytvoř ji v Soukromí → Šifrovaná záloha.")
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            try:
                r = await asyncio.to_thread(reliax.restore_drill, b, text, Path(td))
            except Exception as e:  # noqa: BLE001
                return ToolResult(False, f"Obnova selhala: {reliax.human_reason(e)} (špatné heslo?).")
        reliax.event(ctx, "restore_drill", b.name, "ok" if r["ok"] else "fail")
        return ToolResult(r["ok"], f"Nácvik obnovy z {b.name}: {r['files']} souborů, databáze {r['db'] or 'chybí'}, nastavení {r['config'] or 'chybí'}."
                          + (" Záloha je použitelná." if r["ok"] else " Zálohu raději udělej znovu."), data=r)
    if action == "integrity":
        r = await asyncio.to_thread(reliax.integrity, ctx)
        if r.get("first"):
            return ToolResult(True, f"Zapamatoval jsem si otisky {r['files']} souborů této verze – příště je porovnám.")
        return ToolResult(r["ok"], "Soubory JARVISe jsou beze změny." if r["ok"] else
                          f"Změněno {len(r['changed'])}, chybí {len(r['missing'])}: " + ", ".join((r["changed"] + r["missing"])[:6]), data=r)
    if action == "stress":
        r = await reliax.stress(ctx, 300)
        st = r["stages"]
        return ToolResult(True, f"{r['n']} povelů za {r['seconds']} s ({r['per_s']}/s). P95: rychlé povely {st['instant']['p95']} ms, výběr nástrojů "
                                f"{st['pick']['p95']} ms, databáze {st['db']['p95']} ms. Úzké místo: {r['bottleneck']}.", data=r)
    if action == "config_check":
        issues = reliax.config_issues(ctx)
        return ToolResult(True, "\n".join(f"• {i['what']} → {i['fix']}" for i in issues) or "V nastavení jsem nenašel chybu.", data={"issues": issues})
    today = dt.date.today()
    last = today.replace(day=1) - dt.timedelta(days=1)
    r = reliax.month_report(ctx, today.year, today.month) if text.strip() in ("teď", "tento", "now") else reliax.month_report(ctx, last.year, last.month)
    return ToolResult(True, reliax.month_text(r), data=r)


@tool("access_kit", "Přístupnost: lupa (zoom text=přibliž/oddal/vypni), jednoduchá čeština z úředního dopisu (simplify text nebo path), "
      "přečíst etiketu / cenovku z fotky (label attachment), jazyk rozhraní a hlasu (language text=sk/de/pl/uk/en/cs), stránka pro "
      "překladatele (translate), vyzkoušet bliknutí světel (flash).", category="přístupnost")
async def access_kit(ctx, action: Literal["zoom", "simplify", "label", "language", "translate", "flash"], text: str = "", path: str = "",
                     attachment: str = "") -> ToolResult:
    from .. import accessx

    if action == "zoom":
        how = accessx.zoom_action(text)
        ctx.platform.hotkey(accessx.ZOOM_KEYS[how])
        return ToolResult(True, {"in": "Přibližuji (Lupa Windows). „Oddal“ zmenší, „vypni lupu“ ji zavře.", "out": "Oddaluji.",
                                 "off": "Lupa vypnutá."}[how])
    if action == "simplify":
        src = text
        if path:
            from .files import resolve

            p = resolve(path)
            if p.suffix.lower() == ".pdf":
                from ..moneyx import pdf_text

                src = pdf_text(p)
            elif p.is_file():
                src = p.read_text(encoding="utf-8", errors="ignore")
        if not src.strip():
            return ToolResult(False, "Pošli text nebo soubor s dopisem.")
        out = await _ai(ctx, accessx.PLAIN_PROMPT.format(text=src[:12000]))
        return ToolResult(True, out.strip())
    if action == "label":
        if not attachment:
            return ToolResult(False, "Vyfoť etiketu nebo cenovku telefonem a pošli mi fotku.")
        parts = await ctx.store.llm_parts(attachment, vision=True)
        out = await ctx.router.complete([{"role": "system", "content": accessx.LABEL_PROMPT},
                                         {"role": "user", "content": [{"type": "text", "text": "Přečti etiketu."}, *parts]}], need_vision=True)
        try:
            d = accessx.parse_label(out, ctx.cfg.accessx.allergies)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, accessx.label_text(d), data=d)
    if action == "language":
        lang = linkx.fold(text)[:2]
        lang = {"sl": "sk", "ne": "de", "po": "pl", "uk": "uk", "uj": "uk", "an": "en", "ce": "cs", "ge": "de", "en": "en", "cs": "cs",
                "sk": "sk", "de": "de", "pl": "pl"}.get(lang, lang)
        if lang not in accessx.UI_LANGS:
            return ToolResult(False, "Umím: " + ", ".join(f"{k} ({v})" for k, v in accessx.NAMES.items()))
        patch: dict = {"general": {"language": lang}}
        if lang in accessx.VOICES and lang != "cs":
            patch["voice"] = {"tts_voice": accessx.VOICES[lang]}
        ctx.update_config(patch)
        n = len(accessx.ui_pack(lang))
        return ToolResult(True, f"Jazyk: {accessx.NAMES[lang]}." + (f" Rozhraní má zatím {n} přeložených textů, zbytek zůstane česky – doplnit je "
                                                                     "jde na stránce /translate." if lang not in ("cs", "en") else ""))
    if action == "translate":
        try:
            ctx.platform.open_url(f"http://localhost:{ctx.cfg.phone.port}/translate")
        except Exception:  # noqa: BLE001
            pass
        return ToolResult(True, f"Stránka pro překladatele: http://localhost:{ctx.cfg.phone.port}/translate")
    lights = ctx.cfg.accessx.flash_lights
    if not lights:
        return ToolResult(False, "Nastav světla, která mají blikat (Nastavení → Přístupnost → Světlo místo zvuku).")
    n = await accessx.flash(ctx, lights)
    return ToolResult(True, f"Bliklo {n} světel.")
