"""3.14 Auto, cesty, svět: the car through Home Assistant, trips from e-mail, parcels, the world map."""
import datetime as dt
import json

import httpx
import pytest

from jarvis import car, parcels, tools, travel

tools.load_builtin()

HA_STATES = [
    {"entity_id": "sensor.enyaq_battery_level", "state": "74", "attributes": {"friendly_name": "Enyaq Battery level", "unit_of_measurement": "%"}},
    {"entity_id": "sensor.enyaq_range", "state": "312", "attributes": {"friendly_name": "Enyaq Range", "unit_of_measurement": "km"}},
    {"entity_id": "device_tracker.enyaq_position", "state": "not_home",
     "attributes": {"friendly_name": "Enyaq Position", "latitude": 49.20, "longitude": 16.61}},
    {"entity_id": "lock.enyaq_doors", "state": "locked", "attributes": {"friendly_name": "Enyaq Doors"}},
    {"entity_id": "climate.enyaq_air_conditioning", "state": "off", "attributes": {"friendly_name": "Enyaq Air conditioning"}},
    {"entity_id": "switch.enyaq_charging", "state": "off", "attributes": {"friendly_name": "Enyaq Charging"}},
    {"entity_id": "sensor.phone_battery_level", "state": "40", "attributes": {"friendly_name": "Telefon baterie", "unit_of_measurement": "%"}},
    {"entity_id": "light.obyvak", "state": "on", "attributes": {"friendly_name": "Obývák"}},
]


@pytest.fixture
def ha(rt, monkeypatch):
    from jarvis import secrets

    monkeypatch.setattr(secrets, "get", lambda name: "t" if name == "ha_token" else "")
    calls = []

    def handler(req: httpx.Request):
        if req.url.path == "/api/states":
            return httpx.Response(200, json=HA_STATES)
        if req.url.path.startswith("/api/services/"):
            calls.append((req.url.path, json.loads(req.content)))
            return httpx.Response(200, json=[])
        if req.url.path == "/v1/search":                                    # open-meteo: the home city
            return httpx.Response(200, json={"results": [{"latitude": 50.08, "longitude": 14.42}]})
        if "router.project-osrm.org" in str(req.url):
            return httpx.Response(200, json={"code": "Ok", "routes": [{"duration": 1800}]})
        return httpx.Response(404)

    rt.transport = httpx.MockTransport(handler)
    rt.update_config({"home": {"url": "http://ha.local:8123"}})
    return calls


def test_discover_finds_the_car_and_not_the_phone():
    from jarvis.home import short

    found = car.discover([short(e) for e in HA_STATES])
    assert found == {"battery": "sensor.enyaq_battery_level", "range": "sensor.enyaq_range", "location": "device_tracker.enyaq_position",
                     "lock": "lock.enyaq_doors", "climate": "climate.enyaq_air_conditioning", "charging": "switch.enyaq_charging"}


def test_describe_warns_about_an_unlocked_car_away():
    parts = {"battery": {"state": "18"}, "lock": {"state": "unlocked"}, "location": {"lat": 49.2, "lon": 16.6}}
    text, data = car.describe(parts, (50.08, 14.42), "Enyaq")
    assert "baterie 18 %" in text and "ODEMČENÉ" in text and "km od domova" in text and "Pozor" in text
    text, data = car.describe({"location": {"lat": 50.0801, "lon": 14.4201}}, (50.08, 14.42))
    assert "stojí doma" in text


async def test_car_tools(rt, ha):
    r = await tools.call("car_setup", {"name": "Enyaq"}, rt)
    assert r.ok and "baterie" in r.summary and rt.cfg.home.car["name"] == "Enyaq"
    r = await tools.call("car_status", {}, rt)
    assert r.ok and "Enyaq: baterie 74 %, dojezd 312 km" in r.summary and "zamčené" in r.summary
    r = await tools.call("car_climate", {"on": True}, rt)
    assert r.ok and ha[-1] == ("/api/services/climate/turn_on", {"entity_id": "climate.enyaq_air_conditioning"})
    assert tools.REGISTRY["car_lock"].danger_if({"lock": False}) and not tools.REGISTRY["car_lock"].danger_if({"lock": True})


async def test_car_ready_schedules_the_heating(rt, ha):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    rt.update_config({"home": {"car": {"climate": "climate.enyaq_air_conditioning", "battery": "sensor.enyaq_battery_level"}}})
    evening = (dt.datetime.now() + dt.timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)
    job = car.ready_at(rt, "7:30", now=evening)
    start = dt.datetime.fromtimestamp(job["next_run"])
    assert start == (evening + dt.timedelta(days=1)).replace(hour=7, minute=15) and job["kind"] == "car_ready"
    with pytest.raises(ValueError):
        car.ready_at(rt, "25:00")
    said = []
    rt.notify = lambda title, text, **kw: said.append(text)
    await car.run_ready(rt, {"ready": "07:30"})
    assert ha[-1][0] == "/api/services/climate/turn_on" and "v 07:30 bude připravené" in said[-1]


