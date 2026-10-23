import asyncio

from conftest import FakeRouter, drain
from fastapi.testclient import TestClient

from jarvis import tools


async def test_stop_all_during_confirm(rt):
    rt.router = FakeRouter([[("system_power", {"action": "shutdown"})], "Vypínám."])
    q = rt.bus.subscribe()
    task = asyncio.create_task(rt.agent.handle("vypni počítač"))
    seen = []
    for _ in range(100):
        await asyncio.sleep(0.01)
        seen += drain(q)
        if any(e["type"] == "confirm_request" for e in seen):
            break
    rt.stop_all()
    await asyncio.wait_for(task, 1)
    seen += drain(q)
    assert ("power", "shutdown") not in rt.platform.calls
    assert ("release_all_input",) in rt.platform.calls
    assert rt.tasks.list()[0]["status"] == "cancelled"
    assert any(e["type"] == "stopped" for e in seen)
    assert any(e["type"] == "confirm_resolved" and e["approved"] is False for e in seen)
    assert rt.agent.pending_confirm() is None


def _files(tmp_path, *names):
    for n in names:
        (tmp_path / n).write_text("x", encoding="utf-8")


async def test_move_files_details_and_verify(ctx, tmp_path):
    _files(tmp_path, "a.pdf", "b.pdf")
    moves = [{"src": str(tmp_path / "a.pdf"), "dst": str(tmp_path / "2026" / "a.pdf")},
             {"src": str(tmp_path / "b.pdf"), "dst": str(tmp_path / "2026" / "b.pdf")}]
    spec = tools.REGISTRY["move_files"]
    details = spec.details({"moves": moves})
    assert details[0].endswith("a.pdf") and "→" in details[0] and len(details) == 2
    res = await tools.call("move_files", {"moves": moves}, ctx)
    assert res.ok and res.data["moved"] == 2
    assert (tmp_path / "2026" / "b.pdf").exists() and not (tmp_path / "a.pdf").exists()


async def test_move_files_missing_source(ctx, tmp_path):
    _files(tmp_path, "a.pdf")
    moves = [{"src": str(tmp_path / "a.pdf"), "dst": str(tmp_path / "x" / "a.pdf")},
             {"src": str(tmp_path / "nope.pdf"), "dst": str(tmp_path / "x" / "nope.pdf")}]
    res = await tools.call("move_files", {"moves": moves}, ctx)
    assert not res.ok and res.data["moved"] == 1
    assert any("nope.pdf" in f for f in res.data["failed"])


def test_details_truncated():
    moves = [{"src": f"C:/a/{i}.txt", "dst": f"C:/b/{i}.txt"} for i in range(80)]
    d = tools.REGISTRY["move_files"].details({"moves": moves})
    assert len(d) == 51 and d[-1] == "…a dalších 30"


async def test_confirm_has_details(rt, tmp_path):
    f = tmp_path / "smaz.txt"
    f.write_text("x", encoding="utf-8")
    rt.router = FakeRouter([[("delete_file", {"path": str(f)})], "Nesmazáno."])
    q = rt.bus.subscribe()
    task = asyncio.create_task(rt.agent.handle("smaž soubor"))
    ev = None
    for _ in range(100):
        await asyncio.sleep(0.01)
        ev = next((e for e in drain(q) if e["type"] == "confirm_request"), None)
        if ev:
            break
    assert ev and any("smaz.txt" in line for line in ev["details"])
    rt.agent.confirm(ev["id"], False)
    await task
    assert f.exists()


def test_ws_task_api(rt):
    from jarvis.server.app import create_app

    rt.router = FakeRouter([[("get_time", {})], "Hotovo."])
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_json({"type": "hello", "client": "dashboard"})
            ws.send_json({"type": "user_text", "text": "kolik je"})
            while True:
                if ws.receive_json()["type"] == "assistant_done":
                    break
            ws.send_json({"type": "tasks_get"})
            m = ws.receive_json()
            while m["type"] != "tasks":
                m = ws.receive_json()
            assert len(m["items"]) == 1
            ws.send_json({"type": "task_get", "id": m["items"][0]["id"]})
            m = ws.receive_json()
            while m["type"] != "task":
                m = ws.receive_json()
            assert m["task"]["actions"][0]["tool"] == "get_time"
            ws.send_json({"type": "tasks_clear"})
            m = ws.receive_json()
            while m["type"] != "tasks":
                m = ws.receive_json()
            assert m["items"] == []
