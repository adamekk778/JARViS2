"""3.20 Proaktivita+ (nápady 61–80)."""
from __future__ import annotations

import datetime as dt
import json
import time

from jarvis import proactx, tools


def _weather(rt, day: dt.date, hourly: dict | None = None, daily: dict | None = None):
    hours = [f"{day.isoformat()}T{h:02d}:00" for h in range(24)]
    h = {"time": hours, "temperature_2m": [18.0] * 24, "relative_humidity_2m": [55] * 24, "precipitation_probability": [5] * 24,
         "wind_speed_10m": [10] * 24, "weather_code": [1] * 24, **(hourly or {})}
    d = daily or {"time": [day.isoformat()], "temperature_2m_max": [20.0], "temperature_2m_min": [8.0],
                  "precipitation_probability_max": [10], "weather_code": [1]}
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('px_weather', ?)", (json.dumps({"ts": time.time(), "hourly": h, "daily": d}),))


# ------------------------------------------------------------------ (75) svátky
def test_holidays_and_closed_shops():
    h = proactx.cz_holidays(2027)
    assert h[dt.date(2027, 3, 26)] == "Velký pátek" and h[dt.date(2027, 3, 29)] == "Velikonoční pondělí"
    assert proactx.easter(2026) == dt.date(2026, 4, 5)
    assert proactx.shops_closed(dt.date(2026, 12, 25)) == "celý den" and proactx.shops_closed(dt.date(2026, 12, 24)) == "od 12:00"
    assert proactx.shops_closed(dt.date(2026, 5, 1)) == "" and proactx.shops_closed(dt.date(2027, 3, 29)) == "celý den"
    assert "celý den zavřené" in proactx.holiday_notice(dt.date(2026, 10, 28))
    assert "Obchody mají otevřeno" in proactx.holiday_notice(dt.date(2026, 11, 17))
    assert proactx.holiday_notice(dt.date(2026, 11, 18)) == ""


# ------------------------------------------------------------------ (61) ranní souhrn podle dne
def test_day_kind(rt):
    assert proactx.day_kind(rt, dt.date(2026, 11, 25)) == "work"
    assert proactx.day_kind(rt, dt.date(2026, 11, 28)) == "weekend"
    assert proactx.day_kind(rt, dt.date(2026, 11, 17)) == "weekend"                   # a public holiday
    rt.cfg.day.vacation_until = "2026-11-30"
    assert proactx.day_kind(rt, dt.date(2026, 11, 25)) == "vacation"
    assert proactx.morning_lead(rt, dt.date(2026, 11, 25)).startswith("Jsi na dovolené")
    rt.cfg.day.vacation_until = ""
    assert proactx.morning_lead(rt, dt.date(2026, 11, 28)).startswith("Je víkend.")
    assert proactx.morning_lead(rt, dt.date(2026, 11, 25)) == ""


# ------------------------------------------------------------------ (63) prádlo, (68) pití, (80) víkend
def test_laundry_water_weekend(rt):
    day = dt.date(2026, 6, 10)
    _weather(rt, day)
    assert proactx.laundry_window(rt, day) == "Dnes je dobré počasí na sušení prádla venku – od 8:00 do 20:00 (sucho, bez deště)."
    _weather(rt, day, {"precipitation_probability": [80] * 24})
    assert proactx.laundry_window(rt, day) == ""
    _weather(rt, dt.date.today(), daily={"time": [dt.date.today().isoformat()], "temperature_2m_max": [31.0],
                                         "temperature_2m_min": [18.0], "precipitation_probability_max": [0], "weather_code": [0]})
    assert proactx.water_minutes(rt, 90) == 59 and proactx.water_minutes(rt, 0) == 0
    thu = dt.date(2026, 6, 11)
    _weather(rt, thu, daily={"time": ["2026-06-13", "2026-06-14"], "temperature_2m_max": [24.0, 19.0], "temperature_2m_min": [12.0, 11.0],
                             "precipitation_probability_max": [10, 70], "weather_code": [1, 61]})
    assert proactx.weekend_forecast(rt, thu) == "Víkend: sobota: 12–24 °C, déšť 10 %; neděle: 11–19 °C, déšť 70 %. Na výlet vychází líp sobota."


# ------------------------------------------------------------------ (64) termíny
async def test_deadlines(rt):
    assert proactx.parse_deadline("STK do 3/2027", dt.date(2026, 11, 25))[1] == dt.date(2027, 3, 31)
    t, d, k = proactx.parse_deadline("Pojištění auta končí 15. 6.", dt.date(2026, 11, 25))
    assert (t, d, k) == ("Pojištění auta", dt.date(2027, 6, 15), "pojištění")
    r = await tools.call("day_kit", {"action": "deadline_add", "text": "Faktura Alza splatná 30. 11. 2026"}, rt)
    assert r.ok
    assert proactx.deadlines_due(rt, dt.date(2026, 11, 24)) == ["Za 6 dní končí: Faktura Alza (30. 11. 2026)."]
    assert proactx.deadlines_due(rt, dt.date(2026, 11, 25)) == []                   # said once
    assert proactx.deadlines_due(rt, dt.date(2026, 11, 29)) == ["Zítra končí: Faktura Alza (30. 11. 2026)."]
    rt.db.exec("INSERT INTO facts(text, created) VALUES ('Pas mi platí do 12. 4. 2028.', ?)", (time.time(),))
    assert proactx.deadlines_from_facts(rt) == 1 and proactx.deadlines_from_facts(rt) == 0


