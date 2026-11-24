"""3.15 Dílna (sekce C) a gesta: text → CAD, model v HUD, 3D tiskárna s hlídáním, deník projektů, simulace."""
from __future__ import annotations

import json
import math
import struct

import httpx
import numpy as np
import pytest

from jarvis import cad, models3d, printer3d, sims, tools, workbench


def _bus(rt):
    sent = []
    rt.bus.publish = lambda t, **d: sent.append((t, d))
    return sent


# ------------------------------------------------------------------------------------------ CAD
def _closed(faces: np.ndarray) -> bool:
    e = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    _, c = np.unique(e, axis=0, return_counts=True)
    return bool((c == 2).all())


@pytest.mark.parametrize("tpl", list(cad.TEMPLATES))
def test_every_template_makes_a_closed_outward_mesh(tpl):
    prims = cad.build(tpl, cad.TEMPLATES[tpl]["params"])
    v, f, step = cad.mesh(prims, feature=2)
    assert len(f) > 100 and _closed(f)
    assert cad.volume(v, f) > 0                                   # normals point out
    assert "translate(" in cad.scad(prims, tpl)


def test_mesh_volume_is_close_to_the_real_one():
    v, f, _ = cad.mesh([cad._box(0, 0, 0, 20, 20, 20)])
    assert abs(cad.volume(v, f) - 8000) < 80
    tube = [cad._cyl(5, 5, 0, 5, 10), cad._cyl(5, 5, -1, 2, 12, cut=True)]
    v, f, _ = cad.mesh(tube)
    assert abs(cad.volume(v, f) - math.pi * (25 - 4) * 10) / (math.pi * 21 * 10) < 0.06


def test_stl_bytes_are_a_valid_binary_stl():
    v, f, _ = cad.mesh([cad._box(0, 0, 0, 5, 5, 5)])
    data = cad.stl_bytes(v, f, "test")
    n = struct.unpack("<I", data[80:84])[0]
    assert n == len(f) and len(data) == 84 + 50 * n


@pytest.mark.parametrize("text,tpl,want", [
    ("o 5 mm širší", "bracket", {"w": 45}),
    ("udělej ho o 1 cm vyšší a stěna 3 mm", "box", {"h": 40, "t": 3}),
    ("díry 5 mm", "plate", {"hole": 5}),
    ("6 děr", "plate", {"holes": 6}),
    ("na šrouby M3", "bracket", {"hole": 3.4}),
    ("bez víka", "box", {"lid": 0}),
    ("šířka 100, hloubka 60", "plate", {"w": 100, "d": 60}),
    ("tenčí stěna o 0,5 mm", "box", {"t": 1.5}),
    ("průměr 12 a výška 20", "spacer", {"od": 12, "h": 20}),
    ("o 10 % větší", "box", {"w": 66, "d": 44, "h": 33}),
])
def test_voice_edits(text, tpl, want):
    p, changes = cad.parse_edit(text, tpl, dict(cad.TEMPLATES[tpl]["params"]))
    assert changes
    for k, v in want.items():
        assert p[k] == pytest.approx(v)


def test_nonsense_changes_nothing_and_bad_sizes_are_refused():
    assert cad.parse_edit("ahoj jak se máš", "box", dict(cad.TEMPLATES["box"]["params"]))[1] == []
    assert "stěna" in cad.check("box", {**cad.TEMPLATES["box"]["params"], "t": 0.4})
    assert cad.check("spacer", {"od": 5, "id": 5, "h": 10})
    assert cad.check("box", cad.TEMPLATES["box"]["params"]) == ""
    assert cad.guess_template("L-držák na polici") == "bracket" and cad.guess_template("distanční sloupek M3") == "spacer"


async def test_cad_tool_create_edit_undo(rt):
    tools.load_builtin()
    sent = _bus(rt)
    r = await tools.call("cad_part", {"action": "create", "description": "L-držák 50 mm široký na šrouby M4", "name": "Držák police"}, rt)
    assert r.ok and r.data["params"]["w"] == 50 and r.data["params"]["hole"] == 4.5 and r.data["version"] == 1
    assert any(t == "hud_model" and d["format"] == "stl" for t, d in sent) and len(r.attachments) == 2
    r = await tools.call("cad_part", {"action": "edit", "description": "o 5 mm širší"}, rt)
    assert r.ok and r.data["params"]["w"] == 55 and r.data["version"] == 2
    r = await tools.call("cad_part", {"action": "edit", "description": "stěna 0,3 mm"}, rt)
    assert not r.ok and cad.get(rt, "Držák police")["params"]["t"] == 4                  # refused, unchanged
    r = await tools.call("cad_part", {"action": "undo"}, rt)
    assert r.ok and r.data["params"]["w"] == 50 and r.data["version"] == 3                # back, as a new version
    assert [h["version"] for h in cad.history(rt, "Držák police")] == [1, 2, 3]
    r = await tools.call("cad_part", {"action": "edit", "description": "uvař kafe"}, rt)
    assert not r.ok and "šířka" in r.summary
    files = cad.export(rt, cad.get(rt, "Držák police"))
    assert files["scad"].endswith(".scad") and files["exact"] is False and files["grams_pla"] > 0


