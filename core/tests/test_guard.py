"""3.12 Hlídání PC: someone unlocks / uses the PC while it is watched → a notice on the phone (and optionally a lock)."""
from jarvis import guard as g


def setup(rt):
    pushed, locks = [], []
    rt.phone_push = lambda kind, **d: pushed.append((kind, d)) or True
    rt.platform.power = lambda action: locks.append(action)
    return pushed, locks


def test_unlock_while_watched_tells_the_phone(rt):
    pushed, locks = setup(rt)
    w = g.Guard(rt)
    assert w.step(100, False, 0) is None                      # not watching: nothing
    w.arm(True, now=1000)
    assert w.step(1005, False, 0) is None                     # the owner is still leaving
    assert w.step(1030, True, 40) is None                     # locked and quiet
    ev = w.step(1100, False, 1)                               # unlocked
    assert ev["kind"] == "unlock" and pushed[0][0] == "notify" and "odemkl" in pushed[0][1]["body"]
    assert locks == []
    assert w.step(1110, False, 1) is None                     # not again every few seconds
    assert len(pushed) == 1


def test_touching_a_quiet_pc_counts_and_can_lock_it_again(rt):
    pushed, locks = setup(rt)
    w = g.Guard(rt)
    w.arm(True, auto_lock=True, now=0)
    assert w.step(30, False, 25) is None                      # nobody there
    assert w.step(60, False, 55) is None
    ev = w.step(63, False, 1)                                 # a mouse moved after a quiet minute
    assert ev["kind"] == "input" and ev["locked_again"] and locks == ["lock"]
    assert "znovu zamkl" in pushed[0][1]["body"]


def test_the_owner_typing_without_a_pause_does_not_trigger(rt):
    pushed, _ = setup(rt)
    w = g.Guard(rt)
    w.arm(True, now=0)
    for t in range(21, 120, 3):
        assert w.step(t, False, 1) is None                    # always active, never a quiet stretch → no alarm
    assert pushed == []


def test_only_the_phone_switches_it_off(rt):
    from starlette.testclient import TestClient

    from jarvis.server.app import create_app

    setup(rt)
    app = create_app(rt, manage_runtime=False)
    with TestClient(app, client=("127.0.0.1", 5000)).websocket_connect("/ws") as ws:       # at the PC
        ws.send_json({"type": "hello", "client": "dashboard"})
        ws.send_json({"type": "guard_set", "on": True})
        ws.send_json({"type": "guard_set", "on": False})
        got = []
        for _ in range(80):
            m = ws.receive_json()
            if m["type"] == "guard":
                got.append(m)
                if len(got) == 2:
                    break
    assert got[0]["armed"] and got[1]["armed"] and "telefonu" in got[1]["error"]
    with TestClient(app, client=("100.70.1.2", 5000)).websocket_connect(f"/ws?token={rt.cfg.phone.token}") as ws:   # the phone
        ws.send_json({"type": "hello", "client": "mobile"})
        ws.send_json({"type": "guard_set", "on": False})
        for _ in range(80):
            m = ws.receive_json()
            if m["type"] == "guard":
                break
    assert m["armed"] is False and not rt.guard.armed
