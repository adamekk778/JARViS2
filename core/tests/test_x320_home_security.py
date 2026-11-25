"""3.20 Domácnost+ (161–180) a Bezpečnost+ (181–200)."""
from __future__ import annotations

import datetime as dt
import json
import random
import time
from pathlib import Path

import pytest

from jarvis import homex, secx, tools


def S(eid: str, state: str, name: str = "", cls: str = "", unit: str = "", **attrs) -> dict:
    a = {"friendly_name": name or eid, **attrs}
    if cls:
        a["device_class"] = cls
    if unit:
        a["unit_of_measurement"] = unit
    return {"entity_id": eid, "state": state, "attributes": a}


class Calls:
    def __init__(self) -> None:
        self.log: list[tuple[str, str, dict]] = []

    async def __call__(self, domain: str, svc: str, data: dict) -> None:
        self.log.append((domain, svc, data))


# ------------------------------------------------------------------ (161) okno a topení
async def test_window_turns_heating_off_and_back(rt):
    calls = Calls()
    raw = [S("binary_sensor.okno_loznice", "on", "Okno ložnice", "window"),
           S("climate.topeni_loznice", "heat", "Topení ložnice", current_temperature=21, temperature=21),
           S("climate.topeni_obyvak", "heat", "Topení obývák")]
    st = homex.norm(raw)
    assert homex.pair(st[0], [e for e in st if e["domain"] == "climate"])["id"] == "climate.topeni_loznice"
    t0 = 1000.0
    assert await homex.window_heating(rt, st, t0, calls) == []                   # just opened: wait 2 minutes
    out = await homex.window_heating(rt, st, t0 + 130, calls)
    assert "vypnul jsem Topení ložnice" in out[0] and calls.log[-1] == ("climate", "set_hvac_mode", {"entity_id": "climate.topeni_loznice", "hvac_mode": "off"})
    raw[0]["state"], raw[1]["state"] = "off", "off"
    out = await homex.window_heating(rt, homex.norm(raw), t0 + 400, calls)
    assert "zase topí" in out[0] and calls.log[-1][2]["hvac_mode"] == "heat"


# ------------------------------------------------------------------ (162, 179) zapomenuté spotřebiče a sporák
def test_forgotten_plugs_and_stove(rt):
    raw = [S("sensor.zehlicka_power", "1200", "Žehlička", "power", "W"), S("sensor.sporak_power", "1800", "Sporák", "power", "W"),
           S("binary_sensor.pohyb_kuchyn", "off", "Pohyb kuchyň", "motion"), S("switch.zehlicka", "on", "Žehlička")]
    st = homex.norm(raw)
    t0 = 10_000.0
    assert homex.forgotten(rt, st, True, t0) == []
    out = homex.forgotten(rt, st, True, t0 + 31 * 60)
    assert any(f["kind"] == "power" and "Žehlička" in f["text"] for f in out)
    assert homex.switch_for("sensor.zehlicka_power", st)["id"] == "switch.zehlicka"
    out = homex.forgotten(rt, st, False, t0 + 46 * 60)
    assert any(f["kind"] == "stove" and "Sporák" in f["text"] for f in out)
    assert not [f for f in homex.forgotten(rt, st, False, t0 + 47 * 60) if f["kind"] == "stove"]      # once per 30 min


# ------------------------------------------------------------------ (165) prádlo, (166) vzduch
def test_washer_and_air(rt):
    t = 0.0
    run = homex.norm([S("sensor.pracka_power", "450", "Pračka", "power", "W")])
    idle = homex.norm([S("sensor.pracka_power", "1", "Pračka", "power", "W")])
    assert homex.washer(rt, run, t) == [] and homex.washer(rt, run, t + 310) == []
    assert homex.washer(rt, idle, t + 400) == []
    assert homex.washer(rt, idle, t + 590) == ["Prádlo je hotové – pračka doprala."]
    assert homex.washer(rt, idle, t + 700) == []
    air = homex.norm([S("sensor.co2_pracovna", "1450", "Pracovna", "carbon_dioxide", "ppm"),
                      S("sensor.vlhkost_koupelna", "72", "Koupelna vlhkost", "humidity", "%")])
    out = homex.air(rt, air, 5000)
    assert any("1450 ppm" in x for x in out) and any("plíseň" in x for x in out)
    assert homex.air(rt, air, 5100) == []                                       # not again within hours


