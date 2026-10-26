"""OMEGA §30 / §12 media production: one video pipeline (cut a time range, crop frame by frame, colour filter, resize,
H.264 + AAC) used for reframing to another aspect ratio along the action, short clips from the liveliest moments and
colour-matched shots; background removal for plain-background pictures; organising photos / videos / sound by date and
event; podcast chapters by topic shifts; a colour match to a reference shot exported as a .cube LUT; fitting a voice-over
script to scenes; a sound-effect library search; subtitle sync to the speech; animating graphic elements into a video;
and a render queue that runs these one after another."""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections import Counter, deque
from pathlib import Path
from typing import Callable

import numpy as np

from .comms import fold


# ============================================================================================== video pipeline
def video_meta(src: Path) -> dict:
    import av

    with av.open(str(src)) as c:
        vs = c.streams.video[0]
        fps = float(vs.average_rate or vs.guessed_rate or 25)
        dur = float(c.duration / 1e6) if c.duration else float(vs.frames / fps if vs.frames else 0)
        return {"width": vs.codec_context.width, "height": vs.codec_context.height, "fps": fps, "seconds": dur,
                "audio": bool(c.streams.audio), "frames": vs.frames}


def process_video(src: Path, dst: Path, t0: float = 0.0, t1: float | None = None, crop: Callable[[float, int, int], tuple] | None = None,
                  size: tuple[int, int] | None = None, filt: Callable[[np.ndarray], np.ndarray] | None = None,
                  progress: Callable[[float], None] | None = None, crf: int = 20) -> dict:
    """Decode src from t0 to t1, crop(t, w, h) → (x, y, cw, ch), filter the RGB frame, scale to `size` (even), encode
    H.264 (+ the audio of the same range as AAC)."""
    import av
    from PIL import Image

    meta = video_meta(src)
    t1 = min(t1 if t1 is not None else meta["seconds"], meta["seconds"] or 1e9)
    fps = round(meta["fps"]) or 25
    out = av.open(str(dst), "w")
    vout = None
    aout = fifo = None
    n = 0
    try:
        with av.open(str(src)) as c:
            vin = c.streams.video[0]
            ain = c.streams.audio[0] if c.streams.audio else None
            if t0 > 0:
                c.seek(int(t0 / vin.time_base), stream=vin, any_frame=False, backward=True)
            if ain is not None:
                aout = out.add_stream("aac", rate=48000)
                aout.layout = "stereo"
                fifo = av.AudioFifo()
                res = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
            apts = 0
            for frame in c.decode(*([vin] + ([ain] if ain is not None else []))):
                t = float(frame.pts * frame.time_base) if frame.pts is not None else 0.0
                if t < t0 - 1e-6:
                    continue
                if t >= t1:
                    if isinstance(frame, av.VideoFrame):
                        break
                    continue
                if isinstance(frame, av.AudioFrame):
                    for rf in res.resample(frame):
                        rf.pts = None
                        fifo.write(rf)
                    while fifo.samples >= 1024:
                        fr = fifo.read(1024)
                        fr.pts = apts
                        apts += 1024
                        for p in aout.encode(fr):
                            out.mux(p)
                    continue
                img = frame.to_ndarray(format="rgb24")
                h, w = img.shape[:2]
                if crop:
                    x, y, cw, ch = (int(round(v)) for v in crop(t, w, h))
                    img = img[max(0, y):max(0, y) + ch, max(0, x):max(0, x) + cw]
                if filt:
                    img = filt(img)
                tw, th = size or (img.shape[1], img.shape[0])
                tw, th = tw - tw % 2, th - th % 2
                if (img.shape[1], img.shape[0]) != (tw, th):
                    img = np.asarray(Image.fromarray(img).resize((tw, th), Image.LANCZOS))
                if vout is None:
                    vout = out.add_stream("libx264" if "libx264" in av.codecs_available else "mpeg4", rate=fps)
                    vout.width, vout.height, vout.pix_fmt = tw, th, "yuv420p"
                    vout.options = {"crf": str(crf), "preset": "veryfast"} if vout.codec_context.name == "libx264" else {}
                vf = av.VideoFrame.from_ndarray(np.ascontiguousarray(img), format="rgb24")
                vf.pts = n
                n += 1
                for p in vout.encode(vf):
                    out.mux(p)
                if progress and n % 25 == 0:
                    progress(min(1.0, (t - t0) / max(1e-6, t1 - t0)))
        if vout is not None:
            for p in vout.encode():
                out.mux(p)
        if aout is not None:
            for p in aout.encode():
                out.mux(p)
    finally:
        out.close()
    if n == 0:
        dst.unlink(missing_ok=True)
        raise ValueError("Ve zvoleném úseku není žádný snímek.")
    return {"path": str(dst), "frames": n, "seconds": round(n / fps, 2), "size": [vout.width, vout.height]}


