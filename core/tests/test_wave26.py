"""OMEGA wave 26 (creative production): brand colours, social formats cropped by detail, caption variants, asset
licences and provenance, camera moves and lights (Blender scripts), lip-sync, mix advice, render cost, colour
profiles, storyboard → EDL + SRT, and a click-through demo opened and clicked in a real headless browser."""
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest
from conftest import FakeRouter
from PIL import Image, ImageCms

from jarvis import creative, media, tools

tools.load_builtin()
CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def _dir(tmp_path, name):
    d = tmp_path / name                                                # tmp_path itself also holds JARVIS_HOME
    d.mkdir()
    return d


async def test_brand_check(rt, tmp_path):
    d = _dir(tmp_path, "znacka")
    good = Image.new("RGB", (400, 300), "white")
    good.paste((37, 99, 235), (0, 0, 400, 90))
    good.save(d / "banner.png")
    bad = Image.new("RGB", (300, 300), "white")
    bad.paste((230, 30, 30), (0, 0, 300, 150))
    bad.save(d / "akce.png")
    r = await tools.call("brand_check", {"path": str(d), "palette": ["#2563eb", "#f59e0b"]}, rt)
    rows = {x["file"]: x for x in r.data["images"]}
    assert rows["banner.png"]["ok"] and rows["banner.png"]["off_brand_pct"] == 0
    assert not rows["akce.png"]["ok"] and rows["akce.png"]["off_brand_pct"] == pytest.approx(50, abs=2) and rows["akce.png"]["off"][0]["color"] == "#e61e1e"
    assert r.data["aspect_ratios"] == [1.0, 1.33] and "akce.png" in r.summary


async def test_social_formats_crop_to_detail(rt, tmp_path):
    d = _dir(tmp_path, "foto")
    rng = np.random.default_rng(1)
    arr = np.full((900, 1600, 3), 128, dtype=np.uint8)
    arr[:, 1100:1500] = rng.integers(0, 255, (900, 400, 3))           # all the detail is on the right
    Image.fromarray(arr).save(d / "foto.png")
    r = await tools.call("social_formats", {"image": str(d / "foto.png"), "formats": ["instagram", "story", "youtube-nahled"]}, rt)
    got = {x["format"]: x for x in r.data}
    assert Image.open(got["instagram"]["path"]).size == (1080, 1080) and Image.open(got["story"]["path"]).size == (1080, 1920)
    x0, _, x1, _ = got["instagram"]["crop"]
    assert x1 - x0 == 900 and x0 <= 1100 and x1 >= 1500                 # the square sits over the detailed part
    assert got["youtube-nahled"]["crop"] == [0, 0, 1600, 900] and not (await tools.call("social_formats", {"image": str(d / "foto.png"), "formats": ["tv"]}, rt)).ok


async def test_caption_variants(rt):
    long = "Víte, že " + "opravdu " * 40 + "#kava"
    rt.router = FakeRouter([json.dumps({"variants": [{"angle": "otázka", "text": "Kolik kafe denně je moc? Zjistili jsme to ☕ #kava"},
                                                     {"angle": "dlouhý", "text": long}]}, ensure_ascii=False)])
    r = await tools.call("caption_variants", {"about": "nová kavárna", "platform": "x"}, rt)
    assert r.data[0]["angle"] == "otázka" and r.data[0]["issues"] == [] and r.data[1]["length"] > 280
    assert any("limit 280" in i for i in r.data[1]["issues"]) and "nová kavárna" in rt.router.calls[0]["messages"][-1]["content"]


async def test_asset_register_report_lineage(rt, tmp_path):
    d = _dir(tmp_path, "assets")
    Image.new("RGB", (64, 64), "red").save(d / "foto.png")
    Image.new("RGB", (32, 32), "red").save(d / "foto-maly.png")
    Image.new("RGB", (8, 8), "blue").save(d / "neevidovany.png")
    (d / "font.ttf").write_bytes(b"font-bytes")
    r = await tools.call("asset_register", {"file": str(d / "foto.png"), "source": "unsplash.com", "author": "Jana Nová", "license": "CC BY 4.0"}, rt)
    assert r.ok and len(r.data["sha256"]) == 64
    r = await tools.call("asset_register", {"file": str(d / "foto-maly.png"), "derived_from": str(d / "foto.png"), "note": "zmenšeno"}, rt)
    assert r.data["license"] == "CC BY 4.0"                             # inherited from the original
    await tools.call("asset_register", {"file": str(d / "font.ttf"), "license": "komerční", "expires": "2020-01-01"}, rt)
    assert not (await tools.call("asset_register", {"file": str(d / "font.ttf"), "derived_from": str(d / "neevidovany.png")}, rt)).ok
    Image.new("RGB", (64, 64), "green").save(d / "foto.png")            # changed after registration
    r = await tools.call("assets_report", {"folder": str(d)}, rt)
    assert r.data["changed"] == ["foto.png"] and r.data["expired"][0]["file"] == "font.ttf" and r.data["unregistered"] == ["foto.png", "neevidovany.png"]
    assert any("Jana Nová" in c and "CC BY 4.0" in c for c in r.data["credits"])
    chain = (await tools.call("asset_lineage", {"file": str(d / "foto-maly.png")}, rt)).data
    assert [c["file"] for c in chain] == ["foto-maly.png", "foto.png"] and chain[1]["author"] == "Jana Nová"


