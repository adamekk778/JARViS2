"""3.20 Hlas+ (nápady 1–20)."""
from __future__ import annotations

import datetime as dt
import json
import time
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from conftest import FakeRouter

from jarvis import tools, voicex

NOW = dt.datetime(2026, 11, 24, 10, 0)     # a Tuesday


# ------------------------------------------------------------------ (1) sluchátka
def test_headphones_get_the_voice_and_the_house_stays_quiet(rt):
    outs = ["Reproduktory (Realtek)", "Sluchátka (WH-1000XM5)"]
    assert voicex.is_headphones("Headset Earphone (Jabra Evolve)") and not voicex.is_headphones("Reproduktory (Realtek)")
    assert voicex.output_for(rt, outs) == ""                          # off by default: the speaker you chose
    rt.cfg.voice.headphones_only = True
    assert voicex.output_for(rt, outs) == "Sluchátka (WH-1000XM5)"
    assert not voicex.house_speakers_ok(rt, outs) and voicex.house_speakers_ok(rt, ["Reproduktory (Realtek)"])
    rt.cfg.voice.output_device = "Reproduktory (Realtek)"
    assert voicex.output_for(rt, ["Reproduktory (Realtek)"]) == "Reproduktory (Realtek)"


# ------------------------------------------------------------------ (2) šepot
def test_whisper_is_levelled_up_and_a_voice_is_left_alone():
    rng = np.random.default_rng(1)
    whisper = (rng.standard_normal(16000) * 0.004).astype(np.float32)       # noise-like, no pitch, quiet
    out = voicex.whisper_boost(whisper)
    assert float(np.sqrt(np.mean(out ** 2))) > 5 * float(np.sqrt(np.mean(whisper ** 2)))
    t = np.arange(16000) / 16000
    voice = (0.2 * np.sin(2 * np.pi * 140 * t)).astype(np.float32)          # a voiced tone
    assert np.array_equal(voicex.whisper_boost(voice), voice)


# ------------------------------------------------------------------ (3) sčítání
def test_czech_numbers():
    assert voicex.cz_number("250") == 250 and voicex.cz_number("1 250,50 Kč") == 1250.5
    assert voicex.cz_number("dvě stě padesát") == 250 and voicex.cz_number("tři tisíce dvě stě") == 3200
    assert voicex.cz_number("pět set dvacet") == 520 and voicex.cz_number("ahoj") is None


async def test_running_sum_without_the_ai(rt):
    rt.router = FakeRouter(["nemá se volat"])
    out = await rt.agent.handle("sečti 120 a 250")
    assert out == "120 + 250 je 370." and not rt.router.calls
    assert "celkem 450" in await rt.agent.handle("a ještě 80")
    assert "celkem 400" in await rt.agent.handle("mínus 50")
    assert "Celkem 400" in await rt.agent.handle("kolik to dělá")
    assert "400" in await rt.agent.handle("konec sčítání")
    assert not voicex.tally_active(rt) and not rt.router.calls


# ------------------------------------------------------------------ (4) rozhovor ve dvou
def test_words_for_someone_else_are_not_answered(rt):
    rt.update_config({"booking": {"companions": [{"first_name": "Jana", "last_name": "Nováková"}]}})
    assert voicex.aside(rt, "Jano, podej mi tu sůl")
    assert voicex.aside(rt, "mami, kdy bude večeře?") and voicex.aside(rt, "ty jsi to snědl?")
    assert not voicex.aside(rt, "Jarvisi, jaké je počasí")
    assert not voicex.aside(rt, "jaké bude zítra počasí")
    rt.cfg.voice.addressed_only = False
    assert not voicex.aside(rt, "Jano, podej mi tu sůl")


def test_vocatives():
    assert "jano" in voicex._vocative_of("jana") and "pavle" in voicex._vocative_of("pavel")
    assert "tomasi" in voicex._vocative_of("tomas") and "petre" in voicex._vocative_of("petr")


# ------------------------------------------------------------------ (5, 11) budíček, vzkaz do budoucna
def test_parse_when():
    assert voicex.parse_when("7:30", NOW) == dt.datetime(2026, 11, 25, 7, 30)          # already past today → tomorrow
    assert voicex.parse_when("zítra v 6", NOW) == dt.datetime(2026, 11, 25, 6, 0)
    assert voicex.parse_when("v pátek v 8:15", NOW) == dt.datetime(2026, 11, 27, 8, 15)
    assert voicex.parse_when("24. 12. 2027", NOW) == dt.datetime(2027, 12, 24, 9, 0)
    assert voicex.parse_when("za rok", NOW).date() == dt.date(2027, 11, 24)
    assert voicex.parse_when("1. 1. 2020", NOW) is None


