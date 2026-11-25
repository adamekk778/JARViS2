"""3.20 Programování+ (301–320), Dílna+ (321–340) a Zábava+ (341–360)."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import time
import wave
import zipfile
from pathlib import Path

import numpy as np
import pytest

from jarvis import devx, funx, shopx, tools


# ================================================================== Programování+
def test_licenses():
    assert devx.license_kind("MIT") == ("permissive", 0)
    assert devx.license_kind("GPL-3.0-only")[0] == "copyleft" and devx.license_kind("AGPL-3.0")[1] == 3
    assert devx.license_kind("MIT OR GPL-2.0")[0] == "permissive"
    deps = [{"name": "a", "license": "MIT"}, {"name": "b", "license": "GPL-3.0"}, {"name": "c", "license": ""},
            {"name": "d", "license": "LGPL-2.1"}, {"name": "e", "license": "AGPL-3.0"}]
    bad = {b["name"]: b for b in devx.license_conflicts("MIT", deps)}
    assert set(bad) == {"b", "c", "d", "e"} and bad["d"]["severity"] == "low" and "síť" in bad["e"]["why"]
    assert devx.license_conflicts("GPL-3.0", [{"name": "b", "license": "GPL-3.0"}]) == []


def test_scan_licenses_node(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "1", "evil": "1"}}), encoding="utf-8")
    for n, lic in (("left-pad", "WTFPL"), ("evil", {"type": "GPL-2.0"})):
        d = tmp_path / "node_modules" / n
        d.mkdir(parents=True)
        (d / "package.json").write_text(json.dumps({"license": lic}), encoding="utf-8")
    deps = {d["name"]: d["license"] for d in devx.scan_licenses(tmp_path)}
    assert deps == {"left-pad": "WTFPL", "evil": "GPL-2.0"}


DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,5 @@
 import os
+print("debug", x)
+API_KEY = "sk-abcdefghijklmnopqrstuvwx"
+try:
+    run()
+except:
 def main():
"""


def test_quick_review_and_commit_message():
    issues = devx.quick_review(DIFF)
    labels = [(i["line"], i["issue"]) for i in issues]
    assert (2, "Zapomenutý ladicí výpis") in labels and any("tajný klíč" in x for _, x in labels)
    assert any("spolkne" in x for _, x in labels)
    assert devx.diff_stat(DIFF) == {"app.py": {"add": 5, "del": 0}}
    msg = devx.commit_fallback(DIFF)
    assert msg.startswith("Úpravy v app") and "+5" in msg
    assert devx.commit_lang("Oprava přihlášení\nPřidán test") == "čeština" and devx.commit_lang("Fix login\nAdd test") == "angličtina"


def test_ci_parsing():
    runs = devx.parse_runs({"workflow_runs": [{"id": 7, "name": "CI", "head_branch": "main", "status": "completed", "conclusion": "failure",
                                                "html_url": "https://github.com/x/y/actions/runs/7", "head_sha": "abcdef123"}]})
    assert runs[0]["sha"] == "abcdef1" and runs[0]["conclusion"] == "failure"
    jobs = {"jobs": [{"name": "test", "conclusion": "failure", "steps": [{"name": "pytest", "conclusion": "failure"}]},
                     {"name": "lint", "conclusion": "success", "steps": []}]}
    assert devx.failed_steps(jobs) == ["test: pytest"]


async def test_ci_check_remembers(rt):
    class R:
        def __init__(self, data, code=200):
            self._d, self.status_code = data, code

        def json(self):
            return self._d

    runs = {"workflow_runs": [{"id": 1, "name": "CI", "status": "completed", "conclusion": "failure", "head_branch": "main"}]}

    class C:
        def __init__(self):
            self.data = runs

        async def get(self, url, headers=None):
            return R({"jobs": []}) if url.endswith("/jobs") else R(self.data)

    c = C()
    assert await devx.ci_check(rt, "x/y", c) == []                        # the first look only remembers
    c.data = {"workflow_runs": [*runs["workflow_runs"], {"id": 2, "name": "CI", "status": "completed", "conclusion": "failure",
                                                          "head_branch": "dev"}]}
    new = await devx.ci_check(rt, "x/y", c)
    assert [r["id"] for r in new] == [2] and await devx.ci_check(rt, "x/y", c) == []


def test_readme_and_commands(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "shop", "description": "E-shop", "scripts": {"dev": "vite", "test": "vitest"}}),
                                           encoding="utf-8")
    (tmp_path / "server.py").write_text('"""API serveru e-shopu."""\n\ndef start():\n    pass\n', encoding="utf-8")
    o = devx.project_outline(tmp_path)
    md = devx.readme_from_outline(o)
    assert md.startswith("# shop") and "npm install" in md and "`server.py` – API serveru e-shopu." in md
    cmds = devx.detect_commands(tmp_path)
    assert cmds["dev"] == "npm run dev" and cmds["start"] == "python server.py"
    assert devx.pick_command(cmds, "frontend") == ("dev", "npm run dev")
    assert devx.pick_command(cmds, "test") == ("test", "npm run test")


def test_start_and_stop_command(tmp_path):
    calls = []

    class P:
        pid = 999999

        def terminate(self):
            calls.append("term")

    log = devx.start_command("shop:dev", "npm run dev", tmp_path, tmp_path, popen=lambda *a, **k: P())
    assert log.name == "shop-dev.log" and "shop:dev" in devx.RUNNING
    assert devx.stop_command("shop:dev") and calls == ["term"] and not devx.stop_command("shop:dev")


