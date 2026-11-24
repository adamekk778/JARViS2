"""3.16 Nástroje v hlavě a rychlost: the whole tool catalog, use_tool in one step, the cache-friendly order, latency."""
from __future__ import annotations

import json

import httpx
from conftest import FakeRouter, drain

from jarvis import latency, tools
from jarvis import toolcatalog as tc
from jarvis.config import Brain, Config, ProviderCfg
from jarvis.llm.router import Router
from jarvis.prompt import build_system_prompt


def _all():
    tools.load_builtin()
    return {n for n in tools.REGISTRY}


def test_catalog_has_every_tool_once_and_stays_the_same():
    names = _all()
    cat = tc.catalog(tools.REGISTRY, names)
    for n in ("printer_control", "cad_part", "weather", "open_app", "simulate"):
        assert f"\n{n}(" in cat
    assert "\nuse_tool(" not in cat and "\nfind_tools(" not in cat
    assert cat == tc.catalog(tools.REGISTRY, set(names))                       # the same text → the cache holds
    assert len(cat) < 90_000 and cat.count("\n") > len(names) * 0.95
    assert "\nweather(" not in tc.catalog(tools.REGISTRY, names - {"weather"})  # switched off = not offered


def test_static_part_of_the_instructions_is_the_same_for_every_message():
    a = build_system_prompt(Config(), ["má rád kávu"], voice=True, extra="nálada")
    b = build_system_prompt(Config(), [], voice=False, extra="")
    assert tc.DYN in a and a.split(tc.DYN)[0] == b.split(tc.DYN)[0]
    assert "HLASEM" in a.split(tc.DYN)[1] and "HLASEM" not in b


def test_pack_puts_the_catalog_in_the_cached_part_and_the_hint_after_it():
    _all()
    p1 = tc.Pack("KATALOG", [], hint=tc.hint(tools.REGISTRY, ["printer_control"]))
    p2 = tc.Pack("KATALOG", [], hint=tc.hint(tools.REGISTRY, ["cad_part"]))
    sysm = build_system_prompt(Config(), [], False, "")
    m1 = p1.apply([{"role": "system", "content": sysm}, {"role": "user", "content": "a"}])
    m2 = p2.apply([{"role": "system", "content": sysm}, {"role": "user", "content": "b"}])
    s1, d1 = m1[0]["content"].split(tc.DYN)
    s2, d2 = m2[0]["content"].split(tc.DYN)
    assert s1 == s2 and s1.endswith("KATALOG")
    assert "printer_control: action?: string" in d1 and "cad_part" in d2
    assert tc.Pack("K", []).apply([{"role": "user", "content": "x"}])[0]["role"] == "user"   # nothing to do


def test_which_ai_gets_the_catalog():
    assert tc.wants_catalog("anthropic") and tc.wants_catalog("gemini") and tc.wants_catalog("openai")
    assert not tc.wants_catalog("groq") and not tc.wants_catalog("ollama") and not tc.wants_catalog("anthropic", limited=True)
    assert not tc.wants_catalog("anthropic", "off") and tc.wants_catalog("cerebras", "on")
    assert not tc.wants_catalog("ollama", "on")


def test_use_tool_unwrap_checks_and_fixes_arguments():
    names = _all()
    u = tc.unwrap(tools.REGISTRY, names, {"name": "printer_control", "args": {"action": "pause"}})
    assert (u.name, u.args, u.error) == ("printer_control", {"action": "pause"}, "")
    u = tc.unwrap(tools.REGISTRY, names, {"name": "simulate", "args": json.dumps({"kind": "beam", "length_mm": "500"})})
    assert u.args["length_mm"] == 500 and not u.error                                         # "500" → a number
    u = tc.unwrap(tools.REGISTRY, names, {"name": "printer_control", "args": {"akce": "pause"}})
    assert "neznámý parametr „akce“" in u.error and "Přesný popis" in u.error
    u = tc.unwrap(tools.REGISTRY, names, {"name": "printer_contol", "args": {}})
    assert "neexistuje" in u.error and "printer_control" in u.error                            # a typo: the close one
    u = tc.unwrap(tools.REGISTRY, names - {"weather"}, {"name": "weather"})
    assert "vypnutý" in u.error
    assert tc.unwrap(tools.REGISTRY, names, {"name": "use_tool", "args": {}}).error            # no use_tool in use_tool
    assert "args musí být objekt" in tc.unwrap(tools.REGISTRY, names, {"name": "weather", "args": "{nonsense"}).error


