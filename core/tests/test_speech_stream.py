"""3.12 Rychlejší hlas: speech starts with the first sentence, code is not read out, nothing is said twice."""
import asyncio
import threading

from jarvis.llm.base import Chunk
from jarvis.voice.stream import cut, speakable


def test_cut_waits_for_a_sentence_end_and_skips_code_blocks():
    assert cut("Ahoj, jak", True) == ("", "Ahoj, jak")
    piece, rest = cut("Dobře, pouštím to. A teď další", True)
    assert piece == "Dobře, pouštím to." and rest.strip().startswith("A teď")
    assert cut("Tady:\n```python\nx = 1. y = 2.\n", True)[0] in ("", "Tady:")      # never inside the code
    assert speakable("Kód:\n```py\nprint(1)\n```\nHotovo.") == "Kód:\n \nHotovo."


class FakeSpeaker:
    def __init__(self):
        self._stop = threading.Event()
        self._lock = asyncio.Lock()
        self.speaking = False
        self.on_finished = None
        self.said: list[tuple[float, str]] = []

    async def synth(self, text, lang="cs"):
        self.said.append((asyncio.get_running_loop().time(), text))
        return b"x", "audio/wav"

    def _play(self, audio):
        pass

    def stop(self):
        self._stop.set()


async def test_answer_is_spoken_from_the_first_sentence_on(rt):
    rt.speaker = FakeSpeaker()
    rt.cfg.voice.speak_mode = "always"
    done_at = {}

    async def slow_answer(msgs, tools_, **kw):
        for part in ["Jasně, hned to najdu. ", "Tady je recept na svíčkovou: maso, zelenina a smetana. ",
                     "Kód pro tebe:\n```py\nprint('nečti mě')\n```\n", "Dobrou chuť!"]:
            yield Chunk(text=part)
            await asyncio.sleep(0.05)
        done_at["t"] = asyncio.get_running_loop().time()
        yield Chunk(done=True)

    rt.router.stream = slow_answer
    await rt.agent.handle("recept na svíčkovou", [], "chat")
    await asyncio.sleep(0.1)
    said = rt.speaker.said
    assert said and said[0][0] < done_at["t"]                          # speaking began before the answer was complete
    spoken = " ".join(t for _, t in said)
    assert "nečti mě" not in spoken and "Dobrou chuť" in spoken and spoken.count("Jasně") == 1


async def test_without_speech_mode_nothing_is_streamed(rt):
    rt.speaker = FakeSpeaker()
    rt.cfg.voice.speak_mode = "voice"                                  # only when you spoke to JARVIS

    async def answer(msgs, tools_, **kw):
        yield Chunk(text="Ahoj, tady jsem. Jak ti můžu pomoct?")
        yield Chunk(done=True)

    rt.router.stream = answer
    await rt.agent.handle("ahoj", [], "chat")
    await asyncio.sleep(0.05)
    assert rt.speaker.said == []