async def test_camera_and_lights(rt):
    r = await tools.call("camera_move", {"kind": "orbit", "target": [0, 0, 1], "distance": 5, "seconds": 4, "fps": 24}, rt)
    keys = creative.camera_path("orbit", [0, 0, 1], 5, 1.6, 96, 24)["keys"]
    assert all(abs(math.hypot(k["position"][0], k["position"][1]) - 5) < 1e-3 for k in keys)
    assert r.data["speed_start"] < 0.05 * r.data["speed_mid"] and r.data["speed_end"] < 0.05 * r.data["speed_mid"]     # eases in and out
    code = open(r.data["script"], encoding="utf-8").read()
    compile(code, "kamera.py", "exec")
    assert "keyframe_insert('location'" in code and "TRACK_TO" in code
    d = creative.camera_path("dolly", [0, 0, 0], 8, 1, 10, 24, end_distance=2, ease="linear")["keys"]
    assert d[0]["position"][1] == -8 and d[-1]["position"][1] == -2
    lp = await tools.call("lighting_plan", {"style": "three_point", "subject": [0, 0, 1.5], "camera": [0, -5, 1.6]}, rt)
    key, fill, rim = lp.data["lights"]
    assert fill["watts"] == 500 and rim["name"] == "kontra" and lp.data["stops"] == 1
    ang = math.degrees(math.atan2(key["position"][0], -key["position"][1]))
    assert abs(ang - 45) < 0.5 and rim["position"][1] > 0                # key 45° off the camera axis, rim behind
    compile(open(lp.data["script"], encoding="utf-8").read(), "svetla.py", "exec")


async def test_lip_sync(rt, tmp_path):
    d = _dir(tmp_path, "zvuk")
    rate = 16000
    t = np.arange(rate * 2) / rate
    x = np.where(t >= 1, 0.5 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)), 0.0).astype(np.float32)
    media.write_wav(d / "rec.wav", x, rate)
    r = await tools.call("lip_sync", {"audio": str(d / "rec.wav"), "fps": 24}, rt)
    assert r.data["frames"] == 48 and r.data["keys"][0] == {"frame": 1, "mouth": "X"} and 45 <= r.data["open_pct"] <= 55
    moho = open(r.data["path"], encoding="utf-8").read().splitlines()
    assert moho[0] == "MohoSwitch1" and moho[1] == "1 rest" and any(line.endswith((" AI", " O")) for line in moho)


async def test_mix_advice(rt, tmp_path):
    d = _dir(tmp_path, "stopy")
    rate = 48000
    rng = np.random.default_rng(3)
    n = rate * 6
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / rate)
    voice = np.fft.irfft(spec * ((f > 300) & (f < 3400)), n)
    voice = (0.1 * voice / np.abs(voice).max()).astype(np.float32)
    music = (0.5 * rng.standard_normal(n) / 3).clip(-1, 1).astype(np.float32)
    media.write_wav(d / "hlas.wav", voice, rate)
    media.write_wav(d / "hudba.wav", music, rate)
    r = await tools.call("mix_advice", {"stems": {"dialog": str(d / "hlas.wav"), "hudba": str(d / "hudba.wav")}}, rt)
    g, st = r.data["gains_db"], r.data["stems"]
    assert r.data["anchor"] == "dialog"
    assert g["hudba"] == pytest.approx(-17 - 12 - st["hudba"]["lufs"], abs=0.11) and g["hudba"] < 0
    assert (st["dialog"]["lufs"] + g["dialog"]) - (st["hudba"]["lufs"] + g["hudba"]) == pytest.approx(12, abs=0.2)


