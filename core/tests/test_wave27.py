"""OMEGA wave 27 (lab): chart insights, SQLite column lineage (through views), physics against analytic results,
citations against a scripted Crossref, experiment designs, prototype test plan and results, adaptive circuit tutor."""
import json
import math
import random
import re
import sqlite3

import httpx
import pytest

from jarvis import lab, tools

tools.load_builtin()


async def test_chart_insights(rt, tmp_path):
    d = tmp_path / "graf"
    d.mkdir()
    months = [f"2026-{m:02d}" for m in range(1, 13)] + [f"2027-{m:02d}" for m in range(1, 13)]
    sales = [100 + (30 if i >= 12 else 0) + (5 if i % 4 == 0 else 0) for i in range(24)]
    sales[20] = 400                                                       # one wild value
    visits = [s * 10 + 3 for s in sales]
    (d / "data.csv").write_text("mesic;trzby;navstevy\n" + "\n".join(f"{m};{s};{v}" for m, s, v in zip(months, sales, visits)) + "\n", encoding="utf-8")
    r = await tools.call("chart_insights", {"file": str(d / "data.csv"), "label_column": "mesic"}, rt)
    t = r.data["series"]["trzby"]
    assert t["change_point"]["at"] == "2027-01" and t["outliers"] == [{"at": "2027-09", "value": 400}] and t["max"]["at"] == "2027-09"
    assert r.data["correlations"][0]["r"] == pytest.approx(1.0) and "neznamená, že jedno způsobuje druhé" in r.summary
    flat = lab.chart_insights({"x": [5, 5.1, 4.9, 5, 5.05, 4.95]})
    assert flat["series"]["x"]["trend"] == "stagnuje"
    wave = lab.chart_insights({"teplota": [math.sin(2 * math.pi * i / 6) for i in range(36)]})
    assert wave["series"]["teplota"]["period"]["lag"] == 6
    up = lab.chart_insights({"u": [i * 2 + (1 if i % 2 else 0) for i in range(20)]})
    assert up["series"]["u"]["trend"] == "roste"


def test_decimal_dots_stay_decimals(tmp_path):
    from jarvis import science

    d = tmp_path / "csv"
    d.mkdir()
    (d / "senzor.csv").write_text("cas;teplota\n1;20.995\n2;21.003\n3;19.500\n", encoding="utf-8")
    science.clean_csv(d / "senzor.csv", d / "cisty.csv")
    assert (d / "cisty.csv").read_text(encoding="utf-8").splitlines()[1:] == ["1;20.995", "2;21.003", "3;19.5"]
    assert science.column_nums(["1.250,50", "300"]) == [1250.5, 300.0] and science.column_nums(["1.250.000", "5"]) == [1250000.0, 5.0]


async def test_data_lineage(rt, tmp_path):
    d = tmp_path / "db"
    d.mkdir()
    c = sqlite3.connect(d / "shop.db")
    c.executescript("""
      create table orders(id, customer_id, amount, vat, created, status);
      create table customers(id, name, email, city);
      create view revenue as select c.name as zakaznik, c.city mesto, sum(o.amount + o.vat) as trzba, c.id
        from orders o join customers c on c.id = o.customer_id where o.status = 'paid' group by c.id;
      create view top as select zakaznik, trzba * 1.21 as s_dph from revenue where trzba > 100;""")
    c.close()
    r = await tools.call("data_lineage", {"database": str(d / "shop.db")}, rt)
    by = {v["name"]: {x["column"]: x for x in v["columns"]} for v in r.data}
    assert by["revenue"]["trzba"]["from"] == ["orders.amount", "orders.vat"] and by["revenue"]["trzba"]["computed"]
    assert by["revenue"]["mesto"]["from"] == ["customers.city"] and not by["revenue"]["mesto"]["computed"]
    assert by["top"]["zakaznik"]["from"] == ["customers.name"] and by["top"]["s_dph"]["from"] == ["orders.amount", "orders.vat"]
    rev = next(v for v in r.data if v["name"] == "revenue")
    assert rev["filters_and_joins"] == ["customers.id", "orders.customer_id", "orders.status"]
    q = await tools.call("data_lineage", {"database": str(d / "shop.db"), "sql": "select o.amount, email from orders o join customers c on c.id = o.customer_id"}, rt)
    assert [x["from"] for x in q.data["columns"]] == [["orders.amount"], ["customers.email"]]
    assert not (await tools.call("data_lineage", {"database": str(d / "shop.db"), "view": "neni"}, rt)).ok
    before = (d / "shop.db").read_bytes()
    await tools.call("data_lineage", {"database": str(d / "shop.db"), "view": "top"}, rt)
    assert (d / "shop.db").read_bytes() == before                         # read-only