# ------------------------------------------------------------------------------------------ the model library
def test_model_library_only_serves_its_own_files(tmp_path):
    src = tmp_path / "Držák v2.stl"
    v, f, _ = cad.mesh([cad._box(0, 0, 0, 5, 5, 5)])
    src.write_bytes(cad.stl_bytes(v, f))
    info = models3d.add(src)
    assert info["format"] == "stl" and info["url"].startswith("/api/workshop/model/drzak-v2-")
    assert models3d.path_of(info["name"]) is not None
    for bad in ("../secrets.stl", "x/../../a.stl", "A.STL", "evil.html", "", "a.stl\x00.png"):
        assert models3d.path_of(bad) is None
    assert "error" in models3d.add(tmp_path / "nope.stl")
    (tmp_path / "x.txt").write_text("x")
    assert "error" in models3d.add(tmp_path / "x.txt")


def test_step_needs_freecad_and_converts_with_it(tmp_path, monkeypatch):
    import functools
    from pathlib import Path

    step = tmp_path / "sestava.step"
    step.write_text("ISO-10303-21;")
    monkeypatch.setattr(models3d, "freecad", lambda: None)
    assert "FreeCAD" in models3d.add(step)["error"]
    monkeypatch.setattr(models3d, "freecad", lambda: "/usr/bin/freecadcmd")
    seen = {}

    class Done:
        returncode, stdout, stderr = 0, "", ""

    def runner(cmd, **kw):                           # FreeCAD runs our script with the paths in the environment
        seen["script"] = Path(cmd[1]).read_text()
        Path(kw["env"]["JARVIS_OBJ_OUT"]).write_text("o dil_1\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        return Done()
    monkeypatch.setattr(models3d, "step_to_obj", functools.partial(models3d.step_to_obj, runner=runner))
    info = models3d.add(step)
    assert info["format"] == "obj" and info["name"].endswith(".obj") and "Part.read" in seen["script"]


async def test_model_endpoint(rt, tmp_path):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    src = tmp_path / "kryt.stl"
    v, f, _ = cad.mesh([cad._box(0, 0, 0, 5, 5, 5)])
    src.write_bytes(cad.stl_bytes(v, f))
    info = models3d.add(src)
    client = TestClient(create_app(rt, manage_runtime=False))
    ok = {"Authorization": f"Bearer {rt.cfg.phone.token}", "host": "192.168.1.5:8765"}
    r = client.get(f"/api/workshop/model/{info['name']}", headers=ok)
    assert r.status_code == 200 and r.content[:4] == src.read_bytes()[:4]
    assert client.get("/api/workshop/model/..%2F..%2Fconfig.toml", headers=ok).status_code == 404
    assert client.get("/api/workshop/model/nic.stl", headers=ok).status_code == 404
    hdr = {"host": "192.168.1.5:8765"}
    assert client.get(f"/api/workshop/model/{info['name']}", headers=hdr).status_code == 401      # from the network: the token


# ------------------------------------------------------------------------------------------ the printer
def test_status_parsers():
    s = printer3d.from_octoprint({"state": "Printing", "job": {"file": {"name": "kryt.gcode"}},
                                  "progress": {"completion": 41.6, "printTimeLeft": 3720, "printTime": 1800}},
                                 {"temperature": {"tool0": {"actual": 214.8, "target": 215}, "bed": {"actual": 60, "target": 60}}})
    assert s["state"] == "printing" and s["progress"] == 41.6 and s["nozzle"] == [214.8, 215.0]
    assert "zbývá 1 h 2 min" in printer3d.say(s, "Prusa")
    m = printer3d.from_moonraker({"print_stats": {"state": "paused", "filename": "a.gcode", "print_duration": 600},
                                  "virtual_sdcard": {"progress": 0.25}, "extruder": {"temperature": 200, "target": 0}})
    assert m["state"] == "paused" and m["progress"] == 25 and m["left_s"] == 1800
    ent = printer3d._bambu_entities([{"entity_id": "sensor.p1s_123_print_progress", "state": "70"},
                                     {"entity_id": "sensor.p1s_123_print_status", "state": "running"},
                                     {"entity_id": "sensor.p1s_123_remaining_time", "state": "35"},
                                     {"entity_id": "button.p1s_123_pause_printing", "state": "unknown"},
                                     {"entity_id": "light.kuchyn", "state": "on"}], "")
    b = printer3d.from_bambu(ent)
    assert b["state"] == "printing" and b["progress"] == 70 and b["left_s"] == 2100 and "button.pause_printing" in ent
    assert printer3d.from_bambu({})["state"] == "offline"


async def test_octoprint_and_moonraker_over_http(rt):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path, req.content[:200]))
        if req.url.path == "/api/job" and req.method == "GET":
            return httpx.Response(200, json={"state": "Printing", "progress": {"completion": 10}})
        if req.url.path == "/api/printer":
            return httpx.Response(200, json={"temperature": {}})
        if req.url.path.startswith("/printer/objects/query"):
            return httpx.Response(200, json={"result": {"status": {"print_stats": {"state": "printing"}, "virtual_sdcard": {"progress": 0.5}}}})
        return httpx.Response(204)
    cl = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    rt.update_config({"workshop": {"printer": "octoprint", "printer_url": "http://octopi.local"}})
    assert (await printer3d.status(rt, cl))["progress"] == 10
    assert await printer3d.command(rt, "pause", cl) == ""
    assert json.loads(calls[-1][2]) == {"command": "pause", "action": "pause"}
    assert await printer3d.command(rt, "cancel", cl) == "" and json.loads(calls[-1][2]) == {"command": "cancel"}
    rt.update_config({"workshop": {"printer": "moonraker", "printer_url": "http://mainsail.local:7125"}})
    assert (await printer3d.status(rt, cl))["progress"] == 50
    assert await printer3d.command(rt, "resume", cl) == "" and calls[-1][1] == "/printer/print/resume"
    assert await printer3d.command(rt, "explode", cl) == "neznámý příkaz"


