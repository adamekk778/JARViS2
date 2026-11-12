"""3.12: subtitles of what the PC plays, in the notch; the notch over games / videos and hidden by a hotkey."""
import asyncio
import time

import numpy as np
from conftest import drain

from jarvis import config, livesubs, tools
from jarvis.permissions import READ_ONLY_OK
from jarvis.server import ws


def tone(sec, amp=0.1):
    t = np.arange(int(livesubs.SR * sec)) / livesubs.SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype("float32")


def blocks(sig):
    n = int(livesubs.SR * livesubs.BLOCK_S)
    return [sig[i:i + n] for i in range(0, len(sig), n)]


def test_clean_drops_whisper_phantoms_and_tags():
    assert livesubs.clean("  Ahoj,   jak se máš? ") == "Ahoj, jak se máš?"
    assert livesubs.clean("[Music] Hello there") == "Hello there"
    for junk in ("Titulky vytvořil JohnyX", "Thanks for watching!", "♪ ♪", "...", "[Hudba]", "Subtitles by the Amara.org community"):
        assert livesubs.clean(junk) == "", junk


def test_lines_for_two_lines_without_cutting_words():
    text = "Tohle je docela dlouhá věta, kterou titulky musí rozdělit na dva řádky a neuříznout přitom žádné slovo uprostřed"
    lines = livesubs.lines_for(text, 40)
    assert 1 <= len(lines) <= 2 and all(len(x) <= 40 for x in lines)
    assert " ".join(lines) in text                         # the end of a too long line wins, words stay whole
    assert livesubs.lines_for("Krátce.") == ["Krátce."]


def test_chunker_phrases_pauses_and_silence():
    c = livesubs.Chunker()
    assert all(c.feed(b) is None for b in blocks(np.zeros(livesubs.SR * 2, dtype="float32")))     # silence: nothing
    out = [p for b in blocks(np.concatenate([tone(1.5), np.zeros(livesubs.SR, dtype="float32")])) if (p := c.feed(b)) is not None]
    assert len(out) == 1 and 1.5 <= len(out[0]) / livesubs.SR <= 2.0      # a phrase ends at a short pause
    c = livesubs.Chunker()
    out = [p for b in blocks(tone(9)) if (p := c.feed(b)) is not None]
    assert len(out) == 2 and all(abs(len(p) / livesubs.SR - c.max_s) < 0.3 for p in out)   # nonstop speech: cut at max_s
    c = livesubs.Chunker()
    out = [p for b in blocks(np.concatenate([tone(0.25), np.zeros(livesubs.SR * 2, dtype="float32")])) if (p := c.feed(b)) is not None]
    assert out == []                                     # a click is not speech


class FakeRec:
    def __init__(self, sig):
        self.parts = blocks(sig)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def record(self, numframes):
        time.sleep(0.001)
        return (self.parts.pop(0) if self.parts else np.zeros(numframes, dtype="float32")).reshape(-1, 1)


class FakeSTT:
    class cfg:
        stt_provider = "local"

    def __init__(self, ready=True):
        self.ready, self.calls = ready, 0

    def local_ready(self):
        return self.ready

    def provider(self):
        return "local"

    def caption(self, audio, language=None):
        self.calls += 1
        return "Hello there, welcome back to the channel", "en"


async def test_subtitles_flow_from_pc_sound_to_the_notch(rt, monkeypatch):
    stt = FakeSTT()
    monkeypatch.setattr(rt.dictation, "_stt", lambda: stt)
    rt.cfg.notch.subs_translate = False
    sig = np.concatenate([tone(1.5), np.zeros(livesubs.SR, dtype="float32")])
    monkeypatch.setattr(livesubs.LiveSubs, "_recorder", lambda self: FakeRec(sig))
    q = rt.bus.subscribe()
    subs = livesubs.get(rt)
    assert subs.start()["ok"] and subs.on
    for _ in range(200):
        if subs.text:
            break
        await asyncio.sleep(0.02)
    assert subs.text == "Hello there, welcome back to the channel" and subs.lang == "en"
    rt.stop_all()                                        # the emergency STOP also stops listening
    assert not subs.on
    await asyncio.sleep(0.05)
    ev = [e for e in drain(q) if e["type"] == "live_subs"]
    assert any(e["lines"] == ["Hello there, welcome back to the channel"] for e in ev) and ev[-1]["on"] is False


async def test_translation_to_czech(rt, monkeypatch):
    stt = FakeSTT()
    monkeypatch.setattr(rt.dictation, "_stt", lambda: stt)
    rt.cfg.notch.subs_translate = True
    seen = []

    async def complete(messages, **kw):
        seen.append(messages)
        return "Ahoj, vítejte zpátky na kanálu"

    monkeypatch.setattr(rt.router, "complete", complete)
    monkeypatch.setattr(rt, "loop", asyncio.get_running_loop())
    subs = livesubs.get(rt)
    subs.on, subs.text = True, "Hello there, welcome back to the channel"
    subs._translate(subs.text, "en")
    for _ in range(100):
        if subs.lang == "en→cs":
            break
        await asyncio.sleep(0.02)
    assert subs.text == "Ahoj, vítejte zpátky na kanálu" and "pokyn" in seen[0][0]["content"]
    subs.on = False


async def test_no_silent_model_download(rt, monkeypatch):
    monkeypatch.setattr(rt.dictation, "_stt", lambda: FakeSTT(ready=False))
    r = livesubs.get(rt).start()
    assert not r["ok"] and "Nastavení → Hlas" in r["message"] and not rt.live_subs.on


def test_wiring():
    c = config.Config()
    assert c.hotkeys.notch_toggle == "ctrl+alt+n" and c.hotkeys.subtitles == "ctrl+alt+t" and c.notch.subs_translate
    assert "live_subs" in ws.SERVER_TYPES and {"live_subs_get", "live_subs_set"} <= set(ws.CLIENT_TYPES)
    assert {"live_subs_get", "live_subs_set"} <= ws.LOCAL_ONLY            # a phone cannot start listening to the PC
    assert "video_subtitles" in tools.REGISTRY and "video_subtitles" in READ_ONLY_OK


async def test_subtitle_text_never_reaches_a_phone(rt):
    class Sock:
        def __init__(self):
            self.sent = []

        async def send_json(self, m):
            self.sent.append(m)

    conn = ws.Connection.__new__(ws.Connection)
    conn.ws, conn.client, conn.local, conn.guest, conn.low_power = Sock(), "mobile", False, False, False
    conn.send = lambda type, **kw: conn.ws.send_json({"type": type, **kw})
    q = asyncio.Queue()
    for m in ({"type": "live_subs", "text": "tajné"}, {"type": "media", "title": "x"}):
        q.put_nowait(m)
    task = asyncio.create_task(conn._pump(q))
    await asyncio.sleep(0.05)
    task.cancel()
    assert [m["type"] for m in conn.ws.sent] == ["media"]
