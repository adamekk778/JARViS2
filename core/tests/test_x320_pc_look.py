"""3.20 Ovládání PC+ (81–100) a Vzhled+ (101–120)."""
from __future__ import annotations

import datetime as dt
import io
import os
import subprocess
import time
from pathlib import Path

import pytest

from jarvis import lookx, pcx, tools


def _cp(out: str = "", code: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, out, "")


# ------------------------------------------------------------------ (81) úklid s náhledem a vrácením
def test_clean_preview_apply_undo(tmp_path):
    temp = tmp_path / "Temp"
    temp.mkdir()
    old = time.time() - 10 * 86400
    for name in ("a.tmp", "b.log", "keep.docx"):
        p = temp / name
        p.write_bytes(b"x" * 100)
        os.utime(p, (old, old))
    fresh = temp / "fresh.tmp"
    fresh.write_bytes(b"y")
    dl = tmp_path / "Downloads"
    dl.mkdir()
    (dl / "smlouva.pdf").write_bytes(b"z")
    os.utime(dl / "smlouva.pdf", (old, old))
    items = pcx.clean_candidates([temp, dl])
    names = sorted(Path(i["path"]).name for i in items)
    assert names == ["a.tmp", "b.log", "keep.docx"]                     # everything old in Temp; nothing from Downloads
    r = pcx.clean_apply(items)
    assert r["moved"] == 3 and not (temp / "a.tmp").exists()
    back = pcx.clean_undo()
    assert back["restored"] == 3 and (temp / "a.tmp").read_bytes() == b"x" * 100 and fresh.exists()
    with pytest.raises(ValueError):
        pcx.clean_undo()


# ------------------------------------------------------------------ (82) rozložení oken
async def test_window_layout_by_voice(rt):
    assert pcx.parse_layout("dej prohlížeč doleva a Discord doprava") == [("prohlizec", "left"), ("discord", "right")]
    wins = [{"hwnd": 1, "app": "Google Chrome", "exe": "chrome.exe", "title": "Gmail"},
            {"hwnd": 2, "app": "Discord", "exe": "Discord.exe", "title": "#obecné"}]
    placed = []
    rt.platform.window_layout = lambda: wins
    rt.platform.monitors = lambda: [{"index": 1, "left": 0, "top": 0, "width": 1920, "height": 1040, "primary": True}]
    rt.platform.place_window = lambda h, x, y, w, ht, state="normal": placed.append((h, x, y, w, ht)) or True
    r = await tools.call("pc_kit", {"action": "layout", "text": "dej prohlížeč doleva a Discord doprava a Spotify nahoru"}, rt)
    assert r.ok and placed == [(1, 0, 0, 960, 1040), (2, 960, 0, 960, 1040)] and "Nenašel jsem okno: spotify" in r.summary


# ------------------------------------------------------------------ (83) přesun programu
def test_move_program_with_a_link(tmp_path):
    prog = tmp_path / "C" / "Hra"
    prog.mkdir(parents=True)
    (prog / "hra.exe").write_bytes(b"MZ" + b"0" * 1000)
    calls = []
    r = pcx.move_program(prog, tmp_path / "D", runner=lambda cmd, t: calls.append(cmd) or _cp())
    assert r["to"] == str(tmp_path / "D" / "Hra") and (tmp_path / "D" / "Hra" / "hra.exe").is_file()
    assert calls[0][:4] == ["cmd", "/c", "mklink", "/J"]
    with pytest.raises(ValueError, match="běží"):
        pcx.move_program(tmp_path / "D" / "Hra", tmp_path / "E", running=lambda p: True)
    prog2 = tmp_path / "C" / "App"
    prog2.mkdir()
    (prog2 / "a.txt").write_text("x")
    with pytest.raises(RuntimeError, match="vrátil jsem"):
        pcx.move_program(prog2, tmp_path / "F", runner=lambda cmd, t: _cp("Access denied", 1))
    assert (prog2 / "a.txt").is_file()                                  # put back when the link failed


