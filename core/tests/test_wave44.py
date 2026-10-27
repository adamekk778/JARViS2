"""Wave 44: responsive layout, animation curves, glass, icon set, motion timeline, layout heatmap."""
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from jarvis import designplus, tools

tools.load_builtin()


def test_layout_issues():
    phone = {"width": 360, "label": "telefon", "vw": 360, "scroll": 620, "overflow": [{"sel": "table.big", "right": 620}, {"sel": "img", "right": 400}],
             "small_text": [{"sel": "small", "size": 10}], "small_targets": [{"sel": "a.x", "w": 20, "h": 18}], "overlaps": [["a.x", "button.y"]]}
    desk = {"width": 1440, "label": "monitor", "vw": 1440, "scroll": 1440, "overflow": [], "small_text": [], "small_targets": [{"sel": "a", "w": 30, "h": 20}], "overlaps": []}
    r = designplus.layout_issues([phone, desk])
    assert r["score"] == 55 and not r["ok"]
    assert "table.big" in r["displays"][0]["issues"][0] and r["displays"][1]["issues"] == []      # small targets only matter on touch widths


@pytest.mark.skipif(not os.environ.get("JARVIS_CHROMIUM"), reason="needs a Chromium")
async def test_analyze_layout_real_browser(tmp_path):
    page = tmp_path / "p.html"
    page.write_text("<html><body style='margin:0'><div style='width:900px;height:50px;background:red' class='banner'></div>"
                    "<a href='#' style='font-size:9px'>drobný odkaz</a></body></html>", encoding="utf-8")
    r = await designplus.analyze_layout(str(page), tmp_path)
    phone = r["displays"][0]
    assert any("div.banner" in i for i in phone["issues"]) and any("menší než 12" in i for i in phone["issues"])
    assert r["displays"][-1]["issues"] == ["1× písmo menší než 12 px"] and (tmp_path / "prehled.png").exists()


def test_curves():
    assert designplus.parse_easing("ease-in-out") == (0.42, 0, 0.58, 1)
    c = designplus.parse_easing("cubic-bezier(.34, 1.56, .64, 1)")
    info = designplus.describe_curve(c)
    assert info["overshoot"] and info["closest"] == "easeOutBack" and info["max"] > 1.05
    assert designplus.describe_curve(designplus.NAMED["ease-in"])["kind"].startswith("zrychluje")
    assert designplus.describe_curve(designplus.NAMED["linear"])["kind"] == "lineární"
    assert designplus.ease_at(designplus.NAMED["linear"], 0.3) == pytest.approx(0.3, abs=1e-6)
    with pytest.raises(ValueError):
        designplus.parse_easing("cubic-bezier(2, 0, 1, 1)")


def test_fit_bezier():
    target = designplus.NAMED["easeOutQuart"]
    pts = [(x / 10, designplus.ease_at(target, x / 10)) for x in range(11)]
    fit = designplus.fit_bezier(pts)
    assert max(abs(designplus.ease_at(fit, x) - y) for x, y in pts) < 0.02


async def test_curve_tool(rt):
    r = await tools.call("animation_curve", {"easing": "ease-out"}, rt)
    assert r.ok and "zpomaluje" in r.summary and r.attachments[0].endswith("editor.html")
    assert "[0, 0, 0.58, 1]" in open(r.attachments[0], encoding="utf-8").read()


def test_glass_contrast():
    g = designplus.glass("#ffffff", 0.1, 20, ["#000000", "#ffffff"])
    assert g["raised"] and g["ok"] and g["worst_contrast"] >= 4.5 and "backdrop-filter: blur(20px)" in g["css"] and g["text"] == "#111827"
    d = designplus.glass("#0b0d12", 0.6, 12, ["#ffffff"])
    assert d["text"] == "#f9fafb" and d["ok"]


SVG_A = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 2h20" stroke="#ff0000" stroke-width="2" fill="none"/></svg>'
SVG_B = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5" stroke="currentColor" stroke-width="1.5" fill="none"/></svg>'
SVG_C = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="20" height="20" fill="#000"/></svg>'


async def test_icon_set(rt, tmp_path):
    for n, s in (("Home Icon", SVG_A), ("search", SVG_B), ("box", SVG_C)):
        (tmp_path / f"{n}.svg").write_text(s)
    (tmp_path / "broken.svg").write_text("<svg")
    r = designplus.build_icon_set(sorted(tmp_path.glob("*.svg")))
    assert r["names"] == ["box", "home-icon", "search"] and r["recolored"] == ["box", "home-icon"]
    assert "#ff0000" not in r["sprite"] and 'id="i-home-icon"' in r["sprite"] and "ns0" not in r["sprite"]
    text = " ".join(r["report"])
    assert "broken.svg" in text and "box: jiná velikost plátna (0 0 32 32 místo 0 0 24 24)" in text and "tloušťky čar: 1.5, 2" in text
    assert "míchají se obrysové a vyplněné" in text
    t = await tools.call("icon_set", {"folder": str(tmp_path)}, rt)
    assert t.ok and len(t.attachments) == 3


SPEC = """logo: opacity 0→1 0–0.5s ease-out
logo: scale 0.8->1 0-0.6s
nadpis: y 20→0 0.4–1s ease-out
nadpis: opacity 0→1 0.4–1s
logo: scale 1.2→1 0.5-1s"""


def test_timeline():
    tr = designplus.parse_timeline(SPEC)
    assert len(tr) == 5 and tr[2] == {"layer": "nadpis", "prop": "y", "from": 20, "to": 0, "start": 0.4, "end": 1.0, "ease": "ease-out"}
    issues = designplus.timeline_check(tr)
    assert issues == ["logo: dvě animace scale se překrývají (0–0.6 s a 0.5–1 s)"]
    r = designplus.timeline_css(tr[:4])
    assert r["duration"] == 1.0 and r["layers"] == ["logo", "nadpis"]
    assert "@keyframes logo" in r["css"] and "transform: scale(0.8)" in r["css"] and "40.00%" in r["css"]
    assert "translateY(0.0px)" in r["css"]
    with pytest.raises(ValueError):
        designplus.parse_timeline("logo: wobble 0→1 0–1s")
    with pytest.raises(ValueError):
        designplus.parse_timeline("logo: opacity 0→1 1–0.5s")


def test_heatmap():
    img = Image.new("RGB", (480, 320), "white")
    d = ImageDraw.Draw(img)
    for i in range(0, 200, 6):                       # a busy block on the left
        d.line([(10, 10 + i), (180, 10 + i)], fill="black")
    r = designplus.layout_heatmap(img)
    assert r["center"][0] < 0.4 and "vlevo" in r["balance"] and r["empty_share"] > 0.5
    assert r["hotspots"][0]["x"] < 200 and r["image"].size == (480, 312)
    blank = designplus.layout_heatmap(Image.new("RGB", (240, 240), "white"))
    assert blank["empty_share"] == 1.0 and "hodně prázdného" in blank["advice"][0]
    assert np.asarray(r["image"]).shape[2] == 4
