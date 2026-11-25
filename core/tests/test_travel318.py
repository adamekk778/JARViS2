"""3.18 Cesty: hotels and flights by description, compared, booked and paid only after confirmation – and what
happens after (reminders, the cheaper-now watch, price watches, spend). Every provider answer here is a fake (no
network); the shapes follow the LiteAPI v3 and Duffel v2 documentation."""
from __future__ import annotations

import asyncio
import datetime as dt
import json

import httpx
import pytest
from conftest import FakeRouter

from jarvis import booking, connectors, livecards, secrets, tools, travelsearch, tripcare, trust
from jarvis.tools import select


@pytest.fixture(autouse=True)
def _pinned_day():
    """3.20 the example data (a hotel from 11. 12. 2026…) was written on 24. 11. 2026: the travel parts see that day."""
    from jarvis import clock

    clock.pin(dt.datetime(2026, 11, 24, 10, 0))
    yield
    clock.pin(None)

CRIT = {"kind": "hotel", "city": "Řím", "country": "IT", "checkin": "2026-12-11", "checkout": "2026-12-14", "adults": 2,
        "max_per_night": 150, "currency": "EUR", "near": "centrum", "must": ["snídaně"]}
HOTELS = {"data": [
    {"id": "lp1", "name": "Hotel Roma Centro", "address": "Via del Corso 1", "city": "Rome", "latitude": 41.90,
     "longitude": 12.49, "stars": 4, "rating": 8.7, "reviewCount": 900},
    {"id": "lp2", "name": "Budget Inn", "city": "Rome", "latitude": 41.80, "longitude": 12.60, "stars": 2, "rating": 7.1}]}
RATES = {"data": [
    {"hotelId": "lp1", "roomTypes": [{"offerId": "OFF1", "name": "Double", "rates": [{
        "name": "Double", "boardType": "BB", "boardName": "Snídaně", "retailRate": {"total": [{"amount": 420.0, "currency": "EUR"}]},
        "cancellationPolicies": {"refundableTag": "RFN", "cancelPolicyInfos": [{"cancelTime": "2026-12-09 12:00:00"}]},
        "paymentTypes": ["NUVEE_PAY"]}]}]},
    {"hotelId": "lp2", "roomTypes": [{"offerId": "OFF2", "rates": [{
        "boardType": "RO", "retailRate": {"total": [{"amount": 250.0, "currency": "EUR"}]},
        "cancellationPolicies": {"refundableTag": "NRFN"}, "paymentTypes": ["PAY_AT_PROPERTY"]}]}]}]}


class Lite:
    """A fake LiteAPI: records every request; prebook gives `price` (change it to test a price that moved)."""

    def __init__(self, price: float = 420.0):
        self.price = price
        self.seen: list[tuple[str, str, dict]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content or b"{}")
        self.seen.append((req.method, req.url.path, body))
        assert req.headers["X-API-Key"] == "sand_test-key"
        p = req.url.path
        if p.endswith("/data/hotels"):
            return httpx.Response(200, json=HOTELS)
        if p.endswith("/hotels/rates"):
            return httpx.Response(200, json=RATES)
        if p.endswith("/rates/prebook"):
            return httpx.Response(200, json={"data": {"prebookId": "PB1", "price": self.price, "currency": "EUR",
                                                      "priceDifferencePercent": 0, "cancellationChanged": False}})
        if p.endswith("/rates/book"):
            return httpx.Response(200, json={"data": {"bookingId": "BK1", "status": "CONFIRMED", "hotelConfirmationCode": "HC-77",
                                                      "price": self.price, "currency": "EUR"}})
        if p.endswith("/bookings/BK1") and req.method == "PUT":
            return httpx.Response(200, json={"data": {"status": "CANCELLED", "cancellation_fee": 0, "refund_amount": 420, "currency": "EUR"}})
        return httpx.Response(404, json={"error": {"message": "unknown"}})

    def paths(self) -> list[str]:
        return [p for _, p, _ in self.seen]