# ------------------------------------------------------------------ (84) ovladače, (85) licence
def test_drivers_and_licenses(rt, monkeypatch):
    assert pcx.gpu_vendor("NVIDIA GeForce RTX 4070") == "nvidia" and pcx.gpu_vendor("AMD Radeon RX 7800") == "amd"
    out = "Název           ID                   Verze\n-----------------------------------\nNVIDIA App      Nvidia.NVIDIAApp     11.0\n"
    assert pcx.winget_candidates(out) == [{"name": "NVIDIA App", "id": "Nvidia.NVIDIAApp"}]
    assert pcx.windows_key(lambda cmd, t: _cp("ABCDE-FGHIJ-KLMNO-PQRST-UVWXY\n")) == "ABCDE-FGHIJ-KLMNO-PQRST-UVWXY"
    assert pcx.windows_key(lambda cmd, t: _cp("")) == ""
    vault = {}
    monkeypatch.setattr("jarvis.secrets.get", lambda k: vault.get(k, ""))
    monkeypatch.setattr("jarvis.secrets.set", lambda k, v: vault.__setitem__(k, v))
    pcx.license_add(rt, "Affinity Photo", "AFF-1234-5678-9999")
    assert "AFF-1234-5678-9999" not in rt.db.one("SELECT secret FROM pc_licenses")["secret"]
    assert pcx.licenses(rt)[0]["key"] == "AFF-…9999" and pcx.licenses(rt, reveal=True)[0]["key"] == "AFF-1234-5678-9999"


# ------------------------------------------------------------------ (86) RGB, (89) ventilátory
def test_rgb_and_fans(tmp_path):
    assert pcx.rgb_command("hra", "OpenRGB") == ["OpenRGB", "--mode", "static", "--color", "FF0000"]
    assert pcx.rgb_command("party", "OpenRGB") == ["OpenRGB", "--mode", "rainbow"]
    assert pcx.rgb_command("#00ff88", "OpenRGB") == ["OpenRGB", "--mode", "static", "--color", "00FF88"]
    assert pcx.rgb_command("Večerní", "OpenRGB") == ["OpenRGB", "--profile", "Večerní"]
    (tmp_path / "Tichý.json").write_text("{}")
    (tmp_path / "Výkon.json").write_text("{}")
    assert pcx.fan_configs(tmp_path) == ["Tichý", "Výkon"]


# ------------------------------------------------------------------ (87) bod obnovy
def test_auto_restore_point_once_a_day(rt):
    ran = []

    def runner(cmd, timeout):
        ran.append(cmd)
        return 0, "OK", ""
    assert pcx.auto_restore_point(rt, "open_app", runner) == ""
    assert pcx.auto_restore_point(rt, "app_install", runner, now=1000.0) == "Vytvořil jsem bod obnovy."
    assert pcx.auto_restore_point(rt, "app_uninstall", runner, now=1000.0 + 3600) == ""
    assert pcx.auto_restore_point(rt, "app_uninstall", runner, now=1000.0 + 24 * 3600) == "Vytvořil jsem bod obnovy."
    assert len(ran) == 2


# ------------------------------------------------------------------ (88) schránka
async def test_clipboard_keeps_100_and_finds_without_accents(rt):
    act = rt.activity
    act.clips.clear()
    for i in range(120):
        act.clips.appendleft({"text": f"položka {i}", "ts": 0, "app": "Word"})
    act.clips.appendleft({"text": "Číslo účtu 1234/0800", "ts": 0, "app": "Edge"})
    assert len(act.clips) == 100
    rt.cfg.powers.clipboard_history = True
    r = await tools.call("clipboard_history", {"query": "cislo uctu"}, rt)
    assert r.ok and r.data[0]["text"] == "Číslo účtu 1234/0800"


# ------------------------------------------------------------------ (90) písma, (99) snímek s poznámkou
def test_font_install_and_annotate(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    f = tmp_path / "Moje.ttf"
    f.write_bytes(b"\0\1\0\0" + b"0" * 100)
    dst = pcx.install_font(f)
    assert dst.is_file() and dst.name == "Moje.ttf"
    with pytest.raises(ValueError):
        pcx.install_font(tmp_path / "x.zip")
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (30, 30, 30)).save(buf, "PNG")
    out = pcx.annotate(buf.getvalue(), "Tady klikni", (20, 20, 200, 150), (0, 0, 300, 200))
    im = Image.open(io.BytesIO(out))
    assert im.size == (300, 200) and im.getpixel((110, 85)) != (30, 30, 30)


