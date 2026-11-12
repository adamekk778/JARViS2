"""3.12 Notch na telefonu: the one thing the phone's island shows, asked for by the phone (with its token)."""
from fastapi.testclient import TestClient

from jarvis import phoneisland
from jarvis.server.app import create_app

REMOTE = ("192.168.1.50", 5000)


def test_island_shows_the_most_important_thing(rt, monkeypatch):
    assert phoneisland.state(rt)["kind"] == "idle"
    rt.media_state = {"title": "Golden Hour", "artist": "JVKE", "playing": True}
    assert phoneisland.state(rt) == {"kind": "music", "text": "Golden Hour", "sub": "JVKE"}
    monkeypatch.setattr(rt.timers, "list", lambda: [{"label": "Pizza", "remaining": 125}])
    assert phoneisland.state(rt)["text"] == "2:05"                 # a timer beats the music
    rt.pc_control.on = True
    assert phoneisland.state(rt)["kind"] == "control"              # JARVIS driving the PC beats everything


def test_island_needs_the_phones_token(rt):
    app = create_app(rt, manage_runtime=False)
    c = TestClient(app, client=REMOTE)
    assert c.get("/api/phone/island").status_code in (401, 403)
    r = c.get("/api/phone/island", headers={"Authorization": f"Bearer {rt.cfg.phone.token}"})
    assert r.status_code == 200 and r.json()["kind"] == "idle"
