"""OMEGA wave 16 (engineering & science): units and dimension checks, electronics, power cost, statistics checked
against known reference values, A/B tests, frequency analysis of a real WAV, CSV cleaning, tolerance stack-up, an STL
cube and a broken STL, and the experiment logbook."""
import csv
import math
import struct
import wave

import pytest

from jarvis import science, tools

tools.load_builtin()


@pytest.mark.parametrize("expr,value,unit", [
    ("5 km / 2 h na m/s", 0.694444, "m/s"), ("3 kW * 2 h v kWh", 6.0, "kWh"), ("20 °C na °F", 68.0, "°F"), ("-40 °F na °C", -40.0, "°C"),
    ("60 km/h na m/s", 16.666667, "m/s"), ("1 inch na mm", 25.4, "mm"), ("2000 mAh / 250 mA na h", 8.0, "h"), ("9,81 m/s² * 2 kg", 19.62, "N"),
    ("230 V * 10 A", 2300.0, "W"), ("1 kWh na MJ", 3.6, "MJ"), ("100 %  * 3", 3.0, ""),
])
def test_unit_calc(expr, value, unit):
    r = science.calc(expr)
    assert r["value"] == pytest.approx(value, rel=1e-5) and r["unit"] == unit


def test_unit_errors_and_formula_dimensions():
    with pytest.raises(ValueError, match="nesouhlasí rozměry"):
        science.calc("5 m + 2 s")
    with pytest.raises(ValueError, match="nejde převést"):
        science.calc("5 kg na m")
    with pytest.raises(ValueError, match="neznámá jednotka"):
        science.calc("5 blbost")
    assert science.check_formula("E = m * v^2 / 2", {"E": "J", "m": "kg", "v": "m/s"})["ok"]
    bad = science.check_formula("E = m * v", {"E": "J", "m": "kg", "v": "m/s"})
    assert not bad["ok"] and bad["left"] == "J" and bad["right"] == "m·kg·s⁻¹"
    assert science.check_formula("P = U * I", {"P": "W", "U": "V", "I": "mA"})["ok"]


async def test_unit_tool(rt):
    assert (await tools.call("unit_calc", {"expression": "5 km / 2 h na m/s"}, rt)).summary == "0,694444 m/s"
    assert not (await tools.call("unit_calc", {"expression": "5 m + 2 s"}, rt)).ok


async def test_circuits(rt):
    r = await tools.call("circuit_calc", {"task": "led", "supply_v": 5, "led_v": 2, "current_ma": 20}, rt)
    assert r.data["standard_ohm"] == 150 and r.data["rating_w"] == 0.125
    r = await tools.call("circuit_calc", {"task": "led", "supply_v": 12, "led_v": 3.1, "current_ma": 20}, rt)
    assert r.data["exact_ohm"] == 445.0 and r.data["standard_ohm"] == 470 and r.data["current_ma"] < 20
    r = await tools.call("circuit_calc", {"task": "ohm", "V": 12, "R": 6}, rt)
    assert r.data["I"] == 2 and r.data["P"] == 24
    r = await tools.call("circuit_calc", {"task": "divider", "V": 12, "vout": 3.3}, rt)
    assert abs(r.data["vout"] - 3.3) / 3.3 < 0.01
    r = await tools.call("circuit_calc", {"task": "parallel", "values": [100, 100, 50]}, rt)
    assert r.data["ohm"] == pytest.approx(25)
    r = await tools.call("circuit_calc", {"task": "rc", "R": 10000, "C": 1e-6}, rt)
    assert r.data["tau_s"] == pytest.approx(0.01) and r.data["cutoff_hz"] == pytest.approx(15.915, rel=1e-3)
    assert (await tools.call("circuit_calc", {"task": "colors", "colors": ["žlutá", "fialová", "červená", "zlatá"]}, rt)).summary == "4.7 kΩ ± 5 %."
    assert (await tools.call("circuit_calc", {"task": "bands", "R": 220}, rt)).data["bands"] == ["červená", "červená", "hnědá", "zlatá"]
    assert (await tools.call("circuit_calc", {"task": "bands", "R": 10}, rt)).data["bands"] == ["hnědá", "černá", "černá", "zlatá"]
    r = await tools.call("circuit_calc", {"task": "battery", "capacity_mah": 2000, "load_ma": 50, "sleep_ma": 0.05, "duty": 0.1}, rt)
    assert r.data["avg_ma"] == pytest.approx(5.045) and r.data["days"] == pytest.approx(14.0, abs=0.1)
    assert not (await tools.call("circuit_calc", {"task": "ohm", "V": 5}, rt)).ok
    assert not (await tools.call("circuit_calc", {"task": "led", "supply_v": 3, "led_v": 3.2}, rt)).ok