# ------------------------------------------------------------------ (92, 93, 95, 96, 97, 98, 100)
def test_small_windows_helpers(tmp_path):
    assert pcx.default_app_target("PDF otevírej v prohlížeči") == ".pdf" and pcx.default_app_target("soubory .md v Obsidianu") == ".md"
    assert pcx.printer_diagnose([], [])[0].startswith("Windows nevidí")
    probs = pcx.printer_diagnose([{"Name": "HP", "PrinterStatus": "Offline", "Default": True}],
                                 [{"DocumentName": "faktura.pdf", "JobStatus": "Error, Printing"}])
    assert "offline" in probs[0] and probs[1].startswith("Zaseknutá fronta: 1")
    assert pcx.wifi_profiles("    Profil všech uživatelů : Babička\n    All User Profile : Kancl 5G\n") == ["Babička", "Kancl 5G"]
    assert pcx.wifi_key("    Obsah klíče            : tajne123\n") == "tajne123"
    (tmp_path / "programy-winget.json").write_text('{"Sources":[{"Packages":[{"PackageIdentifier":"Mozilla.Firefox"},{"PackageIdentifier":"7zip.7zip"}]}]}')
    assert pcx.migration_apps(tmp_path) == ["Mozilla.Firefox", "7zip.7zip"]
    a, b, c = b"A" * 16, b"B" * 16, b"C" * 16
    assert pcx.desktop_index(a + b + c, b) == (2, 3)
    assert pcx.desktop_keys(2, 3) == ["win+ctrl+right"] and pcx.desktop_keys(3, 1) == ["win+ctrl+left"] * 2
    assert pcx.monitor_signature([{"width": 2560, "height": 1440}, {"width": 1920, "height": 1080}]) == "1920x1080|2560x1440"
    assert pcx.monitor_of([{"left": 0, "top": 0, "width": 1920, "height": 1080}, {"left": 1920, "top": 0, "width": 2560, "height": 1440}],
                          2500, 300) == 1
    assert pcx.layout_for("Visual Studio Code", {"code": "en", "Telegram": "cs"}) == "00000409"
    assert pcx.layout_for("Telegram Desktop", {"code": "en", "Telegram": "cs"}) == "00000405"


# ------------------------------------------------------------------ Vzhled+: core parts
def test_weather_scene_season_theme():
    assert lookx.weather_scene(61) == "rain" and lookx.weather_scene(73) == "snow" and lookx.weather_scene(95) == "storm"
    assert lookx.weather_scene(0, hour=13) == "sun" and lookx.weather_scene(0, hour=23) == "night" and lookx.weather_scene(None) == ""
    assert lookx.season(dt.date(2026, 1, 5)) == "winter" and lookx.season(dt.date(2026, 10, 5)) == "autumn"
    t = lookx.theme_clean({"name": "Noc", "accent": "#ff00aa", "bg": "red; background:url(x)", "font": "Comic", "speed": 9, "radius": 99})
    assert t == {"name": "Noc", "accent": "#ff00aa", "speed": 2.0, "radius": 30}


def test_burst_of_notices_becomes_one_line():
    b = lookx.Burst()
    t = 1000.0
    shown = [b.add(x, t + i) for i, x in enumerate(["Máma", "Alza", "Máma", "Teams", "Máma", "Kalendář"])]
    assert shown == [True, True, True, True, False, False]
    assert not b.due(t + 6) and b.due(t + 40)
    assert b.summary() == ("2 další upozornění", "Máma, Kalendář")


async def test_notify_burst_in_the_runtime(rt):
    seen = []
    rt.bus.publish = lambda _t, **kw: seen.append((_t, kw)) if _t == "notify" else None
    for i in range(6):
        rt.notify(f"Zpráva {i}", "text", speak=False)
    rt.notify("Budík", "Vstávej", speak=False, urgent=True)
    notes = [kw for k, kw in seen]
    assert len(notes) == 5 and notes[-1]["urgent"] is True and notes[-1]["title"] == "Budík"


