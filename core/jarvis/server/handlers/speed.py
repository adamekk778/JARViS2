"""3.17 Změřit rychlost: the button in Diagnostika runs the speed check in the background and reports as it goes."""
from __future__ import annotations

from . import handles


@handles("speedcheck_run")
async def speedcheck_run(c, m: dict) -> None:
    from ... import speedcheck

    rt = c.rt
    if getattr(rt, "speedcheck_running", False) or rt.agent.busy:
        await c.send("speedcheck", running=False, error="JARVIS teď pracuje – zkus to za chvíli.")
        return

    async def go() -> None:
        def progress(i: int, n: int, row: dict) -> None:
            rt.bus.publish("speedcheck", running=True, done=i, total=n, last=row)
        rt.bus.publish("speedcheck", running=True, done=0, total=len(speedcheck.REQUESTS))
        try:
            rep = await speedcheck.run(rt, voice=bool(m.get("voice", True)), progress=progress)
            rt.bus.publish("speedcheck", running=False, report=rep, text=speedcheck.say(rep))
        except Exception as e:  # noqa: BLE001
            rt.bus.publish("speedcheck", running=False, error=str(e)[:200])
    c.spawn(go())


@handles("speedcheck_get")
async def speedcheck_get(c, m: dict) -> None:
    from ... import speedcheck

    rep = getattr(c.rt, "last_speedcheck", None)
    await c.send("speedcheck", running=False, **({"report": rep, "text": speedcheck.say(rep)} if rep else {}))