# ------------------------------------------------------------------ (167) noční světlo, (168) simulace
async def test_night_light_and_presence_simulation(rt):
    calls = Calls()
    rt.cfg.homex.night_light = "23:00-06:00"
    st = homex.norm([S("binary_sensor.pohyb_chodba", "on", "Pohyb chodba", "motion"), S("light.chodba", "off", "Světlo chodba")])
    night = dt.datetime(2026, 11, 25, 2, 0)
    assert await homex.night_light(rt, st, 100, night, calls) == ["light.chodba"]
    assert calls.log[-1] == ("light", "turn_on", {"entity_id": "light.chodba", "brightness_pct": 8})
    await homex.night_light(rt, st, 230, night, calls)
    assert calls.log[-1] == ("light", "turn_off", {"entity_id": "light.chodba"})
    assert await homex.night_light(rt, st, 300, dt.datetime(2026, 11, 25, 14, 0), calls) == []     # by day: nothing
    rt.cfg.day.vacation_until = "2026-11-30"
    lights = homex.norm([S(f"light.l{i}", "off", f"Světlo {i}") for i in range(4)])
    rnd = random.Random(1)
    evening = dt.datetime(2026, 11, 25, 19, 0)
    changes = []
    for _ in range(60):
        changes += await homex.simulate(rt, lights, True, evening, calls, rnd)
    assert changes and len(homex.state(rt).sim_on) <= 3
    await homex.simulate(rt, lights, True, dt.datetime(2026, 11, 25, 23, 30), calls, rnd)
    assert not homex.state(rt).sim_on                                            # off for the night
    assert await homex.simulate(rt, lights, False, evening, calls, rnd) == []     # someone is home


# ------------------------------------------------------------------ (169) voda, (178) garáž
def test_leak_and_garage(rt):
    st = homex.norm([S("binary_sensor.unik_pracka", "on", "Únik pod pračkou", "moisture"),
                     S("cover.garaz", "open", "Garážová vrata", "garage")])
    assert "Únik vody: Únik pod pračkou" in homex.leaks(rt, st, 100)[0]
    assert homex.leaks(rt, st, 200) == []
    assert homex.garage(rt, st, 0) == []
    g = homex.garage(rt, st, 11 * 60)
    assert g and g[0]["cover"] and "otevřená už 11 min" in g[0]["text"]


# ------------------------------------------------------------------ (164) teploty, (170) mapa, (174) zámky, (176) profily
def test_temps_map_locks_profiles(rt):
    raw = [S("climate.loznice", "heat", "Ložnice", current_temperature=23.5, temperature=21, hvac_action="heating"),
           S("climate.obyvak", "heat", "Obývák", current_temperature=21, temperature=25),
           S("binary_sensor.okno_obyvak", "on", "Okno obývák", "window"),
           S("lock.vchod", "unlocked", "Vchodové dveře"), S("light.obyvak", "on", "Světlo obývák"),
           S("sensor.teplota_detsky", "20.4", "Teplota dětský", "temperature", "°C")]
    st = homex.norm(raw)
    r = homex.room_temps(st, away=True)
    tips = " ".join(r["tips"])
    assert "přetápí" in tips and "otevřeném okně" in tips and "útlum na 17" in tips and "6 % úspora" in tips
    m = homex.house_map(st, positions={"lock.vchod": [10, 20]})
    assert any(i["alert"] for room in m["rooms"] for i in room["items"]) and m["pins"][0]["x"] == 10
    page = homex.map_html({"rooms": [{"name": "<b>x</b>", "items": [{"name": "<i>", "value": "1", "on": True, "alert": False}]}], "pins": []})
    assert "<b>x</b>" not in page and "&lt;b&gt;" in page
    assert homex.locks(st) == {"ok": False, "text": "Ne – Vchodové dveře je odemčený."}
    raw[3]["state"] = "locked"
    assert homex.locks(homex.norm(raw))["ok"] is True
    rt.cfg.homex.profiles = {"Jana": {"lights": {"light.obyvak": 40, "light.loznice": 0}, "climate": {"climate.obyvak": 22}}}
    calls = homex.profile_actions(rt, "jana")
    assert ("light", "turn_on", {"entity_id": "light.obyvak", "brightness_pct": 40}) in calls
    assert ("light", "turn_off", {"entity_id": "light.loznice"}) in calls and ("climate", "set_temperature", {"entity_id": "climate.obyvak", "temperature": 22.0}) in calls
    assert homex.profile_actions(rt, "Petr") == []


