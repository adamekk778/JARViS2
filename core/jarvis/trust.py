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

3.17 (návrh 15) Cizí text v úkolu – an e-mail, a web page, a file, a message, a picture or the clipboard – and the AI
may then do without asking only what reads. It asks first (with or without full trust) before a step that changes
something and that it reached on its own (use_tool, or a tool that was not sent with your words), and before the
steps planted text could misuse: keys and typing (Win+R + typing runs anything), opening a link (data in the address),
writing to memory, the clipboard, sending to the phone.
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


# ------------------------------------------------------------------------------------------ 3.17 foreign text in the task
STEERABLE = {"open_url", "browser_open", "browser_type", "remember", "clipboard_set", "send_to_phone"}
INTERNAL = {"find_tools", "update_plan"}
_TYPE = r"napis|vepis|zadej|vypln|nadiktuj|\btype\b|\bwrite\b"
_OPEN = r"otevr|jdi na|prejdi|\bopen\b"
# the words of YOUR message that ask for one of these steps (without accents); a planted "napiš…" in an e-mail does not count
NAMED_BY = {
    "type_text": _TYPE, "ui_type": _TYPE, "browser_type": _TYPE,
    "press_keys": r"zmack|zmacn|stiskn|stisk|klaves|enter|zkratk|\bpress\b",
    "replace_selected_text": r"nahrad|prepis|oprav|\breplace\b",
    "open_url": _OPEN, "browser_open": _OPEN,
    "remember": r"zapamatuj|pamatuj|uloz si|nezapomen|\bremember\b",
    "clipboard_set": r"zkopiruj|do schranky|\bcopy\b",
    "send_to_phone": r"posli|na telefon|na mobil|\bsend\b",
}
_INPUT_VERBS = r"klikn|klepn|napis|zmack|stiskn|prepn|ovladej|hraj|tlumoc|pohni|mys"


def _fold(text: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))


def foreign_needs_ask(spec: Any, offered: bool, words: str = "") -> bool:
    """Foreign text is in this task: True = ask before this step. offered = sent with your message (not reached by the
    AI later on); words = what YOU wrote or said ("" when the message itself is pasted text)."""
    if spec is None or spec.name in INTERNAL:
        return False
    from .permissions import is_reading, perm_of

    if is_reading(spec):
        return False
    if not offered:
        return True
    if spec.name in STEERABLE or perm_of(spec) == "input":
        import re

        return not re.search(NAMED_BY.get(spec.name, _INPUT_VERBS), _fold(words))
    return False