def test_regex_and_sql(tmp_path):
    pat = devx.regex_offline("najdi e-maily v textu")
    assert devx.regex_test(pat, "piš na a.b@firma.cz nebo x@y.com")["matches"] == ["a.b@firma.cz", "x@y.com"]
    assert devx.regex_offline("telefonní čísla") and devx.regex_offline("něco úplně jiného") is None
    assert not devx.regex_test("(", "x")["ok"]
    assert devx.read_only_sql("SELECT * FROM t WHERE a = 1;") and devx.read_only_sql("with x as (select 1) select * from x")
    assert not devx.read_only_sql("DELETE FROM t") and not devx.read_only_sql("SELECT 1; DROP TABLE t")
    assert not devx.read_only_sql("select * from t; -- ok\nupdate t set a=1")
    import sqlite3

    dbp = tmp_path / "a.db"
    con = sqlite3.connect(dbp)
    con.execute("CREATE TABLE zakaznik (id INTEGER, jmeno TEXT)")
    con.commit()
    con.close()
    assert "CREATE TABLE zakaznik" in devx.sqlite_schema(dbp)
    assert devx.extract_code("Tady:\n```sql\nSELECT 1\n```") == "SELECT 1"


def test_navigation_and_rename(tmp_path):
    (tmp_path / "auth.py").write_text("def login(user):\n    return check(user)\n\n\ndef check(u):\n    return True\n", encoding="utf-8")
    (tmp_path / "web.ts").write_text("export async function handle() {\n  await login(u)\n  const loginCount = 1\n}\n", encoding="utf-8")
    hits = devx.find_symbol(tmp_path, "login")
    assert [(Path(h["file"]).name, h["line"]) for h in hits] == [("auth.py", 1)]
    callers = devx.find_callers(tmp_path, "check")
    assert [(Path(c["file"]).name, c["in"]) for c in callers] == [("auth.py", "login")]
    prev = devx.rename_preview(tmp_path, "login", "sign_in")
    assert sum(p["count"] for p in prev) == 2 and "+def sign_in(user):" in "".join(p["diff"] for p in prev)
    assert devx.rename_apply(tmp_path, "login", "sign_in") == 2
    assert "loginCount" in (tmp_path / "web.ts").read_text(encoding="utf-8")            # only whole words
    assert devx.lang_of("auth.py - Visual Studio Code") == "Python" and devx.lang_of("App.tsx — Cursor") == "TypeScript (React)"


def test_snippets(rt):
    devx.snippet_add(rt, "Debounce v JS", "function debounce(f, ms) {}", "js", "časovač")
    devx.snippet_add(rt, "Čtení CSV v Pythonu", "import csv", "python")
    assert devx.snippet_find(rt, "debounce")[0]["title"] == "Debounce v JS"
    assert devx.snippet_find(rt, "csv python")[0]["title"].startswith("Čtení CSV")
    assert devx.snippet_find(rt, "kubernetes") == []


def test_czech_test_data():
    rows = devx.test_people(50, seed=1)
    assert len(rows) == 50 and rows == devx.test_people(50, seed=1)
    from jarvis import bizx

    for r in rows:
        assert devx.rc_ok(r["rodne_cislo"]), r["rodne_cislo"]
        assert bizx.ico_ok(r["ico"]), r["ico"]
        num = r["ucet"].split("/")[0]
        assert devx.acc_part_ok(num)
        mm = int(r["rodne_cislo"][2:4])
        assert (mm > 50) == (r["pohlavi"] == "ž")
        assert r["email"].isascii() and r["psc"][3] == " "
    women = [r for r in rows if r["pohlavi"] == "ž"]
    assert all(r["prijmeni"].endswith(("á", "ová")) for r in women)
    assert devx.to_csv(rows[:1]).startswith("jmeno;prijmeni")


def test_ports_docker_todos_pretty_git(tmp_path):
    assert isinstance(devx.listening_ports(), list)
    with pytest.raises(ValueError):
        import os

        devx.kill_pid(os.getpid())
    out = '{"ID":"abc123def4567","Names":"db","Image":"postgres","State":"running","Status":"Up 2 hours","Ports":"5432"}\n' \
          '{"ID":"ff","Names":"api","Image":"api","State":"exited","Status":"Exited (1) 3 min ago","Ports":""}'
    rows = devx.parse_docker_ps(out)
    assert rows[0]["id"] == "abc123def456" and "Problém: api" in devx.docker_summary(rows)
    porcelain = ("a" * 40 + " 1 1 1\nauthor Jan\nauthor-time 1700000000\n\t# TODO: opravit\n" +
                 "b" * 40 + " 2 2\nauthor Eva\nauthor-time 1790000000\n\tx = 1  # FIXME rychle\n")
    lines = devx.parse_blame(porcelain)
    assert [(x["line"], x["author"]) for x in lines] == [(1, "Jan"), (2, "Eva")]
    (tmp_path / "a.py").write_text("# TODO: opravit\nx = 1  # FIXME rychle\n", encoding="utf-8")

    def fake_git(cmd, **k):
        return subprocess.CompletedProcess(cmd, 0, porcelain, "")

    todos = devx.old_todos(tmp_path, 30, now=1790000000 + 86400, runner=fake_git)
    assert [t["line"] for t in todos] == [1] and todos[0]["text"] == "TODO: opravit"
    assert devx.pretty("{'a': 1, 'b': [1,2,],}")[0] == '{\n  "a": 1,\n  "b": [\n    1,\n    2\n  ]\n}'
    assert devx.pretty('{"a": 1}', "yaml") == ("a: 1\n", "yaml")
    assert devx.pretty("a: 1\nb:\n  - x\n")[1] == "yaml"
    with pytest.raises(ValueError):
        devx.pretty("{nesmysl")
    p = devx.git_plan("vrať poslední commit")
    assert p["args"] == ["reset", "--soft", "HEAD~1"] and not p["risky"]
    assert devx.git_plan("vrať poslední commit", pushed=True)["args"] == ["revert", "--no-edit", "HEAD"]
    assert devx.git_plan("zahoď změny", path="a.py")["args"] == ["restore", "--", "a.py"] and devx.git_plan("zahoď změny")["risky"]
    assert devx.git_plan("uvař kafe") is None