async def test_alarm_and_future_message_jobs(rt, monkeypatch):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    r = await tools.call("voice_kit", {"action": "alarm", "when": "6:45", "days": "po-pa"}, rt)
    assert r.ok and r.data["kind"] == "voice_alarm" and r.data["spec"]["days"] == [0, 1, 2, 3, 4]
    r = await tools.call("voice_kit", {"action": "future", "text": "Zkontroluj, jestli běháš.", "when": "za rok"}, rt)
    assert r.ok and r.data["kind"] == "future_message" and r.data["payload"]["text"] == "Zkontroluj, jestli běháš."
    said = []
    rt.notify = lambda title, body, **kw: said.append((title, body, kw.get("urgent")))

    async def fake_build(_rt):
        return {"title": "Ranní souhrn", "text": "Dnes 3 °C, v 9:00 porada."}
    monkeypatch.setattr("jarvis.morning.build", fake_build)
    await voicex.run_alarm(rt, {})
    await voicex.run_future(rt, {"text": "Ahoj z minulosti.", "made": "2026-11-24"})
    assert "porada" in said[0][1] and said[0][2] is True
    assert said[1][1] == "Vzkaz z 24. 11. 2026: Ahoj z minulosti."


# ------------------------------------------------------------------ (6, 9) navigace v odpovědi
LONG = "První věta o počasí. Druhá věta o dopravě. Třetí věta o kalendáři. Závěr: vezmi si deštník."


def test_skip_back_end_and_slower(rt):
    rt.speaker = None
    voicex.remember_answer(rt, LONG, SimpleNamespace(queued=["První věta o počasí.", "Druhá věta o dopravě."], played=1))
    assert voicex.nav_active(rt)
    assert voicex.navigate(rt, "skip")[0].startswith("Třetí věta")
    assert voicex.navigate(rt, "back")[0].startswith("První věta")
    assert voicex.navigate(rt, "end")[0] == "Závěr: vezmi si deštník."
    say, rate = voicex.navigate(rt, "slow")
    assert say.startswith("První věta") and rate == "-20%"
    assert voicex.nav_kind("přeskoč") == "skip" and voicex.nav_kind("vrať se o větu") == "back"
    assert voicex.nav_kind("řekni jen závěr") == "end" and voicex.nav_kind("cože?") == "slow" and voicex.nav_kind("přeskoč písničku") == ""


async def test_skip_goes_to_the_answer_only_right_after_a_long_one(rt):
    rt.router = FakeRouter([])
    voicex.remember_answer(rt, LONG)
    out = await rt.agent.handle("jen závěr")
    assert out == "Závěr: vezmi si deštník." and not rt.router.calls
    rt.voicex_said["ts"] = time.time() - 600                  # long ago: "přeskoč" is the next song again
    assert not voicex.nav_active(rt)


# ------------------------------------------------------------------ (7) hlasové poznámky
async def test_voice_note_keeps_the_recording(rt):
    rt.voicex_last_pcm, rt.voicex_last_pcm_text = (np.zeros(8000, np.int16)).tobytes(), "poznamenej si koupit baterky do ovladače"
    out = await rt.agent.handle("poznamenej si koupit baterky do ovladače")
    assert out.startswith("Poznamenáno") and "nahrávkou" in out
    notes = voicex.voice_notes(rt)
    assert notes[0]["text"] == "koupit baterky do ovladače" and notes[0]["wav"].endswith(".wav")
    r = await tools.call("voice_kit", {"action": "notes"}, rt)
    assert "baterky" in r.summary


# ------------------------------------------------------------------ (8) předání rozhovoru
async def test_unfinished_answer_moves_to_the_room(rt, monkeypatch):
    said = []

    async def fake_announce(_rt, text, where="all"):
        said.append((text, where))
        return {"ok": True}
    monkeypatch.setattr("jarvis.house.announce", fake_announce)
    rt.speaker = SimpleNamespace(speaking=True, stop=lambda: None)
    voicex.remember_answer(rt, LONG, SimpleNamespace(queued=["První věta o počasí.", "Druhá věta o dopravě. Třetí věta o kalendáři."],
                                                     played=1))
    rest = await voicex.handoff(rt, "kuchyně")
    assert rest.startswith("Druhá věta") and said == [(rest, "kuchyně")]
    assert voicex.room_context(rt, "obývák").startswith("Uživatel přešel z místa „kuchyně“ do místnosti „obývák“")
    assert voicex.room_context(rt, "obývák") == ""


# ------------------------------------------------------------------ (10) čtení se záložkou
def test_reading_remembers_where_you_stopped(rt):
    text = " ".join(f"Věta číslo {i}." for i in range(1, 11))
    info = voicex.start_reading(rt, "Článek", text, "https://example.com/a")
    assert info == {"resumed": False, "pos": 0, "total": 10}
    assert voicex.next_chunk(rt) == "Věta číslo 1. Věta číslo 2. Věta číslo 3. Věta číslo 4."
    assert "40 %" in voicex.where_reading(rt)
    rt.voicex_read = None
    again = voicex.start_reading(rt, "Článek", text, "https://example.com/a")
    assert again["resumed"] and again["pos"] == 4
    assert voicex.reading_rate(rt, 10) == 10 and voicex.reading_rate(rt, 100) == 60


