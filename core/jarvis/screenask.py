"""3.12 Zeptej se na obrazovku (Ctrl+Alt+S): pick a part of the screen with Windows' own snipping (the same as
Win+Shift+S), the notch shows it small with Vysvětli / Přelož / Shrň / Poraď or your own question, and JARVIS answers
about that picture. Nothing is captured until you pick the area yourself; the picture stays on this PC as an
attachment of the chat.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import sys
import time

log = logging.getLogger(__name__)

PICK_TIMEOUT_S = 45
ACTIONS = {
    "explain": ("Vysvětli", "Vysvětli stručně česky, co je na tomto výřezu obrazovky. Je-li to chyba nebo hláška, řekni, "
                            "co znamená, proč nejspíš vznikla a jak ji opravit."),
    "translate": ("Přelož", "Přelož do češtiny všechen text na tomto výřezu obrazovky. Zachovej rozložení (seznamy, "
                            "odstavce); nic nevysvětluj."),
    "summary": ("Shrň", "Shrň česky v pár bodech, co je na tomto výřezu obrazovky podstatné."),
    "advice": ("Poraď", "Podívej se na tento výřez obrazovky a poraď mi česky, co s tím mám udělat – konkrétní kroky."),
}


def _grab_clipboard_png() -> bytes | None:
    """The picture Windows' snipping put into the clipboard (None = no picture there)."""
    try:
        from PIL import Image, ImageGrab
    except ImportError:
        return None
    try:
        im = ImageGrab.grabclipboard()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(im, Image.Image):
        return None
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def thumb(png: bytes, max_w: int = 320) -> str:
    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, max(1, round(im.height * max_w / im.width))))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=78)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


async def start(rt, open_snip=None, grab=None) -> dict:
    """Ctrl+Alt+S: open the snipping, wait until you have picked an area, then offer what to do with it."""
    if sys.platform != "win32" and open_snip is None:
        rt.notify("Zeptej se na obrazovku", "Funguje na Windows.", speak=False)
        return {}
    grab = grab or _grab_clipboard_png
    p = rt.platform
    seq0 = p.clipboard_seq()
    if open_snip is None:
        import os

        open_snip = lambda: os.startfile("ms-screenclip:")   # noqa: E731 – Windows' own area picker
    await asyncio.to_thread(open_snip)
    rt.bus.publish("screen_ask", state="picking")
    deadline = time.monotonic() + PICK_TIMEOUT_S
    png = None
    while time.monotonic() < deadline:
        await asyncio.sleep(0.25)
        if p.clipboard_seq() != seq0:
            png = await asyncio.to_thread(grab)
            if png:
                break
            seq0 = p.clipboard_seq()             # text was copied meanwhile: keep waiting for the picture
    if not png:
        rt.bus.publish("screen_ask", state="cancelled")
        return {}
    att = await rt.store.save(f"vyrez-{time.strftime('%H%M%S')}.png", png, "image/png")
    rt.screen_ask = {"att": att.id, "ts": time.time()}
    rt.bus.publish("screen_ask", state="ready", thumb=await asyncio.to_thread(thumb, png),
                   actions=[{"key": k, "label": v[0]} for k, v in ACTIONS.items()])
    return rt.screen_ask


async def act(rt, action: str = "", question: str = "") -> str:
    """One of the buttons, or your own question about the picked area → a normal JARVIS answer (with the picture)."""
    sa = getattr(rt, "screen_ask", None) or {}
    if not sa.get("att") or time.time() - sa.get("ts", 0) > 15 * 60:
        rt.notify("Zeptej se na obrazovku", "Výřez už nemám – vyber ho znovu zkratkou Ctrl+Alt+S.", speak=False)
        return ""
    q = (question or "").strip()
    prompt = (f"{q}\n\n(Otázka se týká přiloženého výřezu obrazovky.)" if q else ACTIONS.get(action, ACTIONS["explain"])[1])
    rt.bus.publish("screen_ask", state="asked")
    return await rt.agent.handle(prompt, [sa["att"]], "notch")
