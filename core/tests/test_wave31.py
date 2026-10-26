"""OMEGA wave 31 (media production) on real files made by the test: reframing that follows a moving subject, clips from
the loud moment, background removal, media organised by date, podcast chapters, colour match with a .cube LUT,
voice-over timing, sound-effect library, subtitle sync (offset and drift), animated elements and the render queue."""
import asyncio
import wave

import av
import numpy as np
import pytest
from PIL import Image

from jarvis import media, mediapro, tools

tools.load_builtin()


def make_video(path, seconds=4, loud=(2.4, 3.0)):
    out = av.open(str(path), "w")
    vs = out.add_stream("libx264", rate=25)
    vs.width, vs.height, vs.pix_fmt = 640, 360, "yuv420p"
    aus = out.add_stream("aac", rate=48000)
    aus.layout = "stereo"
    for i in range(seconds * 25):
        img = np.full((360, 640, 3), 20, np.uint8)
        x = 400 + int(100 * np.sin(i / 10))
        img[150:210, x:x + 60] = 255
        f = av.VideoFrame.from_ndarray(img, format="rgb24")
        f.pts = i
        for p in vs.encode(f):
            out.mux(p)
    t = np.arange(48000 * seconds) / 48000
    a = (0.02 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    a[(t >= loud[0]) & (t < loud[1])] = (0.6 * np.sin(2 * np.pi * 880 * t[(t >= loud[0]) & (t < loud[1])])).astype(np.float32)
    fifo = av.AudioFifo()
    af = av.AudioFrame.from_ndarray(np.stack([a, a]), format="fltp", layout="stereo")
    af.sample_rate, af.pts = 48000, 0
    fifo.write(af)
    pts = 0
    while fifo.samples >= 1024:
        fr = fifo.read(1024)
        fr.pts = pts
        pts += 1024
        for p in aus.encode(fr):
            out.mux(p)
    for s in (vs, aus):
        for p in s.encode():
            out.mux(p)
    out.close()
    return path


def frames(path):
    with av.open(str(path)) as c:
        return [f.to_ndarray(format="rgb24") for f in c.decode(c.streams.video[0])]


async def drain(rt):
    q = mediapro.queue(rt)
    if q._task:
        await q._task
    await q.run()


@pytest.fixture
def video(tmp_path):
    d = tmp_path / "video"
    d.mkdir()
    return make_video(d / "src.mp4")


async def test_reframe_follows_the_subject(rt, video):
    r = await tools.call("reframe_video", {"file": str(video), "aspect": "9:16", "height": 360}, rt)
    await drain(rt)
    job = mediapro.queue(rt).jobs()[0]
    assert job["status"] == "hotovo", job
    fr = frames(r.data["path"])
    assert fr[0].shape == (360, 202, 3) and len(fr) == 100
    visible = sum(1 for f in fr if (f > 200).mean() > 0.02)
    assert visible >= 95                                                 # the white square stays in the narrow frame
    assert not (await tools.call("reframe_video", {"file": str(video), "aspect": "3:7"}, rt)).ok


async def test_clips_from_the_loud_moment(rt, video):
    r = await tools.call("extract_clips", {"file": str(video), "count": 1, "seconds": 1.5}, rt)
    c = r.data["clips"][0]
    assert c["start"] <= 2.5 <= c["end"] and c["end"] - c["start"] == pytest.approx(1.5, abs=0.05)
    await drain(rt)
    meta = mediapro.video_meta(r.data["clips"][0]["path"] and __import__("pathlib").Path(c["path"]))
    assert meta["seconds"] == pytest.approx(1.5, abs=0.15) and meta["audio"]


async def test_remove_background(rt, tmp_path):
    d = tmp_path / "foto"
    d.mkdir()
    im = Image.new("RGB", (400, 300), (250, 250, 250))
    from PIL import ImageDraw

    ImageDraw.Draw(im).ellipse((120, 70, 280, 230), fill=(200, 30, 30))
    im.save(d / "produkt.jpg", quality=95)
    r = await tools.call("remove_background", {"image": str(d / "produkt.jpg")}, rt)
    out = Image.open(r.data["path"])
    assert out.mode == "RGBA" and out.getpixel((5, 5))[3] == 0 and out.getpixel((200, 150))[3] == 255
    assert r.data["removed_pct"] == pytest.approx(100 - 100 * np.pi * 80 * 80 / (400 * 300), abs=3) and not r.data["warnings"]
    noisy = (np.random.default_rng(0).integers(0, 255, (200, 200, 3))).astype(np.uint8)
    Image.fromarray(noisy).save(d / "rusne.png")
    assert (await tools.call("remove_background", {"image": str(d / "rusne.png")}, rt)).data["warnings"]


def _photo(path, when, color):
    im = Image.new("RGB", (40, 30), color)
    ex = Image.Exif()
    ex[306] = when
    im.save(path, exif=ex)


async def test_organize_media(rt, tmp_path):
    d = tmp_path / "fotky"
    d.mkdir()
    _photo(d / "IMG_1.jpg", "2026:07:12 10:00:00", "red")
    _photo(d / "IMG_2.jpg", "2026:07:12 18:30:00", "blue")
    _photo(d / "IMG_3.jpg", "2026:07:13 09:00:00", "green")             # the same trip (gap < 6 h? no: 14.5 h → next event)
    _photo(d / "IMG_9.jpg", "2026:08:01 12:00:00", "yellow")
    (d / "kopie.jpg").write_bytes((d / "IMG_1.jpg").read_bytes())
    r = await tools.call("organize_media", {"folder": str(d), "gap_hours": 16}, rt)
    dst = {m["src"].split("/")[-1]: m["dst"].split(str(d))[1] for m in r.data["plan"]}
    assert dst["IMG_1.jpg"].endswith("2026/2026-07-12 až 13/IMG_1.jpg".replace("/", __import__("os").sep)) and "2026-08-01" in dst["IMG_9.jpg"]
    assert "Duplicity" in dst["kopie.jpg"] and len(r.data["events"]) == 2
    done = await tools.call("organize_media", {"folder": str(d), "gap_hours": 16, "apply": True}, rt)
    assert done.data["renamed"] == 5 and (d / "2026" / "2026-08-01" / "IMG_9.jpg").exists() and not (d / "IMG_9.jpg").exists()


def test_chapters():
    topics = [("vaření polévka zelenina hrnec recept vývar mrkev", 0), ("fotbal zápas gól trenér hráči liga stadion", 300),
              ("počítač procesor grafika paměť disk ovladač", 600)]
    segs = []
    for words, t0 in topics:
        w = words.split()
        for k in range(30):
            segs.append((t0 + k * 10, t0 + k * 10 + 9, " ".join(w[(k + j) % len(w)] for j in range(5)) + " a pak jsme si povídali"))
    ch = mediapro.chapters(segs, 45, 120)
    assert len(ch) == 3 and ch[0]["stamp"] == "00:00" and abs(ch[1]["start"] - 300) <= 50 and abs(ch[2]["start"] - 600) <= 50
    assert "fotbal" in " ".join(ch[1]["keywords"]) or "zapas" in " ".join(ch[1]["keywords"]) and "procesor" in " ".join(ch[2]["keywords"])


def test_color_match_and_lut(tmp_path):
    rng = np.random.default_rng(1)
    src = np.clip(rng.normal([90, 110, 160], 25, (60, 80, 3)), 0, 255).astype(np.uint8)          # cold
    ref = np.clip(rng.normal([200, 150, 90], 30, (60, 80, 3)), 0, 255).astype(np.uint8)          # warm
    fn = mediapro.color_transfer_fn(src, ref)
    out = fn(src)
    assert np.abs(out.reshape(-1, 3).mean(0) - ref.reshape(-1, 3).mean(0)).max() < 12
    lut = mediapro.read_cube(mediapro.write_cube(fn, tmp_path / "a.cube"))
    assert lut.shape == (33, 33, 33, 3) and (tmp_path / "a.cube").read_text().splitlines()[1] == "LUT_3D_SIZE 33"
    assert np.abs(mediapro.apply_cube(lut, src).astype(int) - out.astype(int)).mean() < 3
    ident = mediapro.read_cube(mediapro.write_cube(lambda x: x, tmp_path / "i.cube"))
    assert np.abs(mediapro.apply_cube(ident, src).astype(int) - src.astype(int)).max() <= 1


async def test_match_shot_tool(rt, tmp_path, video):
    d = tmp_path / "ref"
    d.mkdir()
    Image.new("RGB", (64, 64), (230, 160, 80)).save(d / "teply.png")
    r = await tools.call("match_shot", {"file": str(video), "reference": str(d / "teply.png"), "apply_video": True}, rt)
    assert r.data["lut"].endswith(".cube") and r.data["job"]
    await drain(rt)
    f = frames(mediapro.queue(rt).jobs()[0]["result"]["path"])[10]
    assert f[5, 5, 0] > f[5, 5, 2]                                     # the dark background turned warm


def test_voiceover_fit():
    script = ("Vítejte v naší pekárně. Každé ráno pečeme kváskový chléb z české mouky. "
              "Tady vidíte, jak se těsto nechává kynout celou noc, aby mělo krásnou chuť a vůni. "
              "A tohle je náš nový obchod na náměstí, kde nás najdete každý den od sedmi do šesti večer.")
    r = mediapro.fit_script(script, [(0, 3), (3, 6), (6, 16)])
    assert sum(len(s["text"].split()) for s in r["scenes"]) == len(script.split())
    assert r["seconds_needed"] == pytest.approx(len(script.split()) / 2.5, abs=0.1)
    s2 = r["scenes"][1]
    assert s2["fits"] == 7 and (s2["over"] > 0) == (2 in r["too_long"]) and "1\n" in r["srt"]


def _wav(path, x, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


async def test_sfx_library(rt, tmp_path):
    d = tmp_path / "sfx"
    (d / "domov").mkdir(parents=True)
    rng = np.random.default_rng(3)
    t = np.arange(16000) / 16000
    _wav(d / "domov" / "door_slam_heavy.wav", np.exp(-t[:8000] * 30) * rng.standard_normal(8000) * 0.8)
    _wav(d / "dest_na_okne.wav", 0.1 * rng.standard_normal(16000 * 4))
    _wav(d / "potlesk_publikum.wav", 0.3 * rng.standard_normal(16000 * 2) * (0.5 + 0.5 * np.sin(2 * np.pi * 8 * np.arange(32000) / 16000)))
    r = await tools.call("sfx_library", {"folder": str(d)}, rt)
    assert r.data["indexed"] == 3
    assert (await tools.call("sfx_library", {"folder": str(d)}, rt)).data["unchanged"] == 3
    assert (await tools.call("sfx_library", {"query": "bouchnutí dveří"}, rt)).data[0]["name"] == "door_slam_heavy"
    assert (await tools.call("sfx_library", {"query": "rain"}, rt)).data[0]["name"] == "dest_na_okne"
    assert (await tools.call("sfx_library", {"query": "applause"}, rt)).data[0]["name"] == "potlesk_publikum"
    like = (await tools.call("sfx_library", {"like": str(d / "domov" / "door_slam_heavy.wav")}, rt)).data
    assert like[0]["name"] == "door_slam_heavy" and like[0]["character"].startswith("ostrý")
    assert (await tools.call("sfx_library", {"query": "dveře", "max_seconds": 0.2}, rt)).data == []


def _speech(spans, seconds, rate=16000):
    t = np.arange(int(seconds * rate)) / rate
    x = 0.002 * np.random.default_rng(0).standard_normal(len(t))
    for a, b in spans:
        m = (t >= a) & (t < b)
        x[m] += 0.3 * np.sin(2 * np.pi * 200 * t[m]) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t[m]))
    return x.astype(np.float32)


