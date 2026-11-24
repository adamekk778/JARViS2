"""3.14 Mozek+ (návrhy 23–26, 29, 30, 32, 35)."""
import asyncio
import json

from conftest import FakeRouter, drain
from jarvis import brainplus


def test_correction_detection():
    for t in ("ne, myslel jsem Spotify", "Ne ne, to jsem nechtěl", "myslela jsem zítra, ne dnes", "příště to pusť na Spotify",
              "vždycky použij Seznam", "ne Brno ale Praha"):
        assert brainplus.is_correction(t), t
    for t in ("pusť hudbu", "jaké je počasí", "nevím, co mám dělat dneska večer s kamarády v Brně"):
        assert not brainplus.is_correction(t), t


async def test_rule_learnt_from_correction(rt):
    rt.router = FakeRouter(["Pouštím na YouTube.", "Dobře, pouštím na Spotify.",
                            '{"rule": "Hudbu pouštěj na Spotify, ne na YouTube."}', "ok"])
    await rt.agent.handle("pusť mi nějakou hudbu na relax")     # not an instant command: the AI answers
    q = rt.bus.subscribe()
    await rt.agent.handle("ne, myslel jsem na Spotify")
    for _ in range(50):
        await asyncio.sleep(0.01)
        if brainplus.rules(rt):
            break
    assert brainplus.rules(rt)[0]["text"].startswith("Hudbu pouštěj na Spotify")
    assert any(e["type"] == "rules" for e in drain(q))
    await rt.agent.handle("pusť něco")                     # the rule goes with the next message
    assert "Hudbu pouštěj na Spotify" in rt.router.calls[-1]["messages"][0]["content"]


def test_rules_dedupe_and_cap(rt):
    assert brainplus.add_rule(rt, "Mluv stručně.")
    assert brainplus.add_rule(rt, "mluv  stručně.") is None
    for i in range(brainplus.MAX_RULES + 5):
        brainplus.add_rule(rt, f"Pravidlo číslo {i} pro test.")
    assert len(brainplus.rules(rt, False)) == brainplus.MAX_RULES


async def test_rating(rt):
    rt.router = FakeRouter(["Odpověď."])
    await rt.agent.handle("ahoj")
    mid = rt.memory.recent(1)[0]["id"]
    assert brainplus.rate(rt, mid, True)
    st = brainplus.rating_stats(rt)
    assert st["total"] == 1 and st["good"] == 1 and st["rows"][0]["tier"] == "fast"
    assert rt.memory.recent(1)[0]["meta"]["rated"] is True
    assert not brainplus.rate(rt, "nope", False)


def test_traits_and_risky(rt):
    rt.cfg.general.traits = {"humor": 0, "formal": 2, "brevity": 0}
    p = brainplus.traits_prompt(rt.cfg)
    assert "Žádný humor" in p and "formálně" in p and "nejkratčeji" in p
    assert brainplus.risky("mám investovat do akcií Tesly?")
    assert brainplus.risky("jaké léky na bolest hlavy")
    assert not brainplus.risky("pusť hudbu")


def test_sensitive():
    assert brainplus.sensitive("moje heslo do banky je kocka123")
    assert brainplus.sensitive("číslo karty 4111 1111 1111 1111")
    assert brainplus.sensitive("rodné číslo 900101/1234")
    assert not brainplus.sensitive("jaké bude počasí")


async def test_private_goes_local(rt):
    rt.cfg.brain.chain = ["omniroute", "ollama"]

    async def ready():
        return True
    rt.router = FakeRouter(["Rozumím."])
    rt.router.local_ready = ready
    await rt.agent.handle("zapamatuj si moje heslo k wifi je abc")
    assert rt.router.calls[-1]["only"] == "ollama"
    assert rt.memory.recent(1)[0]["meta"]["private"] is True


def test_preface_clean():
    assert brainplus.clean_preface("„Projdu nabídky a porovnám je.“ A pak…") == "Projdu nabídky a porovnám je."
    assert brainplus.clean_preface("Chceš, abych to udělal?") == ""
    assert brainplus.clean_preface("x " * 40) == ""


async def test_answer_check(rt):
    rt.router = FakeRouter([[("web_read", {"url": "https://example.com"})],
                            "Podle zprávy vyhrála Sparta 3:1 a gól dal Novák v 89. minutě.",
                            '{"issues": ["gól v 89. minutě – zdroj uvádí 78."]}'])

    async def fake_read(ctx, url: str = "", **kw):
        from jarvis.tools import ToolResult
        return ToolResult(True, "Sparta vyhrála 3:1, Novák skóroval v 78. minutě.")
    from jarvis import tools

    tools.load_builtin()
    spec = tools.REGISTRY["web_read"]
    old = spec.func
    spec.func = fake_read
    try:
        q = rt.bus.subscribe()
        await rt.agent.handle("jak dopadla Sparta?")
        for _ in range(100):
            await asyncio.sleep(0.01)
            ev = [e for e in drain(q) if e["type"] == "answer_check"]
            if ev:
                break
        assert ev and "78" in ev[0]["issues"][0]
        assert rt.memory.recent(1)[0]["meta"]["check"]
    finally:
        spec.func = old


def test_mission_cost_budget(rt):
    rt.cfg.limits.mission_max_cost = 5
    rt.cfg.limits.prices = {"groq": 1000.0}
    rt.tasks.begin("mise", rt.memory.current_conversation)
    assert rt.tasks.over_budget(rt.cfg.limits) == ""
    rt.usage.record("groq", "m", [{"role": "user", "content": "x" * 40000}], 4000)
    assert "Kč" in rt.tasks.over_budget(rt.cfg.limits)


async def test_ws_rules_and_rating(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    brainplus.add_rule(rt, "Odpovídej stručně.")
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "rules_get"})
        for _ in range(40):
            m = ws.receive_json()
            if m["type"] == "rules":
                assert m["items"][0]["text"] == "Odpovídej stručně."
                rid = m["items"][0]["id"]
                break
        ws.send_json({"type": "rule_delete", "id": rid})
        for _ in range(40):
            m = ws.receive_json()
            if m["type"] == "rules":
                assert m["items"] == []
                break
    assert json.dumps(brainplus.rating_stats(rt))