def test_use_tool_is_as_risky_as_the_tool_it_calls(rt):
    _all()
    spec = tools.REGISTRY["use_tool"]
    assert tools.is_dangerous(spec, {"name": "printer_control", "args": {"action": "cancel"}}, ctx=rt)
    assert not tools.is_dangerous(spec, {"name": "printer_control", "args": {"action": "status"}}, ctx=rt)
    assert tools.is_dangerous(spec, {"name": "nic_takoveho"}, ctx=rt)


async def test_agent_runs_the_real_tool_behind_use_tool(rt):
    _all()
    rt.router = FakeRouter([[("use_tool", {"name": "get_time", "args": {}})], "Je přesně tolik."])
    q = rt.bus.subscribe()
    out = await rt.agent.handle("kolik je hodin v Tokiu, napiš to jako básničku")
    assert "Je přesně" in out
    ev = drain(q)
    assert any(e["type"] == "tool_start" and e["name"] == "get_time" for e in ev)      # the card shows the real tool
    second = rt.router.calls[1]["messages"]
    assert second[-1]["role"] == "tool" and second[-1]["name"] == "use_tool"            # answered under the called name
    pack = rt.router.calls[0]["catalog"]
    assert pack is not None and "use_tool" in pack.names and "get_time(" in pack.catalog
    t = latency.get(rt).turns[-1]
    assert t["info"]["use_tool"] == 1 and t["info"]["use_tool_errors"] == 0 and "first_token" in t["marks"]


async def test_wrong_use_tool_call_gets_the_exact_description_and_a_second_try(rt):
    _all()
    rt.router = FakeRouter([[("use_tool", {"name": "printer_control", "args": {"akce": "x"}})],
                            [("use_tool", {"name": "printer_control", "args": {"action": "status"}})], "Tiskárna nic nedělá."])
    await rt.agent.handle("co dělá tiskárna")
    results = [m["content"] for m in rt.router.calls[-1]["messages"] if m.get("role") == "tool"]
    assert "Přesný popis" in results[0] and "Tiskárnu nemám nastavenou" in results[1]
    names = {(t.get("function") or t)["name"] for t in rt.router.calls[1]["tools"]}
    assert "printer_control" in names                                                   # offered natively next time
    assert latency.get(rt).turns[-1]["info"]["use_tool_errors"] == 1


async def test_use_tool_still_asks_before_something_risky(rt):
    _all()
    rt.router = FakeRouter([[("use_tool", {"name": "printer_control", "args": {"action": "cancel"}})], "Nechám ho."])
    asked = []

    async def deny(call, second=False, timeout=None, phone=False):
        asked.append(call.name)
        return False
    rt.agent._ask_confirm = deny
    await rt.agent.handle("zruš tisk")
    assert asked == ["printer_control"]


def _sse(*events):
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


async def _sent(preset: str, model: str = "m") -> dict:
    _all()
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        return _sse({"choices": [{"delta": {"content": "ok"}}]})
    b = Brain(providers=[ProviderCfg(id="p", preset=preset, base_url="http://p/v1", model=model)], chain=["p"], first_token_timeout=2)
    r = Router(b, lambda _: "k", httpx.MockTransport(handler))
    pack = tc.Pack("## Všechny tvoje nástroje\nweather(city?) – Počasí", [tools.REGISTRY["get_time"].schema(), tools.REGISTRY["use_tool"].schema()],
                   hint="HINT", names={"get_time", "use_tool"})
    sysm = build_system_prompt(Config(), [], False, "")
    async for _ in r.stream([{"role": "system", "content": sysm}, {"role": "user", "content": "ahoj"}],
                            [tools.REGISTRY["weather"].schema()], catalog=pack):
        pass
    return {"body": bodies[0], "used": r.catalog_used}