SPANS = [(2, 4), (6, 9), (12, 14), (17, 19.5), (22, 25), (28, 30), (33, 36), (40, 41.5), (45, 48), (52, 55)]


async def test_subtitle_sync(rt, tmp_path):
    d = tmp_path / "tit"
    d.mkdir()
    _wav(d / "rec.wav", _speech(SPANS, 60))
    late = [{"start": a + 1.5, "end": b + 1.5, "text": f"věta {i}"} for i, (a, b) in enumerate(SPANS)]
    (d / "pozde.srt").write_text(media.to_srt(late), encoding="utf-8")
    r = await tools.call("sync_subtitles", {"subtitles": str(d / "pozde.srt"), "media_file": str(d / "rec.wav")}, rt)
    assert r.data["offset_s"] == pytest.approx(-1.5, abs=0.1) and r.data["stretch"] == 1 and r.data["match_after"] > 0.9 > r.data["match_before"]
    fixed = media.parse_srt(open(r.data["path"], encoding="utf-8").read())
    assert fixed[0]["start"] == pytest.approx(2, abs=0.1)
    x = _speech(SPANS, 60)
    drift = [{"start": a * 0.96, "end": b * 0.96, "text": "x"} for a, b in SPANS]          # 25 fps subtitles on a 24 fps video
    r2 = mediapro.sync_subtitles(drift, x, 16000)
    assert r2["stretch"] == pytest.approx(1 / 0.96, abs=0.02) and r2["match_after"] > 0.85