@pytest.fixture
def lite(rt, monkeypatch):
    connectors.load()
    keys = {connectors.skey("liteapi", "api_key"): "sand_test-key"}
    monkeypatch.setattr(secrets, "get", lambda k: keys.get(k, ""))
    fake = Lite()
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(fake))

    async def geocode(rt_, name):
        return (41.90, 12.49)
    from jarvis import travel

    monkeypatch.setattr(travel, "geocode", geocode)
    rt.update_config({"booking": {"first_name": "Jan", "last_name": "Novák", "email": "jan@example.cz", "phone": "+420777000111"}})
    tools.load_builtin()
    return fake


# ------------------------------------------------------------------------------------------ 1–4 description → offers
def test_criteria_are_checked():
    today = dt.date(2026, 11, 24)
    c, missing = travelsearch.clean({"city": "Řím", "checkin": "2026-11-20", "checkout": "2026-11-23", "adults": "x"}, today)
    assert c["checkin"] == "" and "od kdy" in missing                 # a date in the past is not believed
    c, missing = travelsearch.clean({**CRIT, "stars": "4", "max_per_night": "150"}, today)
    assert missing == [] and c["stars"] == 4.0 and c["max_per_night"] == 150.0 and c["currency"] == "EUR"
    c, _ = travelsearch.clean({**CRIT, "checkout": "2026-12-10"}, today)
    assert c["checkout"] == ""                                       # check-out before check-in


async def test_understand_adds_your_own_words(rt):
    rt.router = FakeRouter([json.dumps({**CRIT, "must": []})])
    c, missing = await travelsearch.understand(rt, "Řím od pátku na 3 noci, se snídaní, zrušení zdarma, jako minule",
                                               dt.date(2026, 11, 24))
    assert missing == [] and "snídaně" in c["must"] and c["free_cancel_only"] and c["like_last_time"]
    assert "2026-11-24 (úterý)" in rt.router.calls[0]["messages"][0]["content"]      # the AI knows what "pátek" is


def test_rank_explains_and_respects_the_limits():
    offers = [
        {"kind": "hotel", "provider": "liteapi", "name": "A", "total": 420, "currency": "EUR", "per_night": 140, "nights": 3,
         "rating": 8.7, "refundable": True, "free_cancel_until": "2026-12-09T12:00", "breakfast": True, "lat": 41.9, "lon": 12.49},
        {"kind": "hotel", "provider": "liteapi", "name": "B", "total": 250, "currency": "EUR", "per_night": 83, "nights": 3,
         "rating": 7.1, "refundable": False, "pay_at_property": True, "lat": 41.8, "lon": 12.6},
        {"kind": "hotel", "provider": "liteapi", "name": "Drahý", "total": 900, "currency": "EUR", "per_night": 300, "nights": 3,
         "rating": 9.5, "refundable": True}]
    best = travelsearch.rank(offers, dict(CRIT), center=(41.9, 12.49))
    assert [o["name"] for o in best] == ["A", "B"]                     # 300 €/night is over the 150 asked
    assert "zrušení zdarma do 9. 12. 12:00" in best[0]["why"] and "nejblíž" in best[0]["why"] and "se snídaní" in best[0]["why"]
    assert "nejlevnější" in best[1]["why"] and "platíš až na hotelu" in best[1]["why"]
    only_free = travelsearch.rank([dict(o) for o in offers], {**CRIT, "free_cancel_only": True})
    assert [o["name"] for o in only_free] == ["A"]


def test_like_last_time_is_learned(rt):
    off = {"kind": "hotel", "breakfast": True, "stars": 4, "per_night": 140, "currency": "EUR", "refundable": True}
    travelsearch.learn(rt, off, {"must": ["parkování"]})
    travelsearch.learn(rt, off, {"must": ["parkování"]})
    p = travelsearch.prefs(rt)
    assert p["breakfast"] is True and p["stars"] == 4.0 and p["must"] == ["parkování"]


