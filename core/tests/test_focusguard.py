"""3.12 focus guard: while focusing, the notch blinks when a distracting service comes to the front."""
import time

from conftest import drain

from jarvis import focusguard
from jarvis.server import ws


def test_what_counts_as_a_distraction():
    d = focusguard.distraction
    assert d({"exe": "chrome.exe", "title": "Jak na to - YouTube - Google Chrome"}) == "YouTube"
    assert d({"exe": "msedge.exe", "title": "(3) Instagram - Microsoft Edge"}) == "Instagram"
    assert d({"exe": "firefox.exe", "title": "TikTok - Make Your Day — Mozilla Firefox"}) == "TikTok"
    assert d({"exe": "Netflix.exe", "title": "Netflix"}) == "Netflix"
    assert d({"exe": "chrome.exe", "title": "Lofi - YouTube Music - Google Chrome"}) == ""       # music is fine
    assert d({"exe": "Spotify.exe", "title": "Spotify Premium"}) == ""
    assert d({"exe": "Code.exe", "title": "main.py - Visual Studio Code"}) == ""
    assert d({}) == "" and d(None) == ""


def test_blinks_only_while_focusing_and_not_every_check(rt):
    now = [1000.0]
    g = focusguard.Guard(rt, clock=lambda: now[0])
    yt = {"exe": "chrome.exe", "title": "Video - YouTube - Google Chrome"}
    q = rt.bus.subscribe()
    assert g.check(yt) is None                                         # focus off: nothing
    rt.attention.focus_until = time.time() + 1500
    now[0] = time.time()
    assert g.check(yt) == "YouTube"
    ev = [e for e in drain(q) if e["type"] == "focus_nudge"]
    assert ev and ev[0]["app"] == "YouTube" and "title" not in ev[0]   # only the service, never the window title
    assert g.check(yt) is None                                         # still there: not again right away
    now[0] += focusguard.REPEAT_S + 1
    assert g.check(yt) == "YouTube"                                    # still there after a while: again
    assert g.check({"exe": "Code.exe", "title": "x.py - Visual Studio Code"}) is None
    assert g.check(yt) == "YouTube"                                    # came back: at once
    rt.cfg.notch.focus_guard = False
    now[0] += focusguard.REPEAT_S + 1
    assert g.check(yt) is None                                         # off in settings


def test_focus_mood_counts_too(rt):
    rt.attention.focus_until = 0
    assert not focusguard.focus_active(rt)
    rt.mood.set_manual("focus")
    assert focusguard.focus_active(rt)
    rt.mood.set_manual(None)


def test_nudge_is_a_server_message():
    assert "focus_nudge" in ws.SERVER_TYPES
