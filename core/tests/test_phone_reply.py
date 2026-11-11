"""3.12 Replying to phone messages from the notch: the reply goes through the message's own app, only when you send it."""
from conftest import FakeRouter
from fastapi.testclient import TestClient

from jarvis.server.app import create_app

LOCAL = ("127.0.0.1", 5000)
REMOTE = ("192.168.1.50", 5000)


def recv_until(ws, type_, limit=60):
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == type_:
            return m
    raise AssertionError(f"no {type_}")


def test_notification_keeps_the_reply_key(rt):
    item = rt.phone.on_notification({"package": "com.whatsapp", "app": "WhatsApp", "title": "Máma", "text": "Přijdeš?",
                                     "key": "0|com.whatsapp|1", "can_reply": True})
    assert item["can_reply"] and item["key"] == "0|com.whatsapp|1" and item["messaging"]
    plain = rt.phone.on_notification({"package": "com.android.vending", "app": "Obchod", "title": "Aktualizace", "text": "2 aplikace"})
    assert plain["can_reply"] is False


def test_sending_a_reply_queues_it_for_the_phone(rt):
    app = create_app(rt, manage_runtime=False)
    with TestClient(app, client=LOCAL).websocket_connect("/ws") as ws:
        recv_until(ws, "welcome")
        ws.send_json({"type": "phone_reply", "key": "k1", "text": "Jasně, budu tam v 6!"})
        ws.send_json({"type": "ping"})
        recv_until(ws, "pong")
    cmds = [c for c in rt.phone.queue if c["kind"] == "notif_reply"]
    assert cmds and cmds[0]["key"] == "k1" and cmds[0]["text"] == "Jasně, budu tam v 6!"


def test_suggestion_is_only_a_draft(rt):
    rt.router = FakeRouter(["„Jasně, přijdu!“"])
    app = create_app(rt, manage_runtime=False)
    with TestClient(app, client=LOCAL).websocket_connect("/ws") as ws:
        recv_until(ws, "welcome")
        ws.send_json({"type": "phone_reply_suggest", "key": "k1", "title": "Máma", "text": "Přijdeš na večeři?"})
        m = recv_until(ws, "phone_reply_suggestion")
    assert m["key"] == "k1" and m["text"] == "Jasně, přijdu!"
    assert not [c for c in rt.phone.queue if c["kind"] == "notif_reply"]       # nothing sent by itself


def test_replies_only_from_the_pc_itself(rt):
    from jarvis.server import ws

    assert {"phone_reply", "phone_reply_suggest"} <= ws.LOCAL_ONLY