async def test_hotel_search_compares_and_remembers(rt, lite):
    rt.router = FakeRouter([json.dumps(CRIT)])
    r = await tools.call("hotel_search", {"description": "Řím 11.–14. 12., do 150 € za noc, blízko centra, snídaně"}, rt)
    assert r.ok, r.summary
    assert "1) Hotel Roma Centro" in r.summary and "zkušební klíč" in r.summary and "Kterou chceš" in r.summary
    o1 = booking.offer(rt, 1)
    assert o1["offer_id"] == "OFF1" and o1["checkin"] == "2026-12-11" and o1["free_cancel_until"] == "2026-12-09T12:00"
    rates = next(b for _, p, b in lite.seen if p.endswith("/hotels/rates"))
    assert rates["checkin"] == "2026-12-11" and rates["currency"] == "EUR" and rates["occupancies"] == [{"adults": 2, "children": []}]
    card = livecards.card("hotel_search", True, r.data)
    assert card["kind"] == "offers" and card["items"][0]["n"] == 1 and card["items"][0]["refundable"] is True
    assert "photo" not in card["items"][0]                             # no third-party pictures loaded into the chat


async def test_hotel_search_asks_what_is_missing(rt, lite):
    rt.router = FakeRouter([json.dumps({"kind": "hotel", "city": "Řím"})])
    r = await tools.call("hotel_search", {"description": "hotel v Římě"}, rt)
    assert r.ok and "od kdy" in r.summary and "do kdy" in r.summary and lite.seen == []


async def test_without_a_key_the_site_opens_filled_in(rt, monkeypatch):
    tools.load_builtin()
    opened = []

    async def fake_call(name, args, ctx):
        opened.append((name, args))
        return tools.ToolResult(True, "ok")
    monkeypatch.setattr(tools, "call", fake_call)
    rt.router = FakeRouter([json.dumps(CRIT)])
    from jarvis.tools.booking_tools import hotel_search

    r = await hotel_search(rt, "Řím 11.–14. 12.")
    assert r.ok and "zastavím" in r.summary
    assert opened[0][0] == "browser_open" and "booking.com" in opened[0][1]["url"] and "checkin=2026-12-11" in opened[0][1]["url"]


# ------------------------------------------------------------------------------------------ 5–9 booking with safeguards
async def test_book_checks_the_price_again_and_files_everything(rt, lite):
    rt.router = FakeRouter([json.dumps(CRIT)])
    await tools.call("hotel_search", {"description": "Řím"}, rt)
    wrong = await tools.call("travel_book", {"option": 1, "expected_total": 380, "currency": "EUR"}, rt)
    assert not wrong.ok and "nesouhlasí" in wrong.summary and not any(p.endswith("/rates/book") for p in lite.paths())
    r = await tools.call("travel_book", {"option": 1, "expected_total": 420, "currency": "EUR", "business": True}, rt)
    assert r.ok, r.summary
    assert "ZKUŠEBNÍ" in r.summary and "HC-77" in r.summary
    book = next(b for _, p, b in lite.seen if p.endswith("/rates/book"))
    assert book["prebookId"] == "PB1" and book["payment"] == {"method": "ACC_CREDIT_CARD"} and book["holder"]["lastName"] == "Novák"
    rows = booking.bookings(rt)
    assert rows[0]["ref"] == "BK1" and rows[0]["start"] == "2026-12-11" and rows[0]["refundable"] == 1 and rows[0]["business"] == 1
    d = tripcare.folder(rows[0])
    assert (d / "potvrzeni-BK1.txt").read_text(encoding="utf-8").count("HC-77") == 1
    assert "Hotel Roma Centro" in (tripcare.travel_dir() / "naklady.csv").read_text(encoding="utf-8-sig")
    again = await tools.call("travel_book", {"option": 1, "expected_total": 420, "currency": "EUR"}, rt)
    assert not again.ok and "neplatí" in again.summary                 # no second payment by repeating it


async def test_a_moved_price_stops_the_payment(rt, lite):
    rt.router = FakeRouter([json.dumps(CRIT)])
    await tools.call("hotel_search", {"description": "Řím"}, rt)
    lite.price = 455.0
    r = await tools.call("travel_book", {"option": 1, "expected_total": 420, "currency": "EUR"}, rt)
    assert not r.ok and "změnily" in r.summary and "455" in r.summary and "nic jsem nezaplatil" in r.summary
    assert not any(p.endswith("/rates/book") for p in lite.paths())
    assert booking.offer(rt, 1)["total"] == 455.0                       # what you confirm next time