# ------------------------------------------------------------------ (65) nemocenský den, (66) dovolená
async def test_sick_day_and_vacation_check(rt):
    r = await tools.call("day_kit", {"action": "sick_day"}, rt)
    assert r.ok and r.data["quiet"] and rt.cfg.health.water_minutes == 60 and rt.attention.focus_until > time.time() + 7 * 3600
    items = (await tools.call("day_kit", {"action": "vacation_check"}, rt)).data
    assert items[0][0] == "?" and any("Kytky" in t for _, t in items)


# ------------------------------------------------------------------ (67) uzávěrka, (70) týden
async def test_month_close_and_week_plan(rt):
    assert proactx.last_day_of_month(dt.date(2026, 11, 30)) and not proactx.last_day_of_month(dt.date(2026, 11, 29))
    s = await proactx.month_close(rt)
    assert s.startswith("Uzávěrka měsíce:")
    rt.db.exec("CREATE TABLE IF NOT EXISTS pinned (id INTEGER PRIMARY KEY, text TEXT, created REAL)")
    rt.db.exec("INSERT INTO pinned(text, created) VALUES ('Dodělat prezentaci', 1)")
    plan = await proactx.week_plan(rt, dt.date(2026, 11, 29))
    assert plan.startswith("Návrh týdne:\nPo 30. 11.:") and "Po: Dodělat prezentaci" in plan


# ------------------------------------------------------------------ (69) příprava, (77) volno
async def test_meeting_prep_and_freed_time(rt, monkeypatch):
    rt.calendar.add("Porada s Petrem", dt.datetime.fromtimestamp(time.time() + 30 * 60))
    lines = await proactx.prep_due(rt)
    assert len(lines) == 1 and "Porada s Petrem" in lines[0]
    assert await proactx.prep_due(rt) == []                                          # once
    ev = rt.calendar.add("Oběd s klientem", dt.datetime.fromtimestamp(time.time() + 3 * 3600))
    assert proactx.freed_time(rt) == []
    rt.calendar.delete(ev["id"])
    out = proactx.freed_time(rt)
    assert len(out) == 1 and out[0].startswith("„Oběd s klientem“") and "60 min volna" in out[0]


# ------------------------------------------------------------------ (72) sezónní, (73) kamarádi
async def test_seasonal_and_friends(rt):
    due = dict(proactx.seasonal_due(rt, dt.date(2026, 11, 7)))
    assert "pneu_zima" in due and "okapy" in due
    proactx.seasonal_mark(rt, "pneu_zima", year=2026)
    assert "pneu_zima" not in dict(proactx.seasonal_due(rt, dt.date(2026, 11, 7)))
    proactx.friend_add(rt, "Petr", 30)
    rt.db.exec("UPDATE px_friends SET last=? WHERE name='Petr'", (time.time() - 40 * 86400,))
    assert proactx.friends_overdue(rt) == ["S Petr jsi nemluvil 40 dní."]
    out = await rt.agent.handle("mluvil jsem s Petrem")
    assert out == "Zapsáno." and proactx.friends_overdue(rt) == []


# ------------------------------------------------------------------ (74) pauza ve hře
def test_game_break(rt):
    t0 = 1_000_000.0
    assert proactx.game_break(rt, True, t0) == ""
    assert proactx.game_break(rt, True, t0 + 60 * 60) == ""
    assert proactx.game_break(rt, True, t0 + 121 * 60).startswith("Hraješ už 2 hodiny")
    assert proactx.game_break(rt, True, t0 + 130 * 60) == ""
    assert proactx.game_break(rt, True, t0 + 181 * 60).startswith("Hraješ už 3 hodiny")
    assert proactx.game_break(rt, False, t0 + 200 * 60) == "" and rt.px_game_since is None


# ------------------------------------------------------------------ (76) podmínky, (79) přehled rutin
async def test_conditions_and_routine_stats(rt):
    at = dt.datetime(2026, 6, 13, 8, 0)                       # a Saturday
    _weather(rt, at.date(), {"weather_code": [61] * 24, "temperature_2m": [14.0] * 24})
    assert proactx.conditions_ok(rt, ["prší", "víkend"], at)
    assert not proactx.conditions_ok(rt, ["prší", "všední den"], at)
    assert proactx.conditions_ok(rt, ["teplo<20", "mezi 7:00-9:00"], at) and not proactx.conditions_ok(rt, ["teplo>25"], at)
    assert not proactx.conditions_ok(rt, ["sněží"], at) and not proactx.conditions_ok(rt, ["něco divného"], at)
    rt.update_config({"automations": {"items": [{"id": "destnik", "name": "Deštník", "when": ["prší"], "steps": [{"say": "Vezmi si deštník."}]},
                                                {"id": "nic", "name": "Nepoužívaná"}]}})
    a = rt.cfg.automations.items[0]
    rt.db.exec("DELETE FROM kv WHERE k='px_weather'")
    assert not rt.automations.fire(a)                         # no weather known → the condition does not hold
    _weather(rt, dt.date.today(), {"weather_code": [61] * 24})
    assert rt.automations.fire(a)
    r = proactx.routines_report(rt)
    assert r["used"][0].startswith("Deštník (1×") and r["idle"] == ["Nepoužívaná"]


# ------------------------------------------------------------------ the minute tick
async def test_tick_says_each_thing_once(rt):
    day = dt.date(2026, 10, 27)                               # Tuesday before 28. 10.
    _weather(rt, day)
    said = await proactx.tick(rt, dt.datetime(2026, 10, 27, 17, 5))
    assert "Zítra je svátek" in said and "Sušení prádla" in said and "Deník" not in said
    again = await proactx.tick(rt, dt.datetime(2026, 10, 27, 17, 6))
    assert "Zítra je svátek" not in again
    later = await proactx.tick(rt, dt.datetime(2026, 10, 27, 21, 31))
    assert "Deník" in later and rt.memx_diary_asked > 0
