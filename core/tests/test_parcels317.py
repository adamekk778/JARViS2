"""3.17 Zásilky živě (návrh 19): DPD through its public tracking, PPL through its official API (Client ID from PPL),
GLS stays a link (its open tracking was closed). A fake internet here – the real services were not reachable."""
from __future__ import annotations

import httpx

from jarvis import connectors, parcels, secrets, tools
from jarvis.connectors import ppl

DPD = {"parcellifecycleResponse": {"parcelLifeCycleData": {
    "statusInfo": [{"status": "ACCEPTED", "label": "Převzato", "isCurrentStatus": False},
                   {"status": "PICKUP", "label": "Připraveno k vyzvednutí", "isCurrentStatus": True, "date": "24.11.2026"}],
    "scanInfo": {"scan": [
        {"date": "2026-11-23T08:10:00", "scanData": {"location": "Praha"}, "scanDescription": {"content": ["Zásilka převzata"]}},
        {"date": "2026-11-24T10:05:00", "scanData": {"location": "Pickup Brno"},
         "scanDescription": {"content": ["Zásilka je připravena k vyzvednutí"]}}]}}}}
PPL = [{"shipmentNumber": "40123456789", "trackAndTrace": {"events": [
    {"code": "1", "name": "Zásilka převzata od odesílatele", "eventDate": "2026-11-23T07:00:00"},
    {"code": "5", "name": "Zásilka doručena", "eventDate": "2026-11-24T13:20:00"}]}}]


def test_parsers():
    assert parcels.dpd_status(DPD) == ("Zásilka je připravena k vyzvednutí (Pickup Brno)", "2026-11-24 10:05")
    only_status = {"parcellifecycleResponse": {"parcelLifeCycleData": {"statusInfo": DPD["parcellifecycleResponse"]
                                                                       ["parcelLifeCycleData"]["statusInfo"]}}}
    assert parcels.dpd_status(only_status)[0] == "Připraveno k vyzvednutí"
    assert parcels.dpd_status({"parcellifecycleResponse": {"parcelLifeCycleData": None}}) == ("", "")
    assert parcels.dpd_status({"error": "x"}) == ("", "")
    assert ppl.status_of(PPL) == ("Zásilka doručena", "2026-11-24 13:20")
    assert ppl.status_of({"items": [{"shipmentState": "Delivered"}]}) == ("Delivered", "")
    assert ppl.status_of([]) == ("", "") and ppl.status_of(None) == ("", "")


async def test_dpd_and_ppl_refresh(rt, monkeypatch):
    connectors.load()
    keys = {connectors.skey("ppl", "client_id"): "cid", connectors.skey("ppl", "client_secret"): "sec"}
    monkeypatch.setattr(secrets, "get", lambda k: keys.get(k, ""))
    ppl._TOKEN.update(value="", until=0.0)
    seen: list[str] = []

    def handler(req: httpx.Request):
        seen.append(f"{req.method} {req.url.host}{req.url.path}")
        if req.url.host == "tracking.dpd.de":
            assert req.url.path == "/rest/plc/cs_CZ/01234567890123"
            return httpx.Response(200, json=DPD)
        if req.url.path.endswith("/login/getAccessToken"):
            assert b"client_id=cid" in req.content and b"scope=myapi2" in req.content
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 1800})
        if req.url.path.endswith("/shipment"):
            assert req.headers["Authorization"] == "Bearer tok" and req.url.params["ShipmentNumbers"] == "40123456789"
            return httpx.Response(200, json=PPL)
        return httpx.Response(404)
    rt.transport = httpx.MockTransport(handler)
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(handler))
    said: list[str] = []
    rt.notify = lambda title, text, **kw: said.append(text)
    parcels.add(rt, "dpd", "01234567890123", "Alza")
    parcels.add(rt, "ppl", "40123456789")
    parcels.add(rt, "gls", "12345678901")
    changed = {p["carrier"]: p for p in await parcels.refresh(rt)}
    assert changed["dpd"]["state"] == "ready" and changed["ppl"]["state"] == "done" and "gls" not in changed
    assert any("DPD" in t and "vyzvednutí" in t for t in said) and any("PPL" in t and "doručena" in t for t in said)
    assert not any("gls" in s for s in seen)                                    # GLS: only the link
    assert "gls-group.com" in parcels.summary(rt)
    await parcels.refresh(rt)
    assert sum(1 for s in seen if s.endswith("/login/getAccessToken")) == 1     # the token is kept


async def test_ppl_without_credentials_keeps_the_link(rt, monkeypatch):
    connectors.load()
    monkeypatch.setattr(secrets, "get", lambda k: "")
    calls: list = []
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500)))
    assert await parcels.track(rt, {"carrier": "ppl", "number": "40123456789"}) == ("", "")
    assert calls == []
    tools.load_builtin()
    r = await tools.call("ppl_status", {"number": "40123456789"}, rt)
    assert not r.ok and "Propojení" in r.summary


async def test_ppl_wrong_credentials(rt, monkeypatch):
    connectors.load()
    keys = {connectors.skey("ppl", "client_id"): "cid", connectors.skey("ppl", "client_secret"): "bad"}
    monkeypatch.setattr(secrets, "get", lambda k: keys.get(k, ""))
    ppl._TOKEN.update(value="", until=0.0)
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(
        lambda r: httpx.Response(401, json={"error": "invalid_client"})))
    tools.load_builtin()
    r = await tools.call("ppl_status", {"number": "40123456789"}, rt)
    assert not r.ok and "Client ID" in r.summary and "bad" not in r.summary
