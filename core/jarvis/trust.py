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
             "webhooks", "workflow_import", "delete_file", "claude_code", "email_delete", "roblox_publish",
             "travel_book", "booking_cancel"}
FREE_AREAS = {"apps", "input", "screen", "files_read", "files_write", "system", "home"}
CAREFUL_AREAS = {"files_write", "system"}           # these ask again once untrusted text (mail, web) was read
RULE = ("PLNÁ DŮVĚRA: uživatel ti dovolil dělat na tomhle PC všechno bez ptaní. Co řekne, to rovnou udělej – nevysvětluj, "
        "neptej se „opravdu?“, nenabízej alternativy, nediskutuj. Aplikace otevírej a zavírej, programy po startu vypínej "
        "(startup_apps / startup_app_set), nastavení měň. Hru, kterou uživatel právě hraje, nikdy sám nezavírej – jen když ji "
        "výslovně jmenuje. Když něco nejde, řekni jednou větou proč.")


def on(rt: Any) -> bool:
    return bool(getattr(getattr(getattr(rt, "cfg", None), "tools", None), "full_trust", False))


def skip_confirm(rt: Any, spec: Any, untrusted_seen: bool = False, args: dict | None = None) -> bool:
    """True = this dangerous step runs without asking, because you gave JARVIS full trust."""
    if not on(rt) or spec is None:
        return False
    if spec.name == "browser_click":               # 3.18 paying, buying, booking: always your confirmation
        from .tools.browser import money_click

        if args is None or money_click(args):
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


# ------------------------------------------------------------------------------------------ 3.18 money only on your own word
MONEY_TOOLS = {"travel_book", "booking_cancel"}
MONEY_WORDS = (r"(rezerv|zarezerv|\bberu\b|\bbereme\b|vezmu|vezmeme|zaplat|\bplat|objednej|\bkup|zrus|storn|"
               r"\bbook|reserve|\bpay\b|cancel)")


def money_blocked(name: str, untrusted_seen: bool, words: str = "") -> str:
    """Foreign text (an e-mail, a page) is in this task: booking, paying or cancelling only when YOUR words ask for it
    – otherwise not even a question (a planted "book this now" never reaches the payment)."""
    import re

    if name not in MONEY_TOOLS or not untrusted_seen or re.search(MONEY_WORDS, _fold(words)):
        return ""
    return ("Rezervovat, platit nebo rušit budu jen na tvůj vlastní pokyn – tohle navrhl cizí text (e-mail, stránka). "
            "NEPROVEDENO. Když to chceš, řekni to sám.")


# ------------------------------------------------------------------------------------------ 3.18 a link that carries data out
URL_KEYS = ("url", "link", "href", "address", "uri", "page")
_SECRETISH = (
    (r"[\w.+-]+@[\w-]+\.[\w.-]+", "e-mail"),
    (r"(?:\+?\d[\s-]?){9,}", "telefon nebo číslo"),
    (r"[A-Za-z0-9_\-]{28,}", "klíč nebo token"),
)


def link_leak(args: dict, words: str = "") -> str:
    """Foreign text is in the task: '' when the link in these arguments is harmless, else why it could carry your data
    away (an address you did not name that sends a long query, an e-mail, a number or a key to its server)."""
    import re
    from urllib.parse import unquote, urlsplit

    for k in URL_KEYS:
        v = (args or {}).get(k)
        if not isinstance(v, str) or "://" not in v and not v.startswith("www."):
            continue
        u = urlsplit(v if "://" in v else "https://" + v)
        host = (u.hostname or "").lower()
        if not host:
            continue
        mine = _fold(words)
        base = ".".join(host.split(".")[-2:])
        if base and base in mine:
            continue                                   # you named the site yourself
        carried = unquote(u.query + " " + u.fragment + " " + "/".join(u.path.split("/")[2:]))
        for rx, what in _SECRETISH:
            if re.search(rx, carried):
                return f"odkaz na {host} by odeslal {what}"
        if len(carried.strip()) > 60:
            return f"odkaz na {host} nese dlouhá data"
    return ""


# ------------------------------------------------------------------------------------------ 3.18 what foreign text tried
FOREIGN_SQL = """CREATE TABLE IF NOT EXISTS foreign_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, source TEXT, tool TEXT,
                 what TEXT, why TEXT, approved INTEGER)"""


def log_foreign(rt: Any, source: str, tool: str, what: str, why: str, approved: bool) -> None:
    """Every step foreign text led to that needed your answer – Bezpečí a soukromí shows them (the last 200)."""
    import time

    try:
        rt.db.exec(FOREIGN_SQL)
        rt.db.exec("INSERT INTO foreign_log (ts, source, tool, what, why, approved) VALUES (?,?,?,?,?,?)",
                   (time.time(), source[:60], tool[:60], what[:200], why[:200], int(bool(approved))))
        rt.db.exec("DELETE FROM foreign_log WHERE id NOT IN (SELECT id FROM foreign_log ORDER BY id DESC LIMIT 200)")
    except Exception:  # noqa: BLE001
        pass


def foreign_list(rt: Any, limit: int = 50) -> list[dict]:
    rt.db.exec(FOREIGN_SQL)
    return [dict(r) for r in rt.db.all("SELECT * FROM foreign_log ORDER BY id DESC LIMIT ?", (limit,))]
