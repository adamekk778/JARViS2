"""3.13 Plná důvěra: you turned it on in Nastavení → Oprávnění, so JARVIS does what you ask on this PC without asking
first – opens and closes apps, turns off what starts with Windows, tidies files, changes settings, drives the mouse and
keyboard. It still asks for the few things that leave the PC or cannot be taken back, and it never closes a game you
are playing unless you name that game yourself (tools/apps.py).

Still asked, whatever the setting:
- anything that goes to other people: e-mails, SMS, chat messages, calls, screen sharing, webhooks
- money and invoices, publishing (git push, DNS, a game release), databases
- deleting (even to the Recycle Bin), flashing firmware, pairing devices
- running code or PowerShell the AI wrote (your standing rule: never without approval)
- after JARVIS read an e-mail or a web page in this task, changes to files and the system: text from strangers must
  not steer an assistant that does not ask.
"""
from __future__ import annotations

from typing import Any

STILL_ASK = {"send_sms", "record_call", "paired_devices", "screen_share", "guest_access", "pc_link", "firmware_upload", "flash_esp32",
             "webhooks", "workflow_import", "delete_file", "claude_code", "email_delete", "roblox_publish"}
FREE_AREAS = {"apps", "input", "screen", "files_read", "files_write", "system", "home"}
CAREFUL_AREAS = {"files_write", "system"}           # these ask again once untrusted text (mail, web) was read
RULE = ("PLNÁ DŮVĚRA: uživatel ti dovolil dělat na tomhle PC všechno bez ptaní. Co řekne, to rovnou udělej – nevysvětluj, "
        "neptej se „opravdu?“, nenabízej alternativy, nediskutuj. Aplikace otevírej a zavírej, programy po startu vypínej "
        "(startup_apps / startup_app_set), nastavení měň. Hru, kterou uživatel právě hraje, nikdy sám nezavírej – jen když ji "
        "výslovně jmenuje. Když něco nejde, řekni jednou větou proč.")


def on(rt: Any) -> bool:
    return bool(getattr(getattr(getattr(rt, "cfg", None), "tools", None), "full_trust", False))


def skip_confirm(rt: Any, spec: Any, untrusted_seen: bool = False) -> bool:
    """True = this dangerous step runs without asking, because you gave JARVIS full trust."""
    if not on(rt) or spec is None:
        return False
    from .bizagents import AUTO_SAFE
    from .permissions import perm_of
    from .tools.base import NEVER_TRUSTED

    name = spec.name
    if name in STILL_ASK or name in NEVER_TRUSTED:
        return False
    area = perm_of(spec)
    if area in FREE_AREAS:
        return not (untrusted_seen and area in CAREFUL_AREAS)
    return name in AUTO_SAFE or name == "browser_click"          # internet: only your own records (a task, a note) and clicks
