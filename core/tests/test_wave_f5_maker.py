"""Wave F5d: meaning search (316), automatic versions (328), colours (133 / 282), thumbnail (132), sensors (163 / 486),
equations (766 / 106), notebooks (768), concept map (464), article comparison (386), research → to-dos (390),
learning schedule (452)."""
import json
import os
import time

import pytest

from jarvis import devops, fsplus, makerplus, tools

tools.load_builtin()


def test_lexical_meaning_search_handles_czech_endings():
    docs = [("a.txt", "Nájemní smlouva na byt v Brně, nájemné 15 000 Kč měsíčně."),
            ("b.txt", "Recept na bábovku s kakaem."), ("c.txt", "Faktura za opravu auta.")]
    hits = fsplus.lexical_rank("smlouvy o nájmu bytu", docs)
    assert hits[0]["path"] == "a.txt"


async def test_find_by_meaning_tool(rt, tmp_path):
    (tmp_path / "najem.txt").write_text("Smlouva o nájmu bytu, nájemce a pronajímatel.", encoding="utf-8")
    (tmp_path / "recept.txt").write_text("Bábovka mouka cukr.", encoding="utf-8")
    r = await tools.REGISTRY["find_by_meaning"].func(rt, "pronájem bytu", str(tmp_path))
    assert r.ok and "najem.txt" in r.summary.split(";")[0]


def test_version_watch(tmp_path, monkeypatch):
    from jarvis import fileuniverse as fu

    monkeypatch.setattr(fu, "versions_dir", lambda: tmp_path / "v")
    d = tmp_path / "docs"
    d.mkdir()
    f = d / "zprava.txt"
    f.write_text("verze 1", encoding="utf-8")
    vw = fsplus.VersionWatch(None)
    assert vw.scan([d]) == [] and len(fu.list_versions(f)) == 1      # first look: the starting state only
    f.write_text("verze 2", encoding="utf-8")
    os.utime(f, (time.time() + 5, time.time() + 5))
    saved = vw.scan([d])
    assert len(saved) == 1 and len(fu.list_versions(f)) == 2
    assert vw.scan([d]) == []                                          # unchanged → nothing new


def test_colours(tmp_path):
    from PIL import Image

    d = makerplus.describe_color("#1e88e5")
    assert d["name"] == "modrá" and d["text_on_it"] in ("#000000", "#ffffff")
    im = Image.new("RGB", (100, 100), (220, 30, 30))
    for x in range(30):
        for y in range(100):
            im.putpixel((x, y), (20, 20, 20))
    p = tmp_path / "f.png"
    im.save(p)
    pal = makerplus.palette_from_image(p, 2)
    assert pal[0]["name"] in ("červená", "tmavě červená") and pal[0]["share"] == pytest.approx(70, abs=2)
    assert makerplus.pixel_color(p, 5, 5) == "#141414"


def test_thumbnail(tmp_path):
    from PIL import Image

    out = makerplus.thumbnail("Jak postavit robota za jeden víkend", tmp_path / "t.jpg")
    with Image.open(out) as im:
        assert im.size == (1280, 720)


def test_sensor_diagnose_and_fusion():
    good = [20 + 0.1 * (i % 3) + 0.01 * i for i in range(60)]
    assert makerplus.sensor_diagnose(good, -40, 85)["ok"]
    stuck = [21.5] * 40
    assert any("zamrzlá" in x for x in makerplus.sensor_diagnose(stuck)["issues"])
    spiky = [20 + 0.1 * (i % 2) for i in range(50)]
    spiky[25] = 95
    r = makerplus.sensor_diagnose(spiky, -40, 85)
    assert any("špičky" in x for x in r["issues"]) and any("mimo rozsah" in x for x in r["issues"])
    gaps = [20.0, None, None, 20.1, None, 20.2, 20.1, None, 20.0, 20.2]
    assert any("výpadky" in x for x in makerplus.sensor_diagnose(gaps)["issues"])
    f = makerplus.sensor_fusion({"přesné": [20.0, 20.1, 20.0, 20.1, 20.0], "hlučné": [19.0, 21.5, 18.5, 22.0, 19.5]})
    assert f["weights"]["přesné"] > 0.9 and abs(f["fused"][0] - 20.0) < 0.1
    f2 = makerplus.sensor_fusion({"a": [1.0, None, 1.0], "b": [3.0, 3.0, None]}, {"a": 1, "b": 1})
    assert f2["fused"] == [2.0, 3.0, 1.0]


