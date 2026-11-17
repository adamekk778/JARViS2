"""3.12 Notch v barvě tapety: while nothing plays, the island takes a dark shade of your desktop wallpaper (Nastavení →
Notch → Barva notche). Only a 48 px thumbnail of the wallpaper is read, on this PC, and nothing leaves it."""
from __future__ import annotations

import base64
import io
import os
import sys
from pathlib import Path

_CACHE: dict = {"key": None, "thumb": ""}


def path() -> str:
    """The wallpaper file Windows shows now ("" when there is none, e.g. a plain colour)."""
    if "JARVIS_WALLPAPER" in os.environ or sys.platform != "win32":     # tests (and other systems) name it themselves
        return os.environ.get("JARVIS_WALLPAPER", "")
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(520)
        if ctypes.windll.user32.SystemParametersInfoW(0x0073, 520, buf, 0) and buf.value:   # SPI_GETDESKWALLPAPER
            return buf.value
    except Exception:  # noqa: BLE001
        pass
    cache = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Themes" / "TranscodedWallpaper"
    return str(cache) if cache.exists() else ""


def thumb() -> str:
    """A small JPEG of the wallpaper as a data: URL – the notch picks its colour from it ("" without a wallpaper)."""
    p = path()
    if not p or not Path(p).exists():
        return ""
    st = Path(p).stat()
    key = (p, st.st_mtime, st.st_size)
    if _CACHE["key"] == key:
        return _CACHE["thumb"]
    from PIL import Image

    with Image.open(p) as im:
        im = im.convert("RGB")
        im.thumbnail((48, 48))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=70)
    _CACHE.update(key=key, thumb="data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode())
    return _CACHE["thumb"]
