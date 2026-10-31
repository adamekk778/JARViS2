"""Devices by voice: paired phones (184 / 185 / 402 / 403) and the emergency lockdown (405)."""
from __future__ import annotations

from typing import Annotated

from .base import ToolResult, tool


@tool("paired_devices", "Spárované telefony: seznam (kdy spárováno, naposledy viděn, je teď online) a odpojení jednoho "
      "(remove = název nebo id), např. ztraceného. Ostatní zůstanou spárované.", category="bezpečnost", perm="system",
      danger_if=lambda a, ctx=None: bool(a.get("remove")),
      details=lambda a, ctx=None: [f"Odpojí zařízení „{a.get('remove')}“ – bude se muset spárovat znovu."])
async def paired_devices(ctx, remove: Annotated[str, "název nebo id zařízení k odpojení (prázdné = jen seznam)"] = "") -> ToolResult:
    from .. import mobileplus
    from ..server.ws import close_devices

    devs = mobileplus.device_list(ctx)
    if remove:
        want = remove.strip().lower()
        hit = next((d for d in devs if d["id"] == want or want in d["name"].lower()), None)
        if not hit:
            return ToolResult(False, f"Zařízení „{remove}“ mezi spárovanými není.")
        mobileplus.revoke_device(ctx, hit["id"])
        await close_devices(lambda c: c.device_id == hit["id"])
        return ToolResult(True, f"{hit['name']} je odpojený – jeho klíč už neplatí.", data=hit)
    if not devs:
        return ToolResult(True, "Žádný telefon s vlastním klíčem zatím spárovaný není.", data=[])
    return ToolResult(True, "; ".join(f"{d['name']}" + (" (online)" if d["online"] else "") for d in devs) + ".", data=devs)


@tool("lockdown", "Nouzové uzamčení: odpojí všechny telefony i hosty, vytvoří nový párovací kód, zapne režim jen pro čtení a "
      "zastaví běžící úkol. Na „zamkni všechno“, „ztratil jsem telefon“, „někdo mi leze do PC“.", category="bezpečnost")
async def lockdown(ctx) -> ToolResult:
    from .. import mobileplus
    from ..server.ws import close_devices

    r = mobileplus.lockdown(ctx)
    await close_devices(lambda c: not c.local)
    return ToolResult(True, f"Uzamčeno: odpojeno {r['revoked']} zařízení, nový párovací kód, režim jen pro čtení. "
                            "Až bude bezpečno, vypni režim jen pro čtení v Nastavení a telefon spáruj znovu.", data=r)
