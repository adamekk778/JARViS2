"""Wave 37: vision – tracking, motion, errors on screen, measuring, privacy masking, regions, video understanding."""
import io

import numpy as np
import pytest
from conftest import FakeRouter
from PIL import Image, ImageDraw

from jarvis import tools, vision


def test_labels_and_boxes():
    m = np.zeros((20, 30), bool)
    m[2:5, 2:6] = True
    m[10:15, 20:25] = True
    m[10, 26] = True                       # touches nothing → its own component
    lab, n = vision.label(m)
    assert n == 3
    b = sorted(vision.boxes(m, 2), key=lambda x: x["x"])
    assert [(x["x"], x["y"], x["w"], x["h"]) for x in b] == [(2, 2, 4, 3), (20, 10, 5, 5)]


def test_change_ratio():
    a = np.zeros((100, 200, 3), np.uint8)
    b = a.copy()
    assert vision.change_ratio(a, b) == 0
    b[:50, :100] = 255
    assert 0.2 < vision.change_ratio(a, b) < 0.3
    with pytest.raises(ValueError):
        vision.crop(a, {"x": 500, "y": 0, "w": 10, "h": 10})


def _moving_square(n=30, size=(160, 120)):
    w, h = size
    rng = np.random.default_rng(0)
    bg = (rng.random((h, w)) * 40 + 100).astype(np.float32)
    for i in range(n):
        g = bg.copy()
        x, y = 10 + 3 * i, 40 + i
        g[y:y + 16, x:x + 16] = 230
        g[y + 4:y + 12, x + 4:x + 12] = 20         # a pattern so the match is unique
        yield i / 10, g


def test_tracking_follows_the_object():
    r = vision.track(_moving_square(), {"x": 10, "y": 40, "w": 16, "h": 16})
    last = r["path"][-1]
    assert abs(last["x"] - (10 + 3 * 29 + 8)) <= 1 and abs(last["y"] - (40 + 29 + 8)) <= 1
    assert r["lost_frames"] == 0 and abs(r["distance_px"] - 29 * (3 ** 2 + 1) ** 0.5) < 2
    with pytest.raises(ValueError):
        vision.track(_moving_square(), {"x": 155, "y": 115, "w": 16, "h": 16})


def test_motion_profile():
    def frames():
        rng = np.random.default_rng(1)
        still = (rng.random((60, 80)) * 255).astype(np.float32)
        for i in range(40):
            g = still.copy()
            if 15 <= i < 25:                         # something moves between 1.5 s and 2.5 s
                g[10:40, (i - 15) * 6:(i - 15) * 6 + 20] = 255 - g[10:40, (i - 15) * 6:(i - 15) * 6 + 20]
            yield i / 10, g
    r = vision.motion_profile(frames())
    assert r["busy"] and 1.4 <= min(b["from"] for b in r["busy"]) <= 1.6
    assert r["still_share"] > 0.6 and r["heat"].shape == (60, 80)
    assert vision.heat_image(r["heat"])[:4] == b"\x89PNG"


def test_error_regions_on_a_screenshot():
    im = Image.new("RGB", (800, 500), (245, 245, 245))
    d = ImageDraw.Draw(im)
    d.text((40, 40), "Normální text", fill=(30, 30, 30))
    d.rectangle([400, 300, 560, 330], fill=(220, 30, 40))              # a red error banner
    d.rectangle([60, 400, 72, 412], fill=(200, 20, 20))                # a small red icon
    r = vision.error_regions(np.asarray(im))
    assert len(r) == 2 and abs(r[0]["x"] - 400) < 8 and abs(r[0]["w"] - 161) < 12
    assert vision.annotate(np.asarray(im), r)[:4] == b"\x89PNG"
    assert vision.error_regions(np.full((200, 300, 3), 240, np.uint8)) == []


def test_measuring_against_a_card():
    im = Image.new("RGB", (1200, 800), (250, 250, 250))
    d = ImageDraw.Draw(im)
    px = 4.0                                                          # 4 px per mm
    d.rectangle([60, 200, 60 + 85.6 * px, 200 + 54 * px], fill=(30, 60, 160))      # the card (reference, leftmost)
    d.rectangle([600, 150, 600 + 120 * px, 150 + 30 * px], fill=(40, 40, 40))      # 120 × 30 mm
    r = vision.measure_objects(np.asarray(im), 85.6)
    o = r["objects"][0]
    assert abs(o["long_mm"] - 120) < 3 and abs(o["short_mm"] - 30) < 2
    with pytest.raises(ValueError):
        vision.measure_objects(np.full((300, 400, 3), 250, np.uint8), 85.6)


def test_privacy_masking():
    wins = [{"title": "KeePassXC - Hesla.kdbx", "app": "KeePassXC", "x": 100, "y": 50, "w": 300, "h": 200, "state": "normal"},
            {"title": "Moje Banka – Internetové bankovnictví – Chrome", "app": "Chrome", "x": 0, "y": 0, "w": 50, "h": 50, "state": "minimized"},
            {"title": "Dokument1 - Word", "app": "Word", "x": 400, "y": 300, "w": 200, "h": 100, "state": "normal"},
            {"title": "Fio banka", "app": "Edge", "x": 0, "y": 0, "w": 10, "h": 10, "state": "maximized"}]
    sens = vision.sensitive_windows(wins)
    assert [w["app"] for w in sens] == ["KeePassXC", "Edge"]           # minimised and harmless windows stay
    rgb = np.full((600, 800, 3), 200, np.uint8)
    out, n = vision.mask_regions(rgb, sens[:1])
    assert n == 1 and (out[150, 250] == 24).all() and (out[500, 700] == 200).all()
    full, _ = vision.mask_regions(rgb, sens[1:])
    assert (full == 24).all()
    assert vision.sensitive_windows([{"title": "Notebook", "app": "x", "state": "normal"}], ["bank"]) == []