async def test_code_kit(rt, tmp_path):
    rt.cfg.tools.allowed_folders = [str(tmp_path)]
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "main.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    r = await tools.call("code_kit", {"action": "regex", "text": "e-mail", "sample": "a@b.cz"}, rt)
    assert r.ok and "a@b.cz" in r.summary
    r = await tools.call("code_kit", {"action": "pretty", "text": "[1,2,]"}, rt)
    assert r.ok and rt.platform.clipboard.startswith("[")
    r = await tools.call("code_kit", {"action": "readme", "path": str(tmp_path / "p")}, rt)
    assert r.ok and (tmp_path / "p" / "README.md").exists()
    r = await tools.call("code_kit", {"action": "testdata", "n": 3}, rt)
    assert r.ok and Path(r.data["path"]).read_text(encoding="utf-8").count("\n") == 3
    r = await tools.call("code_kit", {"action": "callers", "path": str(tmp_path / "p"), "name": "nic"}, rt)
    assert not r.ok
    r = await tools.call("code_kit", {"action": "readme", "path": "/etc"}, rt)
    assert not r.ok and "povolenými" in r.summary
    spec = tools.REGISTRY["code_kit"]
    assert spec.danger_if({"action": "kill"}) and spec.danger_if({"action": "git"}) and not spec.danger_if({"action": "review"})


# ================================================================== Dílna+
def cube(size: float = 10.0) -> np.ndarray:
    v = np.array([[x, y, z] for x in (0, size) for y in (0, size) for z in (0, size)], dtype=float)
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    return np.array([[v[a], v[b], v[c]] for a, b, c in faces])


def test_drying_cost_spools(rt):
    d = shopx.dry_advice("petg", humidity=55)
    assert d["need"] and d["temp"] == 65 and "65 °C" in d["text"]
    assert not shopx.dry_advice("PLA", humidity=30)["need"] and shopx.dry_advice("nylon", opened_days=10)["need"]
    assert not shopx.dry_advice("nesmysl")["ok"]
    c = shopx.print_cost(100, 5, 500, 120, 6, 2, 0)
    assert c["material"] == 50 and c["power"] == 3.6 and c["wear"] == 10 and c["total"] == 63.6
    sid = shopx.spool_add(rt, "petg", "černá", total_g=1000, price=549)
    assert shopx.spool_find(rt, "petg černou")["id"] == sid
    u = shopx.spool_use(rt, sid, 900)
    assert u["left"] == 100 and u["low"] and shopx.reorder_list(rt)[0]["id"] == sid


def test_stl_roundtrip_edit_thumbnail_library(rt, tmp_path):
    p = shopx.stl_write(tmp_path / "kostka.stl", cube())
    tris = shopx.stl_read(p)
    assert tris.shape == (12, 3, 3) and shopx.dims(tris) == [10, 10, 10] and abs(shopx.volume_cm3(tris) - 1.0) < 1e-6
    ascii_stl = tmp_path / "a.stl"
    ascii_stl.write_text("solid a\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid a\n")
    assert shopx.stl_read(ascii_stl).shape == (1, 3, 3)
    assert shopx.parse_edit("zvětši o 10 %") == {"op": "scale", "factor": 1.1}
    assert shopx.parse_edit("zmenši na 80 %") == {"op": "scale", "factor": 0.8}
    assert shopx.parse_edit("otoč o 90° kolem x") == {"op": "rotate", "deg": 90.0, "axis": "x"}
    assert shopx.parse_edit("udělej díru 5 mm") == {"op": "hole", "d": 5.0}
    assert shopx.dims(shopx.stl_edit(tris, {"op": "scale", "factor": 2})) == [20, 20, 20]
    long = tris.copy()
    long[:, :, 0] *= 3
    rot = shopx.stl_edit(long, {"op": "rotate", "deg": 90, "axis": "z"})
    assert shopx.dims(rot) == [10, 30, 10] and rot.reshape(-1, 3)[:, 2].min() == 0
    mir = shopx.stl_edit(tris, {"op": "mirror", "axis": "x"})
    assert shopx.volume_cm3(mir) == pytest.approx(1.0)
    png = shopx.thumbnail(tris, 64)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    (tmp_path / "drzaky").mkdir()
    shopx.stl_write(tmp_path / "drzaky" / "drzak_na_kolo.stl", cube(40))
    assert shopx.library_index(rt, [str(tmp_path)]) == 3 and shopx.library_index(rt, [str(tmp_path)]) == 0
    hit = shopx.library_find(rt, "držák na kolo")
    assert hit[0]["name"] == "drzak_na_kolo" and hit[0]["dims"] == "40×40×40"
    scad = shopx.hole_scad(p, 5, [10, 10, 10])
    assert "cylinder(d=5" in scad and "import(" in scad
    ok, why = shopx.run_openscad(scad, tmp_path / "o.stl") if not shopx.openscad() else (False, "OpenSCAD")
    assert not ok and "OpenSCAD" in why