def _gray_frames(src: Path, sample_fps: float = 4, width: int = 160, max_seconds: float = 3 * 3600):
    import av

    with av.open(str(src)) as c:
        vs = c.streams.video[0]
        step, last = 1 / sample_fps, -1e9
        for frame in c.decode(vs):
            t = float(frame.pts * frame.time_base) if frame.pts is not None else 0.0
            if t > max_seconds:
                break
            if t - last < step:
                continue
            last = t
            g = frame.reformat(width=width, height=max(2, int(width * frame.height / frame.width)), format="gray").to_ndarray()
            yield t, g.astype(np.float32)


# ============================================================================================== 365 reframing
def reframe_path(src: Path, aspect: float, sample_fps: float = 8, smooth_s: float = 0.4) -> dict:
    """Where to put a window of the target aspect (w/h) at each moment: the most detail + motion, smoothed, with a
    clean jump at a scene cut instead of a pan."""
    ts, centers, prev, cuts = [], [], None, []
    width = None
    for t, g in _gray_frames(src, sample_fps):
        h, w = g.shape
        width = w
        gy, gx = np.gradient(g)
        energy = np.hypot(gx, gy)
        if prev is not None and prev.shape == g.shape:
            diff = np.abs(g - prev)
            energy = energy + 3 * diff
            if diff.mean() > 40:
                cuts.append(len(ts))
        prev = g
        cw = min(w, int(round(h * aspect)))
        colsum = energy.sum(axis=0)
        cols = np.concatenate([[0], np.cumsum(colsum)])
        x = int(np.argmax(cols[cw:] - cols[:-cw])) if cw < w else 0
        win = colsum[x:x + cw]
        # the best window is often wider than the subject (many equally good positions): centre on the subject itself
        cx = float((win * np.arange(x, x + cw)).sum() / win.sum()) if win.sum() > 0 else x + cw / 2
        ts.append(t)
        centers.append(cx)
    if not ts:
        raise ValueError("Video nejde přečíst.")
    k = max(1, int(smooth_s * sample_fps))
    sm, start = [], 0
    bounds = sorted(set(cuts + [len(ts)]))
    for b in bounds:                                                     # smooth within each scene only
        seg = centers[start:b]
        for i in range(len(seg)):
            lo, hi = max(0, i - k), min(len(seg), i + k + 1)
            sm.append(float(np.mean(seg[lo:hi])))
        start = b
    return {"t": ts, "center": [c / width for c in sm], "cuts": [ts[i] for i in cuts if i < len(ts)]}


def reframe_video(src: Path, dst: Path, aspect: float = 9 / 16, out_height: int = 1920, progress=None) -> dict:
    meta = video_meta(src)
    path = reframe_path(src, aspect)
    t_arr, c_arr = np.array(path["t"]), np.array(path["center"])

    def crop(t, w, h):
        cw = min(w, int(round(h * aspect)))
        cw -= cw % 2
        cx = float(np.interp(t, t_arr, c_arr)) * w
        x = min(max(0, cx - cw / 2), w - cw)
        return x, 0, cw, h
    oh = min(out_height, meta["height"])
    ow = int(round(oh * aspect))
    r = process_video(src, dst, crop=crop, size=(ow, oh), progress=progress)
    r.update(scene_cuts=len(path["cuts"]), aspect=f"{ow}:{oh}")
    return r


# ============================================================================================== 131 short clips
def pick_clips(src: Path, count: int = 3, length: float = 30) -> list[dict]:
    """The liveliest moments (loudness peaks; scene cuts nearby) as non-overlapping ranges."""
    from . import media

    meta = video_meta(src)
    x, rate = media.read_audio(src) if meta["audio"] else (None, None)
    if x is None:
        step = meta["seconds"] / (count + 1)
        return [{"start": round(step * (i + 1) - length / 2, 2), "end": round(step * (i + 1) + length / 2, 2), "why": "rovnoměrně (video bez zvuku)"} for i in range(count)]
    hl = sorted(media.highlights(x, rate, top=count * 3, min_gap_s=length), key=lambda h: -h["score"])
    out = []
    for h in hl:
        s = max(0.0, float(h["t"]) - length / 3)
        e = min(float(meta["seconds"]), s + length)
        if all(e <= o["start"] or s >= o["end"] for o in out):
            out.append({"start": round(s, 2), "end": round(e, 2), "why": f"živý moment {h['t']:g} s ({h['level_db']:g} dB)"})
        if len(out) >= count:
            break
    return sorted(out, key=lambda c: c["start"])


