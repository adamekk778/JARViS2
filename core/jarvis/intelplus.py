"""OMEGA wave 41: predicting the next steps (196), contradictions in texts (205), improving code until the tests pass (210),
spotting repeated work worth automating (498), negotiating priorities against the time available (505), handing data from
one app to another (513), discovering what an app can do (514), a semantic index linking files, events, notes and memory
(515), the input mode that suits the device (522) and the sources behind an answer (550)."""
from __future__ import annotations

import datetime as dt
import difflib
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from .comms import fold

# ---------------------------------------------------------------- 196 / 498 sequences of actions
SESSION_GAP_S = 30 * 60
NOISE = {"update_plan", "remember", "recall", "ui_tick"}


def sessions(rows: list[dict], gap_s: float = SESSION_GAP_S) -> list[list[str]]:
    """task_actions rows (ts, tool) → runs of tools with no long pause in between."""
    out: list[list[str]] = []
    last = None
    for r in sorted(rows, key=lambda r: r["ts"]):
        if r["tool"] in NOISE:
            continue
        if last is None or r["ts"] - last > gap_s:
            out.append([])
        out[-1].append(r["tool"])
        last = r["ts"]
    return [s for s in out if s]


def markov(seqs: list[list[str]]) -> dict:
    """First- and second-order transition counts."""
    one: dict[str, Counter] = defaultdict(Counter)
    two: dict[tuple, Counter] = defaultdict(Counter)
    for s in seqs:
        for i in range(1, len(s)):
            one[s[i - 1]][s[i]] += 1
            if i >= 2:
                two[(s[i - 2], s[i - 1])][s[i]] += 1
    return {"one": one, "two": two}


def _next(model: dict, recent: list[str]) -> list[tuple[str, float]]:
    c = model["two"].get(tuple(recent[-2:])) if len(recent) >= 2 else None
    if not c or sum(c.values()) < 2:
        c = model["one"].get(recent[-1]) if recent else None
    if not c:
        return []
    n = sum(c.values())
    return [(k, v / n) for k, v in c.most_common()]


def predict(model: dict, recent: list[str], steps: int = 3, beam: int = 3) -> list[dict]:
    """The most likely next paths (beam search over the chain), each with its probability."""
    paths = [([], 1.0)]
    for _ in range(steps):
        grown = []
        for path, p in paths:
            nxt = _next(model, recent + path)
            if not nxt:
                grown.append((path, p))
                continue
            grown += [(path + [k], p * q) for k, q in nxt[:beam]]
        paths = sorted(grown, key=lambda x: -x[1])[:beam]
    return [{"steps": path, "p": round(p, 3)} for path, p in paths if path]


def repeated_patterns(seqs: list[list[str]], min_len: int = 2, max_len: int = 4, min_sessions: int = 3) -> list[dict]:
    """Runs of actions that come back in several sessions – candidates for one automation or skill."""
    seen: Counter = Counter()
    for s in seqs:
        found = set()
        for n in range(min_len, max_len + 1):
            for i in range(len(s) - n + 1):
                found.add(tuple(s[i:i + n]))
        seen.update(found)
    hits = [{"steps": list(k), "sessions": v} for k, v in seen.items() if v >= min_sessions and len(set(k)) > 1]
    hits.sort(key=lambda h: (-h["sessions"] * len(h["steps"]), -len(h["steps"])))
    out: list[dict] = []
    for h in hits:                                      # drop a run that is part of a longer one seen as often
        if any(len(o["steps"]) > len(h["steps"]) and o["sessions"] >= h["sessions"] and _contains(o["steps"], h["steps"]) for o in out):
            continue
        out.append(h)
    return out[:8]


def _contains(big: list, small: list) -> bool:
    return any(big[i:i + len(small)] == small for i in range(len(big) - len(small) + 1))


def app_habits(rows: list[dict], weekday: int, hour: int) -> list[dict]:
    """app_hours rows (day, hour, app, seconds) → what is usually in use at this weekday and hour."""
    tot: Counter = Counter()
    days = set()
    for r in rows:
        d = dt.date.fromisoformat(r["day"])
        if d.weekday() == weekday and r["hour"] == hour:
            tot[r["app"]] += r["seconds"]
            days.add(r["day"])
    if not days:
        return []
    return [{"app": a, "minutes_avg": round(s / len(days) / 60, 1)} for a, s in tot.most_common(3)]


