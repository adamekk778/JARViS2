"""Render the JARVIS orb icon to PNG/ICO (run once; outputs are committed)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]


def orb(size: int, bg=True, pad=0.18) -> Image.Image:
    s = size * 4
    im = Image.new("RGBA", (s, s), (10, 12, 15, 255) if bg else (0, 0, 0, 0))
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = int(s * (0.5 - pad))
    c = s // 2
    gd.ellipse((c - r - s // 16, c - r - s // 16, c + r + s // 16, c + r + s // 16), fill=(46, 230, 255, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(s // 24))
    im = Image.alpha_composite(im, glow)
    d = ImageDraw.Draw(im)
    for i in range(r, 0, -2):  # radial gradient: bright top-left core → deep teal edge
        t = i / r
        col = (int(5 + 41 * (1 - t) ** 0.6 + 180 * (1 - t) ** 3), int(51 + 179 * (1 - t) ** 0.5), int(59 + 196 * (1 - t) ** 0.5), 255)
        off = int((1 - t) * r * 0.25)
        d.ellipse((c - i - off, c - i - off, c + i - off, c + i - off), fill=col)
    d.ellipse((c - r - s // 22, c - r - s // 22, c + r + s // 22, c + r + s // 22), outline=(46, 230, 255, 110), width=max(2, s // 90))
    return im.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    big = orb(1024)
    big.save(ROOT / "mobile" / "assets" / "icon.png")
    orb(1024, bg=False, pad=0.3).save(ROOT / "mobile" / "assets" / "icon-foreground.png")
    Image.new("RGBA", (1024, 1024), (10, 12, 15, 255)).save(ROOT / "mobile" / "assets" / "icon-background.png")
    splash = Image.new("RGBA", (2732, 2732), (10, 12, 15, 255))
    splash.alpha_composite(orb(600, bg=False), (1066, 1066))
    splash.save(ROOT / "mobile" / "assets" / "splash.png")
    splash.save(ROOT / "mobile" / "assets" / "splash-dark.png")
    big.save(ROOT / "packaging" / "jarvis.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.resize((256, 256), Image.LANCZOS).save(ROOT / "web" / "public" / "icons" / "jarvis-256.png")
    print("icons written")
