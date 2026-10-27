"""Wave 35: the hardware lab."""
import math
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from jarvis import hwlab, tools


def test_boards_by_usb_id():
    assert hwlab.identify({"vid": "2341", "pid": "0043"})["fqbn"] == "arduino:avr:uno"
    esp = hwlab.identify({"vid": "10C4", "pid": "EA60"})
    assert "CP2102" in esp["board"] and not esp["sure"] and esp["fqbn"] == ""
    assert hwlab.identify({"vid": "303a", "pid": "1001"})["fqbn"].startswith("esp32:")
    assert hwlab.identify({"vid": "", "pid": ""})["board"] == ""


ERR = """sketch.ino:12:5: error: 'ledPin' was not declared in this scope
sketch.ino:3:10: fatal error: DHT.h: No such file or directory
Sketch uses 3456 bytes (10%) of program storage space. Maximum is 32256 bytes.
Global variables use 210 bytes (10%) of dynamic memory"""


def test_build_errors_explained():
    r = hwlab.explain_build(ERR)
    assert any("DHT.h" in h for h in r["hints"]) and any("ledPin" in h for h in r["hints"])
    assert r["errors"][0] == {"file": "sketch.ino", "line": 12, "message": "'ledPin' was not declared in this scope"}
    assert r["flash"] == {"bytes": 3456, "percent": 10, "max": 32256} and r["ram"]["percent"] == 10
    assert "BOOT" in hwlab.explain_build("A fatal error occurred: Failed to connect to ESP32")["hints"][0]


def test_firmware_projects(rt, tmp_path, monkeypatch):
    sk = tmp_path / "blik"
    sk.mkdir()
    (sk / "blik.ino").write_text("void setup(){} void loop(){}")
    hwlab.add_project(rt, "Blikač", str(sk), "arduino:avr:uno", "COM5")
    monkeypatch.setattr(hwlab, "arduino_cli", lambda: "/usr/bin/arduino-cli")
    calls = []

    def runner(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0 if "--upload" not in args else 1,
                                           stdout="Sketch uses 900 bytes (2%) of program storage space. Maximum is 32256 bytes.\n"
                                                  "Global variables use 9 bytes (0%) of dynamic memory",
                                           stderr="" if "--upload" not in args else "avrdude: stk500_recv(): programmer is not responding\navrdude: stk500_getsync() attempt 1 of 10: not in sync")
    ok = hwlab.build_project(rt, "blikač", runner=runner)
    assert ok["ok"] and ok["flash"]["percent"] == 2 and calls[0][1:4] == ["compile", "--fqbn", "arduino:avr:uno"]
    bad = hwlab.build_project(rt, "Blikač", upload=True, runner=runner)
    assert not bad["ok"] and "neodpovídá" in bad["summary"] and calls[1][-3:] == ["--upload", "-p", "COM5"]
    p = hwlab.get_project(rt, "blikač")
    assert [b["action"] for b in p["builds"]] == ["upload", "build"] and p["builds"][1]["flash"] == 900
    assert hwlab.bump("1.2.3") == "1.2.4" and hwlab.bump("1.2.3", "minor") == "1.3.0" and hwlab.bump("x", "major") == "1.0.0"
    with pytest.raises(KeyError):
        hwlab.build_project(rt, "neznámý", runner=runner)


def test_missing_cli_is_explained(rt, tmp_path, monkeypatch):
    monkeypatch.setattr(hwlab, "arduino_cli", lambda: None)
    hwlab.add_project(rt, "x", str(tmp_path), "arduino:avr:uno")
    with pytest.raises(FileNotFoundError) as e:
        hwlab.build_project(rt, "x")
    assert "nestahuje" in str(e.value)


async def test_upload_and_flash_ask_first():
    assert tools.REGISTRY["firmware_upload"].danger and tools.REGISTRY["flash_esp32"].danger
    assert not tools.REGISTRY["firmware_build"].danger


