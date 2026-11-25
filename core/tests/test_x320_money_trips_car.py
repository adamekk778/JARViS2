"""3.20 Peníze+ (201–220), Cesty+ (221–240) a Auto+ (401–420)."""
from __future__ import annotations

import datetime as dt
import json
import time

import pytest

from jarvis import carx, moneyx, tools, tripx


# ================================================================== Peníze+
def test_iban_spayd_and_invoice():
    assert moneyx.cz_iban("19-2000145399/0800") == "CZ6508000000192000145399"
    assert moneyx.iban_ok("CZ65 0800 0000 1920 0014 5399") and not moneyx.iban_ok("CZ6508000000192000145398")
    with pytest.raises(ValueError):
        moneyx.cz_iban("12345")
    code = moneyx.spayd("CZ6508000000192000145399", 450, "2026001", "Večeře * u Petra", dt.date(2026, 12, 1))
    assert code == "SPD*1.0*ACC:CZ6508000000192000145399*AM:450.00*CC:CZK*DT:20261201*X-VS:2026001*MSG:Vecere   u Petra"
    text = ("Faktura č. 2026117\nDodavatel: Alfa s.r.o.\nČíslo účtu: 19-2000145399/0800\nVariabilní symbol: 2026117\n"
            "Datum splatnosti: 10. 12. 2026\nCelkem k úhradě: 12 345,50 Kč")
    info = moneyx.parse_invoice(text)
    assert info == {"iban": "CZ6508000000192000145399", "account": "19-2000145399/0800", "vs": "2026117", "amount": 12345.5,
                    "due": "2026-12-10"}


def test_split_and_qr(tmp_path):
    parts = moneyx.split(1840, ["Adam", "Petr", "Jana"])
    assert parts == [("Adam", 613.34), ("Petr", 613.33), ("Jana", 613.33)] and round(sum(a for _, a in parts), 2) == 1840
    assert moneyx.split(100, 4)[0] == ("Osoba 1", 25.0)
    png = moneyx.qr_png("SPD*1.0*ACC:CZ6508000000192000145399*AM:1.00", tmp_path / "q.png")
    assert png.read_bytes().startswith(b"\x89PNG")


def test_budget_and_spending(rt):
    assert moneyx.parse_spend("utratil jsem 350 za jídlo") == (350.0, "jídlo", "jídlo")
    assert moneyx.parse_spend("benzín 1 200 Kč")[0:2] == (1200.0, "doprava")
    assert moneyx.parse_spend("nic") is None
    moneyx.budget_set(rt, "jídlo", 1000)
    day = dt.date(2026, 11, 25)
    ts = dt.datetime(2026, 11, 20, 12).timestamp()
    moneyx.spend_add(rt, 850, "jídlo", "nákup", ts=ts)
    st = moneyx.budget_status(rt, day)
    assert st == [{"category": "jídlo", "limit": 1000.0, "spent": 850.0, "left": 150.0, "pct": 85}]
    assert "zbývá 150 Kč" in moneyx.budget_alerts(rt, day)[0] and moneyx.budget_alerts(rt, day) == []
    moneyx.spend_add(rt, 300, "jídlo", "restaurace", ts=ts)
    assert "vyčerpaný" in moneyx.budget_alerts(rt, day)[0]
    assert moneyx.spend_add(rt, 99, "jídlo", "x", ts=ts, ref="fio:1") and not moneyx.spend_add(rt, 99, "jídlo", "x", ts=ts, ref="fio:1")


def test_pocket_money(rt):
    moneyx.kid_set(rt, "Ema", 100, day=dt.date(2026, 11, 28).weekday())
    assert moneyx.kids_payday(rt, dt.date(2026, 11, 27)) == []
    assert moneyx.kids_payday(rt, dt.date(2026, 11, 28)) == ["Ema dostal(a) kapesné 100 Kč, má 100 Kč."]
    assert moneyx.kids_payday(rt, dt.date(2026, 11, 28)) == []                   # once that day
    assert moneyx.kid_move(rt, "Ema", -30, "bonbony") == 70
    with pytest.raises(ValueError):
        moneyx.kid_move(rt, "Ema", -500)


