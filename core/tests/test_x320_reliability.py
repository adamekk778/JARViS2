"""3.20 Spolehlivost+ (441–460), with chaos tests (456): failing networks and services must never crash JARVIS."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import random
import socket
import struct
import time
from types import SimpleNamespace

import httpx
import pytest

from jarvis import reliax, tools


async def test_supervise_restarts_and_gives_up(rt):
    runs = {"n": 0}

    async def flaky():
        runs["n"] += 1
        if runs["n"] < 3:
            raise ConnectionError("síť")

    waits = []

    async def no_sleep(s):
        waits.append(s)

    await reliax.supervise(rt, "Test", flaky, sleep=no_sleep)
    assert runs["n"] == 3 and waits == [5.0, 10.0]
    assert sum(1 for n in rt.notices if "spadla" in n["body"]) == 2 and "spojení vypadlo" in rt.notices[0]["body"]

    async def always():
        raise RuntimeError("rozbité")

    await reliax.supervise(rt, "Vždy", always, max_restarts=2, sleep=no_sleep)
    assert reliax.db(rt).one("SELECT name FROM rx_events WHERE kind='gave_up'")["name"] == "Vždy"
    assert reliax.score(rt)["problems"][0]["what"].startswith("část Vždy je vypnutá")


async def test_watch_crashed_tasks(rt):
    async def boom():
        raise ValueError("špatná data")

    async def fine():
        await asyncio.sleep(10)

    t1 = asyncio.get_running_loop().create_task(boom())
    t2 = asyncio.get_running_loop().create_task(fine())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    rt._sys_tasks = [t1, t2]
    said = reliax.watch_tasks(rt)
    assert len(said) == 1 and "boom" in said[0] and "špatná data" in said[0]
    assert reliax.watch_tasks(rt) == []                       # said once
    t2.cancel()


def test_sntp_offset():
    class Sock:
        def __init__(self, *a):
            pass

        def settimeout(self, t):
            pass

        def sendto(self, data, addr):
            assert data[0] == 0x1B and addr[1] == 123

        def recvfrom(self, n):
            server = time.time() - 42 + 2208988800
            return b"\0" * 40 + struct.pack("!II", int(server), int((server % 1) * 2**32)), None

        def close(self):
            pass

    off = reliax.sntp_offset(sock_factory=Sock)
    assert 41 < off < 43
    assert "napřed" in reliax.clock_text(off) and "přesně" in reliax.clock_text(1.2)


def test_settings_history_and_restore(rt):
    from jarvis import config

    config.save(rt.cfg)
    reliax.snapshot(dt.date(2026, 11, 1))
    rt.update_config({"general": {"name": "Pátek"}} if hasattr(rt.cfg, "general") and hasattr(rt.cfg.general, "name") else {"calendar": {"remind_minutes": 33}})
    config.save(rt.cfg)
    reliax.snapshot(dt.date(2026, 11, 20))
    assert reliax.history()[:2] == ["2026-11-20", "2026-11-01"]
    day = reliax.restore_settings(rt, "2026-11-10")
    assert day == "2026-11-01"
    assert rt.cfg.calendar.remind_minutes != 33 or getattr(getattr(rt.cfg, "general", None), "name", "") != "Pátek"
    with pytest.raises(ValueError):
        reliax.restore_settings(rt, "2020-01-01")


def test_config_issues_and_score(rt, tmp_path):
    rt.cfg.tools.allowed_folders = [str(tmp_path / "neni")]
    rt.cfg.calendar.ics_urls = ["ftp://x"]
    rt.cfg.shopx.iron_plug = "light.lampa"
    issues = [i["what"] for i in reliax.config_issues(rt)]
    assert any("neexistuje" in i for i in issues) and any("Kalendář 1" in i for i in issues) and any("Páječka" in i for i in issues)
    s = reliax.score(rt)
    assert s["score"] <= 88 and all(p["fix"] for p in s["problems"])
    rt.safe_mode = True
    assert any("nouzovém" in p["what"] for p in reliax.score(rt)["problems"])
    rt.safe_mode = False


def test_photo_backup_state(tmp_path):
    assert not reliax.photo_backup_state(tmp_path / "nic")["ok"]
    (tmp_path / "a.jpg").write_bytes(b"x")
    import os

    old = time.time() - 6 * 86400
    os.utime(tmp_path / "a.jpg", (old, old))
    st = reliax.photo_backup_state(tmp_path)
    assert not st["ok"] and st["days"] == 6 and "aplikaci" in st["why"]
    assert reliax.photo_backup_state(tmp_path, now=old + 3600)["ok"]


def test_speed_history(rt):
    from jarvis.latency import get

    lat = get(rt)
    for ms in (800, 1000, 1200):
        lat.begin("chat", time.monotonic() - ms / 1000)
        lat.finish()
    assert reliax.speed_record(rt, dt.date(2026, 11, 20)) >= 1
    weeks = reliax.speed_weeks(rt, today=dt.date(2026, 11, 25), weeks=2)
    assert weeks[-1]["ms"] and 900 <= weeks[-1]["ms"] <= 1100 and weeks[0]["ms"] is None


def test_ups_decision():
    on_bat = SimpleNamespace(power_plugged=False, percent=60)
    plugged = SimpleNamespace(power_plugged=True, percent=100)
    assert reliax.ups_decision(None, None, 0, 30, 0) == ("", None)
    assert reliax.ups_decision(on_bat, None, 100, 30, 0) == ("outage", 100)
    assert reliax.ups_decision(on_bat, 100, 160, 30, 0) == ("", 100)
    assert reliax.ups_decision(SimpleNamespace(power_plugged=False, percent=25), 100, 200, 30, 0)[0] == "shutdown"
    assert reliax.ups_decision(on_bat, 100, 100 + 11 * 60, 0, 10)[0] == "shutdown"
    assert reliax.ups_decision(plugged, 100, 300, 30, 0) == ("restored", None)


async def test_ups_tick(rt, monkeypatch):
    import psutil

    rt.cfg.reliax.ups = True
    rt.cfg.reliax.ups_shutdown_pct = 30
    state = {"b": SimpleNamespace(power_plugged=False, percent=80)}
    monkeypatch.setattr(psutil, "sensors_battery", lambda: state["b"])
    now = dt.datetime(2026, 11, 25, 2, 0)
    assert "outage" in await reliax.tick(rt, now)
    state["b"] = SimpleNamespace(power_plugged=False, percent=20)
    assert "shutdown" in await reliax.tick(rt, now + dt.timedelta(minutes=5))
    assert "shutdown" not in await reliax.tick(rt, now + dt.timedelta(minutes=6))          # only once


def test_restore_drill(rt, tmp_path, monkeypatch):
    from jarvis import paths, privacy

    data = paths.data_dir()
    (data / "config.toml").write_text('[calendar]\nremind_minutes = 15\n', encoding="utf-8")
    vault = privacy.backup_encrypted("heslo1234", tmp_path)
    r = reliax.restore_drill(vault, "heslo1234", tmp_path / "drill")
    assert r["ok"] and r["db"] == "ok" and r["config"] == "ok"
    with pytest.raises(Exception):
        reliax.restore_drill(vault, "spatneheslo", tmp_path / "drill2")


def test_integrity(rt, tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.js").write_text("y")
    base = reliax.file_hashes(tmp_path)
    assert reliax.integrity_check(tmp_path, base)["ok"]
    (tmp_path / "a.py").write_text("x = 2\n")
    (tmp_path / "b.js").unlink()
    (tmp_path / "c.py").write_text("")
    r = reliax.integrity_check(tmp_path, base)
    assert r == {"ok": False, "changed": ["a.py"], "missing": ["b.js"], "added": ["c.py"], "files": 2}
    first = reliax.integrity(rt, tmp_path)
    assert first["first"] and reliax.integrity(rt, tmp_path)["ok"]


def test_alarm_check(rt):
    t0 = dt.datetime(2026, 11, 25, 6, 30).timestamp()
    rt.platform.idle_seconds = lambda: 3600.0
    reliax.alarm_fired(rt, "Budík 6:30", now=t0)
    assert reliax.alarm_check(rt, t0 + 60) == ""                               # too early to tell
    assert reliax.alarm_check(rt, t0 + 9 * 60) == "Budík 6:30"
    assert reliax.db(rt).one("SELECT detail FROM rx_events WHERE kind='alarm'")["detail"] == "no reaction"
    reliax.alarm_fired(rt, "Budík 2", now=t0)
    rt.platform.idle_seconds = lambda: 30.0                                    # you touched the PC
    assert reliax.alarm_check(rt, t0 + 9 * 60) == ""
    rep = reliax.month_report(rt, 2026, 11)
    assert rep["alarms_missed"] == 1 and "budík zazvonil znovu" in reliax.month_text(rep)


async def test_stress(rt):
    r = await reliax.stress(rt, 60, 10)
    assert r["n"] == 60 and r["per_s"] > 0 and r["bottleneck"] in ("instant", "pick", "db") and len(r["slowest"]) == 3


def test_online_and_hotspot():
    def dead(addr, timeout):
        raise OSError("down")

    assert not reliax.online(connect=dead)

    class Ok:
        def close(self):
            pass

    assert reliax.online(connect=lambda a, timeout: Ok())
    assert reliax.hotspot_command('Můj "telefon" & x') == 'netsh wlan connect name="Můj telefon  x"'


async def test_hotspot_tick(rt, monkeypatch):
    rt.cfg.reliax.hotspot_ssid = "Telefon"
    monkeypatch.setattr(reliax, "online", lambda: False)
    t = dt.datetime(2026, 11, 25, 10)
    await reliax.tick(rt, t)
    rt._rx_net_at = 0
    said = await reliax.tick(rt, t + dt.timedelta(minutes=1))
    assert "hotspot" in said
    monkeypatch.setattr(reliax, "online", lambda: True)
    rt._rx_net_at = 0
    await reliax.tick(rt, t + dt.timedelta(minutes=2))
    assert any(n["title"] == "Internet je zpět" for n in rt.notices)


async def test_daily_weekly_monthly(rt, monkeypatch):
    monkeypatch.setattr(reliax, "sntp_offset", lambda *a, **k: 45.0)
    monkeypatch.setattr(reliax, "integrity", lambda rt_: {"ok": True})
    monday_first = dt.datetime(2026, 6, 1, 9, 40)                              # a Monday and the 1st
    said = await reliax.tick(rt, monday_first)
    assert "clock" in said and "month" in said
    assert reliax.db(rt).one("SELECT score FROM rx_score WHERE day='2026-06-01'")["score"] <= 90
    reliax.event(rt, "crash", "Proaktivita+", "x")
    rt.db.exec("DELETE FROM kv WHERE k='rx_week'")
    assert "week" in await reliax.tick(rt, monday_first + dt.timedelta(minutes=1))


def test_models_changed(rt):
    assert reliax.models_changed(rt) == []
    p = next(p for p in rt.cfg.brain.providers if p.enabled) if any(p.enabled for p in rt.cfg.brain.providers) else None
    if p is None:
        pytest.skip("no provider")
    p.model = "novy-model-9"
    assert reliax.models_changed(rt) == [p.id] and reliax.models_changed(rt) == []


async def test_care_kit(rt):
    r = await tools.call("care_kit", {"action": "score"}, rt)
    assert r.ok and "/100" in r.summary
    r = await tools.call("care_kit", {"action": "config_check"}, rt)
    assert r.ok
    r = await tools.call("care_kit", {"action": "safe_mode", "text": "on"}, rt)
    from jarvis import paths

    assert r.ok and (paths.data_dir() / "SAFE_MODE").exists()
    r = await tools.call("care_kit", {"action": "safe_mode", "text": "vypni"}, rt)
    assert not (paths.data_dir() / "SAFE_MODE").exists()
    spec = tools.REGISTRY["care_kit"]
    assert spec.danger_if({"action": "settings_restore"}) and not spec.danger_if({"action": "score"})


# ------------------------------------------------------------------ (456) chaos: random failures must not crash anything
CHAOS = [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError]


def chaos_transport(seed: int):
    rnd = random.Random(seed)

    def h(req: httpx.Request):
        r = rnd.random()
        if r < 0.4:
            raise rnd.choice(CHAOS)("chaos", request=req)
        if r < 0.6:
            return httpx.Response(rnd.choice([500, 502, 503, 429]), text="chaos")
        if r < 0.8:
            return httpx.Response(200, text="{nevalidní json <x>")
        return httpx.Response(200, content=b"\x00\xff garbage")

    return httpx.MockTransport(h)


@pytest.mark.parametrize("seed", range(6))
async def test_chaos_services(rt, seed, monkeypatch):
    """The 3.20 kits that reach the internet answer with a ToolResult (never an exception) under random failures."""
    from jarvis import connectors, linkx

    monkeypatch.setattr(linkx, "need", lambda cid: None)
    monkeypatch.setattr(linkx, "value", lambda cid, f: "x" if f != "url" else "http://chaos.local")
    monkeypatch.setattr(connectors, "configured", lambda cid: True)
    connectors.TRANSPORT = chaos_transport(seed)
    try:
        for action, args in (("warnings", {"text": "Brno"}), ("media", {}), ("nas", {}), ("databox", {}), ("school", {"text": "známky"}),
                             ("youtube", {}), ("rss", {})):
            rt.cfg.linkx.rss = ["http://chaos.local/feed"]
            rt.cfg.linkx.youtube = ["UCabcdefghijklmnopqrstuv"]
            r = await tools.call("link_kit", {"action": action, **args}, rt)
            assert isinstance(r.summary, str), action
    finally:
        connectors.TRANSPORT = None


async def test_chaos_ticks(rt, monkeypatch):
    """The minute loop survives failing parts: every 3.20 tick under a broken network and broken platform calls."""
    from jarvis import connectors

    connectors.TRANSPORT = chaos_transport(7)

    def broken(*a, **k):
        raise OSError("chaos")

    monkeypatch.setattr(socket, "create_connection", broken)
    try:
        for mod in ("linkx", "syncx", "reliax", "funx", "shopx", "devx"):
            import importlib

            m = importlib.import_module(f"jarvis.{mod}")
            try:
                out = await m.tick(rt)
            except Exception as e:  # noqa: BLE001
                pytest.fail(f"{mod}.tick crashed: {e!r}")
            assert isinstance(out, list)
    finally:
        connectors.TRANSPORT = None
    _ = json
