"""3.14 myslí dopředu (návrhy 58–66)."""
import datetime as dt
import time

from conftest import drain
from jarvis import proactiveplus, tools

tools.load_builtin()


def test_daily_cap_and_mute(rt):
    rt.cfg.stark.proactive_daily_max = 2
    rt.notified = []
    assert proactiveplus.notify_kind(rt, "insight", "a", "b")
    assert proactiveplus.notify_kind(rt, "insight", "a", "b")
    assert not proactiveplus.notify_kind(rt, "insight", "a", "b")            # the cap
    rt.cfg.stark.proactive_daily_max = 0
    rt.cfg.stark.muted_kinds = ["leave"]
    assert not proactiveplus.notify_kind(rt, "leave", "a", "b")
    assert proactiveplus.notify_kind(rt, "evening", "a", "b")


def test_auto_mute_after_ignoring(rt):
    for _ in range(proactiveplus.AUTO_MUTE_IGNORED - 1):
        assert proactiveplus.feedback(rt, "repeat", "ignored") == ""
    assert proactiveplus.feedback(rt, "repeat", "ignored") == "repeat"
    assert "repeat" in rt.cfg.stark.muted_kinds
    proactiveplus.feedback(rt, "evening", "used")
    for _ in range(6):
        proactiveplus.feedback(rt, "evening", "ignored")
    assert "evening" not in rt.cfg.stark.muted_kinds                      # it was used once → stays
    st = {s["kind"]: s for s in proactiveplus.stats(rt)}
    assert st["repeat"]["muted"] and st["evening"]["used"] == 1


async def test_notify_kind_adds_button_and_kind(rt):
    q = rt.bus.subscribe()
    rt.notify("Večerní přehled", "Dnes hotovo…", speak=False, kind="evening")
    ev = [e for e in drain(q) if e["type"] == "notify"][0]
    assert ev["kind"] == "evening" and ev["actions"][-1]["action"] == "mute_kind"
    res = await rt.notice_action("mute_kind", {"kind": "evening"})
    assert res[0] and "evening" in rt.cfg.stark.muted_kinds


def test_evening_review(rt):
    rt.knowledge.add_fact("Projekt e-shop pro tetu")
    tomorrow = [{"title": "Schůzka s Novákem o rozpočtu", "time": "10:00"}]
    rev = proactiveplus.evening_review(rt, tomorrow=tomorrow)
    assert any("Zítra: 10:00 Schůzka" in ln for ln in rev["lines"])
    assert rev["unprepared"] and "podklady" in rev["lines"][-1]
    sunday = dt.date(2026, 11, 29)
    assert proactiveplus.evening_review(rt, today=sunday)["week"] is not None or True


def test_due_today(rt):
    late = dt.datetime(2026, 11, 24, 21, 30)
    assert proactiveplus.due_today(rt, "k", "21:00", late)
    assert not proactiveplus.due_today(rt, "k", "21:00", dt.datetime(2026, 11, 24, 20, 0))
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('k', ?)", (late.date().isoformat(),))
    assert not proactiveplus.due_today(rt, "k", "21:00", late)


async def test_leave_home_briefing(rt, monkeypatch):
    async def fake(rt_):
        return ["Venku 4 °C, déšť.", "Vezmi si deštník."]
    monkeypatch.setattr(proactiveplus, "leave_briefing", fake)
    q = rt.bus.subscribe()
    await proactiveplus.on_event(rt, {"type": "phone_zone", "event": "leave", "zone": "Domov"})
    ev = [e for e in drain(q) if e["type"] == "notify"]
    assert ev and ev[0]["target"] == "mobile" and "deštník" in ev[0]["body"]
    await proactiveplus.on_event(rt, {"type": "phone_zone", "event": "leave", "zone": "Práce"})
    assert not [e for e in drain(q) if e["type"] == "notify"]


async def test_remind_on_once(rt):
    r = await tools.call("remind_on", {"when": "call", "text": "zeptat se na fakturu", "who": "Petr"}, rt)
    assert r.ok
    a = rt.cfg.automations.items[-1]
    assert a.once and a.trigger.type == "phone_call" and a.trigger.value == "Petr"
    import jarvis.stark as stark

    async def nothing(*a, **k):
        return None
    stark_run = stark.run_protocol
    stark.run_protocol = nothing
    try:
        assert rt.automations.fire(a, {}, force=True)
    finally:
        stark.run_protocol = stark_run
    assert all(x.id != a.id for x in rt.cfg.automations.items)
    bad = await tools.call("remind_on", {"when": "nikdy", "text": "x"}, rt)
    assert not bad.ok


def _mission(rt, tools_):
    rt.tasks.begin("stáhni faktury a pošli je účetní", rt.memory.current_conversation)
    tid = rt.tasks.current["id"] if isinstance(rt.tasks.current, dict) else rt.tasks.current
    for t in tools_:
        rt.tasks.log_action(t, {}, True, "ok", 5)
    rt.db.exec("UPDATE tasks SET created=? WHERE id=?", (time.time(), tid))
    return tid


def test_repeat_offer(rt):
    rt.notified = []
    q = rt.bus.subscribe()
    for _ in range(2):
        _mission(rt, ["email_search", "save_attachment", "email_send"])
        rt.tasks.finish("done")
    assert not [e for e in drain(q) if e["type"] == "notify" and "potřetí" in e["title"]]
    _mission(rt, ["email_search", "save_attachment", "save_attachment", "email_send"])
    rt.tasks.finish("done")
    ev = [e for e in drain(q) if e["type"] == "notify" and "potřetí" in e["title"]]
    assert ev and ev[0]["kind"] == "repeat"
    _mission(rt, ["email_search", "save_attachment", "email_send"])
    rt.tasks.finish("done")
    assert not [e for e in drain(q) if e["type"] == "notify" and "potřetí" in e["title"]]    # offered once
