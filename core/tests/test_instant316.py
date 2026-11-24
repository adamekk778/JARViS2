"""3.16 Odpověď hned: commands with a slot without the AI, no second AI round, a word while tools work, ready phrases,
answers fetched ahead."""
from __future__ import annotations

import asyncio

from conftest import FakeRouter

from jarvis import instant, latency, prefetch, quickcmd, tools
from jarvis.tools.base import ToolResult


def test_slots_keep_what_you_said():
    p = instant.plan("Jarvisi, přidej mléko, chleba a máslo na nákup, prosím")
    assert p.calls == [("list_add", {"items": ["mléko", "chleba", "máslo"], "list": "nákup"})] and p.fallback
    assert instant.plan("pusť Hans Zimmer Time na YouTube").calls == [("youtube_play", {"query": "Hans Zimmer Time"})]
    assert instant.plan("počasí ve Vídni").calls == [("weather", {"city": "Vídeň"})]
    assert instant.plan("zapni světlo v obýváku").calls == [("home_control", {"target": "světlo v obýváku", "action": "on"})]
    assert instant.plan("kolik je 20 dolarů").calls[0][1] == {"amount": 20.0, "from_currency": "USD", "to_currency": "CZK"}
    assert quickcmd.fold_keep("Přidej Mléko") == "pridej mleko" and len(quickcmd.fold_keep("ěščřžýáíé")) == 9


def test_things_that_are_not_commands_go_to_the_ai():
    for t in ("zapni Spotify", "vypni počítač", "přidej mi do kalendáře schůzku s Petrem na zítra v deset a pošli mu pozvánku",
              "co si myslíš o tom modelu", "zruš tisk"):
        p = instant.plan(t)
        assert p is None or p.calls[0][0] not in ("home_control", "list_add", "printer_control", "model_explode"), t


async def test_the_tools_own_words_are_the_answer(rt):
    tools.load_builtin()
    rt.router = FakeRouter([[("volume", {"action": "set", "level": 40})], "Hlasitost je teď 40 %."])
    out = await rt.agent.handle("dej zvuk tak na čtyřicet, ať to není tak hlasité")
    assert len(rt.router.calls) == 1 and out.strip()                         # one AI call, the tool said the rest
    assert latency.get(rt).turns[-1]["info"].get("skipped_round") == 1
    rt.router = FakeRouter([[("volume", {"action": "set", "level": 40})], "Je to tak akorát."])
    await rt.agent.handle("dej zvuk na 40 a řekni, jestli to není moc?")      # a question: the AI answers after the tool
    assert len(rt.router.calls) == 2


async def test_info_tools_still_get_the_ai_answer(rt):
    tools.load_builtin()
    rt.router = FakeRouter([[("system_info", {})], "Všechny systémy v normě, pane."])
    out = await rt.agent.handle("zkontroluj stav počítače")
    assert "v normě" in out and len(rt.router.calls) == 2


async def test_a_word_while_slow_tools_work(rt):
    said = []

    class Speech:
        spoke = False

        def preface(self, line):
            said.append(line)
            self.spoke = True
    rt.agent.ACK_AFTER_S = 0.01
    t = rt.agent._ack_later(Speech())
    await asyncio.sleep(0.05)
    assert said == ["Moment, pane."] and t.done()
    s2 = Speech()
    s2.spoke = True                                                          # already said something: no extra word
    await rt.agent._ack_later(s2)
    assert said == ["Moment, pane."]


async def test_short_phrases_are_ready(rt):
    from jarvis.voice.tts import Speaker

    sp = Speaker(rt)
    made = []

    async def fake(text, lang="cs", override=None):
        made.append(text)
        return (b"RIFF" + text.encode(), "audio/wav")
    sp._synth = fake
    a = await sp.synth("Hotovo.")
    b = await sp.synth("Hotovo.")
    assert a == b and made == ["Hotovo."]                                    # made once, then at once
    await sp.synth("Tohle je dlouhá věta, která se do zásoby nedává, protože je moc dlouhá na krátkou frázi.")
    await sp.synth("Tohle je dlouhá věta, která se do zásoby nedává, protože je moc dlouhá na krátkou frázi.")
    assert len(made) == 3
    await sp.synth("Hotovo.", override={"effect": "none"})                   # a studio preview is never cached
    assert len(made) == 4
    rt.update_config({"voice": {"tts_engine": "edge"}})
    assert await sp.prepare_phrases() == len(Speaker.COMMON)
    rt.update_config({"voice": {"tts_engine": "elevenlabs"}})
    assert await sp.prepare_phrases() == 0                                   # no credits spent ahead


async def test_answers_fetched_ahead(rt, monkeypatch):
    tools.load_builtin()
    pf = prefetch.get(rt)
    pf.put("weather", {}, ToolResult(True, "Doma je 20 °C a slunečno."))
    pf.put("open_app", {"name": "x"}, ToolResult(True, "x"))                    # only read-only things are kept
    assert pf.get("open_app", {"name": "x"}) is None
    rt.router = FakeRouter([])
    out = await rt.agent.handle("jaké je počasí")
    assert "20 °C" in out and pf.hits == 1 and rt.router.calls == []
    pf.cache["weather{}"] = (0.0, pf.cache["weather{}"][1])                  # old → the tool runs again
    assert pf.get("weather", {}) is None


async def test_prefetch_refresh_only_when_at_the_pc(rt, monkeypatch):
    pf = prefetch.Prefetch(rt)
    calls = []

    async def fake_call(name, args, ctx):
        calls.append(name)
        return ToolResult(True, f"{name} ok")
    monkeypatch.setattr(tools, "call", fake_call)
    tools.load_builtin()
    assert await pf.refresh() >= 2 and "weather" in calls and pf.get("weather", {}).summary == "weather ok"
    rt.platform.idle_seconds = lambda: 3600
    assert not pf.should_run()
    rt.platform.idle_seconds = lambda: 5
    rt.update_config({"brain": {"offline_only": True}})
    assert not pf.should_run()


def test_slow_brain_from_the_routers_own_times(rt):
    from jarvis import brainplus

    class R:
        ttft = {"p": [2400, 2600, 2500]}

        def providers(self):
            class P:
                id = "p"
            return [P()]
    rt.router = R()
    assert brainplus.slow_brain(rt)
    rt.router.ttft = {"p": [300, 400, 350]}
    assert not brainplus.slow_brain(rt)