async def test_power_cost(rt):
    r = await tools.call("power_cost", {"devices": [{"name": "lednice", "watts": 100, "hours": 8},
                                                    {"name": "PC", "watts": 300, "hours": 4, "standby_w": 2}], "price_kwh": 5}, rt)
    assert r.data["kwh_day"] == pytest.approx(0.8 + 1.2 + 0.04) and r.data["devices"][0]["name"] == "PC"
    assert r.data["cost_year"] == round(2.04 * 365 * 5) and "Jen pohotovost stojí 73 Kč" in r.summary


def test_t_distribution_reference_values():
    assert science.t_pvalue(2.0, 10) == pytest.approx(0.07339, abs=1e-4)
    assert science.t_pvalue(2.228, 10) == pytest.approx(0.05, abs=5e-4)
    assert science._t_crit(30, 0.05) == pytest.approx(2.042, abs=1e-3)
    assert science.betainc(2, 3, 0.4) == pytest.approx(0.5248, abs=1e-4)


async def test_compare_groups(rt):
    a = [12.1, 11.8, 12.5, 12.0, 11.9, 12.3, 12.2, 11.7, 12.4, 12.0] * 3
    b = [x + 0.6 for x in a]
    r = await tools.call("compare_groups", {"a": a, "b": b}, rt)
    assert r.data["significant"] and r.data["diff"] == pytest.approx(0.6) and r.data["effect"] == "velký"
    assert r.data["ci"][0] < 0.6 < r.data["ci"][1]
    small = await tools.call("compare_groups", {"a": "10 12 11 13", "b": "11 12 12 14"}, rt)
    assert not small.data["significant"] and "malý vzorek" in small.summary
    out = await tools.call("compare_groups", {"a": [10] * 15 + [11] * 14 + [90], "b": [10.5] * 15 + [11.5] * 15}, rt)
    assert "odlehlé hodnoty" in out.summary


async def test_ab(rt):
    r = await tools.call("ab_test", {"baseline_pct": 5, "min_change_pct": 10, "daily_visitors": 2000}, rt)
    assert 31000 < r.data["per_variant"] < 31500 and r.data["days"] == 32
    r = await tools.call("ab_test", {"conv_a": 500, "visits_a": 10000, "conv_b": 580, "visits_b": 10000}, rt)
    assert r.data["significant"] and r.data["p_value"] == pytest.approx(0.0123, abs=5e-4)
    srm = await tools.call("ab_test", {"conv_a": 500, "visits_a": 10000, "conv_b": 600, "visits_b": 11000}, rt)
    assert not srm.data["significant"] and "SRM" in srm.summary


async def test_frequency_wav(rt, tmp_path):
    rate, f = 8000, tmp_path / "ton.wav"
    with wave.open(str(f), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(struct.pack("<hh", *(2 * [int(12000 * math.sin(2 * math.pi * 440 * i / rate) + 4000 * math.sin(2 * math.pi * 1250 * i / rate))]))
                          for i in range(rate))
        w.writeframes(frames)
    r = await tools.call("frequency_analysis", {"file": str(f)}, rt)
    assert r.data["dominant_hz"] == pytest.approx(440, abs=0.5) and r.data["peaks"][1]["hz"] == pytest.approx(1250, abs=0.5)
    assert r.data["peaks"][1]["db"] == pytest.approx(-9.5, abs=0.5)
    c = tmp_path / "vib.csv"
    c.write_text("t;a\n" + "\n".join(f"{i};{math.sin(2 * math.pi * 50 * i / 1000):.6f}".replace(".", ",") for i in range(2000)), encoding="utf-8")
    r = await tools.call("frequency_analysis", {"file": str(c), "sample_rate": 1000, "column": "a"}, rt)
    assert r.data["dominant_hz"] == pytest.approx(50, abs=0.3)
    assert not (await tools.call("frequency_analysis", {"file": str(c)}, rt)).ok


def write_csv(path, rows, delim=";"):
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f, delimiter=delim).writerows(rows)


async def test_dataset_check_and_clean(rt, tmp_path):
    src = tmp_path / "prodeje.csv"
    rows = [["město", "cena", "datum"], ["Praha", "120,50", "1.2.2026"], [" praha", "99", "2026-02-03"], ["Brno ", "80", "03.02.2026"],
            ["Brno", "abc", "2026-02-04"], ["Praha", "120,50", "1.2.2026"], ["Ostrava", "", "2026-02-05"]]
    rows += [["Brno", str(100 + i), "2026-03-01"] for i in range(10)] + [["Brno", "99999", "2026-03-02"]]
    write_csv(src, rows)
    before = src.read_bytes()
    r = await tools.call("dataset_check", {"file": str(src)}, rt)
    cols = {c["name"]: c for c in r.data["cols"]}
    assert r.data["duplicates"] == 1 and cols["cena"]["type"] == "číslo" and cols["cena"]["comma_decimal"] == 2
    assert cols["cena"]["not_number"] == ["abc"] and cols["cena"]["outliers"] == [99999.0] and cols["datum"]["type"] == "datum"
    assert set(cols["datum"]["date_formats"]) == {"%d.%m.%Y", "%Y-%m-%d"} and "praha" in cols["město"]["variants"]
    r = await tools.call("dataset_clean", {"file": str(src)}, rt)
    out = list(csv.reader(open(tmp_path / "prodeje_ciste.csv", encoding="utf-8"), delimiter=";"))
    assert src.read_bytes() == before and r.data["rows_after"] == r.data["rows_before"] - 1
    assert out[1] == ["Praha", "120.5", "2026-02-01"] and out[2][0] == "Praha" and out[3] == ["Brno", "80", "2026-02-03"]
    assert r.data["after_duplicates"] == 0
    assert not (await tools.call("dataset_clean", {"file": str(src)}, rt)).ok        # never overwrites


