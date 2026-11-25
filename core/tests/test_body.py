"""3.14 Zdraví jako ve filmu: the watch's numbers, the morning verdict, care at the PC."""
import datetime as dt

from jarvis import body, tools

tools.load_builtin()

T = dt.date(2026, 11, 24)


def _normal_fortnight(rt, sleep=7.5, rest=58, hrv=60):
    for k in range(1, 15):
        body.record(rt, (T - dt.timedelta(days=k)).isoformat(), sleep_h=sleep, rest_hr=rest + (k % 3) - 1, hrv=hrv, steps=8000 + k)


def test_record_keeps_only_real_numbers_and_never_lowers_steps(rt):
    d = T.isoformat()
    assert body.record(rt, d, steps=3000, rest_hr=500, spo2=40, hrv="x") == {"steps": 3000.0}
    assert body.record(rt, d, steps=2500) == {}                 # an older, smaller count never wins
    assert body.record(rt, d, steps=5200, rest_hr=61) == {"steps": 5200.0, "rest_hr": 61.0}
    assert body.day(rt, d)["steps"] == 5200 and body.day(rt, d)["rest_hr"] == 61


def test_baseline_needs_a_few_days(rt):
    for k in range(1, 4):
        body.record(rt, (T - dt.timedelta(days=k)).isoformat(), rest_hr=60)
    assert body.baseline(rt, "rest_hr", T.isoformat()) is None   # 3 days are not "your normal" yet
    body.record(rt, (T - dt.timedelta(days=4)).isoformat(), rest_hr=64)
    assert body.baseline(rt, "rest_hr", T.isoformat()) == 60


def test_bad_night_means_a_lighter_day(rt):
    _normal_fortnight(rt)
    body.record(rt, T.isoformat(), sleep_h=4.9, rest_hr=67, hrv=41)
    s = body.status(rt, T)
    assert s["level"] == "easy"
    assert "Stav systémů: spánek 4,9 h (obvykle 7,5)" in s["text"]
    assert "doporučuji lehčí den" in s["text"].lower()
    assert any("klidový tep 67" in r for r in s["reasons"])
    assert "včera 8 001 kroků" in s["text"]


def test_good_night_is_full_power(rt):
    _normal_fortnight(rt)
    body.record(rt, T.isoformat(), sleep_h=7.8, rest_hr=57, hrv=63)
    s = body.status(rt, T)
    assert s["level"] == "full" and s["reasons"] == []
    assert "plné síle" in s["text"]


def test_low_oxygen_suggests_a_doctor_and_no_data_says_nothing():
    level, flags = body.assess({"sleep_h": 7, "spo2": 89}, {})
    assert level == "easy" and "lékařem" in body.plan_for(level, flags)
    assert body.assess({"steps": 5000}, {})[0] == "unknown"


async def test_morning_briefing_has_the_body_line(rt):
    from jarvis import stark

    _normal_fortnight(rt)
    body.record(rt, dt.date.today().isoformat(), sleep_h=5.0)
    b = await stark.briefing(rt, news=False)
    assert "Stav systémů: spánek 5 h" in b["text"]
    rt.cfg.health.morning = False
    assert "Stav systémů" not in (await stark.briefing(rt, news=False))["text"]


def test_phone_message_feeds_habits_and_body(rt):
    from jarvis import habits

    habits.seed(rt)
    d = dt.date.today().isoformat()
    out = body.from_phone(rt, {"day": d, "steps": 6400, "sleep_h": 7.2, "rest_hr": 55, "hrv": 70, "hr": 72, "spo2": 97})
    assert out["rest_hr"] == 55 and out["hrv"] == 70
    snap = habits.snapshot(rt)
    assert snap["body"]["now"]["sleep_h"] == 7.2


def _desk(rt):
    said = []
    rt.notify = lambda title, text, **kw: said.append((title, text, kw))
    rt.call_soon = lambda f: f()
    return body.DeskCare(rt), said