async def test_failed_print_watch_pauses_after_two_bad_looks(rt, monkeypatch):
    rt.update_config({"workshop": {"printer": "octoprint", "printer_url": "http://x", "watch_every_min": 1}})
    notes, cmds = [], []
    rt.notify = lambda title, body, **k: notes.append((title, body, k))
    state = {"s": {"state": "printing", "file": "kryt.gcode", "progress": 30}}

    async def fake_status(rt_, client=None):
        return dict(state["s"])

    async def fake_snapshot(rt_, client=None):
        return b"\xff\xd8jpeg"

    async def fake_judge(rt_, jpg):
        return {"fail": True, "kind": "spaghetti", "confidence": 0.9, "why": "chuchvalce vlákna"}

    async def fake_command(rt_, a, client=None):
        cmds.append(a)
        return ""
    monkeypatch.setattr(printer3d, "status", fake_status)
    monkeypatch.setattr(printer3d, "snapshot", fake_snapshot)
    monkeypatch.setattr(printer3d, "judge", fake_judge)
    monkeypatch.setattr(printer3d, "command", fake_command)
    w = printer3d.Watch(rt)
    await w.step(1000.0)
    assert cmds == [] and w.strikes == 1                      # one bad look is not enough
    await w.step(1030.0)
    assert cmds == [] and w.strikes == 1                      # within the interval: no new look
    await w.step(1070.0)
    assert cmds == ["pause"] and notes and "špagety" in notes[-1][1] and "Pozastavil" in notes[-1][1]
    assert [a["label"] for a in notes[-1][2]["actions"]] == ["Pokračovat", "Zrušit tisk"]
    state["s"] = {"state": "done", "file": "kryt.gcode", "progress": 100}
    await w.step(1200.0)
    assert "hotový" in notes[-1][1] and w.strikes == 0


def test_verdict_parsing():
    assert printer3d.parse_verdict('Tady: {"fail": true, "kind": "odlepení", "confidence": 0.8, "why": "roh nahoře"}')["fail"]
    v = printer3d.parse_verdict("nevím")
    assert v["fail"] is False and v["confidence"] == 0
    assert printer3d.parse_verdict('{"fail": false, "confidence": "hodně"}')["confidence"] == 0


