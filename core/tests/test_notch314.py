"""3.14 Notch+ (návrhy 74–79)."""
import numpy as np

from conftest import drain
from jarvis import notchplus, tools

tools.load_builtin()


async def test_live_activity(rt):
    q = rt.bus.subscribe()
    r = await tools.call("live_activity", {"id": "build", "title": "Sestavuju aplikaci", "progress": 0.4}, rt)
    assert r.ok
    ev = [e for e in drain(q) if e["type"] == "live_activity"][0]
    assert ev["progress"] == 0.4 and not ev["done"]
    notchplus.live(rt, "build", "x", done=True)
    assert [e for e in drain(q) if e["type"] == "live_activity"][0]["done"]


async def test_widgets(rt):
    r = await tools.call("notch_widget_add", {"name": "Čas", "tool_name": "get_time", "every_min": 5}, rt)
    assert r.ok and rt.cfg.notch.widgets[0].tool == "get_time"
    items = rt.widgets.items()
    assert items and items[0]["ok"] and items[0]["name"] == "Čas"
    bad = await tools.call("notch_widget_add", {"name": "Vypni", "tool_name": "system_power"}, rt)
    assert not bad.ok
    assert rt.widgets.due() == []                                  # just refreshed


def test_mochi_level(rt):
    lv = notchplus.mochi_level(rt)
    assert lv["level"] == 1 and lv["locked"][0]["id"] == "headphones"
    for d in range(12):
        rt.db.exec("INSERT INTO messages (id, conv_id, role, content, attachments, source, created, meta) VALUES (?,?,?,?,?,?,?,?)",
                   (f"m{d}", "c", "user", "ahoj", "[]", "chat", 1.7e9 + d * 86400, "{}"))
    lv = notchplus.mochi_level(rt)
    assert lv["level"] >= 2 and any(u["id"] == "headphones" for u in lv["unlocked"])


def test_config_accepts_new_outfits():
    from jarvis import config

    assert config.Config.model_validate({"character": {"outfit": "halo"}}).character.outfit == "halo"


def test_load_watch(rt):
    w = notchplus.LoadWatch(rt)
    assert w.sample(90) is None and w.sample(95) is None
    assert w.sample(91) is True and w.heavy
    assert w.sample(70) is None
    assert w.sample(40) is False and not w.heavy


def test_spectrum_bands():
    t = np.arange(4800) / 48000
    bass = np.sin(2 * np.pi * 100 * t)
    treble = np.sin(2 * np.pi * 8000 * t)
    b, tr = notchplus.spectrum(bass), notchplus.spectrum(treble)
    assert len(b) == 8 and b[1] > b[6] and tr[6] > tr[1]
    assert notchplus.spectrum([0.0] * 10) == [0.0] * 8