# ---------------------------------------------------------------- 205 contradictions
STOP = {"je", "jsou", "byl", "byla", "bylo", "ma", "maji", "bude", "budou", "a", "i", "v", "ve", "na", "do", "se", "si", "to", "ze",
        "za", "o", "s", "z", "k", "u", "pro", "nebo", "ale", "the", "is", "of", "a", "an", "pak", "jen", "celkem", "maximalne",
        "minimalne", "nejvyse", "nejmene", "cini", "činí", "obnasi", "stoji", "trva", "nez", "po", "pri", "od", "kterou", "ktera", "ktery"}
NUM = re.compile(r"(\d+(?:[  ]\d{3})*(?:[.,]\d+)?)\s*(%|kč|czk|eur|€|usd|\$|dní|dnů|dny|den|dnu|let|roky|roku|rok|měsíců|měsíce|měsíc|"
                 r"týdnů|týdny|týden|hodin|hodiny|hodinu|h|minut|min|kg|g|km|m|cm|mm|l|ks|kusů)?(?![\w])", re.I)
NEG = {"neni": "je", "nejsou": "jsou", "nema": "ma", "nemaji": "maji", "nemuze": "muze", "nemuzou": "muzou", "nesmi": "smi", "nelze": "lze",
       "nebude": "bude", "nebudou": "budou", "nepotrebuje": "potrebuje", "nevyzaduje": "vyzaduje", "neplati": "plati", "nebyl": "byl",
       "nebyla": "byla", "nebylo": "bylo", "neobsahuje": "obsahuje", "nezahrnuje": "zahrnuje", "not": "", "no": ""}
UNIT = {"dnů": "dní", "dny": "dní", "den": "dní", "dnu": "dní", "roky": "let", "roku": "let", "rok": "let", "měsíce": "měsíců", "měsíc": "měsíců",
        "týdny": "týdnů", "týden": "týdnů", "hodiny": "hodin", "hodinu": "hodin", "h": "hodin", "min": "minut", "czk": "kč", "€": "eur",
        "$": "usd", "kusů": "ks"}


def _stem(w: str) -> str:
    return w[:5]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", text) if len(s.strip()) > 3]


def _claims(sentence: str) -> list[dict]:
    out = []
    for m in NUM.finditer(sentence):
        before = fold(re.split(r"[:;(]|,\s", sentence[:m.start()])[-1])   # only the clause the number belongs to
        words = [w for w in re.findall(r"[a-z]{3,}", before) if w not in STOP][-3:]
        if len(words) < 1:
            continue
        val = float(m.group(1).replace(" ", "").replace(" ", "").replace(",", "."))
        unit = (m.group(2) or "").lower()
        out.append({"key": frozenset(_stem(w) for w in words), "value": val, "unit": UNIT.get(unit, unit), "text": m.group(0).strip()})
    return out


def _polarity(sentence: str) -> tuple[str, bool]:
    words = re.findall(r"\w+", fold(sentence))
    neg = False
    norm = []
    for w in words:
        if w in NEG:
            neg = not neg
            if NEG[w]:
                norm.append(NEG[w])
        else:
            norm.append(w)
    return " ".join(w for w in norm if w not in ("a", "i")), neg


def contradictions(docs: list[dict]) -> list[dict]:
    """docs: [{"name", "text"}] → pairs of statements that cannot both be true (a different number for the same thing,
    or the same sentence once with and once without a negation). Works inside one text and across texts."""
    claims, pols = [], []
    for d in docs:
        for s in _sentences(d.get("text", "")):
            for c in _claims(s):
                claims.append({**c, "doc": d.get("name", ""), "sentence": s})
            norm, neg = _polarity(s)
            if len(norm.split()) >= 3:
                pols.append({"norm": norm, "neg": neg, "doc": d.get("name", ""), "sentence": s})
    out, seen = [], set()
    for i, a in enumerate(claims):
        for b in claims[i + 1:]:
            if a["sentence"] == b["sentence"] or a["unit"] != b["unit"] or a["value"] == b["value"]:
                continue
            overlap = len(a["key"] & b["key"])
            if overlap >= 2 or (overlap == 1 and len(a["key"]) == len(b["key"]) == 1):
                k = (a["sentence"], b["sentence"])
                if k not in seen:
                    seen.add(k)
                    out.append({"kind": "jiná hodnota", "what": " ".join(sorted(a["key"] & b["key"])), "a": {"doc": a["doc"], "text": a["sentence"], "value": a["text"]},
                                "b": {"doc": b["doc"], "text": b["sentence"], "value": b["text"]}})
    for i, a in enumerate(pols):
        for b in pols[i + 1:]:
            if a["neg"] != b["neg"] and difflib.SequenceMatcher(None, a["norm"], b["norm"]).ratio() > 0.9:
                out.append({"kind": "popření", "what": "", "a": {"doc": a["doc"], "text": a["sentence"]}, "b": {"doc": b["doc"], "text": b["sentence"]}})
    return out


