"""3.15 Mega animace na ploše: the frames of the desktop effects, drawn with Pillow (RGBA, transparent background).

The Windows side (jarvis/desktop/fxwin.py) shows them in small always-on-top windows that take no clicks, no keys and
are left out of screenshots; here they are only pictures, so they can be tested anywhere.
Every effect is a function (t from 0 to 1 over its duration) → an RGBA image of a fixed size.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 30


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = (hex_color or "#4fc3ff").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 79, 195, 255


def ease_out(t: float) -> float:
    return 1 - (1 - max(0.0, min(1.0, t))) ** 3


def _font(size: int, bold: bool = True) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for name in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arialbd.ttf" if bold else "arial.ttf", "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _glow(img: Image.Image, radius: int = 6) -> Image.Image:
    """The image plus a soft blurred copy under it (the hologram's glow)."""
    blur = img.filter(ImageFilter.GaussianBlur(radius))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.alpha_composite(blur)
    out.alpha_composite(img)
    return out


@dataclass
class Effect:
    """What to draw: the size of its window, where its centre goes, how long, and the frame for t in 0..1."""
    w: int
    h: int
    seconds: float
    frame: Callable[[float], Image.Image]
    cx: int = 0
    cy: int = 0
    move: Callable[[float], tuple[int, int]] | None = None     # the window's top-left over time (the scan line moves)

    def frames(self) -> int:
        return max(1, int(self.seconds * FPS))


def reticle(color: str = "#4fc3ff", label: str = "", size: int = 220) -> Callable[[float], Image.Image]:
    """The target lock where JARVIS clicks: two arcs closing in and turning, a dot, a ripple, the label."""
    c = rgb(color)
    font = _font(14)

    def frame(t: float) -> Image.Image:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        mid = size // 2
        k = ease_out(min(1, t / 0.4))
        fade = 1.0 if t < 0.7 else max(0.0, 1 - (t - 0.7) / 0.3)
        a = int(255 * fade)
        r1 = int(70 - 36 * k + 36 * (1 - k))
        spin = t * 300
        for r, w, off in ((max(18, r1), 3, 0), (max(10, int(r1 * 0.62)), 2, 90)):
            box = (mid - r, mid - r, mid + r, mid + r)
            for q in range(2):
                st = spin + off + q * 180
                d.arc(box, st, st + 70, fill=(*c, a), width=w)
        d.ellipse((mid - 4, mid - 4, mid + 4, mid + 4), fill=(255, 255, 255, a))
        rr = int(10 + 80 * ease_out(t))                       # the ripple
        d.ellipse((mid - rr, mid - rr, mid + rr, mid + rr), outline=(*c, int(200 * (1 - t))), width=2)
        if label and t > 0.15:
            tw = int(d.textlength(label, font=font)) + 16
            x0, y0 = min(size - tw - 2, mid + 30), mid - 34
            d.rounded_rectangle((x0, y0, x0 + tw, y0 + 22), 3, fill=(*c, a))
            d.text((x0 + 8, y0 + 3), label, font=font, fill=(0, 16, 24, a))
        return _glow(img, 4)
    return frame


def scanline(width: int, color: str = "#4fc3ff", height: int = 46) -> Callable[[float], Image.Image]:
    """The beam that sweeps down the screen while JARVIS reads it (the window moves; the picture is the beam)."""
    c = rgb(color)

    def frame(t: float) -> Image.Image:
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        fade = 1.0 if t < 0.8 else max(0.0, 1 - (t - 0.8) / 0.2)
        mid = height // 2
        for x in range(0, width, 4):                           # brightest in the middle of the screen, fading to the sides
            edge = 1 - abs(x / max(1, width) - 0.5) * 2
            a = int(255 * fade * (0.25 + 0.75 * edge))
            d.line((x, mid - 1, x + 4, mid - 1), fill=(*c, a), width=3)
            d.line((x, mid, x + 4, mid), fill=(255, 255, 255, int(a * 0.8)), width=1)
        return _glow(img, 8)
    return frame


def osd(what: str = "volume", value: float | None = None, text: str = "", color: str = "#4fc3ff", size: int = 220) -> Callable[[float], Image.Image]:
    """The round display for volume / brightness / the song: a ring filling up to the value."""
    c = rgb(color)
    big, small = _font(34), _font(15, bold=False)
    label = {"volume": "HLASITOST", "brightness": "JAS", "media": "HUDBA"}.get(what, what.upper()[:12])

    def frame(t: float) -> Image.Image:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        appear = ease_out(min(1, t / 0.15))
        fade = 1.0 if t < 0.8 else max(0.0, 1 - (t - 0.8) / 0.2)
        a = int(255 * fade * appear)
        mid, r = size // 2, int(80 * (0.85 + 0.15 * appear))
        d.ellipse((mid - r - 10, mid - r - 10, mid + r + 10, mid + r + 10), fill=(2, 14, 24, int(200 * fade * appear)))
        d.ellipse((mid - r, mid - r, mid + r, mid + r), outline=(*c, int(a * 0.25)), width=6)
        if value is not None:
            sweep = 360 * max(0.0, min(100.0, value)) / 100 * ease_out(min(1, t / 0.3))
            d.arc((mid - r, mid - r, mid + r, mid + r), -90, -90 + sweep, fill=(*c, a), width=6)
            num = str(int(round(value)))
            d.text((mid - d.textlength(num, font=big) / 2, mid - 26), num, font=big, fill=(230, 248, 255, a))
        lw = d.textlength(label, font=small)
        d.text((mid - lw / 2, mid + 20), label, font=small, fill=(*c, a))
        if text:
            t2 = text[:28]
            tw = d.textlength(t2, font=small)
            d.text((mid - tw / 2, mid + 42), t2, font=small, fill=(230, 248, 255, a))
        return _glow(img, 5)
    return frame


def welcome(text: str = "Vítejte zpět", color: str = "#4fc3ff", w: int = 760, h: int = 300) -> Callable[[float], Image.Image]:
    """"Vítejte zpět, pane" after unlocking: the reactor spins up, the words come in, all fades out."""
    c = rgb(color)
    font = _font(40)

    def frame(t: float) -> Image.Image:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        appear = ease_out(min(1, t / 0.2))
        fade = 1.0 if t < 0.8 else max(0.0, 1 - (t - 0.8) / 0.2)
        a = int(255 * appear * fade)
        cx, cy, R = w // 2, 92, int(64 * (0.6 + 0.4 * appear))
        spin = t * 540
        for r, width, off in ((R, 3, 0), (int(R * 0.72), 2, 120)):
            box = (cx - r, cy - r, cx + r, cy + r)
            for q in range(3):
                st = spin * (1 if off == 0 else -1) + off + q * 120
                d.arc(box, st, st + 80, fill=(*c, a), width=width)
        core = int(R * 0.38)
        d.ellipse((cx - core, cy - core, cx + core, cy + core), fill=(255, 255, 255, a))
        if t > 0.15:
            k = ease_out(min(1, (t - 0.15) / 0.25))
            tw = d.textlength(text, font=font)
            d.text((cx - tw / 2, 196 + (1 - k) * 14), text, font=font, fill=(230, 248, 255, int(a * k)))
        return _glow(img, 10)
    return frame


def dot(color: str = "#4fc3ff", size: int = 64) -> Callable[[float], Image.Image]:
    """Where JARVIS moves the mouse: a small fading pulse."""
    c = rgb(color)

    def frame(t: float) -> Image.Image:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        mid, r = size // 2, int(6 + 18 * ease_out(t))
        d.ellipse((mid - r, mid - r, mid + r, mid + r), outline=(*c, int(220 * (1 - t))), width=2)
        d.ellipse((mid - 3, mid - 3, mid + 3, mid + 3), fill=(255, 255, 255, int(255 * (1 - t))))
        return _glow(img, 3)
    return frame


def ring(color: str = "#ffcc00", size: int = 120) -> Callable[[float], Image.Image]:
    """3.20 (118) while you share your screen: a soft ring around the cursor, so others see where you point."""
    c = rgb(color)

    def frame(t: float) -> Image.Image:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        mid = size // 2
        r = int(size * 0.32 + 4 * math.sin(t * math.pi * 2))
        a = int(170 * (1 - abs(t - 0.5)))
        d.ellipse((mid - r, mid - r, mid + r, mid + r), outline=(*c, a), width=4)
        d.ellipse((mid - r + 6, mid - r + 6, mid + r - 6, mid + r - 6), fill=(*c, a // 6))
        return _glow(img, 4)
    return frame


def eq(bars: list[float], color: str = "#4fc3ff", w: int = 420, h: int = 46) -> Callable[[float], Image.Image]:
    """3.20 (113) music bars just above the taskbar (the music's own levels, a short fade)."""
    c = rgb(color)
    vals = [max(0.0, min(1.0, float(b))) for b in (bars or [])][:16] or [0.0]

    def frame(t: float) -> Image.Image:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        n = len(vals)
        bw = w / (n * 1.6)
        for i, v in enumerate(vals):
            bh = max(2, int((h - 6) * v * (0.85 + 0.15 * math.sin(t * math.pi * 2 + i))))
            x = int(i * bw * 1.6 + bw * 0.3)
            a = int(200 * (1 - t * 0.6))
            d.rounded_rectangle((x, h - bh, x + int(bw), h), radius=2, fill=(*c, a))
        return img
    return frame


def is_visible(img: Image.Image) -> bool:
    hi = img.split()[-1].getextrema()[1]
    return img.getbbox() is not None and isinstance(hi, (int, float)) and hi > 0


def demo_strip(effect: Callable[[float], Image.Image], steps: int = 5) -> Image.Image:
    """Frames side by side on a dark background (for a quick look in tests / screenshots)."""
    frames = [effect(i / (steps - 1)) for i in range(steps)]
    w, h = frames[0].size
    out = Image.new("RGBA", (w * steps, h), (8, 14, 22, 255))
    for i, f in enumerate(frames):
        out.alpha_composite(f, (i * w, 0))
    return out

