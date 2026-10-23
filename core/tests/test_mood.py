from jarvis.llm.base import AllProvidersFailed
from jarvis.mood import MoodEngine


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def engine(rt):
    c = Clock()
    return MoodEngine(rt, clock=c), c


def test_listening_beats_dancing(rt):
    m, c = engine(rt)
    m.on_event({"type": "media", "playing": True})
    assert m.current["mood"] == "dancing"
    m.on_event({"type": "state", "state": "listening"})
    assert m.current["mood"] == "listening"
    m.on_event({"type": "state", "state": "idle"})
    assert m.current["mood"] == "dancing"


def test_error_during_music_then_back(rt):
    m, c = engine(rt)
    m.on_event({"type": "media", "playing": True})
    m.on_event({"type": "error", "message": "boom"})
    cur = m.current
    assert cur["mood"] == "error" and cur["detail"] == "boom"
    c.t += 4.1
    assert m.current["mood"] == "dancing"


def test_success_expires(rt):
    m, c = engine(rt)
    m.on_event({"type": "assistant_done", "tools": [{"ok": True, "summary": "x"}]})
    assert m.current["mood"] == "success"
    c.t += 2.1
    assert m.current["mood"] == "idle"


def test_failed_tool_is_error(rt):
    m, c = engine(rt)
    m.on_event({"type": "assistant_done", "tools": [{"ok": False, "summary": "nejde to"}]})
    assert m.current["mood"] == "error"


def test_waiting_and_working_progress(rt):
    m, c = engine(rt)
    m.on_event({"type": "state", "state": "waiting"})
    assert m.current["mood"] == "waiting"
    m.on_event({"type": "state", "state": "acting"})
    m.on_event({"type": "task_progress", "step": 3, "total": 10})
    cur = m.current
    assert cur["mood"] == "working" and abs(cur["progress"] - 0.3) < 1e-9


def test_sleep_after_inactivity_and_wake(rt):
    m, c = engine(rt)
    c.t += 601
    assert m.current["mood"] == "sleeping"
    m.on_event({"type": "user_message", "text": "ahoj"})
    assert m.current["mood"] == "idle"


def test_limit_from_router(rt):
    e = AllProvidersFailed({"omniroute": "HTTP 429: rate limit", "groq": "quota exceeded"})
    assert e.is_limit
    assert not AllProvidersFailed({"a": "ConnectError"}).is_limit
    m, c = engine(rt)
    m.on_event({"type": "error", "kind": "limit", "message": "limit"})
    assert m.current["mood"] == "limit"
    m.on_event({"type": "brain", "provider": "groq", "model": "x"})
    assert m.current["mood"] == "idle"


def test_notify_badge_and_clear(rt):
    m, c = engine(rt)
    m.on_event({"type": "notify", "title": "a", "body": "b"})
    m.on_event({"type": "notify", "title": "a", "body": "c"})
    cur = m.current
    assert cur["mood"] == "notify" and cur["badge"] == 2
    m.clear_notify()
    assert m.current["mood"] == "idle"


def test_offline_and_focus(rt):
    m, c = engine(rt)
    m.set_offline(True)
    assert m.current["mood"] == "offline"
    m.set_offline(False)
    m.set_manual("focus")
    assert m.current["mood"] == "focus"
    m.set_manual(None)
    assert m.current["mood"] == "idle"


def test_thanks_gives_joy(rt):
    m, c = engine(rt)
    m.on_event({"type": "user_message", "text": "Díky moc, super!"})
    m.on_event({"type": "assistant_done", "tools": []})
    assert m.current["mood"] == "joy"
    c.t += 3.1
    assert m.current["mood"] == "idle"


def test_publishes_only_on_change(rt):
    m, c = engine(rt)
    q = rt.bus.subscribe()
    m.on_event({"type": "state", "state": "thinking"})
    m.on_event({"type": "state", "state": "thinking"})
    moods = []
    while not q.empty():
        e = q.get_nowait()
        if e["type"] == "mood":
            moods.append(e["mood"])
    assert moods == ["thinking"]


async def test_agent_limit_message(rt):
    from conftest import FakeRouter

    rt.router = FakeRouter([AllProvidersFailed({"a": "HTTP 429 Too Many Requests"})])
    q = rt.bus.subscribe()
    out = await rt.agent.handle("ahoj")
    assert "limit" in out
    errs = []
    while not q.empty():
        e = q.get_nowait()
        if e["type"] == "error":
            errs.append(e)
    assert errs[0]["kind"] == "limit"
