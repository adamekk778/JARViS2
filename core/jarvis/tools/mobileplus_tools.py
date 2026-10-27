"""Wave 34 by voice: the phone and other devices – clean text for sharing, command QR codes, a photo from the phone
(always asked on the phone first) and a temporary guest pairing for music and volume."""
from __future__ import annotations

import secrets
from typing import Annotated

from .base import ToolResult, tool


@tool("clean_for_sharing", "Připraví text k poslání jinam: z odkazů odstraní sledovací parametry (utm, fbclid…) a zamaskuje hesla, "
      "klíče a tokeny.", category="telefon")
async def clean_for_sharing(ctx, text: Annotated[str, "text nebo odkaz"]) -> ToolResult:
    from ..mobileplus import clean_text

    r = clean_text(text)
    notes = []
    if r["removed"]:
        notes.append("odstraněno sledování: " + ", ".join(r["removed"]))
    if r["masked"]:
        notes.append("zamaskována citlivá data")
    return ToolResult(True, r["text"] + (f"\n({'; '.join(notes)})" if notes else "\n(Nebylo co čistit.)"), data=r)


@tool("command_qr", "Vytvoří QR kód s příkazem pro JARVISe (např. na dveře: „Spusť protokol Dobrou noc“). Telefon po naskenování "
      "příkaz ukáže a spustí až po potvrzení.", category="telefon")
async def command_qr(ctx, text: Annotated[str, "co má JARVIS udělat"], name: Annotated[str, "název souboru"] = "") -> ToolResult:
    from ..mobileplus import command_qr as make

    try:
        path = make(text, name)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"QR kód pro „{text.strip()}“ je připravený k vytištění ({path.name}). Naskenuj ho aplikací JARVIS.",
                      data={"path": str(path)}, attachments=[str(path)])


@tool("ask_phone_photo", "Požádá telefon o fotku (např. „vyfoť mi štítek na routeru“). Telefon žádost ukáže a fotí jen ten, "
      "kdo ji potvrdí – kamera se nikdy nezapne sama.", category="telefon")
async def ask_phone_photo(ctx, reason: Annotated[str, "k čemu fotka je"]) -> ToolResult:
    if not any(c.get("client") == "mobile" for c in getattr(ctx, "clients", {}).values()):
        return ToolResult(False, "Telefon teď není připojený – otevři na něm aplikaci JARVIS.")
    rid = secrets.token_hex(4)
    ctx.bus.publish("phone_photo_request", id=rid, reason=reason.strip()[:160], target="mobile")
    return ToolResult(True, "Na telefonu se ukázala žádost o fotku. Až ji vyfotíš, objeví se v polici notche.", data={"id": rid})


def _guest_details(args: dict) -> list[str]:
    return [f"Host: {args.get('name') or 'Host'}", f"Platnost: {args.get('hours') or 3} h",
            "Smí jen: hudba (přehrát, další, YouTube) a hlasitost. Nevidí chat, soubory ani nastavení."]


@tool("guest_access", "Dočasně pustí cizí telefon k ovládání hudby a hlasitosti na PC (třeba na párty). Vytvoří QR kód, "
      "který po zadané době sám přestane platit.", category="telefon", perm="network", danger=True, details=_guest_details)
async def guest_access(ctx, name: Annotated[str, "kdo to je"] = "Host", hours: Annotated[float, "na kolik hodin (max 72)"] = 3) -> ToolResult:
    import qrcode

    from .. import mobileplus, paths
    from ..server.pairing import pairing_info

    g = mobileplus.add_guest(ctx, name, hours)
    info = pairing_info(g["token"], ctx.cfg.phone.port)
    path = paths.sub("qr") / f"host-{g['id']}.png"
    qrcode.make(info["url"], box_size=10, border=3).save(path)
    left = round((g["expires"] - __import__("time").time()) / 3600, 1)
    return ToolResult(True, f"{g['name']} může {left:g} h ovládat hudbu a hlasitost. Ať naskenuje QR kód (aplikace JARVIS nebo fotoaparát). "
                            "Přístup zrušíš na PC v Nastavení → Telefon.", data={"id": g["id"]}, attachments=[str(path)])
