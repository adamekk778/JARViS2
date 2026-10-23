"""3.0 Notetaker: merging the two tracks, echo removal, summary parsing, processing and the tools."""
import json
import wave

from conftest import FakeRouter

from jarvis import paths, tools
from jarvis.notetaker import SR, merge, parse_summary

tools.load_builtin()


def test_merge_orders_and_labels():
    mine = [(0.0, 2.0, "Ahoj, slyšíš mě?"), (6.0, 8.0, "Super, tak začneme.")]
    theirs = [(2.5, 5.0, "Jo, slyším tě dobře.")]
    lines = merge(mine, theirs)
    assert [(l["who"], l["text"]) for l in lines] == [("Já", "Ahoj, slyšíš mě?"), ("Ostatní", "Jo, slyším tě dobře."),
                                                       ("Já", "Super, tak začneme.")]


def test_merge_drops_speaker_echo_in_microphone():
    theirs = [(1.0, 4.0, "Rozpočet na příští měsíc je deset tisíc.")]
    mine = [(1.2, 4.1, "rozpočet na příští měsíc je deset tisíc"), (5.0, 6.0, "Dobře, beru.")]
    lines = merge(mine, theirs)
    assert [l["who"] for l in lines] == ["Ostatní", "Já"]


def test_merge_glues_same_speaker():
    lines = merge([(0, 1, "Ahoj."), (1.5, 3, "Jak se máš?")], [])
    assert len(lines) == 1 and lines[0]["text"] == "Ahoj. Jak se máš?"


def test_parse_summary_json_and_fallback():
    s = parse_summary('```json\n{"title":"Plánování","summary":"Domluvili jsme termín.","points":["pátek"],"todos":["Adam: poslat mail"]}\n```')
    assert s == {"title": "Plánování", "summary": "Domluvili jsme termín.", "points": ["pátek"], "todos": ["Adam: poslat mail"]}
    s = parse_summary("Prostě jsme si povídali.")
    assert s["title"] == "Hovor" and s["summary"] == "Prostě jsme si povídali." and s["todos"] == []


def _wav(path, seconds=2.0):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"\0\0" * int(SR * seconds))


class FakeSegSTT:
    def segments(self, path, progress=None):
        if progress:
            progress(1.0)
        return [(0.0, 2.0, "Ahoj, tady Adam.")] if path.endswith("mic.wav") else [(2.5, 4.0, "Ahoj Adame, tady Petr.")]


async def test_process_writes_note_and_deletes_audio(rt):
    nt = rt.notetaker
    rt.db.exec("INSERT INTO notes VALUES ('n1', 1, 'Nahrávám…', 60, 'processing', '[]', '', '[]', '[]', '')")
    folder = nt.folder("n1")
    _wav(folder / "mic.wav")
    _wav(folder / "sys.wav")
    rt.dictation._own_stt = FakeSegSTT()
    rt.router = FakeRouter(['{"title":"Pozdrav","summary":"Adam a Petr se pozdravili.","points":["pozdrav"],"todos":["Petr: zavolat zítra"]}'])
    await nt.process("n1")
    n = nt.get("n1")
    assert n["status"] == "done" and n["title"] == "Pozdrav" and n["todos"] == ["Petr: zavolat zítra"]
    assert [l["who"] for l in n["transcript"]] == ["Já", "Ostatní"]
    assert not folder.exists()
    assert "Já: Ahoj, tady Adam." in rt.router.calls[0]["messages"][1]["content"]
    assert nt.state == "idle"


async def test_process_without_speech_fails_cleanly(rt):
    nt = rt.notetaker
    rt.db.exec("INSERT INTO notes VALUES ('n2', 1, '', 5, 'processing', '[]', '', '[]', '[]', '')")
    nt.folder("n2")
    await nt.process("n2")
    n = nt.get("n2")
    assert n["status"] == "failed" and "řeč" in n["error"]
    assert not (paths.sub("notes") / "n2").exists()


async def test_summary_failure_keeps_transcript(rt):
    nt = rt.notetaker
    rt.db.exec("INSERT INTO notes VALUES ('n3', 1, '', 60, 'processing', '[]', '', '[]', '[]', '')")
    _wav(nt.folder("n3") / "mic.wav")
    rt.dictation._own_stt = FakeSegSTT()
    rt.router = FakeRouter([RuntimeError("offline")])
    await nt.process("n3")
    n = nt.get("n3")
    assert n["status"] == "done" and n["transcript"] and "nepodařilo" in n["summary"]


def test_start_without_audio_backend(rt, monkeypatch):
    monkeypatch.setattr(rt.notetaker, "_recorders", lambda: (_ for _ in ()).throw(ImportError("no soundcard")))
    res = rt.notetaker.start()
    assert not res["ok"] and "není dostupné" in res["message"] and rt.notetaker.state == "idle"


def test_stale_recordings_marked_failed(rt):
    from jarvis.notetaker import Notetaker

    rt.db.exec("INSERT INTO notes VALUES ('n4', 1, '', 0, 'recording', '[]', '', '[]', '[]', '')")
    Notetaker(rt)
    assert rt.notetaker.get("n4")["status"] == "failed"


def test_record_call_needs_confirmation_only_to_start():
    spec = tools.REGISTRY["record_call"]
    assert tools.is_dangerous(spec, {"action": "start"})
    assert not tools.is_dangerous(spec, {"action": "stop"})


async def test_call_notes_tool(rt):
    rt.db.exec("INSERT INTO notes VALUES ('n5', 1, 'Porada', 600, 'done', ?, 'Shrnutí.', '[\"bod\"]', '[\"úkol\"]', '')",
               (json.dumps([{"who": "Já", "start": 0, "end": 1, "text": "Ahoj"}]),))
    res = await tools.call("call_notes", {}, rt)
    assert res.ok and "n5: Porada (10 min, done)" in res.summary
    res = await tools.call("call_notes", {"id": "n5"}, rt)
    assert res.ok and "Já: Ahoj" in res.summary and "- úkol" in res.summary
