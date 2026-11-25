"""3.14 Roboti: the robot vacuum and lawn mower (Home Assistant) and a DJI Tello drone with hard safety limits."""
from __future__ import annotations

from typing import Annotated

from .base import ToolResult, tool


@tool("robots_status", "Stav robotů v domě: robotický vysavač a sekačka (uklízí, v doku, baterie, chyba) přes Home Assistant.",
      category="domácnost", perm="home")
async def robots_status(ctx) -> ToolResult:
    from .. import robots

    try:
        text, data = await robots.status(ctx)
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Home Assistant teď neodpovídá: {e}")
    return ToolResult(True, text, data=data)


@tool("vacuum_control", "Robotický vysavač: uklidit (celý byt nebo místnost – „ukliď kuchyň“), pauza, stop, domů do doku, najít.",
      category="domácnost", perm="home")
async def vacuum_control(ctx, action: Annotated[str, "clean / pause / stop / dock / locate"] = "clean",
                         room: Annotated[str, "místnost (prázdné = celý byt)"] = "") -> ToolResult:
    from .. import robots

    try:
        return ToolResult(True, await robots.vacuum(ctx, (action or "clean").lower(), room.strip()))
    except (LookupError, ValueError) as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Vysavač teď neodpovídá: {e}")


@tool("mower_control", "Robotická sekačka: sekat, pauza, domů. Spuštění se vždy nejdřív zeptá (na zahradě můžou být děti nebo "
      "zvířata).", category="domácnost", perm="home", danger_if=lambda a: str(a.get("action", "start")).lower() == "start")
async def mower_control(ctx, action: Annotated[str, "start / pause / dock"] = "start") -> ToolResult:
    from .. import robots

    try:
        return ToolResult(True, await robots.mower(ctx, (action or "start").lower()))
    except (LookupError, ValueError) as e:
        return ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001
        return ToolResult(False, f"Sekačka teď neodpovídá: {e}")


DRONE_ACTIONS = ("status", "takeoff", "land", "up", "down", "left", "right", "forward", "back", "turn", "tour", "photo", "emergency")


@tool("drone", "Dron DJI Tello (PC připojené k jeho Wi-Fi): stav baterie, vzlétnout, přistát, pohyb nahoru/dolů/doleva/doprava/"
      "dopředu/dozadu (cm), otočit (°), obletět místnost (čtverec), fotka, nouzové vypnutí motorů. Limity: jen v interiéru, max "
      "1,5 m výška, max 1 m na pohyb, max 2 minuty letu, vzlet jen nad 25 % baterie; vzlet a nouzové vypnutí se vždy ptají.",
      category="hardware", perm="network", danger_if=lambda a: str(a.get("action", "")).lower() in ("takeoff", "tour", "emergency"))
async def drone(ctx, action: Annotated[str, "status / takeoff / land / up / down / left / right / forward / back / turn / tour / photo / emergency"],
                value: Annotated[float, "centimetry pro pohyb, stupně pro otočení (kladné doprava), strana čtverce pro tour"] = 0) -> ToolResult:
    from .. import robots

    a = (action or "").strip().lower()
    if a not in DRONE_ACTIONS:
        return ToolResult(False, "Dron umí: stav, vzlétni, přistaň, nahoru/dolů/doleva/doprava/dopředu/dozadu, otoč, obleť, fotka, nouzově vypni.")
    d = robots.drone(ctx)
    try:
        if a == "status":
            bat = await d.connect()
            return ToolResult(True, f"Dron je připojený, baterie {bat} %" + (", letí." if d.flying else ", stojí."), data={"battery": bat})
        if a == "takeoff":
            return ToolResult(True, await d.takeoff())
        if a == "land":
            return ToolResult(True, await d.land())
        if a == "emergency":
            return ToolResult(True, await d.emergency())
        if a == "turn":
            return ToolResult(True, await d.turn(value or 90))
        if a == "tour":
            return ToolResult(True, await d.room_tour(value or 100))
        if a == "photo":
            jpg = await d.photo()
            att = await ctx.store.save("dron.jpg", jpg, "image/jpeg", conv_id=ctx.memory.current_conversation) \
                if getattr(ctx, "store", None) else None
            return ToolResult(True, "Fotka z dronu.", attachments=[att.id] if att else [])
        return ToolResult(True, await d.move(a, value or 50))
    except robots.DroneError as e:
        return ToolResult(False, f"Dron: {e}.")
    except OSError as e:
        return ToolResult(False, f"Dron není dostupný ({e}) – připoj PC k Wi-Fi dronu (TELLO-…).")