async def test_animate_elements(rt, tmp_path):
    d = tmp_path / "logo"
    d.mkdir()
    Image.new("RGBA", (100, 100), (255, 200, 0, 255)).save(d / "logo.png")
    r = await tools.call("animate_elements", {"width": 320, "height": 240, "seconds": 2, "background": "#000000",
                                              "elements": [{"image": str(d / "logo.png"), "x": 0.5, "y": 0.4, "scale": 0.3, "start": 0.5, "effect": "zoom"},
                                                           {"text": "AHOJ", "x": 0.5, "y": 0.85, "start": 1.0, "effect": "slide-up", "font_size": 40}]}, rt)
    fr = frames(r.data["path"])
    assert len(fr) == 60 and fr[0].shape == (240, 320, 3)
    assert fr[5][96, 160].max() < 40 and fr[59][96, 160][0] > 200 and fr[59][96, 160][2] < 100      # logo appears in yellow
    assert (fr[59][190:220] > 200).mean() > (fr[20][190:220] > 200).mean()                            # the text slid in later


async def test_render_queue_errors_and_cancel(rt, tmp_path):
    q = mediapro.queue(rt)
    bad = q.add("clip", {"src": str(tmp_path / "neni.mp4"), "dst": str(tmp_path / "x.mp4"), "start": 0, "end": 1})
    keep = q.add("transcode", {"src": str(tmp_path / "neni.mp4"), "dst": str(tmp_path / "y.mp4")})
    assert q.cancel(keep)
    await drain(rt)
    jobs = {j["id"]: j for j in q.jobs()}
    assert jobs[bad]["status"] == "chyba" and jobs[keep]["status"] == "zrušeno"
    r = await tools.call("render_queue", {}, rt)
    assert f"č. {bad} clip: chyba" in r.summary
    with pytest.raises(ValueError):
        q.add("render-all", {})
    assert not (await tools.call("render_queue", {"cancel": 9999}, rt)).ok
    await asyncio.sleep(0)
