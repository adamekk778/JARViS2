"""OMEGA wave 18 (design & media): contrast against WCAG reference values, a theme where every pair passes AA, a
design system on disk, visual diff, typography / consistency of a real page in a real browser, similar images,
silence removal, ducking and speech clean-up on generated audio, loudness against the BS.1770 reference
(997 Hz full-scale sine = −3.01 LUFS), scenes in a generated video, subtitles."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from jarvis import design, media, tools

tools.load_builtin()
RATE = 16000
CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
needs_browser = pytest.mark.skipif(not (sys.platform == "win32" or Path(CHROMIUM).exists()), reason="žádný prohlížeč")
try:
    import av  # noqa: F401
    HAS_AV = True
except ImportError:
    HAS_AV = False
needs_av = pytest.mark.skipif(not HAS_AV, reason="PyAV není nainstalované")


def tone(freq, seconds, amp=0.5, rate=RATE):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def save(path, x, rate=RATE):
    media.write_wav(path, x if x.ndim == 2 else x[:, None], rate)
    return path


async def test_contrast(rt):
    r = await tools.call("contrast_check", {"text_color": "#777777", "background": "#ffffff"}, rt)
    assert r.data["ratio"] == pytest.approx(4.48, abs=0.01) and not r.data["aa"] and r.data["aa_large"]
    assert r.data["suggestion_ratio"] >= 4.5 and design.hex_to_rgb(r.data["suggestion"])[0] < 0x77
    ok = await tools.call("contrast_check", {"text_color": "#000", "background": "#fff"}, rt)
    assert ok.data["ratio"] == 21.0 and "AAA" in ok.summary
    assert not (await tools.call("contrast_check", {"text_color": "modrá", "background": "#fff"}, rt)).ok


async def test_theme_and_design_system(rt, tmp_path):
    for brand in ("#2563eb", "#facc15", "#10b981", "#7c3aed"):
        t = design.theme(brand)
        assert t["all_aa"], (brand, [c for c in t["checks"] if not c["aa"]])
    r = await tools.call("design_system", {"primary": "#e11d48", "folder": str(tmp_path / "ds")}, rt)
    css = (tmp_path / "ds" / "tokens.css").read_text(encoding="utf-8")
    assert r.ok and "--primary-500:" in css and "--text-base: 1rem;" in css and "prefers-color-scheme: dark" in css and "--space-4: 16px;" in css
    assert r.data["tokens"]["font"]["size"]["xl"] == 25.0
    assert not (await tools.call("design_system", {"primary": "#e11d48", "folder": str(tmp_path / "ds")}, rt)).ok


async def test_visual_diff(rt, tmp_path):
    a = Image.new("RGB", (400, 300), "white")
    ImageDraw.Draw(a).rectangle([20, 20, 120, 60], fill="#2563eb")
    a.save(tmp_path / "a.png")
    b = a.copy()
    ImageDraw.Draw(b).rectangle([250, 200, 330, 240], fill="red")
    b.save(tmp_path / "b.png")
    r = await tools.call("visual_diff", {"before": str(tmp_path / "a.png"), "after": str(tmp_path / "b.png")}, rt)
    x0, y0, x1, y1 = r.data["regions"][0]
    assert len(r.data["regions"]) == 1 and x0 <= 250 and y0 <= 200 and x1 >= 330 and y1 >= 240
    assert r.data["changed_pct"] == pytest.approx(100 * 81 * 41 / 120000, rel=0.05) and Path(r.data["diff_image"]).is_file()
    same = await tools.call("visual_diff", {"before": str(tmp_path / "a.png"), "after": str(tmp_path / "a.png")}, rt)
    assert same.data["same"]


PAGE = """<!doctype html><html><body style="font-family: Georgia; margin: 0">
<h1 style="font-size: 32px">Nadpis</h1>
<p style="width: 1300px; font-size: 16px; line-height: 18px">""" + "Dlouhý odstavec textu, který se táhne přes celou šířku obrazovky. " * 8 + """</p>
<p style="color: #333333; margin-top: 13px">Text A</p><p style="color: #343434; padding-left: 7px">Text B</p>
<small style="font-size: 10px">drobné písmo</small>
</body></html>"""


@needs_browser
async def test_typography_and_consistency(rt, tmp_path, monkeypatch):
    if sys.platform != "win32":
        monkeypatch.setenv("JARVIS_CHROMIUM", CHROMIUM)
    f = tmp_path / "page.html"
    f.write_text(PAGE, encoding="utf-8")
    r = await tools.call("typography_check", {"url": str(f)}, rt)
    issues = " | ".join(r.data["issues"])
    assert "Georgia" in r.data["fonts"] and "příliš dlouhé řádky" in issues and "těsné řádkování" in issues and "menších než 12 px" in issues
    r = await tools.call("ui_consistency", {"url": str(f)}, rt)
    assert ["#333333", "#343434"] in r.data["near_duplicates"] and any("mimo mřížku" in i for i in r.data["issues"])


async def test_find_similar_image(rt, tmp_path):
    rng = np.random.default_rng(1)
    base = (rng.random((64, 64, 3)) * 255).astype(np.uint8)
    base = np.array(Image.fromarray(base).resize((256, 256), Image.Resampling.BICUBIC))
    Image.fromarray(base).save(tmp_path / "query.png")
    d = tmp_path / "fotky"
    d.mkdir()
    Image.fromarray(base).resize((128, 128)).save(d / "mensi.jpg", quality=80)
    Image.fromarray((rng.random((256, 256, 3)) * 255).astype(np.uint8)).save(d / "jina.png")
    r = await tools.call("find_similar_image", {"image": str(tmp_path / "query.png"), "folder": str(d)}, rt)
    assert [Path(h["path"]).name for h in r.data] == ["mensi.jpg"]


async def test_remove_silence(rt, tmp_path):
    x = np.concatenate([tone(300, 1), np.zeros(int(2 * RATE), np.float32), tone(300, 1), np.zeros(int(0.3 * RATE), np.float32), tone(300, 1)])
    src = save(tmp_path / "rec.wav", x)
    r = await tools.call("remove_silence", {"file": str(src)}, rt)
    y, rate = media.read_audio(Path(r.data["path"]))
    assert len(r.data["cuts"]) == 1 and r.data["removed_s"] == pytest.approx(1.7, abs=0.1) and len(y) / rate == pytest.approx(3.6, abs=0.1)
    assert not (await tools.call("remove_silence", {"file": str(src)}, rt)).ok             # never overwrites


async def test_duck_music(rt, tmp_path):
    voice = np.concatenate([np.zeros(RATE, np.float32), tone(200, 2, 0.5), np.zeros(RATE, np.float32)])
    v = save(tmp_path / "hlas.wav", voice)
    m = save(tmp_path / "hudba.wav", tone(1000, 2, 0.5, rate=8000), rate=8000)                       # other rate, shorter → resampled and looped
    r = await tools.call("duck_music", {"voice": str(v), "music": str(m), "duck_db": -20}, rt)
    y, _ = media.read_audio(Path(r.data["path"]))
    spec = lambda seg: np.abs(np.fft.rfft(seg[:, 0]))  # noqa: E731
    f = np.fft.rfftfreq(RATE // 2, 1 / RATE)
    quiet = spec(y[int(0.25 * RATE):int(0.75 * RATE)])
    talk = spec(y[int(1.75 * RATE):int(2.25 * RATE)])
    music_quiet, music_talk = quiet[np.argmin(abs(f - 1000))], talk[np.argmin(abs(f - 1000))]
    assert 20 * math.log10(music_quiet / music_talk) == pytest.approx(20, abs=3) and 40 < r.data["speech_pct"] < 60


async def test_clean_speech(rt, tmp_path):
    rng = np.random.default_rng(0)
    speech = np.concatenate([np.zeros(RATE, np.float32), tone(440, 2, 0.4), np.zeros(RATE, np.float32)])
    noisy = speech + 0.03 * rng.standard_normal(len(speech)).astype(np.float32) + tone(40, 4, 0.2)
    r = await tools.call("clean_speech", {"file": str(save(tmp_path / "s.wav", noisy))}, rt)
    y, _ = media.read_audio(Path(r.data["path"]))
    y = y[:, 0]

    def snr(sig):
        return 20 * math.log10(np.sqrt(np.mean(sig[int(1.5 * RATE):int(2.5 * RATE)] ** 2)) / np.sqrt(np.mean(sig[int(0.2 * RATE):int(0.8 * RATE)] ** 2)))
    assert snr(y) > snr(noisy) + 12 and r.data["noise_reduction_db"] > 6
    low = np.abs(np.fft.rfft(y[RATE:3 * RATE]))
    fr = np.fft.rfftfreq(2 * RATE, 1 / RATE)
    assert low[np.argmin(abs(fr - 40))] < 0.01 * low[np.argmin(abs(fr - 440))]          # the 40 Hz hum is gone


def test_loudness_reference():
    for rate in (48000, 44100):
        full = media.loudness(tone(997, 5, 1.0, rate)[:, None], rate)
        assert full["lufs"] == pytest.approx(-3.0, abs=0.15)
        assert media.loudness(tone(997, 5, 0.1, rate)[:, None], rate)["lufs"] == pytest.approx(-23.0, abs=0.15)
    assert media.loudness(np.zeros((48000, 1), np.float32), 48000)["lufs"] == -math.inf


async def test_media_quality(rt, tmp_path):
    x = np.concatenate([np.zeros(3 * RATE, np.float32), np.clip(tone(500, 3, 1.4), -1, 1)])
    r = await tools.call("media_quality", {"file": str(save(tmp_path / "q.wav", x))}, rt)
    a = r.data["audio"]
    assert a["clipped_samples"] > 100 and a["lead_silence_s"] == pytest.approx(3, abs=0.1) and "přebuzení" in r.summary
    assert a["adjust_db"]["YouTube"] == pytest.approx(-14 - a["lufs"], abs=0.11)


@needs_av
async def test_video_scenes(rt, tmp_path):
    import av

    path = tmp_path / "klip.mp4"
    with av.open(str(path), "w") as out:
        st = out.add_stream("mpeg4", rate=10)
        st.width, st.height, st.pix_fmt = 160, 96, "yuv420p"
        for i in range(60):                                                        # 3 scenes of 2 s: dark, bright, gradient
            if i < 20:
                img = np.full((96, 160, 3), 20, np.uint8)
            elif i < 40:
                img = np.full((96, 160, 3), 230, np.uint8)
            else:
                img = np.tile(np.linspace(0, 255, 160, dtype=np.uint8), (96, 1))[:, :, None].repeat(3, axis=2)
            img[:, i % 160] = 128                                                  # a little motion inside a scene
            for pkt in st.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                out.mux(pkt)
        for pkt in st.encode():
            out.mux(pkt)
    r = await tools.call("video_scenes", {"file": str(path), "highlights": 0}, rt)
    assert r.data["scenes"] == 3 and [round(c["t"]) for c in r.data["cuts"]] == [2, 4]
    q = await tools.call("media_quality", {"file": str(path)}, rt)
    assert q.data["width"] == 160 and q.data["fps"] == 10 and q.data["video_codec"] == "mpeg4"


async def test_audio_highlights(rt, tmp_path):
    x = np.concatenate([tone(300, 10, 0.05), tone(300, 1, 0.8), tone(300, 15, 0.05), tone(300, 1, 0.6), tone(300, 10, 0.05)])
    r = await tools.call("audio_highlights", {"file": str(save(tmp_path / "h.wav", x)), "top": 3}, rt)
    assert [round(h["t"]) for h in r.data] == [10, 26]


SRT = """1
00:00:01,000 --> 00:00:01,500
Tohle je velmi dlouhý titulek, který se nevejde na jeden řádek a čte se moc rychle

