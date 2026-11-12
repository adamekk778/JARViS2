"""3.12 Away from the PC → notices and confirmations on the phone; shared clipboard PC ↔ phone."""
import time

from fastapi.testclient import TestClient

from jarvis.server.app import create_app

LOCAL = ("127.0.0.1", 5000)
HOME = ("192.168.1.50", 5000)
AWAY = ("100.70.1.2", 5000)       # Tailscale: not at home


def phone_cmds(rt, kind):
    return [c for c in rt.phone.queue if c["kind"] == kind]


def test_notices_go_to_the_phone_only_when_you_are_away(rt):
    rt.phone.last_poll = time.time()                      # the phone's link is alive
    rt.platform.idle = 10
    rt.notify("Stahování dokončeno", "film.mkv", speak=False)
    assert not phone_cmds(rt, "notify")                   # at the PC: nothing on the phone
    rt.platform.idle = 600
    rt.notify("Stahování dokončeno", "film.mkv", speak=False)
    assert phone_cmds(rt, "notify")[-1]["title"] == "Stahování dokončeno"
    rt.cfg.phone_link.away_push = False
    rt.notify("Další", "x", speak=False)
    assert len(phone_cmds(rt, "notify")) == 1


def test_no_pile_for_a_phone_that_is_off(rt):
    rt.phone.last_poll = 0
    rt.platform.idle = 600
    rt.notify("Ahoj", "x", speak=False)
    assert not rt.phone.queue


def test_confirmation_comes_to_the_phone_and_can_be_answered_there(rt):
    rt.phone.last_poll = time.time()
    rt.platform.idle = 600
    rt.on_confirm_request("c1", "Zavřít Steam")
    assert phone_cmds(rt, "confirm")[-1]["cid"] == "c1"
    got = []
    rt.agent.confirm = lambda cid, ok: got.append((cid, ok)) or True
    app = create_app(rt, manage_runtime=False)
    h = {"Authorization": f"Bearer {rt.cfg.phone.token}"}
    rt.cfg.phone.approve_nearby_only = True
    assert TestClient(app, client=AWAY).post("/api/phone/confirm", json={"id": "c1", "approved": True}, headers=h).status_code == 403
    assert TestClient(app, client=HOME).post("/api/phone/confirm", json={"id": "c1", "approved": True}, headers=h).json()["ok"]
    assert TestClient(app, client=AWAY).post("/api/phone/confirm", json={"id": "c1", "approved": False}, headers=h).status_code == 200
    assert got == [("c1", True), ("c1", False)]           # refusing works from anywhere


def test_shared_clipboard_both_ways_without_echo(rt, monkeypatch):
    rt.phone.last_poll = time.time()
    rt.cfg.phone_link.clip_sync = True
    copied = []
    monkeypatch.setattr(rt.platform, "clipboard_set", lambda t: copied.append(t), raising=False)
    act = rt.activity
    seq = [1]
    monkeypatch.setattr(rt.platform, "clipboard_seq", lambda: seq[0], raising=False)
    clip = ["první"]
    monkeypatch.setattr(rt.platform, "clipboard_get", lambda: clip[0], raising=False)
    act._clipboard(time.time())                            # first look only remembers
    seq[0], clip[0] = 2, "Ahoj z PC"
    act._clipboard(time.time())
    assert phone_cmds(rt, "clip")[-1]["text"] == "Ahoj z PC"
    app = create_app(rt, manage_runtime=False)
    with TestClient(app, client=HOME).websocket_connect(f"/ws?token={rt.cfg.phone.token}&client=mobile") as ws:
        ws.receive_json()
        ws.send_json({"type": "clip_from_phone", "text": "Z telefonu"})
        ws.send_json({"type": "ping"})
        for _ in range(30):
            if ws.receive_json()["type"] == "pong":
                break
    assert copied == ["Z telefonu"]
    seq[0], clip[0] = 3, "Z telefonu"                     # the PC's clipboard changed because of the phone…
    n = len(phone_cmds(rt, "clip"))
    act._clipboard(time.time())
    assert len(phone_cmds(rt, "clip")) == n               # …so it is not sent back