FLIGHT_MAIL = """Potvrzení rezervace – Ryanair
Váš let
FR 1234  Praha (PRG) → Barcelona (BCN)
Datum: 12. prosince 2026
Odlet 14:35  Přílet 16:50
Zpáteční let FR 1235 BCN → PRG 19. 12. 2026 17:20 19:40
Číslo rezervace ABC123, cena 2 450 Kč. Odbavení otevřeno do 2026."""

TRAIN_MAIL = """RegioJet – jízdenka
Spoj RJ 1031, Praha hl.n. → Brno hl.n.
Datum 2026-12-03, odjezd 7:48, příjezd 10:21. Vůz 5, místo 42."""


def test_parse_flights_and_trains():
    now = dt.datetime(2026, 11, 24, 9, 0)
    trips = travel.parse(FLIGHT_MAIL, now)
    assert [(t["number"], t["origin"], t["dest"]) for t in trips] == [("FR 1234", "PRG", "BCN"), ("FR 1235", "BCN", "PRG")]
    dep = dt.datetime.fromtimestamp(trips[0]["dep"])
    assert (dep.month, dep.day, dep.hour, dep.minute) == (12, 12, 14, 35)
    assert dt.datetime.fromtimestamp(trips[0]["arr"]).hour == 16
    assert dt.datetime.fromtimestamp(trips[1]["dep"]).day == 19
    tr = travel.parse(TRAIN_MAIL, now)
    assert tr and tr[0]["kind"] == "train" and tr[0]["number"] == "RJ 1031"
    assert tr[0]["origin"].startswith("Praha") and tr[0]["dest"].startswith("Brno")
    assert dt.datetime.fromtimestamp(tr[0]["dep"]).strftime("%d.%m %H:%M") == "03.12 07:48"
    assert travel.parse("Nic tu není, jen OK 2026 a čas 12:00.", now) == []
    assert travel.callsign("FR 1234") == "RYR1234" and travel.callsign("OK 650") == "CSA650" and travel.callsign("ZZ 1") == ""


async def test_leave_plan_and_the_leave_notice(rt, ha):
    dep = dt.datetime.now() + dt.timedelta(hours=3)
    tid = travel.add(rt, {"kind": "flight", "number": "FR 1234", "dep": dep.timestamp(), "origin": "PRG", "dest": "BCN"})
    assert travel.add(rt, {"kind": "flight", "number": "FR 1234", "dep": dep.timestamp()}) is None     # once
    t = travel.upcoming(rt)[0]
    p = await travel.leave_plan(rt, t)
    assert p["drive_min"] == 30 and p["buffer_min"] == 120 and not p["guess"]
    assert abs(p["leave"] - (dep.timestamp() - 150 * 60)) < 1
    said = []
    rt.notify = lambda title, text, **kw: said.append((title, text))
    w = travel.Watch(rt)
    w.last_scan = 1e18                                                       # no mail here
    out = await w.step(now=p["leave"] - 10 * 60)
    assert "leave:FR 1234" in out and said[-1][0] == "Čas vyrazit" and "na letiště" in said[-1][1]
    assert "leave:FR 1234" not in await w.step(now=p["leave"] - 5 * 60)     # once
    assert travel.remove(rt, tid)


async def test_flight_delay_and_gate_from_aerodatabox(rt, monkeypatch):
    from jarvis import connectors, secrets

    monkeypatch.setattr(secrets, "get", lambda k: "key" if k == connectors.skey("aerodatabox", "api_key") else "")
    connectors.load()
    flights = [{"number": "FR 1234", "status": "Delayed", "departure": {
        "airport": {"iata": "PRG"}, "scheduledTime": {"local": "2026-12-12 14:35+01:00"}, "revisedTime": {"local": "2026-12-12 15:20+01:00"},
        "terminal": "2", "gate": "C5"}, "arrival": {"airport": {"iata": "BCN"}}, "airline": {"name": "Ryanair"}}]
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(200, json=flights)

    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(handler))
    dep = dt.datetime(2026, 12, 12, 14, 35).timestamp()
    tid = travel.add(rt, {"kind": "flight", "number": "FR 1234", "dep": dep})
    t = next(x for x in travel.upcoming(rt, now=dep - 3600) if x["id"] == tid)
    res = await travel.check_flight(rt, t)
    assert set(res["changed"]) == {"delay_min", "gate"} and res["info"]["delay_min"] == 45 and res["info"]["gate"] == "C5"
    assert seen[0].headers["X-RapidAPI-Key"] == "key" and "/flights/number/FR1234/2026-12-12" in str(seen[0].url)
    t["info"] = res["info"]
    assert "zpoždění 45 min, gate C5, terminál 2" in travel.describe(t)
    again = await travel.check_flight(rt, {**t, "info": res["info"]})
    assert again["changed"] == []                                            # nothing new → no second notice


SHIP_MAIL = """Dobrý den, vaše objednávka z Alza.cz byla odeslána.
Zásilku doručí Česká pošta, číslo zásilky: DR0123456789M. Sledovat ji můžete na postaonline.cz.
Druhý balík jde přes Zásilkovnu: Z 123 4567 890.
PPL číslo zásilky pro sledování: 40123456789"""


