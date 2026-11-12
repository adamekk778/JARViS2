"""3.12 Ranní souhrn do telefonu: at the chosen time the briefing + the night on the PC goes to the phone, once a day."""
import asyncio
import datetime as dt

from jarvis import morning


def test_due_only_when_on_at_the_time_and_once_a_day(rt):
    at = lambda h, m=0: dt.datetime(2026, 11, 13, h, m)  # noqa: E731
    assert not morning.due(rt, at(7, 5))                                  # off until switched on
    rt.cfg.phone_link.morning, rt.cfg.phone_link.morning_time = True, "6:45"
    assert not morning.due(rt, at(6, 30)) and morning.due(rt, at(6, 45)) and morning.due(rt, at(9, 40))
    assert not morning.due(rt, at(9, 50))                                 # phone off all morning: skip the day
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('phone_morning_day', ?)", ("2026-11-13",))
    assert not morning.due(rt, at(7, 0))
    assert morning._hhmm("nesmysl") == (7, 0) and morning._hhmm("25:00") == (7, 0)


def test_summary_has_the_night_and_reaches_the_phone(rt, monkeypatch):
    import time

    from jarvis import stark

    async def brief(rt_, now=None, news=None):
        return {"text": "Dobré ráno, pane. Je pátek."}

    monkeypatch.setattr(stark, "briefing", brief)
    rt.health.alerts.appendleft({"title": "Na disku dochází místo", "t": time.time() - 3600})
    rt.guard.events.appendleft({"kind": "unlock", "t": time.time() - 7200})
    pushed = []
    rt.phone_push = lambda kind, **d: pushed.append((kind, d)) or True
    rt.cfg.phone_link.morning_autoplay = True
    assert asyncio.run(morning.send(rt))
    kind, d = pushed[0]
    assert kind == "morning" and d["autoplay"] is True
    assert d["text"].startswith("Dobré ráno") and "dochází místo" in d["text"] and "odemkl" in d["text"]
    assert rt.db.one("SELECT v FROM kv WHERE k='phone_morning_day'")["v"] == dt.date.today().isoformat()
    pushed.clear()
    assert asyncio.run(morning.send(rt, test=True)) and pushed[0][1]["autoplay"] is False   # a test never auto-plays


def test_phone_not_connected_keeps_trying(rt, monkeypatch):
    from jarvis import stark

    async def brief(rt_, now=None, news=None):
        return {"text": "Dobré ráno."}

    monkeypatch.setattr(stark, "briefing", brief)
    rt.phone_push = lambda kind, **d: False
    assert not asyncio.run(morning.send(rt))
    assert rt.db.one("SELECT v FROM kv WHERE k='phone_morning_day'") is None          # not marked: next minute again


def test_tts_for_the_phone(rt):
    from types import SimpleNamespace

    from starlette.testclient import TestClient

    from jarvis.server.app import create_app

    async def synth(text, lang="cs", override=None):
        return b"ID3", "audio/mpeg"

    rt.speaker = SimpleNamespace(synth=synth)
    c = TestClient(create_app(rt, manage_runtime=False), client=("100.70.1.2", 5000))
    h = {"Authorization": f"Bearer {rt.cfg.phone.token}"}
    assert c.post("/api/phone/tts", json={"text": "Ahoj"}).status_code == 401
    assert c.post("/api/phone/tts", json={"text": ""}, headers=h).status_code == 400
    assert c.post("/api/phone/tts", json={"text": "Ahoj"}, headers=h).json()["mime"] == "audio/mpeg"
