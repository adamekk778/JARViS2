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


def test_focus_sessions_add_up_for_today(rt):
    att = rt.attention
    q = rt.bus.subscribe()
    att.focus(25)
    start = [e for e in drain(q) if e["type"] == "focus"][-1]
    assert start["active"] and start["started"] > 0 and start["today"] < 1
    att.started -= 600                                  # 10 minutes in
    assert 590 < att.today_seconds() < 610
    att.focus(0)                                        # stopped: logged, the notch hears "done"
    end = [e for e in drain(q) if e["type"] == "focus"][-1]
    assert not end["active"] and end["done"] and 590 < end["session"] < 610 and 590 < end["today"] < 610
    assert att.started == 0 and att.today_seconds() == end["today"]
    att.focus(1)
    att.started -= 120
    att.focus_until = time.time() - 1                   # ran out on its own
    att.tick()
    end = [e for e in drain(q) if e["type"] == "focus"][-1]
    assert not end["active"] and end["done"] and 700 < end["today"] < 740


def test_focus_mode_is_a_quick_action():
    assert "focus_mode" in ws.QUICK_ACTIONS


def test_week_stats_streak_and_distractions(rt):
    """3.12 the weekly focus stats: minutes per day, a streak of days in a row and what pulled you away."""
    import datetime as dt

    att = rt.attention
    now = time.time()
    db = att._db()
    for back, secs in ((1, 1800), (2, 600), (3, 120), (4, 900)):       # day 3 has only 2 min → breaks the streak
        d = dt.date.fromtimestamp(now) - dt.timedelta(days=back)
        db.exec("INSERT INTO focus_log (day, start, seconds) VALUES (?, ?, ?)", (d.isoformat(), now - back * 86400, secs))
    att.note_nudge("YouTube", now)
    att.note_nudge("YouTube", now)
    att.note_nudge("Instagram", now)
    w = att.week(now)
    assert len(w["days"]) == 7 and w["days"][-1]["day"] == dt.date.fromtimestamp(now).isoformat()
    assert w["total"] == 1800 + 600 + 120 + 900
    assert w["streak"] == 2                       # yesterday + the day before (today not counted yet)
    assert w["longest"] == 1800 and w["sessions"] == 4
    assert w["distractions"][0] == {"app": "YouTube", "count": 2}
