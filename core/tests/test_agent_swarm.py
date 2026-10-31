"""P1.08 / 069 / 070: a team of specialists at once – independent parts in parallel, dependent ones after them."""
import json

from conftest import FakeRouter, drain
from jarvis import agents, tools

tools.load_builtin()


def test_new_specialists():
    assert agents.find("3D a scény") == "3d" and agents.find("elektronika") == "hardware" and agents.find("programátor") == "kod"
    for k in ("3d", "hardware", "kod"):
        assert agents.AGENTS[k]["tools"] and "agent_swarm" not in agents.AGENTS[k]["tools"]
    assert "agent_swarm" in agents.NEVER_FOR_SPECIALISTS


async def test_swarm_runs_independent_parts_together(rt):
    q = rt.bus.subscribe()
    rt.router = FakeRouter([
        json.dumps([{"agent": "hardware", "task": "navrhni zapojení teploměru", "after": []},
                    {"agent": "3d", "task": "navrhni krabičku", "after": []},
                    {"agent": "kod", "task": "napiš firmware", "after": [0]}]),
        "Zapojení: DS18B20 na pin 4.", "Krabička 60×40×25 mm.", "Firmware čte pin 4.",
        "Hotovo: zapojení, krabička a firmware.",
    ])
    r = await agents.swarm(rt, "udělej domácí teploměr")
    assert r["waves"] == [["hardware", "3d"], ["kod"]] and r["ok"]
    assert "DS18B20" in rt.router.calls[3]["messages"][1]["content"]         # the coder got the electronics result
    assert r["summary"].startswith("Hotovo")
    starts = [e["name"] for e in drain(q) if e["type"] == "agent_activity" and e["state"] == "start"]
    assert starts[:2] == ["Elektronika", "3D a scény"]


async def test_swarm_tool(rt):
    rt.router = FakeRouter([json.dumps([{"agent": "vyzkum", "task": "zjisti cenu", "after": []}]), "Stojí 100 Kč.", "Cena je 100 Kč."])
    r = await tools.call("agent_swarm", {"goal": "zjisti cenu"}, rt)
    assert r.ok and "Výzkum" in r.summary and "100 Kč" in r.summary
    rt.router = FakeRouter(["nevím"])
    assert not (await tools.call("agent_swarm", {"goal": "x"}, rt)).ok