async def test_iron_and_climate(rt):
    rt.cfg.shopx.iron_plug = "switch.pajecka"
    rt.cfg.shopx.workshop_motion = "binary_sensor.dilna"
    rt.cfg.shopx.workshop_temp = "sensor.dilna_t"
    calls = []

    async def service(d, s, data):
        calls.append((d, s, data["entity_id"]))

    def st(plug="on", motion="off", temp=8.0):
        return [{"id": "switch.pajecka", "state": plug, "value": None}, {"id": "binary_sensor.dilna", "state": motion, "value": None},
                {"id": "sensor.dilna_t", "state": str(temp), "value": temp}]

    t0 = 1_800_000_000.0
    said = await shopx.ha_tick(rt, st(), t0, service)
    assert any("12 °C" in s or "8 °C" in s for s in said)                         # cold workshop, once a day
    assert await shopx.ha_tick(rt, st(motion="on"), t0 + 30 * 60, service) == []   # someone works → the clock restarts
    said = await shopx.ha_tick(rt, st(), t0 + 76 * 60, service)
    assert said and "za 5 minut" in said[0]
    assert await shopx.ha_tick(rt, st(), t0 + 78 * 60, service) == []
    said = await shopx.ha_tick(rt, st(), t0 + 82 * 60, service)
    assert "vypnul" in said[0] and calls == [("switch", "turn_off", "switch.pajecka")]
    assert shopx.climate_advice(20, 70).endswith("rezavět.") and shopx.climate_advice(20, 40) == ""


def test_queue_calibration_laser(rt):
    printers = [{"name": "A1", "materials": ["PLA", "PETG"], "bed": [256, 256, 256]}, {"name": "Mini", "materials": ["PLA"], "bed": [180, 180, 180]}]
    jobs = [{"file": "a", "material": "PLA", "hours": 5, "size": "100x100"}, {"file": "b", "material": "PETG", "hours": 2, "size": ""},
            {"file": "c", "material": "PLA", "hours": 3, "size": "200x200"}, {"file": "d", "material": "ABS", "hours": 1, "size": ""}]
    plan = {j["file"]: j for j in shopx.plan_queue(jobs, printers)}
    assert plan["a"]["printer"] == "A1" and plan["c"]["printer"] == "Mini" or plan["c"]["printer"] == "A1"
    assert plan["c"]["printer"] == "A1" and plan["d"]["printer"] == ""                  # 200 mm does not fit the Mini; nobody prints ABS
    assert plan["b"]["printer"] == "A1" and plan["b"]["start_h"] == 8
    assert shopx.esteps(93, 100, 95) == 97.89 and shopx.flow(1.0, 0.45, 0.5) == 0.9
    with pytest.raises(ValueError):
        shopx.esteps(93, 100, 0)
    g = shopx.laser_gcode("rect", 50, 20, 50, 600, 2)
    assert g.count("M4 S500") == 2 and "G1 X50.000 Y20.000" in g
    assert shopx.gcode_time(g) == pytest.approx(2 * 140 / 600, abs=0.1)
    c = shopx.cnc_profile("rect", 40, 20, 3, 1)
    assert sum(1 for x in c if x.startswith("G1 Z")) == 3 and "G1 Z-3.000 F150" in c


def test_tools_lend_maint_units(rt):
    shopx.tool_add(rt, "Aku vrtačka Makita", "regál vlevo")
    assert shopx.tool_where(rt, "vrtačka")[0]["place"] == "regál vlevo"
    assert shopx.tools_missing(rt, ["vrtačka", "pájka"]) == ["pájka"]
    shopx.lend(rt, "vrtačka", "Petr")
    today = dt.date.today()
    assert shopx.lent_due(rt, today + dt.timedelta(days=31))[0]["person"] == "Petr" and shopx.lent_due(rt, today) == []
    assert shopx.returned(rt, "vrtačku") and shopx.lent_due(rt, today + dt.timedelta(days=40)) == []
    mid = shopx.maint_add(rt, "Kompresor", "vypustit vodu", 14, (today - dt.timedelta(days=20)).isoformat())
    assert shopx.maint_due(rt, today)[0]["late"] == 6 and shopx.maint_done(rt, mid, today) and shopx.maint_due(rt, today) == []
    assert shopx.parse_len('3/8"') == pytest.approx(9.525) and shopx.parse_len("1 1/4 in") == pytest.approx(31.75)
    assert shopx.parse_len("2 cm") == 20 and shopx.inch_fraction(9.525) == '3/8"' and shopx.inch_fraction(31.75) == '1 1/4"'
    assert "vrták pod závit 6.8 mm" in shopx.thread_info("M8") and "1.25" in shopx.thread_info("m8")
    assert "vrták pod závit 8.75" in shopx.thread_info("M10x1.25")
    assert shopx.torque(20, "Nm")["lb·ft"] == 14.75 and shopx.torque(10, "lb ft")["Nm"] == 13.56