async def test_limits_and_missing_details_stop_it(rt, lite):
    rt.router = FakeRouter([json.dumps(CRIT)])
    await tools.call("hotel_search", {"description": "Řím"}, rt)
    rt.update_config({"booking": {"max_per_booking": 5000}})            # 420 € ≈ 10 500 Kč
    r = await tools.call("travel_book", {"option": 1, "expected_total": 420, "currency": "EUR"}, rt)
    assert not r.ok and "limitem" in r.summary
    rt.update_config({"booking": {"max_per_booking": 0, "monthly_budget": 8000}})
    r = await tools.call("travel_book", {"option": 1, "expected_total": 420, "currency": "EUR"}, rt)
    assert not r.ok and "rozpočet" in r.summary
    rt.update_config({"booking": {"monthly_budget": 0, "phone": ""}})
    r = await tools.call("travel_book", {"option": 1, "expected_total": 420, "currency": "EUR"}, rt)
    assert not r.ok and "telefon" in r.summary
    assert not any(p.endswith("/rates/prebook") for p in lite.paths())


def test_money_is_always_asked_twice_and_never_trusted(rt):
    from jarvis.agent_helpers import _needs_second
    from jarvis.llm.base import ToolCall

    tools.load_builtin()
    spec = tools.REGISTRY["travel_book"]
    assert tools.is_dangerous(spec, {}, [], ["travel_book"], rt)          # even when marked trusted
    rt.cfg.tools.full_trust = True
    assert not trust.skip_confirm(rt, spec, False, {})
    rt.cfg.limits.double_confirm = False
    assert _needs_second(ToolCall(id="1", name="travel_book", arguments={}), rt.cfg.limits)
    assert _needs_second(ToolCall(id="1", name="booking_cancel", arguments={}), rt.cfg.limits)


async def test_the_confirmation_shows_the_real_offer_and_goes_to_the_phone(rt, lite):
    rt.router = FakeRouter([json.dumps(CRIT)])
    await tools.call("hotel_search", {"description": "Řím"}, rt)
    seen = []
    rt.on_confirm_request = lambda cid, desc, phone=False: seen.append((cid, desc, phone))
    from jarvis.llm.base import ToolCall

    call = ToolCall(id="x", name="travel_book", arguments={"option": 1, "expected_total": 420, "currency": "EUR"})
    task = asyncio.create_task(rt.agent._ask_confirm(call))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if seen:
            break
    cid, desc, phone = seen[0]
    assert phone is True and desc.startswith("Zaplatit 420.00 EUR: Hotel Roma Centro") and "zrušení zdarma do 9. 12. 12:00" in desc
    assert "ZKUŠEBNÍ" in desc
    details = rt.agent.confirm_info[cid]["details"]
    assert any("Celkem: 420 EUR" in d for d in details) and any("ověřím znovu" in d for d in details)
    rt.agent.confirm(cid, False)
    assert await task is False


def _asker(rt, answers):
    asked = []

    async def ask(call, second=False, timeout=None, phone=False, why=""):
        asked.append((call.name, second))
        return answers.pop(0) if answers else False
    rt.agent._ask_confirm = ask
    return asked


async def test_agent_asks_twice_before_paying(rt, lite):
    rt.router = FakeRouter([json.dumps(CRIT)])
    await tools.call("hotel_search", {"description": "Řím"}, rt)
    asked = _asker(rt, [True, False])
    rt.router = FakeRouter([[("travel_book", {"option": 1, "expected_total": 420, "currency": "EUR"})], "Nezaplaceno."])
    await rt.agent.handle("beru jedničku")
    assert asked == [("travel_book", False), ("travel_book", True)]
    assert not any(p.endswith("/rates/prebook") for p in lite.paths())      # the second "no" stopped it before anything


async def test_a_wrong_amount_is_not_even_asked(rt, lite):
    rt.router = FakeRouter([json.dumps(CRIT)])
    await tools.call("hotel_search", {"description": "Řím"}, rt)
    asked = _asker(rt, [True, True])
    rt.router = FakeRouter([[("travel_book", {"option": 1, "expected_total": 99, "currency": "EUR"})], "Cena nesedí."])
    await rt.agent.handle("beru jedničku")
    assert asked == []


