"""3.14 Notch+ (návrhy 75, 76, 78): widgets, Mochi's level."""
from __future__ import annotations

from ... import notchplus
from . import handles


@handles("widgets_get", slow=True)
async def widgets_get(c, m: dict) -> None:
    wid = getattr(c.rt, "widgets", None)
    items = await wid.refresh(force=bool(m.get("refresh"))) if wid is not None else []
    await c.send("widgets", items=items)


@handles("widget_delete", local_only=True)
async def widget_delete(c, m: dict) -> None:
    wid_id = str(m.get("id", ""))
    c.rt.update_config({"notch": {"widgets": [w.model_dump() for w in c.rt.cfg.notch.widgets if w.id != wid_id]}})
    wid = getattr(c.rt, "widgets", None)
    await c.send("widgets", items=wid.items() if wid is not None else [])


@handles("mochi_level_get")
async def mochi_level_get(c, m: dict) -> None:
    await c.send("mochi_level", **notchplus.mochi_level(c.rt))
