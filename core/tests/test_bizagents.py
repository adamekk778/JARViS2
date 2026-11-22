"""3.12 Firemní agenti: an agent reads and prepares; whatever sends or changes only lands in "Ke schválení"."""
import asyncio
import datetime as dt

import pytest

from jarvis import bizagents, tools
from jarvis.llm.base import Chunk, ToolCall
from jarvis.tools.base import ToolResult

tools.load_builtin()


class FakeRouter:
    """Answers with the scripted rounds: a list of tool calls, then the final text."""

    def __init__(self, rounds):
        self.rounds = list(rounds)

    async def stream(self, msgs, tools_=None, **kw):
        step = self.rounds.pop(0)
        if isinstance(step, str):
            yield Chunk(text=step, done=True)
        else:
            yield Chunk(tool_calls=step, done=True)

    async def complete(self, msgs, **kw):
        return self.rounds.pop(0)


@pytest.fixture
def rt(tmp_path, monkeypatch):
    from jarvis.runtime import Runtime

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    r = Runtime(persist_config=False)
    r.notified = []
    monkeypatch.setattr(r, "notify", lambda *a, **k: r.notified.append(a))
    return r


def test_templates_make_agents_and_tools_are_checked(rt):
    aid = bizagents.from_template(rt, "email")
    a = bizagents.get(rt, aid)
    assert a["name"] == "E-mailový asistent" and "google_gmail_send" in a["tools"] and a["every_min"] == 60
    with pytest.raises(ValueError):
        bizagents.save(rt, {"name": "X", "tools": ["run_shell"]})          # only connector tools and web reading
    with pytest.raises(ValueError):
        bizagents.save(rt, {"name": "X", "tools": ["google_gmail_search"], "daily_at": "25:99"})
    assert bizagents.get(rt, bizagents.save(rt, {"name": "X", "tools": ["google_gmail_search"], "every_min": 5}))["every_min"] == 15


def test_the_agent_never_sends_it_proposes(rt, monkeypatch):
    called = []

    async def fake_call(name, args, ctx):
        called.append(name)
        return ToolResult(True, "2 e-maily", data=[{"id": "m1", "subject": "Poptávka"}])

    monkeypatch.setattr(tools, "call", fake_call)
    aid = bizagents.from_template(rt, "email")
    rt.router = FakeRouter([
        [ToolCall(id="1", name="google_gmail_search", arguments={"query": "is:unread"})],
        [ToolCall(id="2", name="google_gmail_send", arguments={"to": "jan@firma.cz", "subject": "Re: Poptávka", "body": "Dobrý den…"})],
        "Přišla 1 poptávka, odpověď čeká na schválení.",
    ])
    res = asyncio.run(bizagents.run(rt, aid))
    assert res["ok"] and called == ["google_gmail_search"]                 # the send was NOT run
    props = bizagents.proposals(rt)
    assert len(props) == 1 and props[0]["tool"] == "google_gmail_send" and props[0]["args"]["to"] == "jan@firma.cz"
    assert any("Komu: jan@firma.cz" in line for line in props[0]["details"])
    assert rt.notified and "ke schválení" in rt.notified[0][0]
    a = bizagents.get(rt, aid)
    assert a["last_ok"] and "poptávka" in a["last_result"]


def test_approve_runs_exactly_the_proposal_reject_drops_it(rt, monkeypatch):
    called = []

    async def fake_call(name, args, ctx):
        called.append((name, args))
        return ToolResult(True, "Odesláno")

    monkeypatch.setattr(tools, "call", fake_call)
    a = {"id": 1, "name": "Pošta"}
    p1 = bizagents.propose(rt, a, ToolCall(id="x", name="google_gmail_send", arguments={"to": "a@b.cz", "subject": "S", "body": "B"}))
    p2 = bizagents.propose(rt, a, ToolCall(id="y", name="slack_post", arguments={"channel": "C1", "text": "ahoj"}))
    r = asyncio.run(bizagents.decide(rt, p1, True))
    assert r["ok"] and called == [("google_gmail_send", {"to": "a@b.cz", "subject": "S", "body": "B"})]
    asyncio.run(bizagents.decide(rt, p2, False))
    assert len(called) == 1 and not bizagents.proposals(rt)
    with pytest.raises(ValueError):
        asyncio.run(bizagents.decide(rt, p1, True))                        # never twice


def test_an_agent_cannot_use_tools_it_was_not_given(rt, monkeypatch):
    called = []

    async def fake_call(name, args, ctx):
        called.append(name)
        return ToolResult(True, "ok")

    monkeypatch.setattr(tools, "call", fake_call)
    aid = bizagents.save(rt, {"name": "Čtenář", "tools": ["google_gmail_search"], "task": "x"})
    rt.router = FakeRouter([[ToolCall(id="1", name="run_shell", arguments={"command": "del *"})], "hotovo"])
    asyncio.run(bizagents.run(rt, aid))
    assert called == [] and not bizagents.proposals(rt)


def test_when_agents_work():
    base = {"enabled": True, "work_hours": True, "every_min": 60, "daily_at": "", "last_run": None}
    at10 = dt.datetime(2026, 11, 17, 10, 0)
    assert bizagents.due(base, at10)
    assert not bizagents.due({**base, "last_run": (at10 - dt.timedelta(minutes=20)).timestamp()}, at10)
    assert not bizagents.due(base, dt.datetime(2026, 11, 17, 22, 0))           # out of work hours
    daily = {**base, "every_min": 0, "daily_at": "08:30"}
    assert bizagents.due(daily, at10)
    assert not bizagents.due({**daily, "last_run": dt.datetime(2026, 11, 17, 8, 31).timestamp()}, at10)
    assert not bizagents.due({**daily, "enabled": False}, at10)


def test_one_sentence_makes_an_agent(rt):
    rt.router = FakeRouter(['{"name": "Domény", "icon": "globe", "role": "Hlídá domény.", "task": "Zkontroluj domény.", '
                            '"tools": ["spaceship_domains", "run_shell"], "every_min": 0, "daily_at": "09:00", "work_hours": true}'])
    aid = asyncio.run(bizagents.create_from_text(rt, "hlídej mi domény na spaceship"))
    a = bizagents.get(rt, aid)
    assert a["tools"] == ["spaceship_domains"] and a["daily_at"] == "09:00"