async def test_foreign_text_cannot_book(rt, lite):
    rt.router = FakeRouter([json.dumps(CRIT)])
    await tools.call("hotel_search", {"description": "Řím"}, rt)
    asked = _asker(rt, [True, True])
    rt.router = FakeRouter([[("clipboard_get", {})],
                            [("travel_book", {"option": 1, "expected_total": 420, "currency": "EUR"})], "Hotovo."])
    await rt.agent.handle("co mám ve schránce?")
    assert asked == [] and not any(p.endswith("/rates/book") for p in lite.paths())
    assert trust.money_blocked("travel_book", True, "přečti mail od hotelu a zarezervuj ho") == ""
    assert trust.money_blocked("travel_book", True, "co je v tom mailu?")
    assert trust.money_blocked("travel_book", False, "") == ""


def test_browser_never_clicks_pay_on_its_own(rt):
    from jarvis.tools import browser

    assert browser.money_click({"label": "Zaplatit 420 €"}) and browser.money_click({"label": "Complete booking"})
    assert not browser.money_click({"label": "Další fotky"})
    browser.SESSION.last_elements = {1: ("Hotel Roma Centro", "https://www.booking.com/hotel/it/roma.html"),
                                     2: ("Book now", "https://www.booking.com/hotel/it/roma.html#rooms"),
                                     3: ("Pokračovat", "https://secure.booking.com/checkout?id=1"),
                                     4: ("Sdílet na Facebook", "https://facebook.com/share")}
    assert not browser.money_click({"index": 1, "label": "Hotel Roma Centro"})      # "booking.com" is not a booking
    assert not browser._click_danger({"index": 1}) and not browser._click_danger({"index": 4})
    assert browser.money_click({"index": 2, "label": "detail"})                       # its real text decides
    assert browser.money_click({"index": 3, "label": "Pokračovat"}) and browser._click_danger({"index": 3})
    assert browser._click_danger({"index": 99})                                       # never seen → ask
    browser.SESSION.last_elements = {}
    rt.cfg.tools.full_trust = True
    tools.load_builtin()
    assert not trust.skip_confirm(rt, tools.REGISTRY["browser_click"], False, {"index": 3, "label": "Rezervovat"})


# ------------------------------------------------------------------------------------------ 13 cancel and change
async def test_cancel_check_and_cancel(rt, lite):
    rt.router = FakeRouter([json.dumps(CRIT)])
    await tools.call("hotel_search", {"description": "Řím"}, rt)
    await tools.call("travel_book", {"option": 1, "expected_total": 420, "currency": "EUR"}, rt)
    r = await tools.call("booking_cancel_check", {"booking_ref": "Roma"}, rt)
    assert r.ok and "zdarma do 9. 12. 12:00" in r.summary
    assert booking.confirm_text(rt, "booking_cancel", {"booking_ref": "Roma"}).startswith("Zrušit rezervaci: Hotel Roma Centro")
    r = await tools.call("booking_cancel", {"booking_ref": "Roma"}, rt)
    assert r.ok and "vrátí 420" in r.summary and booking.bookings(rt)[0]["status"] == "cancelled"
    assert booking.find_booking(rt, "Roma") is None


# ------------------------------------------------------------------------------------------ 16 flights through Duffel
OFFER = {"id": "off_1", "total_amount": "189.40", "total_currency": "EUR", "owner": {"name": "Example Air"},
         "passengers": [{"id": "pas_1"}], "conditions": {"refund_before_departure": {"allowed": False}},
         "slices": [{"segments": [{"origin": {"iata_code": "PRG"}, "destination": {"iata_code": "LIS"},
                                   "departing_at": "2027-03-12T07:05:00", "arriving_at": "2027-03-12T10:20:00",
                                   "marketing_carrier": {"iata_code": "EX", "name": "Example Air"},
                                   "marketing_carrier_flight_number": "123"}]}]}