async def test_router_sends_the_catalog_only_to_a_big_ai():
    big = await _sent("openai", "gpt-5-mini")
    assert big["used"] and "weather(city?) – Počasí" in big["body"]["messages"][0]["content"]
    assert big["body"]["messages"][0]["content"].index("weather(city?)") < big["body"]["messages"][0]["content"].index(tc.DYN)
    assert [t["function"]["name"] for t in big["body"]["tools"]] == ["get_time", "use_tool"]
    small = await _sent("groq", "llama-3.3-70b-versatile")
    assert not small["used"] and "weather(city?) – Počasí" not in json.dumps(small["body"], ensure_ascii=False)
    assert [t["function"]["name"] for t in small["body"]["tools"]] == ["weather"]


def test_claude_caches_the_unchanging_part():
    from jarvis.llm.claude import convert, convert_tools, mark_cache

    sysm = build_system_prompt(Config(), ["fakt"], True, "")
    system, msgs = convert([{"role": "system", "content": sysm}, {"role": "user", "content": "ahoj"}])
    assert len(system) == 2 and system[1]["text"].startswith("## Aktuální situace")
    tl = convert_tools([tools.REGISTRY["get_time"].schema()])
    mark_cache(tl, system, msgs)
    assert system[0].get("cache_control") and not system[1].get("cache_control")


def test_latency_stats():
    import time

    lat = latency.Latency()
    for stt, tok in ((300, 900), (500, 1100), (400, 1000)):
        t0 = time.monotonic()
        lat.begin("voice", t0=t0)
        lat.mark("stt", t0 + stt / 1000)
        lat.agent_start("voice")
        lat.mark("first_token", t0 + tok / 1000)
        lat.finish(tools=1, find_tools=0, use_tool_errors=0)
    lat.agent_start("chat")
    lat.finish(tools=1, find_tools=1)
    s = lat.stats()
    assert s["voice"]["stt"]["median"] == 400 and s["voice"]["first_token"]["median"] == 1000
    assert s["n"] == 4 and s["first_try"] == 75


async def test_diagnostics_show_latency(rt):
    from jarvis import diagnostics

    rt.router = FakeRouter(["Dobrý den."])
    await rt.agent.handle("ahoj")
    snap = diagnostics.snapshot(rt)
    assert snap["latency"]["n"] >= 1 and "first_token" in snap["latency"]["stages"]


# ------------------------------------------------------------------------------------------ R2: tool memory
async def test_memory_turns_a_repeated_request_into_a_reflex(rt):
    from jarvis import toolmind

    _all()
    rt.router = FakeRouter([[("media_control", {"action": "next"})], "Další skladba.",
                            [("media_control", {"action": "next"})], "Další skladba."])
    await rt.agent.handle("dej tam tu další písničku, Jarvisi")
    assert toolmind.reflex(rt, "dej tam tu další písničku", rt.agent._allowed_names()) is None    # once is not enough
    await rt.agent.handle("dej tam tu další písničku")
    rx = toolmind.reflex(rt, "Dej tam tu další písničku!", rt.agent._allowed_names())
    assert rx == ("media_control", {"action": "next"}, "Další skladba.")
    calls_before = len(rt.router.calls)
    q = rt.bus.subscribe()
    out = await rt.agent.handle("dej tam tu další písničku")
    assert out.strip() == "Další skladba." and len(rt.router.calls) == calls_before            # no AI at all
    assert any(e["type"] == "tool_start" and e["name"] == "media_control" for e in drain(q))
    assert latency.get(rt).turns[-1]["info"]["reflex"] is True
    toolmind.punish(rt, "dej tam tu další písničku")                                           # "ne, to ne"
    assert toolmind.reflex(rt, "dej tam tu další písničku", rt.agent._allowed_names()) is None


