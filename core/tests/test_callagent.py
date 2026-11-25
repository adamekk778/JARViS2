"""3.14 AI sekretářka, volání za tebe, shrnutí chatů."""
import asyncio
import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import httpx
import pytest
from conftest import FakeRouter
from fastapi.testclient import TestClient

from jarvis import callagent, chatdigest, tools

tools.load_builtin()
PUBLIC = "https://jarvis.example.cz"


def twilio_sig(token, url, params):
    """Twilio's documented algorithm, written out independently: URL + sorted name+value pairs, HMAC-SHA1, base64."""
    s = url
    for k in sorted(params):
        s += k + params[k]
    return base64.b64encode(hmac.new(token.encode(), s.encode(), hashlib.sha1).digest()).decode()


@pytest.fixture
def tw(rt, monkeypatch):
    from jarvis import secrets

    monkeypatch.setattr(secrets, "get", lambda k: "tok123" if k == "twilio_token" else "")
    rt.update_config({"phone_link": {"twilio_sid": "AC1", "twilio_from": "+12025550123", "my_number": "+420777000111",
                                     "public_url": PUBLIC, "secretary": True}, "general": {"user_name": "Adam"}})
    said = []
    rt.notify = lambda title, text, **kw: said.append((title, text, kw))
    return said


def post(client, rt, path, params, sig=None):
    url = PUBLIC + path
    return client.post(path, content=urlencode(params), headers={"Content-Type": "application/x-www-form-urlencoded",
                                                                 "X-Twilio-Signature": sig or twilio_sig("tok123", url, params)})


def test_signature_matches_twilio():
    p = {"CallSid": "CA1", "From": "+420777123456", "SpeechResult": "Dobrý den, tady Novák.", "To": "+12025550123"}
    url = "https://jarvis.example.cz/twilio/abc/gather?c=xyz"
    assert callagent.signature("tok123", url, p) == twilio_sig("tok123", url, p)


def test_ready_explains_what_is_missing(rt, monkeypatch):
    from jarvis import secrets

    monkeypatch.setattr(secrets, "get", lambda k: "")
    assert "Twilio" in callagent.ready(rt)
    monkeypatch.setattr(secrets, "get", lambda k: "tok")
    rt.update_config({"phone_link": {"twilio_sid": "AC1", "twilio_from": "+1", "my_number": "+420", "public_url": "http://x"}})
    assert "HTTPS" in callagent.ready(rt)
    rt.update_config({"phone_link": {"public_url": "https://x.cz"}})
    assert callagent.ready(rt) == ""


async def test_secretary_takes_a_call_and_sends_a_summary(rt, tw):
    from jarvis.server.app import create_app

    rt.router = FakeRouter([
        '{"say": "Dobře, pane Nováku. Jak je to naléhavé a kam vám má zavolat zpět?", "done": false, "urgent": false}',
        '{"say": "Děkuji, vyřídím. Na shledanou.", "done": true, "urgent": false}',
        "Volal pan Novák kvůli faktuře, není to naléhavé, zpět na 777 123 456.",
    ])
    key = callagent.hook_key(rt)
    c = TestClient(create_app(rt, manage_runtime=False))
    r = post(c, rt, f"/twilio/{key}/voice", {"CallSid": "CA9", "From": "+420777123456"})
    assert r.status_code == 200 and "<Gather" in r.text and "umělá inteligence" in r.text and "Adam" in r.text
    r = post(c, rt, f"/twilio/{key}/gather?c=CA9", {"CallSid": "CA9", "SpeechResult": "Tady Novák, volám kvůli faktuře."})
    assert "Jak je to naléhavé" in r.text and "<Gather" in r.text
    r = post(c, rt, f"/twilio/{key}/gather?c=CA9", {"CallSid": "CA9", "SpeechResult": "Nespěchá, číslo 777 123 456."})
    assert "<Hangup/>" in r.text
    if "CA9" in callagent.calls(rt):                     # the test client's loop may stop before the background summary
        await callagent.finish(rt, "CA9")
    hist = callagent.history(rt)
    assert hist and hist[0]["number"] == "+420777123456" and "Novák" in hist[0]["summary"]
    assert tw and tw[-1][0].startswith("Zmeškaný hovor") and "Novák" in tw[-1][1]


