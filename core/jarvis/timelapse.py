"""3.18 Hotový tisk (návrh 10): while a print runs JARVIS keeps a camera picture every couple of minutes; when it is
done, they become a short time-lapse video (and the last picture a photo) in the workshop journal, and the phone gets
"hotovo" with where to find them. Pictures stay on this PC; old prints' frames are deleted after the video is made.
"""
from __future__ import annotations

import io
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("jarvis.timelapse")
MAX_FRAMES = 240
WIDTH = 640


def folder(job: str) -> Path:
    from . import paths
    from .cad import slug

    d = paths.sub("workshop") / "timelapse" / (re.sub(r"[^a-z0-9-]+", "-", slug(job)).strip("-")[:60] or "tisk")
    d.mkdir(parents=True, exist_ok=True)
    return d


def add_frame(job: str, jpg: bytes) -> int:
    """Keep one camera picture (a JPEG) of a running print; returns how many there are."""
    if not jpg or jpg[:2] != b"\xff\xd8":
        return 0
    d = folder(job)
    frames = sorted(d.glob("f-*.jpg"))
    if len(frames) >= MAX_FRAMES:                 # a long print: keep every second picture, then go on
        for f in frames[1::2]:
            f.unlink(missing_ok=True)
        frames = sorted(d.glob("f-*.jpg"))
    # numbered, not timed: two pictures in the same millisecond (a fast PC, a coarse Windows clock) never overwrite
    last = max((int(m.group(1)) for f in frames if (m := re.match(r"f-(\d+)\.jpg$", f.name))), default=0)
    (d / f"f-{last + 1:07d}.jpg").write_bytes(jpg)
    return len(frames) + 1


def build(job: str, fps: int = 12) -> Path | None:
    """The frames → an MP4 (H.264, or MPEG-4 when the codec is missing); None with fewer than 3 frames."""
    from PIL import Image

    d = folder(job)
    frames = sorted(d.glob("f-*.jpg"))
    if len(frames) < 3:
        return None
    import av

    out = d.parent / f"{d.name}-{time.strftime('%Y%m%d-%H%M')}.mp4"
    with Image.open(frames[0]) as first:         # closed again: Windows cannot delete a file that is still open
        fw, fh = first.size
    w = WIDTH
    h = int(fh * w / fw) // 2 * 2
    codec = "libx264" if "libx264" in av.codecs_available else "mpeg4"
    with av.open(str(out), "w") as box:
        st: Any = box.add_stream(codec, rate=fps)
        st.width, st.height, st.pix_fmt = w, h, "yuv420p"
        for f in frames:
            try:
                img = Image.open(io.BytesIO(f.read_bytes())).convert("RGB").resize((w, h))
            except OSError:
                continue
            for pkt in st.encode(av.VideoFrame.from_image(img)):
                box.mux(pkt)
        for pkt in st.encode():
            box.mux(pkt)
    last = d.parent / f"{d.name}-hotovo.jpg"
    shutil.copy2(frames[-1], last)
    shutil.rmtree(d, ignore_errors=True)
    return out
