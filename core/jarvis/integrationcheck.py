"""3.18 Samotest integrací (návrh 2): Diagnostika → Kontrola funkcí also tries what 3.15–3.18 added – the 3D printer
(Bambu napřímo too), the finger-gesture model, PPL and DPD parcels, the STEP engine in the HUD and the travel booking
services – and says in plain words what is missing (the printer's IP, the access code, a download…).
Nothing is changed and nothing is booked; a part you do not use is "not set up", not an error.
"""
from __future__ import annotations

import asyncio
from typing import Any


def _r(key: str, name: str, ok: bool | None, detail: str, fix: str = "") -> dict:
    return {"key": key, "name": name, "ok": ok, "detail": detail[:300], "fix": fix[:400]}


async def printer(rt: Any) -> dict:
    from . import printer3d

    name = "3D tiskárna"
    c = rt.cfg.workshop
    if c.printer == "off":
        return _r("printer", name, None, "Není nastavená.", "Nastavení → Integrace → Dílna – 3D tiskárna.")
    if c.printer == "bambu_lan":
        from . import bambu

        why = bambu.problem(rt)
        if why:
            return _r("printer", name, False, f"Bambu napřímo: {why}.", "Nastavení → Integrace → Dílna.")
    try:
        s = await asyncio.wait_for(printer3d.status(rt), 15)
    except Exception as e:  # noqa: BLE001
        s = {"state": "offline", "why": str(e)[:120]}
    if s.get("state") == "offline":
        return _r("printer", name, False, printer3d.say(s, c.printer_name),
                  "Je tiskárna zapnutá a ve stejné síti? U Bambu zapni na tiskárně LAN režim a zkontroluj IP a přístupový kód.")
    return _r("printer", name, True, printer3d.say(s, c.printer_name))


def hands(rt: Any) -> dict:
    from . import handmodel

    name = "Gesta prsty"
    if not getattr(rt.cfg.appearance, "gesture_fingers", False) or not getattr(rt.cfg.appearance, "gestures", False):
        return _r("hands", name, None, "Vypnuto.", "Vzhled → Ovládání gesty a Gesta prsty.")
    if handmodel.ready():
        return _r("hands", name, True, "Model ruky je stažený a ověřený.")
    return _r("hands", name, False, "Model ruky není stažený.", f"Vzhled → Gesta prsty → Stáhnout (asi {handmodel.SIZE_MB} MB).")


def step_engine() -> dict:
    from . import models3d, paths

    name = "STEP v HUD"
    if models3d.freecad():
        return _r("step", name, True, "FreeCAD je nainstalovaný – STEP se převede přesně.")
    wasm = list((paths.web_dist() / "assets").glob("occt-import-js-*.wasm")) if (paths.web_dist() / "assets").exists() else []
    if wasm:
        return _r("step", name, True, "STEP přečte HUD sám (OpenCascade ve WebAssembly).")
    return _r("step", name, False, "Chybí soubor pro čtení STEP.", "Nainstaluj nejnovější JARVIS, nebo FreeCAD (zdarma).")


async def parcels(rt: Any) -> list[dict]:
    from . import connectors
    from . import parcels as pc

    out = []
    if connectors.configured("ppl"):
        from .connectors import ppl

        try:
            await asyncio.wait_for(ppl.token(), 15)
            out.append(_r("ppl", "Zásilky PPL", True, "PPL přijalo přihlášení."))
        except Exception as e:  # noqa: BLE001
            out.append(_r("ppl", "Zásilky PPL", False, str(e)[:200], "Nastavení → Propojení → PPL: zkontroluj Client ID a secret."))
    else:
        out.append(_r("ppl", "Zásilky PPL", None, "Bez přístupu od PPL – jen odkaz na sledování.", "Propojení → PPL (Client ID od PPL)."))
    if any(p["carrier"] == "dpd" for p in pc.listing(rt)):
        try:
            async with rt.http() as c:
                r = await asyncio.wait_for(c.get("https://tracking.dpd.de/rest/plc/cs_CZ/0", timeout=10), 15)
            out.append(_r("dpd", "Zásilky DPD", r.status_code < 500, f"Sledování DPD odpovídá ({r.status_code})."))
        except Exception as e:  # noqa: BLE001
            out.append(_r("dpd", "Zásilky DPD", False, f"Sledování DPD neodpovídá: {str(e)[:120]}", "Internet, nebo firewall."))
    return out


async def travel(rt: Any) -> list[dict]:
    import importlib

    try:
        booking = importlib.import_module("jarvis.booking")
    except Exception:  # noqa: BLE001
        return []
    return list(await booking.selfcheck(rt))


async def run(rt: Any) -> list[dict]:
    res = [await printer(rt), hands(rt), step_engine()]
    res += await parcels(rt)
    try:
        res += await asyncio.wait_for(travel(rt), 30)
    except asyncio.TimeoutError:
        res.append(_r("travel", "Rezervace cest", None, "Kontrola nestihla doběhnout."))
    return res