async def test_render_cost(rt):
    r = await tools.call("render_cost", {"frames": 240, "seconds_per_frame": 30, "machines": 4, "price_per_hour": 2, "mb_per_frame": 50,
                                         "test_resolution": [960, 540], "final_resolution": [1920, 1080]}, rt)
    assert r.data == {"seconds_per_frame": 120, "machine_hours": 8, "wall_hours": 2, "wall": "0 d 2 h 0 min", "cost": 16, "disk_gb": 11.72}


async def test_color_profile(rt, tmp_path):
    d = _dir(tmp_path, "barvy")
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.new("RGB", (10, 10), "red").save(d / "srgb.png", icc_profile=srgb)
    Image.new("RGB", (10, 10), "red").save(d / "bez.png")
    Image.new("CMYK", (10, 10), (0, 255, 255, 0)).save(d / "tisk.jpg")
    a = await tools.call("color_profile", {"image": str(d / "srgb.png")}, rt)
    assert a.data["srgb"] and not a.data["advice"] and "sRGB" in a.data["profile"]
    assert "bez profilu" in (await tools.call("color_profile", {"image": str(d / "bez.png")}, rt)).summary
    c = await tools.call("color_profile", {"image": str(d / "tisk.jpg"), "convert": True}, rt)
    out = Image.open(c.data["converted"])
    assert c.data["cmyk"] and "jen přibližný" in c.summary and out.mode == "RGB" and out.getpixel((5, 5))[0] > 200 and out.getpixel((5, 5))[1] < 80


async def test_storyboard(rt):
    shots = [{"name": "Úvod", "duration": 3}, {"name": "Rozhovor", "dialogue": "Dobrý den, vítejte v naší nové kavárně na náměstí v Brně."},
             {"name": "Detail", "duration": 2, "dialogue": "Tohle je naše nejlepší káva z Etiopie, pražená každé ráno."}]
    r = await tools.call("storyboard_timeline", {"shots": shots, "fps": 25}, rt)
    s = r.data["shots"]
    assert s[1]["duration"] == pytest.approx(11 / 2.5 + 0.6) and s[1]["tc_in"] == "00:00:03:00" and s[2]["tc_in"] == "00:00:08:00"
    assert r.data["total_tc"] == "00:00:10:00" and "dialog potřebuje 4.6 s, záběr má 2 s" in r.data["warnings"][0]
    edl = open(r.data["files"][0], encoding="utf-8").read()
    assert "FCM: NON-DROP FRAME" in edl and "002  AX       V     C        00:00:00:00 00:00:05:00 00:00:03:00 00:00:08:00" in edl
    subs = media.parse_srt(open(r.data["files"][1], encoding="utf-8").read())
    assert len(subs) == 2 and subs[0]["start"] == pytest.approx(3.3)


@pytest.fixture
def browser_env(monkeypatch):
    if sys.platform != "win32":
        if not os.path.exists(CHROMIUM):
            pytest.skip("Chromium není k dispozici")
        monkeypatch.setenv("JARVIS_CHROMIUM", CHROMIUM)


async def test_product_demo_in_a_real_browser(rt, tmp_path, browser_env):
    pytest.importorskip("playwright")
    from jarvis import testlab

    d = _dir(tmp_path, "demo")
    Image.new("RGB", (800, 500), "#e2e8f0").save(d / "1.png")
    Image.new("RGB", (800, 500), "#cbd5e1").save(d / "2.png")
    r = await tools.call("product_demo", {"title": "Jak založit fakturu", "steps": [
        {"image": str(d / "1.png"), "title": "Klikni na Nová faktura", "text": "Vpravo nahoře.", "hotspot": [600, 20, 160, 50]},
        {"image": str(d / "2.png"), "title": "Hotovo", "text": "Faktura je založená."}]}, rt)
    assert r.data["steps"] == 2 and r.data["hotspots"] == 1
    pw, browser = await testlab.headless()
    try:
        page = await browser.new_page(viewport={"width": 1100, "height": 900})
        await page.goto(Path(r.data["path"]).as_uri())
        assert await page.text_content("#t") == "Klikni na Nová faktura" and await page.text_content("#n") == "1 / 2"
        box = await page.locator("#spot").bounding_box()
        img = await page.locator("#img").bounding_box()
        assert abs((box["x"] - img["x"]) / img["width"] - 0.75) < 0.01      # the hotspot sits where it was put (600/800)
        await page.click("#spot")
        assert await page.text_content("#t") == "Hotovo" and await page.is_hidden("#spot")
        await page.keyboard.press("ArrowLeft")
        assert await page.text_content("#n") == "1 / 2"
    finally:
        await browser.close()
        await pw.stop()