@pytest.mark.parametrize("eq,sol", [("2x + 3 = 11", [4.0]), ("x^2 - 5x + 6 = 0", [2.0, 3.0]), ("x² + 2x + 1 = 0", [-1.0]),
                                    ("3x - 2 = x + 4", [3.0]), ("x^2 + 1 = 0", []), ("-x + 0,5 = 2", [-1.5])])
def test_solve_steps(eq, sol):
    r = makerplus.solve_steps(eq)
    assert r["solutions"] == sol and r["steps"][0].startswith("Zadání")


def test_solve_steps_rejects_nonsense():
    with pytest.raises(ValueError):
        makerplus.solve_steps("sin(x) = 1")
    with pytest.raises(ValueError):
        makerplus.solve_steps("x^3 = 8")


async def test_notebook_runner(rt, tmp_path):
    nb = {"cells": [{"cell_type": "markdown", "source": "# Ahoj"},
                    {"cell_type": "code", "source": ["a = 21\n", "%matplotlib inline\n", "print(a * 2)"]},
                    {"cell_type": "code", "source": "print('dál', a)"}], "nbformat": 4, "nbformat_minor": 5, "metadata": {}}
    p = tmp_path / "n.ipynb"
    p.write_text(json.dumps(nb), encoding="utf-8")
    script, cells = devops.notebook_script(nb)
    assert cells == [1, 2] and "%matplotlib" not in script
    r = await tools.REGISTRY["run_notebook"].func(rt, str(p))
    assert r.ok, r.summary
    out = json.loads((tmp_path / "n_vystup.ipynb").read_text(encoding="utf-8"))
    assert out["cells"][1]["outputs"][0]["text"].strip() == "42" and "dál 21" in out["cells"][2]["outputs"][0]["text"]
    nb["cells"][2]["source"] = "1/0"
    p.write_text(json.dumps(nb), encoding="utf-8")
    r = await tools.REGISTRY["run_notebook"].func(rt, str(p))
    assert not r.ok and "Buňka 2 spadla" in r.summary and "ZeroDivisionError" in r.summary
    assert tools.REGISTRY["run_notebook"].danger


def test_concept_map_compare_actions():
    text = ("Fotosyntéza probíhá v chloroplastech. Chloroplasty obsahují chlorofyl. Chlorofyl pohlcuje světlo. "
            "Světlo pohání fotosyntézu a vzniká glukóza. Glukóza je zdroj energie.")
    g = makerplus.concept_map(text)
    ids = {n["id"] for n in g["nodes"]}
    assert {"chlorofyl", "světlo"} <= ids and any({e["a"], e["b"]} == {"chlorofyl", "světlo"} for e in g["edges"])
    c = makerplus.compare_texts("Inflace v roce 2025 byla 3,1 %. Centrální banka snížila sazby.",
                                "Inflace v roce 2025 dosáhla 2,8 %. Centrální banka snížila úrokové sazby.")
    assert "3,1 %" in c["numbers_only_a"] and "2,8 %" in c["numbers_only_b"] and c["same_claims"]
    acts = makerplus.research_actions("Výsledky jsou slibné. Je potřeba ověřit vzorek na větší skupině. Doporučuji zopakovat měření v zimě.")
    assert acts == ["Ověřit vzorek na větší skupině", "Doporučuji zopakovat měření v zimě"]


async def test_learning_schedule(rt):
    r = await tools.REGISTRY["learning_schedule"].func(rt, {"derivace": ["limity", "funkce"], "limity": ["funkce"], "funkce": []},
                                                       "derivace", 1, None, "2026-11-02")
    assert r.ok and r.data["order"] == ["funkce", "limity", "derivace"]
    assert r.data["plan"]["2026-11-02"] == ["nové: funkce"] and "opakovat: funkce" in r.data["plan"]["2026-11-03"]