async def test_price_watch(rt):
    page = ('<html><title>Sluchátka X</title><script type="application/ld+json">{"@type":"Product","name":"Sluchátka X",'
            '"offers":{"@type":"Offer","price":"2490.00","priceCurrency":"CZK"}}</script></html>')
    assert moneyx.price_from_html(page) == (2490.0, "Sluchátka X")
    assert moneyx.price_from_html('<meta itemprop="price" content="1 299,90">')[0] == 1299.9
    assert moneyx.price_from_html("<span>3 499 Kč</span>")[0] == 3499.0
    moneyx.watch_add(rt, "https://www.alza.cz/x", 2000)
    prices = iter(["2490", "2300", "1990"])

    async def fetch(url):
        return page.replace("2490.00", next(prices))

    assert await moneyx.watch_check(rt, fetch) == []
    assert "zlevnilo z 2 490 Kč na 2 300 Kč" in (await moneyx.watch_check(rt, fetch))[0]
    assert "pod tvou cenou 2 000 Kč" in (await moneyx.watch_check(rt, fetch))[0]
    with pytest.raises(ValueError):
        moneyx.watch_add(rt, "alza.cz/x")


def test_goals_items_and_reminders(rt):
    moneyx.goal_set(rt, "Dovolená", 30000, "2027-06-01")
    g = moneyx.goal_add(rt, "Dovolená", 6000)
    assert g["pct"] == 20 and g["per_month"] is not None
    assert moneyx.warranty_until(dt.date(2026, 2, 29) if False else dt.date(2024, 2, 29), 24) == dt.date(2026, 2, 28)
    today = dt.date(2026, 11, 25)
    moneyx.item_add(rt, "voucher", "Kino Svět", (today + dt.timedelta(days=7)).isoformat(), 500)
    moneyx.item_add(rt, "return", "Bunda Zalando", (today + dt.timedelta(days=3)).isoformat())
    moneyx.item_add(rt, "bill", "Elektřina", today.isoformat(), 1890)
    out = moneyx.item_reminders(rt, today)
    assert any("Poukázka Kino Svět (500 Kč) propadne za 7 dní" in x for x in out)
    assert any("Lhůta na vrácení Bunda Zalando končí za 3 dní" in x for x in out)
    assert any("Faktura Elektřina (1 890 Kč) je splatná dnes" in x for x in out)
    assert moneyx.item_reminders(rt, today) == []
    with pytest.raises(ValueError):
        moneyx.item_add(rt, "nesmysl", "x", "2026-12-01")


def test_energy_tariffs_unusual_tax(rt):
    r = moneyx.advance_check(3200, 5.2, 150, 2200)
    assert r["fair_month"] == 1537 and "požádej o snížení" in r["verdict"]
    assert "doplatíš" in moneyx.advance_check(3200, 5.2, 150, 1000)["verdict"]
    rows = moneyx.tariffs(3000, [{"name": "A", "price_kwh": 5.0, "fixed_month": 100}, {"name": "B", "price_kwh": 4.6, "fixed_month": 180}])
    assert rows[0]["name"] == "B" and rows[1]["vs_best"] == 240
    hist = [300, 320, 280, 310, 290, 305, 315, 295, 300]
    assert "nad obvyklou platbou" in moneyx.unusual(4800, hist) and moneyx.unusual(330, hist) == ""
    assert "První platba" in moneyx.unusual(9000, [], new_counterparty=True)
    moneyx.tax_add(rt, 2026, "penzijni", 36000)
    moneyx.tax_add(rt, 2026, "zivotni", 24000)
    moneyx.tax_add(rt, 2026, "hypoteka", 95000)
    s = moneyx.tax_summary(rt, 2026)
    assert s["deductible"] == (36000 - 20400) + 24000 + 80000 and any("strop 48 000 Kč" in x for x in s["lines"])