async def test_physics_against_analytic(rt):
    r = await tools.call("physics_sim", {"model": "projectile", "params": {"v0": 20, "angle": 45}}, rt)
    assert r.data["range_m"] == pytest.approx(20 ** 2 / 9.81, abs=0.01) and r.data["max_height_m"] == pytest.approx(20 ** 2 / (4 * 9.81), abs=0.01)
    drag = lab.simulate("projectile", {"v0": 20, "angle": 45, "drag": 0.02})
    assert drag["range_m"] < r.data["range_m"] and drag["impact_speed"] < 20
    small = lab.simulate("pendulum", {"length": 1, "angle": 5})
    assert small["period_s"] == pytest.approx(2 * math.pi * math.sqrt(1 / 9.81), rel=0.001)
    big = lab.simulate("pendulum", {"length": 1, "angle": 60})
    assert big["difference_pct"] == pytest.approx(7.32, abs=0.1)          # T/T0 = 2K(sin 30°)/π ≈ 1.0732
    sp = lab.simulate("spring", {"mass": 1, "k": 100, "c": 2, "x0": 0.1})
    z = 0.1
    assert sp["overshoot_pct"] == pytest.approx(100 * math.exp(-math.pi * z / math.sqrt(1 - z * z)), abs=0.3) and sp["kind"].startswith("podtlumené")
    assert lab.simulate("rc", {"r": 1000, "c": 1e-6})["t99_s"] == pytest.approx(1e-3 * math.log(100), rel=1e-4)
    assert lab.simulate("cooling", {"t0": 90, "env": 20, "k": 0.05, "target": 40})["time_to_target"] == pytest.approx(math.log(70 / 20) / 0.05, rel=1e-4)
    s = await tools.call("physics_sim", {"model": "projectile", "params": {"v0": 20}, "sweep_param": "angle", "values": [15, 30, 45, 60, 75], "output": "range_m"}, rt)
    assert s.data["best"]["angle"] == 45 and s.data["rows"][0]["range_m"] == pytest.approx(s.data["rows"][-1]["range_m"], abs=0.01)
    assert not (await tools.call("physics_sim", {"model": "raketa", "params": {}}, rt)).ok
    assert "Chybí parametr" in (await tools.call("physics_sim", {"model": "spring", "params": {"mass": 1}}, rt)).summary


WORKS = {"10.1000/real": {"title": ["Deep learning for cats"], "issued": {"date-parts": [[2019]]}, "author": [{"family": "Novák"}], "DOI": "10.1000/real",
                          "container-title": ["J Cats"]},
         "10.1000/retracted": {"title": ["Vaccines cause everything"], "issued": {"date-parts": [[1998]]}, "author": [{"family": "Wakefield"}],
                               "DOI": "10.1000/retracted", "container-title": ["Lancet"]}}


