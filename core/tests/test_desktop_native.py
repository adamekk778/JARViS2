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
    monkeypatch.setattr(winutil, "set_region", lambda hwnd, polys: calls.append(("region", hwnd, polys)))
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
    assert winutil.set_region(1, [[(0, 0), (1, 0), (1, 1)]]) is None
    assert winutil.cursor_over(1) is False
    assert winutil.dpi_scale(1) == 1.0


def test_window_handle_prefers_own_native_handle(monkeypatch):
    monkeypatch.setattr(winutil, "IS_WIN", True)
    monkeypatch.setattr(winutil, "find_own_window", lambda title: 777)
    native = SimpleNamespace(native=SimpleNamespace(Handle=SimpleNamespace(ToInt64=lambda: 31337)))
    assert winutil.window_handle(native, "JARVIS Notch") == 31337
    assert winutil.window_handle(SimpleNamespace(), "JARVIS Notch") == 777   # no native handle → own-process lookup


def test_smooth_edges_is_safe_off_windows_and_on_by_default():
    from jarvis import config
    from jarvis.desktop import winutil

    assert winutil.enable_alpha(0) is False   # no window, no change (and off Windows it never touches DWM)
    assert config.Config().notch.smooth_edges is True