def test_fio_restock_portfolio_year(rt):
    data = {"accountStatement": {"transactionList": {"transaction": [
        {"column22": {"value": 111}, "column0": {"value": "2026-11-20+0100"}, "column1": {"value": -459.0}, "column14": {"value": "CZK"},
         "column10": {"value": "Albert"}, "column16": {"value": "nákup potraviny"}},
        {"column22": {"value": 112}, "column0": {"value": "2026-11-21+0100"}, "column1": {"value": 25000.0}, "column14": {"value": "CZK"},
         "column10": {"value": "Zaměstnavatel"}}]}}}
    tx = moneyx.parse_fio(data)
    assert tx[0] == {"id": "111", "date": "2026-11-20", "amount": -459.0, "currency": "CZK", "counter": "Albert", "note": "nákup potraviny"}
    now = time.time()
    for k in range(4):
        moneyx.bought(rt, "Mléko", now - (4 - k) * 3 * 86400)
    assert moneyx.due_items(rt, now) == ["mleko"]
    n = moneyx.import_csv(rt, "XTB", "Symbol;Quantity;Cost\nAAPL;2;8000\nVWCE;10;25000\n")
    assert n == 2

    async def q(sym):
        return {"price": 5000 if sym == "AAPL" else 2600}

    import asyncio

    p = asyncio.run(moneyx.portfolio(rt, q))
    assert p["value"] == 36000 and p["cost"] == 33000 and p["gain"] == 3000
    moneyx.spend_add(rt, 1000, "jídlo", "x", ts=dt.datetime(2025, 5, 1).timestamp())
    moneyx.spend_add(rt, 3000, "jídlo", "x", ts=dt.datetime(2026, 5, 1).timestamp())
    y = moneyx.year_summary(rt, 2026)
    assert y["total"] == 3000 and any("Největší změna: jídlo +2 000 Kč" in x for x in y["lines"])


# ================================================================== Cesty+
def test_places_and_walks():
    data = {"elements": [{"lat": 50.01, "lon": 14.0, "tags": {"name": "Vyhlídka Máj", "tourism": "viewpoint"}},
                         {"lat": 50.10, "lon": 14.0, "tags": {"natural": "peak", "name": "Kopec"}},
                         {"type": "way"}]}
    near = (50.0, 14.0)
    v = tripx.parse_places(data, near, "viewpoint")
    assert v[0]["name"] == "Vyhlídka Máj" and v[0]["km"] == 1.11 and len(v) == 2
    q = tripx.overpass_query("cafe_work", 50.0, 14.0, 1500)
    assert 'internet_access' in q and "around:1500,50.00000,14.00000" in q
    walk = tripx.nature_walk(near, [dict(x, kind="nature") for x in v])
    assert [s["name"] for s in walk] == ["Vyhlídka Máj", "Kopec"] and tripx.walk_km(near, walk) > 20
    assert tripx.stops_along([(0, 0), (1, 1), (2, 2), (3, 3)], 300, 90) == [(1, 1), (2, 2), (3, 3)]
    assert tripx.stops_along([(0, 0)], 60, 90) == []


