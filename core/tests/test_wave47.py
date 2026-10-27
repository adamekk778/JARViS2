"""Wave 47: notch anchored above a window, hand-offs, Mochi on the phone, PC parts for the 3D explorer."""
import time

from conftest import FakeRouter, drain
from jarvis import mochiplus, tools

tools.load_builtin()

WINS = [{"hwnd": 1, "title": "Dokument1 - Word", "app": "Word", "x": 0, "y": 0, "w": 960, "h": 1080},
        {"hwnd": 2, "title": "Seznam - Google Chrome", "app": "Chrome", "x": 1200, "y": 0, "w": 720, "h": 1080}]


def test_target_window():
    assert mochiplus.target_window("ui_click", {"window": "word"}, WINS)["hwnd"] == 1
    assert mochiplus.target_window("type_text", {"app": "Chrome"}, WINS)["hwnd"] == 2
    assert mochiplus.target_window("web_search", {"query": "word"}, WINS) is None          # not a window tool, no window arg
    assert mochiplus.target_window("ui_click", {"window": "Excel"}, WINS) is None


def test_anchor_offset():
    assert mochiplus.anchor_offset(None, 0, 1920, 300) == 0
    assert mochiplus.anchor_offset(WINS[0], 0, 1920, 300) == -480                      # above the middle of Word
    assert mochiplus.anchor_offset(WINS[1], 0, 1920, 300) == 600                        # Chrome's centre 1560 → clamped to the edge
    far = {"x": 1900, "y": 0, "w": 20, "h": 10}
    assert mochiplus.anchor_offset(far, 0, 1920, 300) == (1920 - 300 - 24) - (1920 - 300) // 2


async def test_agent_anchors_notch(rt, monkeypatch):
    monkeypatch.setattr(rt.platform, "window_layout", lambda: WINS)
    seen = []
    rt.on_anchor = seen.append
    q = rt.bus.subscribe()
    rt.router = FakeRouter([[("ui_read", {"window": "Word"})], "Přečteno."])
    await rt.agent.handle("co je v dokumentu?")
    ev = [e for e in drain(q) if e["type"] == "anchor"]
    assert ev[0]["cx"] == 0.25 and "Word" in ev[0]["title"] and ev[-1]["cx"] is None
    assert seen[0]["hwnd"] == 1 and seen[-1] is None
    rt.cfg.notch.follow_window = False
    rt.set_anchor(WINS[1])
    assert seen[-1] is None


async def test_handoff_events(rt):
    q = rt.bus.subscribe()
    rt.clients["x"] = {"client": "mobile"}
    r = await tools.call("send_to_phone", {"text": "nákupní seznam", "url": "https://example.com/?utm_source=x"}, rt)
    assert r.ok
    ho = [e for e in drain(q) if e["type"] == "handoff"]
    assert ho == [{"type": "handoff", "to": "phone", "label": "https://example.com/", "kind": "link"}] or (ho and ho[0]["to"] == "phone")


async def test_share_from_phone_hands_off(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    q = rt.bus.subscribe()
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "share", "kind": "text", "value": "poznámka z mobilu"})
        for _ in range(30):
            if ws.receive_json()["type"] == "quick_result":
                break
    ho = [e for e in drain(q) if e["type"] == "handoff"]
    assert ho and ho[0]["to"] == "pc" and ho[0]["label"] == "poznámka z mobilu"


def test_mochi_move(rt):
    import pytest

    with pytest.raises(ValueError):
        mochiplus.mochi_move(rt, "phone")                      # no phone connected
    rt.clients["p"] = {"client": "mobile"}
    q = rt.bus.subscribe()
    st = mochiplus.mochi_move(rt, "phone")
    assert st["at"] == "phone" and rt.mochi_at == "phone"
    evs = drain(q)
    assert any(e["type"] == "mochi_where" and e["at"] == "phone" for e in evs) and any(e["type"] == "handoff" and e["kind"] == "mochi" for e in evs)
    assert mochiplus.mochi_move(rt, "pc")["at"] == "pc"
    with pytest.raises(ValueError):
        mochiplus.mochi_move(rt, "tv")


def test_hardware_overview():
    r = mochiplus.hardware_overview()
    kinds = [p["kind"] for p in r["parts"]]
    assert kinds[0] == "cpu" and "ram" in kinds and any(k == "disk" for k in kinds)
    assert all(set(p) >= {"kind", "name", "detail", "load", "size"} for p in r["parts"]) and r["ts"] <= time.time()
