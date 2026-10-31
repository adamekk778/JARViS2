"""Blender / Unity / Roblox / Czech public transport bridges and several models of one gateway compared."""
import datetime as dt
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from conftest import FakeRouter
from jarvis import bridges, thinking, tools

tools.load_builtin()


def _cp(out="", err="", code=0):
    return subprocess.CompletedProcess([], code, out, err)


def test_blender_info_and_export_commands(tmp_path):
    seen = []

    def runner(cmd, **kw):
        seen.append(cmd)
        if "--python-expr" in cmd and "OUT =" in cmd[cmd.index("--python-expr") + 1]:
            return _cp('JARVIS_JSON{"ok": true}')
        return _cp('noise\nJARVIS_JSON{"scene": "Scene", "frames": [1, 250], "fps": 24, "engine": "CYCLES", '
                   '"resolution": [1920, 1080], "camera": "Camera", "objects": [{"name": "Cube", "type": "MESH", "verts": 8}]}')

    info = bridges.blender_info("blender", "a.blend", runner)
    assert info["objects"][0]["verts"] == 8 and seen[0][:3] == ["blender", "-b", "a.blend"]
    out = bridges.blender_export("blender", "a.blend", str(tmp_path / "a.glb"), "glb", runner)
    assert out.endswith("a.glb") and "export_scene.gltf" in seen[1][seen[1].index("--python-expr") + 1]
    with pytest.raises(ValueError):
        bridges.blender_export("blender", "a.blend", "x.abc", "abc", runner)
    with pytest.raises(RuntimeError, match="nevrátil"):
        bridges.blender_info("blender", "a.blend", lambda c, **k: _cp("", "Error: not a blend file"))


def test_blender_render_moves_the_frame(tmp_path):
    out = tmp_path / "r.png"

    def runner(cmd, **kw):
        base = cmd[cmd.index("-o") + 1].replace("_####", "")
        Path(f"{base}_0007.png").write_bytes(b"PNG")
        return _cp()

    assert bridges.blender_render("blender", "a.blend", str(out), 7, runner) == str(out) and out.read_bytes() == b"PNG"


def test_unity_project_and_results(tmp_path):
    (tmp_path / "ProjectSettings").mkdir()
    (tmp_path / "ProjectSettings" / "ProjectVersion.txt").write_text("m_EditorVersion: 2022.3.40f1\n", encoding="utf-8")
    (tmp_path / "ProjectSettings" / "EditorBuildSettings.asset").write_text("  - enabled: 1\n    path: Assets/Scenes/Main.unity\n", encoding="utf-8")
    (tmp_path / "Packages").mkdir()
    (tmp_path / "Packages" / "manifest.json").write_text(json.dumps({"dependencies": {"com.unity.test-framework": "1.1.33"}}), encoding="utf-8")
    (tmp_path / "Assets" / "Scenes").mkdir(parents=True)
    (tmp_path / "Assets" / "Scenes" / "Main.unity").write_text("x", encoding="utf-8")
    (tmp_path / "Assets" / "Player.cs").write_text("class P {}", encoding="utf-8")
    (tmp_path / "Assets" / "PlayerTests.cs").write_text("[Test] public void Moves() {}", encoding="utf-8")
    info = bridges.unity_project(tmp_path)
    assert info["version"] == "2022.3.40f1" and info["scenes"] == ["Assets/Scenes/Main.unity"] and info["test_files"] == 1
    xml = ('<test-run><test-case fullname="A.Ok" result="Passed"/><test-case fullname="A.Bad" result="Failed">'
           '<failure><message>Expected 2 but was 3</message></failure></test-case><test-case fullname="A.Skip" result="Skipped"/></test-run>')
    r = bridges.parse_nunit(xml)
    assert r == {"total": 3, "passed": 1, "failed": [{"name": "A.Bad", "message": "Expected 2 but was 3"}], "skipped": 1}
    with pytest.raises(ValueError):
        bridges.unity_project(tmp_path / "Assets")


