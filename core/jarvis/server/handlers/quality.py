"""Zdraví JARVISe (návrhy 12, 13, 16, 17, 20): health panel, one-click bug report, back to the previous version."""
from __future__ import annotations

import asyncio

from ... import quality
from . import handles


@handles("quality_get", slow=True)
async def quality_get(c, m: dict) -> None:
    rt = c.rt
    data = await asyncio.to_thread(quality.health, rt, int(m.get("days", 7) or 7))
    up = getattr(rt, "updater", None)
    prev = ""
    try:
        row = rt.db.one("SELECT v FROM kv WHERE k='updated_from'")
        prev = str(row["v"]) if row else ""
    except Exception:  # noqa: BLE001
        pass
    await c.send("quality", **data, channel=getattr(rt.cfg.general, "update_channel", "stable"),
                 auto_rollback=getattr(rt.cfg.general, "auto_rollback", True), previous=prev,
                 current=(up.status.get("current") if up else ""))


@handles("bug_report", local_only=True, slow=True)
async def bug_report(c, m: dict) -> None:
    url = await asyncio.to_thread(quality.issue_url, c.rt, str(m.get("title", "")), str(m.get("text", "")))
    await c.send("bug_report_url", url=url)


@handles("rollback_now", local_only=True, slow=True)
async def rollback_now(c, m: dict) -> None:
    rt = c.rt
    up = getattr(rt, "updater", None)
    to = str(m.get("to", "")).strip()
    if up is None or not to:
        await c.send("error", message="Předchozí verzi neznám – nainstaluj ji ze stránky Releases.")
        return
    ok = await up.rollback(to, bad=str(up.status.get("current", "")))
    if not ok:
        await c.send("error", message=f"Instalátor verze {to} se nepodařilo najít ani stáhnout.")


@handles("update_channel_set", local_only=True)
async def update_channel_set(c, m: dict) -> None:
    ch = "beta" if m.get("channel") == "beta" else "stable"
    c.rt.update_config({"general": {"update_channel": ch}})
    up = getattr(c.rt, "updater", None)
    if up is not None:
        c.spawn(up.check(force=True))
    await quality_get(c, {})
