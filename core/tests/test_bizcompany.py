"""3.12 Velín firmy: 100 ready agents in 11 departments, the company brain every agent reads, the run history,
the daily budget – and still: whatever sends or changes only lands in "Ke schválení"."""
import asyncio
import datetime as dt
import json
import re

import pytest

from jarvis import bizagents, bizcompany, connectors, secrets, tools
from jarvis.llm.base import Chunk

tools.load_builtin()


class Router:
    def __init__(self, text="hotovo", fail=False):
        self.text, self.fail, self.seen = text, fail, []

    async def stream(self, msgs, tools_=None, **kw):
        self.seen.append(msgs)
        if self.fail:
            raise RuntimeError("žádný poskytovatel není nastaven")
        yield Chunk(text=self.text, done=True)


@pytest.fixture
def rt(tmp_path, monkeypatch):
    from jarvis.runtime import Runtime

    store: dict[str, str] = {}
    monkeypatch.setattr(secrets, "get", lambda k: store.get(k, ""))
    monkeypatch.setattr(secrets, "set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    r = Runtime(persist_config=False)
    monkeypatch.setattr(r, "notify", lambda *a, **k: None)
    return r


def test_the_library_is_a_whole_company():
    bps = bizcompany.BLUEPRINTS
    assert len(bps) == 100 and len(bizcompany.DEPTS) == 11
    for d in bizcompany.DEPTS:
        assert sum(1 for b in bps.values() if b["dept"] == d) >= 7, d
    for b in bps.values():
        assert all(t in tools.REGISTRY for t in b["tools"]), b["key"]
        assert b["daily_at"] == "" or re.fullmatch(r"([0-6] )?([01]\d|2[0-3]):[0-5]\d", b["daily_at"]), b["key"]
        assert b["every_min"] == 0 or b["every_min"] >= 15, b["key"]
        assert b["skill"] and len(b["skill"]) <= 70 and b["replaces"], b["key"]
        assert not b["skill"].startswith("Na nové poptávky") or "bez" in b["skill"]


def test_build_hires_what_can_work_and_says_what_waits(rt, monkeypatch):
    r = bizcompany.build(rt, only_ready=True)
    lib = bizcompany.library(rt)
    no_service = [x for x in lib if not x["needs"]]
    assert len(r["hired"]) == len(no_service) > 0                  # web + brain agents work without any service
    assert r["waiting"].get("google") and r["waiting"].get("stripe")
    assert bizcompany.build(rt, only_ready=True)["hired"] == []      # nobody twice
    bizcompany.build(rt, ["finance"], only_ready=False)
    assert sum(1 for a in bizagents.agents(rt) if a["dept"] == "finance") == sum(1 for b in bizcompany.BLUEPRINTS.values() if b["dept"] == "finance")
    assert all(a["dept"] for a in bizagents.agents(rt))


def test_a_hired_agent_gets_the_tools_of_connected_services(rt):
    connectors.save("fio", {"token": "x"})
    aid = bizcompany.hire(rt, "cash_morning")                       # Fio + Stripe, only Fio is connected
    assert bizagents.get(rt, aid)["tools"] == ["fio_account"]
    aid2 = bizcompany.hire(rt, "orders_morning")                    # nothing of it connected: all tools, it says what to connect
    assert set(bizagents.get(rt, aid2)["tools"]) == {"shopify_orders", "woocommerce_orders", "shoptet_orders"}
    a = bizagents.get(rt, aid)
    assert a["dept"] == "finance" and a["bkey"] == "cash_morning" and a["skill"] and a["replaces"]


def test_saving_from_the_simple_editor_keeps_the_department(rt):
    aid = bizcompany.hire(rt, "seo")
    a = bizagents.get(rt, aid)
    bizagents.save(rt, {"id": aid, "name": "SEO 2", "tools": a["tools"], "every_min": 0, "daily_at": "2 09:00", "enabled": False})
    b = bizagents.get(rt, aid)
    assert b["dept"] == "marketing" and b["bkey"] == "seo" and b["name"] == "SEO 2" and not b["enabled"]
    with pytest.raises(ValueError):
        bizagents.save(rt, {"id": aid, "name": "x", "tools": a["tools"], "daily_at": "9 09:00"})


def test_weekly_schedule():
    a = {"enabled": True, "work_hours": False, "every_min": 0, "daily_at": "0 08:00", "last_run": None}
    monday = dt.datetime(2026, 11, 16, 8, 5)
    assert bizagents.due(a, monday)
    assert not bizagents.due(a, monday + dt.timedelta(days=1))
    assert not bizagents.due({**a, "last_run": monday.timestamp()}, monday + dt.timedelta(minutes=30))
    assert bizcompany.when(a) == "každé pondělí v 08:00" and bizcompany.when({"every_min": 120}) == "každých 2 h"


def test_every_agent_knows_the_company(rt):
    bizcompany.save_profile(rt, {"name": "Nordic Supply", "what": "outdoorové vybavení", "rules": "Nikdy neslibuj slevu nad 10 %."})
    bizcompany.brain_add(rt, "Ceník B2B: od 50 ks sleva 7 %.")
    bizcompany.brain_add(rt, "Recept na guláš.")
    aid = bizcompany.hire(rt, "lead_reply")
    rt.router = Router("Odpověď připravena.")
    r = asyncio.run(bizagents.run(rt, aid))
    system = rt.router.seen[0][0]["content"]
    assert r["ok"] and "Nordic Supply" in system and "slevu nad 10 %" in system and "Ceník B2B" in system
    runs = bizcompany.runs(rt)
    assert runs[0]["agent"] == "Rychlá odpověď na poptávky" and runs[0]["dept"] == "obchod" and runs[0]["ok"] == 1
    assert bizagents.get(rt, aid)["runs"] == 1
    n = bizcompany.numbers(rt)
    assert n["runs_today"] == 1 and n["notes"] == 2


def test_agents_write_into_the_brain_and_see_each_other(rt):
    rt.router = Router()
    aid = bizcompany.hire(rt, "competitors")
    asyncio.run(bizagents.run(rt, aid))
    r = asyncio.run(tools.call("company_brain_note", {"text": "Konkurent X zdražil o 5 %."}, rt))
    assert r.ok and "Konkurent X" in bizcompany.brain_notes(rt)[0]["text"]
    found = asyncio.run(tools.call("company_brain_search", {"query": "konkurent zdražil"}, rt))
    assert found.ok and found.data["notes"][0]["text"].startswith("Konkurent X")
    ov = asyncio.run(tools.call("company_overview", {}, rt))
    assert ov.ok and ov.data["agents"][0]["agent"] == "Zpravodaj o konkurenci"
    assert not tools.REGISTRY["company_brain_note"].danger              # the company's own notes, nothing leaves the PC


def test_budget_pause_and_a_dead_ai_stop_the_company(rt):
    bizcompany.set_budget(rt, 1)
    assert bizcompany.can_run(rt)
    rt.router = Router(fail=True)
    aid = bizcompany.hire(rt, "trends")
    r = asyncio.run(bizagents.run(rt, aid))
    assert not r["ok"] and r["ai_down"]
    assert not bizcompany.can_run(rt)                                   # 1 of 1 runs used today
    bizcompany.set_budget(rt, 50)
    bizcompany.set_paused(rt, True)
    assert not bizcompany.can_run(rt)
    bizcompany.set_paused(rt, False)
    assert bizcompany.can_run(rt)


def test_bulk_switches_a_department(rt):
    bizcompany.build(rt, ["tech"], only_ready=False)
    n = bizcompany.bulk(rt, [], "tech", False)
    assert n == 10 and not any(a["enabled"] for a in bizagents.agents(rt))
    bizcompany.bulk(rt, [], "*", True)
    assert all(a["enabled"] for a in bizagents.agents(rt))
    bizcompany.bulk(rt, [], "tech", None, delete=True)
    assert bizagents.agents(rt) == []


def test_state_for_the_control_room(rt):
    bizcompany.build(rt, ["pravo"], only_ready=False)
    st = bizagents.state(rt)
    c = st["company"]
    assert len(c["library"]) == 100 and len(c["depts"]) == 11 and "profile_fields" in c
    assert next(d for d in c["depts"] if d["id"] == "pravo")["agents"] == 7
    assert all("when" in a for a in st["agents"]) and "queue" in st
    assert len(json.dumps(st)) < 400_000


def test_writes_of_library_agents_still_wait_for_approval(rt):
    from jarvis.llm.base import ToolCall

    class R:
        def __init__(self):
            self.step = 0

        async def stream(self, msgs, tools_=None, **kw):
            self.step += 1
            if self.step == 1:
                yield Chunk(tool_calls=[ToolCall(id="1", name="stripe_refund", arguments={"payment_id": "pi_1"})], done=True)
            else:
                yield Chunk(text="navrženo", done=True)
    rt.router = R()
    aid = bizcompany.hire(rt, "returns")
    r = asyncio.run(bizagents.run(rt, aid))
    assert r["ok"] and len(r["proposals"]) == 1
    p = bizagents.proposals(rt)[0]
    assert p["tool"] == "stripe_refund" and p["status"] == "pending"
