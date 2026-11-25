"""3.16 Rychlý poslech: early transcription at pauses, the smart end of a sentence, your words, kept connections."""
from __future__ import annotations

import time

import httpx

from jarvis.config import Brain, ProviderCfg
from jarvis.llm import pool
from jarvis.llm.router import Router
from jarvis.voice import fastear
from jarvis.voice.text import Endpointer

FRAME_S = 0.08


def test_finished_or_open_sentence():
    assert fastear.looks_complete("pusť hudbu") is True                  # an everyday command
    assert fastear.looks_complete("kolik je hodin?") is True
    assert fastear.looks_complete("napiš mámě, že") is False
    assert fastear.looks_complete("zapni světlo a") is False
    assert fastear.looks_complete("otevři ten soubor v") is False
    assert fastear.looks_complete("najdi mi prosím levné letenky do Říma") is True
    assert fastear.looks_complete("hm") is None and fastear.looks_complete("") is None


def _run(script: list[bool], texts: dict[int, str], base: float = 0.6, delay: float = 0.0):
    """Feed speech (True) / silence (False) frames; the fake recognizer answers by how much audio it got."""
    ep = Endpointer(FRAME_S, base)
    calls = []

    def stt(b: bytes) -> str:
        calls.append(len(b))
        time.sleep(delay)
        return texts.get(len(b), "")
    sp = fastear.Speculator(stt, 2, base)
    audio = bytearray()
    for i, speech in enumerate(script):
        audio += b"x" * 10
        r = ep.feed(speech)
        if r is None:
            r = sp.step(ep, audio, speech)
            if sp.fut is not None and delay == 0:
                sp.fut.result()                       # deterministic: the fake recognizer is instant
                r = r or sp.step(ep, audio, speech)
        if r:
            out = (i + 1, r, sp.result_for(len(audio)), calls, ep.silence_s)
            sp.close()
            return out
    sp.close()
    return (len(script), None, None, calls, ep.silence_s)


def test_a_finished_sentence_ends_after_a_quarter_second():
    script = [True] * 10 + [False] * 20
    frames, why, text, calls, _ = _run(script, {100: "pusť hudbu"})
    assert why == "done" and text == "pusť hudbu"
    assert frames <= 10 + 4                                              # ~0.25–0.3 s of silence, not 0.6 s
    assert calls == [100]                                                # written down once, used as the final text


def test_an_open_sentence_waits_longer_and_a_new_word_drops_the_old_guess():
    script = [True] * 10 + [False] * 5 + [True] * 5 + [False] * 30
    frames, why, text, calls, silence = _run(script, {100: "napiš mámě, že", 200: "napiš mámě, že přijdu později"})
    assert why == "done" and text == "napiš mámě, že přijdu později"
    assert calls[0] == 100 and 200 in calls                              # the first guess was old after the new words
    unfinished = _run([True] * 10 + [False] * 30, {100: "zapni světlo a"})
    assert unfinished[1] == "done" and unfinished[0] >= 10 + int(fastear.LONGER_S / FRAME_S) - 1   # waited ~1.2 s
    assert unfinished[4] == fastear.LONGER_S


def test_unknown_end_keeps_the_normal_pause_and_reuses_the_text():
    frames, why, text, calls, silence = _run([True] * 10 + [False] * 20, {100: "hm"})
    assert why == "done" and frames == 10 + int(round(0.6 / FRAME_S)) and text == "hm" and calls == [100]


def test_vocabulary_has_your_words(rt):
    fastear._VOCAB.update(at=0.0, text="")
    rt.update_config({"general": {"user_name": "Adam"}, "dictation": {"words": ["OctoPrint", "Mochi"]}})
    from jarvis import workbench

    workbench.create(rt, "Meteostanice")
    v = fastear.vocabulary(rt)
    for w in ("JARVIS", "Adam", "OctoPrint", "Mochi", "Meteostanice"):
        assert w in v
    assert len(v) <= 600
    assert fastear.vocabulary(rt) is fastear._VOCAB["text"]              # kept for 10 minutes


async def test_connections_are_kept_and_prewarmed():
    a = pool.shared()
    assert pool.shared() is a                                           # one client for the loop
    seen = []

    def handler(req):
        seen.append(req.method)
        return httpx.Response(200)
    async with pool.client(httpx.MockTransport(handler)) as c:          # tests keep their own transport
        assert c is not a
        await c.get("http://x/")
    assert seen == ["GET"]
    b = Brain(providers=[ProviderCfg(id="g", preset="custom", base_url="http://127.0.0.1:9/v1", model="m")], chain=["g"])
    r = Router(b, lambda _: "")
    assert await r.prewarm() == []                                      # nothing listens there: no error, nothing warmed
    await pool.close_all()


def test_speculator_live_text_only_when_allowed():
    got = []
    ep = Endpointer(FRAME_S, 0.6)
    sp = fastear.Speculator(lambda b: "ahoj světe", 2, 0.6, live=got.append, live_ok=lambda: True)
    audio = bytearray(b"x" * 100)
    sp.step(ep, audio, True)
    sp.live_fut.result()
    assert got == ["ahoj světe"]
    sp2 = fastear.Speculator(lambda b: "x", 2, 0.6, live=got.append, live_ok=lambda: False)
    sp2.step(ep, audio, True)
    assert sp2.live_fut is None
    sp.close()
    sp2.close()
