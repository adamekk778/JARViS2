import pytest
from conftest import FakeRouter
from fastapi.testclient import TestClient

from jarvis.server.app import create_app

LOCAL = ("127.0.0.1", 5000)
REMOTE = ("192.168.1.50", 5000)


@pytest.fixture
def app(rt):
    rt.router = FakeRouter(["Ahoj z PC.", "Druhá odpověď."])
    return create_app(rt, manage_runtime=False)


def recv_until(ws, type_, limit=50):
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == type_:
            return m
    raise AssertionError(f"no {type_}")


def test_health(app):
    assert TestClient(app, client=REMOTE).get("/api/health").json()["ok"]


def test_remote_ws_requires_token(app, rt):
    c = TestClient(app, client=REMOTE)
    with pytest.raises(Exception):
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()
    with c.websocket_connect(f"/ws?token={rt.cfg.phone.token}") as ws:
        assert ws.receive_json()["type"] == "welcome"


def test_local_ws_no_token(app):
    with TestClient(app, client=LOCAL).websocket_connect("/ws") as ws:
        w = ws.receive_json()
        assert w["type"] == "welcome" and w["local"] is True and "token" not in w["settings"]["phone"]


def test_chat_syncs_between_clients(app, rt):
    with TestClient(app, client=LOCAL) as c, c.websocket_connect("/ws") as a, c.websocket_connect("/ws") as b:
        a.receive_json(), b.receive_json()
        a.send_json({"type": "hello", "client": "dashboard"})
        b.send_json({"type": "hello", "client": "mobile"})
        a.send_json({"type": "user_text", "text": "ahoj"})
        um = recv_until(b, "user_message")
        assert um["text"] == "ahoj" and um["source"] == "chat"
        done = recv_until(b, "assistant_done")
        assert "Ahoj z PC." in done["text"]


def test_upload_download_and_auth(app, rt):
    remote = TestClient(app, client=REMOTE)
    r = remote.post("/api/upload", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 401
    r = remote.post("/api/upload", params={"token": "wrong"}, files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 401
    r = remote.post("/api/upload", headers={"Authorization": f"Bearer {rt.cfg.phone.token}"},
                    files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 200
    aid = r.json()["id"]
    assert remote.get(f"/api/files/{aid}", params={"token": rt.cfg.phone.token}).content == b"hello"
    local = TestClient(app, client=LOCAL)
    assert local.get(f"/api/files/{aid}").content == b"hello"
    assert local.get("/api/files/nope").status_code == 404


def test_upload_too_big(app, rt):
    rt.cfg.memory.max_upload_mb = 0
    r = TestClient(app, client=LOCAL).post("/api/upload", files={"file": ("a.bin", b"xx", "application/octet-stream")})
    assert r.status_code == 413


def test_settings_set_local_only(app, rt):
    with TestClient(app, client=REMOTE).websocket_connect(f"/ws?token={rt.cfg.phone.token}") as ws:
        ws.receive_json()
        ws.send_json({"type": "settings_set", "patch": {"general": {"user_name": "hacker"}}})
        assert recv_until(ws, "error")
    assert rt.cfg.general.user_name != "hacker"
    with TestClient(app, client=LOCAL).websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "settings_set", "patch": {"general": {"user_name": "Adam"}}})
        assert recv_until(ws, "settings")["settings"]["general"]["user_name"] == "Adam"


def test_quick_action_volume(app, rt):
    with TestClient(app, client=LOCAL).websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "quick_action", "action": "volume", "args": {"action": "set", "level": 30}})
        r = recv_until(ws, "quick_result")
        assert r["ok"] and rt.platform.volume == 30
        ws.send_json({"type": "quick_action", "action": "run_shell", "args": {"command": "x"}})
        assert recv_until(ws, "quick_result")["ok"] is False
        ws.send_json({"type": "quick_action", "action": "system_power", "args": {"action": "shutdown"}})
        assert recv_until(ws, "quick_result")["needs_confirm"]


def test_pairing_local_only(app):
    assert TestClient(app, client=REMOTE).get("/api/pairing").status_code == 403
    p = TestClient(app, client=LOCAL).get("/api/pairing").json()
    assert p["qr_svg"].startswith("<?xml") or "<svg" in p["qr_svg"]
    assert "#token=" in p["url"]


def test_new_chat_and_history(app, rt):
    with TestClient(app, client=LOCAL).websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_text", "text": "první"})
        recv_until(ws, "assistant_done")
        ws.send_json({"type": "new_chat"})
        assert recv_until(ws, "history")["messages"] == []
        ws.send_json({"type": "conversations_get"})
        assert len(recv_until(ws, "conversations")["items"]) >= 2


def test_path_traversal_blocked(app, tmp_path):
    c = TestClient(app, client=LOCAL)
    for p in ["/C:/Windows/win.ini", "/..%2f..%2fetc/passwd", "/%5c%5cevil%5cshare", "/etc/passwd"]:
        r = c.get(p)
        assert r.status_code == 404, p


def test_foreign_origin_is_not_local(app, rt):
    c = TestClient(app, client=LOCAL)
    assert c.get("/api/pairing", headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.get("/api/pairing", headers={"Host": "evil.example:8765"}).status_code == 403
    assert c.get("/api/pairing", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
    r = c.post("/api/upload", headers={"Origin": "https://evil.example"}, files={"file": ("a.txt", b"x", "text/plain")})
    assert r.status_code == 401
    with pytest.raises(Exception):
        with c.websocket_connect("/ws", headers={"Origin": "https://evil.example"}) as ws:
            ws.receive_json()


def test_uploaded_html_is_not_executable(app, rt):
    c = TestClient(app, client=LOCAL)
    aid = c.post("/api/upload", files={"file": ("x.html", b"<script>alert(1)</script>", "text/html")}).json()["id"]
    r = c.get(f"/api/files/{aid}")
    assert r.headers["content-type"] == "application/octet-stream"
    assert "attachment" in r.headers["content-disposition"] and r.headers["content-security-policy"] == "sandbox"


def test_pet_removed_command_is_harmless(app, rt):
    """3.1: no desktop pet any more; old clients may still send pet_command, it does nothing."""
    with TestClient(app, client=LOCAL).websocket_connect("/ws") as ws:
        w = ws.receive_json()
        assert w["mood"]["mood"] in ("idle", "offline") and w["pet_mode"] is False
        ws.send_json({"type": "pet_command", "action": "undock"})
        ws.send_json({"type": "mood_set", "mood": "focus"})
        ws.send_json({"type": "ping"})
        recv_until(ws, "pong")
    assert rt.cfg.character.pet_mode is False and rt.mood.manual == "focus"
