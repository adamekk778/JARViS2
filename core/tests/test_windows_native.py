"""3.17 Ověření na skutečném Windows (návrh 1): the native parts that Linux cannot try – they run in CI on
windows-latest (GitHub Actions, the "Tests on Windows" step) and on any Windows PC with `pytest`.

- the effect windows on the desktop: layered, click-through, always on top, never active, left out of screenshots,
  a frame pushed with per-pixel alpha, the window gone afterwards,
- a whole effect played from an overlay_fx event (the thread ends and frees its slot),
- the live wallpaper's layer behind the desktop icons (WorkerW) – when the session has Explorer,
- the Piper voice loaded once and fast the second time – when Piper and a voice are installed.
"""
from __future__ import annotations

import ctypes
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only (runs in CI on windows-latest)")

WS_EX = {"LAYERED": 0x00080000, "TRANSPARENT": 0x00000020, "TOPMOST": 0x00000008, "TOOLWINDOW": 0x00000080,
         "NOACTIVATE": 0x08000000}


def _ex_style(hwnd: int) -> int:
    u = ctypes.windll.user32
    u.GetWindowLongW.restype = ctypes.c_long
    return u.GetWindowLongW(ctypes.c_void_p(hwnd), -20) & 0xFFFFFFFF          # GWL_EXSTYLE


def test_effect_window_is_click_through_on_top_and_out_of_screenshots(rt):
    from jarvis import fxrender
    from jarvis.desktop.fxwin import FxWin

    fx = FxWin(rt)
    hwnd = fx._window(220, 220)
    try:
        u = ctypes.windll.user32
        assert u.IsWindow(ctypes.c_void_p(hwnd))
        ex = _ex_style(hwnd)
        for name, bit in WS_EX.items():
            assert ex & bit, f"{name} missing"
        fx._push(hwnd, fxrender.reticle("#4fc3ff", "Test")(0.5), 100, 100)    # UpdateLayeredWindow with alpha
        fx._pump()
        aff = ctypes.c_uint(0)
        if hasattr(u, "GetWindowDisplayAffinity") and u.GetWindowDisplayAffinity(ctypes.c_void_p(hwnd), ctypes.byref(aff)):
            assert aff.value in (0x11, 0x1)                                     # excluded from capture (or monitor-only)
        rect = (ctypes.c_long * 4)()
        u.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))
        assert (rect[2] - rect[0], rect[3] - rect[1]) == (220, 220) and (rect[0], rect[1]) == (100, 100)
    finally:
        ctypes.windll.user32.DestroyWindow(ctypes.c_void_p(hwnd))
    assert not ctypes.windll.user32.IsWindow(ctypes.c_void_p(hwnd))


def test_a_whole_effect_plays_and_frees_its_slot(rt):
    from jarvis.desktop.fxwin import FxWin

    fx = FxWin(rt)
    fx.handle("click", {"x": 300, "y": 300, "label": "OK"})
    fx.handle("osd", {"what": "volume", "value": 40})
    assert fx.live >= 1
    deadline = time.time() + 6
    while fx.live and time.time() < deadline:
        time.sleep(0.05)
    assert fx.live == 0


def test_live_wallpaper_layer_behind_the_icons(rt):
    from jarvis.desktop import winutil
    from jarvis.desktop.fxwin import FxWin

    layer = winutil.desktop_layer()
    if not layer:
        pytest.skip("no Explorer desktop in this session")
    fx = FxWin(rt)
    hwnd = fx._window(200, 120)
    try:
        assert winutil.attach_to_desktop(hwnd, 0, 0, 200, 120)
        u = ctypes.windll.user32
        u.GetParent.restype = ctypes.c_void_p
        assert int(u.GetParent(ctypes.c_void_p(hwnd)) or 0) == int(layer)
    finally:
        ctypes.windll.user32.DestroyWindow(ctypes.c_void_p(hwnd))
        winutil.refresh_wallpaper()


def test_piper_voice_is_quick_the_second_time():
    piper = pytest.importorskip("piper")
    assert piper
    from jarvis import paths
    from jarvis.voice import tts

    voices = sorted((paths.sub("models") / "piper").glob("*.onnx"))
    if not voices:
        pytest.skip("no Piper voice installed")
    name = voices[0].stem
    t0 = time.perf_counter()
    a = tts.piper_synth("Dobrý den, pane.", name)
    first = time.perf_counter() - t0
    t1 = time.perf_counter()
    b = tts.piper_synth("Všechny systémy v normě.", name)
    second = time.perf_counter() - t1
    assert a[:4] == b[:4] == b"RIFF" and second < max(first, 0.05) * 1.5
