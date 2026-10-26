"""OMEGA wave 24 (maker workshop and planning): bill of materials, part compatibility, serial monitor over a real
pyserial loopback, sensor chart, robot arm kinematics, task dependency plan, formula explorer, learning path, one
search across everything, the user's own workflows, and named window groups."""
import json
import math

import pytest
from PIL import Image

from jarvis import maker, paths, tools

tools.load_builtin()


async def test_bill_of_materials(rt, tmp_path):
    d = tmp_path / "deska"                                  # tmp_path itself also holds JARVIS_HOME
    d.mkdir()
    (d / "bom.csv").write_text(
        "Ref;Value;Footprint;Qty;Cena\n"
        "R1,R2;10k ohm;0805;2;0,50\n"
        "R3;10 kOhm;0603;1;0,50\n"
        "C1;100nF;0805;1;1,20\n"
        "U1;ESP32-WROOM;Module;1;\n", encoding="utf-8")
    r = await tools.call("bill_of_materials", {"file": str(d / "bom.csv"), "boards": 5}, rt)
    assert r.ok, r.summary
    res = next(x for x in r.data["lines"] if x["refs"] == ["R1", "R2", "R3"])
    assert res["per_board"] == 3 and res["qty"] == 15 and res["cost"] == 7.5
    assert r.data["unique"] == 3 and r.data["pieces"] == 25 and r.data["total"] == 13.5
    assert r.data["missing_price"] == ["ESP32-WROOM"] and "0603, 0805" in r.data["footprint_conflicts"][0]
    assert not (await tools.call("bill_of_materials", {"file": str(d / "nic.csv")}, rt)).ok


async def test_parts_compatibility(rt):
    parts = [{"name": "ESP32", "role": "mcu", "logic_v": 3.3, "vin_min": 3.0, "vin_max": 3.6, "current_ma": 240},
             {"name": "HC-SR04", "role": "sensor", "logic_v": 5, "vin_min": 4.5, "vin_max": 5.5, "current_ma": 15},
             {"name": "BME280", "role": "sensor", "logic_v": 3.3, "vin_min": 1.7, "vin_max": 3.6, "current_ma": 1},
             {"name": "Motor", "role": "actuator", "current_ma": 300}]
    r = await tools.call("parts_compatibility", {"parts": parts, "supply_v": 3.3, "supply_ma": 500}, rt)
    iss = " | ".join(r.data["issues"])
    assert not r.data["compatible"] and "HC-SR04 posílá 5 V" in iss and "pod minimem 4.5 V" in iss
    assert "Motor bere 300 mA" in iss and "celkový odběr 556 mA" in iss
    assert "BME280 ↔ ESP32: logické úrovně sedí" in r.data["ok"]
    ok = maker.compatibility(parts[:1] + parts[2:3], 3.3, 1000)
    assert ok["compatible"] and ok["total_ma"] == 241


def test_serial_loopback():
    serial = pytest.importorskip("serial")
    port = serial.serial_for_url("loop://", baudrate=9600, timeout=0.05)
    r = maker.serial_read("loop://", 9600, 0.6, 50, "teplota 21.5 vlhkost 40", opener=lambda: port)
    assert r["lines"] == ["teplota 21.5 vlhkost 40"] and r["numbers"] == [[21.5, 40.0]]
    with pytest.raises(Exception):
        maker.serial_read("COM_NEEXISTUJE_99", 9600, 0.2)


async def test_serial_tool_errors(rt):
    pytest.importorskip("serial")
    r = await tools.call("serial_monitor", {"port": "/dev/neexistuje-jarvis", "seconds": 1}, rt)
    assert not r.ok and "nejde otevřít" in r.summary
    assert (await tools.call("serial_monitor", {}, rt)).ok