def test_webhooks_refuse_bad_signatures_and_keys(rt, tw):
    from jarvis.server.app import create_app

    key = callagent.hook_key(rt)
    c = TestClient(create_app(rt, manage_runtime=False))
    assert post(c, rt, f"/twilio/{key}/voice", {"CallSid": "CA1"}, sig="bad").status_code == 403
    assert post(c, rt, "/twilio/wrongkey/voice", {"CallSid": "CA1"}).status_code == 403
    r = c.post(f"/twilio/{key}/voice", content="CallSid=CA1", headers={
        "Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": twilio_sig("tok123", f"{PUBLIC}/twilio/{key}/voice", {"CallSid": "CA1"}),
        "X-Twilio-Webhooks-Signature-Settings": "key=x,algorithm=HMAC_SHA256"})
    assert r.status_code == 403
    rt.update_config({"phone_link": {"secretary": False}})
    r = post(c, rt, f"/twilio/{key}/voice", {"CallSid": "CA2", "From": "+420"})
    assert r.status_code == 200 and "<Hangup/>" in r.text and "<Gather" not in r.text


async def test_urgent_call_rings_the_phone(rt, tw):
    rt.router = FakeRouter(['{"say": "Rozumím, hned to předám.", "done": true, "urgent": true}', "Naléhavé: nehoda, volá sestra."])
    rang = []

    class Phone:
        notifications = []

        async def ring(self, text, reason=""):
            rang.append(text)

    rt.phone = Phone()
    callagent.incoming(rt, "CA5", "+420602000000", PUBLIC + "/twilio/k")
    out = await callagent.heard(rt, "CA5", "Tady sestra, máma měla nehodu, ať se hned ozve!", PUBLIC + "/twilio/k")
    assert "<Hangup/>" in out
    for _ in range(40):                                   # the summary and the ring run in the background
        if rang:
            break
        await asyncio.sleep(0.02)
    assert rang and "Naléhavý hovor" in rang[-1]
    assert tw[-1][0] == "Naléhavý hovor"


async def test_call_for_me_introduces_itself_as_ai(rt, tw):
    rt.router = FakeRouter([
        '{"say": "Chtěl bych zarezervovat stůl na pátek na 19:00 pro 4 osoby."}',
        '{"say": "Výborně, na jméno Adam. Děkuji, na shledanou.", "done": true, "result": "Stůl na pátek 19:00 pro 4 je zarezervovaný."}',
        "Stůl na pátek v 19:00 pro 4 osoby je zarezervovaný.",
    ])
    sent = []

    def handler(req: httpx.Request):
        sent.append(dict(httpx.QueryParams(req.content.decode())))
        return httpx.Response(201, json={"sid": "CAout"})

    rt.transport = httpx.MockTransport(handler)
    assert tools.REGISTRY["call_for_me"].danger
    r = await tools.call("call_for_me", {"number": "777 123 456", "goal": "rezervace stolu na pátek 19:00 pro 4"}, rt)
    assert r.ok and "+420777123456" in r.summary
    assert sent[0]["To"] == "+420777123456" and sent[0]["MachineDetection"] == "Enable" and "/twilio/" in sent[0]["Url"]
    cid = r.data["id"]
    first = callagent.answered(rt, cid, "human", PUBLIC + "/twilio/k")
    assert "Jsem umělá inteligence a volám jménem uživatele Adam" in first and "zarezervovat stůl" in first
    out = await callagent.heard(rt, cid, "Ano, máme volno, na jaké jméno?", PUBLIC + "/twilio/k")
    assert "<Hangup/>" in out
    for _ in range(40):
        if tw and tw[-1][0] == "Hovor za tebe":
            break
        await asyncio.sleep(0.02)
    assert tw[-1][0] == "Hovor za tebe" and "zarezervovaný" in tw[-1][1]