2
00:00:01,400 --> 00:00:04,000
Krátký

3
00:00:05,000 --> 00:00:15,000
Moc dlouho
"""


async def test_subtitles(rt, tmp_path):
    f = tmp_path / "t.srt"
    f.write_text(SRT, encoding="utf-8")
    r = await tools.call("check_subtitles", {"file": str(f)}, rt)
    probs = {(x["n"], x["problem"].split(" ")[0]) for x in r.data}
    assert {(1, "rychlé"), (1, "řádek"), (1, "zobrazení"), (1, "překrývá"), (3, "zobrazení")} <= probs
    r = await tools.call("restyle_subtitles", {"file": str(f), "format": "ass", "position": "nahoře", "color": "#FFFF00", "box": True}, rt)
    ass = Path(r.data["path"]).read_text(encoding="utf-8")
    assert r.data["after"] < r.data["before"] and "&H0000FFFF" in ass and ",8,60,60," in ass and "\\N" in ass and "Dialogue: 0,0:00:01.00," in ass
    r = await tools.call("restyle_subtitles", {"file": str(f), "format": "srt"}, rt)
    fixed = media.parse_srt(Path(r.data["path"]).read_text(encoding="utf-8"))
    assert all(len(line) <= 42 for s in fixed for line in s["text"].split("\n")) and fixed[0]["end"] <= fixed[1]["start"]