def test_jetlag_dst_eu261():
    plan = tripx.jetlag_plan(6, dt.date(2026, 12, 10))
    assert plan[0].startswith("07. 12.: spát o 1 h dřív") and "Zbylé 3 h" in plan[-1]
    assert "později" in tripx.jetlag_plan(-9, dt.date(2026, 12, 10))[0]
    assert tripx.dst_change(2026) == [dt.date(2026, 3, 29), dt.date(2026, 10, 25)]
    assert "hodina spánku navíc" in tripx.dst_notice(dt.date(2026, 10, 24)) and tripx.dst_notice(dt.date(2026, 10, 20)) == ""
    assert tripx.eu261(1200, 3.5) == {"eligible": True, "eur": 250, "why": "Zpoždění 3.5 h na 1200 km → 250 € na osobu."}
    assert tripx.eu261(2500, 4)["eur"] == 400 and tripx.eu261(6000, 5)["eur"] == 600
    assert not tripx.eu261(6000, 2.5)["eligible"] and not tripx.eu261(800, 5, extraordinary=True)["eligible"]
    letter = tripx.eu261_letter("Adam Novák", "OK123", "1. 12. 2026", "Praha – Řím", 4, 250, "ABC123")
    assert "261/2004" in letter and "250 EUR" in letter and "ABC123" in letter


def test_closures_gbfs_emergency_vignettes():
    page = ("<p>Výluka na trati S7 mezi Berounem a Prahou: náhradní doprava autobusy.</p><p>Na lince R10 vše normálně.</p>"
            "<p>Omezení provozu ve stanici Beroun o víkendu.</p>")
    hits = tripx.closures_in(page, ["S7"], ["Beroun"])
    assert len(hits) == 2 and "S7" in hits[0]
    assert tripx.closures_in(page, ["S9"]) == []
    st = {"data": {"stations": [{"station_id": "1", "name": "Anděl", "lat": 50.07, "lon": 14.40}]}}
    ss = {"data": {"stations": [{"station_id": "1", "num_bikes_available": 3}]}}
    fb = {"data": {"bikes": [{"lat": 50.071, "lon": 14.401, "vehicle_type_id": "koloběžka"}, {"lat": 51, "lon": 14, "is_reserved": False}]}}
    near = tripx.gbfs_nearby(st, ss, fb, (50.0705, 14.4005))
    assert [x["name"] for x in near] == ["Anděl", "koloběžka"]
    assert tripx.ride_cost(12, 25, 6.9) == 107.8
    assert "Policie 113, záchranka 118, hasiči 115" in tripx.emergency_text("it")
    assert "911" in tripx.emergency_text("us") and "112" in tripx.emergency_text("xx")
    v = " ".join(tripx.vignette_text(["at", "si", "it", "de"]))
    assert "asfinag.at" in v and "evinjeta.dars.si" in v and "mýto na dálnici podle úseku" in v and "zdarma" in v


