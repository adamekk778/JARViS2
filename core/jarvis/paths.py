"""Where JARVIS keeps its data."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """%APPDATA%\\JARVIS on Windows, $JARVIS_HOME or ~/.jarvis elsewhere."""
    if os.environ.get("JARVIS_HOME"):
        base = Path(os.environ["JARVIS_HOME"])
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
    for cand in (resource_dir() / "web" / "dist", resource_dir() / "web_dist"):
        if cand.exists():
            return cand
    return resource_dir() / "web" / "dist"
