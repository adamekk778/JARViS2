"""Wave 33: the notch knows what you are doing – app actions (089), suggestions (094), pins (093), workspaces (091)."""
import datetime as dt
import os
import time

from conftest import drain
from fastapi.testclient import TestClient

from jarvis import tools, uiplus
from jarvis.config import Config
from jarvis.server.app import create_app

LOCAL = ("127.0.0.1", 5000)


def test_actions_follow_the_app_in_front():
    assert uiplus.kind_of({"exe": "C:\\Program Files\\Google\\Chrome\\chrome.exe"}) == "browser"
    assert uiplus.kind_of({"app": "Microsoft Excel", "exe": "EXCEL.EXE"}) == "sheet"
    assert uiplus.kind_of({"app": "Spotify Premium"}) == "media"
    assert uiplus.kind_of({"exe": "neznamy.exe", "app": "Něco"}) == "any"
    acts = uiplus.actions_for({"exe": "chrome.exe"})
    assert acts[0]["label"] == "Shrnout stránku" and "text" in acts[0] and len(acts) == 4
    media = uiplus.actions_for({"exe": "spotify.exe"})
    assert media[0] == {"label": "Play / pauza", "icon": "play-pause", "quick": "media_control", "args": {"action": "play_pause"}}
    other = uiplus.actions_for({"exe": "neznamy.exe"})
    assert [a["label"] for a in other] == ["Co je na obrazovce?", "Screenshot"]


def test_own_actions_come_first():
    custom = [{"app": "excel", "label": "Měsíční report", "text": "Udělej souhrn za měsíc."},
              {"app": "winword", "label": "Jiné", "text": "x"}, {"app": "excel", "label": "Prázdné", "text": ""}]
    acts = uiplus.actions_for({"exe": "EXCEL.EXE", "app": "Excel"}, custom)
    assert acts[0] == {"label": "Měsíční report", "icon": "lightning", "text": "Udělej souhrn za měsíc."}
    assert all(a["label"] not in ("Jiné", "Prázdné") for a in acts)


def test_quick_actions_in_actions_are_allowed_in_the_notch():
    from jarvis.server.ws import QUICK_ACTIONS

    for acts in uiplus.ACTIONS.values():
        for a in acts:
            assert ("text" in a) != ("quick" in a)
            if "quick" in a:
                assert a["quick"] in QUICK_ACTIONS


def test_app_context_never_shows_jarvis_or_the_title(rt):
    rt.platform.front = {"hwnd": 1, "pid": os.getpid(), "app": "JARVIS", "title": "Notch"}
    rt.activity.last_external = {"hwnd": 2, "pid": 99, "app": "Google Chrome", "exe": "chrome.exe", "title": "Moje banka – účet"}
    c = uiplus.app_context(rt)
    assert c["app"] == "Google Chrome" and c["kind"] == "browser"
    assert "title" not in c and "banka" not in str(c)
    rt.platform.front = {"hwnd": 3, "pid": 77, "app": "Excel", "exe": "excel.exe", "title": "Platy.xlsx"}
    assert uiplus.app_context(rt)["kind"] == "sheet"


def test_suggestions(rt):
    now = time.time()
    events = [{"title": "Porada s Petrem", "start": now + 10 * 60}, {"title": "Pozdější", "start": now + 3 * 3600}]
    s = uiplus.suggestions(rt, events, "https://example.com/clanek", now)
    assert s[0]["label"].startswith("Za 10 min: Porada") and "Porada s Petrem" in s[0]["text"]
    assert s[1]["label"] == "Shrnout odkaz ze schránky"
    assert uiplus.suggestions(rt, [], "slovo " * 100, now)[0]["label"] == "Shrnout text ze schránky"
    assert uiplus.suggestions(rt, [], "krátké", now) == []
    assert uiplus.suggestions(rt, [], "sk-ant-api03-" + "x" * 80, now) == []        # a key in the clipboard is never offered
    assert uiplus.suggestions(rt, [{"title": "Celý den", "start": now + 60, "all_day": True}], "", now) == []
    p = uiplus.add_pin(rt, "zavolat zubaři", now - 60)
    s = uiplus.suggestions(rt, [], "", now)
    assert s == [{"label": "Po termínu: zavolat zubaři", "icon": "push-pin", "text": "", "pin": p["id"]}]


def test_parse_due():
    now = dt.datetime(2026, 10, 26, 14, 0).timestamp()
    f = lambda t: dt.datetime.fromtimestamp(uiplus.parse_due(t, now)).strftime("%d %H:%M")  # noqa: E731
    assert f("v 15:30") == "26 15:30"
    assert f("zítra v 9") == "27 09:00"
    assert f("za 20 minut") == "26 14:20"
    assert f("za 2 hodiny") == "26 16:00"
    assert f("v 10") == "27 10:00"              # already past today → tomorrow
    assert f("pozítří") == "28 09:00"
    assert uiplus.parse_due("koupit mléko", now) is None
    assert uiplus.parse_due("koupit 2 rohlíky", now) is None