# ============================================================================================== 367 background removal
def remove_background(src: Path, dst: Path, tolerance: float = 25, feather: float = 1.5, work: int = 512) -> dict:
    """Plain (one-colour or gradient-free) background → transparent PNG: the background colour from the border,
    everything similar AND connected to the border goes; edges softened."""
    from PIL import Image, ImageFilter

    from .gamedev import _lab

    im = Image.open(src).convert("RGB")
    small = im.copy()
    small.thumbnail((work, work))
    a = np.asarray(small).astype(np.float32)
    h, w = a.shape[:2]
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(border, axis=0)
    lab, bg_lab = _lab(a), _lab(bg[None, :])[0]
    dist = np.linalg.norm(lab - bg_lab, axis=2)
    spread = float(np.percentile(np.linalg.norm(_lab(border) - bg_lab, axis=1), 90))
    cand = dist < tolerance
    seen = np.zeros_like(cand)
    q = deque()
    for y in range(h):
        for x in (0, w - 1):
            if cand[y, x] and not seen[y, x]:
                seen[y, x] = True
                q.append((y, x))
    for x in range(w):
        for y in (0, h - 1):
            if cand[y, x] and not seen[y, x]:
                seen[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= ny < h and 0 <= nx < w and cand[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))
    alpha = Image.fromarray(((~seen) * 255).astype(np.uint8)).resize(im.size, Image.BILINEAR)
    if feather:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
    out = im.copy()
    out.putalpha(alpha)
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst)
    removed = float(seen.mean())
    warn = []
    if spread > tolerance:
        warn.append("pozadí není jednobarevné – výsledek bude nepřesný (na fotky s rušným pozadím je potřeba AI model)")
    if removed > 0.97:
        warn.append("odstranilo se skoro všechno – zmenši toleranci")
    if removed < 0.03:
        warn.append("skoro nic se neodstranilo – objekt se dotýká okraje nebo je pozadí jiné, zvyš toleranci")
    return {"path": str(dst), "background": "#%02x%02x%02x" % tuple(int(v) for v in bg), "removed_pct": round(100 * removed, 1), "warnings": warn}


# ============================================================================================== 368 media organiser
MEDIA_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".tif", ".tiff", ".gif", ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp",
             ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
MONTHS = ["leden", "únor", "březen", "duben", "květen", "červen", "červenec", "srpen", "září", "říjen", "listopad", "prosinec"]


def media_date(p: Path):
    import datetime as dt

    from .fileuniverse import _taken_date

    if p.suffix.lower() in (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp"):
        try:
            import av

            with av.open(str(p)) as c:
                raw = c.metadata.get("creation_time") or (c.streams.video[0].metadata.get("creation_time") if c.streams.video else None)
            if raw:
                return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
        except Exception:  # noqa: BLE001
            pass
    return _taken_date(p)


def organize_plan(folder: Path, gap_hours: float = 6) -> dict:
    """Photos, videos and sound recordings → Rok/YYYY-MM-DD (or a multi-day event "YYYY-MM-DD až DD") by when they
    were taken; exact duplicates set aside."""
    from .fileuniverse import free_name, sha256

    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA_EXT and not p.name.startswith(".")]
    items = sorted(((media_date(p), p) for p in files), key=lambda x: x[0])
    seen: dict[str, Path] = {}
    plan, dups, events = [], [], []
    cur: list = []
    for d, p in items:
        if cur and (d - cur[-1][0]).total_seconds() > gap_hours * 3600:
            events.append(cur)
            cur = []
        cur.append((d, p))
    if cur:
        events.append(cur)
    taken: set[str] = set()
    for ev in events:
        first, last = ev[0][0], ev[-1][0]
        name = first.strftime("%Y-%m-%d") + (f" až {last.strftime('%d')}" if last.date() != first.date() and last.month == first.month else
                                             f" až {last.strftime('%Y-%m-%d')}" if last.date() != first.date() else "")
        target_dir = folder / first.strftime("%Y") / name
        for d, p in ev:
            h = sha256(p)
            if h in seen:
                dst = free_name(folder / "Duplicity" / p.name)
                dups.append({"file": str(p), "same_as": str(seen[h])})
            else:
                seen[h] = p
                dst = target_dir / p.name
                k = 2
                while str(dst).lower() in taken or (dst.exists() and dst != p):
                    dst = target_dir / f"{p.stem} ({k}){p.suffix}"
                    k += 1
            taken.add(str(dst).lower())
            if dst != p:
                plan.append({"src": str(p), "dst": str(dst)})
    return {"plan": plan, "events": [{"folder": (e[0][0].strftime("%Y-%m-%d")), "files": len(e)} for e in events], "duplicates": dups, "files": len(files)}


# ============================================================================================== 370 podcast chapters
STOP_SHORT = {"jsem", "jsme", "jste", "bylo", "byla", "jsou", "tady", "takze", "proste", "vlastne", "treba", "taky", "ještě", "jeste",
              "neco", "nekdo", "ktery", "ktera", "ktere", "kdyz", "protoze", "tedy", "toho", "tomu", "tom", "jako", "tak", "ale", "aby",
              "the", "and", "that", "this", "with", "you", "they", "have", "what", "just", "like", "dobre", "jo", "no", "ano", "mame", "mate"}


def _bag(text: str) -> Counter:
    from .webbiz import STOP

    return Counter(w for w in re.findall(r"[a-z0-9]{4,}", fold(text)) if w not in STOP and w not in STOP_SHORT)


