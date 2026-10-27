"""Wave 33 – the notch knows what you are doing: quick actions for the app in front (OMEGA 089), suggestions that fit
the moment (094), small pinned to-dos with an optional time (093) and workspaces one click away (091).

Actions are plain data for the UI: either a sentence JARVIS gets as if you typed it ("text") or one of the notch's
allowed quick actions ("quick" + "args"). Nothing here runs anything by itself."""
from __future__ import annotations

import datetime as dt
import os
import re
import time
from typing import Any

SCHEMA = ("CREATE TABLE IF NOT EXISTS pins (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, due REAL, "
          "done INTEGER DEFAULT 0, created REAL, reminded INTEGER DEFAULT 0)")
MAX_PINS = 30


def A(label: str, icon: str, text: str = "", quick: str = "", **args: Any) -> dict:
    a = {"label": label, "icon": icon}
    if quick:
        a.update(quick=quick, args=args)
    else:
        a["text"] = text
    return a


# exe (lower case, without .exe) → kind
KINDS = {
    "browser": {"chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "arc"},
    "writer": {"winword", "notepad", "notepad++", "wordpad", "soffice", "swriter", "obsidian", "notion", "onenote"},
    "sheet": {"excel", "scalc"},
    "slides": {"powerpnt", "simpress"},
    "code": {"code", "devenv", "pycharm64", "idea64", "rider64", "webstorm64", "sublime_text", "cursor", "windowsterminal",
             "powershell", "cmd", "wt"},
    "files": {"explorer", "totalcmd64", "totalcmd"},
    "mail": {"outlook", "thunderbird", "olk", "hxoutlook"},
    "media": {"spotify", "vlc", "wmplayer", "music.ui", "foobar2000", "aimp", "itunes"},
    "call": {"teams", "ms-teams", "zoom", "discord", "slack", "skype", "webex"},
    "image": {"photoshop", "gimp-2.10", "gimp", "paint.net", "mspaint", "photos", "figma", "krita", "affinity photo 2"},
    "pdf": {"acrord32", "acrobat", "sumatrapdf", "foxitpdfreader"},
}

ACTIONS = {
    "browser": [A("Shrnout stránku", "article", "Podívej se na obrazovku a shrň mi stránku, kterou mám otevřenou."),
                A("Přeložit stránku", "translate", "Podívej se na obrazovku a přelož mi hlavní text stránky do češtiny."),
                A("Je to důvěryhodné?", "shield-check", "Podívej se na obrazovku: je tahle stránka důvěryhodná? Upozorni na podvodné znaky.")],
    "writer": [A("Opravit označené", "text-aa", "Oprav pravopis a stylistiku textu, který mám ve schránce, a vrať opravenou verzi."),
               A("Shrnout dokument", "list-bullets", "Podívej se na obrazovku a shrň mi dokument, na kterém pracuji."),
               A("Přečíst nahlas", "speaker-high", "Přečti mi nahlas text, který mám ve schránce.")],
    "sheet": [A("Vysvětlit vzorec", "function", "Podívej se na obrazovku a vysvětli mi vzorec v označené buňce."),
              A("Shrnout tabulku", "table", "Podívej se na obrazovku a shrň mi, co je v tabulce zajímavého."),
              A("Navrhnout graf", "chart-bar", "Podívej se na obrazovku a navrhni, jaký graf by se k těm datům hodil.")],
    "slides": [A("Zkontrolovat snímek", "presentation-chart", "Podívej se na obrazovku a poraď, jak snímek zpřehlednit."),
               A("Poznámky řečníka", "note", "Podívej se na obrazovku a napiš mi krátké poznámky řečníka k tomuhle snímku.")],
    "code": [A("Vysvětlit chybu", "bug", "Podívej se na obrazovku a vysvětli mi chybu, kterou vidím, a jak ji opravit."),
             A("Co dělá tenhle kód", "code", "Vysvětli mi kód, který mám ve schránce."),
             A("Napsat test", "test-tube", "Napiš test ke kódu, který mám ve schránce.")],
    "files": [A("Nedávné soubory", "clock-counter-clockwise", "Ukaž mi soubory, se kterými jsem dnes pracoval."),
              A("Najít duplicity", "copy", "Najdi duplicitní soubory ve složce Stažené soubory."),
              A("Roztřídit Stažené", "folders", "Roztřiď složku Stažené soubory podle typu.")],
    "mail": [A("Shrnout nepřečtené", "envelope-open", "Shrň mi nepřečtené e-maily."),
             A("Navrhnout odpověď", "pencil-simple-line", "Podívej se na obrazovku a navrhni odpověď na otevřený e-mail. Nic neodesílej.")],
    "media": [A("Play / pauza", "play-pause", quick="media_control", action="play_pause"),
              A("Další", "skip-forward", quick="media_control", action="next"),
              A("Co to hraje?", "music-notes", "Co teď hraje?")],
    "call": [A("Zapisovat poznámky", "record", "Začni zapisovat poznámky z hovoru."),
             A("Ztlumit zvuk PC", "speaker-slash", quick="volume", action="mute")],
    "image": [A("Popsat obrázek", "image", "Podívej se na obrazovku a popiš obrázek, na kterém pracuji."),
              A("Barvy a kontrast", "palette", "Podívej se na obrazovku a zhodnoť barvy a kontrast návrhu.")],
    "pdf": [A("Shrnout PDF", "file-pdf", "Podívej se na obrazovku a shrň mi otevřený dokument."),
            A("Vysvětlit odstavec", "chat-text", "Vysvětli mi jednoduše text, který mám ve schránce.")],
    "any": [A("Co je na obrazovce?", "monitor", "Podívej se na obrazovku a řekni mi, co vidíš."),
            A("Screenshot", "camera", "Udělej screenshot")],
}


def _exe(info: dict) -> str:
    exe = (info.get("exe") or info.get("path") or info.get("app") or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return exe.removesuffix(".exe")


def kind_of(info: dict) -> str:
    exe = _exe(info)
    for k, names in KINDS.items():
        if exe in names:
            return k
    app = (info.get("app") or "").lower()
    for k, names in KINDS.items():
        if any(n in app for n in names if len(n) > 3):
            return k
    return "any"


def actions_for(info: dict, custom: list | None = None, limit: int = 4) -> list[dict]:
    """The quick actions for the app in front: your own ones for it first, then the built-in ones."""
    kind = kind_of(info)
    exe, app = _exe(info), (info.get("app") or "").lower()
    out = []
    for c in custom or []:
        c = c if isinstance(c, dict) else c.model_dump()
        target = (c.get("app") or "").lower().removesuffix(".exe").strip()
        if target and (target == exe or target in app) and c.get("text"):
            out.append(A(str(c.get("label") or c["text"])[:40], c.get("icon") or "lightning", str(c["text"])[:500]))
    out += ACTIONS.get(kind, []) if kind != "any" else []
    if len(out) < limit:
        out += ACTIONS["any"]
    return out[:limit]


def app_context(rt, info: dict | None = None) -> dict:
    """The app in front (never JARVIS itself) and its actions. Only the app's name goes out, not the window title."""
    if info is None:
        fg = {}
        try:
            fg = rt.platform.foreground_info() or {}
        except Exception:  # noqa: BLE001
            pass
        last = getattr(getattr(rt, "activity", None), "last_external", None) or {}
        info = fg if fg.get("pid") and fg.get("pid") != os.getpid() else last
    custom = getattr(getattr(rt.cfg, "notch", None), "app_actions", None) or []
    return {"app": info.get("app") or "", "kind": kind_of(info), "actions": actions_for(info, custom)}


# ---------------------------------------------------------------- suggestions for the moment (094)
URL = re.compile(r"^https?://\S+$")


def suggestions(rt, events: list[dict] | None = None, clipboard: str | None = None, now: float | None = None) -> list[dict]:
    """Up to three things that fit right now: a meeting soon, a link or a long text in the clipboard, a pin due today,
    a layout to restore. Built only from what JARVIS already has – nothing is sent anywhere."""
    now = now or time.time()
    out: list[dict] = []
    for e in events or []:
        start = e.get("start") or 0
        if not e.get("all_day") and 0 <= start - now <= 20 * 60:
            mins = max(1, round((start - now) / 60))
            out.append(A(f"Za {mins} min: {str(e.get('title', 'schůzka'))[:28]}", "calendar-check",
                         f"Připrav mě na schůzku „{str(e.get('title', ''))[:120]}“: co o ní vím, s kým je a co si připravit."))
            break
    clip = (clipboard or "").strip()
    if clip and len(clip) < 20000:
        from .powers import looks_secret

        if not looks_secret(clip):
            if URL.match(clip):
                out.append(A("Shrnout odkaz ze schránky", "link", "Shrň mi stránku z odkazu, který mám ve schránce."))
            elif len(clip) > 400:
                out.append(A("Shrnout text ze schránky", "clipboard-text", "Shrň stručně text, který mám ve schránce."))
    today_end = dt.datetime.combine(dt.date.fromtimestamp(now), dt.time(23, 59, 59)).timestamp()
    due = [p for p in list_pins(rt) if not p["done"] and p["due"] and p["due"] <= today_end]
    if due:
        p = min(due, key=lambda x: x["due"])
        late = p["due"] < now
        out.append({**A(("Po termínu: " if late else "Dnes: ") + p["text"][:34], "push-pin", ""), "pin": p["id"]})
    return out[:3]


# ---------------------------------------------------------------- pinned to-dos (093)
def _db(rt):
    rt.db.exec(SCHEMA)
    return rt.db


def list_pins(rt, include_done: bool = False) -> list[dict]:
    rows = _db(rt).all("SELECT * FROM pins " + ("" if include_done else "WHERE done=0 ") +
                       "ORDER BY done, CASE WHEN due IS NULL THEN 1 ELSE 0 END, due, id")
    return [{**r, "done": bool(r["done"]), "reminded": bool(r["reminded"])} for r in rows]


def parse_due(text: str, now: float | None = None) -> float | None:
    """'v 15:30', 'zítra v 9', 'za 20 minut', 'za 2 hodiny', '15:30' → a time stamp (None = no time)."""
    now_dt = dt.datetime.fromtimestamp(now or time.time())
    t = text.lower()
    m = re.search(r"za\s+(\d+)\s*(min|minut|minuty|minutu|h|hod|hodin|hodiny|hodinu)\b", t)
    if m:
        n = int(m.group(1))
        return (now_dt + (dt.timedelta(hours=n) if m.group(2).startswith("h") else dt.timedelta(minutes=n))).timestamp()
    day = now_dt.date() + dt.timedelta(days=2 if ("pozítří" in t or "pozitri" in t) else 1 if ("zítra" in t or "zitra" in t) else 0)
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", t) or re.search(r"\bve?\s+(\d{1,2})\s*(?:h|hod|hodin)?\b(?![.:\d])", t)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2)) if m.lastindex and m.lastindex >= 2 else 0
        if hh < 24 and mm < 60:
            when = dt.datetime.combine(day, dt.time(hh, mm))
            if when < now_dt and day == now_dt.date():
                when += dt.timedelta(days=1)
            return when.timestamp()
    if day != now_dt.date():
        return dt.datetime.combine(day, dt.time(9, 0)).timestamp()
    return None


TIME_WORDS = re.compile(r"\s*(?:\bza\s+\d+\s*(?:min|minut|minuty|minutu|h|hod|hodin|hodiny|hodinu)\b|\b(?:zítra|zitra|pozítří|pozitri|dnes)\b"
                        r"|\b(?:v|ve)\s+\d{1,2}(?:[:.]\d{2})?\s*(?:h|hod|hodin)?\b|\b\d{1,2}:\d{2}\b)", re.I)


def split_due(text: str, now: float | None = None) -> tuple[str, float | None]:
    """'zavolat Petrovi zítra v 9' → ('zavolat Petrovi', <zítra 9:00>); text without a time stays as it is."""
    due = parse_due(text, now)
    if due is None:
        return text, None
    rest = " ".join(TIME_WORDS.sub(" ", text).split()).strip(" ,.-–")
    return (rest or text), due


def add_pin(rt, text: str, due: float | None = None) -> dict:
    text = " ".join(str(text).split())[:200]
    if not text:
        raise ValueError("Napiš, co mám připnout.")
    if len(list_pins(rt)) >= MAX_PINS:
        raise ValueError(f"Připnutých je už {MAX_PINS}. Nejdřív nějaké odškrtni.")
    cur = _db(rt).exec("INSERT INTO pins (text, due, created) VALUES (?,?,?)", (text, due, time.time()))
    return next(p for p in list_pins(rt, True) if p["id"] == cur.lastrowid)


def find_pin(rt, ref: str | int) -> dict | None:
    pins = list_pins(rt)
    if isinstance(ref, int) or str(ref).isdigit():      # "the 2nd one" = the position you see, not the inner id
        n = int(ref)
        return pins[n - 1] if 0 < n <= len(pins) else None
    from .comms import fold

    q = fold(str(ref))
    return next((p for p in pins if q in fold(p["text"])), None)


def set_done(rt, pid: int, done: bool = True) -> bool:
    return _db(rt).exec("UPDATE pins SET done=? WHERE id=?", (int(done), pid)).rowcount > 0


def remove_pin(rt, pid: int) -> bool:
    return _db(rt).exec("DELETE FROM pins WHERE id=?", (pid,)).rowcount > 0


def clear_done(rt) -> int:
    return _db(rt).exec("DELETE FROM pins WHERE done=1").rowcount


def due_reminders(rt, now: float | None = None) -> list[dict]:
    """Pins whose time has come: each one is announced once."""
    now = now or time.time()
    due = [p for p in list_pins(rt) if p["due"] and p["due"] <= now and not p["reminded"]]
    for p in due:
        _db(rt).exec("UPDATE pins SET reminded=1 WHERE id=?", (p["id"],))
    return due


def publish_pins(rt) -> None:
    rt.bus.publish("pins", items=list_pins(rt))