def test_pins(rt):
    a = uiplus.add_pin(rt, "  koupit   mléko ")
    b = uiplus.add_pin(rt, "zavolat Petrovi", time.time() + 3600)
    assert a["text"] == "koupit mléko"
    assert [p["text"] for p in uiplus.list_pins(rt)] == ["zavolat Petrovi", "koupit mléko"]   # timed ones first
    assert uiplus.find_pin(rt, "petr")["id"] == b["id"]
    assert uiplus.find_pin(rt, "2")["id"] == a["id"]
    uiplus.set_done(rt, a["id"])
    assert [p["text"] for p in uiplus.list_pins(rt)] == ["zavolat Petrovi"]
    assert uiplus.list_pins(rt, include_done=True)[-1]["done"] is True
    assert uiplus.clear_done(rt) == 1
    assert uiplus.remove_pin(rt, b["id"]) and uiplus.list_pins(rt) == []
    try:
        uiplus.add_pin(rt, "   ")
        raise AssertionError
    except ValueError:
        pass
    for i in range(uiplus.MAX_PINS):
        uiplus.add_pin(rt, f"úkol {i}")
    try:
        uiplus.add_pin(rt, "jeden navíc")
        raise AssertionError
    except ValueError as e:
        assert "30" in str(e)


def test_due_pins_are_announced_once(rt):
    p = uiplus.add_pin(rt, "vyndat prádlo", time.time() - 5)
    uiplus.add_pin(rt, "později", time.time() + 3600)
    assert [x["id"] for x in uiplus.due_reminders(rt)] == [p["id"]]
    assert uiplus.due_reminders(rt) == []


async def test_activity_tells_the_notch_and_reminds(rt):
    q = rt.bus.subscribe()
    rt.activity.last_external = {"app": "Spotify", "exe": "spotify.exe", "pid": 5}
    rt.activity.ui_tick()
    ctx = [m for m in drain(q) if m["type"] == "app_context"]
    assert ctx and ctx[0]["kind"] == "media"
    rt.activity.ui_tick()                                   # same app → nothing new
    assert not [m for m in drain(q) if m["type"] == "app_context"]
    uiplus.add_pin(rt, "zalít kytky", time.time() - 1)
    rt.activity.ui_tick()
    msgs = drain(q)
    assert any(m["type"] == "notify" and m["body"] == "zalít kytky" for m in msgs)
    assert any(m["type"] == "pins" for m in msgs)


async def test_pin_tools(rt):
    r = await tools.call("pin_task", {"text": "poslat fakturu", "when": "zítra v 9"}, rt)
    assert r.ok and "zítra 09:00" in r.summary
    r = await tools.call("pin_task", {"text": "koupit chleba"}, rt)
    assert r.ok and "(" not in r.summary
    r = await tools.call("pinned_tasks", {}, rt)
    assert "1. poslat fakturu" in r.summary and "2. koupit chleba" in r.summary
    assert (await tools.call("pin_done", {"which": "chleba"}, rt)).ok
    assert not (await tools.call("pin_done", {"which": "neexistuje"}, rt)).ok
    assert (await tools.call("unpin_task", {"which": "1"}, rt)).ok
    assert (await tools.call("pinned_tasks", {}, rt)).summary == "V notchi nemáš nic připnutého."


def test_config_defaults():
    c = Config()
    assert c.notch.open_on == "hover" and c.notch.tuck_minutes == 10 and c.notch.app_actions == []
    assert c.appearance.density == "auto" and c.stark.hud_layout == "full"


def _until(ws, kind, n=80):
    for _ in range(n):
        m = ws.receive_json()
        if m.get("type") == kind:
            return m
    raise AssertionError(f"no {kind}")


def test_ws_pins_context_and_workspaces(rt):
    rt.activity.last_external = {"app": "Excel", "exe": "excel.exe", "pid": 7}
    rt.platform.front = {"hwnd": 1, "pid": os.getpid(), "app": "JARVIS"}
    rt.platform.clipboard = "https://example.com"
    with TestClient(create_app(rt, manage_runtime=False), client=LOCAL) as c, c.websocket_connect("/ws") as ws:
        welcome = _until(ws, "welcome")
        assert welcome["pins"] == []
        ws.send_json({"type": "pin_add", "text": "porada v 15:00"})
        pins = _until(ws, "pins")["items"]
        assert pins[0]["text"] == "porada" and pins[0]["due"]
        ws.send_json({"type": "pin_done", "id": pins[0]["id"]})
        assert _until(ws, "pins")["items"] == []
        ws.send_json({"type": "notch_context_get"})
        ctx = _until(ws, "app_context")
        assert ctx["kind"] == "sheet" and ctx["actions"][0]["label"] == "Vysvětlit vzorec"
        assert any(s["label"] == "Shrnout odkaz ze schránky" for s in ctx["suggestions"])
        ws.send_json({"type": "workspaces_get"})
        assert _until(ws, "workspaces")["items"] == []


def test_time_words_leave_the_pin_text():
    now = dt.datetime(2026, 10, 26, 14, 0).timestamp()
    assert uiplus.split_due("zavolat Petrovi zítra v 9", now)[0] == "zavolat Petrovi"
    assert uiplus.split_due("zalít kytky za 20 minut", now)[0] == "zalít kytky"
    assert uiplus.split_due("porada v 15:30", now)[0] == "porada"
    assert uiplus.split_due("koupit mléko", now) == ("koupit mléko", None)
    assert uiplus.split_due("v 9", now)[0] == "v 9"            # nothing else left → keep what was said