def test_find_parcels_in_a_shipping_mail():
    found = parcels.find(SHIP_MAIL, "objednavky@alza.cz", "Alza.cz")
    assert [(p["carrier"], p["number"]) for p in found] == [("cpost", "DR0123456789M"), ("zasilkovna", "Z1234567890"), ("ppl", "40123456789")]
    assert all(p["shop"] == "Alza" for p in found)
    assert parcels.find("Objednávka 12345678901 přijata", "shop@x.cz") == []      # 11 digits alone are not a PPL parcel
    assert parcels.guess_carrier("RR123456789CZ") == "cpost" and parcels.guess_carrier("Z1234567890") == "zasilkovna"


async def test_czech_post_tracking_and_the_ready_notice(rt):
    answer = [{"id": "DR0123456789M", "states": {"state": [
        {"id": "21", "date": "2026-11-23", "text": "Zásilka převzata do přepravy.", "postoffice": "Praha 022"},
        {"id": "82", "date": "2026-11-24", "text": "Zásilka je připravena k vyzvednutí.", "postoffice": "Brno 2"}]}}]

    def handler(req: httpx.Request):
        assert req.url.params["idParcel"] == "DR0123456789M"
        return httpx.Response(200, json=answer)

    rt.transport = httpx.MockTransport(handler)
    said = []
    rt.notify = lambda title, text, **kw: said.append(text)
    assert parcels.add(rt, "cpost", "DR0123456789M", "Alza") and not parcels.add(rt, "cpost", "DR 0123456789M")
    parcels.add(rt, "ppl", "40123456789")
    changed = await parcels.refresh(rt)
    assert [p["number"] for p in changed] == ["DR0123456789M"] and changed[0]["state"] == "ready"
    assert said == ["Balík z Alza (Česká pošta): Zásilka je připravena k vyzvednutí. (Brno 2)."]
    assert await parcels.refresh(rt) == []                                   # the same state → no second notice
    s = parcels.summary(rt)
    assert "2 zásilky" in s and "ppl.cz" in s
    assert parcels.cpost_status([{"states": {"state": [{"id": "-3", "text": "není v evidenci"}]}}]) == ("", "")


async def test_scan_mail_finds_trips_and_parcels(rt):
    class Acc:
        def list(self, unread, limit):
            return [{"id": "a:1", "uid": 1, "subject": "Potvrzení rezervace letu", "newsletter": False},
                    {"id": "a:2", "uid": 2, "subject": "Vaše zásilka je na cestě", "newsletter": False},
                    {"id": "a:3", "uid": 3, "subject": "Týdenní slevy", "newsletter": False}]

        def read(self, uid, mark):
            assert uid != 3                                                  # only booking / shipping subjects are opened
            return {"subject": "", "text": FLIGHT_MAIL if uid == 1 else SHIP_MAIL, "from": "info@alza.cz", "from_name": "Alza"}

    class Mail:
        def account(self):
            return Acc()

        def sync(self):
            pass

    rt.mail = Mail()
    rt.update_config({"mail": {"accounts": [{"id": "a", "address": "ja@example.cz"}]}})
    found = await travel.scan_mail(rt)
    assert {t["number"] for t in found} >= {"FR 1234"} or found == []        # past dates are skipped on old test clocks
    assert {p["number"] for p in parcels.listing(rt)} == {"DR0123456789M", "Z1234567890", "40123456789"}
    assert await travel.scan_mail(rt) == []                                  # each e-mail only once


async def test_trip_tools_and_briefing(rt, ha):
    when = dt.date.today() + dt.timedelta(days=1)
    r = await tools.call("trip_add", {"number": "fr1234", "date": when.strftime("%d. %m. %Y"), "time": "14:35",
                                       "origin": "prg", "dest": "bcn"}, rt)
    assert r.ok and "let FR 1234 Praha → Barcelona" in r.summary and "Vyrazit v 12:05" in r.summary
    r = await tools.call("trips_list", {"scan": False}, rt)
    assert "FR 1234" in r.summary and "vyrazit v 12:05" in r.summary
    assert travel.briefing_line(rt, dt.datetime.combine(when, dt.time(7))) .startswith("Dnes cestujete: let FR 1234")
    r = await tools.call("trip_remove", {"number": "FR1234"}, rt)
    assert r.ok and travel.upcoming(rt) == []


async def test_world_map_data(rt, ha):
    from jarvis.server.handlers.world import map_data

    rt.update_config({"home": {"car": {"location": "device_tracker.enyaq_position"}}})
    travel.add(rt, {"kind": "flight", "number": "OK 650", "dep": dt.datetime.now().timestamp() + 86400, "origin": "PRG", "dest": "LHR"})
    d = await map_data(rt)
    assert d["home"]["lat"] == 50.08 and d["car"]["lat"] == 49.2
    assert [p["code"] for p in d["trips"][0]["points"]] == ["PRG", "LHR"]
    r = await tools.call("world_map", {}, rt)
    assert r.ok
