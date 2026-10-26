"""OMEGA wave 23 (smart home): rooms and room control, energy from history, batteries, firmware, logbook – against a
scripted Home Assistant – and the automation simulator against JARVIS's real rule engine."""
import json

import httpx
import pytest

from jarvis import secrets, tools

tools.load_builtin()

STATES = [
    {"entity_id": "light.obyvak_strop", "state": "on", "attributes": {"friendly_name": "Strop obývák"}},
    {"entity_id": "light.obyvak_lampa", "state": "off", "attributes": {"friendly_name": "Lampa obývák"}},
    {"entity_id": "media_player.tv", "state": "playing", "attributes": {"friendly_name": "Televize"}},
    {"entity_id": "lock.vchod", "state": "locked", "attributes": {"friendly_name": "Vchod", "battery_level": 12}},
    {"entity_id": "sensor.teplota_obyvak", "state": "21.5", "attributes": {"friendly_name": "Teplota obývák", "unit_of_measurement": "°C"}},
    {"entity_id": "sensor.cidlo_okno_battery", "state": "64", "attributes": {"friendly_name": "Čidlo okno Battery", "device_class": "battery"}},
    {"entity_id": "binary_sensor.kour_battery_low", "state": "on", "attributes": {"friendly_name": "Hlásič kouře", "device_class": "battery"}},
    {"entity_id": "sensor.pracka_energy", "state": "120.5", "attributes": {"friendly_name": "Pračka", "unit_of_measurement": "kWh", "device_class": "energy"}},
    {"entity_id": "sensor.bojler_energy", "state": "5000", "attributes": {"friendly_name": "Bojler", "unit_of_measurement": "Wh", "device_class": "energy"}},
    {"entity_id": "update.zigbee_hub", "state": "on", "attributes": {"title": "Zigbee hub", "installed_version": "1.2", "latest_version": "1.4", "release_summary": "opravy"}},
    {"entity_id": "update.core", "state": "off", "attributes": {"title": "Home Assistant Core", "installed_version": "2026.10.1", "latest_version": "2026.10.1"}},
]
AREAS = {"obyvak": {"name": "Obývák", "entities": ["light.obyvak_strop", "light.obyvak_lampa", "media_player.tv", "sensor.teplota_obyvak"]},
         "predsin": {"name": "Předsíň", "entities": ["lock.vchod"]}}


@pytest.fixture
def ha(rt, monkeypatch):
    calls = []

    def handler(req):
        p = req.url.path
        if p == "/api/states":
            return httpx.Response(200, json=STATES)
        if p == "/api/template":
            assert "areas()" in json.loads(req.content)["template"]
            return httpx.Response(200, text=json.dumps(AREAS))
        if p.startswith("/api/history/period/"):
            ids = req.url.params["filter_entity_id"].split(",")
            assert set(ids) == {"sensor.pracka_energy", "sensor.bojler_energy"}
            return httpx.Response(200, json=[
                [{"entity_id": "sensor.pracka_energy", "state": s, "last_changed": d} for s, d in
                 (("100", "2026-10-20T00:00"), ("101.5", "2026-10-21T00:00"), ("unavailable", "2026-10-21T10:00"), ("103", "2026-10-22T00:00"))],
                [{"entity_id": "sensor.bojler_energy", "state": s, "last_changed": d} for s, d in
                 (("9000", "2026-10-20T00:00"), ("12000", "2026-10-21T00:00"), ("1000", "2026-10-22T00:00"))]])     # reset to 0 and counted 1000
        if p.startswith("/api/logbook/"):
            ent = req.url.params.get("entity")
            ev = [{"when": "2026-10-26T07:01:00", "name": "Vchod", "entity_id": "lock.vchod", "state": "unlocked"},
                  {"when": "2026-10-26T07:02:00", "name": "Strop obývák", "entity_id": "light.obyvak_strop", "message": "turned on"}]
            return httpx.Response(200, json=[e for e in ev if not ent or e["entity_id"] == ent])
        if p.startswith("/api/services/"):
            calls.append((p, json.loads(req.content)))
            return httpx.Response(200, json=[])
        return httpx.Response(404)
    rt.transport = httpx.MockTransport(handler)
    monkeypatch.setattr(secrets, "get", lambda k: "tok" if k == "ha_token" else "")
    rt.update_config({"home": {"url": "http://ha.local:8123"}})
    return calls