def _cos(a: Counter, b: Counter) -> float:
    num = sum(a[k] * b[k] for k in a if k in b)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def chapters(segments: list[tuple[float, float, str]], block_s: float = 45, min_chapter_s: float = 120, max_chapters: int = 12) -> list[dict]:
    """TextTiling over the transcript: blocks of ~block_s seconds, similarity of the words before and after each
    block boundary; deep valleys = topic changes. Titles from the words typical for the chapter."""
    if not segments:
        return []
    end = segments[-1][1]
    blocks: list[tuple[float, Counter]] = []
    cur, start = Counter(), segments[0][0]
    for s, e, text in segments:
        if s - start >= block_s and cur:
            blocks.append((start, cur))
            cur, start = Counter(), s
        cur += _bag(text)
    blocks.append((start, cur))
    if len(blocks) < 3:
        cuts = [0]
    else:
        sims = [_cos(blocks[i - 1][1] + (blocks[i - 2][1] if i >= 2 else Counter()), blocks[i][1] + (blocks[i + 1][1] if i + 1 < len(blocks) else Counter()))
                for i in range(1, len(blocks))]
        depth = []
        for i, s in enumerate(sims):
            left = max(sims[:i + 1])
            right = max(sims[i:])
            depth.append((left - s) + (right - s))
        thr = float(np.mean(depth) + 0.5 * np.std(depth)) if depth else 1
        cand = sorted((i + 1 for i, d in enumerate(depth) if d > thr and d > 0.1), key=lambda i: -depth[i - 1])
        cuts = [0]
        for i in cand:
            if all(abs(blocks[i][0] - blocks[c][0]) >= min_chapter_s for c in cuts) and blocks[i][0] <= end - min_chapter_s / 2:
                cuts.append(i)
            if len(cuts) >= max_chapters:
                break
        cuts.sort()
    total = Counter()
    for _, b in blocks:
        total += b
    out = []
    for n, ci in enumerate(cuts):
        nxt = cuts[n + 1] if n + 1 < len(cuts) else len(blocks)
        words = Counter()
        for _, b in blocks[ci:nxt]:
            words += b
        score = {w: c * math.log(1 + sum(total.values()) / (1 + total[w])) for w, c in words.items() if c >= 2}
        top = [w for w, _ in sorted(score.items(), key=lambda kv: -kv[1])[:3]]
        start_s = 0.0 if n == 0 else blocks[ci][0]
        out.append({"start": round(start_s, 1), "stamp": f"{int(start_s // 3600):02d}:{int(start_s % 3600 // 60):02d}:{int(start_s % 60):02d}"
                    if end >= 3600 else f"{int(start_s // 60):02d}:{int(start_s % 60):02d}", "keywords": top,
                    "title": ", ".join(top).capitalize() if top else ("Úvod" if n == 0 else f"Část {n + 1}")})
    return out


# ============================================================================================== 371 shot matching
def _lab_stats(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from .gamedev import _lab

    lab = _lab(rgb.reshape(-1, 3).astype(np.float32))
    return lab.mean(axis=0), lab.std(axis=0) + 1e-6


def _lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    fy = (lab[..., 0] + 16) / 116
    fx, fz = fy + lab[..., 1] / 500, fy - lab[..., 2] / 200

    def inv(f):
        return np.where(f ** 3 > 0.008856, f ** 3, (f - 16 / 116) / 7.787)
    xyz = np.stack([inv(fx) * 0.95047, inv(fy), inv(fz) * 1.08883], axis=-1)
    m = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]])
    lin = np.clip(xyz @ m.T, 0, 1)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055) * 255


def color_transfer_fn(src_rgb: np.ndarray, ref_rgb: np.ndarray, strength: float = 1.0) -> Callable[[np.ndarray], np.ndarray]:
    """Reinhard colour transfer in Lab: the source shot's mean and contrast per channel → those of the reference."""
    from .gamedev import _lab

    ms, ss = _lab_stats(src_rgb)
    mr, sr = _lab_stats(ref_rgb)

    def f(rgb: np.ndarray) -> np.ndarray:
        lab = _lab(rgb.astype(np.float32))
        moved = (lab - ms) / ss * sr + mr
        lab = lab + strength * (moved - lab)
        return np.clip(_lab_to_rgb(lab), 0, 255).astype(np.uint8)
    return f


def write_cube(fn: Callable[[np.ndarray], np.ndarray], path: Path, n: int = 33, title: str = "JARVIS shot match") -> Path:
    g = np.linspace(0, 255, n)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")                      # .cube: red changes fastest
    grid = np.stack([r, gg, b], axis=-1).reshape(-1, 3)
    out = fn(grid.reshape(1, -1, 3).astype(np.uint8)).reshape(-1, 3) / 255.0
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {n}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    lines += [f"{c[0]:.6f} {c[1]:.6f} {c[2]:.6f}" for c in out]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


def read_cube(path: Path) -> np.ndarray:
    vals, n = [], None
    for ln in path.read_text(encoding="ascii").splitlines():
        if ln.startswith("LUT_3D_SIZE"):
            n = int(ln.split()[1])
        elif re.match(r"^[\d.\-]+\s+[\d.\-]+\s+[\d.\-]+$", ln.strip()):
            vals.append([float(v) for v in ln.split()])
    return np.array(vals).reshape(n, n, n, 3)                            # [b][g][r]