def crossref(req: httpx.Request) -> httpx.Response:
    assert req.url.host == "api.crossref.org"
    path = req.url.path
    if path.startswith("/works/"):
        doi = path[len("/works/"):]
        return httpx.Response(200, json={"message": WORKS[doi]}) if doi in WORKS else httpx.Response(404, text="Resource not found.")
    f = req.url.params.get("filter", "")
    if f == "updates:10.1000/retracted":
        return httpx.Response(200, json={"message": {"items": [{"update-to": [{"DOI": "10.1000/retracted", "type": "retraction"}]}]}})
    if f:
        return httpx.Response(200, json={"message": {"items": []}})
    if "Attention" in req.url.params.get("query.bibliographic", ""):
        return httpx.Response(200, json={"message": {"items": [{"title": ["Attention is all you need"], "DOI": "10.5555/attn", "issued": {"date-parts": [[2017]]},
                                                                "author": [{"family": "Vaswani"}]}]}})
    return httpx.Response(200, json={"message": {"items": []}})


async def test_citation_check(rt):
    rt.transport = httpx.MockTransport(crossref)
    text = ("1. Novák, J. (2019). Deep learning for cats. J Cats. https://doi.org/10.1000/real\n"
            "2. Smith, A. (2020). Something that was never written. doi:10.1000/fake\n"
            "3. Wakefield, A. (1998). Vaccines cause everything. Lancet. 10.1000/retracted.\n"
            "4. Vaswani, A. et al. (2016). Attention is all you need. NeurIPS proceedings.\n")
    r = await tools.call("citation_check", {"text": text}, rt)
    a, b, c, d = r.data
    assert a["status"] == "nalezeno" and a["problems"] == [] and a["year"] == 2019
    assert b["status"] == "neexistuje" and "vymyšlená" in b["problems"][0]
    assert c["retracted"] and c["problems"][0].startswith("ČLÁNEK BYL STAŽEN")
    assert d["status"] == "dohledáno" and d["doi"] == "10.5555/attn" and "rok 2016 ≠ 2017" in d["problems"]
    assert "10.1000/fake" in r.summary and not (await tools.call("citation_check", {"text": "ahoj"}, rt)).ok


async def test_experiment_design(rt):
    f = [{"name": "teplota", "levels": [180, 200]}, {"name": "čas", "levels": [10, 15]}, {"name": "mouka", "levels": ["hladká", "polohrubá"]}]
    r = await tools.call("experiment_design", {"factors": f, "replicates": 2, "seed": 7, "blocks": 2}, rt)
    runs = r.data["runs"]
    assert r.data["total"] == 16 and len({(x["teplota"], x["čas"], x["mouka"]) for x in runs}) == 8
    assert all(x["block"] == 1 for x in runs[:8]) and [x["run"] for x in runs] == list(range(1, 17))
    assert runs == (await tools.call("experiment_design", {"factors": f, "replicates": 2, "seed": 7, "blocks": 2}, rt)).data["runs"]
    assert open(r.data["sheet"], encoding="utf-8-sig").read().startswith("run;block;teplota;čas;mouka;výsledek")
    four = f + [{"name": "kvasnice", "levels": [1, 2]}]
    h = lab.experiment_design(four, half_fraction=True)
    assert h["cells"] == 8 and h["resolution"] == 4
    code = {"teplota": {180: -1, 200: 1}, "čas": {10: -1, 15: 1}, "mouka": {"hladká": -1, "polohrubá": 1}, "kvasnice": {1: -1, 2: 1}}
    assert all(code["kvasnice"][x["kvasnice"]] == code["teplota"][x["teplota"]] * code["čas"][x["čas"]] * code["mouka"][x["mouka"]] for x in h["runs"])
    p = lab.experiment_design(f, effect=1, sd=1)
    assert p["power"]["runs_total"] == 32 and p["replicates"] == 4
    assert not (await tools.call("experiment_design", {"factors": [{"name": "a", "levels": [1]}]}, rt)).ok


