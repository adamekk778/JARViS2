"""Wave 43: workflow recorder and sharing, animated scene proposals, audio device handoff, rigging assistant."""
import json
import struct
import sys
import time

import pytest

from jarvis import flowplus, tools
from jarvis.tools import flowplus_tools

tools.load_builtin()


def test_steps_from_recording():
    acts = [{"ts": 10, "tool": "update_plan", "args": "{}", "ok": 1},
            {"ts": 11, "tool": "web_search", "args": '{"query": "kurz eura"}', "ok": 1},
            {"ts": 12, "tool": "web_search", "args": '{"query": "kurz eura"}', "ok": 1},
            {"ts": 30, "tool": "set_volume", "args": '{"level": 20}', "ok": 0},
            {"ts": 40, "tool": "list_add", "args": '{"items": ["eura"]}', "ok": 1}]
    apps = [{"ts": 5, "app": "Excel"}, {"ts": 20, "app": "Excel"}, {"ts": 25, "app": "Outlook"}]
    st = flowplus.steps_from_recording(acts, apps)
    assert st == [{"tool": "open_app", "args": {"name": "Excel"}}, {"tool": "web_search", "args": {"query": "kurz eura"}},
                  {"tool": "open_app", "args": {"name": "Outlook"}}, {"tool": "list_add", "args": {"items": ["eura"]}}]


def test_app_watch_only_records_changes():
    seq = iter(["Excel", "Excel", "", "Word"])
    w = flowplus.AppWatch(lambda: next(seq))
    for i in range(4):
        w.sample(i)
    assert [x["app"] for x in w.log] == ["Excel", "Word"]


async def test_workflow_record_tool(rt):
    r = await tools.call("workflow_record", {"action": "start", "name": "Ranní kurz"}, rt)
    assert r.ok and rt.notify
    rt.tasks.begin("test", rt.memory.current_conversation)
    rt.tasks.log_action("web_search", {"query": "kurz eura"}, True, "ok", 5)
    assert tools.is_dangerous(tools.REGISTRY["workflow_record"], {"action": "stop"}, ctx=rt)
    details = flowplus_tools._rec_details({"action": "stop"}, rt)
    assert "kurz eura" in " ".join(details) or "web_search" in " ".join(details) or len(details) == 2
    r = await tools.call("workflow_record", {"action": "stop"}, rt)
    assert r.ok and any(p.name == "Ranní kurz" for p in rt.cfg.stark.protocols)
    assert not (await tools.call("workflow_record", {"action": "stop"}, rt)).ok


def test_export_scrubs_secrets(tmp_path):
    proto = {"id": "x", "name": "Záloha", "icon": "x", "steps": [
        {"tool": "api_call", "args": {"name": "shop", "params": {"api_key": "abc123", "q": "ok"}}, "say": "", "ask": ""},
        {"tool": "copy_file", "args": {"path": "C:\\Users\\adam\\Documents\\a.txt", "token_note": "x"}},
        {"say": "Hotovo, karta 4111111111111111", "tool": ""}]}
    r = flowplus.export_flow(proto, "/home/adam")
    s = json.dumps(r["flow"], ensure_ascii=False)
    assert "abc123" not in s and "4111111111111111" not in s and "adam" not in s and r["removed_secrets"] == 3
    assert r["flow"]["steps"][0]["args"]["params"]["q"] == "ok" and "~\\\\Documents" in s


def test_check_flow():
    f = flowplus.export_flow({"name": "P", "steps": [{"tool": "open_app", "args": {"name": "Excel"}}, {"tool": "delete_file", "args": {"path": "a"}},
                                                       {"ask": "shrň poštu"}]})["flow"]
    known = {"open_app", "delete_file"}
    c = flowplus.check_flow(f, known, lambda t, a: t == "delete_file")
    assert c["ok"] and [s["changes"] for s in c["steps"]] == [False, True, False] and "úkoly pro AI" in c["warnings"][0]
    tampered = {**f, "steps": f["steps"] + [{"tool": "open_app", "args": {}}]}
    assert "změněn" in flowplus.check_flow(tampered, known, lambda t, a: False)["problems"][0]
    unknown = flowplus.export_flow({"name": "Q", "steps": [{"tool": "format_disk", "args": {}}]})["flow"]
    assert not flowplus.check_flow(unknown, known, lambda t, a: False)["ok"]
    assert not flowplus.check_flow({"x": 1}, known, lambda t, a: False)["ok"]


async def test_export_import_roundtrip(rt):
    rt.update_config({"stark": {"protocols": [p.model_dump(mode="json") for p in rt.cfg.stark.protocols] +
                                [{"id": "moje", "name": "Moje", "steps": [{"tool": "open_app", "args": {"name": "Spotify"}}]}]}})
    r = await tools.call("workflow_export", {"name": "Moje"}, rt)
    assert r.ok and r.attachments[0].endswith(".jarvisflow.json")
    det = flowplus_tools._import_details({"file": r.attachments[0]}, rt)
    assert any("open_app" in d for d in det)
    r2 = await tools.call("workflow_import", {"file": r.attachments[0]}, rt)
    assert r2.ok and any(p.name == "Sdílený: Moje" for p in rt.cfg.stark.protocols)
    assert tools.REGISTRY["workflow_import"].danger


