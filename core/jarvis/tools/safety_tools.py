"""3.14 Ochrana a nouze: the emergency protocol, the security briefing, kids mode, the house cameras."""
from __future__ import annotations

from typing import Annotated

from .base import ToolResult, tool


@tool("emergency_help", "Nouzový protokol: „JARVIS, pomoc“, „je mi zle“, „upadl jsem“. Zeptá se, jestli jsi v pořádku; když do "
      "30 s neodpovíš, napíše tvým nouzovým kontaktům s polohou. Na 112 volá jen po tvém potvrzení.", category="bezpečnost")
async def emergency_help(ctx, reason: Annotated[str, "co se stalo (vlastními slovy)"] = "požádal jsi o pomoc") -> ToolResult:
    from .. import safety

    r = await safety.emergency(ctx).start(reason)
    return ToolResult(True, r["message"] + " Řekni „jsem v pořádku“ a zruším to.")


@tool("emergency_ok", "Zruší běžící nouzový protokol – „jsem v pořádku“, „to byl omyl“.", category="bezpečnost")
async def emergency_ok(ctx) -> ToolResult:
    from .. import safety

    running = safety.emergency(ctx).cancel()
    return ToolResult(True, "Dobře, ruším." if running else "Žádný nouzový protokol neběží.")


@tool("security_briefing", "Bezpečnostní přehled: neznámá zařízení v síti, neúspěšná přihlášení do Windows, úniky e-mailů "
      "(Have I Been Pwned s tvým klíčem). Sám ho pošle každou neděli večer.", category="bezpečnost")
async def security_briefing(ctx) -> ToolResult:
    from .. import safety

    b = await safety.briefing(ctx)
    if b["items"]:
        return ToolResult(True, "Pozor: " + "; ".join(b["items"]) + ".", data=b)
    return ToolResult(True, "Všechno v pořádku: " + (", ".join(b["ok"]) or "nic podezřelého") + ".", data=b)


@tool("kids_mode", "Dětský režim: u PC je dítě – laskavá řeč, nic nevhodného, žádné nákupy, mazání, instalace, zámky ani alarm. "
      "Zapnout jde komukoli, vypnout jen v nastavení nebo hlasem majitele.", category="bezpečnost",
      danger_if=lambda a: not a.get("on", True))
async def kids_mode(ctx, on: bool = True) -> ToolResult:
    if not on:
        vid = getattr(ctx, "voiceid", None)
        if vid is not None and not vid.owner_ok():
            return ToolResult(False, "Dětský režim vypne jen majitel (jeho hlasem nebo v nastavení).")
    ctx.update_config({"privacy": {"kids_mode": bool(on)}})
    return ToolResult(True, "Dětský režim je zapnutý." if on else "Dětský režim je vypnutý.")


@tool("cameras_status", "Kamery domu: jestli JARVIS hlídá kamery (Frigate) a zvonek, a co hlásil naposledy.", category="bezpečnost")
async def cameras_status(ctx) -> ToolResult:
    h = ctx.cfg.home
    parts = []
    parts.append(f"Frigate: {h.frigate_url}" if h.frigate_url else "Frigate není nastavený")
    parts.append(f"zvonek: {h.doorbell_entity}" if h.doorbell_entity else "zvonek není nastavený")
    if h.camera_zones:
        parts.append("přes den hlídám zóny " + ", ".join(h.camera_zones))
    return ToolResult(True, "; ".join(parts) + ".", data={"frigate": bool(h.frigate_url), "doorbell": bool(h.doorbell_entity)})
