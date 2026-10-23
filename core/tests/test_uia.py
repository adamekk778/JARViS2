from conftest import drain

from jarvis import tools

tools.load_builtin()


async def test_inspect_lists_buttons(ctx):
    res = await tools.call("ui_inspect", {"window": "Kalkulačka"}, ctx)
    assert res.ok
    names = [n["name"] for n in res.data]
    assert "Sedm" in names and all(n["ref"] for n in res.data)


async def test_click_by_name_verifies(ctx):
    res = await tools.call("ui_click", {"target": "Sedm", "window": "Kalkulačka"}, ctx)
    assert res.ok and res.data["verified"] is True and res.data["window"] == "Kalkulačka"
    acts = [c for c in ctx.platform.calls if c[0] == "ui_act"]
    assert acts and acts[-1][2] == "invoke"


async def test_type_reads_back(ctx):
    res = await tools.call("ui_type", {"target": "Výsledek", "text": "84", "window": "Kalkulačka"}, ctx)
    assert res.ok and res.data["value"] == "84"


def test_danger_keywords():
    spec = tools.REGISTRY["ui_click"]
    assert tools.is_dangerous(spec, {"target": "Smazat vše"})
    assert tools.is_dangerous(spec, {"target": "OK", "window": "Odeslat zprávu"})
    assert not tools.is_dangerous(spec, {"target": "Sedm", "window": "Kalkulačka"})


async def test_own_windows_refused(ctx):
    res = await tools.call("ui_click", {"target": "x", "window": "JARVIS"}, ctx)
    assert not res.ok and "JARVIS" in res.summary


async def test_czech_unicode_names(ctx):
    node = ctx.platform.ui_find(window="kalkulacka", name="rovna se")
    assert node and node["name"] == "Rovná se"


async def test_missing_element(ctx):
    res = await tools.call("ui_click", {"target": "Neexistuje", "window": "Kalkulačka"}, ctx)
    assert not res.ok and "Nenašel" in res.summary


async def test_mouse_drag(ctx):
    res = await tools.call("mouse", {"action": "drag", "x": 1, "y": 2, "x2": 3, "y2": 4}, ctx)
    assert res.ok and ("drag", 1, 2, 3, 4) in ctx.platform.calls


async def test_mouse_needs_input_permission(ctx):
    from jarvis import config

    ctx.cfg = config.Config.model_validate({"permissions": {"input": False}})
    res = await tools.call("mouse", {"action": "click", "x": 1, "y": 1}, ctx)
    assert not res.ok


async def test_screen_capture_events(ctx):
    q = ctx.bus.subscribe()
    await tools.call("screenshot", {}, ctx)
    ev = [e for e in drain(q) if e["type"] == "screen_capture"]
    assert [e["active"] for e in ev] == [True, False]


def test_selftest_uia_skips_off_windows(capsys):
    import json

    from jarvis.__main__ import main

    assert main(["--selftest-uia"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "skipped" in out
