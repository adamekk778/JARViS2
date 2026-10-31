"""Exploded view (484), assembly guide (485), hands-free workshop (492), camera gestures setting (188)."""
import subprocess
from pathlib import Path

from conftest import drain
from jarvis import bridges, config, tools
from jarvis.tools import bridge_tools

tools.load_builtin()


def test_exploded_and_assembly_scripts(tmp_path):
    seen = []

    def runner(cmd, **kw):
        expr = cmd[cmd.index("--python-expr") + 1]
        seen.append(expr)
        if "FACTOR" in expr:
            return subprocess.CompletedProcess(cmd, 0, 'JARVIS_JSON{"parts": ["Base", "Lid"], "out": "x.png"}', "")
        imgs = [{"part": "Base", "image": str(tmp_path / "krok_01.png"), "size": [1, 1, 0.2]},
                {"part": "Lid", "image": str(tmp_path / "krok_02.png"), "size": [1, 1, 0.05]}]
        import json
        return subprocess.CompletedProcess(cmd, 0, "JARVIS_JSON" + json.dumps({"steps": imgs, "total_parts": 2}), "")

    r = bridges.blender_exploded("blender", "a.blend", "out.png", 1.5, runner)
    assert r["parts"] == ["Base", "Lid"] and "FACTOR = 1.5" in seen[0]
    a = bridges.blender_assembly("blender", "a.blend", str(tmp_path), 5, runner)
    assert [s["part"] for s in a["steps"]] == ["Base", "Lid"] and "MAX_STEPS = 5" in seen[1]
    html = bridges.assembly_html("Montáž <krabička>", a["steps"])
    assert "Krok 2" in html and "krok_02.png" in html and "&lt;krabička&gt;" in html


async def test_workshop_mode_reads_steps_and_turns_gestures_on(rt):
    q = rt.bus.subscribe()
    spec = tools.REGISTRY["workshop_mode"]
    assert tools.is_dangerous(spec, {"on": True}, ctx=rt) and not tools.is_dangerous(spec, {"on": False}, ctx=rt)
    r = await tools.call("workshop_mode", {"steps": ["Přišroubuj základ", "Nasaď víko", "Zapoj kabel"]}, rt)
    assert r.ok and rt.cfg.appearance.gestures and rt.cfg.voice.followup
    r = await tools.call("workshop_step", {"move": "next"}, rt)
    assert r.summary == "Krok 2 z 3: Nasaď víko"
    await tools.call("workshop_step", {"move": "prev"}, rt)
    ev = [e for e in drain(q) if e["type"] == "workshop"]
    assert ev[-1]["step"] == 1 and ev[-1]["text"] == "Přišroubuj základ" and ev[-1]["on"]
    r = await tools.call("workshop_mode", {"on": False}, rt)
    assert r.ok and not rt.cfg.appearance.gestures and not bridge_tools.WORKSHOP["on"]
    assert not (await tools.call("workshop_step", {}, rt)).ok


def test_gestures_off_by_default_and_not_for_the_ai():
    assert config.Config().appearance.gestures is False
    src = Path(config.__file__).read_text(encoding="utf-8")
    assert '"appearance.gestures"' not in src             # never in the list of settings the AI may change by itself