async def test_flights_search_book_and_cancel(rt, monkeypatch):
    connectors.load()
    keys = {connectors.skey("duffel", "access_token"): "duffel_test_abc"}
    monkeypatch.setattr(secrets, "get", lambda k: keys.get(k, ""))
    seen = []

    def handler(req: httpx.Request):
        body = json.loads(req.content or b"{}")
        seen.append((req.method, req.url.path, body))
        assert req.headers["Duffel-Version"] == "v2" and req.headers["Authorization"] == "Bearer duffel_test_abc"
        p = req.url.path
        if p == "/air/offer_requests":
            assert body["data"]["slices"][0] == {"origin": "PRG", "destination": "LIS", "departure_date": "2027-03-12"}
            return httpx.Response(201, json={"data": {"offers": [OFFER, {**OFFER, "id": "off_2", "total_amount": "240.00"}]}})
        if p == "/air/offers/off_1":
            return httpx.Response(200, json={"data": OFFER})
        if p == "/air/orders":
            return httpx.Response(201, json={"data": {"id": "ord_1", "booking_reference": "RZ8P2K", "total_amount": "189.40",
                                                      "total_currency": "EUR", "live_mode": False}})
        if p == "/air/order_cancellations":
            return httpx.Response(201, json={"data": {"id": "ore_1", "refund_amount": "0.00", "refund_currency": "EUR"}})
        if p == "/air/order_cancellations/ore_1/actions/confirm":
            return httpx.Response(200, json={"data": {"id": "ore_1", "confirmed_at": "2026-11-24T10:00:00Z", "refund_amount": "0.00",
                                                      "refund_currency": "EUR"}})
        return httpx.Response(404, json={"errors": [{"message": "nope"}]})
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(handler))
    tools.load_builtin()
    rt.update_config({"booking": {"first_name": "Jan", "last_name": "Novák", "email": "jan@example.cz", "phone": "+420777000111",
                                  "born_on": "1990-05-01"}})
    rt.router = FakeRouter([json.dumps({"kind": "flight", "origin": "PRG", "destination": "LIS", "date": "2027-03-12"})])
    r = await tools.call("flight_search", {"description": "z Prahy do Lisabonu 12. 3."}, rt)
    assert r.ok and "1) Example Air: PRG→LIS 03-12 07:05 (přímý) – 189 EUR" in r.summary and "nejlevnější" in booking.offer(rt, 1)["why"]
    r = await tools.call("travel_book", {"option": 1, "expected_total": 189.4, "currency": "EUR"}, rt)
    assert r.ok and "RZ8P2K" in r.summary
    order = next(b for _, p, b in seen if p == "/air/orders")["data"]
    assert order["payments"] == [{"type": "balance", "amount": "189.40", "currency": "EUR"}]
    assert order["passengers"][0]["id"] == "pas_1" and order["passengers"][0]["born_on"] == "1990-05-01"
    from jarvis import travel

    assert travel.upcoming(rt, now=dt.datetime(2027, 3, 1).timestamp())[0]["number"] == "EX 123"   # delay, gate, when to leave
    q = await tools.call("booking_cancel_check", {"booking_ref": "Example"}, rt)
    assert q.ok and "vrátí 0.00 EUR" in q.summary
    c = await tools.call("booking_cancel", {"booking_ref": "Example"}, rt)
    assert c.ok and any(p.endswith("/actions/confirm") for _, p, _ in seen)


# ------------------------------------------------------------------------------------------ 10–12, 15, 17, 19 after
def _booked(rt, **kw):
    b = {"provider": "liteapi", "ref": "BK9", "kind": "hotel", "name": "Hotel Lisboa", "city": "Lisabon", "start": "2026-12-01",
         "end": "2026-12-04", "total": 300.0, "currency": "EUR", "refundable": 1, "free_cancel_until": "2026-11-25T12:00",
         "pay_at_property": 0, "status": "confirmed", "sandbox": 0, "data": json.dumps({"offer": {"hotel_id": "lp1"}}),
         "created": dt.datetime(2026, 11, 20).timestamp(), "business": 0}
    b.update(kw)
    booking._db(rt).exec("INSERT INTO bookings (" + ", ".join(b) + ") VALUES (" + ",".join("?" * len(b)) + ")", tuple(b.values()))
    return booking.find_booking(rt, b["name"])


