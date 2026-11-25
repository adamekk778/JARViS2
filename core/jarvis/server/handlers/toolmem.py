"""3.17 Co se JARVIS naučil (návrh 13) and the check of your own requests (návrh 12)."""
from __future__ import annotations

from . import handles


@handles("toolmem_get")
async def toolmem_get(c, m: dict) -> None:
    from ... import toolmind

    await c.send("toolmem", items=toolmind.memory_list(c.rt))


@handles("toolmem_forget", local_only=True)
async def toolmem_forget(c, m: dict) -> None:
    from ... import toolmind

    n = toolmind.memory_forget(c.rt, str(m.get("phrase") or ""), str(m.get("tool") or ""), block=bool(m.get("block")),
                               everything=bool(m.get("all")))
    await c.send("toolmem", items=toolmind.memory_list(c.rt), changed=n)


@handles("mine_check", slow=True)
async def mine_check(c, m: dict) -> None:
    import asyncio

    from ...evals import mine

    await c.send("mine_check", **await asyncio.to_thread(mine.check, c.rt))