def test_trip_clock_and_stretch(rt):
    rt.db.exec("CREATE TABLE IF NOT EXISTS bookings (provider TEXT, ref TEXT, kind TEXT, name TEXT, city TEXT, country TEXT, start TEXT, end TEXT, "
               "status TEXT)")
    rt.db.exec("INSERT INTO bookings(provider, ref, kind, name, city, country, start, end, status) VALUES "
               "('liteapi','B1','hotel','Hotel X','Londýn','GB','2026-12-01','2026-12-05','booked')")
    assert lookx.trip_clock(rt, dt.date(2026, 12, 2)) == {"tz": "Europe/London", "label": "Londýn"}
    assert lookx.trip_clock(rt, dt.date(2026, 12, 9)) is None
    assert not lookx.stretch_due(rt, 30) and lookx.stretch_due(rt, 91) and not lookx.stretch_due(rt, 120)
    assert not lookx.stretch_due(rt, 0) and lookx.stretch_due(rt, 95)


async def test_look_tick_sends_the_notch_its_data(rt):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    rt.calendar.add("Porada", dt.datetime.fromtimestamp(time.time() + 5 * 60))
    seen = []
    rt.bus.publish = lambda _t, **kw: seen.append(_t)
    sent = await lookx.tick(rt)
    assert "countdown" in sent and {"day_timeline", "weather_now", "second_clock", "wallpaper_tasks"} <= set(seen)
    again = await lookx.tick(rt, time.time() + 1)
    assert "countdown" not in again


def test_startup_sound_and_fx_render(rt):
    wav = lookx.startup_wav()
    assert wav[:4] == b"RIFF" and len(wav) > 30000
    assert lookx.startup_sound_ok(rt, 12) and not lookx.startup_sound_ok(rt, 23)
    rt.cfg.appearance.startup_sound = False
    assert not lookx.startup_sound_ok(rt, 12)
    from jarvis import fxrender

    assert fxrender.is_visible(fxrender.ring()(0.5)) and fxrender.is_visible(fxrender.eq([0.2, 0.9, 0.5])(0.3))
    from jarvis.desktop import fxwin

    assert fxwin.effect_for(rt, "ring", {"x": 100, "y": 100}) is not None
    assert fxwin.effect_for(rt, "eq", {"bars": [0.3, 0.6]}) is not None
    assert lookx.sharing_screen(["Microsoft Teams – Sdílíte obrazovku"]) and not lookx.sharing_screen(["Word"])


async def test_look_and_pc_tools(rt):
    r = await tools.call("look_kit", {"action": "obs_url"}, rt)
    assert r.ok and r.data["url"].endswith("/hud?obs=1") and "token" not in r.data["url"]
    r = await tools.call("look_kit", {"action": "theme_save", "name": "Noc", "accent": "#112233", "font": "Orbitron"}, rt)
    assert r.ok and rt.cfg.appearance.active_theme == "Noc"
    assert (await tools.call("look_kit", {"action": "second_clock", "text": "Mars/Base"}, rt)).ok is False
    assert (await tools.call("look_kit", {"action": "second_clock", "text": "Asia/Tokyo"}, rt)).ok and rt.cfg.notch.second_tz == "Asia/Tokyo"
    assert tools.REGISTRY["pc_kit"].danger_if({"action": "move_program"}) and not tools.REGISTRY["pc_kit"].danger_if({"action": "wifi"})


def test_weather_scene_is_off_by_default_and_migrated_off(rt, monkeypatch):
    """The snow showed as a grid of dots over the answer card: off by default, and a saved "on" from 3.20 goes off once."""
    from jarvis import config

    assert config.Config().notch.weather_scene is False
    old = config.Config().model_dump(mode="json")
    old["notch"]["weather_scene"] = True
    old["notch"].pop("weather_scene_rev")
    assert config.Config.model_validate(old).notch.weather_scene is False
    kept = config.Config().model_dump(mode="json")
    kept["notch"]["weather_scene"] = True                      # switched on again after the migration: stays on
    assert config.Config.model_validate(kept).notch.weather_scene is True