# ------------------------------------------------------------------ (171) baterie, (172) slunce, (173) zalévání, (175) vysavač, (180)
async def test_batteries_solar_watering_vacuum_cameras(rt):
    today = dt.date(2026, 11, 25)
    for k in range(10):
        homex.batt_record(rt, [{"id": "sensor.okno_batt", "level": 60 - k * 3}], today - dt.timedelta(days=9 - k))
    days = homex.batt_forecast(rt, "sensor.okno_batt", today)
    assert days is not None and 6 <= days <= 9                                   # 33 % now, −3 % a day → ~7 days to 10 %
    calls = Calls()
    rt.cfg.homex.solar_entity, rt.cfg.homex.solar_loads = "sensor.pretok", ["switch.pracka"]
    sun = homex.norm([S("sensor.pretok", "2400", "Přetok", "power", "W")])
    noon = dt.datetime(2026, 6, 1, 12, 0)
    assert await homex.solar(rt, sun, 0, noon, calls) == ""
    assert "2400 W" in await homex.solar(rt, sun, 601, noon, calls) and calls.log[-1] == ("switch", "turn_on", {"entity_id": "switch.pracka"})
    assert await homex.solar(rt, sun, 2000, noon, calls) == ""                    # once a day
    rt.cfg.homex.watering_entity = "switch.zavlaha"
    day = dt.date(2026, 6, 2)
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('px_weather', ?)", (json.dumps({"ts": time.time(), "daily": {
        "time": [day.isoformat()], "precipitation_probability_max": [80]}}),))
    assert "vynechám" in await homex.watering(rt, dt.datetime(2026, 6, 2, 6, 0), calls)
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('px_weather', ?)", (json.dumps({"ts": time.time(), "daily": {
        "time": ["2026-06-03", "2026-06-04"], "precipitation_probability_max": [10, 20]}}),))
    assert "Zalévám 15 min" in await homex.watering(rt, dt.datetime(2026, 6, 3, 6, 0), calls)
    assert await homex.watering_off(rt, time.time() + 16 * 60, calls) and calls.log[-1][1] == "turn_off"
    rt.cfg.homex.vacuum_days = [2]
    vac = homex.norm([S("vacuum.robot", "docked", "Robot")])
    wed = dt.datetime(2026, 11, 25, 10, 0)
    assert await homex.vacuum(rt, vac, True, 0, wed, calls) == ""
    assert "Robot jde uklízet" in await homex.vacuum(rt, vac, True, 16 * 60, wed, calls)
    rt.cfg.homex.privacy_cameras = ["switch.kamera_obyvak"]
    assert "vypnul" in await homex.camera_privacy(rt, True, calls) and calls.log[-1][1] == "turn_off"
    assert await homex.camera_privacy(rt, True, calls) == ""
    assert "hlídají" in await homex.camera_privacy(rt, False, calls)


