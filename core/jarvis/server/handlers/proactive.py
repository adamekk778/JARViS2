"""3.14 Myslí dopředu (návrhy 64, 66): which proactive notices you use or let pass; the muted kinds."""
from __future__ import annotations

from ... import proactiveplus
from . import handles


@handles("notice_feedback")
async def notice_feedback(c, m: dict) -> None:
    kind = str(m.get("kind", ""))[:30]
    if kind:
        proactiveplus.feedback(c.rt, kind, "used" if m.get("action") == "used" else "ignored")


@handles("proactive_get")
async def proactive_get(c, m: dict) -> None:
    st = c.rt.cfg.stark
    await c.send("proactive", stats=proactiveplus.stats(c.rt), muted=list(st.muted_kinds), labels=proactiveplus.KIND_LABEL,
                 daily_max=st.proactive_daily_max)
