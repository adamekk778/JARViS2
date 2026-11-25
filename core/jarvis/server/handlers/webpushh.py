"""3.18 iPhone: Web Push for the JARVIS web app on the iPhone's home screen (subscribe, test)."""
from __future__ import annotations

from . import handles


@handles("webpush_key")
async def webpush_key(c, m: dict) -> None:
    from ... import webpush

    await c.send("webpush", key=webpush.public_key(), count=len(webpush.subscriptions(c.rt)))


@handles("webpush_subscribe")
async def webpush_subscribe(c, m: dict) -> None:
    from ... import webpush

    raw = m.get("subscription")
    sub: dict = raw if isinstance(raw, dict) else {}
    ok = webpush.subscribe(c.rt, sub, str(m.get("label") or "iPhone"))
    await c.send("webpush", ok=ok, count=len(webpush.subscriptions(c.rt)),
                 error="" if ok else "Tohle předplatné neznám (jen Apple, Google, Mozilla a Microsoft push).")


@handles("webpush_test", slow=True)
async def webpush_test(c, m: dict) -> None:
    from ... import webpush

    n = await webpush.send(c.rt, "JARVIS", "Upozornění na tomhle zařízení fungují.")
    await c.send("webpush", tested=n, count=len(webpush.subscriptions(c.rt)))
