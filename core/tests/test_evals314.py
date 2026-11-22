"""3.14 návrh 5: the eval set itself – offline score, the live runner with a scripted AI."""
from conftest import FakeRouter
from jarvis import evals
from jarvis.evals import cases


def test_offline_score_is_high():
    rep = evals.offline()
    assert rep["cases"] >= 280
    assert rep["score"] >= 0.95, [m for p in rep["parts"] for m in p["misses"]]


def test_cases_name_real_tools():
    from jarvis import tools

    tools.load_builtin()
    for text, want in cases.PICK:
        assert any(w in tools.REGISTRY for w in want), (text, want)
    for text, tool in cases.INSTANT:
        assert tool in tools.REGISTRY, (text, tool)


def test_intents_do_not_flood():
    from jarvis.tools import select

    assert select.intents("vypni počítač") == ["system_power"]
    assert len(select.intents("každý den ráno zálohuj projekt a spusť testy a pošli mi to")) <= 6
    assert select.intents("ahoj, jak se máš?") == []


async def test_live_runner_scores_each_ai(rt):
    rt.router = FakeRouter([[("system_power", {})], "nevím"])
    rt.cfg.brain.chain = ["omniroute"]
    old = list(cases.PICK)
    try:
        evals.PICK[:] = [("vypni počítač", ("system_power",)), ("kolik je hodin", ("get_time",))]
        rep = await evals.live(rt, limit=2, providers=["fake"])
    finally:
        evals.PICK[:] = old
    assert rep["providers"][0]["ok"] == 1 and rep["providers"][0]["total"] == 2


def test_wer_and_voice_run(tmp_path):
    import json

    from jarvis.evals import voice

    assert voice.wer("hlasitost na třicet", "hlasitost na třicet") == 0
    assert voice.wer("hlasitost na třicet", "hlasitost třicet") == 1 / 3
    assert voice.wer("Další písnička", "dalsi pisnicka") == 0           # accents and case do not count
    (tmp_path / "a.wav").write_bytes(b"RIFF")
    (tmp_path / "b.wav").write_bytes(b"RIFF")
    (tmp_path / "cases.json").write_text(json.dumps({
        "a.wav": {"text": "hlasitost na 30", "tool": "volume"},
        "b.wav": {"text": "vypni počítač", "tool": "system_power"},
        "c.wav": {"text": "chybí", "tool": ""}}), "utf-8")
    heard = {"a.wav": "hlasitost na 30", "b.wav": "vypni počítač"}
    rep = voice.run(tmp_path, lambda p: heard[p.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]])
    assert rep["wer"] == 0 and rep["commands_ok"] == 1.0 and len(rep["errors"]) == 1