async def test_roblox_open_cloud(tmp_path):
    place = tmp_path / "hra.rbxl"
    place.write_bytes(b"<roblox!")
    seen = {}

    def handler(req):
        seen["url"], seen["key"] = str(req.url), req.headers.get("x-api-key")
        if "datastores" in req.url.path:
            return httpx.Response(200, json={"keys": [{"key": "player_1"}, {"key": "player_2"}]})
        return httpx.Response(200, json={"versionNumber": 12})

    tr = httpx.MockTransport(handler)
    r = await bridges.roblox_publish("k", 111, 222, place, True, tr)
    assert r["versionNumber"] == 12 and "/universes/v1/111/places/222/versions" in seen["url"] and "Published" in seen["url"]
    d = await bridges.roblox_datastore("k", 111, "Coins", transport=tr)
    assert [k["key"] for k in d["keys"]] == ["player_1", "player_2"] and seen["key"] == "k"
    with pytest.raises(RuntimeError, match="API klíč"):
        await bridges.roblox_publish("", 1, 2, place, True, tr)
    made = bridges.rojo_project(tmp_path / "rojo", "Hra")
    assert (tmp_path / "rojo" / "default.project.json").exists() and len(made) == 5


async def test_transit():
    url = bridges.idos_link("Brno", "Praha", dt.datetime(2026, 11, 2, 8, 15))
    assert url.startswith("https://idos.cz/") and "f=Brno" in url and "t=Praha" in url and "time=08%3A15" in url

    def handler(req):
        assert req.headers["X-Access-Token"] == "g" and req.url.params["names"] == "Můstek"
        return httpx.Response(200, json={"departures": [{"route": {"short_name": "A"}, "trip": {"headsign": "Depo Hostivař"},
                                         "departure_timestamp": {"predicted": "2026-11-02T08:16:00+01:00"},
                                         "delay": {"seconds": 120}, "stop": {"platform_code": "1"}}]})

    deps = await bridges.pid_departures("g", "Můstek", transport=httpx.MockTransport(handler))
    assert deps == [{"line": "A", "to": "Depo Hostivař", "time": "08:16", "delay_min": 2, "platform": "1"}]


async def test_transit_tool_opens_idos(rt):
    r = await tools.call("transit_connection", {"src": "Ostrava", "dst": "Olomouc", "when": "18:30", "open_browser": True}, rt)
    assert r.ok and "idos.cz" in r.data["url"] and any(c[0] == "open_url" for c in rt.platform.calls)


def test_diverse_models_one_per_family():
    models = ["auto", "text-embedding-3", "openai/gpt-4o", "openai/gpt-4o-mini", "anthropic/claude-sonnet-4",
              "google/gemini-2.5-flash", "meta-llama/llama-3.3-70b"]
    assert thinking.diverse_models(models) == ["anthropic/claude-sonnet-4", "openai/gpt-4o", "google/gemini-2.5-flash"]


async def test_ask_models_through_one_gateway(rt, monkeypatch):
    class Prov:
        id = "omniroute"
    fake = FakeRouter(["Odpověď 1. Jistota: 80 %", "Odpověď 2. Jistota: 70 %",
                       json.dumps({"agree": ["x"], "disagree": [], "consensus": "Shoda.", "agreement": 90})])
    fake.providers = lambda: [Prov()]
    rt.router = fake

    async def models(rt_, p):
        return ["anthropic/claude-sonnet-4", "openai/gpt-4o"]

    monkeypatch.setattr(thinking, "gateway_models", models)
    d = await thinking.ask_models(rt, "Kolik je 2+2?")
    assert d["compared"] and [a["model"] for a in d["answers"]] == ["anthropic/claude-sonnet-4", "openai/gpt-4o"]
    assert fake.calls[0]["model"] == "anthropic/claude-sonnet-4" and fake.calls[0]["only"] == "omniroute"
