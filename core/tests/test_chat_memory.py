import sqlite3

import pytest
from conftest import FakeRouter
from fastapi.testclient import TestClient

from jarvis import tools
from jarvis.memory import DB, Memory
from jarvis.server.app import create_app

LOCAL = ("127.0.0.1", 5000)


def recv_until(ws, type_, limit=60):
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == type_:
            return m
    raise AssertionError(f"no {type_}")


def _four(mem):
    u1 = mem.add_message("user", "první")
    a1 = mem.add_message("assistant", "odpověď 1")
    u2 = mem.add_message("user", "druhá")
    mem.add_message("assistant", "odpověď 2")
    return u1, a1, u2


def test_truncate_from_middle(tmp_path):
    mem = Memory(DB(tmp_path / "m.db"))
    u1, a1, u2 = _four(mem)
    removed = mem.truncate_from(u2["id"])
    assert removed["text"] == "druhá"
    assert [m["id"] for m in mem.recent()] == [u1["id"], a1["id"]]
    assert mem.truncate_from("nope") is None


def test_message_edit_busy_refused(rt):
    _, _, u2 = _four(rt.memory)
    rt.agent.busy = True
    with TestClient(create_app(rt, manage_runtime=False), client=LOCAL) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "message_edit", "id": u2["id"], "text": "jinak"})
        assert "Počkej" in recv_until(ws, "error")["message"]
    assert len(rt.memory.recent()) == 4


def test_message_edit_unknown_id(rt):
    _four(rt.memory)
    with TestClient(create_app(rt, manage_runtime=False), client=LOCAL) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "message_edit", "id": "neexistuje", "text": "x"})
        recv_until(ws, "error")
    assert len(rt.memory.recent()) == 4


def test_message_edit_reruns(rt):
    u1, a1, u2 = _four(rt.memory)
    rt.router = FakeRouter(["Nová odpověď."])
    with TestClient(create_app(rt, manage_runtime=False), client=LOCAL) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "message_edit", "id": u2["id"], "text": "druhá, upravená"})
        recv_until(ws, "assistant_done")
    texts = [m["text"].strip() for m in rt.memory.recent()]
    assert texts == ["první", "odpověď 1", "druhá, upravená", "Nová odpověď."]


def test_rename_and_folder(rt):
    cid = rt.memory.current_conversation
    with TestClient(create_app(rt, manage_runtime=False), client=LOCAL) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "conversation_rename", "id": cid, "title": "Plánování dovolené"})
        recv_until(ws, "conversations")
        ws.send_json({"type": "conversation_move", "id": cid, "folder": "Práce"})
        items = recv_until(ws, "conversations")["items"]
    row = next(i for i in items if i["id"] == cid)
    assert row["title"] == "Plánování dovolené" and row["folder"] == "Práce"


def test_folder_migration(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL)")
    con.execute("INSERT INTO conversations VALUES ('c1', 'stará', 1, 1)")
    con.commit()
    con.close()
    mem = Memory(DB(path))
    rows = {r["id"]: r for r in mem.list_conversations()}
    assert rows["c1"]["folder"] == ""
    mem.new_conversation()


def test_export_import_roundtrip(tmp_path):
    a = Memory(DB(tmp_path / "a.db"))
    a.remember("Jmenuje se Adam")
    a.add_message("user", "ahoj")
    a.add_message("assistant", "Dobrý den")
    data = a.export(include_conversations=True)
    assert data["version"] == 1 and data["facts"][0]["text"] == "Jmenuje se Adam"
    b = Memory(DB(tmp_path / "b.db"))
    res = b.import_data(data)
    assert res == {"facts_added": 1, "facts_skipped": 0, "conversations_added": 1}
    assert b.import_data(data)["facts_skipped"] == 1
    assert [f["text"] for f in b.facts()] == ["Jmenuje se Adam"]
    assert not a.export(include_conversations=False).get("conversations")


def test_import_bad_shape(tmp_path):
    with pytest.raises(ValueError):
        Memory(DB(tmp_path / "x.db")).import_data({"foo": 1})


async def test_remember_refuses_secret(ctx):
    res = await tools.call("remember", {"fact": "heslo k wifi je Kocka123"}, ctx)
    assert not res.ok and ctx.memory.facts() == []


def test_ws_export_import(rt):
    rt.memory.remember("Má rád pizzu")
    with TestClient(create_app(rt, manage_runtime=False), client=LOCAL) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "memory_export", "conversations": False})
        data = recv_until(ws, "memory_export_data")["data"]
        ws.send_json({"type": "memory_import", "data": {"version": 1, "facts": [{"text": "Bydlí v Brně"}]}})
        res = recv_until(ws, "memory_import_result")
    assert data["facts"][0]["text"] == "Má rád pizzu" and res["facts_added"] == 1