def test_shared_plan_and_insurance(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    tok = tripx.plan_create(rt, "Šumava 2027")
    assert tripx.plan_add(rt, tok, "Jana", "Vezmu stan") and not tripx.plan_add(rt, "nic", "x", "y")
    c = TestClient(create_app(rt, manage_runtime=False), client=("85.1.2.3", 5000))
    page = c.get(f"/plan/{tok}")
    assert page.status_code == 200 and "Vezmu stan" in page.text
    r = c.post(f"/plan/{tok}", content="who=Petr&text=%3Cb%3Eauto%3C%2Fb%3E", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and "&lt;b&gt;auto" in r.text
    assert c.get("/plan/neni").status_code == 404
    today = dt.date(2026, 11, 25)
    trips = [{"id": 7, "title": "Řím", "start": "2026-11-30", "country": "it"}, {"id": 8, "title": "Brno", "start": "2026-11-28", "country": "cz"}]
    out = tripx.insurance_due(rt, trips, today)
    assert len(out) == 1 and "Řím" in out[0] and "EHIC" in out[0]
    assert tripx.insurance_due(rt, trips, today) == []
    tripx.insured(rt, "9")
    assert tripx.insurance_due(rt, [{"id": 9, "title": "Vídeň", "start": "2026-11-27", "country": "at"}], today) == []


def test_menu_prompt_and_diary():
    p = tripx.menu_prompt(["ořechy", "lepek"])
    assert "ořechy, lepek" in p and "⚠" in p and "sezam" in p
    h = tripx.diary_html("Cesta <Řím>", [{"date": "1. 12.", "places": ["Koloseum"], "photos": ["a.jpg"], "note": "super"}], 18500)
    assert "&lt;Řím&gt;" in h and "Koloseum" in h and "18 500 Kč" in h


# ================================================================== Auto+
def test_obd_codes():
    r = carx.obd_explain("p0420")
    assert r["code"] == "P0420" and "katalyzátor" in r["summary"] and not r["serious"]
    assert carx.obd_explain("P0302")["serious"] and "Jeď opatrně" in carx.obd_explain("P0302")["summary"]
    unk = carx.obd_explain("P1234")
    assert "výrobcem definovaný" in unk["summary"] and "motor a převodovka" in unk["summary"]
    assert carx.obd_explain("U0100")["system"] == "komunikace jednotek"
    with pytest.raises(ValueError):
        carx.obd_explain("X999")


def test_consumption_service_logbook(rt):
    carx.fuel_add(rt, 40, 1500, 10000, True, ts=1)
    carx.fuel_add(rt, 30, 1150, 10500, True, ts=2)
    carx.fuel_add(rt, 36, 1400, 11100, True, ts=3)
    carx.cost_add(rt, "pojištění", 6000)
    c = carx.consumption(rt)
    assert c["l_per_100"] == 6.0 and c["avg_l_per_100"] == 6.0 and c["km"] == 1100 and c["fuel_cost"] == 2550
    assert c["per_km"] == round((2550 + 6000) / 1100, 2)
    carx.service_add(rt, "2025-12-01", 9000, "olej + filtry", 4200)
    assert "servis podle času za" in carx.next_service(rt, 11100, dt.date(2026, 11, 15))
    assert "servis podle km za" in carx.next_service(rt, 23500, dt.date(2026, 1, 15))
    t0 = dt.datetime(2026, 11, 3, 7, 30).timestamp()
    carx.trip_start(rt, "Domov", 11100, ts=t0)
    t = carx.trip_end(rt, "Kancelář", 11124, ts=t0 + 1800)
    assert t["km"] == 24
    carx.trip_purpose(rt, t["id"], "služební – klient Alfa")
    csv_ = carx.logbook_csv(rt, "2026-11")
    assert "03.11.2026;07:30;08:00;Domov;Kancelář;služební – klient Alfa;24;11100;11124" in csv_
    assert carx.trip_end(rt) is None


def test_parking_prices_chargers_tyres(rt):
    p = carx.park(rt, 50.08, 14.42, minutes=60, now=1000)
    assert p["until"] == 4600 and carx.where_parked(rt)["lat"] == 50.08
    assert carx.parking_due(rt, 1000) == "" and carx.parking_due(rt, 4600 - 300) == "Parkovné končí za 5 min."
    assert carx.parking_due(rt, 4600 - 200) == ""
    carx.price_report(rt, "Shell Zličín", "natural", 38.9)
    carx.price_report(rt, "Orlen Řepy", "natural", 37.5)
    assert [r["station"] for r in carx.cheapest(rt)] == ["Orlen Řepy", "Shell Zličín"]
    tk = carx.parse_tankerkoenig({"stations": [{"brand": "ARAL", "place": "Furth", "price": 1.789, "isOpen": True, "dist": 2.1},
                                               {"brand": "JET", "place": "Cham", "price": 1.699, "isOpen": True, "dist": 5}]})
    assert tk[0]["name"] == "JET Cham"
    ocm = carx.parse_ocm([{"AddressInfo": {"Title": "Ionity D1", "Distance": 4.2, "Latitude": 49.6, "Longitude": 15.6},
                           "Connections": [{"PowerKW": 350}], "OperatorInfo": {"Title": "IONITY"}},
                          {"AddressInfo": {"Title": "AC Obchoďák", "Distance": 1.0}, "Connections": [{"PowerKW": 22}]}])
    assert ocm[0]["name"] == "Ionity D1" and ocm[0]["fast"]
    assert carx.charge_time(77, 20, 80, 150) == 21
    assert "zimní pneumatiky" in carx.tyre_advice([6, 5, 4, 6, 5], 11)
    assert carx.tyre_advice([6, 5, 4, 6, 5], 11, "zimní") == "" and "letní" in carx.tyre_advice([14, 15, 12], 4)
    assert "hned" in carx.car_heat(34, False, True) and carx.car_heat(34, True, True) == "" and carx.car_heat(25, False, True) == ""


def test_traffic_trip_share_sell_points():
    t = carx.parse_tomtom({"routes": [{"summary": {"travelTimeInSeconds": 2100, "trafficDelayInSeconds": 480, "lengthInMeters": 23400}}]})
    assert t == {"minutes": 35, "delay_min": 8, "km": 23.4}
    plan = carx.long_trip_plan(1100, 640, 400)
    assert any("rozděl to na dva dny" in x for x in plan) and any("nabíjení" in x for x in plan) and any("přestávka" in x for x in plan)
    r = carx.rideshare(300, 6, 40, 3)
    assert r == {"total": 720, "each": 240.0, "people": 3}
    est = carx.price_estimate(600000, 2022, 90000, dt.date(2026, 11, 25))
    assert 250000 < est["estimate"] < 360000 and est["low"] < est["estimate"] < est["high"]
    ad = carx.sale_ad({"brand": "Škoda", "model": "Octavia", "year": 2020, "km": 98000, "equipment": ["tažné", "zimní kola"]})
    assert ad.startswith("Škoda Octavia r. v. 2020 98000 km") and "tažné" in ad
    assert carx.points_after(7, 25) == 0 and carx.points_after(9, 13) == 5


# ================================================================== tools and hooks
async def test_x6_tools(rt):
    for n in ("money_kit", "trip_kit", "car_kit"):
        assert n in tools.REGISTRY
    r = await tools.call("money_kit", {"action": "split", "amount": 1000, "text": "Adam, Petr"}, rt)
    assert r.ok and "Adam: 500 Kč" in r.summary and "QR platby pošlu" in r.summary
    rt.cfg.moneyx.my_account = "19-2000145399/0800"
    r = await tools.call("money_kit", {"action": "split", "amount": 1000, "text": "Adam, Petr"}, rt)
    assert r.data["qr"][0].startswith("SPD*1.0*ACC:CZ65")
    r = await tools.call("car_kit", {"action": "obd", "text": "P0171"}, rt)
    assert r.ok and "chudá" in r.summary
    r = await tools.call("trip_kit", {"action": "sos", "text": "hr"}, rt)
    assert "192" in r.summary
    r = await tools.call("money_kit", {"action": "spend", "text": "kino 280"}, rt)
    assert r.ok and "zábava" in r.summary


def test_driving_starts_logbook(rt):
    from jarvis import phonex

    pushed = []
    rt.phone_push = lambda kind, **d: pushed.append(kind) or True
    phonex.on_bt(rt, "Skoda Octavia", True)
    assert carx.db(rt).one("SELECT COUNT(*) n FROM cx_trips WHERE end IS NULL")["n"] == 1
    phonex.on_bt(rt, "Skoda Octavia", False)
    assert carx.db(rt).one("SELECT COUNT(*) n FROM cx_trips WHERE end IS NOT NULL")["n"] == 1 and "where" in pushed


def test_phone_where_route(rt):
    from fastapi.testclient import TestClient

    from jarvis import watchpair
    from jarvis.server.app import create_app

    app = create_app(rt, manage_runtime=False)
    c = TestClient(app, client=("192.168.1.30", 5000))
    tok = c.post("/api/watch/pair", json={"code": watchpair.start(rt)["code"]}).json()["token"]
    r = c.post("/api/phone/where", json={"lat": 50.1, "lon": 14.3}, headers={"Authorization": f"Bearer {tok}"})
    assert r.json()["ok"] and carx.where_parked(rt)["lon"] == 14.3
    _ = json