def test_cut_paint_anchor_split_safety_printables(tmp_path):
    r = shopx.cut_plan(2440, [800, 800, 600, 600, 600, 1200], kerf=3)
    assert r["count"] == 3 and all(sum(b["pieces"]) + 3 * (len(b["pieces"]) - 1) + b["rest"] == pytest.approx(2440) for b in r["boards"])
    with pytest.raises(ValueError):
        shopx.cut_plan(1000, [1200])
    s = shopx.sheet_plan((2800, 2070), [(600, 400)] * 10 + [(1200, 800)])
    assert s["count"] == 1 and 0 < s["waste_pct"] < 100
    placed = s["sheets"][0]
    for a in placed:                                                       # nothing overlaps
        for b in placed:
            if a is not b:
                assert a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"]
    p = shopx.paint_need(40, "interiér")
    assert p["liters"] == 11.0 and p["coats"] == 2
    assert shopx.wall_area(4, 3, 2.6, 1, 1) == 33.3
    assert "BEZ příklepu" in shopx.anchor_advice("dutinová cihla", 8) and "Molly" in shopx.anchor_advice("sádrokarton")
    assert "Řekni" in shopx.anchor_advice("sklo")
    sp = shopx.split_plan([500, 200, 100], [256, 256, 256])
    assert sp["pieces"] == 2 and sp["counts"] == [2, 1, 1] and sp["cuts"][0] == [250.0]
    sc = shopx.split_scad(tmp_path / "x.stl", [0, 0, 0], [500, 200, 100], [2, 1, 1], 0, 0, 0)
    assert "cube([250.00, 200.00, 100.00])" in sc and sc.count("cylinder") == 1
    assert len(shopx.safety_for("budu řezat laserem a brousit flexou")) == 2
    stl = shopx.stl_write(tmp_path / "drzak.stl", cube(20))
    pack = shopx.printables_package([stl], tmp_path / "p.zip", "Držák")
    names = zipfile.ZipFile(pack["path"]).namelist()
    assert {"modely/drzak.stl", "obrazky/drzak.png", "POPIS.md"} <= set(names) and pack["pictures"] == 1
    assert "20 × 20 × 20 mm" in zipfile.ZipFile(pack["path"]).read("POPIS.md").decode()


async def test_shop_kit_and_tick(rt, tmp_path):
    r = await tools.call("shop_kit", {"action": "units", "text": "3/8 palce"}, rt)
    assert r.ok and "9.52 mm" in r.summary and '3/8"' in r.summary
    r = await tools.call("shop_kit", {"action": "units", "text": "M6"}, rt)
    assert r.ok and "M6" in r.summary
    r = await tools.call("shop_kit", {"action": "cut", "text": "2440: 2x800, 600"}, rt)
    assert r.ok and r.data["count"] == 1
    r = await tools.call("shop_kit", {"action": "spool_add", "text": "PETG černá 1000 g 549 Kč"}, rt)
    assert r.ok and shopx.spools(rt)[0]["price"] == 549
    r = await tools.call("shop_kit", {"action": "cost", "amount": 100, "hours": 5, "text": "petg"}, rt)
    assert r.ok and "54,90 Kč" in r.summary
    stl = shopx.stl_write(tmp_path / "k.stl", cube())
    r = await tools.call("shop_kit", {"action": "stl", "path": str(stl), "text": "zvětši o 50 %"}, rt)
    assert r.ok and r.data["dims"] == [15, 15, 15]
    r = await tools.call("shop_kit", {"action": "laser", "text": "kruh", "w": 30}, rt)
    assert r.ok and Path(r.data["path"]).read_text().count("\nG2 ") == 1
    shopx.lend(rt, "pila", "Jana")
    rt.db.exec("UPDATE sx_lent SET since=?", ((dt.date.today() - dt.timedelta(days=40)).isoformat(),))
    said = await shopx.tick(rt, dt.datetime.combine(dt.date.today(), dt.time(10, 5)))
    assert any("Jana" in s for s in said)
    assert await shopx.tick(rt, dt.datetime.combine(dt.date.today(), dt.time(11, 0))) == []


# ================================================================== Zábava+
def test_coach_and_mood():
    now = dt.datetime(2026, 11, 25, 20).timestamp()
    losses = [{"result": "loss", "at": now - i * 600} for i in range(3)]
    assert "pauzu" in funx.coach_line(losses, [], now)
    hot = [{"result": "win" if i % 5 else "loss", "at": now - i * 600} for i in range(10)]
    hot[0]["result"] = "win"
    assert "formu" in funx.coach_line(hot, [], now)
    long_day = [{"start": now - 4 * 3600, "seconds": 3.5 * 3600}]
    assert "3.5 h" in funx.coach_line([{"result": "win", "at": now}], long_day, now)
    assert funx.coach_line([], [], now) == ""
    q = funx.mood_query("pusť něco na soustředění", [{"artist": "Daft Punk"}])
    assert q["mood"] == "soustred" and q["query"].startswith("lo-fi")
    assert funx.mood_query("něco na párty", [{"artist": "Daft Punk"}, {"artist": "Daft Punk"}])["query"].startswith("Daft Punk")


