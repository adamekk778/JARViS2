"""OMEGA wave 10 (everyday): life events, packing by forecast, best time outside, substitutes, shopping by aisle,
focus report, reading level, setup check."""
import datetime as dt

import httpx

from jarvis import everyday, tools

tools.load_builtin()


def test_life_event_timeline():
    p = everyday.life_event("Stěhujeme se", dt.date(2026, 12, 1), today=dt.date(2026, 11, 1))
    assert p["event"] == "stěhování"
    first = p["steps"][0]
    assert first["date"] == "2026-10-20" and first["late"] and p["late"] == 1
    assert any(s["text"].startswith("Změna trvalého pobytu") and s["date"] == "2026-12-04" for s in p["steps"])


async def test_life_event_tool_to_list(rt):
    when = (dt.date.today() + dt.timedelta(days=60)).isoformat()
    r = await tools.call("life_event_plan", {"event": "narozeniny", "date": when, "to_list": "oslava"}, rt)
    from jarvis.tools.list_tools import items_of

    assert r.ok and len(items_of(rt, "oslava")) == 5
    assert not (await tools.call("life_event_plan", {"event": "let na Mars", "date": when}, rt)).ok


def fake_forecast(req):
    if "geocoding" in str(req.url):
        return httpx.Response(200, json={"results": [{"name": "Split", "latitude": 43.5, "longitude": 16.4}]})
    base = dt.datetime.now().replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    hours = [base + dt.timedelta(hours=i) for i in range(48)]
    return httpx.Response(200, json={
        "daily": {"time": [(dt.date.today() + dt.timedelta(days=i)).isoformat() for i in range(3)], "weather_code": [0, 61, 0],
                  "temperature_2m_max": [29, 22, 31], "temperature_2m_min": [5, 14, 18], "precipitation_probability_max": [10, 80, 0],
                  "precipitation_sum": [0, 12, 0], "wind_speed_10m_max": [10, 40, 5], "uv_index_max": [7, 3, 8]},
        "hourly": {"time": [h.isoformat(timespec="minutes") for h in hours],
                   "temperature_2m": [12 + (i % 24) / 2 for i in range(48)],
                   "precipitation_probability": [80 if i < 24 else (0 if (base + dt.timedelta(hours=i)).hour == 10 else 30) for i in range(48)],
                   "wind_speed_10m": [5] * 48}})


async def test_packing_uses_the_forecast(rt):
    rt.transport = httpx.MockTransport(fake_forecast)
    r = await tools.call("packing_list", {"destination": "Split", "nights": 4, "activities": "moře", "abroad": True, "to_list": "kufr"}, rt)
    items = r.data["items"]
    for x in ("spodní prádlo ×5", "plavky", "deštník nebo pláštěnka", "opalovací krém", "teplá bunda", "adaptér do zásuvky", "kraťasy"):
        assert x in items, x
    assert "déšť až 80 %" in r.summary


async def test_best_time_outside(rt):
    rt.transport = httpx.MockTransport(fake_forecast)
    r = await tools.call("best_time_outside", {"activity": "kolo", "city": "Split"}, rt)
    assert r.ok and r.data["best_hours"][0]["rain_pct"] == 0 and dt.datetime.fromisoformat(r.data["best_hours"][0]["time"]).hour == 10


async def test_substitutes_and_aisles(rt):
    assert "mletého lnu" in (await tools.call("ingredient_substitute", {"ingredient": "vejce"}, rt)).summary
    assert not (await tools.call("ingredient_substitute", {"ingredient": "šafrán"}, rt)).ok
    from jarvis.tools.list_tools import add_items

    add_items(rt, "nákup", ["rohlíky", "mléko", "jablka", "toaletní papír", "kuřecí prsa", "kafe", "něco divného"])
    r = await tools.call("shopping_by_aisle", {}, rt)
    assert list(r.data) == ["Ovoce a zelenina", "Pečivo", "Mléčné a vejce", "Maso a uzeniny", "Trvanlivé", "Drogerie", "Ostatní"]


async def test_focus_report(rt):
    d = dt.date.today().isoformat()
    for app, h, s in (("Microsoft Word", 9, 3600), ("Excel", 10, 1800), ("YouTube - Chrome", 20, 1800), ("Steam", 21, 1200), ("Outlook", 9, 600)):
        rt.db.exec("INSERT INTO app_usage VALUES (?,?,?) ON CONFLICT(day, app) DO UPDATE SET seconds=seconds+excluded.seconds", (d, app, s))
        rt.db.exec("INSERT INTO app_hours VALUES (?,?,?,?)", (d, h, app, s))
    r = await tools.call("focus_report", {}, rt)
    assert r.data["minutes"] == {"práce": 90, "zábava": 30, "hry": 20, "komunikace": 10}
    assert r.data["focus_pct"] == 60 and r.data["best_hour"] == 9


def test_readability():
    easy = everyday.readability("Pes běží. Kočka spí. Je hezky.")
    hard = everyday.readability("Implementace administrativních mechanismů vyžaduje systematickou koordinaci "
                                "interdisciplinárních kompetencí odpovědných institucí a transparentní komunikaci.")
    assert easy["level"] == "snadný" and hard["level"] == "náročný"


async def test_setup_check(rt):
    r = await tools.call("setup_check", {}, rt)
    keys = {i["key"]: i["ok"] for i in r.data}
    assert set(keys) >= {"ai", "name", "city", "voice", "mail", "calendar", "phone", "home", "backup"} and not keys["mail"]
    rt.update_config({"general": {"user_name": "Adam"}})
    assert {i["key"]: i["ok"] for i in (await tools.call("setup_check", {}, rt)).data}["name"]