async def test_prototype_tests(rt, tmp_path):
    assert lab.success_run(0.9, 0.9) == 22 and lab.success_run(0.9, 0.9, failures=1) == 38 and lab.success_run(0.95, 0.99) == 299
    reqs = [{"name": "pád z 1 m", "destructive": True}, {"name": "napětí", "min": 4.75, "max": 5.25, "unit": "V"}, {"name": "výdrž", "min": 8, "unit": "h"}]
    r = await tools.call("prototype_test_plan", {"requirements": reqs}, rt)
    assert [p["requirement"] for p in r.data["plan"]] == ["napětí", "výdrž", "pád z 1 m"] and r.data["samples_per_test"] == 22
    sheet = open(r.data["sheet_path"], encoding="utf-8-sig").read().splitlines()
    assert len(sheet) == 1 + 3 * 22 and sheet[1] == "T01;napětí;1;;V"
    d = tmp_path / "vysledky"
    d.mkdir()
    rng = random.Random(2)
    rows = ["test;požadavek;vzorek;naměřeno;jednotka"] + [f"T01;napětí;{i};{5 + rng.gauss(0, 0.03):.3f};V" for i in range(22)]
    rows += [f"T02;výdrž;{i};{9 if i else 7.5};h" for i in range(22)]
    (d / "v.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    e = await tools.call("prototype_test_results", {"requirements": reqs, "file": str(d / "v.csv")}, rt)
    v = {x["requirement"]: x for x in e.data}
    assert v["napětí"]["verdict"] == "vyhověl" and v["napětí"]["cpk"] > 2 and v["napětí"]["reliability_shown"] == round(0.1 ** (1 / 22), 4)
    assert v["výdrž"]["verdict"] == "nevyhověl" and v["výdrž"]["failed"] == 1 and v["pád z 1 m"]["verdict"] == "neměřeno"


def test_problems_have_right_answers():
    for seed in range(30):
        p3 = lab.problem(3, random.Random(seed))
        r1, r2 = [float(x) for x in re.findall(r"([\d.]+) Ω", p3["question"])]
        assert p3["answer"] == pytest.approx(1 / (1 / r1 + 1 / r2))
        p4 = lab.problem(4, random.Random(seed))
        u = float(re.search(r"Zdroj ([\d.]+) V", p4["question"]).group(1))
        a, b, c = [float(x) for x in re.findall(r"R\d = ([\d.]+) Ω", p4["question"])]
        total = a + b * c / (b + c)
        assert p4["answer"] == pytest.approx(u / total * (b * c / (b + c)) / c)
    assert lab.parse_answer("2k2") == (2200.0, "Ω") and lab.parse_answer("12 mA") == (0.012, "A") and lab.parse_answer("4,7 kΩ") == (4700.0, "Ω")
    assert lab.parse_answer("0,15 W") == (0.15, "W") and lab.parse_answer("hodně") is None


async def test_tutor_adapts(rt):
    def current():
        return json.loads(rt.db.one("SELECT current FROM tutor_progress WHERE subject='obvody'")["current"])

    q = await tools.call("circuit_tutor", {}, rt)
    assert q.data["level"] == 1
    for _ in range(3):                                                     # three right in a row → harder
        p = current()
        r = await tools.call("circuit_tutor", {"answer": f"{p['answer']:.6g} {p['unit']}"}, rt)
        assert r.data["correct"], r.summary
    assert r.data["level"] == 2 and "těžší" in r.summary and r.data["next"]["level"] == 2
    p = current()
    w = await tools.call("circuit_tutor", {"answer": f"{p['answer'] * 3:.6g} {p['unit']}"}, rt)
    assert not w.data["correct"] and "správně je" in w.summary and w.data["level"] == 2
    p = current()
    w = await tools.call("circuit_tutor", {"answer": "5 W" if p["unit"] != "W" else "5 V"}, rt)
    assert not w.data["unit_ok"] and w.data["level"] == 1 and "níž" in w.summary       # two wrong of the last three → easier
    assert w.data["accuracy"] == 60 and w.data["answered"] == 5
    assert not (await tools.call("circuit_tutor", {"answer": "nevím"}, rt)).ok
