"""3.12 Návyky a zdraví: tick what you did, JARVIS counts today / week / month, streaks, trend, the best habit."""
import asyncio
import datetime as dt

from jarvis import habits as hb


def _freeze(monkeypatch, day: dt.date):
    monkeypatch.setattr(hb, "today", lambda: day)


def test_a_sensible_start_and_today(rt):
    s = hb.snapshot(rt)
    names = [i["name"] for i in s["items"]]
    assert "Spánek" in names and "Trénink" in names and "Voda" in names
    assert s["today"]["due"] >= 5 and s["today"]["done"] == 0 and s["today"]["pct"] == 0
    hb.seed(rt)                                                      # never twice
    assert len(hb.habits(rt)) == len(names)


def test_tick_counts_and_amounts(rt):
    s = hb.snapshot(rt)
    by = {i["name"]: i for i in s["items"]}
    hb.log(rt, by["Zdravé jídlo"]["id"], 1)
    hb.log(rt, by["Voda"]["id"], 5)                                  # 5 of 8 glasses: not done yet
    hb.log(rt, by["Spánek"]["id"], 7.5)                              # 7.5 h ≥ 7: done
    s = hb.snapshot(rt)
    by = {i["name"]: i for i in s["items"]}
    assert by["Zdravé jídlo"]["done"] and by["Spánek"]["done"] and not by["Voda"]["done"] and by["Voda"]["value"] == 5
    assert s["today"]["done"] == 2 and s["today"]["pct"] == round(200 / s["today"]["due"])
    hb.log(rt, by["Zdravé jídlo"]["id"], 0)                          # untick
    assert hb.snapshot(rt)["today"]["done"] == 1


def test_streaks_week_and_month(rt, monkeypatch):
    start = dt.date(2026, 11, 2)                                     # a Monday
    _freeze(monkeypatch, start)
    hb.seed(rt)
    hid = hb.save(rt, {"name": "Čtení", "kind": "check"})
    _freeze(monkeypatch, start + dt.timedelta(days=6))               # Sunday, not read yet today
    for k in range(5):                                               # Mon–Fri read every day
        hb.log(rt, hid, 1, (start + dt.timedelta(days=k)).isoformat())
    s = hb.snapshot(rt)
    it = next(i for i in s["items"] if i["id"] == hid)
    assert it["streak"] == 0 and it["best"] == 5                     # Saturday was missed → the run ended
    assert it["last7"] == [True, True, True, True, True, False, False]
    grid = next(g for g in s["month"]["grid"] if g["id"] == hid)["cells"]
    assert grid[1:6] == ["done"] * 5 and grid[6] == "miss" and grid[7] == "today" and grid[8] == "future"
    assert s["month"]["days"] == 30 and s["month"]["first_weekday"] == 6       # 1 Nov 2026 is a Sunday
    assert len(s["trend"]) == 30 and s["week"] is not None


def test_planned_days_do_not_break_a_streak(rt, monkeypatch):
    mon = dt.date(2026, 11, 2)
    _freeze(monkeypatch, mon)
    hid = hb.save(rt, {"name": "Gym", "kind": "check", "days": "024"})   # Mon, Wed, Fri
    _freeze(monkeypatch, mon + dt.timedelta(days=6))
    for k in (0, 2, 4):
        hb.log(rt, hid, 1, (mon + dt.timedelta(days=k)).isoformat())
    it = next(i for i in hb.snapshot(rt)["items"] if i["id"] == hid)
    assert it["streak"] == 3 and it["due"] is False and it["rate30"] == 100


def test_meals_and_no_future(rt):
    hb.set_meal(rt, "obed", "kuře s rýží")
    assert next(m for m in hb.snapshot(rt)["meals"] if m["slot"] == "obed")["text"] == "kuře s rýží"
    hb.set_meal(rt, "obed", "")
    assert next(m for m in hb.snapshot(rt)["meals"] if m["slot"] == "obed")["text"] == ""
    hid = hb.habits(rt)[0]["id"] if hb.habits(rt) else hb.save(rt, {"name": "x"})
    import pytest
    with pytest.raises(ValueError):
        hb.log(rt, hid, 1, (dt.date.today() + dt.timedelta(days=1)).isoformat())


def test_by_voice(rt):
    from jarvis.tools import habit_tools as ht

    hb.seed(rt)
    r = asyncio.run(ht.habit_done(rt, "byl jsem v posilovně"))
    assert r.ok and "Trénink" in r.summary
    r = asyncio.run(ht.habit_done(rt, "voda", 3, add=True))
    r = asyncio.run(ht.habit_done(rt, "voda", 2, add=True))
    assert next(i for i in hb.snapshot(rt)["items"] if i["name"] == "Voda")["value"] == 5
    assert asyncio.run(ht.habit_done(rt, "spal jsem", 7)).ok
    assert "Dnes" in asyncio.run(ht.habit_status(rt)).summary
    assert asyncio.run(ht.meal_log(rt, "k snídani", "ovesná kaše")).ok
    assert not asyncio.run(ht.habit_done(rt, "skok do dálky")).ok


def test_removed_habit_keeps_history(rt):
    hid = hb.save(rt, {"name": "Běh", "kind": "check"})
    hb.log(rt, hid, 1)
    hb.remove(rt, hid)
    assert all(i["id"] != hid for i in hb.snapshot(rt)["items"])
    assert rt.db.one("SELECT value FROM habit_log WHERE habit_id=?", (hid,))["value"] == 1


def test_evening_reminder_once_and_only_when_something_is_left(rt):
    hb.seed(rt)
    assert hb.remind_time(rt) == "20:30"
    early = dt.datetime.combine(dt.date.today(), dt.time(19, 0))
    late = dt.datetime.combine(dt.date.today(), dt.time(21, 0))
    assert hb.remind_due(rt, early) == ""
    text = hb.remind_due(rt, late)
    assert "Ještě zbývá" in text and "Spánek" in text
    assert hb.remind_due(rt, late) == ""                              # once a day
    hb.set_remind(rt, "")
    assert hb.remind_time(rt) == "" and hb.snapshot(rt)["remind"] == ""
    hb.set_remind(rt, "7:5")
    assert hb.remind_time(rt) == "07:05"
