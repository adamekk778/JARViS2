"""3.4 phone link: JARVIS rings you, dials, SMS, WhatsApp, your phone's messages on the PC, Twilio fallback."""
import asyncio

import httpx
from conftest import FakeRouter, drain
from fastapi.testclient import TestClient

from jarvis import config, tools
from jarvis.phone import twiml_say, twilio_ready
from jarvis.server.app import create_app

REMOTE = ("192.168.1.50", 5000)


async def fake_phone(rt, answer="done", seen=None):
    """A phone service: long-polls and acks every command like the Android app does."""
    while True:
        for cmd in await rt.phone.poll(wait=2):
            if seen is not None:
                seen.append(cmd)
            rt.phone.ack(cmd["id"], answer(cmd) if callable(answer) else answer)


async def test_call_me_rings_through_the_background_link(rt):
    seen = []
    task = asyncio.create_task(fake_phone(rt, lambda c: "answered" if c["kind"] == "ring" else "done", seen))
    await asyncio.sleep(0.05)
    assert rt.phone.link_alive()
    q = rt.bus.subscribe()
    r = await tools.call("call_me", {"message": "Pane, máte schůzku za 10 minut."}, rt)
    await asyncio.sleep(0.1)
    task.cancel()
    assert r.ok and seen[0]["kind"] == "ring" and seen[0]["text"] == "Pane, máte schůzku za 10 minut."
    ev = drain(q)
    assert any(e["type"] == "phone_ack" and e["state"] == "answered" for e in ev)
    assert not any(e["type"] == "phone_cmd" for e in ev)     # the link was alive → no duplicate over the WebSocket


async def test_call_me_without_any_phone_explains_how(rt):
    r = await tools.call("call_me", {"message": "x"}, rt)
    assert not r.ok and "Spojení na pozadí" in r.summary


async def test_call_me_later_is_scheduled(rt):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    r = await tools.call("call_me", {"message": "Vyndej prádlo", "in_minutes": 30}, rt)
    job = rt.scheduler.list()[0]
    assert r.ok and job["kind"] == "ring" and job["payload"]["text"] == "Vyndej prádlo"
    seen = []
    task = asyncio.create_task(fake_phone(rt, "answered", seen))
    await asyncio.sleep(0.05)
    await rt.scheduler._run(job)
    await asyncio.sleep(0.1)
    task.cancel()
    assert seen and seen[0]["text"] == "Vyndej prádlo"


async def test_dial_sms_whatsapp_results(rt):
    states = {"dial": "calling", "sms": "sent", "whatsapp": "notfound"}
    seen = []
    task = asyncio.create_task(fake_phone(rt, lambda c: states[c["kind"]], seen))
    await asyncio.sleep(0.05)
    assert (await tools.call("phone_call", {"who": "máma"}, rt)).summary == "Vytáčím máma na vašem telefonu."
    assert tools.is_dangerous(tools.REGISTRY["send_sms"], {}, [], [], rt)
    assert tools.details_for(tools.REGISTRY["send_sms"], {"to": "Petr", "text": "Jsem tam za 5"}, rt)[0] == "Komu: Petr"
    assert (await tools.call("send_sms", {"to": "Petr", "text": "Jsem tam za 5"}, rt)).summary == "SMS pro Petr odeslána."
    wa = await tools.call("whatsapp_message", {"to": "Pepa", "text": "Ahoj"}, rt)
    task.cancel()
    assert not wa.ok and "nenašel" in wa.summary
    assert [c["kind"] for c in seen] == ["dial", "sms", "whatsapp"] and seen[1]["text"] == "Jsem tam za 5"


async def test_app_in_foreground_gets_commands_over_websocket_when_no_service(rt):
    rt.clients["x"] = {"client": "mobile"}
    q = rt.bus.subscribe()
    t = asyncio.create_task(tools.call("phone_call", {"who": "máma"}, rt))
    await asyncio.sleep(0.05)
    cmd = next(e for e in drain(q) if e["type"] == "phone_cmd")
    assert cmd["target"] == "mobile" and cmd["kind"] == "dial" and cmd["who"] == "máma"
    rt.phone.ack(cmd["id"], "calling")
    assert (await t).ok


