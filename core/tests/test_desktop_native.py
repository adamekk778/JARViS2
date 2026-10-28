"""Notch / pet window geometry on Windows: one atomic SetWindowPos in physical pixels, window region, cursor check."""
from types import SimpleNamespace

import pytest

from jarvis.desktop import host as host_mod
from jarvis.desktop import platforms, winutil
from jarvis.desktop.pet import Rect


@pytest.fixture
def fake_win(monkeypatch):
    calls = []
    monkeypatch.setattr(winutil, "find_window", lambda title: 4242)
    monkeypatch.setattr(winutil, "window_handle", lambda win, title: 4242)
    monkeypatch.setattr(winutil, "dpi_scale", lambda hwnd: 1.25)
    monkeypatch.setattr(winutil, "set_window_rect", lambda hwnd, x, y, w, h: calls.append(("rect", hwnd, x, y, w, h)))
    monkeypatch.setattr(winutil, "set_region", lambda hwnd, polys: calls.append(("region", hwnd, polys)) or True)
    monkeypatch.setattr(winutil, "cursor_over", lambda hwnd: calls.append(("cursor", hwnd)) or True)
    monkeypatch.setattr(platforms, "monitors", lambda: [(Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1040))])
    return calls


def _host(rt):
    h = host_mod.DesktopHost(rt, "http://127.0.0.1:8765")
    h.notch = SimpleNamespace(resize=lambda *a: pytest.fail("pywebview resize used"),
                              move=lambda *a: pytest.fail("pywebview move used"))
    return h