async def test_not_configured(rt):
    assert "Nastavení → Domov" in (await tools.call("home_rooms", {}, rt)).summary


async def test_rooms_and_room_control(rt, ha):
    r = await tools.call("home_rooms", {}, rt)
    ob = next(x for x in r.data if x["name"] == "Obývák")
    assert ob["lights_on"] == 1 and ob["temperature"] == "21.5" and "Obývák: 4 zařízení, svítí 1, 21.5 °C" in r.summary
    r = await tools.call("room_control", {"room": "obyvak", "action": "off"}, rt)
    assert [c[0] for c in ha] == ["/api/services/light/turn_off"] * 2 and r.data["room"] == "Obývák"
    ha.clear()
    await tools.call("room_control", {"room": "Obývák", "action": "off", "what": "all"}, rt)
    assert "/api/services/media_player/turn_off" in [c[0] for c in ha]
    r = await tools.call("room_control", {"room": "předsíň", "action": "off", "what": "all"}, rt)
    assert not r.ok                                                                  # a lock is never switched this way
    assert not (await tools.call("room_control", {"room": "garáž", "action": "on"}, rt)).ok


async def test_energy_batteries_firmware_history(rt, ha):
    r = await tools.call("home_energy", {"days": 7, "price_kwh": 5}, rt)
    m = {x["name"]: x for x in r.data["meters"]}
    assert m["Pračka"]["kwh"] == 3.0 and m["Bojler"]["kwh"] == 4.0 and r.data["total_kwh"] == 7.0 and "35 Kč" in r.summary
    r = await tools.call("home_batteries", {}, rt)
    assert [x["name"] for x in r.data if x["low"]] == ["Hlásič kouře", "Vchod"] and "Čidlo okno" in [x["name"] for x in r.data]
    r = await tools.call("home_firmware", {}, rt)
    assert "Zigbee hub 1.2 → 1.4" in r.summary and len(r.data) == 2
    r = await tools.call("home_history", {"hours": 12}, rt)
    assert "07:01 Vchod unlocked" in r.summary
    r = await tools.call("home_history", {"device": "strop obývák"}, rt)
    assert len(r.data) == 1 and r.data[0]["entity"] == "light.obyvak_strop"


async def test_simulator(rt):
    rt.update_config({"automations": {"items": [
        {"id": "a", "name": "Ranní budíček", "trigger": {"type": "time", "value": "07:00", "days": [0, 1, 2, 3, 4]}, "steps": [{"say": "Dobré ráno"}]},
        {"id": "b", "name": "Šéf píše", "trigger": {"type": "mail", "value": "šéf", "text": "porada"}, "steps": [{"say": "Mail od {sender}: {subject}"}]},
        {"id": "c", "name": "Slabá baterie", "trigger": {"type": "battery", "value": "20"}, "steps": [{"say": "Baterie {percent} %"}]},
        {"id": "d", "name": "Spotify", "trigger": {"type": "app_open", "value": "spotify"}, "steps": [{"say": "Hudba"}]},
        {"id": "e", "name": "Taky Spotify", "trigger": {"type": "app_open", "value": "spoti"}, "steps": [{"say": "Ještě jednou"}]},
        {"id": "f", "name": "Odchod", "trigger": {"type": "away", "value": "30"}, "steps": [{"say": "Zamykám"}]},
        {"id": "g", "name": "Vypnuté", "enabled": False, "trigger": {"type": "boot"}, "steps": [{"say": "x"}]}]}})
    r = await tools.call("simulate_automations", {"events": "po 7:00; so 7:00; e-mail od Šéf Novák: Porada v 10; baterie 15; otevřu Spotify; odejdu 20; start"}, rt)
    ev = r.data["events"]
    assert [h["rule"] for h in ev[0]["rules"]] == ["Ranní budíček"] and ev[1]["rules"] == []
    assert ev[2]["rules"][0]["steps"] == ["Řekne: „Mail od Šéf Novák: Porada v 10“"] and ev[3]["rules"][0]["steps"] == ["Řekne: „Baterie 15 %“"]
    assert r.data["multiple"] == [{"n": 5, "rules": ["Spotify", "Taky Spotify"]}] and r.data["never_fired"] == ["Odchod"]
    assert ev[6]["rules"] == []                                                      # the disabled rule never fires
    assert not (await tools.call("simulate_automations", {"events": "přistane UFO"}, rt)).ok