def apply_cube(lut: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    n = lut.shape[0]
    x = rgb.astype(np.float32) / 255 * (n - 1)
    i0 = np.clip(np.floor(x).astype(int), 0, n - 2)
    f = x - i0
    out = np.zeros(rgb.shape, np.float32)
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                w = (f[..., 0] if dr else 1 - f[..., 0]) * (f[..., 1] if dg else 1 - f[..., 1]) * (f[..., 2] if db else 1 - f[..., 2])
                out += w[..., None] * lut[i0[..., 2] + db, i0[..., 1] + dg, i0[..., 0] + dr]
    return np.clip(out * 255, 0, 255).astype(np.uint8)


def frame_at(src: Path, t: float | None = None) -> np.ndarray:
    """An image file, or a video frame at t seconds (default: the middle)."""
    from PIL import Image

    if src.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"):
        return np.asarray(Image.open(src).convert("RGB"))
    import av

    meta = video_meta(src)
    t = meta["seconds"] / 2 if t is None else t
    with av.open(str(src)) as c:
        vs = c.streams.video[0]
        c.seek(int(t / vs.time_base), stream=vs, backward=True)
        for fr in c.decode(vs):
            if fr.pts is not None and float(fr.pts * fr.time_base) >= t - 0.05:
                return fr.to_ndarray(format="rgb24")
    raise ValueError("Snímek nejde přečíst.")


# ============================================================================================== 372 voice-over script
def fit_script(script: str, scenes: list[tuple[float, float]], wps: float = 2.5) -> dict:
    """Spread the script's sentences over the scenes by time; per scene words that fit vs words given; what to cut."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+|\n+", script) if s.strip()]
    if not sentences or not scenes:
        raise ValueError("Zadej text a délky scén (nebo video).")
    total_words = sum(len(s.split()) for s in sentences)
    total_time = sum(e - s for s, e in scenes)
    out, k = [], 0
    for i, (s, e) in enumerate(scenes):
        budget = (e - s) * wps
        lines, used = [], 0
        share = total_words * (e - s) / total_time
        while k < len(sentences) and (used < share * 0.6 or i == len(scenes) - 1) and (used + len(sentences[k].split()) <= max(budget, share) * 1.25 or not lines):
            lines.append(sentences[k])
            used += len(sentences[k].split())
            k += 1
        out.append({"scene": i + 1, "start": s, "end": e, "text": " ".join(lines), "words": used, "fits": int(budget),
                    "over": max(0, used - int(budget)), "seconds_needed": round(used / wps, 1)})
    rest = sentences[k:]
    if rest:
        out[-1]["text"] += " " + " ".join(rest)
        extra = sum(len(r.split()) for r in rest)
        out[-1]["words"] += extra
        out[-1]["over"] = max(0, out[-1]["words"] - out[-1]["fits"])
    from .media import to_srt, wrap

    subs = [{"start": x["start"] + 0.2, "end": min(x["end"] - 0.1, x["start"] + 0.2 + x["seconds_needed"]), "text": wrap(x["text"], 42)}
            for x in out if x["text"]]
    return {"scenes": out, "words": total_words, "seconds_needed": round(total_words / wps, 1), "seconds_available": round(total_time, 1),
            "too_long": [x["scene"] for x in out if x["over"] > 0], "srt": to_srt(subs)}


# ============================================================================================== 373 sound effects
SFX_SQL = """CREATE TABLE IF NOT EXISTS sfx_index (path TEXT PRIMARY KEY, name TEXT, seconds REAL, loudness REAL, brightness REAL,
  attack REAL, tags TEXT, mtime REAL);"""
SYNONYMS = {"dvere": ["door"], "bouchnuti": ["slam", "bang"], "kroky": ["footstep", "steps", "walk"], "vybuch": ["explosion", "boom", "blast"], "dest": ["rain"],
            "potlesk": ["applause", "clap"], "zvonek": ["bell", "ring", "doorbell"], "klik": ["click", "tap", "button"], "svih": ["whoosh", "swish", "swoosh"],
            "vitr": ["wind"], "auto": ["car", "engine", "vehicle"], "pes": ["dog", "bark"], "kocka": ["cat", "meow"], "sklo": ["glass", "shatter"],
            "voda": ["water", "splash"], "ohen": ["fire", "crackle"], "hrom": ["thunder"], "ptaci": ["bird", "birds", "chirp"], "smich": ["laugh", "laughter"],
            "telefon": ["phone", "ring"], "klavesnice": ["keyboard", "typing"], "uder": ["hit", "punch", "impact"], "notifikace": ["notification", "ding", "chime"],
            "chyba": ["error", "fail", "buzz"], "uspech": ["success", "win", "level up"], "papir": ["paper", "page"], "mince": ["coin", "money"]}


def _tags(name: str) -> list[str]:
    """Words of the name / query plus their synonyms; Czech word forms match by the first four letters
    (dveře / dveří / dveřmi, bouchnutí / bouchnout)."""
    words = [w for w in re.split(r"[^a-z0-9]+", fold(name)) if len(w) > 1 and not w.isdigit()]
    out = set(words)
    for cz, en in SYNONYMS.items():
        if any(w == cz or (len(w) >= 4 and len(cz) >= 4 and w[:4] == cz[:4]) for w in words) or any(e in words for e in en):
            out |= {cz, *en}
    return sorted(out)


def sfx_features(x: np.ndarray, rate: int) -> dict:
    from .media import _mono

    m = _mono(x)
    if not len(m):
        return {"seconds": 0, "loudness": -120, "brightness": 0, "attack": 0}
    spec = np.abs(np.fft.rfft(m[: rate * 10]))
    f = np.fft.rfftfreq(min(len(m), rate * 10), 1 / rate)
    env = np.abs(m)
    peak_i = int(np.argmax(env))
    return {"seconds": round(len(m) / rate, 3), "loudness": round(20 * math.log10(max(float(np.sqrt(np.mean(m ** 2))), 1e-9)), 1),
            "brightness": round(float((spec * f).sum() / max(spec.sum(), 1e-9)), 1), "attack": round(peak_i / rate, 3)}


def index_sfx(rt, folder: Path, read=None) -> dict:
    from . import media

    rt.db.conn.executescript(SFX_SQL)
    read = read or media.read_audio
    n = skipped = 0
    for p in folder.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aif", ".aiff"):
            continue
        row = rt.db.one("SELECT mtime FROM sfx_index WHERE path=?", (str(p),))
        if row and abs(row["mtime"] - p.stat().st_mtime) < 1:
            skipped += 1
            continue
        try:
            x, rate = read(p, 60)
        except Exception:  # noqa: BLE001 – a broken file is skipped
            continue
        f = sfx_features(x, rate)
        rt.db.exec("INSERT OR REPLACE INTO sfx_index VALUES (?,?,?,?,?,?,?,?)",
                   (str(p), p.stem, f["seconds"], f["loudness"], f["brightness"], f["attack"], " ".join(_tags(str(p.relative_to(folder)))), p.stat().st_mtime))
        n += 1
    total = rt.db.one("SELECT count(*) AS n FROM sfx_index")["n"]
    return {"indexed": n, "unchanged": skipped, "total": total}


def search_sfx(rt, query: str = "", like: Path | None = None, max_seconds: float = 0, limit: int = 10) -> list[dict]:
    rt.db.conn.executescript(SFX_SQL)
    rows = rt.db.all("SELECT * FROM sfx_index")
    q = set(_tags(query)) if query else set()
    ref = None
    if like is not None:
        from . import media

        x, rate = media.read_audio(like, 60)
        ref = sfx_features(x, rate)
    out = []
    for r in rows:
        if max_seconds and r["seconds"] > max_seconds:
            continue
        tags = set(r["tags"].split())
        score = len(q & tags) * 10 if q else 0
        if q and not score:
            continue
        if ref:
            d = (abs(math.log((r["seconds"] + 0.05) / (ref["seconds"] + 0.05))) + abs(r["brightness"] - ref["brightness"]) / 2000 +
                 abs(r["loudness"] - ref["loudness"]) / 20 + abs(r["attack"] - ref["attack"]))
            score += max(0.0, 10 - 4 * d)
        out.append({"file": r["path"], "name": r["name"], "seconds": r["seconds"], "score": round(score, 2),
                    "character": ("ostrý" if r["attack"] < 0.03 else "pozvolný") + ", " + ("jasný" if r["brightness"] > 2500 else "tmavý")})
    return sorted(out, key=lambda x: -x["score"])[:limit]


# ============================================================================================== 129 subtitle sync
def speech_track(x: np.ndarray, rate: int, step: float = 0.05) -> np.ndarray:
    from .media import _mono

    m = _mono(x)
    n = int(len(m) / (rate * step))
    if n < 2:
        return np.zeros(1)
    hop = int(rate * step)
    rms = np.sqrt((m[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    thr = max(np.percentile(db, 30) + 10, db.max() - 35)
    return (db > thr).astype(np.float32)


def subs_track(subs: list[dict], length: int, step: float = 0.05) -> np.ndarray:
    a = np.zeros(length, np.float32)
    for s in subs:
        a[max(0, int(s["start"] / step)):max(0, int(s["end"] / step))] = 1
    return a


def _offset(speech: np.ndarray, subs: np.ndarray, max_shift: int) -> tuple[int, float]:
    best, score = 0, -1.0
    for k in range(-max_shift, max_shift + 1):
        if k >= 0:
            v = float((speech[k:] * subs[:len(subs) - k]).sum()) if k < len(subs) else 0.0
        else:
            v = float((speech[:k] * subs[-k:]).sum())
        if v > score:
            best, score = k, v
    return best, score


def sync_subtitles(subs: list[dict], x: np.ndarray, rate: int, max_shift_s: float = 60, step: float = 0.05) -> dict:
    """Find how much the subtitles are early / late against the speech (cross-correlation of speech activity and
    subtitle on-screen time); separately for each half → a stretch when the drift grows (23.976 vs 25 fps)."""
    sp = speech_track(x, rate, step)
    n = len(sp)
    st = subs_track(subs, n, step)
    ms = int(max_shift_s / step)
    off, _ = _offset(sp, st, ms)
    half = len(subs) // 2
    a, b = subs[:half], subs[half:]
    stretch, base = 1.0, off * step
    if len(a) >= 3 and len(b) >= 3:
        oa, _ = _offset(sp, subs_track(a, n, step), ms)
        ob, _ = _offset(sp, subs_track(b, n, step), ms)
        ta = np.mean([s["start"] for s in a])
        tb = np.mean([s["start"] for s in b])
        if abs(oa - ob) * step > 0.3 and tb > ta:                      # drift: fit t' = t·stretch + base
            stretch = ((tb + ob * step) - (ta + oa * step)) / (tb - ta)
            base = ta + oa * step - ta * stretch
    fixed = [{"start": round(max(0.0, s["start"] * stretch + base), 3), "end": round(max(0.0, s["end"] * stretch + base), 3), "text": s["text"]} for s in subs]
    before = float((sp * st).sum() / max(1, st.sum()))
    after_t = subs_track(fixed, n, step)
    after = float((sp * after_t).sum() / max(1, after_t.sum()))
    return {"offset_s": round(base, 3), "stretch": round(stretch, 5), "fixed": fixed, "match_before": round(before, 3), "match_after": round(after, 3)}


# ============================================================================================== 134 animated elements
def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def animate(elements: list[dict], dst: Path, size: tuple[int, int] = (1080, 1080), seconds: float = 5, fps: int = 30,
            background: str = "#101828") -> dict:
    """Elements [{image | text, x, y (0–1, centre), scale, start, end, effect: fade / slide-left / slide-up / zoom /
    pop, color, font_size}] composed frame by frame → MP4 (H.264)."""
    import av
    from PIL import Image, ImageDraw, ImageFont

    W, H = size
    W, H = W - W % 2, H - H % 2
    sprites = []
    for e in elements:
        if e.get("image"):
            im = Image.open(e["image"]).convert("RGBA")
            s = float(e.get("scale", 0.4)) * W / im.width
            im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
        else:
            fs = int(e.get("font_size", 72))
            try:
                font = ImageFont.truetype("DejaVuSans-Bold.ttf", fs)
            except OSError:
                try:
                    font = ImageFont.truetype("arialbd.ttf", fs)
                except OSError:
                    font = ImageFont.load_default(fs)
            box = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), str(e.get("text", "")), font=font)
            im = Image.new("RGBA", (box[2] - box[0] + 8, box[3] - box[1] + 8), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((4 - box[0], 4 - box[1]), str(e.get("text", "")), font=font, fill=e.get("color", "#ffffff"))
        sprites.append((e, im))
    out = av.open(str(dst), "w")
    vs = out.add_stream("libx264" if "libx264" in av.codecs_available else "mpeg4", rate=fps)
    vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
    n = int(seconds * fps)
    try:
        for i in range(n):
            t = i / fps
            frame = Image.new("RGBA", (W, H), background)
            for e, im in sprites:
                s0, s1 = float(e.get("start", 0)), float(e.get("end", seconds))
                if not s0 <= t <= s1:
                    continue
                k = _ease((t - s0) / max(0.01, float(e.get("in", 0.6))))
                k_out = _ease((s1 - t) / max(0.01, float(e.get("out", 0.4)))) if e.get("fade_out", True) and s1 < seconds else 1.0
                cx, cy = float(e.get("x", 0.5)) * W, float(e.get("y", 0.5)) * H
                spr, alpha = im, k * k_out
                eff = e.get("effect", "fade")
                if eff == "slide-left":
                    cx += (1 - k) * W * 0.6
                elif eff == "slide-up":
                    cy += (1 - k) * H * 0.4
                elif eff in ("zoom", "pop"):
                    z = (0.3 + 0.7 * k) if eff == "zoom" else (1 + 0.15 * math.sin(math.pi * min(1, k)) if k < 1 else 1)
                    spr = im.resize((max(1, int(im.width * z)), max(1, int(im.height * z))), Image.LANCZOS)
                if alpha < 1:
                    a = spr.getchannel("A").point(lambda v, al=alpha: int(v * al))
                    spr = spr.copy()
                    spr.putalpha(a)
                frame.alpha_composite(spr, (int(cx - spr.width / 2), int(cy - spr.height / 2)))
            vf = av.VideoFrame.from_ndarray(np.asarray(frame.convert("RGB")), format="rgb24")
            vf.pts = i
            for p in vs.encode(vf):
                out.mux(p)
        for p in vs.encode():
            out.mux(p)
    finally:
        out.close()
    return {"path": str(dst), "frames": n, "seconds": seconds, "size": [W, H]}


# ============================================================================================== 374 render queue
QUEUE_SQL = """CREATE TABLE IF NOT EXISTS render_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, args TEXT, status TEXT, progress REAL,
  result TEXT, error TEXT, created REAL, finished REAL);"""
KINDS = ("reframe", "clip", "color", "animate", "transcode")


def run_job(kind: str, a: dict, progress=None) -> dict:
    src = Path(a.get("src", ""))
    dst = Path(a["dst"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    if kind == "reframe":
        return reframe_video(src, dst, float(a.get("aspect", 9 / 16)), int(a.get("height", 1920)), progress)
    if kind == "clip":
        return process_video(src, dst, float(a["start"]), float(a["end"]), size=tuple(a["size"]) if a.get("size") else None, progress=progress)
    if kind == "color":
        lut = read_cube(Path(a["lut"]))
        return process_video(src, dst, filt=lambda img: apply_cube(lut, img), progress=progress)
    if kind == "animate":
        return animate(a["elements"], dst, tuple(a.get("size", (1080, 1080))), float(a.get("seconds", 5)), int(a.get("fps", 30)))
    if kind == "transcode":
        h = a.get("height")
        meta = video_meta(src)
        size = (int(meta["width"] * h / meta["height"]), int(h)) if h else None
        return process_video(src, dst, size=size, crf=int(a.get("crf", 23)), progress=progress)
    raise ValueError(f"Neznámá úloha {kind}.")


class RenderQueue:
    """Media jobs one after another in the background (CPU-heavy work must not run in parallel); kept in the
    database, so a restart shows what was done and what failed."""

    def __init__(self, rt):
        self.rt = rt
        rt.db.conn.executescript(QUEUE_SQL)
        rt.db.exec("UPDATE render_jobs SET status='přerušeno', error='JARVIS se během renderu ukončil.' WHERE status='běží'")
        self._task: asyncio.Task | None = None
        self._cancel: set[int] = set()

    def add(self, kind: str, args: dict) -> int:
        if kind not in KINDS:
            raise ValueError(f"Druh úlohy: {', '.join(KINDS)}.")
        self.rt.db.exec("INSERT INTO render_jobs(kind, args, status, progress, created) VALUES (?,?,?,?,?)",
                        (kind, json.dumps(args, ensure_ascii=False), "čeká", 0.0, time.time()))
        jid = self.rt.db.one("SELECT max(id) AS id FROM render_jobs")["id"]
        self.kick()
        return jid

    def kick(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._task is None or self._task.done():
            self._task = loop.create_task(self.run())

    def cancel(self, jid: int) -> bool:
        row = self.rt.db.one("SELECT status FROM render_jobs WHERE id=?", (jid,))
        if not row or row["status"] not in ("čeká", "běží"):
            return False
        if row["status"] == "čeká":
            self.rt.db.exec("UPDATE render_jobs SET status='zrušeno', finished=? WHERE id=?", (time.time(), jid))
        else:
            self._cancel.add(jid)
        return True

    def jobs(self, limit: int = 20) -> list[dict]:
        return [dict(r, args=json.loads(r["args"]), result=json.loads(r["result"]) if r["result"] else None)
                for r in self.rt.db.all("SELECT * FROM render_jobs ORDER BY id DESC LIMIT ?", (limit,))]

    async def run(self) -> None:
        while True:
            job = self.rt.db.one("SELECT * FROM render_jobs WHERE status='čeká' ORDER BY id LIMIT 1")
            if not job:
                return
            jid = job["id"]
            self.rt.db.exec("UPDATE render_jobs SET status='běží' WHERE id=?", (jid,))
            self.rt.bus.publish("render", id=jid, status="běží", progress=0)

            def prog(x, jid=jid):
                if jid in self._cancel:
                    raise InterruptedError("zrušeno")
                self.rt.db.exec("UPDATE render_jobs SET progress=? WHERE id=?", (round(x, 3), jid))
                self.rt.bus.publish_threadsafe("render", id=jid, status="běží", progress=round(x, 3))
            try:
                res = await asyncio.to_thread(run_job, job["kind"], json.loads(job["args"]), prog)
                self.rt.db.exec("UPDATE render_jobs SET status='hotovo', progress=1, result=?, finished=? WHERE id=?",
                                (json.dumps(res, ensure_ascii=False), time.time(), jid))
                self.rt.bus.publish("render", id=jid, status="hotovo", progress=1)
                self.rt.notify("Render hotový", f"{job['kind']} → {Path(res.get('path', '')).name}", speak=False)
            except InterruptedError:
                Path(json.loads(job["args"])["dst"]).unlink(missing_ok=True)
                self.rt.db.exec("UPDATE render_jobs SET status='zrušeno', finished=? WHERE id=?", (time.time(), jid))
            except Exception as e:  # noqa: BLE001 – one failed job does not stop the queue
                self.rt.db.exec("UPDATE render_jobs SET status='chyba', error=?, finished=? WHERE id=?", (str(e)[:300], time.time(), jid))
                self.rt.bus.publish("render", id=jid, status="chyba", error=str(e)[:200])
            finally:
                self._cancel.discard(jid)


def queue(rt) -> RenderQueue:
    q = getattr(rt, "_render_queue", None)
    if q is None:
        q = RenderQueue(rt)
        rt._render_queue = q
    return q