async def test_sensor_chart(rt, tmp_path):
    d = tmp_path / "senzory"
    d.mkdir()
    rows = "\n".join(f"{i};{20 + math.sin(i / 3):.3f};{50 - i}" for i in range(30))
    (d / "data.csv").write_text("cas;teplota;vlhkost\n" + rows + "\n", encoding="utf-8")
    r = await tools.call("sensor_chart", {"file": str(d / "data.csv"), "columns": ["teplota", "vlhkost"], "title": "Dílna"}, rt)
    assert r.ok, r.summary
    st = r.data["stats"]
    assert set(st) == {"teplota", "vlhkost"} and st["vlhkost"] == {"min": 21, "max": 50, "mean": 35.5, "n": 30}
    assert 19 < st["teplota"]["min"] < st["teplota"]["max"] < 21
    im = Image.open(r.data["path"])
    assert im.size == (1000, 480) and r.attachments == [r.data["path"]]
    blue = {c: n for n, c in im.getcolors(1_000_000)}.get((37, 99, 235), 0)
    assert blue > 300                                               # the line is really drawn
    bad = await tools.call("sensor_chart", {"values": {"x": [1]}}, rt)
    assert not bad.ok and "2 a více" in bad.summary


async def test_robot_arm(rt):
    r = await tools.call("robot_arm", {"l1": 10, "l2": 8, "points": [[12, 5]]}, rt)
    t1, t2 = math.radians(r.data["shoulder_deg"]), math.radians(r.data["elbow_deg"])
    assert abs(10 * math.cos(t1) + 8 * math.cos(t1 + t2) - 12) < 1e-3 and abs(10 * math.sin(t1) + 8 * math.sin(t1 + t2) - 5) < 1e-3
    assert "Nedosáhne" in (await tools.call("robot_arm", {"l1": 10, "l2": 8, "points": [[20, 0]]}, rt)).summary
    assert "moc blízko" in maker.arm_ik(10, 8, 1, 0)["why"]
    p = await tools.call("robot_arm", {"l1": 10, "l2": 8, "points": [[12, 5], [5, 12]]}, rt)
    assert p.data["ok"] and len(p.data["path"]) == 11 and 0 < p.data["max_jump_deg"] < 30
    q = maker.arm_path(10, 8, [(12, 0), (19, 0)], 7)
    assert not q["ok"] and any("daleko" in x for x in q["problems"])


async def test_task_plan(rt):
    tasks = [{"name": "Návrh", "days": 3}, {"name": "Deska", "days": 5, "after": ["Návrh"]},
             {"name": "Firmware", "days": 4, "after": ["Návrh"]}, {"name": "Krabička", "days": 2, "after": ["Návrh"]},
             {"name": "Test", "days": 1, "after": ["Deska", "Firmware", "Krabička"]}]
    r = await tools.call("task_plan", {"tasks": tasks}, rt)
    assert r.data["finish_days"] == 9 and r.data["critical"] == ["Návrh", "Deska", "Test"]
    assert r.data["slack"] == {"Návrh": 0, "Deska": 0, "Firmware": 1, "Krabička": 3, "Test": 0}
    assert r.data["parallel"] == [["Deska", "Firmware", "Krabička"]] and "Krabička (+3 d)" in r.summary
    c = await tools.call("task_plan", {"tasks": [{"name": "A", "after": ["B"]}, {"name": "B", "after": ["A"]}, {"name": "C", "after": ["X"]}]}, rt)
    assert not c.ok and c.data["cycle"] == ["A", "B"] and c.data["unknown"] == ["X"]


async def test_formula_explorer(rt):
    r = await tools.call("formula_explorer", {"formula": "U**2 / R", "variable": "U", "start": 0, "stop": 12, "steps": 4, "fixed": {"R": 6}}, rt)
    assert [x["value"] for x in r.data["rows"]] == [0, 1.5, 6, 13.5, 24] and r.data["max"] == 24
    assert abs(r.data["elasticity"] - 2.01) < 0.01                   # power grows with the square of the voltage
    assert not (await tools.call("formula_explorer", {"formula": "__import__('os')", "variable": "x", "start": 0, "stop": 1}, rt)).ok


