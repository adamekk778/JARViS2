"""3.20 Domácnost+ (161–180) and Bezpečnost+ (181–200) tools."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from .. import homex, secx
from .base import ToolResult, tool

HOME_CHANGES = {"profile", "door_say", "matter_on", "matter_off", "matter_add"}
SEC_CHANGES = {"keys_restore", "wipe", "vault_open"}


async def _states(ctx) -> list[dict]:
    from ..homeplus import raw_states

    return homex.norm(await raw_states(ctx))


@tool("home_kit", "Dům (Home Assistant): teploty po místnostech a kde se zbytečně topí (temps), mapa domu (map), „je zamčeno?“ "
      "s fotkou (locks), odpověď u zvonku hlasem (door_say text), můj profil světel a teplot (profile person), baterie v čidlech "
      "s předpovědí (batteries), Matter bez cloudu (matter_nodes, matter_on/matter_off node, matter_add text=kód), přehled "
      "hlídání (status).", category="domácnost", perm="home", danger_if=lambda a: a.get("action") in HOME_CHANGES)
async def home_kit(ctx, action: Literal["temps", "map", "locks", "door_say", "profile", "batteries", "matter_nodes", "matter_on",
                                        "matter_off", "matter_add", "status"],
                   text: str = "", person: str = "", node: int = 0) -> ToolResult:
    from .. import home

    if action.startswith("matter"):
        m = homex.matter(ctx)
        try:
            if action == "matter_nodes":
                nodes = await m.nodes()
                return ToolResult(True, "\n".join(f"#{n['node']} {n['name']}" + ("" if n["available"] else " (nedostupné)")
                                                  + (f" – {'zapnuto' if n['on'] else 'vypnuto'}" if n["on"] is not None else "")
                                                  for n in nodes) or "Žádná zařízení Matter.", data=nodes)
            if action in ("matter_on", "matter_off"):
                await m.onoff(node, action == "matter_on")
                return ToolResult(True, f"Matter #{node}: {'zapnuto' if action == 'matter_on' else 'vypnuto'}.")
            await m.commission(text)
            return ToolResult(True, "Zařízení Matter je přidané.")
        except ValueError as e:
            return ToolResult(False, str(e))
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, f"Matter server ({m.url}) neodpovídá: {e}. Běží python-matter-server (doplněk Home Assistantu)?")
    if not home.configured(ctx):
        return ToolResult(False, "Na dům potřebuju Home Assistant (Nastavení → Domov).")
    if action == "door_say":
        if not text:
            return ToolResult(False, "Co mám u dveří říct?")
        r = await homex.door_say(ctx, text)
        return ToolResult(bool(r.get("ok")), r.get("message", ""))
    if action == "profile":
        calls = homex.profile_actions(ctx, person or text)
        if not calls:
            return ToolResult(False, f"Profil „{person or text}“ nemám – nastavíš ho v Nastavení → Domov → Rodinné profily.")
        for dom, svc, data in calls:
            await ctx.home.service(dom, svc, data)
        return ToolResult(True, f"Nastaveno podle profilu {person or text} ({len(calls)} změn).")
    st = await _states(ctx)
    if action == "temps":
        hs = getattr(ctx, "house", None)
        r = homex.room_temps(st, away=getattr(hs, "home", None) is False)
        lines = [f"{x['name']}: {x['current'] if x['current'] is not None else '?'} °C" + (f" (cíl {x['target']:.0f})" if x["target"] else "")
                 for x in r["rooms"]]
        return ToolResult(True, "\n".join(lines + (["Tipy:"] + r["tips"] if r["tips"] else ["Nikde se zbytečně netopí."])), data=r)
    if action == "map":
        return ToolResult(True, f"Mapa domu: http://localhost:{ctx.cfg.phone.port}/house-map (obnovuje se sama).",
                          data=homex.house_map(st, None, ctx.cfg.homex.map_positions))
    if action == "locks":
        r = homex.locks(st)
        img = await homex.lock_photo(ctx)
        atts = []
        if img:
            att = await ctx.store.save("zamek.jpg", img, "image/jpeg")
            atts = [att.id]
        return ToolResult(r["ok"] is not False, r["text"], data=r, attachments=atts)
    if action == "batteries":
        from ..homeplus import low_batteries, raw_states

        items = low_batteries(await raw_states(ctx))
        import datetime as dt

        today = dt.date.today()
        homex.batt_record(ctx, items, today)
        lines = []
        for b in items[:15]:
            days = homex.batt_forecast(ctx, b["id"], today)
            lines.append(f"{b['name']}: {int(b['level'])} %" + (f", asi {days} dní" if days is not None else ""))
        return ToolResult(True, "\n".join(lines) or "Žádná čidla s baterií.", data=items)
    s = homex.state(ctx)
    return ToolResult(True, f"Hlídám {len(st)} entit. Okna s vypnutým topením: {len(s.saved_hvac)}, noční světla: {len(s.night_on)}, "
                            f"simulace přítomnosti: {len(s.sim_on)} světel.")


@tool("security_kit", "Bezpečnost: co JARVIS smí a co nepoužívá (audit), návnadové soubory (canary folder), soubory sdílené odkazem "
      "pro kohokoli na Disku Google a OneDrive (public_files), účty bez dvoufázového ověření (twofa, twofa_on service), šifrovaná "
      "záloha klíčů (keys_backup path+password, keys_restore), je to podvod? (scam text), kdo teď používá kameru a mikrofon "
      "(media), tresor dokumentů (vault_add path+name+tags, vault_find query, vault_open id), časový zámek (time_lock what+from+to), "
      "kontrola záznamu schválení (log_verify), heslo odkazem na jedno přečtení (secret_share text, hours), YubiKey (yubikey otp), "
      "vymazání stop (wipe_preview, wipe), router (router), rozšíření prohlížečů (extensions), všechno najednou (full).",
      category="bezpečnost", danger_if=lambda a: a.get("action") in SEC_CHANGES)
async def security_kit(ctx, action: Literal["audit", "canary", "public_files", "twofa", "twofa_on", "keys_backup", "keys_restore", "scam",
                                            "media", "vault_add", "vault_find", "vault_open", "time_lock", "log_verify", "secret_share",
                                            "yubikey", "wipe_preview", "wipe", "router", "extensions", "full"],
                       text: str = "", path: str = "", password: str = "", name: str = "", tags: str = "", query: str = "",
                       id: int = 0, hours: float = 24, what: str = "", start: str = "", end: str = "",  # noqa: A002
                       otp: str = "", service: str = "") -> ToolResult:
    if action == "audit":
        a = secx.permission_audit(ctx)
        return ToolResult(True, secx.audit_text(a), data=a)
    if action == "canary":
        folder = Path(path or text or Path.home() / "Documents")
        base = f"http://127.0.0.1:{ctx.cfg.phone.port}"
        made = secx.canary_create(ctx, folder, base)
        return ToolResult(True, "Návnady připravené: " + ", ".join(Path(m["path"]).name for m in made)
                          + ". Když je někdo otevře, hned ti to řeknu (a napíšu do telefonu).", data=made)
    if action == "public_files":
        r = await secx.public_drive_files(ctx)
        if r["google"] is None and r["onedrive"] is None:
            return ToolResult(False, "Nemám přístup k Disku Google ani OneDrive – připoj je v Nastavení → Připojení.")
        lines = []
        for k, label in (("google", "Disk Google"), ("onedrive", "OneDrive")):
            v = r[k]
            if isinstance(v, list):
                lines.append(f"{label}: {len(v)} souborů sdílených pro kohokoli s odkazem" + (": " + ", ".join(f["name"] for f in v[:10]) if v else "."))
            elif v:
                lines.append(f"{label}: {v}")
        return ToolResult(True, "\n".join(lines), data=r)
    if action == "twofa":
        r = secx.twofa_report(ctx)
        lines = [f"{m['service']}: {m['how']}" for m in r["missing"]]
        return ToolResult(True, ("Zapni druhé ověření:\n" + "\n".join(lines)) if lines else "U všech důležitých účtů máš druhé ověření.", data=r)
    if action == "twofa_on":
        key = secx.twofa_mark(ctx, service or text, True)
        return ToolResult(True, f"Zapsáno: {secx.IMPORTANT.get(key, key)} má druhé ověření.")
    if action == "keys_backup":
        if not path or not password:
            return ToolResult(False, "Kam (třeba E:\\JARVIS-klice.jvk) a jaké heslo zálohy?")
        try:
            p = await asyncio.to_thread(secx.keys_backup, Path(path), password, secx.collect_keys())
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Klíče zašifrované heslem jsou v {p}. Bez hesla se nedají přečíst – heslo si zapiš jinam.")
    if action == "keys_restore":
        from .. import secrets

        try:
            vals = await asyncio.to_thread(secx.keys_restore, Path(path), password)
        except (ValueError, OSError) as e:
            return ToolResult(False, str(e))
        for k, v in vals.items():
            secrets.set(k, v)
        return ToolResult(True, f"Obnoveno {len(vals)} klíčů.")
    if action == "scam":
        r = secx.scam_score(text, service)
        verdict = {"high": "Skoro jistě podvod", "medium": "Spíš podezřelé", "low": "Nevypadá to jako podvod"}[r["level"]]
        return ToolResult(True, f"{verdict}" + (f" ({', '.join(dict.fromkeys(r['why']))})." if r["why"] else ".")
                          + (" Na odkaz neklikej a nic neplať." if r["level"] != "low" else ""), data=r)
    if action == "media":
        from .. import secplus

        data = await asyncio.to_thread(secplus.run_ps, secplus.CONSENT_PS, 60)
        if "error" in data:
            return ToolResult(False, f"Nejde zjistit: {data['error']}")
        now_ = secx.in_use(secplus.parse_consent(secplus._list(data.get("apps"))))
        return ToolResult(True, ", ".join(x.split(":", 1)[1] + " – " + x.split(":", 1)[0] for x in sorted(now_)) or "Kameru ani mikrofon teď nic nepoužívá.")
    if action == "vault_add":
        p = Path(path)
        if not p.is_file():
            return ToolResult(False, "Takový soubor nemám.")
        vid = await asyncio.to_thread(secx.vault_add, ctx, p, name, tags, text)
        return ToolResult(True, f"Uloženo šifrovaně do tresoru (#{vid}). Původní soubor můžeš smazat.")
    if action == "vault_find":
        hits = secx.vault_search(ctx, query or text)
        return ToolResult(True, "\n".join(f"#{h['id']} {h['name']}" + (f" ({h['tags']})" if h["tags"] else "") for h in hits) or "Nic takového v tresoru není.",
                          data=hits)
    if action == "vault_open":
        import tempfile

        try:
            out = await asyncio.to_thread(secx.vault_get, ctx, id, Path(tempfile.gettempdir()) / "jarvis-trezor")
        except ValueError as e:
            return ToolResult(False, str(e))
        try:
            ctx.platform.open_path(str(out))
        except Exception:  # noqa: BLE001
            pass
        return ToolResult(True, f"Otevřeno: {out.name} (dočasná kopie – po zavření ji smaž).")
    if action == "time_lock":
        if not (what and start and end):
            locks = ctx.cfg.secx.time_locks
            return ToolResult(True, "\n".join(f"{x['what']}: {x['from']}–{x['to']}" for x in locks) or "Žádné časové zámky.", data=locks)
        lk = {"what": what, "from": start, "to": end}
        ctx.update_config({"secx": {"time_locks": [*ctx.cfg.secx.time_locks, lk]}})
        return ToolResult(True, f"Časový zámek: {what} jen mimo {start}–{end}.")
    if action == "log_verify":
        r = secx.verify_log(ctx)
        return ToolResult(r["ok"], f"Záznam schválení je neporušený ({r['count']} položek)." if r["ok"]
                          else f"Pozor: záznam byl změněn u položky #{r['broken_at']}!", data=r)
    if action == "secret_share":
        try:
            tok = secx.oneshot_create(ctx, text, hours)
        except ValueError as e:
            return ToolResult(False, str(e))
        base = str(getattr(ctx.cfg.phone_link, "public_url", "") or "").rstrip("/") or f"http://{_lan(ctx)}"
        return ToolResult(True, f"Odkaz na jedno přečtení (platí {hours:g} h): {base}/s/{tok}"
                          + ("" if base.startswith("https") else " – mimo domácí síť funguje jen s veřejnou adresou."))
    if action == "yubikey":
        ok, msg = await secx.yubikey_verify(ctx, otp or text)
        return ToolResult(ok, msg)
    if action in ("wipe_preview", "wipe"):
        targets = await asyncio.to_thread(secx.trace_targets)
        if action == "wipe_preview":
            return ToolResult(True, "\n".join(f"{t['label']}: {t['files']} souborů, {t['bytes'] / 2**20:.0f} MB" for t in targets)
                              or "Nic ke smazání.", data=targets)
        r = await asyncio.to_thread(secx.wipe, targets, [x.strip() for x in text.split(",") if x.strip()] or None)
        return ToolResult(True, f"Smazáno {r['files']} souborů ({r['bytes'] / 2**20:.0f} MB). Hesla a přihlášení zůstala.", data=r)
    if action == "router":
        rep = await secx.default_checks(ctx)["router"]()
        return ToolResult(True, f"Router {rep.get('gateway', '?')}: " + " ".join(rep.get("tips", [])), data=rep)
    if action == "extensions":
        exts = await asyncio.to_thread(secx.scan_extensions, secx.browser_ext_dirs())
        risky = [e for e in exts if e["level"] != "low"]
        return ToolResult(True, "\n".join(f"{e['name']} ({e['browser']}): {', '.join(e['risky']) or 'hodně oprávnění'}" for e in risky)
                          or f"Prošel jsem {len(exts)} rozšíření – žádné nemá nebezpečná oprávnění.", data=exts)
    r = await secx.full_check(ctx)
    return ToolResult(True, r["summary"] + ("\n" + "\n".join(r["findings"][3:10]) if len(r["findings"]) > 3 else ""), data=r)


def _lan(ctx) -> str:
    from ..house import lan_ip

    try:
        return f"{lan_ip()}:{ctx.cfg.phone.port}"
    except Exception:  # noqa: BLE001
        return f"localhost:{ctx.cfg.phone.port}"

