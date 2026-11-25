"""Where JARVIS keeps its data."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """%APPDATA%\\JARVIS on Windows, $JARVIS_HOME or ~/.jarvis elsewhere."""
    portable = None
    if not os.environ.get("JARVIS_HOME"):
        from .communityx import demo_base, demo_on, portable_base

        portable = demo_base() if demo_on() else portable_base(sys.executable, bool(getattr(sys, "frozen", False)))
    if os.environ.get("JARVIS_HOME"):
        base = Path(os.environ["JARVIS_HOME"])
    elif portable is not None:                       # 3.20 (490) from a USB stick, (497) the demo in a fresh folder
        base = portable
    elif sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"]) / "JARVIS"
    else:
        base = Path.home() / ".jarvis"
    base.mkdir(parents=True, exist_ok=True)
    return base


def sub(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def resource_dir() -> Path:
    """Directory with bundled resources (web/dist, models) — works frozen too."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def web_dist() -> Path:
    env = os.environ.get("JARVIS_WEB_DIST")          # 3.14 the server image keeps the UI next to the installed core
    if env and Path(env).exists():
        return Path(env)
    for cand in (resource_dir() / "web" / "dist", resource_dir() / "web_dist"):
        if cand.exists():
            return cand
    return resource_dir() / "web" / "dist"
