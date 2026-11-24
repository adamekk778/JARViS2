"""3.18 Dílna (C7–C10): STL → OrcaSlicer → Bambu, the pre-print check, richer parts from a description, the finished
print (photo + time-lapse)."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
from conftest import FakeRouter

from jarvis import cad, printcheck, printer3d, timelapse, tools


def _stl(tmp: Path, name: str, tree: dict) -> Path:
    t = cad.expand(tree)
    lo, hi = cad.tree_bounds(t)
    v, f, _ = cad.mesh([], fn=lambda P: cad.tree_sdf(t, P), box=(lo, hi))
    p = tmp / name
    p.write_bytes(cad.stl_bytes(v, f, "x"))
    return p


# ------------------------------------------------------------------------------------------ C8 the pre-print check
def test_check_a_simple_block(tmp_path):
    p = _stl(tmp_path, "kostka.stl", {"box": [40, 30, 10]})
    r = printcheck.analyze(*printcheck.load(p), (256, 256, 256), fast=True)
    assert r["fits"] and r["size_mm"] == pytest.approx([40, 30, 10], abs=0.6)
    assert r["overhang_pct"] < 2 and r["contact_mm2"] > 1000 and r["warnings"] == []
    assert 5 < r["grams"] < 15 and r["minutes"] > 0
    assert "vejde se" in printcheck.lines(r)[0]


def test_check_finds_overhangs_a_small_base_and_a_big_part(tmp_path):
    t = {"union": [{"cylinder": {"r": 3, "h": 20}, "at": [20, 20, 0]}, {"box": [40, 40, 4], "at": [0, 0, 20]}]}
    r = printcheck.analyze(*printcheck.load(_stl(tmp_path, "t.stl", t)))
    assert any("podpory" in w for w in r["warnings"]) and any("brim" in w for w in r["warnings"])
    big = printcheck.analyze(*printcheck.load(_stl(tmp_path, "b.stl", {"box": [300, 20, 10]})), (256, 256, 256))
    assert not big["fits"] and not big["turn_fits"] and "NEVEJDE" in printcheck.lines(big)[0]
    tall = printcheck.analyze(*printcheck.load(_stl(tmp_path, "c.stl", {"box": [20, 240, 100]})), (220, 220, 250))
    assert not tall["fits"] and tall["turn_fits"]


def test_ascii_stl_and_sliced_3mf(tmp_path):
    a = tmp_path / "a.stl"
    a.write_text("solid x\n facet normal 0 0 1\n outer loop\n vertex 0 0 0\n vertex 10 0 0\n vertex 0 10 0\n endloop\n endfacet\nendsolid x\n")
    v, f = printcheck.load(a)
    assert v.shape == (3, 3) and f.shape == (1, 3)
    sliced = tmp_path / "hotovy.gcode.3mf"
    with zipfile.ZipFile(sliced, "w") as z:
        z.writestr("Metadata/plate_1.gcode", "G1")
    assert printcheck.check_file(None, sliced) is None                         # already sliced: nothing to check
    with pytest.raises(ValueError):
        printcheck.read_stl(b"junk" * 30)


async def test_print_tool_refuses_what_does_not_fit_and_shows_the_check(rt, tmp_path):
    tools.load_builtin()
    rt.update_config({"workshop": {"printer": "octoprint", "printer_url": "http://octopi.local"}})
    big = _stl(tmp_path, "velky.stl", {"box": [400, 20, 10]})
    r = await tools.call("printer_control", {"action": "print", "file": str(big)}, rt)
    assert not r.ok and "nevejde" in r.summary
    ok = _stl(tmp_path, "maly.stl", {"box": [20, 20, 5]})
    lines = tools.details_for(tools.REGISTRY["printer_control"], {"action": "print", "file": str(ok)}, rt)
    assert lines and "vejde se" in lines[0] and "filamentu" in lines[1]


# ------------------------------------------------------------------------------------------ C7 STL → Bambu
def test_slice_for_bambu_command(tmp_path, monkeypatch):
    model = tmp_path / "díl.stl"
    model.write_bytes(b"solid")
    monkeypatch.setattr(printer3d, "orca", lambda: None)
    assert "OrcaSlicer" in printer3d.slice_for_bambu(model, "", "")[1]
    monkeypatch.setattr(printer3d, "orca", lambda: "/opt/orca-slicer")
    assert "profily" in printer3d.slice_for_bambu(model, "", "")[1]               # an STL needs the profiles
    m, pr, fi = tmp_path / "m.json", tmp_path / "p.json", tmp_path / "f.json"
    for x in (m, pr, fi):
        x.write_text("{}")
    seen = {}

    class Done:
        returncode, stdout, stderr = 0, "", ""

    def runner(cmd, **kw):
        seen["cmd"] = cmd
        out = Path(cmd[cmd.index("--outputdir") + 1]) / cmd[cmd.index("--export-3mf") + 1]
        out.write_bytes(b"PK")
        return Done()
    out, why = printer3d.slice_for_bambu(model, f"{m};{pr}", str(fi), runner)
    assert why == "" and out.name == "díl.gcode.3mf"
    assert seen["cmd"][:3] == ["/opt/orca-slicer", "--slice", "0"] and f"{m};{pr}" in seen["cmd"] and str(fi) in seen["cmd"]


async def test_bambu_print_slices_an_stl_first(rt, tmp_path, monkeypatch):
    from jarvis import bambu

    tools.load_builtin()
    rt.update_config({"workshop": {"printer": "bambu_lan", "printer_url": "10.0.0.5", "bambu_serial": "01P"}})
    stl = _stl(tmp_path, "drzak.stl", {"box": [30, 20, 10]})
    sent = []
    monkeypatch.setattr(printer3d, "slice_for_bambu", lambda p, s, f, runner=None: (tmp_path / "drzak.gcode.3mf", ""))

    async def upload(rt_, path, start=True, opener=None, ftp_factory=None):
        sent.append(path.name)
        return ""
    monkeypatch.setattr(bambu, "upload_and_print", upload)
    r = await tools.call("printer_control", {"action": "print", "file": str(stl)}, rt)
    assert r.ok and sent == ["drzak.gcode.3mf"]


# ------------------------------------------------------------------------------------------ C9 richer parts
def test_holes_arrays_text_round_and_colours():
    tree = {"difference": [{"box": [80, 30, 6], "round": 2},
                           {"array": {"of": {"hole": {"screw": "M3", "kind": "insert", "h": 8}, "at": [0, 0, -1]},
                                      "n": [3, 1], "step": [30, 0]}, "at": [10, 15, 0]}]}
    assert cad.check_tree(tree) == ""
    e = cad.expand(tree)
    holes = e["difference"][1]["union"]
    assert len(holes) == 3 and holes[0]["union"][0]["cylinder"]["r"] == pytest.approx(2.0)      # M3 insert = 4.0 mm
    pts = np.array([[10, 15, 3], [5, 5, 3]], dtype=np.float32)
    d = cad.tree_sdf(e, pts)
    assert d[0] > 0 and d[1] < 0                                               # in the hole / in the plastic
    assert "minkowski()" in cad.tree_scad(e) and "sphere(r=2" in cad.tree_scad(e)
    assert "screw" in cad.check_tree({"hole": {"screw": "M7", "h": 5}})
    assert "100 kopií" in cad.check_tree({"array": {"of": {"box": [1, 1, 1]}, "n": [11, 10], "step": [2, 2]}})
    assert "háčků" in cad.check_tree({"text": {"text": "Ахой", "size": 5, "depth": 1}})
    assert cad.check_tree({"text": {"text": "Žluťoučký", "size": 5, "depth": 1}}) == ""          # accents folded
    assert "#rrggbb" in cad.check_tree({"box": [1, 1, 1], "color": "red"})
    assert "polovina" in cad.check_tree({"box": [10, 10, 4], "round": 2})
    boxes = cad.text_boxes("I", 7, 1)
    assert len(boxes) == 7 and boxes[0]["box"] == [3, 1, 1]                     # "I": top bar of three pixels


def test_free_part_files_with_colours_and_3mf(rt):
    label = {"union": [{"box": [70, 20, 3], "color": "#ffffff"},
                       {"text": {"text": "JARVIS", "size": 10, "depth": 1.5}, "at": [5, 5, 3], "color": "#ff0000"}]}
    f = cad.free_files({"name": "Štítek", "version": 1, "params": {"tree": label}})
    assert f["3mf"].endswith(".3mf") and f["closed"]
    with zipfile.ZipFile(f["3mf"]) as z:
        model = z.read("3D/3dmodel.model").decode()
    assert model.count("<object ") == 2 and 'displaycolor="#FF0000FF"' in model and 'unit="millimeter"' in model
    v, fc = printcheck.read_3mf(Path(f["3mf"]).read_bytes())
    assert len(fc) > 1000


async def test_ai_part_with_new_nodes(rt):
    tools.load_builtin()
    plate = {"name": "Montážní deska", "tree": {"difference": [
        {"box": [60, 40, 4], "round": 1},
        {"array": {"of": {"hole": {"screw": "M4", "kind": "clear", "h": 6}, "at": [0, 0, -1]}, "n": [2, 2], "step": [40, 20]},
         "at": [10, 10, 0]}]}}
    rt.router = FakeRouter([json.dumps(plate)])
    r = await tools.call("cad_part", {"action": "design", "description": "montážní deska se 4 dírami na M4"}, rt)
    assert r.ok and "Montážní deska" in r.summary and len(r.attachments) == 3       # scad, stl, 3mf
    assert "round" in rt.router.calls[0]["messages"][0]["content"]                 # the AI was told about the new nodes


# ------------------------------------------------------------------------------------------ C10 the finished print
async def test_finished_print_photo_timelapse_and_notice(rt, monkeypatch):
    from PIL import Image

    def jpg(i: int) -> bytes:
        b = io.BytesIO()
        Image.new("RGB", (320, 240), (i * 30 % 255, 90, 160)).save(b, "JPEG")
        return b.getvalue()
    shots = iter(jpg(i) for i in range(20))

    async def snap(rt_, client=None):
        return next(shots)
    monkeypatch.setattr(printer3d, "snapshot", snap)
    states = iter([{"state": "printing", "file": "Držák v2", "progress": 50}] * 4 + [{"state": "done", "file": "Držák v2"}])

    async def status(rt_, client=None):
        return next(states)
    monkeypatch.setattr(printer3d, "status", status)
    rt.update_config({"workshop": {"printer": "octoprint", "printer_url": "http://x", "watch": False, "timelapse_every_min": 1}})
    said, events = [], []
    rt.notify = lambda title, body, **kw: said.append(body)
    q = rt.bus.subscribe()
    w = printer3d.Watch(rt)
    for i in range(5):
        await w.step(1000.0 + i * 61)
    while not q.empty():
        events.append(q.get_nowait())
    done = [e for e in events if e["type"] == "printer_done"]
    assert done and done[0]["video"].endswith(".mp4") and Path(done[0]["video"]).stat().st_size > 500
    assert said and "hotový" in said[-1] and "časosběrné video" in said[-1]
    assert not timelapse.folder("Držák v2").exists() or not list(timelapse.folder("Držák v2").glob("f-*.jpg"))
