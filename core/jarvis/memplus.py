"""3.14 Paměť+ (návrhy 52, 53, 54, 56, 57).

- facts that are only true for a while ("zítra mám zubaře", "v pátek letím do Londýna") get an end date and stop
  being used (and are removed) after it
- the data folder encrypted with Windows EFS (`cipher /e`): the files are readable only under your Windows login –
  transparent for JARVIS, nothing to remember (not on Windows Home; BitLocker then)
- imports: ChatGPT and Claude exports (conversations.json) and Google Keep notes (Takeout) – first a preview of
  what would come in, then the conversations / notes become searchable chats in the folder "Import"
- decisions with their reason ("rozhodli jsme se pro B, protože…") remembered as such
- a monthly clean-up: near-duplicate facts and expired ones, proposed – nothing is deleted without your click
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
import time
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

DAYS = {"pondeli": 0, "pondělí": 0, "utery": 1, "úterý": 1, "streda": 2, "středa": 2, "ctvrtek": 3, "čtvrtek": 3,
        "patek": 4, "pátek": 4, "sobota": 5, "sobotu": 5, "nedele": 6, "neděle": 6, "nedeli": 6, "neděli": 6}


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# ---------- 52: facts with an end ----------
def expiry_for(text: str, now: float | None = None) -> float | None:
    """The moment a time-bound fact stops being true (the end of the day after the event), or None."""
    t = _fold(text)
    today = dt.date.fromtimestamp(now if now is not None else time.time())
    day: dt.date | None = None
    if re.search(r"\b(dnes|dneska|dnesni|vecer|odpoledne)\b", t):
        day = today
    elif re.search(r"\bpozitri\b", t):
        day = today + dt.timedelta(days=2)
    elif re.search(r"\bzitra\b", t):
        day = today + dt.timedelta(days=1)
    elif re.search(r"\b(tento|tenhle|tenhle|pristi) tyden\b", t):
        day = today + dt.timedelta(days=(6 - today.weekday()) + (7 if "pristi" in t else 0))
    else:
        m = re.search(r"\b(?:v|ve|na|od|do)\s+(pondeli|utery|stred[au]|ctvrtek|patek|sobotu|nedeli)\b", t)
        if m:
            wd = DAYS.get(m.group(1).replace("stredu", "streda"), None)
            if wd is not None:
                delta = (wd - today.weekday()) % 7 or 7
                day = today + dt.timedelta(days=delta)
        else:
            m = re.search(r"\b(\d{1,2})\.\s*(\d{1,2})\.(?:\s*(\d{4}))?", t)
            if m:
                try:
                    year = int(m.group(3)) if m.group(3) else today.year
                    day = dt.date(year, int(m.group(2)), int(m.group(1)))
                    if not m.group(3) and day < today:
                        day = day.replace(year=today.year + 1)
                except ValueError:
                    day = None
    if day is None or not re.search(r"\b(mam|mame|jdu|jedu|letim|odjizdim|prijede|prijde|budu|bude|je|ma|schuzk\w*|"
                                    r"zubar\w*|doktor\w*|termin\w*|narozenin\w*|navstev\w*|zkousk\w*|pohovor\w*)\b", t):
        return None
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(23, 59))
    return end.timestamp()


def ensure_columns(rt: Any) -> None:
    db = rt.db
    with db.lock:
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(facts)")}
        if "expires" not in cols:
            db.conn.execute("ALTER TABLE facts ADD COLUMN expires REAL")
            db.conn.commit()


def set_expiry(rt: Any, fact_id: int, text: str) -> float | None:
    ensure_columns(rt)
    exp = expiry_for(text)
    if exp:
        rt.db.exec("UPDATE facts SET expires=? WHERE id=?", (exp, fact_id))
    return exp


def expired(rt: Any, now: float | None = None) -> list[dict]:
    ensure_columns(rt)
    return rt.db.all("SELECT id, text, expires FROM facts WHERE expires IS NOT NULL AND expires < ?", (now or time.time(),))


def drop_expired(rt: Any, now: float | None = None) -> int:
    gone = expired(rt, now)
    for f in gone:
        rt.db.exec("DELETE FROM facts WHERE id=?", (f["id"],))
    return len(gone)


# ---------- 56: a decision with its reason ----------
def decision_text(decision: str, reason: str, when: dt.date | None = None) -> str:
    d = (when or dt.date.today()).strftime("%d. %m. %Y")
    return f"Rozhodnutí ({d}): {decision.strip().rstrip('.')} – protože {reason.strip().rstrip('.')}."


# ---------- 57: clean-up ----------
def _words(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z0-9]+", _fold(text)) if len(w) > 2}


def cleanup_suggestions(rt: Any, threshold: float = 0.7) -> dict:
    """Near-duplicate facts (most of their words the same) and expired ones – proposals only."""
    ensure_columns(rt)
    facts = rt.db.all("SELECT id, text, created FROM facts ORDER BY id")
    pairs = []
    ws = [(f, _words(f["text"])) for f in facts]
    for i, (a, wa) in enumerate(ws):
        for b, wb in ws[i + 1:]:
            if not wa or not wb:
                continue
            j = len(wa & wb) / len(wa | wb)
            if j >= threshold:
                keep, drop = (b, a) if b["created"] >= a["created"] else (a, b)   # the newer one stays
                pairs.append({"keep": {"id": keep["id"], "text": keep["text"]}, "drop": {"id": drop["id"], "text": drop["text"]},
                              "similar": round(j, 2)})
    return {"duplicates": pairs[:30], "expired": [{"id": f["id"], "text": f["text"]} for f in expired(rt)][:30]}


def apply_cleanup(rt: Any, ids: list[int]) -> int:
    n = 0
    for i in ids:
        if rt.db.exec("DELETE FROM facts WHERE id=?", (int(i),)).rowcount:
            n += 1
    return n


# ---------- 54: imports ----------
def _read_json(path: Path, inner: str) -> Any:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.endswith(inner)), None)
            if not name:
                raise ValueError(f"v ZIPu není {inner}")
            return json.loads(z.read(name).decode("utf-8"))
    return json.loads(path.read_text("utf-8"))


def parse_chat_export(path: str | Path) -> list[dict]:
    """ChatGPT or Claude export → [{title, created, messages: [{role, text, ts}]}] (oldest message first)."""
    data = _read_json(Path(path), "conversations.json")
    out = []
    for conv in data if isinstance(data, list) else []:
        msgs: list[dict] = []
        if isinstance(conv.get("mapping"), dict):                       # ChatGPT
            for node in conv["mapping"].values():
                m = (node or {}).get("message") or {}
                role = ((m.get("author") or {}).get("role")) or ""
                parts = ((m.get("content") or {}).get("parts")) or []
                text = "\n".join(p for p in parts if isinstance(p, str)).strip()
                if role in ("user", "assistant") and text:
                    msgs.append({"role": role, "text": text, "ts": float(m.get("create_time") or conv.get("create_time") or 0)})
        elif isinstance(conv.get("chat_messages"), list):              # Claude
            for m in conv["chat_messages"]:
                role = {"human": "user", "assistant": "assistant"}.get(m.get("sender", ""), "")
                text = (m.get("text") or "").strip()
                if role and text:
                    ts = m.get("created_at") or ""
                    try:
                        t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
                    except ValueError:
                        t = 0.0
                    msgs.append({"role": role, "text": text, "ts": t})
        if msgs:
            msgs.sort(key=lambda x: x["ts"])
            out.append({"title": (conv.get("title") or conv.get("name") or "Import")[:120], "created": msgs[0]["ts"],
                        "messages": msgs})
    return out


def parse_keep(path: str | Path) -> list[dict]:
    """Google Keep from Takeout (a folder of .json notes, or the Takeout ZIP) → [{title, text, ts}]."""
    p = Path(path)
    items: list[dict] = []

    def one(d: dict) -> None:
        if d.get("isTrashed"):
            return
        text = (d.get("textContent") or "").strip()
        if d.get("listContent"):
            text = "\n".join(("✓ " if x.get("isChecked") else "• ") + x.get("text", "") for x in d["listContent"])
        if text or d.get("title"):
            items.append({"title": (d.get("title") or text.split("\n")[0])[:120], "text": text,
                          "ts": float(d.get("userEditedTimestampUsec") or d.get("createdTimestampUsec") or 0) / 1e6})
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if "/Keep/" in n and n.endswith(".json"):
                    one(json.loads(z.read(n).decode("utf-8")))
    elif p.is_dir():
        for f in sorted(p.glob("*.json")):
            one(json.loads(f.read_text("utf-8")))
    return items


def preview_import(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise ValueError("soubor nebo složka neexistuje")
    kind = "keep" if (p.is_dir() or "takeout" in p.name.lower()) else "chat"
    if kind == "chat":
        convs = parse_chat_export(p)
        return {"kind": "chat", "conversations": len(convs), "messages": sum(len(c["messages"]) for c in convs),
                "titles": [c["title"] for c in convs[:12]]}
    notes = parse_keep(p)
    return {"kind": "keep", "notes": len(notes), "titles": [n["title"] for n in notes[:12]]}


def run_import(rt: Any, path: str, source: str = "") -> dict:
    """Into the chat history (folder "Import") – searchable, deletable conversation by conversation."""
    import uuid

    mem = rt.memory
    if mem.private:
        return {"imported": 0, "reason": "soukromý režim"}
    p = Path(path)
    prev = preview_import(path)
    db = rt.db
    n_conv = n_msg = 0

    def conv(title: str, created: float) -> str:
        cid = uuid.uuid4().hex[:12]
        db.exec("INSERT INTO conversations (id, title, created, updated, folder) VALUES (?,?,?,?,?)",
                (cid, title, created or time.time(), created or time.time(), "Import"))
        return cid

    def msg(cid: str, role: str, text: str, ts: float, src: str) -> None:
        db.exec("INSERT INTO messages (id, conv_id, role, content, attachments, source, created, meta) VALUES (?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex[:12], cid, role, text[:20000], "[]", src, ts or time.time(), "{}"))

    if prev["kind"] == "chat":
        for c in parse_chat_export(p):
            cid = conv(f"{source or 'Import'}: {c['title']}", c["created"])
            n_conv += 1
            for m in c["messages"]:
                msg(cid, m["role"], m["text"], m["ts"], "import")
                n_msg += 1
    else:
        cid = conv("Google Keep", time.time())
        n_conv = 1
        for nt in parse_keep(p):
            msg(cid, "user", f"{nt['title']}\n{nt['text']}".strip(), nt["ts"], "import-keep")
            n_msg += 1
    try:
        rt.knowledge.refresh_index()
    except Exception:  # noqa: BLE001
        pass
    return {"imported": n_msg, "conversations": n_conv, "kind": prev["kind"]}


# ---------- 53: the data folder encrypted with Windows EFS ----------
def encrypt_data_folder(data_dir: Path) -> dict:
    if sys.platform != "win32":
        return {"ok": False, "message": "Šifrování složky přes EFS je jen ve Windows."}
    r = subprocess.run(["cipher", "/e", "/s:" + str(data_dir)], capture_output=True, text=True, timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        home = "not supported" in out.lower() or "nepodporuje" in out.lower()
        return {"ok": False, "message": ("Tahle edice Windows (Home) EFS nemá – zapni šifrování celého disku "
                                         "(Nastavení Windows → Ochrana osobních údajů → Šifrování zařízení / BitLocker).")
                if home else f"cipher skončil s chybou: {out.strip()[:200]}"}
    return {"ok": True, "message": "Složka s daty JARVISe je zašifrovaná – číst ji jde jen pod tvým přihlášením do Windows. "
                                   "Zálohuj si certifikát EFS (certmgr → Osobní), jinak data po přeinstalaci Windows neotevřeš."}


def encryption_state(data_dir: Path) -> str:
    if sys.platform != "win32":
        return "unsupported"
    try:
        import ctypes

        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(data_dir / "jarvis.db"))
        return "on" if attrs != -1 and attrs & 0x4000 else "off"          # FILE_ATTRIBUTE_ENCRYPTED
    except Exception:  # noqa: BLE001
        return "unknown"


async def monthly(rt: Any, every_s: float = 30 * 86400) -> None:
    """Once a month: "Mám N návrhů na úklid paměti" (only when there are some)."""
    import asyncio

    await asyncio.sleep(1800)
    while True:
        try:
            row = rt.db.one("SELECT v FROM kv WHERE k='memory_cleanup_at'")
            last = float(row["v"]) if row else 0.0
            if time.time() - last >= every_s:
                rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('memory_cleanup_at', ?)", (str(time.time()),))
                s = cleanup_suggestions(rt)
                n = len(s["duplicates"]) + len(s["expired"])
                if n:
                    rt.notify("Úklid paměti", f"Mám {n} návrhů, co v paměti sloučit nebo smazat – Paměť → Úklid paměti.",
                              speak=False)
        except Exception:  # noqa: BLE001 – a reminder must never break anything
            pass
        await asyncio.sleep(6 * 3600)