def test_scores_and_film(rt):
    funx.score_add(rt, "Carcassonne", "jana", 12)
    funx.score_add(rt, "carcassonne", "Petr", 20)
    funx.score_add(rt, "Carcassonne", "Jana", 15)
    assert [(t["player"], t["points"]) for t in funx.score_table(rt, "CARCASSONNE")] == [("Jana", 27), ("Petr", 20)]
    funx.score_reset(rt, "carcassonne")
    assert funx.score_table(rt, "carcassonne") == []
    assert funx.genres_for("něco ke smíchu a pro děti") == [16, 35, 10751]
    films = funx.parse_tmdb({"results": [{"title": "Film", "release_date": "2020-01-01", "vote_average": 7.5, "overview": "x", "id": 1}]})
    assert films == [{"title": "Film", "year": "2020", "rating": 7.5, "overview": "x", "id": 1}]


async def test_film_needs_key(rt, monkeypatch):
    from jarvis import secrets

    monkeypatch.setattr(secrets, "get", lambda name: "")
    with pytest.raises(ValueError, match="TMDB"):
        await funx.film_tonight(rt, "komedie", ["netflix"])


def test_game_library(tmp_path):
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    lib2 = tmp_path / "Games"
    (lib2 / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n "0" { "path" "%s" }\n "1" { "path" "%s" }\n}\n' % (str(steam).replace("\\", "\\\\"), str(lib2).replace("\\", "\\\\")))
    (steam / "steamapps" / "appmanifest_570.acf").write_text('"AppState"\n{\n "appid" "570"\n "name" "Dota 2"\n "SizeOnDisk" "40000000000"\n}\n')
    (lib2 / "steamapps" / "appmanifest_228980.acf").write_text('"AppState"\n{ "appid" "228980" "name" "Steamworks Common Redistributables" }')
    (lib2 / "steamapps" / "appmanifest_1091500.acf").write_text('"AppState"\n{ "appid" "1091500" "name" "Cyberpunk 2077" "LastPlayed" "1700000000" }')
    g = {x["name"]: x for x in funx.steam_games(steam)}
    assert set(g) == {"Dota 2", "Cyberpunk 2077"} and g["Dota 2"]["launch"] == "steam://rungameid/570" and g["Dota 2"]["size_gb"] == 40
    epic = tmp_path / "Manifests"
    epic.mkdir()
    (epic / "a.item").write_text(json.dumps({"DisplayName": "Hra z Epicu", "AppName": "Fish", "CatalogNamespace": "ns", "CatalogItemId": "id"}))
    e = funx.epic_games(epic)
    assert e[0]["name"] == "Hra z Epicu" and e[0]["launch"].startswith("com.epicgames.launcher://apps/ns%3Aid%3AFish")
    lib = funx.game_library(str(steam), str(epic))
    assert [x["name"] for x in lib] == ["Cyberpunk 2077", "Dota 2", "Hra z Epicu"]
    import random

    picks = [funx.random_game(lib, {"Dota 2"}, random.Random(i))["name"] for i in range(200)]
    assert picks.count("Dota 2") < picks.count("Hra z Epicu")
    assert funx.parse_vdf('"a" { "b" "c" "d" { "e" "f" } }') == {"a": {"b": "c", "d": {"e": "f"}}}


async def test_wishlist(rt):
    class R:
        status_code = 200

        def __init__(self, data):
            self._d = data

        def json(self):
            return self._d

    price = {"v": "29.99"}

    class C:
        async def get(self, url, params=None):
            return R([{"gameID": "1", "external": "Hollow Knight", "cheapest": price["v"], "cheapestDealID": "abc"}])

    funx.wish_add(rt, "Hollow Knight", 10)
    assert await funx.wish_check(rt, C()) == []
    price["v"] = "7.49"
    said = await funx.wish_check(rt, C())
    assert said and "$7.49" in said[0] and "dealID=abc" in said[0]
    assert await funx.wish_check(rt, C()) == []                                # once per drop
    assert funx.parse_cheapshark([]) is None


def test_quiz_flow(rt):
    tok = funx.quiz_create(rt, funx.BUILTIN_QUIZ[:2], "Test")
    jana, kj = funx.quiz_join(rt, tok, "Jana")
    jana2, _ = funx.quiz_join(rt, tok, "Jana")
    assert jana == "Jana" and jana2 == "Jana 2"
    assert not funx.quiz_answer(rt, tok, "Jana", 0, kj)                         # nothing open yet
    d = funx.quiz_next(rt, tok)
    assert d["i"] == 0 and d["open"]
    pub = funx.quiz_public(d)
    assert "ok" not in pub and pub["q"]["q"] == funx.BUILTIN_QUIZ[0]["q"]
    assert not funx.quiz_answer(rt, tok, "Jana", 0, "spatny-klic")
    assert funx.quiz_answer(rt, tok, "Jana", 0, kj) and not funx.quiz_answer(rt, tok, "Jana", 1, kj)
    d = funx.quiz_next(rt, tok)
    assert dict(d["players"])["Jana"] >= 100 and dict(d["players"])["Jana 2"] == 0
    d = funx.quiz_next(rt, tok)
    assert funx.quiz_public(d)["done"]
    qs = funx.parse_quiz('Tady: [{"q": "2+2?", "a": ["3", "4"], "ok": 1}, {"q": "x", "a": ["a"], "ok": 3}]')
    assert qs == [{"q": "2+2?", "a": ["3", "4"], "ok": 1}]
    files = [Path(f"/m/{i:02d} - Píseň {i}.mp3") for i in range(6)]
    import random

    mr = funx.music_round(files, 3, random.Random(1))
    assert len(mr) == 3 and all(q["a"][q["ok"]] == funx.song_name(Path(q["clip"])) for q in mr)
    assert funx.song_name(Path("03 - Píseň_3.mp3")) == "Píseň 3"


