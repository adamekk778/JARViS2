"""3.5 smart home (Home Assistant REST): find devices by spoken names, control them, confirm locks and gates."""
import json

import httpx
import pytest

from jarvis import secrets, tools
from jarvis.home import match, risky

STATES = [
    {"entity_id": "light.obyvak", "state": "on", "attributes": {"friendly_name": "Světlo obývák", "brightness": 128}},
    {"entity_id": "light.loznice", "state": "off", "attributes": {"friendly_name": "Lampa ložnice"}},
    {"entity_id": "switch.kavovar", "state": "off", "attributes": {"friendly_name": "Kávovar"}},
    {"entity_id": "climate.topeni", "state": "heat", "attributes": {"friendly_name": "Topení", "temperature": 21, "current_temperature": 20.5}},
    {"entity_id": "sensor.teplota_loznice", "state": "19.8", "attributes": {"friendly_name": "Teplota ložnice", "unit_of_measurement": "°C"}},
    {"entity_id": "lock.vchod", "state": "locked", "attributes": {"friendly_name": "Vchodové dveře"}},
    {"entity_id": "cover.garaz", "state": "closed", "attributes": {"friendly_name": "Garážová vrata"}},
    {"entity_id": "scene.kino", "state": "scening", "attributes": {"friendly_name": "Kino"}},
]


@pytest.fixture
def ha(rt, monkeypatch):
    calls = []

    def handler(req: httpx.Request):
        assert req.headers["Authorization"] == "Bearer tok"
        if req.url.path == "/api/states":
            return httpx.Response(200, json=STATES)
        calls.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json=[])

    rt.transport = httpx.MockTransport(handler)
    monkeypatch.setattr(secrets, "get", lambda k: "tok" if k == "ha_token" else "")
    rt.update_config({"home": {"url": "http://ha.local:8123"}})
    return calls


async def test_not_configured_explains_how(rt):
    r = await tools.call("home_control", {"target": "obývák", "action": "on"}, rt)
    assert not r.ok and "Nastavení → Domov" in r.summary


async def test_devices_and_states_in_czech(rt, ha):
    r = await tools.call("home_devices", {"query": "ložnice"}, rt)
    assert r.ok and "Lampa ložnice: vypnuto" in r.summary and "Teplota ložnice: 19.8 °C" in r.summary
    r = await tools.call("home_devices", {"domain": "climate"}, rt)
    assert r.summary == "Topení: topí, 20.5 °C → 21 °C"


async def test_control_by_spoken_names(rt, ha):
    assert (await tools.call("home_control", {"target": "obývák", "action": "off"}, rt)).summary == "Světlo obývák: vypínám."
    assert (await tools.call("home_control", {"target": "lampa v ložnici", "action": "set", "value": 40}, rt)).ok
    assert (await tools.call("home_control", {"target": "topení", "action": "set", "value": 22.5}, rt)).summary == "Topení: nastavuji 22.5 °C."
    assert (await tools.call("home_control", {"target": "všechna světla", "action": "off"}, rt)).ok
    assert (await tools.call("home_scene", {"name": "kino"}, rt)).summary == "Spouštím Kino."
    assert ha == [("/api/services/light/turn_off", {"entity_id": "light.obyvak"}),
                  ("/api/services/light/turn_on", {"entity_id": "light.loznice", "brightness_pct": 40}),
                  ("/api/services/climate/set_temperature", {"entity_id": "climate.topeni", "temperature": 22.5}),
                  ("/api/services/light/turn_off", {"entity_id": "all"}),
                  ("/api/services/scene/turn_on", {"entity_id": "scene.kino"})]


async def test_locks_and_gates_always_ask(rt, ha):
    spec = tools.REGISTRY["home_control"]
    assert not tools.is_dangerous(spec, {"target": "obývák", "action": "on"}, [], [], rt)
    assert tools.is_dangerous(spec, {"target": "vchod", "action": "unlock"}, [], [], rt)
    assert tools.is_dangerous(spec, {"target": "garáž", "action": "open"}, [], [], rt)
    await rt.home.states()                                  # once JARVIS has seen the devices…
    assert tools.is_dangerous(spec, {"target": "vrata", "action": "toggle"}, [], [], rt)   # …"vrata" is the garage
    assert not tools.is_dangerous(spec, {"target": "vchod", "action": "lock"}, [], [], rt)
    r = await tools.call("home_control", {"target": "vchodové dveře", "action": "off"}, rt)
    assert "výslovně" in r.summary and not any("lock" in c[0] for c in ha)      # "off" never unlocks a lock


def test_matching_and_risk_words():
    from jarvis.home import short

    items = [short(e) for e in STATES]
    assert match(items, "kavovar")[0]["id"] == "switch.kavovar"
    assert match(items, "obyvak")[0]["id"] == "light.obyvak"
    assert match(items, "lampa lozni")[0]["id"] == "light.loznice"
    assert risky("unlock", "cokoli") and risky("open", "Garážová vrata") and not risky("on", "Lampa")
