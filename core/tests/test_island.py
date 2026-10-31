"""3.11 island notch: the volume bar follows system volume changes; the look is a setting."""
from conftest import drain
from jarvis import sysplus


async def test_volume_changes_are_published_not_the_first_reading(rt):
    q = rt.bus.subscribe()
    rt.platform.volume, rt.platform.muted = 40, False
    states = iter([(40, False), (40, False), (55, False), (55, True)])
    rt.platform.audio_state = lambda: next(states)
    await sysplus.volume_loop(rt, interval=0, rounds=4)
    ev = [e for e in drain(q) if e["type"] == "volume"]
    assert [(e["level"], e["muted"]) for e in ev] == [(55, False), (55, True)]
    assert rt.last_audio == {"level": 55, "muted": True}


async def test_no_speaker_is_quiet(rt, monkeypatch):
    q = rt.bus.subscribe()
    rt.platform.audio_state = lambda: (None, None)
    real_sleep = sysplus.asyncio.sleep
    monkeypatch.setattr(sysplus.asyncio, "sleep", lambda s: real_sleep(0))   # the 5 s back-off, without waiting
    await sysplus.volume_loop(rt, interval=0, rounds=3)
    assert not [e for e in drain(q) if e["type"] == "volume"]


def test_island_is_the_default_look():
    import pathlib

    from jarvis import config
    from jarvis.server import ws

    assert config.Config().notch.style == "island" and "volume" in ws.SERVER_TYPES
    ts = (pathlib.Path(__file__).parents[2] / "web" / "src" / "shared" / "protocol.ts").read_text(encoding="utf-8")
    assert '"volume"' in ts
