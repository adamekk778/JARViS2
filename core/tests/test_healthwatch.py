"""3.12 Zdraví PC v telefonu: what is wrong on the PC becomes one quiet notice (on the phone when you are away)."""
from jarvis import healthwatch as hw


def S(t, cpu=10, ram=40, disks=None, gpu=None, crashed=None, top=None):
    return {"t": t, "cpu": cpu, "ram": ram, "disks": disks or [{"mount": "C:\\", "used_pct": 50, "free_gb": 120.0}],
            "gpu_temp": gpu, "top": top or [{"name": "chrome.exe", "cpu": 30.0, "ram_mb": 900}], "crashed": crashed or []}


def test_problems_are_found_and_sent_once(rt):
    notes = []
    rt.notify = lambda title, body, **k: notes.append((title, body, k.get("speak")))
    w = hw.HealthWatch(rt)
    assert w.step(S(0)) == [] and notes == []                                    # all fine
    full = [{"mount": "C:\\", "used_pct": 97, "free_gb": 3.2}]
    sent = w.step(S(300, disks=full))
    assert [a["key"] for a in sent] == ["disk:C:\\"] and "C:" in notes[0][1] and "3.2 GB" in notes[0][1]
    assert notes[0][2] is False                                                  # quiet: never spoken aloud
    assert w.step(S(600, disks=full)) == []                                      # the same problem: not again soon
    assert [a["key"] for a in w.step(S(600 + hw.REPEAT_S, disks=full))] == ["disk:C:\\"]   # 6 hours later: once more


def test_memory_and_processor_only_when_it_lasts(rt):
    rt.notify = lambda *a, **k: 1
    w = hw.HealthWatch(rt)
    assert w.step(S(0, cpu=99, ram=95)) == []                                    # one busy moment is normal
    assert w.step(S(300, cpu=99, ram=95)) == []
    keys = [a["key"] for a in w.step(S(600, cpu=99, ram=95))]                     # 15 minutes in a row
    assert keys == ["ram", "cpu"]
    assert "chrome.exe" in w.alerts[0]["body"]                                   # names what uses it most


def test_hot_graphics_and_crashed_apps(rt):
    rt.notify = lambda *a, **k: 1
    w = hw.HealthWatch(rt)
    keys = [a["key"] for a in w.step(S(0, gpu=91, crashed=["Game.exe", "Notepad.exe"]))]
    assert keys == ["gpu_hot", "crash:game.exe", "crash:notepad.exe"]
    st = w.status()
    assert st["now"]["gpu_temp"] == 91 and st["history"][-1] == {"t": 0, "cpu": 10, "ram": 40, "gpu_temp": 91}
    assert len(st["alerts"]) == 3


def test_crashes_parse_windows_events(monkeypatch):
    xml = ("<Event><System><EventID>1000</EventID></System><EventData><Data>Game.exe</Data><Data>1.0</Data></EventData></Event>"
           "<Event><System><EventID>1000</EventID></System><EventData><Data Name='AppName'>Game.exe</Data></EventData></Event>"
           "<Event><System><EventID>1000</EventID></System><EventData><Data>svchost.dll</Data></EventData></Event>")
    monkeypatch.setattr(hw.sys, "platform", "win32")
    monkeypatch.setattr(hw.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": xml})())
    assert hw.crashes(600000) == ["Game.exe"]


def test_phone_gets_health(rt, monkeypatch):
    from starlette.testclient import TestClient

    from jarvis.server.app import create_app

    monkeypatch.setattr(rt.health, "sample", lambda: S(100, cpu=33))
    app = create_app(rt, manage_runtime=False)
    with TestClient(app, client=("100.70.1.2", 5000)).websocket_connect(f"/ws?token={rt.cfg.phone.token}") as ws:   # the phone
        ws.send_json({"type": "hello", "client": "mobile"})
        ws.send_json({"type": "health_get", "fresh": True})
        for _ in range(60):
            m = ws.receive_json()
            if m["type"] == "health":
                break
        assert m["now"]["cpu"] == 33 and m["history"]
