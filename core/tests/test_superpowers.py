import asyncio
import datetime as dt
import sys
from pathlib import Path

import pytest
from conftest import FakeRouter

from jarvis import tools
from jarvis.tools import REGISTRY, call


async def test_run_python_output_and_files(rt):
    r = await call("run_python", {"code": "print(6*7)\nopen('vysledek.txt','w').write('ahoj')"}, rt)
    assert r.ok and r.data["stdout"].strip() == "42" and len(r.attachments) == 1
    assert rt.store.get(r.attachments[0]).name == "vysledek.txt"


async def test_run_python_error_and_risk(rt):
    r = await call("run_python", {"code": "raise SystemExit(3)"}, rt)
    assert not r.ok
    assert tools.is_dangerous(REGISTRY["run_python"], {"code": "import shutil; shutil.rmtree('x')"})
    assert not tools.is_dangerous(REGISTRY["run_python"], {"code": "print(2**10)"})


async def test_create_skill_hot_loads(rt):
    code = '''
from jarvis.tools.base import tool, ToolResult

@tool("kostka", "Hodí kostkou.")
async def kostka(ctx, sides: int = 6) -> ToolResult:
    return ToolResult(True, f"padlo {sides}")
'''
    r = await call("create_skill", {"name": "kostka", "code": code}, rt)
    assert r.ok and "kostka" in REGISTRY
    assert (await call("kostka", {"sides": 20}, rt)).summary == "padlo 20"
    bad = await call("create_skill", {"name": "rozbity", "code": "@tool(\nsyntax error"}, rt)
    assert not bad.ok and not (Path(r.data["file"]).parent / "rozbity.py").exists()
    assert (await call("delete_skill", {"name": "kostka"}, rt)).ok and "kostka" not in REGISTRY


async def test_scheduler_fires_due_job(rt):
    from jarvis.scheduler import Scheduler, next_run

    rt.router = FakeRouter(["Dobré ráno, je 12 °C."])
    s = Scheduler(rt)
    rt.scheduler = s
    q = rt.bus.subscribe()
    job = s.add({"type": "daily", "time": "07:00", "days": list(range(7))}, "prompt", {"prompt": "Řekni počasí"}, "Ráno")
    assert job["spec_text"] == "denně v 07:00"
    later = dt.datetime.fromtimestamp(job["next_run"]) + dt.timedelta(seconds=5)
    assert await s.tick(later) == 1
    await asyncio.sleep(0.2)
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(e["type"] == "notify" and "12 °C" in e["body"] for e in events)
    assert s.get(job["id"])["next_run"] > later.timestamp()  # rescheduled for tomorrow
    weekdays = next_run({"type": "daily", "time": "07:00", "days": [0, 1, 2, 3, 4]}, dt.datetime(2026, 10, 24, 8, 0))
    assert weekdays.weekday() == 0  # Saturday 8:00 → Monday


async def test_set_reminder_uses_scheduler(rt):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    r = await call("set_reminder", {"text": "zavolat mámě", "when": "23:59"}, rt)
    assert r.ok and rt.scheduler.list()[0]["kind"] == "notify"


async def test_computer_use_loop(rt):
    rt.router = FakeRouter(['{"action":"click","x":64,"y":36,"why":"tlačítko"}', 'ok {"action":"type","text":"ahoj"}',
                            '{"action":"done","summary":"Hotovo"}'])
    rt.platform.screen_size = lambda: (128, 72)
    from jarvis.tools.computer_use import run_computer_task

    r = await run_computer_task(rt, "napiš ahoj")
    assert r.ok and r.data["steps"] == 3
    assert ("click", 64, 36, "left", False) in rt.platform.calls and ("type_text", "ahoj") in rt.platform.calls


async def test_computer_use_disabled(rt):
    rt.cfg.tools.computer_use = False
    assert not (await call("computer_use", {"task": "x"}, rt)).ok


async def test_mcp_server_tools_become_jarvis_tools(rt):
    from jarvis.config import McpServer
    from jarvis.integrations.mcp_client import McpManager

    fixture = Path(__file__).parent / "fixtures" / "echo_mcp.py"
    rt.cfg.integrations.mcp = [McpServer(name="echo", command=sys.executable, args=[str(fixture)])]
    m = McpManager(rt)
    await m.start()
    for _ in range(100):
        if m.status()[0]["ok"]:
            break
        await asyncio.sleep(0.1)
    assert m.status()[0]["ok"], m.status()
    assert "mcp__echo__add" in REGISTRY
    r = await call("mcp__echo__add", {"a": 2, "b": 40}, rt)
    assert r.ok and "42" in r.data
    assert tools.is_dangerous(REGISTRY["mcp__echo__delete_everything"], {})
    await m.stop()
    await asyncio.sleep(0.2)


@pytest.mark.parametrize("raw,expected", [('{"action":"done","summary":"x"}', "done"),
                                          ('Jasně: {"action": "key", "keys": ["win"]} hotovo', "key")])
def test_parse_action(raw, expected):
    from jarvis.tools.computer_use import parse_action

    assert parse_action(raw)["action"] == expected


@pytest.mark.skipif(not Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome").exists(), reason="no chromium")
async def test_browser_tools(rt, monkeypatch, tmp_path):
    import http.server
    import threading

    (tmp_path / "index.html").write_text('<h1>Obchod</h1><input placeholder="Hledat"><button onclick="document.body.append(\'KOUPENO\')">Koupit</button>', encoding="utf-8")
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(tmp_path), **k)  # noqa: E731
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("JARVIS_HEADLESS", "1")
    monkeypatch.setenv("JARVIS_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    from jarvis.tools import browser

    browser.SESSION = browser.BrowserSession()
    r = await call("browser_open", {"url": f"http://127.0.0.1:{srv.server_port}/"}, rt)
    assert r.ok and "Obchod" in r.data["text"]
    btn = next(e for e in r.data["elements"] if e["label"] == "Koupit")
    assert tools.is_dangerous(REGISTRY["browser_click"], {"index": btn["i"], "label": "Koupit"})
    r = await call("browser_click", {"index": btn["i"], "label": "Koupit"}, rt)
    assert "KOUPENO" in r.data["text"]
    await call("browser_close", {}, rt)
    srv.shutdown()
