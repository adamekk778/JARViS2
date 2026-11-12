"""3.12 Vzdálená plocha: a paired phone sees and drives the PC – only when allowed on the PC, always visible there."""
import asyncio

import pytest


def test_off_until_allowed_on_the_pc(rt):
    assert "Zapni ji jednou na PC" in rt.remote_desk.why_not(None)
    rt.cfg.phone_link.remote_desktop = True
    assert rt.remote_desk.why_not(None) == ""
    assert "Co smí telefon" in rt.remote_desk.why_not({"screen"})        # the phone must be allowed input too


def test_finger_drives_the_pc_and_the_pc_shows_it(rt):
    rt.cfg.phone_link.remote_desktop = True
    calls = []
    p = rt.platform
    p.click = lambda x, y, button="left", double=False: calls.append(("click", x, y, button, double))
    p.drag = lambda *a: calls.append(("drag", *a))
    p.scroll = lambda dy: calls.append(("scroll", dy))
    p.type_text = lambda t: calls.append(("text", t))
    p.hotkey = lambda keys: calls.append(("keys", tuple(keys)))
    rt.notify = lambda *a, **k: 0

    async def main():
        rt.screen_share.size = (1920, 1080)
        st = rt.remote_desk.start("Pixel 8")
        assert st["on"] and rt.pc_control.state()["remote"] and rt.pc_control.on      # frame + "Telefon ovládá PC"
        assert rt.screen_share.active
        await rt.remote_desk.input({"kind": "tap", "x": 0.5, "y": 0.5})
        await rt.remote_desk.input({"kind": "right", "x": 1.5, "y": -1})              # clamped to the screen
        await rt.remote_desk.input({"kind": "double", "x": 0, "y": 0})
        await rt.remote_desk.input({"kind": "drag", "x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.3})
        await rt.remote_desk.input({"kind": "scroll", "dy": 999})
        await rt.remote_desk.input({"kind": "text", "text": "ahoj"})
        await rt.remote_desk.input({"kind": "key", "key": "alttab"})
        await rt.remote_desk.input({"kind": "key", "key": "rm -rf"})                  # unknown keys do nothing
        rt.pc_control.take_over()                                                     # "Ukončit" in the notch
        assert not rt.remote_desk.on and not rt.pc_control.state()["remote"] and not rt.screen_share.active
        with pytest.raises(PermissionError):
            await rt.remote_desk.input({"kind": "tap", "x": 0.5, "y": 0.5})

    asyncio.run(main())
    assert calls == [("click", 960, 540, "left", False), ("click", 1919, 0, "right", False), ("click", 0, 0, "left", True),
                     ("drag", 192, 108, 384, 324), ("scroll", 30), ("text", "ahoj"), ("keys", ("alt", "tab"))]


def test_stop_all_ends_remote(rt):
    rt.cfg.phone_link.remote_desktop = True
    rt.notify = lambda *a, **k: 0

    async def main():
        rt.remote_desk.start("Telefon")
        rt.stop_all()
        assert not rt.remote_desk.on and not rt.pc_control.on

    asyncio.run(main())
