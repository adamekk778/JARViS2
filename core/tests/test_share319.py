"""3.19 (návrhy 15, 16): the watch tile shows the next trip and a payment waiting (approved only on the phone), and a
read-only trip link for the family – no price, no booking number, expires after the trip, revocable, always asked."""
from __future__ import annotations

import pytest

import datetime as dt
import json
import time

from fastapi.testclient import TestClient

from jarvis import booking, tools, tripshare, watchpair



@pytest.fixture(autouse=True)
def _pinned_day():
    """3.20 the example data (a hotel from 11. 12. 2026…) was written on 24. 11. 2026: the travel parts see that day."""
    from jarvis import clock

    clock.pin(dt.datetime(2026, 11, 24, 10, 0))
    yield
    clock.pin(None)

def _hotel(rt, start: str, end: str, **kw):
    b = {"provider": "liteapi", "ref": "BK5", "kind": "hotel", "name": "Hotel Lisboa", "city": "Lisabon", "start": start, "end": end,
         "total": 300.0, "currency": "EUR", "refundable": 1, "free_cancel_until": "", "pay_at_property": 0, "status": "confirmed",
         "sandbox": 0, "data": json.dumps({"offer": {"legs": [{"flight": "TP1281", "from": "PRG", "to": "LIS",
                                                               "dep": start + "T07:05"}]}, "confirmation": "SECRET-77"}),
         "created": 0, "business": 0}
    b.update(kw)
    booking._db(rt).exec("INSERT INTO bookings (" + ", ".join(b) + ") VALUES (" + ",".join("?" * len(b)) + ")", tuple(b.values()))
    return booking.find_booking(rt, b["name"])


# ------------------------------------------------------------------------------------------ 15 the watch
def test_watch_tile_shows_the_trip_and_a_waiting_payment(rt):
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    _hotel(rt, tomorrow, "2099-01-01")
    assert watchpair.next_trip(rt) == "Hotel Lisboa zítra"
    rt.agent.confirm_info["x"] = {"tool": "travel_book"}
    line = watchpair.status(rt)["line"]
    assert line.startswith("Potvrď platbu v telefonu") and "Hotel Lisboa" in line
    rt.agent.confirm_info.clear()
    from jarvis import travel

    dep = time.time() + 3 * 3600
    travel.add(rt, {"kind": "flight", "number": "FR 1234", "dep": dep, "arr": dep + 7200, "origin": "PRG", "dest": "BCN",
                    "info": {"gate": "B12"}})
    assert watchpair.next_trip(rt) == "Let FR 1234 za 3 h · gate B12"


# ------------------------------------------------------------------------------------------ 16 sharing a trip
def test_shared_trip_page_is_safe_and_expires(rt):
    b = _hotel(rt, "2099-01-01", "2099-01-05")
    r = tripshare.create(rt, b)
    assert "/share/" in r["url"] and r["public"] is False and len(r["token"]) >= 30
    page = tripshare.page(rt, r["token"])
    assert "Hotel Lisboa" in page and "TP1281" in page
    assert "SECRET-77" not in page and "300" not in page and "EUR" not in page                   # no booking number, no price
    assert tripshare.page(rt, "nope") is None
    assert tripshare.page(rt, r["token"], now=dt.datetime(2099, 1, 7).timestamp()) is None       # the day after the trip: gone
    r2 = tripshare.create(rt, b)
    assert tripshare.stop(rt, b["id"]) == 1 and tripshare.page(rt, r2["token"]) is None


def test_shared_trip_route_and_public_address(rt):
    from jarvis.server.app import create_app

    b = _hotel(rt, "2099-01-01", "2099-01-05")
    rt.update_config({"phone_link": {"public_url": "https://jarvis.example.net/"}})
    r = tripshare.create(rt, b)
    assert r["public"] and r["url"].startswith("https://jarvis.example.net/share/")
    app = create_app(rt, manage_runtime=False)
    away = TestClient(app, client=("203.0.113.9", 5000))                                          # from outside, no token
    res = away.get(f"/share/{r['token']}")
    assert res.status_code == 200 and "Hotel Lisboa" in res.text and res.headers["cache-control"] == "no-store"
    assert res.headers["x-robots-tag"] == "noindex"
    assert away.get("/share/abc").status_code == 404


def test_sharing_always_asks(rt):
    tools.load_builtin()
    spec = tools.REGISTRY["trip_share"]
    assert tools.is_dangerous(spec, {"booking_ref": "x"}) and not tools.is_dangerous(spec, {"action": "stop"})
    from jarvis.permissions import is_reading

    assert not is_reading(spec)                                       # foreign text cannot make a link without you