# ---------------------------------------------------------------- 210 improve until the tests pass
def _copy_project(root: Path) -> tuple[Path, Callable[[], None]]:
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-improve-"))
    dest = tmp / root.name
    shutil.copytree(root, dest, ignore=shutil.ignore_patterns(".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"))
    return dest, lambda: shutil.rmtree(tmp, ignore_errors=True)


def run_tests(cwd: Path, cmd: str, timeout: int = 300) -> tuple[bool, str]:
    import os

    for c in cwd.rglob("__pycache__"):                  # an edit of the same size in the same second would reuse stale bytecode
        shutil.rmtree(c, ignore_errors=True)
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"},
                           creationflags=0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
    except subprocess.TimeoutExpired:
        return False, f"Testy nedoběhly do {timeout} s."
    out = (p.stdout + "\n" + p.stderr).strip()
    return p.returncode == 0, out[-6000:]


async def improve_loop(root: Path, test_cmd: str, files: list[str], propose, max_rounds: int = 4, runner=run_tests) -> dict:
    """Work in a throw-away copy: run the tests, give the failure and the files to `propose` (→ {file: new text}), apply,
    repeat. The original project is never touched; the result is a diff the user can apply."""
    work, cleanup = _copy_project(root)
    try:
        original = {f: (root / f).read_text(encoding="utf-8") for f in files}
        log: list[dict] = []
        ok, out = runner(work, test_cmd)
        log.append({"round": 0, "ok": ok, "output": out[-1500:]})
        rounds = 0
        while not ok and rounds < max_rounds:
            rounds += 1
            current = {f: (work / f).read_text(encoding="utf-8") for f in files}
            change = await propose(current, out, rounds)
            if not isinstance(change, dict) or not change:
                log.append({"round": rounds, "ok": False, "output": "AI nenavrhla žádnou změnu."})
                break
            for f, text in change.items():
                if f in files and isinstance(text, str):
                    (work / f).write_text(text, encoding="utf-8")
            ok, out = runner(work, test_cmd)
            log.append({"round": rounds, "ok": ok, "output": out[-1500:], "changed": sorted(k for k in change if k in files)})
        final = {f: (work / f).read_text(encoding="utf-8") for f in files}
        diff = "".join("".join(difflib.unified_diff(original[f].splitlines(True), final[f].splitlines(True), f"a/{f}", f"b/{f}"))
                       for f in files if original[f] != final[f])
        return {"ok": ok, "rounds": rounds, "log": log, "diff": diff, "files": {f: final[f] for f in files if original[f] != final[f]}}
    finally:
        cleanup()


# ---------------------------------------------------------------- 505 priorities against the time available
def _date(x: Any) -> dt.date:
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x)[:10])


def schedule(tasks: list[dict], hours_per_day: float, start: dt.date, workdays: set[int] = frozenset(range(5))) -> list[dict]:
    """Earliest deadline first (ties: higher priority = lower number): when each task would be finished."""
    order = sorted(tasks, key=lambda t: (_date(t["due"]), int(t.get("priority", 2))))
    day, left, out = start, hours_per_day if start.weekday() in workdays else 0, []
    for t in order:
        need = float(t["hours"])
        while need > 1e-9:
            while left <= 1e-9:
                day += dt.timedelta(days=1)
                left = hours_per_day if day.weekday() in workdays else 0
            used = min(left, need)
            need -= used
            left -= used
        out.append({**t, "finish": day.isoformat(), "late_days": max(0, (day - _date(t["due"])).days)})
    return out


