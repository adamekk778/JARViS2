"""3.12 Asking before closing apps/games, and "JARVIS právě ovládá tvůj PC" with take over / stop."""
import asyncio
from types import SimpleNamespace

from jarvis import tools
from jarvis.pccontrol import LINGER_S

tools.load_builtin()


def test_closing_an_app_always_asks_and_says_what_closes(monkeypatch):
    from jarvis.tools import apps

    spec = tools.REGISTRY["close_app"]
    assert tools.is_dangerous(spec, {"name": "Steam"})
    monkeypatch.setattr(apps, "matching_apps", lambda n: [{"name": "cs2.exe", "path": "c:/steam/steamapps/common/cs2.exe", "count": 1, "game": True}])
    lines = spec.details({"name": "cs2"})
    assert "Zavřu: cs2.exe" in lines[0] and any("hra" in x for x in lines)
    monkeypatch.setattr(apps, "matching_apps", lambda n: [])
    assert "neběží" in spec.details({"name": "nic"})[0]


async def test_frame_shows_while_jarvis_types_and_goes_after(rt, monkeypatch):
    seen = []
    rt.pc_control.listeners.append(lambda st: seen.append((st["on"], st["paused"])))
    monkeypatch.setattr(rt.platform, "type_text", lambda text: None, raising=False)
    res = await tools.call("type_text", {"text": "ahoj"}, rt)
    assert res.ok and seen[0] == (True, False) and rt.pc_control.on
    await asyncio.sleep(LINGER_S + 0.2)
    assert seen[-1] == (False, False) and not rt.pc_control.on


async def test_take_over_makes_jarvis_wait_until_given_back(rt):
    pc = rt.pc_control
    moves = []

    async def jarvis():
        async with pc.session("computer_use"):
            for i in range(3):
                await pc.wait_if_taken()
                moves.append(i)
                await asyncio.sleep(0.05)

    task = asyncio.create_task(jarvis())
    await asyncio.sleep(0.02)
    pc.take_over()
    assert pc.paused and pc.state()["on"]
    await asyncio.sleep(0.2)
    stuck = len(moves)
    assert stuck <= 1                                  # it stopped at the next move
    pc.give_back()
    await asyncio.wait_for(task, 2)
    assert moves == [0, 1, 2]


async def test_stop_turns_everything_off(rt):
    pc = rt.pc_control
    async with pc.session("mouse"):
        pc.take_over()
        rt.stop_all()
    assert not pc.on and not pc.paused and pc._resume.is_set()


async def test_websocket_take_and_give_are_local_only():
    from jarvis.server import ws

    assert {"pc_control_take", "pc_control_give"} <= ws.LOCAL_ONLY
    assert "pc_control" in ws.SERVER_TYPES