async def test_reminders_once_each(rt):
    b = _booked(rt)
    rt.router = FakeRouter(["pas, nabíječka, plavky"])
    said = await tripcare.reminders(rt, now=dt.datetime(2026, 11, 24, 18).timestamp())
    assert any("končí zítra" in s for s in said)
    again = await tripcare.reminders(rt, now=dt.datetime(2026, 11, 24, 19).timestamp())
    assert not any("končí zítra" in s for s in again)
    late = await tripcare.reminders(rt, now=dt.datetime(2026, 11, 25, 10).timestamp())
    assert any("Poslední 3 hodiny" in s for s in late)
    packing = await tripcare.reminders(rt, now=dt.datetime(2026, 11, 30, 12).timestamp())
    assert any(s.startswith("Na zítřejší cestu") and "plavky" in s for s in packing)
    assert b["id"]


def test_passport_warning(rt):
    rt.update_config({"booking": {"passport_until": "2027-03-01"}})
    assert "6 měsíců" in tripcare.passport_problem(rt, {"end": "2026-12-04", "city": "Lisabon"})
    rt.update_config({"booking": {"passport_until": "2030-01-01"}})
    assert tripcare.passport_problem(rt, {"end": "2026-12-04"}) == ""


async def test_a_booked_hotel_got_cheaper(rt, monkeypatch):
    _booked(rt, free_cancel_until="2099-01-01T12:00")
    connectors.load()
    keys = {connectors.skey("liteapi", "api_key"): "sand_test-key"}
    monkeypatch.setattr(secrets, "get", lambda k: keys.get(k, ""))
    cheap = {"data": [{"hotelId": "lp1", "roomTypes": [{"offerId": "N1", "rates": [{"retailRate": {"total": [{"amount": 270.0, "currency": "EUR"}]}}]}]}]}
    tr = httpx.MockTransport(lambda r: httpx.Response(200, json=cheap))
    said = await tripcare.price_watch(rt, transport=tr)
    assert said and "o 30 EUR levnější" in said[0] and "Chceš přerezervovat" in said[0]
    assert await tripcare.price_watch(rt, transport=tr) == []           # told once


async def test_price_watches(rt):
    wid = tripcare.add_watch(rt, "hotel", {"city": "Řím", "checkin": "2099-03-12"}, 4000, "CZK")
    assert tripcare.watches(rt)[0]["id"] == wid

    async def dear(rt_, kind, c):
        return (5200.0, "CZK")

    async def cheap(rt_, kind, c):
        return (150.0, "EUR")                                            # ≈ 3 750 Kč
    assert await tripcare.check_watches(rt, dear) == [] and tripcare.watches(rt)[0]["last_price"] == 5200
    said = await tripcare.check_watches(rt, cheap)
    assert said and "Řím je teď za 150 EUR" in said[0] and tripcare.watches(rt) == []
    tripcare.add_watch(rt, "hotel", {"city": "Paříž", "checkin": "2020-01-01"}, 4000, "CZK")
    assert await tripcare.check_watches(rt, cheap) == [] and tripcare.watches(rt) == []   # past dates stop by themselves


async def test_spend_and_the_page(rt):
    _booked(rt, created=dt.datetime(2026, 2, 3).timestamp(), business=1)
    _booked(rt, ref="BK10", name="Hotel B", created=dt.datetime(2026, 5, 3).timestamp())
    _booked(rt, ref="BK11", name="Zkušební", created=dt.datetime(2026, 5, 4).timestamp(), sandbox=1)
    s = tripcare.spend(rt, 2026)
    assert s["total_czk"] == 15000 and s["business_czk"] == 7500 and s["by_month"] == {"02": 7500, "05": 7500}
    r = await tools.call("travel_spend", {"year": 2026}, rt)
    assert "15 000 Kč" in r.summary and "služebně 7 500 Kč" in r.summary
    from jarvis.server import handlers
    from jarvis.server.handlers.travelh import travel_get

    sent = []

    class C:
        pass
    c = C()
    c.rt = rt

    async def send(t, **d):
        sent.append((t, d))
    c.send = send
    await travel_get(c, {"past": True})
    assert sent[0][0] == "travel" and sent[0][1]["spend"]["year"] == dt.date.today().year and len(sent[0][1]["bookings"]) == 3
    handlers.load()
    assert "travel_get" in handlers.LOCAL_ONLY and "travel_watch_stop" in handlers.LOCAL_ONLY


