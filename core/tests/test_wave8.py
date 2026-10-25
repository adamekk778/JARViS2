"""OMEGA wave 8 (proactive): forgotten work, unanswered conversations, routines from hourly app use, deadline risks,
effort from history, next actions (and in a spare moment), the day summary, quiet hours that never mute an alarm."""
import datetime as dt
import time

from jarvis import proactive, tools

tools.load_builtin()
NOW = time.time()


def test_forgotten_and_unanswered(rt):
    tid = rt.tasks.begin("Vyřídit pojistku", rt.memory.current_conversation)
    rt.db.exec("UPDATE tasks SET status='paused', created=? WHERE id=?", (NOW - 10 * 86400, tid))
    rt.knowledge.create_project("Kolo")
    rt.db.exec("UPDATE projects SET updated=? WHERE name='Kolo'", (NOW - 20 * 86400,))
    from jarvis.tools.list_tools import add_items

    add_items(rt, "nákup", ["žárovka"])
    rt.db.exec("UPDATE lists SET ts=?", (NOW - 9 * 86400,))
    f = proactive.forgotten(rt, 7, NOW)
    kinds = [x["kind"] for x in f]
    assert kinds[0] == "project" and {"mission", "list"} <= set(kinds)
    rt.memory.add_message("user", "Kolik stojí letenka do Říma?")
    rt.db.exec("UPDATE messages SET created=? WHERE role='user'", (NOW - 3600,))
    u = proactive.unfinished_conversations(rt, 14, NOW)
    assert u and u[0]["why"] == "tvoje zpráva zůstala bez odpovědi"


def test_routines_from_hourly_app_use(rt):
    monday = dt.date(2026, 10, 26)
    for i in range(5):                              # Mon–Fri 8:00 Outlook, 15 min each
        d = (monday + dt.timedelta(days=i)).isoformat()
        rt.db.exec("INSERT INTO app_hours VALUES (?,?,?,?)", (d, 8, "Outlook", 900))
    rt.db.exec("INSERT INTO app_hours VALUES (?,?,?,?)", ((monday + dt.timedelta(days=5)).isoformat(), 21, "Steam", 3600))
    r = proactive.routines(rt, today=monday + dt.timedelta(days=6))
    assert len(r) == 1 and r[0]["app"] == "Outlook" and r[0]["hour"] == 8 and r[0]["when"] == "všední den" and r[0]["days"] == 5


def test_activity_records_hours(rt):
    rt.platform.foreground_info = lambda: {"hwnd": 1, "pid": -1, "app": "Word"}
    rt.platform.idle_seconds = lambda: 0
    rt.cfg.powers.screen_time = True
    t = dt.datetime(2026, 10, 26, 9, 15).timestamp()
    rt.activity.sample(now=t, dt_s=3)
    rt.activity.sample(now=t + 3, dt_s=3)
    assert rt.db.one("SELECT hour, seconds FROM app_hours WHERE app='Word'") == {"hour": 9, "seconds": 6}


def test_deadline_risks_and_effort(rt):
    tid = rt.tasks.begin("Odevzdat projekt", rt.memory.current_conversation)
    rt.db.exec("UPDATE tasks SET deadline=? WHERE id=?", (NOW + 3600, tid))
    rt.tasks.set_plan(["krok 1", "krok 2", "krok 3"], 0)
    r = proactive.deadline_risks(rt, NOW)
    assert r[0]["risk"] == "vysoké" and "kroků 3" in r[0]["text"]
    rt.learning.plan_exam("Matika", dt.date.today() + dt.timedelta(days=2), ["zlomky"])
    assert any(x["kind"] == "exam" and x["risk"] == "vysoké" for x in proactive.deadline_risks(rt, NOW))
    for i, mins in enumerate((10, 20, 30)):
        t = rt.tasks.begin(f"Uklidit plochu {i}", rt.memory.current_conversation)
        rt.db.exec("UPDATE tasks SET status='done', created=?, finished=? WHERE id=?", (NOW - 7200, NOW - 7200 + mins * 60, t))
    e = proactive.effort_estimate(rt, "uklidit plochu")
    assert e["known"] and e["similar"] == 3 and e["median_minutes"] == 20.0
    assert not proactive.effort_estimate(rt, "postavit raketu")["known"]


async def test_what_next_ranks_and_fits_the_time(rt):
    tid = rt.tasks.begin("Poslat fakturu", rt.memory.current_conversation)
    rt.db.exec("UPDATE tasks SET deadline=? WHERE id=?", (NOW + 1800, tid))
    for i in range(5):
        rt.learning.add_card("A", f"q{i}", "a")
    r = await tools.call("what_next", {}, rt)
    assert r.ok and r.data[0]["why"].startswith("riziko termínu") and any("kartiček" in x["text"] for x in r.data)
    short = await tools.call("what_next", {"minutes": 5}, rt)
    assert all(x["minutes"] <= 5 for x in short.data) and any("kartiček" in x["text"] for x in short.data)


async def test_day_summary(rt):
    t = rt.tasks.begin("Napsat dopis", rt.memory.current_conversation)
    rt.db.exec("UPDATE tasks SET status='done', finished=? WHERE id=?", (NOW, t))
    rt.memory.add_message("user", "ahoj")
    r = await tools.call("day_summary", {}, rt)
    assert r.ok and "dokončeno 1 misí (Napsat dopis)" in r.summary and "1 zpráv" in r.summary


def test_quiet_hours_never_mute_an_alarm(rt, monkeypatch):
    rt.cfg.stark.smart_quiet = True
    said = []
    rt.speak = lambda text, lang="cs": said.append(text)
    monkeypatch.setattr(proactive, "quiet_reason", lambda rt_, now=None: "noc")
    rt.notify("Síť", "Nové zařízení v síti.")
    rt.notify("⏲ Vajíčka", "Vajíčka – čas vypršel!", urgent=True)
    assert said == ["Vajíčka – čas vypršel!"]
    monkeypatch.setattr(proactive, "quiet_reason", lambda rt_, now=None: "")
    rt.notify("Síť", "Teď už ano.")
    assert said[-1] == "Teď už ano."


def test_quiet_reason_rules(rt):
    night = dt.datetime(2026, 10, 26, 23, 0).timestamp()
    day = dt.datetime(2026, 10, 26, 14, 0).timestamp()
    assert proactive.quiet_reason(rt, night) == "noc"
    assert proactive.quiet_reason(rt, day) == ""
    rt.calendar.add("Porada", dt.datetime(2026, 10, 26, 13, 30), 60)
    assert proactive.quiet_reason(rt, day) == "schůzka"
    rt.db.exec("DELETE FROM cal_events")
    rt.mood.manual = "focus"
    assert proactive.quiet_reason(rt, day) == "soustředění"