async def test_tolerance_stackup(rt):
    dims = [{"name": "pouzdro", "nominal": 50, "plus": 0.1, "minus": 0.1, "dir": 1},
            {"name": "díl A", "nominal": 20, "plus": 0.05, "minus": 0.05, "dir": -1},
            {"name": "díl B", "nominal": 29.5, "plus": 0.2, "minus": 0.0, "dir": -1}]
    r = await tools.call("tolerance_stackup", {"dims": dims, "gap_min": 0.1}, rt)
    assert r.data["nominal"] == pytest.approx(0.5) and r.data["worst_min"] == pytest.approx(0.15) and r.data["worst_max"] == pytest.approx(0.65)
    assert r.data["worst_ok"] and r.data["contributors"][0]["name"] in ("pouzdro", "díl B")
    r = await tools.call("tolerance_stackup", {"dims": dims, "gap_min": 0.2}, rt)
    assert not r.data["worst_ok"] and r.data["rss_ok"] and "v nejhorším případě NE" in r.summary


def cube(path, size=20.0, drop_face=False, binary=True):
    s = size
    v = [(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0), (0, 0, s), (s, 0, s), (s, s, s), (0, s, s)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    if drop_face:
        faces = faces[:-1]
    if binary:
        data = b"\0" * 80 + struct.pack("<I", len(faces))
        for f in faces:
            data += struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *v[i]) for i in f) + b"\0\0"
        path.write_bytes(data)
    else:
        path.write_text("solid c\n" + "".join("facet normal 0 0 0\nouter loop\n" + "".join(f"vertex {v[i][0]} {v[i][1]} {v[i][2]}\n" for i in f) +
                                              "endloop\nendfacet\n" for f in faces) + "endsolid c\n", encoding="utf-8")


async def test_stl(rt, tmp_path):
    good = tmp_path / "kostka.stl"
    cube(good)
    r = await tools.call("check_3d_model", {"file": str(good)}, rt)
    assert r.data["size_mm"] == [20, 20, 20] and r.data["volume_cm3"] == 8.0 and r.data["watertight"] and r.data["printable"]
    assert 3 < r.data["filament_g"] < 6 and "Připraveno k tisku" in r.summary
    txt = tmp_path / "kostka_txt.stl"
    cube(txt, binary=False)
    assert (await tools.call("check_3d_model", {"file": str(txt)}, rt)).data["volume_cm3"] == 8.0
    broken = tmp_path / "dira.stl"
    cube(broken, drop_face=True)
    r = await tools.call("check_3d_model", {"file": str(broken)}, rt)
    assert not r.data["watertight"] and "není uzavřený" in r.summary
    big = tmp_path / "velka.stl"
    cube(big, size=300)
    assert "nevejde se na tiskárnu" in (await tools.call("check_3d_model", {"file": str(big)}, rt)).summary
    (tmp_path / "x.stl").write_text("hello", encoding="utf-8")
    assert not (await tools.call("check_3d_model", {"file": str(tmp_path / "x.stl")}, rt)).ok


async def test_experiments(rt):
    r = await tools.call("experiment_log", {"title": "Nový lepidlo na PETG", "hypothesis": "drží o 20 % víc", "params": {"teplota": 240},
                                            "project": "tiskárna", "tags": "lepidlo"}, rt)
    eid = r.data["id"]
    await tools.call("experiment_log", {"title": "Rychlejší chlazení"}, rt)
    r = await tools.call("experiment_result", {"experiment_id": eid, "result": "drží o 35 % víc", "conclusion": "používat", "confirmed": True}, rt)
    assert r.data["status"] == "potvrzeno"
    r = await tools.call("experiments", {"query": "lepidlo"}, rt)
    assert len(r.data) == 1 and r.data[0]["params"] == {"teplota": 240} and "potvrzeno" in r.summary
    assert len((await tools.call("experiments", {"project": "tiskárna"}, rt)).data) == 1
    assert not (await tools.call("experiment_result", {"experiment_id": 999, "result": "x"}, rt)).ok