async def test_printer_tool_and_notice_button(rt, monkeypatch):
    tools.load_builtin()
    r = await tools.call("printer_control", {"action": "status"}, rt)
    assert not r.ok and "Nastavení → Dílna" in r.summary
    assert tools.is_dangerous(tools.REGISTRY["printer_control"], {"action": "cancel"}, ctx=rt)
    assert not tools.is_dangerous(tools.REGISTRY["printer_control"], {"action": "status"}, ctx=rt)
    got = []

    async def fake_command(rt_, a, client=None):
        got.append(a)
        return ""
    monkeypatch.setattr(printer3d, "command", fake_command)
    ok, text = await rt.notice_action("printer", {"action": "resume"})
    assert ok and got == ["resume"] and "pokračuje" in text


# ------------------------------------------------------------------------------------------ the project journal
async def test_project_journal_and_shopping_list(rt, tmp_path):
    from jarvis.tools import list_tools

    p = workbench.create(rt, "Meteostanice", "měřit teplotu na zahradě")
    assert workbench.find(rt, "meteostanice")["id"] == p["id"] and workbench.find(rt)["id"] == p["id"]
    items = workbench.parse_parts("2× BME280 za 150 Kč, ESP32, 3 m kabelu, 10 ks šroubů M3")
    assert [(i["part"], i["qty"], i["unit"], i["price"]) for i in items] == [
        ("BME280", 2, "ks", 150), ("ESP32", 1, "ks", 0), ("kabelu", 3, "m", 0), ("šroubů M3", 10, "ks", 0)]
    workbench.add_parts(rt, p, items)
    workbench.add_parts(rt, p, workbench.parse_parts("1× BME280"))                       # merged, not a second line
    assert next(x for x in workbench.parts(rt, p) if x["part"] == "BME280")["qty"] == 3
    assert workbench.mark_have(rt, p, ["esp32"]) == ["ESP32"]
    assert {m["part"] for m in workbench.missing(rt, p)} == {"BME280", "kabelu", "šroubů M3"}
    added = workbench.to_shopping(rt, p)
    assert len(added) == 3 and any("BME280" in x for x in list_tools.all_lists(rt)["dílna"])
    photo = tmp_path / "pajeni.jpg"
    photo.write_bytes(b"\xff\xd8x")
    e = workbench.add_entry(rt, p, "photo", "Pájení", photo)
    assert e["path"] and e["path"] != str(photo)
    assert workbench.set_status(rt, p, "testování") == "testování" and workbench.set_status(rt, p, "blbost") == ""
    assert workbench.new_version(rt, p, "minor") == "0.2.0"
    o = workbench.overview(rt, workbench.find(rt, "Meteostanice"))
    assert o["status"] == "testování" and o["photos"] and o["bom"]["to_buy_czk"] == 450
    workbench.log_active(rt, "print", "Vytištěno: kryt.gcode")
    assert workbench.timeline(rt, p)[0]["text"] == "Vytištěno: kryt.gcode"


async def test_project_tool(rt):
    tools.load_builtin()
    r = await tools.call("workshop_project", {"action": "create", "project": "Robotické rameno", "text": "4 osy"}, rt)
    assert r.ok
    r = await tools.call("workshop_project", {"action": "parts", "text": "4× servo MG996R za 120 Kč, Arduino Nano"}, rt)
    assert r.ok and "480" in r.summary
    r = await tools.call("workshop_project", {"action": "missing"}, rt)
    assert "servo" in r.summary
    r = await tools.call("workshop_project", {"action": "show", "project": "rameno"}, rt)
    assert r.ok and "Robotické rameno" in r.summary


# ------------------------------------------------------------------------------------------ simulations
def test_beam_matches_the_textbook():
    b = sims.beam(500, 100, "konzola", material="ocel", profile="plný čtverec", size_mm=20)
    I = 20 ** 4 / 12
    assert b["max_deflection_mm"] == pytest.approx(100 * 500 ** 3 / (3 * 210000 * I), rel=1e-3)
    assert b["max_stress_mpa"] == pytest.approx(100 * 500 * 10 / I, rel=1e-3) and "<polyline" in b["svg"]
    u = sims.beam(1000, 1000, "prostý nosník", distributed=True, size_mm=20)
    assert u["max_deflection_mm"] == pytest.approx(5 * 1 * 1000 ** 4 / (384 * 210000 * I), rel=1e-3)
    with pytest.raises(ValueError):
        sims.beam(0, 10)