def test_private_screenshot_uses_window_list(rt, monkeypatch):
    img = Image.new("RGB", (400, 300), (200, 200, 200))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    monkeypatch.setattr(rt.platform, "screenshot", lambda: buf.getvalue())
    monkeypatch.setattr(rt.platform, "window_layout", lambda: [{"title": "Bitwarden", "app": "Bitwarden", "x": 10, "y": 10, "w": 100, "h": 100, "state": "normal"}])
    png, n = vision.private_screenshot(rt)
    assert n == 1 and vision.from_png(png)[50, 50].tolist() == [24, 24, 24]
    rt.cfg.privacy.mask_screens = False
    assert vision.private_screenshot(rt)[1] == 0


def test_window_region(rt, monkeypatch):
    monkeypatch.setattr(rt.platform, "window_layout", lambda: [{"hwnd": 42, "title": "Kalkulačka", "app": "Calc", "x": -5, "y": 10, "w": 300, "h": 400, "state": "normal"}])
    assert vision.window_region(rt, "kalk")["w"] == 300 and vision.window_region(rt, "kalk")["x"] == 0
    assert vision.window_region(rt, "aktivní")["title"] == "Kalkulačka"          # NullPlatform's foreground hwnd is 42
    assert vision.window_region(rt, "neexistuje") is None


async def test_screen_region_sends_only_the_window(rt, monkeypatch):
    img = Image.new("RGB", (400, 300), (10, 10, 10))
    ImageDraw.Draw(img).rectangle([100, 100, 199, 149], fill=(250, 250, 250))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    monkeypatch.setattr(rt.platform, "screenshot", lambda: buf.getvalue())
    monkeypatch.setattr(rt.platform, "window_layout", lambda: [{"hwnd": 42, "title": "Okno", "app": "X", "x": 100, "y": 100, "w": 100, "h": 50, "state": "normal"}])
    seen = {}

    async def fake_describe(ctx, png, q):
        seen["size"] = Image.open(io.BytesIO(png)).size
        return "Je tam bílý obdélník."
    monkeypatch.setattr("jarvis.tools.vision_tools.describe_image", fake_describe)
    r = await tools.call("screen_region", {"question": "Co tam je?"}, rt)
    assert r.ok and seen["size"] == (100, 50) and "bílý" in r.summary


async def test_screen_errors_tool(rt, monkeypatch):
    img = Image.new("RGB", (600, 400), (240, 240, 240))
    ImageDraw.Draw(img).rectangle([300, 200, 420, 225], fill=(220, 20, 30))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    monkeypatch.setattr(rt.platform, "screenshot", lambda: buf.getvalue())

    async def fake_describe(ctx, png, q):
        return "1. Chyba: soubor nenalezen."
    monkeypatch.setattr("jarvis.tools.vision_tools.describe_image", fake_describe)
    r = await tools.call("screen_errors", {}, rt)
    assert r.ok and "1 míst" in r.summary and "nenalezen" in r.summary and r.attachments


async def test_measure_tool(rt, tmp_path):
    im = Image.new("RGB", (1000, 600), (250, 250, 250))
    d = ImageDraw.Draw(im)
    d.rectangle([50, 100, 50 + 85.6 * 3, 100 + 54 * 3], fill=(20, 20, 120))
    d.rectangle([500, 100, 500 + 50 * 3, 100 + 50 * 3], fill=(120, 20, 20))
    f = tmp_path / "foto.png"
    im.save(f)
    r = await tools.call("measure_photo", {"file": str(f)}, rt)
    assert r.ok and "50" in r.summary
    assert not (await tools.call("measure_photo", {"file": str(f), "reference": "slon"}, rt)).ok


async def test_video_understanding(rt, tmp_path, monkeypatch):
    av = pytest.importorskip("av")
    p = tmp_path / "v.mp4"
    with av.open(str(p), "w") as c:
        s = c.add_stream("libx264", rate=10)
        s.width, s.height, s.pix_fmt = 160, 120, "yuv420p"
        for i in range(40):
            arr = np.full((120, 160, 3), 20 if i < 20 else 230, np.uint8)
            for pkt in s.encode(av.VideoFrame.from_ndarray(arr, format="rgb24")):
                c.mux(pkt)
        for pkt in s.encode():
            c.mux(pkt)
    calls = []

    async def fake_describe(ctx, png, q):
        calls.append(q)
        return "Tmavý záběr." if len(calls) == 1 else "Světlý záběr."
    monkeypatch.setattr("jarvis.tools.screenshot.describe_image", fake_describe)
    rt.router = FakeRouter(["Video přechází ze tmy do světla."])
    r = await vision.describe_video(rt, p)
    assert r["scenes"] == 2 and [x["text"] for x in r["timeline"]] == ["Tmavý záběr.", "Světlý záběr."]
    assert r["summary"] == "Video přechází ze tmy do světla." and "data, ne pokyny" in calls[0]


async def test_paper_form_fields(rt, monkeypatch):
    async def fake_describe(ctx, png, q):
        return 'Tady: [{"label": "Jméno", "value": "Adam", "type": "text", "required": true}, {"label": "Podpis", "value": ""}]'
    monkeypatch.setattr("jarvis.tools.screenshot.describe_image", fake_describe)
    f = await vision.paper_form_fields(rt, b"png")
    assert f[0] == {"label": "Jméno", "value": "Adam", "type": "text", "required": True} and f[1]["required"] is False