# ------------------------------------------------------------------ (177) Matter
async def test_matter_client():
    sent: list[dict] = []

    class WS:
        def __init__(self) -> None:
            self.q = [json.dumps({"server_version": "6"})]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def recv(self):
            return self.q.pop(0)

        async def send(self, m):
            msg = json.loads(m)
            sent.append(msg)
            result = [{"node_id": 7, "available": True, "attributes": {"0/40/5": "Lampa", "1/6/0": True}}] if msg["command"] == "get_nodes" else None
            self.q.append(json.dumps({"message_id": msg["message_id"], "result": result}))

    m = homex.Matter("ws://x:5580/ws", connect=lambda url: WS())
    nodes = await m.nodes()
    assert nodes == [{"node": 7, "name": "Lampa", "vendor": "", "available": True, "on": True}]
    await m.onoff(7, False)
    assert sent[-1]["command"] == "device_command" and sent[-1]["args"]["command_name"] == "Off" and sent[-1]["args"]["cluster_id"] == 6
    with pytest.raises(ValueError):
        await m.commission("ahoj")


# ------------------------------------------------------------------ the house tick end to end
async def test_home_tick(rt):
    calls = Calls()

    class Home:
        async def service(self, d, s, data):
            await calls(d, s, data)

    rt.home = Home()
    raw = [S("binary_sensor.unik", "on", "Únik koupelna", "moisture")]
    said = await homex.tick(rt, now=1000, clock=dt.datetime(2026, 11, 25, 12, 0), raw=raw)
    assert any("Únik vody" in s for s in said)


# ================================================================== Bezpečnost+
def test_permission_audit(rt):
    rt.cfg.phone_link.remote_desktop = True
    a = secx.permission_audit(rt)
    assert any(r["perm"] == "shell" for r in a["rows"]) and any("Vzdálená plocha" in t for t in a["tips"])
    assert "JARVIS teď smí" in secx.audit_text(a)


