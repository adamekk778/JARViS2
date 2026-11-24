"""3.14 Jarvis-level voice: live conversation, look-to-talk, JARVIS / FRIDAY, humour, guests, interpreter, speed."""
import time

import numpy as np
from conftest import FakeRouter

from jarvis import instant, interpreter, persona, tools, webcam
from jarvis.voice.stream import cut

tools.load_builtin()


def test_first_clause_is_spoken_before_the_sentence_ends():
    piece, rest = cut("Dobře, pane, podíval jsem se na to, a vypadá to, že zítra bude pršet", True)
    assert piece.endswith("na to,") and rest.startswith(" a vypadá")
    assert cut("Krátké, ", True)[0] == ""                      # a short clause waits for more
    assert cut("```\\nkód, který, se, nečte\\n", True)[0] == ""      # never inside code


async def test_persona_switch_changes_personality_and_voice(rt):
    r = await tools.call("persona_switch", {"name": "FRIDAY"}, rt)
    assert r.ok and rt.cfg.general.personality == "friday" and rt.cfg.voice.tts_voice == "cs-CZ-VlastaNeural"
    assert rt.cfg.voice.tts_voice_en == "en-IE-EmilyNeural"
    from jarvis.prompt import build_system_prompt

    assert "F.R.I.D.A.Y." in build_system_prompt(rt.cfg, [])
    r = await tools.call("persona_switch", {"name": "jarvis"}, rt)
    assert rt.cfg.voice.tts_voice_en == "en-GB-RyanNeural" and rt.cfg.voice.effect == "jarvis"
    assert instant.plan("přepni na FRIDAY").calls == [("persona_switch", {"name": "friday"})]
    assert instant.plan("chci zpátky Jarvise").calls == [("persona_switch", {"name": "jarvis"})]


def test_humour_knows_when(rt):
    assert "žádné vtipy" in persona.humour_line(rt, "Včera mi umřel děda", now=time.mktime((2026, 11, 24, 15, 0, 0, 0, 0, -1)))
    assert "žádné vtipy" in persona.humour_line(rt, "co děláš", now=time.mktime((2026, 11, 24, 23, 30, 0, 0, 0, -1)))
    assert "vtip si dovolit" in persona.humour_line(rt, "co děláš", now=time.mktime((2026, 11, 24, 15, 0, 0, 0, 0, -1)))


def test_running_jokes_from_your_laugh(rt):
    assert persona.note_reaction(rt, "hahaha to je dobrý", "Hotovo, pane. Kafe jsem objednal, ale pít ho budete vy.")
    jokes = persona._jokes(rt)
    assert jokes and "pít ho budete vy" in jokes[-1]["text"]
    assert not persona.note_reaction(rt, "ok díky", "Další věta.")


async def test_unknown_voice_is_a_guest_for_that_sentence(rt):
    class Vid:
        class profiles:
            people = {"Adam": {}}
        last_speaker = ""
        last_at = time.time()

        @staticmethod
        def prompt():
            return ""

    rt.voiceid = Vid()
    assert "host" in persona.speaker_line(rt)
    Vid.last_speaker = "Adam"
    assert persona.speaker_line(rt) == ""


async def test_live_conversation_tool_and_phrase(rt):
    r = await tools.call("live_conversation", {"on": True}, rt)
    assert r.ok and rt.live_talk
    assert instant.plan("pojďme si povídat").calls == [("live_conversation", {"on": True})]
    await tools.call("live_conversation", {"on": False}, rt)
    assert not rt.live_talk


def test_look_to_talk_rules():
    assert webcam.looking([(100, 80, 200, 200)], 1280)
    assert not webcam.looking([(100, 80, 200, 200), (700, 80, 180, 180)], 1280)   # two people: a wake word is needed
    assert not webcam.looking([(100, 80, 60, 60)], 1280)                          # too far to be the one at the PC
    assert not webcam.looking([], 1280)


def test_faces_on_a_blank_frame_finds_nobody():
    import pytest

    pytest.importorskip("cv2")
    assert webcam.faces(np.zeros((480, 640, 3), dtype="uint8")) == []


def test_look_to_talk_needs_speech_while_looking(rt):
    from jarvis.voice.loop import VoiceLoop

    class LW:
        def ok(self):
            return True

    loop = VoiceLoop.__new__(VoiceLoop)
    loop.rt = rt

    class Spk:
        speaking = False

    loop.speaker = Spk()
    loop._is_speech = lambda frame, vad, np_: True
    rt.look_watcher = LW()
    rt.cfg.voice.look_to_talk = True
    hits = [loop._look_talk(b"\\0" * 2560, None, np) for _ in range(4)]
    assert hits == [False, False, True, False]                   # 3 frames = 0.24 s of speech, then it starts over
    rt.cfg.voice.look_to_talk = False
    assert not loop._look_talk(b"\\0" * 2560, None, np)


def test_interpreter_finds_the_virtual_microphone():
    devs = [{"name": "Mikrofon (Realtek)", "max_output_channels": 0}, {"name": "Reproduktory", "max_output_channels": 2},
            {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_output_channels": 2}]
    assert interpreter.find_output("CABLE Input", devs) == 2
    assert interpreter.find_output("nic takového", devs) is None


async def test_interpreter_translates_and_speaks(rt):
    it = interpreter.of(rt)
    it.lang, it.on = "en", True
    rt.router = FakeRouter(["Good morning everyone."])

    class T:
        def transcribe(self, pcm, sr):
            return "Dobré ráno všem."

    class V:
        transcriber = T()
        paused = False

    rt.voice = V()
    played = []

    async def play(text):
        played.append(text)

    it.play = play
    out = await it.say(np.zeros(16000, dtype="float32"))
    assert out == "Good morning everyone." and played == ["Good morning everyone."]
    assert it.lines[-1] == {"cs": "Dobré ráno všem.", "out": "Good morning everyone."}
    assert instant.plan("tlumoč do angličtiny").calls == [("interpreter", {"on": True, "lang": "en"})]