def test_heat_balance_and_hot_spot():
    r = sims.heat_plate(100, 60, 5, at=(30, 30), material="hliník", thickness_mm=2, edges_fixed=False)
    assert 2 * 10 * (r["mean_c"] - 25) * 0.1 * 0.06 == pytest.approx(5, rel=0.03)       # what goes in goes out
    assert abs(r["hot_mm"][0] - 30) < 6 and "<rect" in r["svg"]
    assert sims.heat_plate(100, 60, 5, material="FR4", thickness_mm=1.6)["max_c"] > r["max_c"]   # FR4 spreads heat badly


def test_dc_circuit_and_transients():
    d = sims.dc("V1 vcc 0 5; R1 vcc out 10k; R2 out 0 4k7")
    assert d["nodes"]["out"] == pytest.approx(5 * 4.7 / 14.7, abs=1e-3)
    assert sims.dc("V1 a 0 12; R1 a 0 100")["too_hot"]
    assert sims.dc("I1 0 a 10m; R1 a 0 1k")["nodes"]["a"] == pytest.approx(10)
    with pytest.raises(ValueError):
        sims.dc("V1 a 0 5; R1 b c 1k")                        # b–c floats: no way to solve it
    with pytest.raises(ValueError):
        sims.dc("Q1 a 0 5")
    t = sims.transient("rc", 10e3, 100e-6, 5)
    assert t["tau_s"] == pytest.approx(1.0) and t["final"] == pytest.approx(5 * (1 - math.exp(-5)), rel=1e-3)
    assert sims.value("4k7") == 4700 and sims.value("2.2u") == pytest.approx(2.2e-6) and sims.value("1M") == 1e6


async def test_simulate_tool(rt):
    tools.load_builtin()
    r = await tools.call("simulate", {"kind": "beam", "length_mm": 1000, "load_n": 300, "support": "prostý nosník", "size_mm": 15}, rt)
    assert r.ok and "průhyb" in r.summary and len(r.attachments) == 2
    r = await tools.call("simulate", {"kind": "circuit", "netlist": "V1 a 0 5; R1 a b 1k; R2 b 0 1k"}, rt)
    assert r.ok and "b 2,5 V" in r.summary
    r = await tools.call("simulate", {"kind": "heat", "width_mm": 40, "height_mm": 40, "power_w": 4, "material": "FR4", "thickness_mm": 1.6}, rt)
    assert r.ok and "moc" in r.summary
    r = await tools.call("simulate", {"kind": "rc", "r": "10k", "c_or_l": "100u"}, rt)
    assert r.ok and "τ = 1" in r.summary
    assert not (await tools.call("simulate", {"kind": "circuit", "netlist": "R1 a"}, rt)).ok


# ------------------------------------------------------------------------------------------ gestures + HUD presence
async def test_hud_presence_and_gestures(rt):
    from jarvis.server.handlers.workshop import hud_gesture, hud_presence, printer_get

    sent, replies = _bus(rt), []

    class C:
        pass
    c = C()
    c.rt = rt

    async def send(t, **d):
        replies.append((t, d))
    c.send = send
    await hud_presence(c, {"visible": True})
    assert rt.hud_on_screen > 0 and ("hud_presence", {"on": True}) in sent
    await hud_gesture(c, {"g": "wave"})
    await hud_gesture(c, {"g": "<script>"})
    assert [d for t, d in sent if t == "hud_cmd"] == [{"action": "gesture", "gesture": "wave"}]
    await printer_get(c, {})
    assert replies == [("printer", {"state": "off", "name": ""})]
    from jarvis.server import ws

    assert {"hud_presence", "hud_gesture", "printer_get"} <= set(ws.CLIENT_TYPES)
    assert {"hud_model", "printer", "printer_look", "hud_presence"} <= set(ws.SERVER_TYPES)


async def test_model_explode_tool(rt):
    tools.load_builtin()
    sent = _bus(rt)
    r = await tools.call("model_explode", {"action": "explode"}, rt)
    assert r.ok and ("hud_cmd", {"action": "model_explode"}) in sent
    assert not (await tools.call("model_explode", {"action": "fly"}, rt)).ok


def test_firmware_build_lands_in_the_active_project(rt):
    from jarvis import hwlab

    p = workbench.create(rt, "Meteostanice")
    hwlab.record_build(rt, "meteo-fw", "upload", True, "0.3.0", {}, "ok")
    hwlab.record_build(rt, "meteo-fw", "build", False, "0.3.1", {}, "chybí knihovna Adafruit_BME280")
    texts = [e["text"] for e in workbench.timeline(rt, p)]
    assert "Nahráno do desky: meteo-fw v0.3.0" in texts and any("chybí knihovna" in t for t in texts)