def test_no_reflex_for_answers_with_numbers_risky_tools_or_secrets(rt):
    from jarvis import toolmind

    _all()
    allowed = {n for n in tools.REGISTRY}
    for _ in range(3):
        toolmind.learn(rt, "jaké je počasí", [("weather", {}, True)], "Venku je 5 °C a zataženo.")
        toolmind.learn(rt, "zruš tisk", [("printer_control", {"action": "cancel"}, True)], "Zrušeno.")
        toolmind.learn(rt, "moje heslo k bance je 1234", [("remember", {"text": "x"}, True)], "Uloženo.")
    assert toolmind.reflex(rt, "jaké je počasí", allowed) is None           # the moment's numbers
    assert toolmind.reflex(rt, "zruš tisk", allowed) is None               # it would ask first
    assert rt.db.one("SELECT COUNT(*) AS n FROM tool_memory WHERE phrase LIKE '%heslo%'")["n"] == 0
    rt.update_config({"agent": {"reflexes": False}})
    toolmind.learn(rt, "ztlum to", [("volume", {"action": "down"}, True)], "Ztlumeno.")
    toolmind.learn(rt, "ztlum to", [("volume", {"action": "down"}, True)], "Ztlumeno.")
    assert toolmind.reflex(rt, "ztlum to", allowed) is None


def test_examples_from_earlier_requests(rt):
    from jarvis import toolmind

    toolmind.learn(rt, "pusť lo-fi na YouTube", [("youtube_play", {"query": "lo-fi"}, True)], "Pouštím lo-fi.")
    ex = toolmind.examples(rt, "pusť mi lo-fi hudbu na YouTube")
    assert ex and ex[0]["tool"] == "youtube_play" and ex[0]["args"] == {"query": "lo-fi"}
    assert "youtube_play" in toolmind.examples_hint(rt, "pusť lo-fi na YouTube")
    assert toolmind.examples(rt, "kolik stojí bitcoin") == []


def test_screen_and_habits(rt):
    from jarvis import toolmind

    _all()
    rt.platform.front_app = "Visual Studio Code"
    app, areas = toolmind.screen_areas(rt)
    assert app == "Visual Studio Code" and "programování" in areas
    found = toolmind.screen_tools(rt, tools.REGISTRY, "ukaž git log a stav")
    assert found and all(tools.REGISTRY[n].category in areas for n in found)
    rt.platform.front_app = "Poznámkový blok"
    assert toolmind.screen_tools(rt, tools.REGISTRY, "ukaž git log") == []
    import time as _t

    h = _t.localtime().tm_hour
    toolmind._db(rt)
    for _ in range(3):
        rt.db.exec("INSERT INTO tool_uses (tool, hour, ts) VALUES (?,?,?)", ("briefing", h, _t.time()))
    assert toolmind.habits(rt) == ["briefing"]


def test_meaning_search_with_a_fake_model(rt, monkeypatch, tmp_path):
    import numpy as np

    from jarvis import embedder, toolmind

    reg = {n: tools.REGISTRY[n] for n in ("weather", "printer_control", "youtube_play")}
    vecs = {"weather": [1, 0, 0], "printer_control": [0, 1, 0], "youtube_play": [0, 0, 1]}

    def encode(texts, kind="passage", batch=16):
        out = []
        for t in texts:
            if kind == "query":
                out.append([0.05, 0.99, 0.0] if "tisk" in t else [0.0, 0.0, 1.0])
            else:
                out.append(next(v for k, v in vecs.items() if t.startswith(k.replace("_", " "))))
        return out
    monkeypatch.setattr(embedder, "ready", lambda: True)
    monkeypatch.setattr(embedder, "encode", encode)
    sem = toolmind.Semantic()
    assert sem.build(reg, tmp_path)
    assert sem.search("jak jde tisk") == ["printer_control"]
    assert list(tmp_path.glob("toolvec-*.npy"))
    again = toolmind.Semantic()
    monkeypatch.setattr(embedder, "encode", lambda texts, kind="passage", batch=16: (_ for _ in ()).throw(AssertionError) if kind == "passage" else encode(texts, kind))
    assert again.build(reg, tmp_path) and again.search("pusť hudbu") == ["youtube_play"]   # vectors from disk
    assert isinstance(again.mat, np.ndarray)


async def test_suggestions_reach_the_message(rt):
    from jarvis import toolmind

    _all()
    toolmind.learn(rt, "vymodeluj mi držák na polici", [("cad_part", {"action": "create"}, True)], "Hotovo.")
    rt.router = FakeRouter(["Dobře."])
    await rt.agent.handle("vymodeluj mi držák na polici")
    assert "cad_part" in rt.agent._picked
    pack = rt.router.calls[0]["catalog"]
    assert "Takhle se ti to dřív povedlo" in pack.hint and "cad_part" in pack.hint