def test_water_long_day_and_bedtime(rt):
    d, said = _desk(rt)
    rt.cfg.health.water_minutes = 60
    rt.cfg.health.long_day_h = 1
    rt.cfg.health.bedtime = "23:00"
    t0 = dt.datetime(2026, 11, 24, 21, 0).timestamp()
    out = []
    for i in range(0, 125):                                    # two hours at the PC, a minute at a time
        now = t0 + i * 60
        out += d.tick(now, 10, dt.datetime.fromtimestamp(now))
    assert out.count("water") == 2 and out.count("long") == 1 and "bed" in out
    assert any(t == "Pitný režim" and kw["actions"][0]["action"] == "water_done" for t, _, kw in said)
    assert any("už 1 h." in txt for t, txt, _ in said if t == "Dlouhý den u PC")


def test_bedtime_after_midnight_and_last_night(rt):
    d, said = _desk(rt)
    rt.cfg.health.bedtime = "23:30"
    body.record(rt, "2026-11-24", sleep_h=5.2)                # the night before the 24th
    clock = dt.datetime(2026, 11, 25, 0, 40)                   # still up after midnight
    assert d.tick(clock.timestamp(), 5, clock) == ["bed"]
    assert "spal jen 5,2 h" in said[-1][1]
    assert d.tick(clock.timestamp() + 60, 5, clock + dt.timedelta(minutes=1)) == []   # once a night
    assert not body.DeskCare._past_bedtime(dt.datetime(2026, 11, 25, 14, 0), "23:30")


def test_away_from_the_pc_counts_as_drinking(rt):
    d, _ = _desk(rt)
    rt.cfg.health.water_minutes = 30
    t0 = 1_000_000.0
    d.tick(t0, 0)
    assert d.tick(t0 + 25 * 60, 10 * 60) == []                 # 10 minutes away → the clock restarts from then
    assert d.tick(t0 + 40 * 60, 0) == []
    assert d.tick(t0 + 46 * 60, 0) == ["water"]


def test_posture_learns_your_good_sitting_then_warns(rt):
    d, said = _desk(rt)
    good = (300, 160, 140, 140)
    for i in range(5):
        assert d.posture_step(i * 120.0, good, 1280, 720) == ""
    base = d.posture_base()
    assert base and base["w"] == 140
    assert body.posture_verdict((280, 140, 180, 180), 1280, 720, base) == "close"
    assert body.posture_verdict((300, 260, 140, 140), 1280, 720, base) == "low"
    assert body.posture_verdict(good, 1280, 720, base) == "ok"
    leaning = (280, 140, 180, 180)
    res = [d.posture_step(1000 + i * 120.0, leaning, 1280, 720) for i in range(3)]
    assert res == ["", "", "close"] and "blízko" in said[-1][1]
    assert d.posture_step(1400, leaning, 1280, 720) == ""     # not again within half an hour


def test_water_done_ticks_the_water_habit(rt):
    from jarvis import habits

    habits.seed(rt)
    water = next(h for h in habits.habits(rt) if h["name"] == "Voda")
    assert "Voda" in body.water_done(rt)
    row = rt.db.one("SELECT value FROM habit_log WHERE habit_id=? AND day=?", (water["id"], dt.date.today().isoformat()))
    assert row["value"] == 1


async def test_tools(rt):
    r = await tools.call("body_status", {}, rt)
    assert r.ok and "Health Connect" in r.summary
    _normal_fortnight(rt)
    body.record(rt, dt.date.today().isoformat(), sleep_h=7.6, rest_hr=58)
    r = await tools.call("body_status", {}, rt)
    assert "Stav systémů" in r.summary
    r = await tools.call("body_history", {"days": 7}, rt)
    assert "průměrně" in r.summary
    r = await tools.call("health_reminders", {"water_minutes": 45, "bedtime": "23.15", "posture": "on"}, rt)
    assert r.ok and rt.cfg.health.water_minutes == 45 and rt.cfg.health.bedtime == "23:15" and rt.cfg.health.posture
    assert "sedni si teď rovně" in r.summary
    r = await tools.call("health_reminders", {"bedtime": "25:00"}, rt)
    assert not r.ok


async def test_water_button(rt):
    ok, text = await rt.notice_action("water_done", {})
    assert ok and text
