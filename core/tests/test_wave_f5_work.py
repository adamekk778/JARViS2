"""Wave F5b: Home Assistant sensor triggers (425), player volume (429), meetings → tasks / minutes / search (166 / 167 /
566 / 551), deadlines and content as .ics (171 / 565 / 446), the weekly work report (175)."""
import datetime as dt
import json
import time

from jarvis import notetaker, tools, workreport
from jarvis.automations import state_matches

tools.load_builtin()


def test_state_conditions():
    assert state_matches("> 25", "26.5") and not state_matches("> 25", "25")
    assert state_matches("<= 10", "10") and state_matches("= 3", "3.0")
    assert state_matches("open", "Open") and not state_matches("open", "closed")
    assert not state_matches("> 5", "unavailable")


async def test_home_state_trigger_fires_on_transition(rt):
    auto = {"id": "h1", "name": "Horko", "enabled": True, "trigger": {"type": "home_state", "value": "Teplota obývák", "text": "> 25", "days": []},
            "steps": [{"say": "{device} má {state}"}]}
    rt.update_config({"automations": {"items": [auto]}})
    fired = []
    rt.automations.fire = lambda a, vars=None, reason="", force=False: fired.append((a.id, vars)) or True
    st = lambda v: [{"id": "sensor.teplota_obyvak", "name": "Teplota obývák", "domain": "sensor", "state": v}]  # noqa: E731
    items = rt.automations.active()
    await rt.automations._home(items, st("27"))     # first look only learns (no firing at start-up)
    await rt.automations._home(items, st("24"))
    await rt.automations._home(items, st("26"))     # became true → fire
    await rt.automations._home(items, st("27"))     # still true → quiet
    assert [f[0] for f in fired] == ["h1"] and fired[0][1]["state"] == "26"
    from jarvis.automations import describe_trigger
    assert "má hodnotu > 25" in describe_trigger(rt.cfg.automations.items[0].trigger)


def _seed_note(rt, title="Porada s klientem", todos=("Poslat nabídku do pátku", "Zavolat Petrovi")):
    rt.notetaker  # noqa: B018 – make sure the table exists
    rt.db.exec("INSERT INTO notes (id, created, title, seconds, status, transcript, summary, points, todos) VALUES (?,?,?,?,?,?,?,?,?)",
               ("n1", time.time() - 3600, title, 1800, "done",
                json.dumps([{"who": "Já", "text": "Cenu necháme na 50 tisících."}, {"who": "Ostatní 1", "text": "Dobře, termín je březen."}], ensure_ascii=False),
                "Domluvili jsme cenu a termín.", json.dumps(["Cena 50 000 Kč"], ensure_ascii=False), json.dumps(list(todos), ensure_ascii=False)))


async def test_meeting_tasks_minutes_search(rt):
    _seed_note(rt)
    r = await tools.REGISTRY["meeting_tasks"].func(rt)
    assert r.ok and "Připnuto 2" in r.summary and any(p["due"] for p in r.data)
    hits = notetaker.search_notes(rt, "cenu")
    assert hits and hits[0]["id"] == "n1" and "50 tisících" in hits[0]["match"]
    assert notetaker.search_notes(rt, "neexistuje xyz") == []


def test_ics_and_content_plan():
    ev = [{"uid": "a", "title": "Odevzdat, projekt; v1", "start": dt.date(2026, 11, 20), "remind_h": 24},
          {"uid": "b", "title": "Schůzka", "start": dt.datetime(2026, 11, 21, 9, 30), "note": "řádek 1\nřádek 2"}]
    s = workreport.ics(ev)
    assert s.startswith("BEGIN:VCALENDAR") and "DTSTART;VALUE=DATE:20261120" in s and "DTEND;VALUE=DATE:20261121" in s
    assert "SUMMARY:Odevzdat\\, projekt\\; v1" in s and "DTSTART:20261121T093000" in s and "TRIGGER:-PT24H" in s and "\r\n" in s
    plan = workreport.content_plan(["A", "B", "C", "D"], dt.date(2026, 11, 2), 2, ["IG", "FB"])     # Monday
    assert [p["start"].strftime("%a") for p in plan] == ["Tue", "Thu", "Tue", "Thu"] and plan[1]["title"] == "FB: B"


async def test_milestones_and_weekly_report(rt):
    tid = rt.tasks.enqueue("Dodělat web", deadline=time.time() + 3 * 86400)
    ev = workreport.milestones(rt)
    assert any(e["uid"] == f"task-{tid}" for e in ev)
    r = await tools.REGISTRY["deadlines_calendar"].func(rt)
    assert r.ok and r.data["path"].endswith(".ics")
    rep = workreport.weekly_report(rt)
    assert {"done", "failed", "meetings", "apps", "upcoming"} <= set(rep)
    assert any("Dodělat web" in u["title"] for u in rep["upcoming"])
    assert "# Týdenní report" in workreport.report_markdown(rep)