def test_traveller_details_stay_on_the_pc(rt):
    from jarvis import config

    rt.update_config({"booking": {"first_name": "Jan", "born_on": "1990-05-01"}})
    assert config.public_dump(rt.cfg)["booking"]["first_name"] == "Jan"
    remote = config.public_dump(rt.cfg, local=False)["booking"]
    assert "first_name" not in remote and "born_on" not in remote and remote["max_per_booking"] == 15000


def test_words_offer_the_travel_tools():
    assert "hotel_search" in select.intents("najdi mi hotel v Římě na víkend")
    assert "flight_search" in select.intents("najdi letenky z Prahy do Lisabonu")
    assert "travel_book" in select.intents("beru dvojku")
    assert "booking_cancel_check" in select.intents("zruš tu rezervaci hotelu")
    assert "travel_watch" in select.intents("dej vědět, až bude cena pod 4000")
    assert "travel_spend" in select.intents("kolik jsem letos utratil za cesty")
    assert "travel_book" not in select.intents("chci to vidět")


async def test_duffel_stays_book_the_rate_you_saw(rt, monkeypatch):
    connectors.load()
    keys = {connectors.skey("duffel", "access_token"): "duffel_test_abc"}
    monkeypatch.setattr(secrets, "get", lambda k: keys.get(k, ""))
    seen = []

    def handler(req: httpx.Request):
        body = json.loads(req.content or b"{}")
        seen.append((req.url.path, body))
        p = req.url.path
        if p == "/stays/search":
            assert body["data"]["location"]["geographic_coordinates"] == {"latitude": 41.9, "longitude": 12.49}
            return httpx.Response(200, json={"data": {"results": [{"id": "srr_1", "cheapest_rate_total_amount": "300.00",
                                                                   "cheapest_rate_currency": "EUR", "accommodation": {
                                                                       "id": "acc_1", "name": "Casa Duffel", "rating": 3, "review_score": 8.1,
                                                                       "location": {"geographic_coordinates": {"latitude": 41.9, "longitude": 12.49},
                                                                                    "address": {"city_name": "Rome"}}}}]}})
        if p == "/stays/search_results/srr_1/actions/fetch_all_rates":
            return httpx.Response(200, json={"data": {"accommodation": {"rooms": [{"rates": [
                {"id": "rat_cheap", "total_amount": "300.00", "total_currency": "EUR", "board_type": "room_only", "payment_type": "pay_now",
                 "cancellation_timeline": [{"before": "2026-12-08T23:59:00Z", "refund_amount": "300.00"}]},
                {"id": "rat_dear", "total_amount": "380.00", "total_currency": "EUR", "board_type": "breakfast", "payment_type": "pay_now",
                 "cancellation_timeline": []}]}]}}})
        if p == "/stays/quotes":
            assert body["data"] == {"rate_id": "rat_cheap"}                 # the price you were shown, not another rate
            return httpx.Response(201, json={"data": {"id": "quo_1", "total_amount": "300.00", "total_currency": "EUR"}})
        if p == "/stays/bookings":
            assert body["data"]["quote_id"] == "quo_1" and body["data"]["guests"] == [{"given_name": "Jan", "family_name": "Novák"}]
            return httpx.Response(201, json={"data": {"id": "bok_1", "status": "confirmed", "reference": "DUF123"}})
        return httpx.Response(404, json={"errors": [{"message": "nope"}]})
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(handler))

    async def geocode(rt_, name):
        return (41.9, 12.49)
    from jarvis import travel

    monkeypatch.setattr(travel, "geocode", geocode)
    tools.load_builtin()
    rt.update_config({"booking": {"first_name": "Jan", "last_name": "Novák", "email": "jan@example.cz", "phone": "+420777000111"}})
    rt.router = FakeRouter([json.dumps(CRIT)])
    r = await tools.call("hotel_search", {"description": "Řím"}, rt)
    assert r.ok and "Casa Duffel" in r.summary
    r = await tools.call("travel_book", {"option": 1, "expected_total": 300, "currency": "EUR"}, rt)
    assert r.ok and "DUF123" in r.summary
    b = booking.bookings(rt)[0]
    assert b["refundable"] == 1 and b["free_cancel_until"] == "2026-12-08T23:59"       # the real terms of the booked rate