def test_answering_machine_gets_one_sentence(rt, tw):
    callagent.calls(rt)["X"] = {"id": "X", "dir": "out", "number": "+420", "goal": "g", "turns": [("jarvis", "Dobrý den")],
                                "started": time.time(), "urgent": False, "done": False}
    async def go():
        return callagent.answered(rt, "X", "machine_end_beep", PUBLIC)

    out = asyncio.run(go())
    assert "<Hangup/>" in out and "umělá inteligence" in out


def test_forwarding_codes():
    c = callagent.forwarding_codes("+1 202 555 0123")
    assert c["nepřijatý"] == "**61*+12025550123**20#" and c["zrušit vše"] == "##002#"


def _notes(now):
    return [
        {"app": "WhatsApp", "title": "Petr", "text": "Ahoj, stihneš to dneska v 6?", "ts": now - 600, "messaging": True, "call": False,
         "key": "k1", "can_reply": True},
        {"app": "WhatsApp", "title": "Petr", "text": "Ozvi se prosím hned, je to důležité", "ts": now - 300, "messaging": True,
         "call": False, "key": "k2", "can_reply": True},
        {"app": "Messenger", "title": "Jana", "text": "Posílám fotky z výletu", "ts": now - 900, "messaging": True, "call": False,
         "key": "k3", "can_reply": False},
        {"app": "Gmail", "title": "Newsletter", "text": "Sleva 20 %", "ts": now - 100, "messaging": False, "call": False},
        {"app": "WhatsApp", "title": "Starý", "text": "Včerejší zpráva", "ts": now - 30 * 3600, "messaging": True, "call": False},
    ]


async def test_chat_digest_orders_by_importance(rt):
    now = time.time()

    class Phone:
        notifications = _notes(now)
        sent = []

        def send(self, kind, **d):
            self.sent.append((kind, d))

    rt.phone = Phone()
    convs = chatdigest.conversations(Phone.notifications, now - 8 * 3600)
    assert [c["who"] for c in convs] == ["Petr", "Jana"] and convs[0]["urgent"] and convs[0]["key"] == "k2"
    assert convs[0]["messages"] == ["Ahoj, stihneš to dneska v 6?", "Ozvi se prosím hned, je to důležité"]
    rt.router = FakeRouter([json.dumps([{"i": 0, "gist": "Petr se ptá, jestli stihneš 6 a chce se ozvat.", "reply": "Stihnu, ozvu se.",
                                          "important": True}, {"i": 1, "gist": "Jana poslala fotky z výletu.", "reply": ""}],
                                        ensure_ascii=False)])
    r = await tools.call("chat_digest", {"hours": 8}, rt)
    assert "3 zpráv ve 2" in r.summary.replace("v 2", "ve 2") or "3 zpráv v 2" in r.summary
    assert "❗ Petr (WhatsApp): Petr se ptá" in r.summary and "návrh: „Stihnu, ozvu se.“" in r.summary
    assert "Newsletter" not in r.summary and "Starý" not in r.summary
    rt.router = FakeRouter([RuntimeError("offline")])
    d = await chatdigest.digest(rt, 8)
    assert "❗ Petr (WhatsApp, 2×)" in d["text"]
    assert tools.REGISTRY["chat_reply"].danger
    r = await tools.call("chat_reply", {"who": "petr", "text": "Stihnu, v 6 jsem tam."}, rt)
    assert r.ok and Phone.sent[-1] == ("notif_reply", {"key": "k2", "text": "Stihnu, v 6 jsem tam."})
    r = await tools.call("chat_reply", {"who": "Jana", "text": "Díky"}, rt)
    assert not r.ok and "otevři ji v telefonu" in r.summary


async def test_secretary_setup_tool(rt, tw):
    r = await tools.call("secretary_setup", {"on": "on"}, rt)
    assert r.ok and "/twilio/" in r.data["webhook"] and "**61*" in r.summary
    from jarvis.config import public_dump

    assert "call_key" not in json.dumps(public_dump(rt.cfg))