def test_place_notch_is_one_physical_setwindowpos(rt, fake_win):
    h = _host(rt)
    h.place_notch(360, 100)  # CSS px from the page
    assert fake_win == [("rect", 4242, (1920 - 450) // 2, 0, 450, 125)]


def test_place_notch_offset_scaled(rt, fake_win):
    rt.cfg.notch.offset_x = 40
    _host(rt).place_notch(200, 40)
    assert fake_win[0][2] == (1920 - 250) // 2 + 50


def test_notch_api_region_and_cursor(rt, fake_win):
    api = host_mod.NotchApi(_host(rt))
    api.region([[[10.4, 0], [20.6, 0], [20, 30.2]]])
    assert fake_win[-1] == ("region", 4242, [[(10, 0), (21, 0), (20, 30)]])
    assert api.cursor_inside() is True and ("cursor", 4242) in fake_win


def test_region_resent_unchanged_is_not_reapplied_but_a_lost_one_comes_back(rt, fake_win, monkeypatch):
    """The grey box around the notch: Windows dropped the window region (or never got it) and nothing put it back."""
    kind = {"v": 3}
    monkeypatch.setattr(winutil, "region_kind", lambda hwnd: kind["v"])
    h = _host(rt)
    api = host_mod.NotchApi(h)
    poly = [[[0, 0], [10, 0], [10, 5]]]
    assert api.region(poly) is True and api.region(poly) is True
    assert sum(1 for c in fake_win if c[0] == "region") == 1          # the 2 s re-send does not repaint
    assert h.heal_region() is False                                     # region in place: nothing to do
    kind["v"] = 0                                                       # Windows lost it
    assert h.heal_region() is True and sum(1 for c in fake_win if c[0] == "region") == 2
    kind["v"] = 3
    monkeypatch.setattr(winutil, "set_region", lambda hwnd, polys: False)
    assert api.region([[[0, 0], [20, 0], [20, 5]]]) is False            # not taken → the page will send it again


def test_late_animation_frames_are_dropped(rt, fake_win, monkeypatch):
    """pywebview runs each call on its own thread: an older frame arriving after a newer one must not win."""
    monkeypatch.setattr(winutil, "region_kind", lambda hwnd: 3)
    api = host_mod.NotchApi(_host(rt))
    frame = lambda n: [[[0, 0], [n, 0], [n, 5]]]                       # noqa: E731
    base = 1_700_000_000_000_000
    assert api.region(frame(30), base + 3) and api.region(frame(10), base + 1)   # frame 1 arrives last
    regions = [c[2] for c in fake_win if c[0] == "region"]
    assert regions == [[[(0, 0), (30, 0), (30, 5)]]]
    assert api.region(frame(40), base + 4) and api.region(frame(50), 5)          # page reloaded: numbers restart
    assert [c[2][0][1][0] for c in fake_win if c[0] == "region"] == [30, 40, 50]


def test_notch_window_fits_every_mode_and_matches_the_page():
    from jarvis import config

    n = config.Config().notch
    w, h = host_mod.notch_window_size(n)
    assert (w, h) == (max(n.expanded_width, 560) + 2 * host_mod.PAD, max(340, n.expanded_height) + host_mod.PAD)
    small = n.model_copy(update={"expanded_width": 600})                # the page treats < 900 as the default
    assert host_mod.notch_window_size(small) == (1000 + 2 * host_mod.PAD, 410 + host_mod.PAD)
    import pathlib

    ts = (pathlib.Path(host_mod.__file__).parents[3] / "web" / "src" / "notch" / "main.ts").read_text(encoding="utf-8")
    assert "Math.max(cfg.expanded_width || 1000, 560" in ts and "Math.max(340, cfg.expanded_height || 390" in ts


def test_mica_backdrop_turned_off_on_the_notch(rt, fake_win, monkeypatch):
    """pywebview gives windows Mica in dark mode and Windows paints it as a grey box around the notch."""
    seen = []
    monkeypatch.setattr(winutil, "no_backdrop", lambda hwnd: seen.append(hwnd) or 2)
    h = _host(rt)
    h.no_backdrop()
    assert seen == [4242]
    monkeypatch.undo()
    assert winutil.no_backdrop(0) is None and winutil.DWMWA_SYSTEMBACKDROP_TYPE == 38


def test_notch_handle_found_again_when_window_recreated(rt, fake_win, monkeypatch):
    alive = {4242}
    monkeypatch.setattr(winutil, "is_window", lambda hwnd: hwnd in alive)
    h = _host(rt)
    assert h.notch_hwnd() == 4242
    alive.clear()
    alive.add(5151)
    monkeypatch.setattr(winutil, "window_handle", lambda win, title: 5151)
    assert h.notch_hwnd() == 5151


def test_notch_api_cursor_without_window(rt, monkeypatch):
    monkeypatch.setattr(winutil, "window_handle", lambda win, title: 0)
    assert host_mod.NotchApi(_host(rt)).cursor_inside() is False


def test_notch_window_not_transparent():
    """A pywebview 'transparent' window shows the WinForms grey/white back colour around the page on Windows."""
    import inspect

    src = inspect.getsource(host_mod.DesktopHost.create_windows)
    assert "transparent=True" not in src and 'background_color="#000000"' in src


def test_winutil_noops_off_windows():
    assert winutil.set_window_rect(1, 0, 0, 10, 10) is None
    assert winutil.set_region(1, [[(0, 0), (1, 0), (1, 1)]]) is False
    assert winutil.region_kind(1) in (-1, 0) and not winutil.is_window(0)          # Windows: no such window → 0
    assert winutil.cursor_over(1) is False
    assert winutil.dpi_scale(1) == 1.0


def test_window_handle_prefers_own_native_handle(monkeypatch):
    monkeypatch.setattr(winutil, "IS_WIN", True)
    monkeypatch.setattr(winutil, "find_own_window", lambda title: 777)
    native = SimpleNamespace(native=SimpleNamespace(Handle=SimpleNamespace(ToInt64=lambda: 31337)))
    assert winutil.window_handle(native, "JARVIS Notch") == 31337
    assert winutil.window_handle(SimpleNamespace(), "JARVIS Notch") == 777   # no native handle → own-process lookup


def test_hard_edges_by_default_smooth_only_when_chosen(rt, monkeypatch):
    """Per-pixel alpha made Windows draw a grey box (and a white rim) around the notch on a user's PC, so the
    window is cut to the shape by default; smooth edges only when chosen in Settings – also for old config
    files that still say smooth_edges = true."""
    from jarvis import config
    from jarvis.desktop import winutil

    assert winutil.enable_alpha(0) is False   # no window, no change (and off Windows it never touches DWM)
    old = config.Config.model_validate({"notch": {"smooth_edges": True}})
    assert old.notch.edges == "hard"
    h = _host(rt)
    tried = []
    monkeypatch.setattr(h, "_make_alpha", lambda win, hwnd: tried.append(hwnd) or True)
    h.notch.evaluate_js = lambda js: None
    h._smooth_edges()
    assert tried == [] and h.alpha is False
    rt.cfg.notch.edges = "smooth"
    h._smooth_edges()
    assert tried and h.alpha is True
