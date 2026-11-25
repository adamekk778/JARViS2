"""3.20 Paměť+: another JARVIS of yours syncs its memory (60); ★ a favourite answer (55)."""
from __future__ import annotations

from . import handles


@handles("mem_sync", slow=True)
async def mem_sync(c, m: dict) -> None:
    """The other PC's facts, encrypted with this PC's pairing key – only a PC paired with the main key can send them."""
    from ... import memx

    key = c.rt.cfg.phone.token
    try:
        r = memx.import_facts(c.rt, str(m.get("blob") or ""), key)
    except ValueError as e:
        await c.send("mem_sync_done", error=str(e))
        return
    await c.send("mem_sync_done", added=r["added"], removed=r["removed"], blob=memx.export_facts(c.rt, key))


@handles("msg_star")
async def msg_star(c, m: dict) -> None:
    from ... import memx

    ok = memx.star(c.rt, str(m.get("id") or ""), bool(m.get("on", True)))
    await c.send("msg_starred", id=str(m.get("id") or ""), on=bool(m.get("on", True)) and ok)