def negotiate(tasks: list[dict], hours_per_day: float, start: dt.date | None = None, workdays: set[int] = frozenset(range(5))) -> dict:
    """If something will be late: postpone the least important tasks (priority 3, then 2) to make room, report the new
    finish dates and how many extra hours would keep everything on time."""
    start = start or dt.date.today()
    plan = schedule(tasks, hours_per_day, start, workdays)
    late = [p for p in plan if p["late_days"]]
    if not late:
        return {"ok": True, "plan": plan, "postpone": [], "extra_hours": 0, "late": []}
    keep = list(tasks)
    postponed: list[dict] = []
    for prio in (3, 2):
        for t in sorted([t for t in keep if int(t.get("priority", 2)) == prio], key=lambda t: _date(t["due"]), reverse=True):
            trial = schedule([k for k in keep if k is not t], hours_per_day, start, workdays)
            keep.remove(t)
            postponed.append(t)
            if not any(p["late_days"] for p in trial):
                break
        if not any(p["late_days"] for p in schedule(keep, hours_per_day, start, workdays)):
            break
    after = schedule(keep, hours_per_day, start, workdays)
    tail = schedule(keep + [{**p, "due": "2999-12-31"} for p in postponed], hours_per_day, start, workdays)
    new_dates = {p["name"]: p["finish"] for p in tail if any(p["name"] == q["name"] for q in postponed)}
    extra = 0.0
    for p in schedule(tasks, hours_per_day, start, workdays):        # hours missing up to each deadline
        due = _date(p["due"])
        cap = sum(hours_per_day for i in range((due - start).days + 1) if (start + dt.timedelta(days=i)).weekday() in workdays)
        need = sum(float(t["hours"]) for t in tasks if _date(t["due"]) <= due)
        extra = max(extra, need - cap)
    return {"ok": not any(p["late_days"] for p in after), "plan": after, "late": [p["name"] for p in late],
            "postpone": [{"name": p["name"], "priority": int(p.get("priority", 2)), "was_due": str(p["due"])[:10], "new_finish": new_dates.get(p["name"])} for p in postponed],
            "extra_hours": round(extra, 1)}


# ---------------------------------------------------------------- 513 handing data between apps
def table_from_text(text: str) -> list[list[str]]:
    """Clipboard from Excel / a web table / CSV → rows (tabs, semicolons, commas or 2+ spaces)."""
    lines = [ln for ln in text.replace("\r", "").split("\n") if ln.strip()]
    if len(lines) < 2:
        return []
    for sep in ("\t", ";", ",", "  "):
        if all(sep in ln for ln in lines):
            rows = [[c.strip() for c in (re.split(r" {2,}", ln) if sep == "  " else ln.split(sep))] for ln in lines]
            if len({len(r) for r in rows}) == 1 and len(rows[0]) > 1:
                return rows
    return []


def event_from_text(text: str, now: float | None = None) -> dict | None:
    from .uiplus import parse_due

    due = parse_due(text, now)
    m = re.search(r"\b(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?(?:\s+(?:v|ve|od)?\s*(\d{1,2})[:.](\d{2}))?", text)
    if m:
        base = dt.datetime.fromtimestamp(now or time.time())
        y = int(m.group(3) or base.year)
        hh, mm = (int(m.group(4)), int(m.group(5))) if m.group(4) else (9, 0)
        try:
            due = dt.datetime(y, int(m.group(2)), int(m.group(1)), hh, mm).timestamp()
        except ValueError:
            pass
    if due is None:
        return None
    title = re.sub(r"\b\d{1,2}\.\s?\d{1,2}\.(\s?\d{4})?|\b(v|ve|od)?\s*\d{1,2}[:.]\d{2}\b|\b(zítra|pozítří|dnes)\b", " ", text.splitlines()[0])
    title = " ".join(title.split()).strip(" ,.-–:") or "Událost"
    loc = re.search(r"\b(?:v|ve|na)\s+([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][\wáčďéěíňóřšťúůýž]+(?:\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ\d][\wáčďéěíňóřšťúůýž]*)*)", text)
    return {"title": title[:80], "start": due, "location": loc.group(1) if loc else ""}


def items_from_text(text: str) -> list[str]:
    out = []
    for ln in text.replace("\r", "").split("\n"):
        ln = re.sub(r"^\s*(?:[-*•▪◦]|\d+[.)]|\[[ x]\])\s*", "", ln).strip()
        if ln:
            out.append(ln[:200])
    if len(out) == 1 and "," in out[0]:
        out = [x.strip() for x in out[0].split(",") if x.strip()]
    return out[:50]


