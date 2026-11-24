"""3.14 Telefon+ (návrhy 9, 93, 94, 97, 99).

- the home-screen widget is kept fresh by the phone's background connection (the app may be closed): a mission
  starting or finishing sends its line at once, at most every 20 s
- every notice on the phone has "Odpovědět" – typed (or dictated on a watch / in Android Auto) right in the
  notification; the answer comes back to the phone
- Dynamický zámek: Windows locks the PC when the paired phone walks away (Bluetooth) – JARVIS switches it on and
  opens the pairing page; Windows does the measuring
"""
from __future__ import annotations

import sys
import time
from typing import Any

WIDGET_EVERY_S = 20.0


def widget_line(rt: Any) -> dict:
    cur = getattr(rt.tasks, "current", None)
    goal = (cur.get("goal") if isinstance(cur, dict) else "") or ""
    busy = bool(getattr(rt.agent, "busy", False))
    status = f"Pracuju: {goal[:60]}" if goal else ("Přemýšlím…" if busy else "Připraven")
    ms = getattr(rt, "media_state", {}) or {}
    song = f"{ms.get('artist', '')} – {ms.get('title', '')}".strip(" –") if ms.get("playing") else ""
    return {"status": status, "task": goal[:80], "song": song[:60]}


def push_widget(rt: Any, force: bool = False) -> bool:
    now = time.monotonic()
    if not force and now - getattr(rt, "_widget_pushed", 0.0) < WIDGET_EVERY_S:
        return False
    line = widget_line(rt)
    if line == getattr(rt, "_widget_last", None) and not force:
        return False
    rt._widget_pushed, rt._widget_last = now, line
    try:
        return bool(rt.phone_push("widget", **line))
    except Exception:  # noqa: BLE001 – no phone: nothing to refresh
        return False


DYNAMIC_LOCK_KEY = r"HKCU\Software\Microsoft\Windows NT\CurrentVersion\Winlogon"


def dynamic_lock(on: bool, runner=None) -> dict:
    """Windows' own Dynamic Lock (EnableGoodbye); the phone must be paired over Bluetooth in Windows settings."""
    if sys.platform != "win32" and runner is None:
        return {"ok": False, "message": "Dynamický zámek je funkce Windows."}
    import subprocess

    run = runner or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=20,
                                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
    r = run(["reg", "add", DYNAMIC_LOCK_KEY, "/v", "EnableGoodbye", "/t", "REG_DWORD", "/d", "1" if on else "0", "/f"])
    ok = getattr(r, "returncode", 1) == 0
    if ok and on:
        try:
            run(["cmd", "/c", "start", "", "ms-settings:bluetooth"])
        except Exception:  # noqa: BLE001
            pass
    return {"ok": ok, "message": ("Dynamický zámek je zapnutý: když od PC odejdeš s telefonem (Bluetooth), Windows ho asi do minuty "
                                  "zamkne. Telefon musí být spárovaný v nastavení Bluetooth – otevřel jsem ho.") if ok and on else
            "Dynamický zámek je vypnutý." if ok else "Nastavení se nepovedlo změnit."}
