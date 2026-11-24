"""3.18 (E14–E16): GLS with its API key, "vyzvedni do čtvrtka", Web Push for the iPhone web app, the Wear OS watch."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from jarvis import connectors, parcels, secrets, watchpair, webpush


# ------------------------------------------------------------------------------------------ E16 GLS + pickup reminders
GLS = {"tuStatus": [{"progressBar": {"statusInfo": "INTRANSIT", "statusText": "Na cestě"}, "history": [
    {"date": "2026-11-23", "time": "08:10:00", "address": {"city": "Jihlava"}, "evtDscr": "Zásilka převzata v depu"},
    {"date": "2026-11-24", "time": "06:40:00", "address": {"city": "Brno"}, "evtDscr": "Zásilka je na cestě k příjemci"}]}]}


def test_gls_parser():
    from jarvis.connectors import gls

    assert gls.status_of(GLS) == ("Zásilka je na cestě k příjemci (Brno)", "2026-11-24 06:40")
    assert gls.status_of({"tuStatus": [{"progressBar": {"statusText": "Doručeno"}}]}) == ("Doručeno", "")
    assert gls.status_of({}) == ("", "") and gls.status_of(None) == ("", "")


async def test_gls_live_with_the_key(rt, monkeypatch):
    connectors.load()
    keys = {connectors.skey("gls", "api_key"): "k-123"}
    monkeypatch.setattr(secrets, "get", lambda k: keys.get(k, ""))
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        assert req.headers["x-api-key"] == "k-123" and req.url.params["match"] == "12345678901"
        return httpx.Response(200, json=GLS)
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(handler))
    text, when = await parcels.track(rt, {"carrier": "gls", "number": "12345678901"})
    assert "Brno" in text and "/CZ/cs/rstt001" in str(seen[0].url)
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(403, json={"message": "Forbidden"})))
    from jarvis import tools

    tools.load_builtin()
    r = await tools.call("gls_status", {"number": "12345678901"}, rt)
    assert not r.ok and "klíč" in r.summary


def test_pickup_deadline_and_reminder(rt):
    assert parcels.pickup_until("", "2026-11-27T23:59:00") == "2026-11-27"
    assert parcels.pickup_until("Zásilka je uložena do 27.11.2026 na poště Brno 2") == "2026-11-27"
    assert parcels.pickup_until("na cestě") == ""
    parcels.add(rt, "zasilkovna", "Z1234567890", "Alza")
    rt.db.exec("UPDATE parcels SET state='ready', pickup_until='2026-11-27' WHERE number='Z1234567890'")
    told = []
    rt.notify = lambda title, body, **kw: told.append(body)
    import datetime as dt

    two_days = dt.datetime(2026, 11, 25, 9).timestamp()
    assert parcels.remind_pickups(rt, two_days) == []                         # not yet
    day_before = dt.datetime(2026, 11, 26, 9).timestamp()
    said = parcels.remind_pickups(rt, day_before)
    assert said and "zítra" in said[0] and "v pátek 27. 11." in said[0] and "Alza" in said[0]
    assert parcels.remind_pickups(rt, day_before + 3600) == []                # once


# ------------------------------------------------------------------------------------------ E15 Web Push (iPhone)
def _decrypt(body: bytes, ua_key, auth: bytes) -> bytes:
    """The phone's side of RFC 8291 (to prove the PC encrypted it right)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, rs, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    as_pub = body[21:21 + idlen]
    ct = body[21 + idlen:]
    ua_pub = ua_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = ua_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    ikm = webpush._hkdf(auth, shared, b"WebPush: info\x00" + ua_pub + as_pub, 32)
    cek = webpush._hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = webpush._hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    assert rs == 4096
    plain = AESGCM(cek).decrypt(nonce, ct, None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def _phone():
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    return key, auth, {"endpoint": "https://web.push.apple.com/QGuQyavXutnMH", "keys": {"p256dh": webpush.b64u(pub), "auth": webpush.b64u(auth)}}


def test_encrypt_round_trip_and_vapid(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(secrets, "get", lambda k: store.get(k, ""))
    monkeypatch.setattr(secrets, "set", lambda k, v: store.__setitem__(k, v))
    key, auth, sub = _phone()
    body = webpush.encrypt(b'{"title":"JARVIS","body":"Ahoj"}', sub["keys"]["p256dh"], sub["keys"]["auth"])
    assert json.loads(_decrypt(body, key, auth)) == {"title": "JARVIS", "body": "Ahoj"}
    hdr = webpush.vapid_header(sub["endpoint"])
    t = hdr.split("t=")[1].split(",")[0]
    claims = json.loads(base64.urlsafe_b64decode(t.split(".")[1] + "=="))
    assert claims["aud"] == "https://web.push.apple.com" and claims["exp"] > 0
    assert hdr.endswith(webpush.public_key()) and len(webpush.unb64u(webpush.public_key())) == 65
    assert webpush.public_key() == webpush.public_key()                          # the same key every time


async def test_subscribe_send_and_forget_gone_phones(rt, monkeypatch):
    store: dict = {}
    monkeypatch.setattr(secrets, "get", lambda k: store.get(k, ""))
    monkeypatch.setattr(secrets, "set", lambda k, v: store.__setitem__(k, v))
    key, auth, sub = _phone()
    assert not webpush.subscribe(rt, {**sub, "endpoint": "https://evil.example/push"})         # only real push services
    assert not webpush.subscribe(rt, {**sub, "endpoint": "http://web.push.apple.com/x"})
    assert webpush.subscribe(rt, sub, "iPhone") and len(webpush.subscriptions(rt)) == 1
    got = []

    def handler(req: httpx.Request):
        got.append(json.loads(_decrypt(req.content, key, auth)))
        assert req.headers["Content-Encoding"] == "aes128gcm" and req.headers["Authorization"].startswith("vapid t=")
        return httpx.Response(201)
    assert await webpush.send(rt, "Vyzvedni balík", "Čeká do pátku.", transport=httpx.MockTransport(handler)) == 1
    assert got[0]["title"] == "Vyzvedni balík" and got[0]["body"] == "Čeká do pátku."
    await webpush.send(rt, "x", "y", transport=httpx.MockTransport(lambda r: httpx.Response(410)))
    assert webpush.subscriptions(rt) == []                                       # gone → removed


def test_service_worker_and_button_exist():
    root = Path(__file__).resolve().parents[2] / "web"
    sw = (root / "public" / "sw.js").read_text(encoding="utf-8")
    assert "showNotification" in sw and "notificationclick" in sw
    assert "webpush_subscribe" in (root / "src" / "mobile" / "main.ts").read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------ E14 the watch
def test_watch_pairing_code_rules(rt):
    info = watchpair.start(rt)
    assert len(info["code"]) == 6 and info["code"].isdigit() and info["port"] == rt.cfg.phone.port
    for _ in range(4):
        assert watchpair.redeem(rt, "000000" if info["code"] != "000000" else "111111")[1] == "Špatný kód."
    assert "pokusů" in watchpair.redeem(rt, "999999" if info["code"] != "999999" else "888888")[1]
    assert "vypršel" in watchpair.redeem(rt, info["code"])[1]                     # the 5th wrong try ended it
    info = watchpair.start(rt)
    token, why = watchpair.redeem(rt, info["code"], "Galaxy Watch")
    assert token and why == "" and any(d.name == "Galaxy Watch" for d in rt.cfg.phone.devices)
    assert "vypršel" in watchpair.redeem(rt, info["code"])[1]                     # used once


async def test_watch_http_api(rt):
    from fastapi.testclient import TestClient

    from conftest import FakeRouter
    from jarvis.server.app import create_app

    rt.router = FakeRouter(["Dnes máš poradu v deset."])
    app = create_app(rt, manage_runtime=False)
    away = TestClient(app, client=("192.168.1.30", 5000))
    assert away.post("/api/watch/pair", json={"code": "123456"}).status_code == 403   # no code started on the PC
    assert away.get("/api/watch/status").status_code == 401
    code = watchpair.start(rt)["code"]
    r = away.post("/api/watch/pair", json={"code": code, "name": "Hodinky"})
    assert r.status_code == 200 and r.json()["token"]
    auth = {"Authorization": f"Bearer {r.json()['token']}"}
    assert away.get("/api/watch/status", headers=auth).json()["line"]
    ans = away.post("/api/watch/ask", json={"text": "co mám dnes?"}, headers=auth).json()
    assert ans["answer"] == "Dnes máš poradu v deset."
    assert "hodinek" in rt.router.calls[0]["messages"][0]["content"]             # short answers for the watch


def test_watch_project_is_separate_and_complete():
    w = Path(__file__).resolve().parents[2] / "mobile" / "wear"
    for f in ("settings.gradle", "build.gradle", "app/build.gradle", "app/src/main/AndroidManifest.xml",
              "app/src/main/java/cz/adamekk/jarvis/wear/MainActivity.java", "app/src/main/java/cz/adamekk/jarvis/wear/JarvisTile.java"):
        assert (w / f).exists(), f
    man = (w / "app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    assert "android.hardware.type.watch" in man and "BIND_TILE_PROVIDER" in man
    ci = (w.parents[1] / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    assert "gradle -p mobile/wear assembleDebug" in ci


@pytest.mark.parametrize("hostport,base", [("192.168.1.20", "http://192.168.1.20:8765"), ("http://pc.local:9000/", "http://pc.local:9000")])
def test_watch_address_rule(hostport, base):
    """The same rule as Api.base() in the watch app (kept in sync by hand)."""
    import re

    h = re.sub(r"/+$", "", re.sub(r"^https?://", "", hostport.strip()))
    if ":" not in h:
        h += ":8765"
    assert "http://" + h == base