def test_flash_esp_checks_input(tmp_path, monkeypatch):
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda n: object())
    fw = tmp_path / "fw.bin"
    fw.write_bytes(b"\xe9" * 100)
    with pytest.raises(ValueError):
        hwlab.flash_esp("COM3", fw, "0x0; rm -rf /", runner=None)
    with pytest.raises(ValueError):
        hwlab.flash_esp("COM3", tmp_path / "fw.txt", "0x0", runner=None)
    seen = {}

    def runner(args, **kw):
        seen["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="Hash of data verified.", stderr="")
    assert hwlab.flash_esp("COM3", fw, "0x10000", runner=runner)["ok"]
    assert seen["args"][-3:] == ["write_flash", "0x10000", str(fw)] and seen["args"][-4] == "COM3"


def test_raspberry_pi():
    devs = [{"ip": "192.168.1.5", "mac": "DC-A6-32-11-22-33"}, {"ip": "192.168.1.6", "mac": "00:11:22:33:44:55"}]
    assert [d["ip"] for d in hwlab.find_pis(devs)] == ["192.168.1.5"]
    st = hwlab.parse_pi_status("up 3 days, 2 hours\ntemp=82.3'C\n/dev/root  29G  27G  1.0G  95% /\nMem:  3790  1200  2000")
    assert st["uptime"] == "3 days, 2 hours" and st["temp_c"] == 82.3 and st["disk"]["percent"] == 95 and st["ram_mb"]["used"] == 1200
    assert len(st["warnings"]) == 2
    assert hwlab.parse_pi_status("54321")["temp_c"] == 54.3
    with pytest.raises(ValueError):
        hwlab.pi_status("host; rm -rf /")


def test_schematic():
    w = hwlab.parse_wiring("Arduino.D9 -> R1.1; R1.2 -> LED1.A\nLED1.K -> GND; Arduino.GND -> GND")
    assert set(w["components"]) == {"Arduino", "R1", "LED1"}
    nets = {n["name"]: n["pins"] for n in w["nets"]}
    assert nets["GND"] == ["Arduino.GND", "LED1.K"]
    assert ["Arduino.D9", "R1.1"] in nets.values() and ["LED1.A", "R1.2"] in nets.values()
    svg = hwlab.schematic_svg(w)
    assert svg.startswith("<svg") and svg.count("<rect") == 4 and "LED1" in svg
    net = hwlab.kicad_netlist(w)
    assert '(net (code "1")' in net and '(node (ref "LED1") (pin "K"))' in net
    assert hwlab.parse_wiring("nic tu není")["nets"] == []


def test_pcb_helpers():
    t = hwlab.trace_width(1.0, 10, 1, True)
    assert 0.25 < t["width_mm"] < 0.35                      # ~12 mil for 1 A on an outer layer
    assert hwlab.trace_width(1.0, 10, 1, False)["width_mm"] > t["width_mm"] * 2
    with pytest.raises(ValueError):
        hwlab.trace_width(0)
    b = hwlab.board_size([{"w": 20, "h": 10}, {"w": 5, "h": 5, "qty": 4}])
    assert b["parts_area_mm2"] == 300 and b["board_mm"][0] >= 26


def test_enclosure_stl_is_a_closed_set_of_boxes():
    r = hwlab.enclosure(60, 40, 25, 2, holes=[{"x": 10, "z": 12, "d": 6}])
    assert r["outer_mm"] == [64, 44, 27] and "cylinder(d=6" in r["scad"]
    assert r["stl"].count("facet normal") == 10 * 12               # 10 boxes × 12 triangles
    with pytest.raises(ValueError):
        hwlab.enclosure(60, 40, 25, 0.5)


def test_beam_alternatives():
    r = hwlab.beam_alternatives(200 * 9.81, 500, "konzola", 2)
    assert r["options"] and all(r["options"][i]["mass_kg"] <= r["options"][i + 1]["mass_kg"] for i in range(len(r["options"]) - 1))
    steel = next(o for o in r["options"] if o["material"] == "ocel S235" and o["profile"] == "plný čtverec")
    s = float(steel["size"].split("×")[0])
    assert 6 * 200 * 9.81 * 500 / s ** 3 * 2 <= 235 + 1e-6      # σ = 6M/b³ with the safety factor
    assert r["options"][0]["profile"] != "plný čtverec"          # a tube beats a full bar on mass


def _rot(ax, ay, az):
    ax, ay, az = map(math.radians, (ax, ay, az))
    rx = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
    ry = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
    rz = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    return rz @ ry @ rx


def test_camera_calibration_recovers_the_lens(tmp_path):
    k = np.array([[800, 0, 480], [0, 800, 320], [0, 0, 1.0]])
    files = []
    for n, angles in enumerate([(15, 0, 0), (-15, 10, 5), (0, -20, -5), (10, 15, 10), (-10, -10, 0)]):
        r, t = _rot(*angles), np.array([-120, -75, 650.0])
        im = Image.new("L", (960, 640), 255)
        d = ImageDraw.Draw(im)

        def proj(x, y):
            p = k @ (r @ np.array([x, y, 0]) + t)
            return (p[0] / p[2], p[1] / p[2])
        for j in range(7):
            for i in range(10):
                if (i + j) % 2 == 0:
                    x0, y0 = (i - 1) * 30, (j - 1) * 30
                    d.polygon([proj(x0, y0), proj(x0 + 30, y0), proj(x0 + 30, y0 + 30), proj(x0, y0 + 30)], fill=0)
        f = tmp_path / f"cb{n}.png"
        im.save(f)
        files.append(f)
    out = hwlab.calibrate_photos(files, 9, 6, 30)
    assert abs(out["fx"] - 800) < 40 and abs(out["fy"] - 800) < 40
    assert abs(out["cx"] - 480) < 15 and abs(out["cy"] - 320) < 15 and out["rms_px"] < 1.5
    blank = tmp_path / "prazdna.png"
    Image.new("L", (400, 300), 255).save(blank)
    with pytest.raises(ValueError):
        hwlab.calibrate_photos([blank, blank, blank], 9, 6, 30)


async def test_hardware_tools(rt):
    r = await tools.call("schematic", {"wiring": "Arduino.D9 -> R1.1; R1.2 -> LED1.A; LED1.K -> GND"}, rt)
    assert r.ok and [Path(a).suffix for a in r.attachments] == [".svg", ".net"]
    r = await tools.call("pcb_helper", {"current_a": 2, "parts": "20x10, 5x5x4"}, rt)
    assert r.ok and "mm" in r.summary and "Deska" in r.summary
    r = await tools.call("enclosure_design", {"width": 50, "depth": 30, "height": 20, "holes": "10,8,6"}, rt)
    assert r.ok and Path(r.attachments[1]).read_text().startswith("solid jarvis")
    r = await tools.call("beam_alternatives", {"load_kg": 10, "length_mm": 300}, rt)
    assert r.ok and "kg" in r.summary