async def test_canary_files(rt, tmp_path):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    made = secx.canary_create(rt, tmp_path, "http://127.0.0.1:8765")
    assert len(made) == 2 and all(Path(m["path"]).exists() for m in made)
    html = (tmp_path / secx.CANARY_NAMES["html"]).read_text(encoding="utf-8")
    assert f"/canary/{made[0]['token']}.png" in html
    app = create_app(rt, manage_runtime=False)
    out = TestClient(app, client=("192.168.1.50", 5000))
    r = out.get(f"/canary/{made[0]['token']}.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert rt.notices[0]["title"] == "Návnada spuštěna" and "192.168.1.50" in rt.notices[0]["body"]
    assert not secx.canary_hit(rt, "neni")


def test_twofa_and_keys_backup(rt, tmp_path):
    secx.twofa_mark(rt, "Google", True)
    r = secx.twofa_report(rt)
    assert "Google (Gmail, Disk)" in r["done"] and any(m["service"] == "Seznam.cz" for m in r["missing"])
    p = secx.keys_backup(tmp_path / "usb" / "klice.jvk", "dlouhe-heslo-123", {"anthropic": "sk-ant-xyz", "groq": "gsk_1"})
    assert "sk-ant" not in p.read_text(encoding="utf-8")
    assert secx.keys_restore(p, "dlouhe-heslo-123") == {"anthropic": "sk-ant-xyz", "groq": "gsk_1"}
    with pytest.raises(ValueError):
        secx.keys_restore(p, "spatne-heslo-000")
    with pytest.raises(ValueError):
        secx.keys_backup(tmp_path / "x.jvk", "kratke", {})


def test_scam_detection(rt):
    assert secx.scam_score("Vaše zásilka čeká. Doplaťte clo 49 Kč: https://ceska-posta.top/x")["level"] == "high"
    assert secx.scam_score("Ahoj mami, ztratil jsem telefon, tohle je moje nové číslo, pošli mi peníze", "+447700900123")["level"] == "high"
    assert secx.scam_score("Zítra v 18:00 trénink, vezmi si boty")["level"] == "low"
    pushed = []
    rt.phone_push = lambda kind, **d: pushed.append((kind, d)) or True
    rt.cfg.secx.family_devices = ["Máma"]
    r = secx.on_message(rt, {"messaging": True, "title": "+420777", "text": "Váš účet byl zablokován, ověřte svůj účet ihned: https://bit.ly/x",
                             "device": "Máma"})
    assert r and pushed and "podvod" in pushed[0][1]["body"] and rt.notices[0]["title"] == "Rodina: podvodná zpráva"


async def test_stranger_second_ai_media(rt):
    assert secx.stranger_check([{"name": "host"}], ["Adam"]) == "U počítače je někdo, koho neznám."
    assert secx.stranger_check([{"name": "Adam"}, {"name": "host"}], ["adam"]) == ""
    assert secx.stranger_check([], ["Adam"]) == ""
    assert await secx.second_opinion(rt, "smaž složku") == ""                    # off unless you switch it on
    rt.cfg.secx.second_ai = True

    async def ask(desc):
        return "POZOR – maže celou složku Dokumenty\nnavíc"

    assert await secx.second_opinion(rt, "smaž Dokumenty", ask) == "POZOR – maže celou složku Dokumenty"
    before = {"kamera:Zoom"}
    now_ = secx.in_use({"capabilities": {"kamera": [{"app": "Zoom", "in_use": True}], "mikrofon": [{"app": "Discord", "in_use": True}]}})
    assert secx.media_changes(before, now_) == ["Discord teď používá mikrofon."]


def test_document_vault(rt, tmp_path, monkeypatch):
    monkeypatch.setattr(secx, "vault_dir", lambda rt: tmp_path / "vault")
    (tmp_path / "vault").mkdir()
    src = tmp_path / "pas.pdf"
    src.write_bytes(b"%PDF passport data")
    vid = secx.vault_add(rt, src, "Cestovní pas", "doklady", "pas platnost 2031")
    stored = list((tmp_path / "vault").iterdir())[0].read_bytes()
    assert b"passport" not in stored
    assert secx.vault_search(rt, "platnost pas")[0]["id"] == vid and secx.vault_search(rt, "smlouva") == []
    out = secx.vault_get(rt, vid, tmp_path / "out")
    assert out.read_bytes() == b"%PDF passport data"
    with pytest.raises(ValueError):
        secx.vault_get(rt, 999, tmp_path / "out")


def test_downloads(tmp_path):
    seen: dict[str, float] = {}
    (tmp_path / "a.exe").write_bytes(b"MZ")
    (tmp_path / "b.crdownload").write_bytes(b"x")
    now = time.time()
    assert secx.new_downloads(tmp_path, seen, now) == []                         # still being written
    got = secx.new_downloads(tmp_path, seen, now + 20)
    assert [p.name for p in got] == ["a.exe"] and secx.new_downloads(tmp_path, seen, now + 40) == []
    assert "Defender našel hrozbu" in secx.download_verdict({"path": "x/a.exe", "defender": {"threats": ["Trojan:Win32/X"]}})
    assert secx.download_verdict({"path": "x/setup.exe", "defender": {"clean": True}, "signature": "Valid|CN=Mozilla Corporation, O=Mozilla",
                                  "reasons": ["spustitelný typ souboru (.exe)"], "level": "warn"}) == \
        "setup.exe: Defender nic nenašel, podepsal Mozilla Corporation."
    assert secx.download_verdict({"path": "f.pdf.exe", "level": "bad", "reasons": ["dvojitá přípona (f.pdf.exe) – typický trik"]}).startswith("⚠")


async def test_time_lock_blocks_money_at_night(rt):
    rt.cfg.secx.time_locks = [{"what": "money", "from": "23:00", "to": "06:00"}, {"what": "shell", "from": "00:00", "to": "23:59", "days": [6]}]
    pay = next(n for n, s in tools.REGISTRY.items() if __import__("jarvis.trust", fromlist=["is_money"]).is_money(n, {}))
    assert "Platby jsou teď zamčené" in secx.time_blocks(rt, pay, {}, dt.datetime(2026, 11, 25, 23, 30))
    assert secx.time_blocks(rt, pay, {}, dt.datetime(2026, 11, 25, 12, 0)) == ""
    assert "Příkazy a kód" in secx.time_blocks(rt, "run_shell", {}, dt.datetime(2026, 11, 29, 12, 0)) or "run_shell" not in tools.REGISTRY
    assert secx.time_blocks(rt, "get_time", {}, dt.datetime(2026, 11, 25, 23, 30)) == ""


async def test_audit_chain_and_agent_hook(rt):
    secx.log_event(rt, "uživatel", "send_email: Petrovi", True, ts=100.0)
    secx.log_event(rt, "uživatel", "delete_file: x", False, ts=200.0)
    assert secx.verify_log(rt) == {"ok": True, "count": 2, "last": secx.db(rt).one("SELECT h FROM sx_audit ORDER BY n DESC")["h"]}
    rt.db.exec("UPDATE sx_audit SET approved=1 WHERE n=2")                       # someone quietly rewrites history
    assert secx.verify_log(rt)["ok"] is False and secx.verify_log(rt)["broken_at"] == 2
    from jarvis import agent_x320

    rt.db.exec("DELETE FROM sx_audit")
    agent_x320.audit_confirm(rt, {"tool": "run_shell", "description": "Spustit příkaz dir"}, True)
    assert secx.verify_log(rt)["count"] == 1


def test_one_time_secret(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    tok = secx.oneshot_create(rt, "WiFi heslo: <tajne>")
    app = create_app(rt, manage_runtime=False)
    c = TestClient(app, client=("85.1.2.3", 5000))
    page = c.get(f"/s/{tok}")
    assert page.status_code == 200 and "Zobrazit" in page.text and "tajne" not in page.text    # a link preview does not burn it
    r = c.post(f"/s/{tok}")
    assert r.status_code == 200 and "&lt;tajne&gt;" in r.text
    assert c.post(f"/s/{tok}").status_code == 410                                # gone after one reading
    with pytest.raises(ValueError):
        secx.oneshot_create(rt, "  ")


async def test_yubikey(rt):
    import base64
    import hashlib
    import hmac

    from jarvis import secrets

    key = base64.b64encode(b"0123456789abcdef0123").decode()
    sig = secx.yubico_signature({"id": "1", "otp": "x", "nonce": "n"}, key)
    assert sig == base64.b64encode(hmac.new(base64.b64decode(key), b"id=1&nonce=n&otp=x", hashlib.sha1).digest()).decode()
    otp = "cccjgjgkhcbb" + "irdrfdnlnghhfgrtnnlgedjlftrbdeut"
    assert secx.otp_public_id(otp) == "cccjgjgkhcbb" and secx.otp_public_id("123456") == ""
    assert (await secx.yubikey_verify(rt, "123"))[0] is False
    secrets.set("yubico_api", f"1:{key}")

    class Client:
        async def get(self, url, params, timeout):
            fields = {"otp": params["otp"], "nonce": params["nonce"], "status": "OK", "t": "2026-11-25T12:00:00Z0000"}
            fields["h"] = secx.yubico_signature(fields, key)

            class R:
                text = "\r\n".join(f"{k}={v}" for k, v in fields.items())
            return R()

        async def aclose(self):
            pass

    assert await secx.yubikey_verify(rt, otp, Client()) == (True, "Ověřeno klíčem.")
    rt.cfg.secx.yubikey_id = "ccccccdddddd"
    assert (await secx.yubikey_verify(rt, otp, Client()))[1] == "Tenhle YubiKey není ten tvůj."
    rt.cfg.secx.yubikey_required = True
    danger = next(n for n, s in tools.REGISTRY.items() if s.danger)
    assert secx.needs_otp(rt, danger) and not secx.needs_otp(rt, "get_time")


def test_wipe_traces(tmp_path):
    temp = tmp_path / "Temp"
    (temp / "sub").mkdir(parents=True)
    (temp / "a.tmp").write_bytes(b"x" * 100)
    (temp / "sub" / "b.tmp").write_bytes(b"y" * 50)
    targets = secx.trace_targets(home=tmp_path, env={"TEMP": str(temp), "LOCALAPPDATA": str(tmp_path / "L"), "APPDATA": str(tmp_path / "R")})
    assert targets == [{"label": "Dočasné soubory", "path": str(temp), "files": 2, "bytes": 150}]
    r = secx.wipe(targets)
    assert r["files"] == 2 and r["bytes"] == 150 and temp.is_dir() and not any(temp.iterdir())


def test_router_and_extensions(tmp_path):
    up = secx.parse_upnp("<root><device><manufacturer>TP-Link</manufacturer><modelName>Archer C6</modelName>"
                         "<softwareVersion>1.0.3</softwareVersion></device></root>")
    assert up == {"maker": "TP-Link", "model": "Archer C6", "firmware": "1.0.3"}
    rep = secx.router_report("192.168.0.1", [23, 80, 7547], up)
    tips = " ".join(rep["tips"])
    assert "Telnet" in tips and "7547" in tips and "UPnP" in tips and "1.0.3" in tips and "nešifrované HTTP" in tips
    ext = tmp_path / "Default" / "Extensions"
    (ext / "abc" / "1.0").mkdir(parents=True)
    (ext / "abc" / "1.0" / "manifest.json").write_text(json.dumps({"name": "Super Kupony", "permissions": ["cookies", "webRequest", "<all_urls>"]}))
    (ext / "def" / "2.0").mkdir(parents=True)
    (ext / "def" / "2.0" / "manifest.json").write_text(json.dumps({"name": "Tmavý režim", "permissions": ["storage"]}))
    found = secx.scan_extensions([("Chrome (Default)", ext)])
    assert found[0]["name"] == "Super Kupony" and found[0]["level"] == "high" and "<all_urls>" in found[0]["risky"]
    assert found[1]["level"] == "low"


async def test_full_check_scores(rt):
    r = await secx.full_check(rt, {"permissions": lambda: {"tips": ["Vypni X."]},
                                   "extensions": lambda: [{"name": "Kupony", "browser": "Chrome", "level": "high", "risky": ["<all_urls>"]}],
                                   "router": lambda: {"tips": ["Telnet je zapnutý.", "Výchozí heslo…"]},
                                   "twofa": lambda: {"missing": [{"service": "Seznam.cz", "how": "…"}]},
                                   "failed_logons": lambda: 9, "audit_log": lambda: {"ok": True}})
    assert r["score"] < 70 and r["findings"][0].startswith(("Rozšíření", "9 neúspěšných")) and r["summary"].startswith("Bezpečnost:")
    bad = await secx.full_check(rt, {"x": lambda: 1 / 0})
    assert bad["score"] == 100 and "error" in bad["results"]["x"]


async def test_tools_registered(rt):
    for n in ("home_kit", "security_kit"):
        assert n in tools.REGISTRY
    r = await tools.call("security_kit", {"action": "scam", "text": "Doplaťte clo za balík: https://dpd-cz.click/pay"}, rt)
    assert r.ok and r.summary.startswith("Skoro jistě podvod")
    r = await tools.call("home_kit", {"action": "temps"}, rt)
    assert not r.ok and "Home Assistant" in r.summary
    assert tools.REGISTRY["security_kit"].danger_if({"action": "wipe"}) and not tools.REGISTRY["security_kit"].danger_if({"action": "audit"})