def eml_draft(to: str, subject: str, body: str) -> bytes:
    """A draft e-mail the default mail program opens (X-Unsent: 1) – the user sends it, never JARVIS."""
    from email.message import EmailMessage

    m = EmailMessage()
    m["To"] = to
    m["Subject"] = subject
    m["X-Unsent"] = "1"
    m.set_content(body)
    return bytes(m)


# ---------------------------------------------------------------- 514 what an app can do
def parse_help(text: str) -> dict:
    """`program --help` → options (flag, argument, description) and sub-commands."""
    opts, cmds, section = [], [], ""
    for raw in text.splitlines():
        ln = raw.rstrip()
        if re.match(r"^\s*(commands|subcommands|příkazy|available commands)\s*:?\s*$", ln, re.I):
            section = "cmd"
            continue
        if re.match(r"^\s*(options|flags|optional arguments|global options|přepínače|parametry)\s*:?\s*$", ln, re.I):
            section = "opt"
            continue
        m = re.match(r"^\s{0,8}((?:-{1,2}|/)[\w?][\w-]*)(?:,\s*((?:-{1,2}|/)[\w-]+))?(?:[ =]([<\[A-Z][\w<>\[\].|-]*))?\s{2,}(.+)$", ln)
        if m:
            flags = [f for f in (m.group(1), m.group(2)) if f]
            opts.append({"flags": flags, "arg": (m.group(3) or "").strip("<>[]"), "desc": m.group(4).strip()})
            continue
        m = re.match(r"^\s{1,8}([a-z][\w-]+)\s{2,}(.+)$", ln)
        if m and section == "cmd":
            cmds.append({"name": m.group(1), "desc": m.group(2).strip()})
    return {"options": opts, "commands": cmds}


def app_associations(exe_name: str, reader: Callable[[], list[dict]]) -> dict:
    """reader() → [{"kind": "ext"|"protocol", "name": ".pdf"|"mailto", "command": "…exe …"}] (from the registry on Windows)."""
    key = fold(Path(exe_name).stem)
    hits = [r for r in reader() if key and key in fold(r.get("command", ""))]
    return {"extensions": sorted({r["name"] for r in hits if r["kind"] == "ext"}),
            "protocols": sorted({r["name"] for r in hits if r["kind"] == "protocol"})}


def registry_associations(limit: int = 6000) -> list[dict]:     # pragma: no cover – Windows registry
    import winreg

    out = []
    root = winreg.HKEY_CLASSES_ROOT
    i = 0
    while i < limit:
        try:
            name = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        try:
            with winreg.OpenKey(root, name) as k:
                is_proto = False
                try:
                    winreg.QueryValueEx(k, "URL Protocol")
                    is_proto = True
                except OSError:
                    pass
                target = name
                if name.startswith("."):
                    try:
                        target = winreg.QueryValueEx(k, "")[0] or name
                    except OSError:
                        continue
            with winreg.OpenKey(root, target + r"\shell\open\command") as c:
                cmd = winreg.QueryValueEx(c, "")[0]
        except OSError:
            continue
        if name.startswith(".") or is_proto:
            out.append({"kind": "ext" if name.startswith(".") else "protocol", "name": name, "command": str(cmd)})
    return out


# ---------------------------------------------------------------- 515 semantic desktop index
LINKS_SQL = ("CREATE TABLE IF NOT EXISTS sem_links (entity TEXT, kind TEXT, source TEXT, ref TEXT, label TEXT, ts REAL)",
             "CREATE INDEX IF NOT EXISTS ix_sem_entity ON sem_links(entity)")
NAME = re.compile(r"(?=\b([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]{1,20}\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]{2,20})\b)")
FIRST = {"Dobrý", "Ahoj", "Dobry", "Vážený", "Vážená", "Milý", "Milá", "Prosím", "Děkuji", "Dnes", "Zítra", "Hello", "Dear"}