# ------------------------------------------------------------------ (12) čeština + angličtina
def test_english_words_come_back(rt):
    assert voicex.codeswitch(rt, "pusť ten plejlist čil vajbs na spotifaj") == "pusť ten playlist chill vibes na Spotify"
    rt.update_config({"voice": {"pronounce": [{"src": "Netlify", "dst": "netlifaj"}]}})
    assert voicex.codeswitch(rt, "otevři netlifaj") == "otevři Netlify"
    rt.cfg.voice.code_switch = False
    assert voicex.codeswitch(rt, "čil vajbs") == "čil vajbs"


# ------------------------------------------------------------------ (13, 15, 18) hlas pro děti, tón, rychlost
def test_kids_voice_tone_and_rate(rt, monkeypatch):
    monkeypatch.setattr("jarvis.safety.kids_on", lambda _rt: True)
    assert voicex.kids_override(rt)["tts_voice"] == "cs-CZ-VlastaNeural"
    rt.cfg.voice.kids_voice = False
    assert voicex.kids_override(rt) is None
    assert voicex.plain_ack("Hotovo, pane.") and voicex.plain_ack("Pouštím.") and not voicex.plain_ack("V Brně bude 5 °C a polojasno.")
    wav = voicex.tone_wav()
    assert wav[:4] == b"RIFF" and len(wav) > 4000
    assert voicex.length_rate(rt, "krátce", "+0%") == "+0%" and voicex.length_rate(rt, "x" * 800, "+5%") == "+17%"


# ------------------------------------------------------------------ (14) rodinné hlasování
async def test_family_poll(rt, monkeypatch):
    said = []
    rt.notify = lambda title, body, **kw: said.append(body)
    monkeypatch.setattr("jarvis.voicex.house_speakers_ok", lambda _rt, outputs=None: False)
    r = await tools.call("family_poll", {"question": "Co k večeři?", "options": ["pizza", "sushi"], "minutes": 5}, rt)
    assert r.ok and "pizza, sushi" in said[0]
    assert voicex.poll_answer(rt, "já chci pizzu", "Adam") == "Zapsáno: pizza."
    assert voicex.poll_answer(rt, "pro mě sushi", "Jana") == "Zapsáno: sushi."
    assert voicex.poll_answer(rt, "taky pizzu", "Petr") == "Zapsáno: pizza."
    assert voicex.poll_answer(rt, "nevím", "Eva") is None
    assert voicex.poll_result(rt) == "Vyhrává pizza. Hlasy: pizza 2, sushi 1."


# ------------------------------------------------------------------ (17) nácvik prezentace
def test_speech_coach_metrics():
    text = "Dobrý den ehm dnes vám ehm jako ukážu prostě náš nový produkt " * 6
    r = voicex.coach(text, 20.0, [0.5, 3.4, 4.0])
    assert r["wpm"] > 170 and r["fillers"]["ehm"] == 12 and r["long_pauses"] == 2 and r["length"] == "0:20"
    assert any("rychle" in t for t in r["tips"]) and any("výplňových" in t for t in r["tips"])
    pcm = np.concatenate([np.full(16000, 3000, np.int16), np.zeros(16000, np.int16), np.full(8000, 3000, np.int16)]).tobytes()
    p = voicex.pauses_of(pcm)
    assert len(p) == 1 and 0.9 <= p[0] <= 1.1


# ------------------------------------------------------------------ (19) oznámení podle odesílatele
def test_notices_by_sender(rt):
    rt.cfg.voice.read_full_from = ["jana"]
    title, body = voicex.notice_text(rt, "Jana Nováková", "jana@example.cz", "Večer", "Přijdu v sedm, vezmu víno.")
    assert title == "Zpráva od blízkého" and "Přijdu v sedm" in body
    assert voicex.notice_text(rt, "Alza.cz", "noreply@alza.cz", "Vaše objednávka")[1] == "Přišel e-mail od Alza.cz."
    assert voicex.notice_text(rt, "Petr Malý", "petr@firma.cz", "Smlouva")[1] == "Píše vám Petr Malý: Smlouva"


# ------------------------------------------------------------------ (20) vlastní hlas
async def test_voice_clone_needs_consent_and_a_key(rt, tmp_path, monkeypatch):
    rec = tmp_path / "ja.wav"
    rec.write_bytes(b"RIFF" + b"\0" * 40000)
    with pytest.raises(ValueError, match="souhlasu"):
        await voicex.clone_voice(rt, str(rec), consent=False)
    monkeypatch.setattr("jarvis.secrets.get", lambda name: "xi-key" if name == "elevenlabs" else "")
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["key"] = req.headers.get("xi-api-key")
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"voice_id": "v123"})
    rt.http = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    r = await tools.call("voice_clone", {"path": str(rec), "consent": True}, rt)
    assert r.ok and seen == {"key": "xi-key", "url": voicex.CLONE_URL}
    assert rt.cfg.voice.eleven_voice_id == "v123" and rt.cfg.voice.tts_engine == "elevenlabs"
    assert tools.REGISTRY["voice_clone"].danger
    assert json.loads(rt.db.one("SELECT v FROM kv WHERE k='voice_clone'")["v"])["id"] == "v123"