def test_scene_plan_and_outputs():
    p = flowplus.scene_plan("reklama na sportovní boty", 10)
    assert p["style"] == "energická" and abs(sum(s["duration"] for s in p["shots"]) - 10) < 0.05
    assert p["shots"][0]["shot"] == "Úvod" and p["shots"][-1]["shot"] == "Závěr"
    starts = [s["start"] for s in p["shots"]]
    assert starts == sorted(starts) and starts[0] == 0
    html_ = flowplus.scene_preview_html(p)
    assert html_.count('class="shot"') == len(p["shots"]) and "@keyframes m0" in html_
    py = flowplus.scene_blender_script(p)
    compile(py, "scena.py", "exec")
    assert "keyframe_insert" in py and f"frame_end = 1, {int(10 * 24)}" in py
    assert flowplus.scene_plan("klidná krajina", 30)["style"] == "klidná"


async def test_scene_tool(rt):
    r = await tools.call("scene_animation", {"brief": "aplikace pro data", "seconds": 8}, rt)
    assert r.ok and r.data["style"] == "technická" and len(r.attachments) == 2


def test_pick_device():
    devs = [{"id": "1", "name": "Reproduktory (Realtek(R) Audio)", "state": "active", "flow": "output"},
            {"id": "2", "name": "Sluchátka (WH-1000XM4 Hands-Free)", "state": "active", "flow": "output"},
            {"id": "3", "name": "Headphones (AirPods Pro)", "state": "off", "flow": "output"},
            {"id": "4", "name": "LG TV (HDMI)", "state": "active", "flow": "output"}]
    assert flowplus.pick_device(devs, "sluchátka")["id"] == "2"
    assert flowplus.pick_device(devs, "reproduktory")["id"] == "1"
    assert flowplus.pick_device(devs, "televize")["id"] == "4"
    assert flowplus.pick_device(devs, "airpods") is None                     # disconnected
    assert flowplus.pick_device(devs, "WH-1000XM4")["id"] == "2"


@pytest.mark.skipif(sys.platform == "win32", reason="would switch the real audio device of the machine")
async def test_audio_tool_non_windows(rt):
    r = await tools.call("audio_device", {"device": "sluchátka"}, rt)
    assert not r.ok and "Windows" in r.summary


def test_rigs_are_valid():
    for bones in (flowplus.humanoid_rig(1.8), flowplus.quadruped_rig(1.2)):
        r = flowplus.check_rig(bones)
        assert r["ok"] and not r["warnings"] and r["roots"] == ["root"]
    tall = {b["name"]: b for b in flowplus.humanoid_rig(2.0)}
    assert tall["head"]["tail"][2] == pytest.approx(1.78 / 1.8 * 2.0, abs=1e-3)
    compile(flowplus.blender_rig_script(flowplus.humanoid_rig(), "Postava"), "rig.py", "exec")


def test_check_rig_problems():
    bones = [{"name": "root", "parent": None, "head": (0, 0, 0), "tail": (0, 0, 1)},
             {"name": "arm.L", "parent": "root", "head": (0, 0, 1), "tail": (0.5, 0, 1)},
             {"name": "leg.L", "parent": "root", "head": (0, 0, 0), "tail": (0, 0, -1)},
             {"name": "leg.R", "parent": "root", "head": (0, 0, 0), "tail": (0, 0, -0.5)},
             {"name": "a", "parent": "b", "head": (0, 0, 0), "tail": (0, 0, 0)},
             {"name": "b", "parent": "a", "head": (0, 0, 0), "tail": (0, 1, 0)},
             {"name": "x", "parent": "nikdo", "head": (0, 0, 0), "tail": (0, 1, 0)}]
    r = flowplus.check_rig(bones)
    text = " ".join(r["problems"] + r["warnings"])
    assert not r["ok"] and "nulovou délku" in text and "Smyčka" in text and "nikdo neexistuje" in text
    assert "arm: je jen levá strana" in text and "jinou délku" in text
    assert flowplus._side("mixamorig:LeftArm") == ("mixamorig:Arm", "L") and flowplus._side("hand_r") == ("hand", "R")


def _glb(doc: dict) -> bytes:
    js = json.dumps(doc).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    return b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js)) + struct.pack("<I", len(js)) + b"JSON" + js


async def test_gltf_check(rt, tmp_path):
    doc = {"nodes": [{"name": "Hips", "children": [1, 2], "translation": [0, 1, 0]}, {"name": "LeftUpLeg", "translation": [0.1, -0.1, 0]},
                     {"name": "Spine", "translation": [0, 0.2, 0]}, {"name": "Mesh"}],
           "skins": [{"joints": [0, 1, 2]}]}
    f = tmp_path / "postava.glb"
    f.write_bytes(_glb(doc))
    bones = flowplus.gltf_bones(f)
    assert [b["name"] for b in bones] == ["Hips", "LeftUpLeg", "Spine"] and bones[1]["parent"] == "Hips" and bones[1]["head"] == (0.1, 0.9, 0)
    r = await tools.call("rig_assistant", {"check_file": str(f)}, rt)
    assert r.ok and "UpLeg: je jen levá strana" in r.summary
    (tmp_path / "bez.gltf").write_text(json.dumps({"nodes": [{"name": "a"}]}))
    assert not (await tools.call("rig_assistant", {"check_file": str(tmp_path / "bez.gltf")}, rt)).ok
    r = await tools.call("rig_assistant", {"kind": "quadruped", "height": 0.8, "mesh": "Pes"}, rt)
    assert r.ok and r.attachments[0].endswith(".py") and "tail" in r.data["bones"]
    assert time.time()