def entities(text: str, known: list[str] | None = None) -> set[tuple[str, str]]:
    """(kind, value): e-mails, phone numbers, two-word names, ICO, and known project / contact names."""
    out: set[tuple[str, str]] = set()
    for e in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text):
        out.add(("email", e.lower()))
    for p in re.findall(r"(?:\+420\s?)?\b\d{3}\s?\d{3}\s?\d{3}\b", text):
        out.add(("telefon", re.sub(r"\D", "", p)[-9:]))
    for n in NAME.findall(text):
        if n.split()[0] not in FIRST:
            out.add(("jméno", fold(n)))
    for m in re.findall(r"\bIČO?:?\s*(\d{8})\b", text):
        out.add(("ičo", m))
    ft = fold(text)
    for k in known or []:
        if len(k) >= 3 and re.search(rf"\b{re.escape(fold(k))}\b", ft):
            out.add(("projekt", fold(k)))
    return out


def gather(rt) -> list[dict]:
    """Items from JARVIS's own stores: indexed documents, calendar, call notes, memory, lists, pinned tasks, chats."""
    db = rt.db
    have = {r["name"] for r in db.all("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    items: list[dict] = []

    def q(table, sql, fn):
        if table in have:
            for r in db.all(sql):
                items.append(fn(r))
    q("doc_idx", "SELECT path, MIN(loc) AS loc, group_concat(body, ' ') AS body FROM doc_idx GROUP BY path LIMIT 3000",
      lambda r: {"source": "dokument", "ref": r["path"], "label": Path(r["path"]).name, "text": (r["body"] or "")[:20000], "ts": 0})
    q("cal_events", "SELECT id, title, location, start FROM cal_events ORDER BY start DESC LIMIT 1000",
      lambda r: {"source": "kalendář", "ref": r["id"], "label": f"{r['title']} ({dt.datetime.fromtimestamp(r['start']).strftime('%d. %m. %Y %H:%M')})",
                 "text": f"{r['title']} {r['location'] or ''}", "ts": r["start"]})
    q("notes", "SELECT id, title, summary, transcript, created FROM notes ORDER BY created DESC LIMIT 500",
      lambda r: {"source": "hovor", "ref": r["id"], "label": r["title"] or "Hovor", "text": f"{r['title']} {r['summary'] or ''} {(r['transcript'] or '')[:8000]}", "ts": r["created"]})
    q("facts", "SELECT id, text, created FROM facts LIMIT 3000",
      lambda r: {"source": "paměť", "ref": str(r["id"]), "label": r["text"][:80], "text": r["text"], "ts": r["created"]})
    q("lists", "SELECT id, list, item, ts FROM lists LIMIT 3000",
      lambda r: {"source": "seznam", "ref": str(r["id"]), "label": f"{r['list']}: {r['item']}", "text": r["item"], "ts": r["ts"]})
    q("pins", "SELECT id, text, created FROM pins LIMIT 1000",
      lambda r: {"source": "připnuté", "ref": str(r["id"]), "label": r["text"], "text": r["text"], "ts": r["created"]})
    q("conversations", "SELECT c.id, c.title, c.updated, group_concat(m.content, ' ') AS body FROM conversations c JOIN messages m ON m.conv_id=c.id "
      "WHERE m.role='user' GROUP BY c.id ORDER BY c.updated DESC LIMIT 500",
      lambda r: {"source": "chat", "ref": r["id"], "label": r["title"], "text": (r["body"] or "")[:8000], "ts": r["updated"]})
    return items


def build_index(rt, items: list[dict] | None = None) -> dict:
    for s in LINKS_SQL:
        rt.db.exec(s)
    items = gather(rt) if items is None else items
    known = []
    try:
        known = [p["name"] for p in rt.knowledge.projects()] if hasattr(rt.knowledge, "projects") else []
    except Exception:  # noqa: BLE001
        known = []
    rt.db.exec("DELETE FROM sem_links")
    n = 0
    for it in items:
        for kind, val in entities(it.get("text", "") + " " + it.get("label", ""), known):
            rt.db.exec("INSERT INTO sem_links VALUES (?,?,?,?,?,?)", (val, kind, it["source"], it["ref"], it["label"][:200], it.get("ts") or 0))
            n += 1
    return {"items": len(items), "links": n, "entities": rt.db.one("SELECT COUNT(DISTINCT entity) AS n FROM sem_links")["n"]}


def related(rt, query: str, limit: int = 30) -> dict:
    """Everything that mentions the person / e-mail / project – grouped by where it lives – and what else is linked to it."""
    for s in LINKS_SQL:
        rt.db.exec(s)
    f = fold(query.strip())
    if not f:
        return {"entities": [], "items": {}, "linked": []}
    ents = [r["entity"] for r in rt.db.all("SELECT DISTINCT entity FROM sem_links WHERE entity LIKE ? LIMIT 10", (f"%{f}%",))]
    if not ents:
        return {"entities": [], "items": {}, "linked": []}
    marks = ",".join("?" * len(ents))
    rows = rt.db.all(f"SELECT DISTINCT source, ref, label, ts FROM sem_links WHERE entity IN ({marks}) ORDER BY ts DESC LIMIT ?", (*ents, limit))
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        by[r["source"]].append({"ref": r["ref"], "label": r["label"], "ts": r["ts"]})
    refs = [(r["source"], r["ref"]) for r in rows]
    co: Counter = Counter()
    for src, ref in refs:
        for r in rt.db.all("SELECT entity, kind FROM sem_links WHERE source=? AND ref=?", (src, ref)):
            if r["entity"] not in ents:
                co[(r["kind"], r["entity"])] += 1
    return {"entities": ents, "items": dict(by), "linked": [{"kind": k, "entity": e, "together": n} for (k, e), n in co.most_common(8)]}


# ---------------------------------------------------------------- 522 input mode
def input_profile(sig: dict) -> dict:
    """sig: touch_points, coarse, hover, last_input ('mouse'|'touch'|'pen'|'key'|'voice'), fullscreen, preference."""
    pref = sig.get("preference") or "auto"
    if pref != "auto":
        mode = pref
        why = "nastaveno ručně"
    elif sig.get("last_input") == "voice" and sig.get("fullscreen"):
        mode, why = "voice", "běží aplikace přes celou obrazovku a mluvíš"
    elif sig.get("last_input") in ("touch", "pen") or (sig.get("coarse") and not sig.get("hover")):
        mode, why = "touch", "ovládáš dotykem"
    else:
        mode, why = "mouse", "myš a klávesnice"
    return {"mode": mode, "why": why, "target_px": 48 if mode == "touch" else 40 if mode == "voice" else 32,
            "density": "comfortable" if mode == "touch" else "normal"}


# ---------------------------------------------------------------- 550 sources behind an answer
URL = re.compile(r"https?://[^\s\"'<>)\]]+")
SKIP_SOURCE = {"update_plan", "remember", "recall", "list_add", "notify", "speak"}


def sources_from(tool: str, args: dict, data: Any, summary: str = "") -> list[dict]:
    """What a tool result rests on: web pages, files, e-mails, calendar items, API endpoints."""
    if tool in SKIP_SOURCE:
        return []
    out: list[dict] = []

    def add(kind, ref, label=""):
        ref = str(ref).strip()
        if ref and not any(o["ref"] == ref for o in out):
            out.append({"kind": kind, "ref": ref[:500], "label": (label or ref)[:120], "tool": tool})

    for k in ("url", "link", "href"):
        if isinstance(args.get(k), str) and args[k].startswith("http"):
            add("web", args[k])
    for k in ("path", "file", "source", "folder"):
        v = args.get(k)
        if isinstance(v, str) and v and not v.startswith("http") and (("/" in v) or ("\\" in v) or "." in v):
            add("soubor", v, Path(v).name)

    def walk(x, depth=0):
        if depth > 3 or len(out) >= 10:
            return
        if isinstance(x, dict):
            if x.get("subject") and (x.get("from") or x.get("from_name")):
                add("e-mail", f"{x.get('from') or x.get('from_name')}: {x['subject']}", f"{x.get('from_name') or x.get('from')} – {x['subject']}")
            for k in ("url", "link", "href"):
                if isinstance(x.get(k), str) and x[k].startswith("http"):
                    add("web", x[k], x.get("title") or x.get("name") or "")
            for k in ("file", "path"):
                if isinstance(x.get(k), str) and x[k] and not x[k].startswith("http") and ("/" in x[k] or "\\" in x[k] or "." in x[k]):
                    add("soubor", x[k] + (f" ({x['loc']})" if x.get("loc") else ""), Path(x[k]).name + (f", {x['loc']}" if x.get("loc") else ""))
            for v in list(x.values())[:40]:
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(x, list):
            for v in x[:20]:
                walk(v, depth + 1)
    walk(data)
    if not out and tool.startswith(("web_", "search", "fetch", "browse", "read_page")):
        for u in URL.findall(summary)[:5]:
            add("web", u)
    return out[:10]
