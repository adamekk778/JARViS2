"""Wave F2: automation versions + rollback (150) and dry run (149), smart names for photos / videos / music (320),
disk errors before crashes (291), the service dependency tree (294), OBJ / 3MF models (775), lip sync by sounds (668)."""
import datetime as dt
import os
import zipfile

import numpy as np

from jarvis import creative, rescue, science, skillforge, tools

tools.load_builtin()

AUTO = {"id": "a1", "name": "Spotify potichu", "enabled": True, "trigger": {"type": "app_open", "value": "spotify", "text": "", "days": []},
        "steps": [{"say": "Píše {sender}"}]}


def test_automation_versions_and_rollback(rt):
    rt.update_config({"automations": {"items": [AUTO]}})
    rt.update_config({"automations": {"items": [{**AUTO, "name": "Spotify tiše"}]}})
    h = skillforge.history(rt, "auto:a1")
    assert [v["version"] for v in h] == [2, 1] and h[0]["protocol"]["name"] == "Spotify tiše"
    rt.update_config({"automations": {"items": [{**AUTO, "name": "Spotify tiše"}]}})        # no change → no new version
    assert len(skillforge.history(rt, "auto:a1")) == 2
    skillforge.rollback(rt, "auto:a1", 1)
    assert rt.cfg.automations.items[0].name == "Spotify potichu"
    assert skillforge.history(rt, "auto:a1")[0]["note"].startswith("návrat")


def test_automation_test_vars_fill():
    from jarvis.automations import TEST_VARS, fill

    assert fill("Píše {sender}: {subject}", TEST_VARS) == "Píše Test: Zkouška"


def test_media_smart_names(tmp_path):
    from PIL import Image

    from jarvis import fileuniverse as fu

    img = Image.new("RGB", (8, 8))
    ex = img.getexif()
    ex[271], ex[272], ex[306] = "Apple", "iPhone 13", "2026:06:14 14:03:22"
    p = tmp_path / "IMG_0001.jpg"
    img.save(p, exif=ex)
    assert fu.smart_name(p) == "Foto_2026-06-14_14-03_Apple-iPhone-13.jpg"
    v = tmp_path / "VID_1.mp4"
    v.write_bytes(b"\0" * 10)
    os.utime(v, (dt.datetime(2025, 1, 2, 3, 4).timestamp(),) * 2)
    assert fu.smart_name(v) == "Video_2025-01-02_03-04.mp4"
    d = tmp_path / "scan.txt"
    d.write_text("Faktura č. 5\nDatum: 3. 10. 2026\nAlza.cz a.s.", encoding="utf-8")
    assert fu.smart_name(d).startswith("Faktura_2026-10-03")


def test_disk_errors_before_crash():
    io = [{"Time": "2026-10-01T10:00:00"}, {"Time": "2026-10-01T10:08:00"}, {"Time": "2026-09-01T00:00:00"}]
    crashes = [{"Id": 41, "Time": "2026-10-01T10:10:00"}, {"Id": 41, "Time": "2026-10-05T10:00:00"}]
    links = rescue.disk_crash_links(io, crashes)
    assert links == [{"crash": "2026-10-01T10:10:00", "errors": 2, "minutes": 15}]
    f = rescue._an_disks({"io_events": [{"Id": 7, **io[0]}], "crash_times": crashes})
    assert any("Pád systému" in x["text"] for x in f)


def test_service_dependency_tree():
    deps = [{"Name": "Spooler", "Display": "Zařazování tisku", "Needs": [{"Name": "RPCSS", "Display": "RPC", "Status": "Running"},
                                                                     {"Name": "HTTP", "Display": "HTTP", "Status": "Stopped"}],
             "Waiting": [{"Name": "Fax", "Display": "Fax", "Status": "Stopped"}]}]
    t = rescue.service_tree(deps)[0]
    assert t["blocked_by"] == ["HTTP"] and t["affects"] == ["Fax"]
    f = rescue._an_services({"deps": deps})
    assert any("protože nejede" in x["text"] for x in f) and any("čeká" in x["text"] for x in f)
    assert "Get-Service" in rescue.ALLOWED and rescue.cmdlets(rescue.PROBES["services"]["script"]) <= rescue.ALLOWED
    assert rescue.cmdlets(rescue.PROBES["disks"]["script"]) <= rescue.ALLOWED


CUBE_V = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10)]
CUBE_Q = [(1, 4, 3, 2), (5, 6, 7, 8), (1, 2, 6, 5), (2, 3, 7, 6), (3, 4, 8, 7), (4, 1, 5, 8)]


def test_obj_and_3mf_models(tmp_path):
    obj = tmp_path / "kostka.obj"
    obj.write_text("\n".join([f"v {x} {y} {z}" for x, y, z in CUBE_V] + [f"f {a}/1 {b}/1 {c}/1 {d}/1" for a, b, c, d in CUBE_Q]))
    r = science.inspect_stl(obj)
    assert r["triangles"] == 12 and abs(r["volume_cm3"] - 1.0) < 1e-6
    tris = "".join(f'<triangle v1="{a - 1}" v2="{b - 1}" v3="{c - 1}"/><triangle v1="{a - 1}" v2="{c - 1}" v3="{d - 1}"/>' for a, b, c, d in CUBE_Q)
    verts = "".join(f'<vertex x="{x / 10}" y="{y / 10}" z="{z / 10}"/>' for x, y, z in CUBE_V)
    model = ('<?xml version="1.0"?><model unit="centimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<resources><object id="1" type="model"><mesh><vertices>{verts}</vertices><triangles>{tris}</triangles></mesh></object></resources></model>')
    m3 = tmp_path / "kostka.3mf"
    with zipfile.ZipFile(m3, "w") as z:
        z.writestr("3D/3dmodel.model", model)
    r2 = science.inspect_stl(m3)
    assert r2["triangles"] == 12 and abs(r2["volume_cm3"] - 1.0) < 1e-6 and [round(v) for v in r2["size_mm"]] == [10, 10, 10]
    step = tmp_path / "dil.step"
    step.write_text("ISO-10303-21;")
    try:
        science.read_mesh(step)
        raise AssertionError("STEP should be refused")
    except ValueError as e:
        assert "STL" in str(e)


def test_czech_visemes_and_text_lipsync():
    assert creative.czech_visemes("máma") == [["MBP", "AI", "MBP", "AI"]]
    assert creative.czech_visemes("Ahoj, vole!") == [["AI", "etc", "O", "etc"], ["FV", "O", "L", "E"]]
    rate = 16000
    t = np.arange(rate * 2) / rate
    x = np.where((t > 0.2) & (t < 1.6), np.sin(2 * np.pi * 200 * t), 0.0).astype(np.float32) * 0.5
    r = creative.lipsync_text(x, rate, "máma volá", 24)
    shapes = {k["mouth"] for k in r["keys"]}
    assert {"MBP", "AI", "rest"} <= shapes and r["words"] == 2
    assert r["moho"].startswith("MohoSwitch1\n1 rest")
    assert r["keys"][-1]["mouth"] == "rest" or r["frames"] > 0
