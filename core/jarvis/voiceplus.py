"""OMEGA §23 / §10 / §09 voice, more: bookmarks in a recording or a conversation, pronunciation scoring of a read
sentence (word alignment + how sure the recogniser was), and the peaks of wake-word scores for calibration."""
from __future__ import annotations

import difflib
import re
import time

from .comms import fold

BOOKMARKS_SQL = """CREATE TABLE IF NOT EXISTS voice_bookmarks (id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL, kind TEXT NOT NULL,
  ref TEXT NOT NULL, at REAL, label TEXT, context TEXT);"""


# ============================================================================================== 266 bookmarks
def add_bookmark(rt, label: str = "") -> dict:
    """While a call is being recorded: a mark at this second of the recording. Otherwise: a mark on the last exchange
    of the current conversation."""
    rt.db.conn.executescript(BOOKMARKS_SQL)
    nt = getattr(rt, "notetaker", None)
    if nt is not None and nt.state == "recording" and nt.current:
        at = round(time.time() - nt.started, 1)
        rt.db.exec("INSERT INTO voice_bookmarks(created, kind, ref, at, label, context) VALUES (?,?,?,?,?,?)",
                   (time.time(), "note", nt.current, at, label, ""))
        return {"kind": "note", "ref": nt.current, "at": at, "label": label}
    recent = rt.memory.recent(4)
    if not recent:
        raise ValueError("Není co označit – nenahrává se hovor a konverzace je prázdná.")
    last = recent[-1]
    ctx = " / ".join(f"{'Ty' if m['role'] == 'user' else 'JARVIS'}: {m['text'][:160]}" for m in recent[-2:])
    rt.db.exec("INSERT INTO voice_bookmarks(created, kind, ref, at, label, context) VALUES (?,?,?,?,?,?)",
               (time.time(), "chat", last["id"], None, label, ctx))
    return {"kind": "chat", "ref": last["id"], "label": label, "context": ctx}


def _fmt(sec: float) -> str:
    return f"{int(sec // 60)}:{int(sec % 60):02d}"


def bookmarks(rt, query: str = "", limit: int = 30) -> list[dict]:
    """Bookmarks, newest first; recording marks get the transcript lines around their second once it is ready."""
    rt.db.conn.executescript(BOOKMARKS_SQL)
    rows = rt.db.all("SELECT * FROM voice_bookmarks ORDER BY created DESC LIMIT ?", (limit * 3,))
    out = []
    for r in rows:
        item = {"id": r["id"], "when": time.strftime("%d. %m. %H:%M", time.localtime(r["created"])), "kind": r["kind"],
                "label": r["label"] or "", "context": r["context"] or ""}
        if r["kind"] == "note":
            note = rt.notetaker.get(r["ref"]) if getattr(rt, "notetaker", None) else None
            item["at"] = _fmt(r["at"] or 0)
            item["note"] = r["ref"]
            if note and note.get("status") == "done":
                lines = note["transcript"]
                near = [ln for ln in lines if ln["start"] - 20 <= (r["at"] or 0) <= ln["end"] + 5] or \
                    sorted(lines, key=lambda ln: abs(ln["start"] - (r["at"] or 0)))[:1]
                item["context"] = " / ".join(f"{ln['who']}: {ln['text'][:200]}" for ln in near[-3:])
                item["title"] = note.get("title")
            elif note:
                item["context"] = "přepis se ještě zpracovává" if note.get("status") in ("recording", "processing") else item["context"]
            else:
                item["context"] = "nahrávka už neexistuje"
        if query and fold(query) not in fold(item["label"] + " " + item["context"] + " " + item.get("title", "")):
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


# ============================================================================================== 114 pronunciation
def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[\w'’]+", text)]


def pronunciation(target: str, words: list[dict], unsure: float = 0.6) -> dict:
    """Align what the student was supposed to read with the recognised words: missing, misheard (target → heard),
    extra, and words recognised only with low certainty (unclear). Score = clearly right words / target words."""
    tgt = _tokens(target)
    if not tgt:
        raise ValueError("Zadej větu, kterou budeš číst.")
    heard = [w for w in words if _tokens(w["word"])]
    a = [fold(t) for t in tgt]
    b = [fold(_tokens(w["word"])[0]) for w in heard]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    good, unclear, wrong, missing, extra = [], [], [], [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                p = heard[j].get("p")
                (unclear if p is not None and p < unsure else good).append({"word": tgt[i], "p": p})
        elif op == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                if i1 + k < i2 and j1 + k < j2:
                    wrong.append({"word": tgt[i1 + k], "heard": heard[j1 + k]["word"]})
                elif i1 + k < i2:
                    missing.append(tgt[i1 + k])
                else:
                    extra.append(heard[j1 + k]["word"])
        elif op == "delete":
            missing += tgt[i1:i2]
        else:
            extra += [heard[j]["word"] for j in range(j1, j2)]
    score = round(100 * len(good) / len(tgt))
    tips = []
    if wrong:
        tips.append("Zopakuj pomalu: " + ", ".join(f"„{w['word']}“ (slyšel jsem „{w['heard']}“)" for w in wrong[:5]))
    if unclear:
        tips.append("Nezřetelně: " + ", ".join(f"„{w['word']}“" for w in unclear[:5]) + " – vyslov celé slovo, ne jen začátek")
    if missing:
        tips.append("Vynechal jsi: " + ", ".join(f"„{w}“" for w in missing[:5]))
    if heard and len(heard) > 1:
        dur = heard[-1]["end"] - heard[0]["start"]
        wpm = round(60 * len(heard) / dur) if dur > 0 else None
        if wpm and wpm > 170:
            tips.append(f"Mluvíš rychle ({wpm} slov/min) – zpomal na 120–150")
    else:
        wpm = None
    return {"score": score, "good": len(good), "total": len(tgt), "wrong": wrong, "unclear": unclear, "missing": missing, "extra": extra,
            "words_per_minute": wpm, "tips": tips}


# ============================================================================================== 260 calibration
def peaks(scores: list[float], min_score: float = 0.05, gap: int = 12) -> list[float]:
    """The highest score of each separate moment the phrase was (probably) said (frames above min_score, apart by
    `gap` frames ≈ 1 s)."""
    out, cur, last = [], 0.0, -10 ** 9
    for i, s in enumerate(scores):
        if s >= min_score:
            if i - last > gap and cur:
                out.append(cur)
                cur = 0.0
            cur = max(cur, s)
            last = i
    if cur:
        out.append(cur)
    return out