def test_quiz_routes(rt, tmp_path):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    rt.cfg.phone_link.public_url = "https://jarvis.example"
    tok = funx.quiz_create(rt, funx.BUILTIN_QUIZ[:1])
    guest = TestClient(create_app(rt, manage_runtime=False), client=("85.1.2.3", 5000))
    host = TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000))
    assert guest.get(f"/quiz/{tok}").status_code == 200 and guest.get("/quiz/nope").status_code == 404
    assert guest.get(f"/quiz/{tok}/host").status_code in (401, 403)
    me = guest.post(f"/api/quiz/{tok}/join", json={"name": "<b>Eva</b>"}).json()
    assert me["name"] == "<b>Eva</b>" and me["key"]
    page = host.get(f"/quiz/{tok}/host")
    assert page.status_code == 200 and "data:image/png;base64," in page.text and f"https://jarvis.example/quiz/{tok}" in page.text
    assert host.post(f"/api/quiz/{tok}/next").json()["open"]
    assert guest.post(f"/api/quiz/{tok}/answer", json={"who": me["name"], "key": me["key"], "pick": 0}).json()["ok"]
    st = guest.get(f"/api/quiz/{tok}").json()
    assert st["answered"] == ["<b>Eva</b>"] and "ok" not in st
    assert host.get(f"/api/quiz/{tok}/host-state").json()["ok"] is None
    assert host.get(f"/api/quiz/{tok}/clip").status_code == 404


def test_podcast_ads():
    segs = [{"start": 0, "end": 30, "text": "Vítejte u dalšího dílu."}, {"start": 30, "end": 45, "text": "Partnerem dnešního dílu je banka X."},
            {"start": 45, "end": 70, "text": "S kódem JARVIS máte slevu 20 %."}, {"start": 70, "end": 100, "text": "Ale zpátky k tématu, dnes o vesmíru."},
            {"start": 400, "end": 420, "text": "Use code POD for 10% off."}, {"start": 420, "end": 600, "text": "Thanks for listening."}]
    cut = funx.ad_segments(segs)
    assert cut[0][0] == 28 and cut[0][1] >= 72 and cut[1][0] == 398
    keep = funx.keep_ranges(cut, 600)
    assert keep[0] == (0.0, 28.0) and keep[-1][1] == 600
    f = funx.ffmpeg_concat_filter(keep)
    assert f.count("atrim") == len(keep) and f.endswith(f"concat=n={len(keep)}:v=0:a=1[out]")
    assert funx.merge_ranges([(0, 5), (4, 8), (10, 12)]) == [(0, 8), (10, 12)]


def test_adventure_and_play_timer(rt):
    story, st = funx.adventure_parse('Stojíš před bránou.\nSTAV: {"misto": "brána", "inventar": ["lucerna"], "zdravi": 10, "cil": "dovnitř"}')
    assert story == "Stojíš před bránou." and st["inventar"] == ["lucerna"]
    assert funx.adventure_parse("Bez stavu")[1] is None
    funx.adventure_save(rt, st, [{"role": "user", "content": "x"}] * 40)
    loaded = funx.adventure_load(rt)
    assert loaded["state"]["misto"] == "brána" and len(loaded["log"]) == 30
    t0 = dt.datetime(2026, 11, 25, 15).timestamp()
    funx.play_start(rt, "Tom", t0)
    assert funx.play_check(rt, {"Tom": 60}, t0 + 50 * 60) == []
    assert funx.play_check(rt, {"Tom": 60}, t0 + 56 * 60) == [{"kid": "Tom", "kind": "warn", "left": 4}]
    assert funx.play_check(rt, {"Tom": 60}, t0 + 57 * 60) == []
    assert funx.play_check(rt, {"Tom": 60}, t0 + 61 * 60)[0]["kind"] == "over"
    assert funx.play_stop(rt, "Tom", t0 + 62 * 60) == 62


