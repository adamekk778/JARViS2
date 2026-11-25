"""3.20 Ovládání PC+ tools (nápady 81–100)."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Literal

from .. import pcx
from .base import ToolResult, tool

CHANGES = {"clean_apply", "move_program", "printer_fix", "migrate_import", "shutdown_in", "default_app", "presentation"}
WIN_ONLY = "Tohle umím jen na Windows."


@tool("pc_kit", "Počítač: úklid s náhledem a vrácením (clean_preview, clean_apply, clean_undo), rozložení oken hlasem (layout, "
      "text = „prohlížeč doleva a Discord doprava“), přesun programu na jiný disk (move_program path+dest), ovladače grafiky "
      "(driver_update), licence (licenses, license_add product+key, windows_key), RGB (rgb text), ventilátory (fans text), "
      "písmo z obrázku (font_identify attachment) a instalace (font_install path), vypnutí za N minut (shutdown_in minutes, "
      "shutdown_cancel), výchozí aplikace (default_app text), proč netiskne (printer, printer_fix), režim prezentace "
      "(presentation on), Wi-Fi hesla (wifi text), přenos na nové PC (migrate_export, migrate_import path), virtuální plochy "
      "(desktop number), profily monitorů (monitor_save/monitor_load name), snímek s poznámkou (snip text), klávesnice podle "
      "aplikace (keyboard app+lang).", category="systém", danger_if=lambda a: a.get("action") in CHANGES)
async def pc_kit(ctx, action: Literal["clean_preview", "clean_apply", "clean_undo", "layout", "move_program", "driver_update", "licenses",
                                      "license_add", "windows_key", "rgb", "fans", "font_identify", "font_install", "shutdown_in",
                                      "shutdown_cancel", "default_app", "printer", "printer_fix", "presentation", "wifi",
                                      "migrate_export", "migrate_import", "desktop", "monitor_save", "monitor_load", "snip", "keyboard"],
                 text: str = "", path: str = "", dest: str = "", product: str = "", key: str = "", minutes: int = 60, on: bool = True,
                 number: int = 0, name: str = "", attachment: str = "", app: str = "", lang: str = "") -> ToolResult:
    import os

    if action == "clean_preview":
        roots = [Path(os.environ.get("TEMP", "/tmp")), Path.home() / "AppData" / "Local" / "Temp", Path.home() / "Downloads"]
        items = await asyncio.to_thread(pcx.clean_candidates, roots)
        ctx.pcx_clean = items
        total = sum(i["size"] for i in items)
        top = ", ".join(Path(i["path"]).name for i in sorted(items, key=lambda x: -x["size"])[:5])
        return ToolResult(True, f"Mohu uklidit {len(items)} souborů ({pcx.human(total)}), např.: {top or '—'}. Nic nesmažu hned – půjde to do "
                                "karantény a „vrať úklid“ to vrátí.", data={"count": len(items), "size": total})
    if action == "clean_apply":
        items = getattr(ctx, "pcx_clean", None) or []
        if not items:
            return ToolResult(False, "Nejdřív řekni „ukaž, co uklidíš“.")
        r = await asyncio.to_thread(pcx.clean_apply, items)
        ctx.pcx_clean = []
        return ToolResult(True, f"Uklizeno {r['moved']} souborů ({pcx.human(r['size'])}). Vrátit jde 30 dní („vrať úklid“).", data=r)
    if action == "clean_undo":
        try:
            r = await asyncio.to_thread(pcx.clean_undo, text)
        except ValueError as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Vráceno {r['restored']} souborů na původní místa.", data=r)
    if action == "layout":
        pairs = pcx.parse_layout(text)
        if not pairs:
            return ToolResult(False, "Nerozumím rozložení – třeba „prohlížeč doleva a Discord doprava“.")
        wins = await asyncio.to_thread(ctx.platform.window_layout) if hasattr(ctx.platform, "window_layout") else []
        mons = await asyncio.to_thread(ctx.platform.monitors) if hasattr(ctx.platform, "monitors") else []
        mon = next((m for m in mons if m.get("primary")), mons[0] if mons else {"left": 0, "top": 0, "width": 1920, "height": 1040})
        done, missing = [], []
        for who, side in pairs:
            w = pcx.find_window(wins, who)
            if w is None:
                missing.append(who)
                continue
            x, y, wd, ht = pcx.rect_for(side, mon)
            ok = await asyncio.to_thread(ctx.platform.place_window, w["hwnd"], x, y, wd, ht, "normal")
            (done if ok else missing).append(f"{w.get('app') or who} {side}" if ok else who)
        msg = ("Rozloženo: " + ", ".join(done) + ".") if done else ""
        if missing:
            msg += f" Nenašel jsem okno: {', '.join(missing)}."
        return ToolResult(bool(done), msg.strip(), data={"done": done, "missing": missing})
    if action == "move_program":
        if not path or not dest:
            return ToolResult(False, "Potřebuju složku programu (path) a kam (dest, např. D:\\Programy).")
        try:
            import psutil

            def running(folder: Path) -> bool:
                f = str(folder).lower()
                return any((p.info.get("exe") or "").lower().startswith(f) for p in psutil.process_iter(["exe"]))
            r = await asyncio.to_thread(pcx.move_program, Path(path), Path(dest), None, running)
        except (ValueError, RuntimeError, OSError) as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Přesunuto na {r['to']} ({pcx.human(r['size'])}). Na původním místě je odkaz, program poběží jako dřív.", data=r)
    if action == "driver_update":
        if not pcx.WIN:
            return ToolResult(False, WIN_ONLY)
        gpu = pcx.ps("(Get-CimInstance Win32_VideoController | Select-Object -First 1).Name")
        vendor = pcx.gpu_vendor(gpu)
        if not vendor:
            return ToolResult(False, f"Grafiku „{gpu}“ neznám – ovladač najdeš na webu výrobce.")
        out = await asyncio.to_thread(pcx.run, ["winget", "search", pcx.VENDOR_APPS[vendor], "--accept-source-agreements"], 60)
        cands = pcx.winget_candidates(out.stdout)
        if not cands:
            return ToolResult(False, f"Aplikaci {pcx.VENDOR_APPS[vendor]} jsem ve wingetu nenašel.")
        return ToolResult(True, f"Grafika {gpu}: ovladače aktualizuje {cands[0]['name']} (winget {cands[0]['id']}). Mám ji nainstalovat? "
                                "(řekni „nainstaluj " + cands[0]["id"] + "“)", data={"gpu": gpu, "candidates": cands[:5]})
    if action == "windows_key":
        if not pcx.WIN:
            return ToolResult(False, WIN_ONLY)
        k = await asyncio.to_thread(pcx.windows_key)
        return ToolResult(bool(k), f"Klíč Windows z firmwaru: {k}" if k else "Klíč Windows ve firmwaru není (digitální licence k účtu).")
    if action == "license_add":
        if not product or not key:
            return ToolResult(False, "Potřebuju název programu a klíč.")
        pcx.license_add(ctx, product, key, text)
        return ToolResult(True, f"Licence k {product} je uložená šifrovaně.")
    if action == "licenses":
        ls = pcx.licenses(ctx, reveal=bool(product))
        if product:
            ls = [x for x in ls if pcx.fold(product) in pcx.fold(x["product"])]
        return ToolResult(True, "\n".join(f"{x['product']}: {x['key']}" + (f" ({x['note']})" if x["note"] else "") for x in ls)
                          or "Zatím nemám uložené žádné licence.", data=ls)
    if action == "rgb":
        exe = pcx.find_exe(("OpenRGB", "OpenRGB.exe"), ("OpenRGB/OpenRGB.exe",))
        if not exe:
            return ToolResult(False, "Na RGB potřebuju OpenRGB (zdarma, openrgb.org) – nainstaluj ho a spusť jednou.")
        out = await asyncio.to_thread(pcx.run, pcx.rgb_command(text or "klid", exe), 30)
        return ToolResult(out.returncode == 0, f"Podsvícení: {text or 'klid'}." if out.returncode == 0 else f"OpenRGB: {out.stderr[:200]}")
    if action == "fans":
        exe = pcx.find_exe(("FanControl", "FanControl.exe"), ("FanControl/FanControl.exe",))
        if not exe:
            return ToolResult(False, "Na ventilátory potřebuju FanControl (zdarma, getfancontrol.com) s uloženými profily.")
        folder = Path(exe).parent / "Configurations"
        cfgs = pcx.fan_configs(folder)
        want = next((c for c in cfgs if pcx.fold(text) and pcx.fold(text)[:4] in pcx.fold(c)), "")
        if not want:
            return ToolResult(False, "Profil nenašel. Mám: " + (", ".join(cfgs) or "žádné (ulož je ve FanControlu)"))
        out = await asyncio.to_thread(pcx.run, [exe, "-c", str(folder / f"{want}.json")], 30)
        return ToolResult(out.returncode == 0, f"Ventilátory: profil {want}.")
    if action == "font_identify":
        if not attachment:
            return ToolResult(False, "Pošli mi obrázek s tím písmem.")
        parts = await ctx.store.llm_parts(attachment, vision=True)
        out = await ctx.router.complete([{"role": "system", "content": pcx.FONT_PROMPT},
                                         {"role": "user", "content": [{"type": "text", "text": "Jaké je to písmo?"}, *parts]}], need_vision=True)
        m = re.search(r"\{.*\}", out or "", re.S)
        d = json.loads(m.group(0)) if m else {}
        if not d.get("font"):
            return ToolResult(False, "Písmo nepoznám jistě – zkus větší výřez s víc písmeny.")
        sim = d.get("similar_free") or []
        links = ", ".join(f"{s} (fonts.google.com/specimen/{s.replace(' ', '+')})" for s in sim[:3])
        return ToolResult(True, f"Vypadá to na {d['font']}." + (f" Podobná zdarma: {links}." if links else ""), data=d)
    if action == "font_install":
        try:
            dst = await asyncio.to_thread(pcx.install_font, Path(path))
        except (ValueError, OSError) as e:
            return ToolResult(False, str(e))
        return ToolResult(True, f"Písmo {dst.stem} je nainstalované (pro tebe, bez správce). Programy ho uvidí po restartu.")
    if action == "shutdown_in":
        if not pcx.WIN:
            return ToolResult(False, WIN_ONLY)
        until = await asyncio.to_thread(pcx.shutdown_in, minutes)
        ctx.bus.publish("countdown", kind="shutdown", title="Vypnutí PC", until=until)
        return ToolResult(True, f"Počítač se vypne za {minutes} min. Odpočet je v notchi; „zruš vypnutí“ to zastaví.")
    if action == "shutdown_cancel":
        if pcx.WIN:
            await asyncio.to_thread(pcx.shutdown_cancel)
        ctx.bus.publish("countdown", kind="shutdown", title="", until=0)
        return ToolResult(True, "Vypnutí zrušeno.")
    if action == "default_app":
        target = pcx.default_app_target(text)
        exe = pcx.find_exe(("SetUserFTA", "SetUserFTA.exe"))
        if exe and target:
            out = await asyncio.to_thread(pcx.run, [exe, target, app or text], 30)
            return ToolResult(out.returncode == 0, f"{target} teď otevírá {app}.")
        if pcx.WIN:
            os.startfile("ms-settings:defaultapps")                # type: ignore[attr-defined]  # pragma: no cover
        return ToolResult(True, f"Windows nedovolí programům měnit výchozí aplikace samy – otevřel jsem Nastavení → Výchozí aplikace; "
                                f"vyber {app or 'program'} pro {target or 'ten typ souboru'}.")
    if action in ("printer", "printer_fix"):
        if not pcx.WIN:
            return ToolResult(False, WIN_ONLY)
        printers = pcx.ps_json("Get-Printer | Select-Object Name,PrinterStatus,WorkOffline,Default") or []
        jobs = pcx.ps_json("Get-Printer | ForEach-Object { Get-PrintJob -PrinterName $_.Name } | Select-Object DocumentName,JobStatus") or []
        problems = pcx.printer_diagnose(printers, jobs)
        if action == "printer":
            return ToolResult(True, " ".join(problems), data={"printers": printers, "jobs": jobs})
        pcx.ps("Get-Printer | ForEach-Object { Get-PrintJob -PrinterName $_.Name | Remove-PrintJob }; Restart-Service Spooler -Force")
        return ToolResult(True, "Fronta vyčištěná a tisková služba restartovaná – zkus tisknout znovu.")
    if action == "presentation":
        ctx.attention.focus(240 if on else 0)
        if pcx.WIN:
            v = 0 if on else 1
            pcx.ps(f"Set-ItemProperty -Path HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\PushNotifications -Name ToastEnabled -Value {v}")
        return ToolResult(True, "Režim prezentace: upozornění Windows i JARVISe jsou ztlumená." if on else "Režim prezentace vypnutý.")
    if action == "wifi":
        if not pcx.WIN:
            return ToolResult(False, WIN_ONLY)
        out = await asyncio.to_thread(pcx.run, ["netsh", "wlan", "show", "profiles"], 30)
        names = pcx.wifi_profiles(out.stdout)
        hit = next((n for n in names if pcx.fold(text) and (pcx.fold(n) in pcx.fold(text) or pcx.fold(text) in pcx.fold(n))), "")
        if not hit:
            return ToolResult(True, "Uložené sítě: " + ", ".join(names) + ". Kterou?" if names else "Žádné uložené Wi-Fi nemám.")
        k = await asyncio.to_thread(pcx.run, ["netsh", "wlan", "show", "profile", f"name={hit}", "key=clear"], 30)
        pw = pcx.wifi_key(k.stdout)
        return ToolResult(bool(pw), f"Heslo k {hit}: {pw}" if pw else f"K síti {hit} heslo uložené není.")
    if action == "migrate_export":
        folder = Path(path or Path.home() / "Documents" / "JARVIS" / "Nové PC")
        await asyncio.to_thread(pcx.migration_pack, ctx, folder)
        return ToolResult(True, f"Připraveno ve složce {folder} – zkopíruj ji na nové PC.")
    if action == "migrate_import":
        apps = pcx.migration_apps(Path(path))
        if not apps:
            return ToolResult(False, "Ve složce není seznam programů (programy-winget.json).")
        out = await asyncio.to_thread(pcx.run, ["winget", "import", "-i", str(Path(path) / "programy-winget.json"),
                                                "--accept-package-agreements", "--accept-source-agreements"], 3600)
        return ToolResult(out.returncode == 0, f"Instaluji {len(apps)} programů ze starého PC." if out.returncode == 0 else out.stdout[-300:],
                          data={"apps": apps})
    if action == "desktop":
        if not pcx.WIN:
            return ToolResult(False, WIN_ONLY)
        import winreg                                            # pragma: no cover – Windows

        base = r"Software\Microsoft\Windows\CurrentVersion\Explorer\VirtualDesktops"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as k:
            ids = winreg.QueryValueEx(k, "VirtualDesktopIDs")[0]
            cur = winreg.QueryValueEx(k, "CurrentVirtualDesktop")[0]
        c, n = pcx.desktop_index(ids, cur)
        want = max(1, min(number or c, n))
        for combo in pcx.desktop_keys(c, want):
            await asyncio.to_thread(ctx.platform.hotkey, combo.split("+"))
            await asyncio.sleep(0.25)
        return ToolResult(True, f"Plocha {want} z {n}.")
    if action in ("monitor_save", "monitor_load"):
        exe = pcx.find_exe(("MultiMonitorTool", "MultiMonitorTool.exe"), ("MultiMonitorTool/MultiMonitorTool.exe",))
        if not exe:
            return ToolResult(False, "Na profily monitorů potřebuju MultiMonitorTool (NirSoft, zdarma) – stačí ho rozbalit do Program Files.")
        from ..paths import data_dir

        cfg = data_dir() / "monitory" / f"{pcx.fold(name or 'doma').replace(' ', '-')}.cfg"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        flag = "/SaveConfig" if action == "monitor_save" else "/LoadConfig"
        out = await asyncio.to_thread(pcx.run, [exe, flag, str(cfg)], 30)
        if action == "monitor_save":
            mons = await asyncio.to_thread(ctx.platform.monitors)
            profiles = dict(getattr(ctx.cfg.pc, "monitor_profiles", {}) or {})
            profiles[pcx.monitor_signature(mons)] = cfg.stem
            ctx.update_config({"pc": {"monitor_profiles": profiles}})
        return ToolResult(out.returncode == 0, f"Profil monitorů „{cfg.stem}“ {'uložený' if action == 'monitor_save' else 'nastavený'}.")
    if action == "snip":
        png = await asyncio.to_thread(ctx.platform.screenshot)
        crop = None
        m = re.search(r"(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", text or "")
        if m:
            crop = tuple(int(x) for x in m.groups())
            text = text[:m.start()].strip()
        img = await asyncio.to_thread(pcx.annotate, png, text, None, crop)
        att = await ctx.store.save("snimek-s-poznamkou.png", img, "image/png")
        return ToolResult(True, "Snímek s poznámkou je v chatu.", attachments=[att.id])
    if not app or not lang:
        m = dict(getattr(ctx.cfg.pc, "keyboard_by_app", {}) or {})
        return ToolResult(True, "Klávesnice podle aplikace: " + (", ".join(f"{k} → {v}" for k, v in m.items()) or "nic nastaveno"), data=m)
    m = dict(getattr(ctx.cfg.pc, "keyboard_by_app", {}) or {})
    m[app] = lang
    ctx.update_config({"pc": {"keyboard_by_app": m}})
    return ToolResult(True, f"V {app} přepnu klávesnici na {lang}.")


@tool("look_kit", "Vzhled: odkaz na průhledný HUD pro OBS (obs_url), 3D postava místo notche (avatar on), režim zen (zen on), "
      "druhé hodiny (second_clock text = časové pásmo, např. Europe/London), vlastní téma (theme_save name + accent/bg/text "
      "#rrggbb, font, speed, radius; theme_use name), fotka z tohoto dne hned (photo_now).", category="vzhled")
async def look_kit(ctx, action: Literal["obs_url", "avatar", "zen", "second_clock", "theme_save", "theme_use", "photo_now"],
                   on: bool = True, text: str = "", name: str = "", accent: str = "", bg: str = "", fg: str = "", font: str = "",
                   speed: float = 1.0, radius: int = 14) -> ToolResult:
    from .. import lookx

    if action == "obs_url":
        url = f"http://127.0.0.1:{ctx.cfg.phone.port}/hud?obs=1"
        return ToolResult(True, f"V OBS přidej zdroj Prohlížeč s adresou {url} (šířka 1920, výška 1080) – je průhledný a ukazuje, "
                                "co JARVIS slyší, dělá a říká.", data={"url": url})
    if action == "avatar":
        ctx.update_config({"appearance": {"avatar3d": bool(on)}})
        return ToolResult(True, "3D postava se ukáže po restartu JARVISe." if on else "Po restartu bude zase notch.")
    if action == "zen":
        ctx.update_config({"notch": {"zen": bool(on)}})
        return ToolResult(True, "Režim zen: notch je neviditelný, dokud ho nepotřebuješ." if on else "Režim zen vypnutý.")
    if action == "second_clock":
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        tz = text.strip()
        if tz:
            try:
                ZoneInfo(tz)
            except (ZoneInfoNotFoundError, ValueError):
                return ToolResult(False, f"Časové pásmo „{tz}“ neznám – zkus třeba Europe/London nebo America/New_York.")
        ctx.update_config({"notch": {"second_tz": tz}})
        return ToolResult(True, f"Druhé hodiny: {tz}." if tz else "Druhé hodiny vypnuté.")
    if action == "theme_save":
        t = lookx.theme_clean({"name": name or "Moje téma", "accent": accent, "bg": bg, "text": fg, "font": font, "speed": speed,
                               "radius": radius})
        themes = [x for x in (ctx.cfg.appearance.custom_themes or []) if x.get("name") != t["name"]] + [t]
        ctx.update_config({"appearance": {"custom_themes": themes, "active_theme": t["name"]}})
        return ToolResult(True, f"Téma „{t['name']}“ je uložené a zapnuté.", data=t)
    if action == "theme_use":
        names = [x.get("name") for x in (ctx.cfg.appearance.custom_themes or [])]
        if name and name not in names:
            return ToolResult(False, "Takové téma nemám. Mám: " + (", ".join(names) or "žádné"))
        ctx.update_config({"appearance": {"active_theme": name}})
        return ToolResult(True, f"Téma „{name}“." if name else "Vestavěné téma.")
    p = lookx.photo_of_day(ctx)
    if not p:
        return ToolResult(False, "Z tohoto dne v minulých letech nemám žádnou fotku (nejdřív „projdi moje fotky“).")
    ctx.bus.publish("photo_frame", **p)
    return ToolResult(True, f"V notchi: {p['caption']}.")
