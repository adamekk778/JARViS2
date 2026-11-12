"""3.12 Chytrý režim schůzky: a call is noticed, the notes are only offered, the end stops them; notices wait."""
from jarvis import meetings


def events(q, kind):
    out = []
    while not q.empty():
        m = q.get_nowait()
        if m.get("type") == kind:
            out.append(m)
    return out


def test_call_apps_on_the_microphone_are_a_call_but_jarvis_is_not(rt):
    rt.platform.mic = ["python.exe"]                          # JARVIS's own wake word
    assert meetings.detect(rt) == ""
    rt.platform.mic = ["ms-teams.exe", "python.exe"]
    assert meetings.detect(rt) == "Teams"
    rt.platform.mic = ["chrome.exe"]
    rt.platform.list_windows = lambda: ["Meet - abc-defg-hij - Google Chrome"]
    assert meetings.detect(rt) == "Google Meet"


def test_offered_not_recorded_and_ended_after_a_while(rt, monkeypatch):
    q = rt.bus.subscribe()
    m = rt.meetings
    rt.platform.mic = ["zoom.exe"]
    m.tick()
    assert not m.active                                       # one look is not enough (a mic test)
    m.tick()
    assert m.active and events(q, "meeting")[-1] == {"type": "meeting", "state": "started", "app": "Zoom", "recording": False}
    assert rt.notetaker.state == "idle"                       # nothing records by itself
    assert rt.attention.busy_reason() == "hovor"              # less important notices wait
    rt.platform.mic = []
    for _ in range(3):
        m.tick()
    assert not m.active and events(q, "meeting")[-1]["state"] == "ended"


def test_your_click_records_and_the_end_stops_it(rt, monkeypatch):
    calls = []
    monkeypatch.setattr(rt.notetaker, "start", lambda: (calls.append("start"), setattr(rt.notetaker, "state", "recording"), {"ok": True})[2])
    monkeypatch.setattr(rt.notetaker, "stop", lambda cancel=False: (calls.append("stop"), setattr(rt.notetaker, "state", "processing"), {"ok": True})[2])
    m = rt.meetings
    rt.platform.mic = ["discord.exe"]
    m.tick()
    m.tick()
    assert m.record(True)["ok"] and m.recording
    rt.platform.mic = []
    for _ in range(3):
        m.tick()
    assert calls == ["start", "stop"] and not m.recording