def test_eq_albums_video(tmp_path):
    assert funx.eq_for_genre("Alternative Rock") == "rock" and funx.eq_for_genre("Hip-Hop/Rap") == "hiphop"
    assert funx.eq_for_genre("polka") == "flat"
    txt = funx.eq_apo_text("rock")
    assert txt.startswith("# JARVIS: rock\nPreamp: -5 dB") and "16000 4" in txt
    (tmp_path / "config.txt").write_text("Preamp: 0 dB\n", encoding="utf-8")
    funx.eq_apply("pop", tmp_path)
    funx.eq_apply("rock", tmp_path)
    assert (tmp_path / "config.txt").read_text(encoding="utf-8").count("Include: jarvis-eq.txt") == 1
    base = dt.datetime(2026, 7, 1, 10).timestamp()
    items = [("a", base), ("b", base + 600), ("c", base + 3600), ("d", base + 2 * 86400), ("e", base + 2 * 86400 + 60)]
    ev = funx.photo_events(items, 6)
    assert [len(e["photos"]) for e in ev] == [3, 2] and ev[0]["name"] == "2026-07-01"
    photos = tmp_path / "foto"
    photos.mkdir()
    import os

    for i, t in enumerate([base, base + 60, base + 120, base + 90000, base + 90060, base + 90120]):
        f = photos / f"IMG_{i}.jpg"
        f.write_bytes(b"x")
        os.utime(f, (t, t))
    plan = funx.album_plan(photos)
    assert len(plan) == 2 and funx.album_apply(plan, photos / "Alba") == 6
    assert sorted(p.name for p in (photos / "Alba").iterdir()) == [e["name"] for e in plan]
    segs = funx.short_segments(600, 60)
    assert len(segs) == 10 and sum(b - a for a, b in segs) == pytest.approx(60) and segs[0][0] == 30
    assert funx.short_segments(30, 60) == [(0.0, 30)]
    cmd = funx.ffmpeg_short_cmd(Path("in.mp4"), Path("out.mp4"), segs[:2], Path("m.mp3"))
    assert "-stream_loop" in cmd and "amix" in cmd[cmd.index("-filter_complex") + 1]


async def test_series_concerts_discord(rt):
    class R:
        status_code = 200

        def __init__(self, d):
            self._d = d

        def json(self):
            return self._d

    class C:
        async def get(self, url, params=None):
            return R({"id": 5, "name": "Seriál", "_embedded": {"nextepisode": {"season": 2, "number": 4, "airdate": "2026-11-25", "name": "Díl"}}})

    funx.show_add(rt, "Seriál")
    assert funx.show_watched(rt, "seriál", 2, 3)
    said = await funx.shows_check(rt, dt.date(2026, 11, 25), C())
    assert said and "S02E04" in said[0] and "S02E03" in said[0]
    assert await funx.shows_check(rt, dt.date(2026, 11, 25), C()) == []
    assert funx.shows(rt)[0]["tvmaze"] == 5
    ev = funx.parse_ticketmaster({"_embedded": {"events": [{"name": "Kapela", "url": "u", "dates": {"start": {"localDate": "2027-03-01"}},
                                                            "_embedded": {"venues": [{"name": "O2 arena", "city": {"name": "Praha"}}]}}]}})
    assert ev == [{"name": "Kapela", "date": "2027-03-01", "venue": "O2 arena", "city": "Praha", "url": "u"}]
    assert funx.bot_command("!kviz historie") == ("quiz", "historie") and funx.bot_command("!a 2") == ("answer", "2")
    assert funx.bot_command("ahoj") == ("", "")
    ok, why = funx.discord_ready()
    assert ok or "discord" in why.lower()


def test_sound_packs(tmp_path):
    (tmp_path / "chyba.mp3").write_bytes(b"own")                       # your own sound stays
    r = funx.install_pack("marimba", tmp_path)
    assert "chyba" in r["kept"] and len(r["written"]) == 4
    with wave.open(str(tmp_path / "hotovo.wav")) as w:
        assert w.getframerate() == 44100 and 0.3 < w.getnframes() / 44100 < 1.5
    r = funx.install_pack("scifi", tmp_path)
    assert len(r["written"]) == 4 and (tmp_path / "chyba.mp3").read_bytes() == b"own"
    assert funx.remove_pack(tmp_path) == 4 and (tmp_path / "chyba.mp3").exists() and not (tmp_path / "hotovo.wav").exists()
    with pytest.raises(ValueError):
        funx.install_pack("nic", tmp_path)


async def test_fun_kit_and_tick(rt, tmp_path):
    r = await tools.call("fun_kit", {"action": "score", "name": "Eva", "amount": 5, "text": "Dixit"}, rt)
    assert r.ok and "Eva 5" in r.summary
    rt.sounds_dir = lambda: tmp_path
    r = await tools.call("fun_kit", {"action": "sounds", "text": "krystal"}, rt)
    assert r.ok and (tmp_path / "upozorneni.wav").exists()
    r = await tools.call("fun_kit", {"action": "sounds", "text": "původní"}, rt)
    assert r.ok and not (tmp_path / "upozorneni.wav").exists()
    r = await tools.call("fun_kit", {"action": "quiz"}, rt)
    assert r.ok and funx.quiz_get(rt, r.data["token"])["q"]
    assert tools.REGISTRY["fun_kit"].danger_if({"action": "albums_apply"}) and not tools.REGISTRY["fun_kit"].danger_if({"action": "albums"})
    rt.cfg.funx.play_limits = {"Tom": 30}
    funx.play_start(rt, "Tom", time.time() - 27 * 60)
    said = await funx.tick(rt, dt.datetime.now())
    assert any("Tom" in s for s in said)


async def test_game_result_gets_a_coach_line(rt):
    for i in range(3):
        rt.gamecoach.log_result("prohra", game="Valorant", now=time.time() - 60 * (3 - i))
    r = await tools.call("game_result", {"result": "prohra", "game": "Valorant"}, rt)
    assert r.ok and "pauzu" in r.summary
