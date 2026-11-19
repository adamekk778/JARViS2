from __future__ import annotations

import asyncio
from typing import Annotated

from .base import ToolResult, tool


@tool("open_app", "Spustí aplikaci na PC podle názvu (Spotify, Discord, Steam, Word, kalkulačka…).", category="aplikace")
async def open_app(ctx, name: Annotated[str, "název aplikace"]) -> ToolResult:
    hit = await asyncio.to_thread(ctx.platform.open_app, name)
    return ToolResult(True, f"Spouštím {hit}")


GAME_HINTS = ("steamapps", "epic games", "riot games", "ubisoft", "ea games", "battle.net", "gog galaxy", "rockstar games",
              "xboxgames", "minecraft", "roblox", "fortnite", "valorant", "leagueoflegends", "cs2", "dota2")


def matching_apps(name: str) -> list[dict]:
    """The running programs close_app would end: [{name, path, count, game}] – shown before anything is closed."""
    try:
        import psutil
    except ImportError:
        return []
    from .platform.windows import ALIASES

    target = ALIASES.get(name.lower(), name).lower().replace(" ", "")
    found: dict[str, dict] = {}
    for p in psutil.process_iter(["name", "exe"]):
        pname = (p.info.get("name") or "").lower().removesuffix(".exe")
        if not pname or pname in ("python", "pythonw", "jarvis") or not (target in pname or (len(pname) >= 4 and pname in target)):
            continue
        exe = (p.info.get("exe") or "").lower()
        it = found.setdefault(pname, {"name": p.info.get("name") or pname, "path": exe, "count": 0, "game": False})
        it["count"] += 1
        it["game"] = it["game"] or any(g in exe or g in pname for g in GAME_HINTS)
    return list(found.values())


def _close_details(a: dict, ctx=None) -> list[str]:
    """What the confirmation shows: which programs end, and a warning for games and unsaved work."""
    apps = matching_apps(str(a.get("name", "")))
    if not apps:
        return [f"„{a.get('name', '')}“ teď neběží – nic se nezavře."]
    out = [f"Zavřu: {x['name']}" + (f" ({x['count']} procesy)" if x["count"] > 1 else "") for x in apps[:6]]
    if any(x["game"] for x in apps):
        out.append("🎮 Je to hra – rozehraná, neuložená hra se ztratí.")
    out.append("Neuložená práce v nich se ztratí.")
    return out


def _plain(text: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(c for c in t if c.isalnum())


def front_is_game(info: dict | None = None, fullscreen: bool | None = None) -> bool:
    """3.13 Herní režim: the program in front is a game – a known game folder/name, or anything over the whole screen
    that is not a browser or a video player (a film in full screen is not a game)."""
    try:
        import sys

        if sys.platform != "win32" and info is None:
            return False
        if info is None:
            from .platform.windows import WindowsPlatform  # noqa: F401 – only on Windows

            import ctypes
            from ctypes import wintypes

            import psutil

            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(ctypes.windll.user32.GetForegroundWindow(), ctypes.byref(pid))
            p = psutil.Process(pid.value)
            info = {"exe": p.name(), "path": p.exe()}
        exe = str(info.get("exe") or "").lower()
        path = str(info.get("path") or "").lower()
        if any(g in path or g.replace(" ", "") in exe for g in GAME_HINTS):
            return True
        if fullscreen is None:
            from ..desktop.winutil import foreground_is_fullscreen

            fullscreen = foreground_is_fullscreen()
        not_games = ("chrome", "msedge", "firefox", "opera", "brave", "vlc", "mpc-hc", "potplayer", "wmplayer", "netflix",
                     "powerpnt", "explorer", "zoom", "teams", "discord", "obs64", "jarvis", "python")
        return bool(fullscreen) and bool(exe) and not any(n in exe for n in not_games)
    except Exception:  # noqa: BLE001 – unknown is not a game
        return False


def playing(apps: list[dict]) -> list[dict]:
    """3.13 The games among these programs – known game folders and names, or the program now in front over the whole
    screen (that is what you are playing)."""
    out = [a for a in apps if a.get("game")]
    try:
        import sys

        if sys.platform == "win32" and not out:
            from ..desktop.winutil import foreground_is_fullscreen

            if foreground_is_fullscreen():
                import ctypes
                from ctypes import wintypes

                import psutil

                pid = wintypes.DWORD()
                ctypes.windll.user32.GetWindowThreadProcessId(ctypes.windll.user32.GetForegroundWindow(), ctypes.byref(pid))
                front = (psutil.Process(pid.value).name() or "").lower()
                out = [a for a in apps if a["name"].lower() == front]
    except Exception:  # noqa: BLE001 – unknown is not a game
        pass
    return out


def named(request: str, games: list[dict], name: str) -> bool:
    """Did you yourself name this game in what you asked ("zavři Roblox")? "Vypni zbytečné aplikace" does not."""
    req = _plain(request)
    if not req:
        return False
    words = {_plain(name)}
    for g in games:
        stem = _plain(g["name"].lower().removesuffix(".exe"))
        words.add(stem)
        words |= {_plain(h) for h in GAME_HINTS if h in (g.get("path") or "") or h.replace(" ", "") in stem}
    return any(len(w) >= 3 and w in req for w in words)


@tool("close_app", "Zavře (ukončí) aplikaci podle názvu. Hru, kterou uživatel hraje, zavře jen když ji výslovně jmenoval.",
      danger=True, details=_close_details, category="aplikace")
async def close_app(ctx, name: Annotated[str, "název aplikace"]) -> ToolResult:
    games = playing(await asyncio.to_thread(matching_apps, name))
    if games and not named(getattr(ctx, "request_text", "") or "", games, name):
        g = games[0]["name"].removesuffix(".exe").removesuffix(".EXE")
        return ToolResult(False, f"🎮 {g} je hra a běží – uprostřed hry ji nezavřu. Když ji opravdu chceš zavřít, řekni to výslovně "
                                 f"(např. „zavři {g}“).")
    n = await asyncio.to_thread(ctx.platform.close_app, name)
    return ToolResult(n > 0, f"Zavřeno procesů: {n}" if n else f"{name} neběží")


@tool("list_apps", "Vrátí seznam nainstalovaných aplikací (pro nalezení správného názvu).", category="aplikace")
async def list_apps(ctx, filter: Annotated[str, "volitelný filtr"] = "") -> ToolResult:  # noqa: A002
    apps = await asyncio.to_thread(ctx.platform.list_apps)
    if filter:
        apps = [a for a in apps if filter.lower() in a.lower()]
    return ToolResult(True, f"{len(apps)} aplikací", data=apps[:200])
