"""3.12 Velín firmy 2: agents remember and never propose the same thing twice, react to e-mails / orders / payments,
hand work to each other in chains, keep to department limits, log everything, and write the weekly PDF report."""
import asyncio
import json

import pytest

from jarvis import bizagents, bizcompany, bizevents, bizreport, secrets, tools
from jarvis.llm.base import Chunk, ToolCall

tools.load_builtin()


class Router:
    def __init__(self, steps):
        self.steps, self.seen = list(steps), []

    async def stream(self, msgs, tools_=None, **kw):
        self.seen.append((msgs, kw))
        step = self.steps.pop(0) if self.steps else "hotovo"
        if isinstance(step, str):
            yield Chunk(text=step, done=True)
        else:
            yield Chunk(tool_calls=step, done=True)


@pytest.fixture
def rt(tmp_path, monkeypatch):
    from jarvis.runtime import Runtime

    store: dict[str, str] = {}
    monkeypatch.setattr(secrets, "get", lambda k: store.get(k, ""))
    monkeypatch.setattr(secrets, "set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    r = Runtime(persist_config=False)
    monkeypatch.setattr(r, "notify", lambda *a, **k: None)
    pushed = []
    monkeypatch.setattr(r, "phone_push", lambda kind, **d: pushed.append((kind, d)) or True)
    r.pushed = pushed
    bizagents.JOBS.clear()
    return r


def mail(to="a@b.cz", subject="Re: poptávka", body="Dobrý den"):
    return ToolCall(id="1", name="google_gmail_send", arguments={"to": to, "subject": subject, "body": body})


def test_the_same_proposal_is_not_made_twice_and_a_no_is_remembered(rt):
    aid = bizcompany.hire(rt, "lead_reply")
    a = bizagents.get(rt, aid)
    p1 = bizagents.propose(rt, a, mail(body="Dobrý den, posílám ceník."))
    p2 = bizagents.propose(rt, a, mail(body="Zdravím, tady je ceník."))           # other words, same e-mail
    assert p1 > 0 and p2 == -p1
    asyncio.run(bizagents.decide(rt, p1, False))
    assert bizagents.propose(rt, a, mail()) == -p1                               # you said no: not again for 30 days
    assert bizagents.propose(rt, a, mail(to="jiny@b.cz")) > 0                   # another person: a new proposal
    kinds = [x["kind"] for x in bizcompany.actions(rt)]
    assert kinds.count("proposal") == 2 and "rejected" in kinds


def test_the_agent_sees_its_recent_work_and_is_told_not_to_repeat(rt):
    aid = bizcompany.hire(rt, "lead_reply")
    rt.router = Router([[mail()], "připraveno"])
    asyncio.run(bizagents.run(rt, aid))
    rt.router = Router([[mail(body="jinými slovy")], "hotovo"])
    r = asyncio.run(bizagents.run(rt, aid))
    system = rt.router.seen[0][0][0]["content"]
    assert "TVOJE POSLEDNÍ PRÁCE" in system and "čeká na schválení" in system
    tool_answer = rt.router.seen[1][0][-1]["content"]
    assert "už bylo navrženo" in tool_answer and r["proposals"] == []
    assert len(bizagents.proposals(rt)) == 1


def test_events_start_the_subscribed_agents_after_the_first_look(rt, monkeypatch):
    items = [("g:1", "E-mail od Jan: „Poptávka“")]

    async def probe():
        return list(items)
    monkeypatch.setitem(bizevents.PROBES, "mail", probe)
    aid = bizcompany.hire(rt, "lead_triage")                                       # listens to "mail" by default
    assert bizagents.get(rt, aid)["triggers"] == ["mail"]
    assert asyncio.run(bizevents.check(rt)) == {"mail": 0} and not bizagents.JOBS   # the first look only remembers
    items.append(("g:2", "E-mail od Eva: „Objednávka 50 ks“"))
    assert asyncio.run(bizevents.check(rt))["mail"] == 1
    assert bizagents.JOBS[0]["aid"] == aid and "Eva" in bizagents.JOBS[0]["extra"] and "Jan" not in bizagents.JOBS[0]["extra"]
    items.append(("g:3", "E-mail od Petr"))
    asyncio.run(bizevents.check(rt))
    assert len(bizagents.JOBS) == 1 and "Petr" in bizagents.JOBS[0]["extra"]       # one job, the news added to it


def test_a_chain_hands_the_work_on(rt):
    names = bizcompany.build_chain(rt, "sales")
    assert names == ["Třídič poptávek", "Rychlá odpověď na poptávky", "Autor nabídek"]
    triage = next(a for a in bizagents.agents(rt) if a["bkey"] == "lead_triage")
    assert triage["next"] == ["lead_reply"]
    rt.router = Router(["Lead od Evy, 50 ks, hodnocení 5."])
    asyncio.run(bizagents.run(rt, triage["id"]))
    reply = next(a for a in bizagents.agents(rt) if a["bkey"] == "lead_reply")
    assert bizagents.JOBS and bizagents.JOBS[0]["aid"] == reply["id"] and "Lead od Evy" in bizagents.JOBS[0]["extra"]
    assert bizagents.JOBS[0]["depth"] == 1


def test_handoff_tool_and_depth_limit(rt):
    a = bizagents.get(rt, bizcompany.hire(rt, "lead_triage"))
    b = bizagents.get(rt, bizcompany.hire(rt, "proposals"))
    r = asyncio.run(tools.call("company_handoff", {"agent": "Autor nabídek", "task": "Nabídka pro hotel Šumava, 80 ks"}, rt))
    assert r.ok and bizagents.JOBS[-1]["aid"] == b["id"]
    token = bizagents._DEPTH.set(bizagents.MAX_DEPTH)
    try:
        r2 = asyncio.run(tools.call("company_handoff", {"agent": "Autor nabídek", "task": "znovu"}, rt))
    finally:
        bizagents._DEPTH.reset(token)
    assert not r2.ok
    assert not asyncio.run(tools.call("company_handoff", {"agent": "Neexistující", "task": "x"}, rt)).ok
    assert a


def test_an_approval_continues_the_chain(rt):
    bizcompany.build_chain(rt, "money")
    inv = next(a for a in bizagents.agents(rt) if a["bkey"] == "invoicing")
    pid = bizagents.propose(rt, inv, ToolCall(id="1", name="todoist_add", arguments={"task": "x"}))

    async def fake_call(name, args, ctx):
        from jarvis.tools.base import ToolResult
        return ToolResult(True, "Faktura 2026-0042 vystavena.")
    orig = tools.call
    tools.call = fake_call
    try:
        r = asyncio.run(bizagents.decide(rt, pid, True))
    finally:
        tools.call = orig
    dun = next(a for a in bizagents.agents(rt) if a["bkey"] == "dunning")
    assert r["ok"] and bizagents.JOBS and bizagents.JOBS[0]["aid"] == dun["id"] and "2026-0042" in bizagents.JOBS[0]["extra"]


def test_department_limit_and_fast_model(rt):
    bizcompany.set_dept_budget(rt, "finance", 1)
    aid = bizcompany.hire(rt, "cash_morning")
    assert bizagents.get(rt, aid)["tier"] == "fast"
    assert bizcompany.can_run(rt, "finance")
    rt.router = Router(["Zůstatek 120 000 Kč."])
    asyncio.run(bizagents.run(rt, aid))
    assert rt.router.seen[0][1].get("fast") is True                             # the cheap model for a simple check
    assert not bizcompany.can_run(rt, "finance") and bizcompany.can_run(rt, "obchod")
    n = bizcompany.numbers(rt)
    assert n["ai_week"] == 1 and n["saved_week_min"] > 0 and n["dept_budget"] == {"finance": 1}


def test_phone_gets_the_proposal_with_buttons(rt, monkeypatch):
    bizcompany._set(rt, "biz_phone", "always")
    a = bizagents.get(rt, bizcompany.hire(rt, "lead_reply"))
    pid = bizagents.propose(rt, a, mail())
    kind, data = rt.pushed[-1]
    assert kind == "confirm" and data["cid"] == f"biz:{pid}" and data["yes"] == "Schválit" and "recepce" not in data["text"]
    bizcompany._set(rt, "biz_phone", "off")
    bizagents.propose(rt, a, mail(to="x@y.cz"))
    assert len(rt.pushed) == 1


def test_the_log_exports_and_the_weekly_report_is_a_pdf(rt, tmp_path):
    rt.router = Router(["Tržby 182 400 Kč, 61 objednávek."])
    aid = bizcompany.hire(rt, "kpi_watch")
    asyncio.run(bizagents.run(rt, aid))
    path = bizcompany.export_actions(rt)
    assert path.endswith(".csv") and "čas;agent;co" in open(path, encoding="utf-8-sig").read()
    bizcompany.log_action(rt, {"id": aid, "name": "X"}, "tool", "t", '=HYPERLINK("http://evil")', True)
    text = open(bizcompany.export_actions(rt), encoding="utf-8-sig").read()
    assert "'=HYPERLINK" in text and ';=HYPERLINK' not in text        # a formula from a mail stays text in Excel
    pdf = bizreport.make_pdf(rt, tmp_path)
    data = open(pdf, "rb").read()
    assert data.startswith(b"%PDF") and len(data) > 20_000
    rep = bizreport.build(rt)
    assert rep["numbers"]["runs_week"] == 1 and rep["results"][0][0] == "Strážce čísel (KPI)"


def test_light_live_update_has_no_library(rt):
    bizcompany.hire(rt, "seo")
    full, light = bizagents.state(rt), bizagents.state(rt, full=False)
    assert "library" in full["company"] and "library" not in light["company"] and "templates" not in light
    assert len(json.dumps(light)) < len(json.dumps(full)) / 2