async def test_learning_path(rt):
    topics = {"Derivace": ["Limity", "Funkce"], "Limity": ["Funkce"], "Funkce": ["Algebra"], "Algebra": [], "Integrály": ["Derivace"]}
    r = await tools.call("learning_path", {"topics": topics, "goal": "integraly", "known": ["Algebra"]}, rt)
    assert r.data["order"] == ["Funkce", "Limity", "Derivace", "Integrály"] and r.data["undefined"] == []
    assert not (await tools.call("learning_path", {"topics": {"A": ["B"], "B": ["A"]}, "goal": "A"}, rt)).ok
    assert maker.prerequisites({"A": ["Z"]}, "A")["undefined"] == ["Z"]


async def test_search_everything_and_workflows(rt, tmp_path):
    rt.knowledge.add_fact("Router v dílně má heslo na štítku pod krytem")
    from jarvis import docsearch

    d = tmp_path / "dokumenty"
    d.mkdir()
    (d / "navod.txt").write_text("Návod k routeru: reset se dělá sponkou na 10 sekund.", encoding="utf-8")
    docsearch.index_folder(rt, d)
    await tools.call("list_add", {"list": "nákup", "items": ["nový router TP-Link"]}, rt)
    rt.update_config({"automations": {"items": [
        {"id": "r", "name": "Restart routeru", "trigger": {"type": "time", "value": "04:00"}, "steps": [{"say": "Restartuju router"}]}]}})
    wf = paths.data_dir() / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "faktura.json").write_text(json.dumps({"name": "Faktura do iDokladu", "url": "https://app.idoklad.cz", "steps": ["klikni Nová faktura", "vyplň {částka}"]}),
                                     encoding="utf-8")
    r = await tools.call("search_everything", {"query": "router"}, rt)
    assert {"paměť a konverzace", "dokumenty", "seznamy", "postupy"} <= set(r.data), r.data
    assert "navod.txt" in r.data["dokumenty"][0]["title"] and r.data["seznamy"][0]["text"] == "nový router TP-Link"
    assert r.data["postupy"][0]["title"] == "Restart routeru"
    w = await tools.call("find_workflow", {"query": "jak jsem dělal fakturu"}, rt)
    assert w.data[0]["kind"] == "nahraný postup" and w.data[0]["title"] == "Faktura do iDokladu"
    assert "nikde" in (await tools.call("search_everything", {"query": "zxqwv"}, rt)).summary


async def test_name_window_groups(rt, monkeypatch):
    wins = [{"title": "Rozpočet Chata 2026.xlsx - Excel", "app": "Excel"},
            {"title": "Chata – nabídky stavebnin - Google Chrome", "app": "Chrome"},
            {"title": "Poznámky chata.txt - Poznámkový blok", "app": "Notepad"},
            {"title": "Spotify Premium", "app": "Spotify"},
            {"title": "Nová karta - Google Chrome", "app": "Chrome"}]
    monkeypatch.setattr(rt.platform, "window_layout", lambda: wins)
    r = await tools.call("name_window_groups", {}, rt)
    assert len(r.data) == 1 and r.data[0]["name"] == "Chata" and len(r.data[0]["windows"]) == 3
    assert r.data[0]["apps"] == ["Chrome", "Excel", "Notepad"]


def test_bom_kicad_refs_count(tmp_path):
    d = tmp_path / "kicad"
    d.mkdir()
    (d / "k.csv").write_text('"Reference","Value","Footprint"\n"C1 C2 C3","100n","C_0603"\n"D1","LED","LED_0805"\n', encoding="utf-8")
    r = maker.bom(d / "k.csv", 2)
    assert {x["part"]: x["qty"] for x in r["lines"]} == {"100n": 6, "LED": 2} and r["total"] == 0
