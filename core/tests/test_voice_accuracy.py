"""3.20.1 Better Czech by ear and quicker answers aloud: the model per PC, the Czech hint, made-up sentences, the
deep-thinking rule only for what really is at stake."""
from __future__ import annotations

from types import SimpleNamespace

from jarvis import brainx
from jarvis.voice import stt as stt_mod


def test_the_accurate_model_where_the_pc_runs_it():
    assert stt_mod.best_model(cuda=True, threads=4) == "large-v3-turbo"
    assert stt_mod.best_model(cuda=False, threads=16) == "large-v3-turbo"
    assert stt_mod.best_model(cuda=False, threads=8) == "small"


def test_small_answers_while_the_accurate_model_downloads(monkeypatch):
    t = stt_mod.Transcriber(SimpleNamespace(stt_provider="local", stt_model="auto", stt_language="cs", stt_download_ok=True))
    monkeypatch.setattr(stt_mod, "best_model", lambda: "large-v3-turbo")
    disk = {"small"}
    monkeypatch.setattr(stt_mod.Transcriber, "on_disk", staticmethod(lambda name: name in disk))
    asked = []
    monkeypatch.setattr(t, "_download_later", lambda name: asked.append(name))
    assert t.model_now() == "small" and asked == ["large-v3-turbo"] and t.local_ready()
    disk.add("large-v3-turbo")
    assert t.model_now() == "large-v3-turbo"
    t.cfg.stt_model = "medium"                              # your own choice stays yours
    disk.add("medium")
    assert t.model_now() == "medium"
    t.cfg.stt_download_ok = False                           # no consent: nothing is downloaded behind your back
    asked.clear()
    disk.discard("large-v3-turbo")
    t.cfg.stt_model = "auto"
    assert t.model_now() == "small" and asked == []


def test_made_up_sentences_are_dropped():
    assert stt_mod.clean_hallucinations([" Titulky vytvořil JohnyX"]) == ""
    assert stt_mod.clean_hallucinations(["Zhasni světla v obýváku.", " Děkuji za pozornost."]) == "Zhasni světla v obýváku."
    assert stt_mod.clean_hallucinations(["Konec"]) == "" and stt_mod.clean_hallucinations(["Konec filmu je super."]) != ""


def test_saved_small_becomes_auto_once():
    from jarvis.config import Config

    old = Config().model_dump(mode="json")
    old["voice"]["stt_model"] = "small"
    old["voice"].pop("stt_model_rev")
    assert Config.model_validate(old).voice.stt_model == "auto"
    mine = Config().model_dump(mode="json")
    mine["voice"]["stt_model"] = "small"                    # chosen again after the change: stays
    assert Config.model_validate(mine).voice.stt_model == "small"
    assert Config().voice.stt_model == "auto"


def test_final_words_use_beam_search_and_the_czech_hint(monkeypatch):
    seen = {}

    class Model:
        def transcribe(self, audio, **kw):
            seen.update(kw)
            return [SimpleNamespace(text=" Zhasni světla."), SimpleNamespace(text=" Titulky vytvořil JohnyX")], \
                SimpleNamespace(language="cs")

    t = stt_mod.Transcriber(SimpleNamespace(stt_provider="local", stt_model="small", stt_language="cs", stt_download_ok=True))
    monkeypatch.setattr(t, "_local", lambda: Model())
    assert t._run([0.0], "Kryštof") == "Zhasni světla."
    assert seen["beam_size"] == 5 and seen["initial_prompt"].startswith(stt_mod.CS_HINT) and "Kryštof" in seen["initial_prompt"]
    tiny = stt_mod.Transcriber(SimpleNamespace(stt_provider="local", stt_model="tiny", stt_language="cs", stt_download_ok=True))
    monkeypatch.setattr(tiny, "_local", lambda: Model())
    tiny._run([0.0])
    assert seen["beam_size"] == 1 and not seen["initial_prompt"]     # the live text stays quick


def test_everyday_commands_do_not_think_at_the_highest_effort():
    for t in ("pošli mi tu fotku do telefonu", "kde je nejbližší lékárna", "připomeň mi lekci angličtiny", "pošli to na tiskárnu",
              "dej mi akci na dnešek", "smaž tu připomínku", "objednej pizzu", "kup lístky do kina", "jaká je platforma"):
        assert not brainx.risky_action(t), t
    for t in ("zaplať tu fakturu", "převeď mu dva tisíce", "smaž všechny fotky z dovolené", "zformátuj disk D",
              "podepiš tu smlouvu", "jaké je dávkování ibuprofenu"):
        assert brainx.risky_action(t), t


def test_aloud_the_answer_stays_quick(rt):
    from jarvis import agent_x320

    kw = {"fast": True}
    agent_x320.tune_routing(rt, "zaplať tu fakturu", kw, False, None, "voice")
    assert kw.get("fast") and "effort" not in kw                    # risky actions ask for confirmation anyway
    kw = {"fast": True}
    agent_x320.tune_routing(rt, "zaplať tu fakturu", kw, False, None, "chat")
    assert kw.get("effort") == "high" and "fast" not in kw
    kw = {"fast": True}
    agent_x320.tune_routing(rt, "promysli to důkladně, jestli mám koupit auto", kw, False, None, "voice")
    assert kw.get("effort") == "high" and kw.get("fast")           # asked for it aloud: deeper, the quick path stays


def test_a_hint_when_the_accurate_model_is_not_allowed(rt, monkeypatch):
    from jarvis.voice.loop import VoiceLoop

    v = VoiceLoop.__new__(VoiceLoop)
    v.rt = rt
    rt.cfg.voice.stt_download_ok = False
    v.transcriber = stt_mod.Transcriber(rt.cfg.voice)
    monkeypatch.setattr(stt_mod, "best_model", lambda: "large-v3-turbo")
    monkeypatch.setattr(stt_mod.Transcriber, "on_disk", staticmethod(lambda name: name == "small"))
    monkeypatch.setattr(v.transcriber, "provider", lambda: "local")
    said = []
    monkeypatch.setattr(rt, "notify", lambda title, body, **kw: said.append(title))
    v._upgrade_hint()
    v._upgrade_hint()
    assert said == ["Přesnější rozpoznávání češtiny"]          # once
    v2 = VoiceLoop.__new__(VoiceLoop)
    v2.rt, v2.transcriber = rt, v.transcriber
    v2._upgrade_hint()
    assert len(said) == 1                                      # and not again this week