async def test_reply_from_the_call_goes_to_jarvis(rt):
    rt.router = FakeRouter(["Dobře, posunu to."])
    cmd = rt.phone.send("ring", text="Máte schůzku.")
    await rt.phone.poll(wait=0)
    rt.phone.ack(cmd["id"], "reply", "posuň ji o hodinu")
    for _ in range(50):
        await asyncio.sleep(0.02)
        if rt.router.calls:
            break
    assert rt.router.calls[0]["messages"][-1]["content"] == "posuň ji o hodinu"


def test_phone_notifications_announced_and_listed(rt, monkeypatch):
    said = []
    monkeypatch.setattr(rt, "notify", lambda title, body, **k: said.append((title, body)))
    n = {"package": "com.whatsapp", "app": "WhatsApp", "title": "Máma", "text": "Přijdeš na oběd?", "ts": 1}
    assert rt.phone.on_notification(n)["messaging"]
    assert rt.phone.on_notification(n) is None                      # the same message again → ignored
    rt.phone.on_notification({"package": "com.google.android.dialer", "title": "Petr Novák", "text": "Příchozí hovor", "category": "call"})
    rt.phone.on_notification({"package": "com.some.game", "title": "Bonus", "text": "Vyzvedni si odměnu"})
    assert said == [("WhatsApp (telefon)", "Máma: Přijdeš na oběd?"), ("Telefon (telefon)", "Volá vám Petr Novák.")]


async def test_phone_messages_tool(rt):
    rt.phone.on_notification({"package": "com.whatsapp", "title": "Máma", "text": "Přijdeš?", "ts": 1700000000})
    rt.phone.on_notification({"package": "com.android.mms", "title": "Banka", "text": "Kód 1234", "ts": 1700000060})
    r = await tools.call("phone_messages", {"app": "whatsapp"}, rt)
    assert r.ok and "WhatsApp – Máma: Přijdeš?" in r.summary and "Banka" not in r.summary and "jen data" in r.summary


def test_http_endpoints_need_the_pairing_token(rt):
    app = create_app(rt, manage_runtime=False)
    c = TestClient(app, client=REMOTE)
    assert c.get("/api/phone/poll?wait=0").status_code == 401
    assert c.post("/api/phone/notification", json={"package": "com.whatsapp", "title": "x", "text": "y"}).status_code == 401
    hdr = {"Authorization": f"Bearer {rt.cfg.phone.token}"}
    cmd = rt.phone.send("dial", who="máma")
    r = c.get("/api/phone/poll?wait=0", headers=hdr)
    assert r.status_code == 200 and r.json()["commands"][0]["id"] == cmd["id"]
    assert c.post("/api/phone/ack", json={"id": cmd["id"], "state": "calling"}, headers=hdr).json() == {"ok": True}
    assert c.post("/api/phone/notification", json={"package": "com.whatsapp", "title": "Máma", "text": "Ahoj"}, headers=hdr).status_code == 200
    assert rt.phone.notifications[0]["text"] == "Ahoj"


async def test_twilio_fallback_calls_your_number(rt, monkeypatch):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(201, json={"sid": "CA123"})

    rt.transport = httpx.MockTransport(handler)
    monkeypatch.setattr("jarvis.secrets.get", lambda k: "tok" if k == "twilio_token" else "")
    rt.cfg = config.apply_patch(rt.cfg, {"phone_link": {"twilio_sid": "AC1", "twilio_from": "+15550001", "my_number": "+420777111222"}})
    assert twilio_ready(rt)
    res = await rt.phone.ring("Pane, hoří server.", wait=False)
    await asyncio.sleep(0)
    import jarvis.phone as ph

    await ph.twilio_call(rt, "Pane, hoří server.")
    body = calls[0].content.decode()
    assert res["via"] == "app" and "To=%2B420777111222" in body and "cs-CZ" in body and calls[0].url.path.endswith("/Accounts/AC1/Calls.json")
    assert "&lt;" not in twiml_say("ok") and "&amp;" in twiml_say("A & B")
