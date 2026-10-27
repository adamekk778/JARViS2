"""OMEGA wave 42: whether recurring meetings are worth it (564) and how they go (567), one folder per meeting with its
documents (569), programming exercises checked by hidden tests (458), learning through a project with milestones (465)
and a private status page for a client (448)."""
from __future__ import annotations

import datetime as dt
import html
import json
import random
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import paths
from .comms import fold


# ---------------------------------------------------------------- 564 / 567 recurring meetings
def series_key(title: str) -> str:
    """'Porada týmu #12 (říjen)' and 'Porada týmu – 3. 11.' → the same series."""
    t = fold(title)
    t = re.sub(r"\(.*?\)|#\s*\d+|\b\d{1,2}\.\s?\d{1,2}\.?(\s?\d{4})?|\b\d+\b", " ", t)
    return " ".join(w for w in re.findall(r"[a-z]+", t) if len(w) > 1)


def _json_list(v: Any) -> list:
    if isinstance(v, list):
        return v
    try:
        x = json.loads(v or "[]")
        return x if isinstance(x, list) else []
    except (TypeError, ValueError):
        return []


def meeting_series(events: list[dict], notes: list[dict], now: float | None = None, min_count: int = 3) -> list[dict]:
    """events: cal_events rows; notes: recorded calls (created, seconds, points, todos, transcript). A note belongs to an
    event when it was recorded inside it (±10 min). Per series: how often, hours a month, how many produced decisions or
    tasks, overruns, who talks – and a verdict."""
    now = now or time.time()
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        k = series_key(e.get("title", ""))
        if k:
            groups[k].append(e)
    out = []
    for k, evs in groups.items():
        if len(evs) < min_count:
            continue
        evs.sort(key=lambda e: e["start"])
        past = [e for e in evs if e["start"] <= now]
        span_days = max(1.0, (evs[-1]["start"] - evs[0]["start"]) / 86400)
        per_month = len(evs) / span_days * 30
        minutes = sum((e["end"] - e["start"]) / 60 for e in evs) / len(evs)
        rows = []
        for e in past:
            n = next((n for n in notes if e["start"] - 600 <= n["created"] <= e["end"] + 600), None)
            todos = _json_list(n.get("todos")) if n else []
            points = _json_list(n.get("points")) if n else []
            over = round((n["seconds"] / 60) - (e["end"] - e["start"]) / 60, 1) if n and n.get("seconds") else None
            speakers = defaultdict(int)
            for line in (n.get("transcript") or "").splitlines() if n else []:
                m = re.match(r"^([^:]{1,20}):\s*(.+)$", line)
                if m:
                    speakers[m.group(1).strip()] += len(m.group(2).split())
            rows.append({"start": e["start"], "recorded": bool(n), "todos": len(todos), "points": len(points), "overrun_min": over,
                         "speakers": dict(speakers)})
        rec = [r for r in rows if r["recorded"]]
        useful = [r for r in rec if r["todos"] or r["points"] >= 3]
        trend = None
        if len(rec) >= 4:
            half = len(rec) // 2
            a = sum(r["todos"] for r in rec[:half]) / half
            b = sum(r["todos"] for r in rec[half:]) / (len(rec) - half)
            trend = "méně výstupů" if b < a * 0.6 else "víc výstupů" if b > a * 1.4 else "stejně"
        overruns = [r["overrun_min"] for r in rec if r["overrun_min"] is not None]
        talk: dict[str, int] = defaultdict(int)
        for r in rec:
            for s, w in r["speakers"].items():
                talk[s] += w
        tot = sum(talk.values()) or 1
        share = {s: round(w / tot * 100) for s, w in sorted(talk.items(), key=lambda x: -x[1])}
        hours_month = round(per_month * minutes / 60, 1)
        if not rec:
            verdict, why = "nevím", "žádná z nich nebyla zaznamenaná"
        elif len(useful) / len(rec) < 0.34:
            verdict, why = "zrušit nebo nahradit e-mailem", f"jen {len(useful)} z {len(rec)} přinesla úkoly nebo rozhodnutí"
        elif overruns and sum(overruns) / len(overruns) < -minutes * 0.3:
            verdict, why = "zkrátit", f"obvykle končí o {abs(round(sum(overruns) / len(overruns)))} min dřív"
        elif len(useful) / len(rec) < 0.67 or trend == "méně výstupů":
            verdict, why = "zředit (např. jednou za 2 týdny)", "výstupy ubývají" if trend == "méně výstupů" else "přínosná jen část schůzek"
        else:
            verdict, why = "nechat", f"{len(useful)} z {len(rec)} přinesly úkoly nebo rozhodnutí"
        out.append({"series": k, "title": evs[-1]["title"], "count": len(evs), "per_month": round(per_month, 1), "minutes": round(minutes),
                    "hours_month": hours_month, "recorded": len(rec), "useful": len(useful), "trend": trend,
                    "avg_overrun_min": round(sum(overruns) / len(overruns), 1) if overruns else None, "talk_share": share,
                    "verdict": verdict, "why": why})
    return sorted(out, key=lambda s: -s["hours_month"])


# ---------------------------------------------------------------- 569 meeting folder
def meeting_folder(title: str, start: float, note: dict | None, related: list[Path], dest_root: Path, copy_max_mb: float = 25) -> dict:
    """A folder '2026-11-03 Porada' with the notes (summary, points, tasks, transcript) and copies of the related files."""
    clean = re.sub(r"[^\w ,.-]", "", title).strip()[:60] or "Schůzka"
    name = f"{dt.datetime.fromtimestamp(start).strftime('%Y-%m-%d')} {clean}"
    d = dest_root / name
    d.mkdir(parents=True, exist_ok=True)
    md = [f"# {title}", "", f"Kdy: {dt.datetime.fromtimestamp(start).strftime('%d. %m. %Y %H:%M')}", ""]
    if note:
        md += ["## Shrnutí", note.get("summary") or "–", "", "## Hlavní body"] + [f"- {p}" for p in _json_list(note.get("points"))]
        md += ["", "## Úkoly"] + [f"- [ ] {t if isinstance(t, str) else t.get('text', t)}" for t in _json_list(note.get("todos"))]
        if note.get("transcript"):
            (d / "prepis.txt").write_text(note["transcript"], encoding="utf-8")
            md += ["", "Přepis: prepis.txt"]
    copied, linked = [], []
    for p in related:
        if not p.is_file():
            continue
        if p.stat().st_size <= copy_max_mb * 2**20:
            target = d / p.name
            if target.exists() and target.read_bytes() != p.read_bytes():
                target = d / f"{p.stem}-{len(copied)}{p.suffix}"
            shutil.copy2(p, target)
            copied.append(target.name)
        else:
            linked.append(str(p))
    if copied or linked:
        md += ["", "## Dokumenty"] + [f"- {c}" for c in copied] + [f"- (velký, jen odkaz) {x}" for x in linked]
    (d / "schuzka.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return {"folder": str(d), "copied": copied, "linked": linked}


def files_around(roots: list[Path], start: float, end: float, margin_s: float = 3600, limit: int = 30) -> list[Path]:
    """Files created or saved shortly before / during / after the meeting (agenda, presentation, minutes)."""
    out = []
    for r in roots:
        if not r.is_dir():
            continue
        for p in r.rglob("*"):
            try:
                if p.is_file() and not p.name.startswith(("~$", ".")) and start - margin_s <= p.stat().st_mtime <= end + margin_s:
                    out.append(p)
            except OSError:
                continue
            if len(out) >= limit:
                return out
    return out


# ---------------------------------------------------------------- 458 programming exercises
def _ex_sum_even(rng):
    return {"title": "Součet sudých", "task": "Napiš funkci solve(cisla), která vrátí součet sudých čísel v seznamu.",
            "cases": [[[rng.randint(-20, 40) for _ in range(rng.randint(0, 8))]] for _ in range(6)] + [[[]]],
            "ref": lambda c: sum(x for x in c if x % 2 == 0), "level": 1}


def _ex_count_vowels(rng):
    words = ["kočka", "Python", "AEIOU", "", "rytmus", "Příliš žluťoučký kůň", "programování"]
    return {"title": "Počet samohlásek", "task": "Napiš solve(text), která spočítá samohlásky (a e i o u y, i s diakritikou, malá i velká).",
            "cases": [[w] for w in rng.sample(words, 5)] + [[""]],
            "ref": lambda t: sum(1 for ch in fold(t) if ch in "aeiouy"), "level": 1}


def _ex_fizz(rng):
    a, b = rng.choice([(3, 5), (2, 7), (4, 6)])
    return {"title": "FizzBuzz po svém", "task": f"Napiš solve(n), která vrátí seznam 1..n, kde násobky {a} nahradí 'Fizz', násobky {b} 'Buzz' a obou 'FizzBuzz'.",
            "cases": [[n] for n in (1, a, b, a * b, 20)],
            "ref": lambda n: ["FizzBuzz" if i % a == 0 and i % b == 0 else "Fizz" if i % a == 0 else "Buzz" if i % b == 0 else i for i in range(1, n + 1)],
            "level": 1}


def _ex_palindrome(rng):
    return {"title": "Palindrom", "task": "Napiš solve(text), která vrátí True, když se text čte stejně pozpátku (bez mezer, interpunkce, diakritiky a velikosti písmen).",
            "cases": [["Kobyla má malý bok."], ["Python"], [""], ["A man, a plan, a canal: Panama"], ["Jelenovi pivo nelej"]],
            "ref": lambda t: (lambda s: s == s[::-1])(re.sub(r"[^a-z0-9]", "", fold(t))), "level": 2}


def _ex_reverse_words(rng):
    return {"title": "Obrácená slova", "task": "Napiš solve(veta), která vrátí slova věty v obráceném pořadí, oddělená jednou mezerou.",
            "cases": [["ahoj světe"], ["  víc   mezer  tady "], ["jedno"], [""]],
            "ref": lambda s: " ".join(reversed(s.split())), "level": 1}


def _ex_max_subarray(rng):
    return {"title": "Nejlepší úsek", "task": "Napiš solve(cisla), která vrátí největší součet souvislého úseku (aspoň jeden prvek; prázdný seznam → 0).",
            "cases": [[[rng.randint(-10, 10) for _ in range(rng.randint(1, 10))]] for _ in range(5)] + [[[-3, -1, -2]], [[]]],
            "ref": lambda c: (max(_kadane(c)) if c else 0), "level": 3}


def _kadane(c):
    best, cur = [], 0
    for i, x in enumerate(c):
        cur = x if i == 0 else max(x, cur + x)
        best.append(cur)
    return best


def _ex_anagram(rng):
    return {"title": "Přesmyčky", "task": "Napiš solve(a, b), která vrátí True, když jsou slova přesmyčky (bez ohledu na velikost písmen a mezery).",
            "cases": [["Listen", "Silent"], ["kos", "sok"], ["abc", "abd"], ["a b", "ba"], ["", ""]],
            "ref": lambda a, b: sorted(fold(a).replace(" ", "")) == sorted(fold(b).replace(" ", "")), "level": 2}


def _ex_dedupe(rng):
    return {"title": "Bez duplicit", "task": "Napiš solve(seznam), která odstraní opakující se prvky a zachová pořadí prvního výskytu.",
            "cases": [[[rng.randint(1, 5) for _ in range(rng.randint(0, 10))]] for _ in range(5)],
            "ref": lambda s: list(dict.fromkeys(s)), "level": 1}


def _ex_roman(rng):
    def roman(n):
        out = ""
        for v, s in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
            while n >= v:
                out, n = out + s, n - v
        return out
    return {"title": "Římská čísla", "task": "Napiš solve(n) pro 1–3999, která vrátí číslo římsky (např. 1994 → 'MCMXCIV').",
            "cases": [[n] for n in (1, 4, 9, 14, 40, 1994, rng.randint(100, 3999))], "ref": roman, "level": 2}


def _ex_word_freq(rng):
    return {"title": "Nejčastější slovo", "task": "Napiš solve(text), která vrátí nejčastější slovo (malými písmeny); při shodě to, které je dřív v textu.",
            "cases": [["pes kočka pes"], ["A a b B b"], ["jedno"], ["Ahoj, ahoj! Čau."]],
            "ref": lambda t: (lambda ws: max(ws, key=lambda w: (ws.count(w), -ws.index(w))) if ws else "")(re.findall(r"\w+", t.lower())), "level": 2}


EXERCISES = {"soucet_sudych": _ex_sum_even, "samohlasky": _ex_count_vowels, "fizzbuzz": _ex_fizz, "palindrom": _ex_palindrome,
             "obracena_slova": _ex_reverse_words, "nejlepsi_usek": _ex_max_subarray, "presmycky": _ex_anagram, "bez_duplicit": _ex_dedupe,
             "rimska_cisla": _ex_roman, "nejcastejsi_slovo": _ex_word_freq}


def make_exercise(key: str = "", level: int = 0, seed: int | None = None) -> dict:
    rng = random.Random(seed)
    keys = [k for k, f in EXERCISES.items() if not level or f(random.Random(0))["level"] == level] or list(EXERCISES)
    key = key if key in EXERCISES else rng.choice(sorted(keys))
    ex = EXERCISES[key](rng)
    tests = [{"args": c, "expected": ex["ref"](*c)} for c in ex["cases"]]
    return {"id": key, "title": ex["title"], "task": ex["task"], "level": ex["level"], "examples": tests[:2], "tests": tests,
            "starter": "def solve(" + ", ".join(f"arg{i + 1}" for i in range(len(ex["cases"][0]))) + "):\n    # tvůj kód\n    pass\n"}


RUNNER = r'''
import json, sys
ns = {}
src = open(sys.argv[1], encoding="utf-8").read()
exec(compile(src, "reseni.py", "exec"), ns)
out = []
for t in json.load(open(sys.argv[2], encoding="utf-8")):
    try:
        got = ns["solve"](*t["args"])
        out.append({"ok": got == t["expected"], "got": repr(got)[:200]})
    except Exception as e:
        out.append({"ok": False, "got": type(e).__name__ + ": " + str(e)[:150]})
print(json.dumps(out))
'''


def check_solution(code: str, tests: list[dict], timeout: float = 10) -> dict:
    """Runs the user's own solution in a separate, isolated Python process with a time limit."""
    with tempfile.TemporaryDirectory(prefix="jarvis-cviceni-") as tmp:
        t = Path(tmp)
        (t / "reseni.py").write_text(code, encoding="utf-8")
        (t / "tests.json").write_text(json.dumps(tests, ensure_ascii=False), encoding="utf-8")
        (t / "runner.py").write_text(RUNNER, encoding="utf-8")
        try:
            p = subprocess.run([sys.executable, "-I", str(t / "runner.py"), str(t / "reseni.py"), str(t / "tests.json")], cwd=tmp,
                               capture_output=True, text=True, timeout=timeout, creationflags=0x08000000 if sys.platform == "win32" else 0)
        except subprocess.TimeoutExpired:
            return {"ok": False, "passed": 0, "total": len(tests), "error": f"Řešení běží déle než {timeout:g} s (nekonečná smyčka?)."}
        if p.returncode != 0 or not p.stdout.strip():
            err = (p.stderr or "").strip().splitlines()
            return {"ok": False, "passed": 0, "total": len(tests), "error": err[-1] if err else "Řešení nejde spustit."}
        res = json.loads(p.stdout.strip().splitlines()[-1])
    fails = [{"args": tests[i]["args"], "expected": tests[i]["expected"], "got": r["got"]} for i, r in enumerate(res) if not r["ok"]]
    return {"ok": not fails, "passed": len(res) - len(fails), "total": len(res), "fails": fails[:3]}


# ---------------------------------------------------------------- 465 learning through a project
PROJECTS = {
    "web": {"title": "Vlastní webová stránka", "match": ("web", "html", "stránk", "css"),
            "milestones": [("Kostra stránky v HTML", ["HTML", "nadpisy a odstavce", "odkazy"], "Stránka s nadpisem, odstavcem a odkazem se otevře v prohlížeči."),
                           ("Vzhled v CSS", ["CSS", "barvy a písmo", "box model"], "Stránka má vlastní barvy, písmo a odsazení."),
                           ("Rozložení pro mobil", ["flexbox", "media queries"], "Na úzkém okně se sloupce složí pod sebe."),
                           ("Formulář", ["formuláře", "validace"], "Formulář nejde odeslat bez e-mailu."),
                           ("Zveřejnění", ["hosting", "doména"], "Stránka je dostupná na veřejné adrese.")]},
    "python": {"title": "Pomocník v Pythonu", "match": ("python", "program", "skript", "bot"),
               "milestones": [("První skript", ["proměnné", "print", "input"], "Skript se zeptá na jméno a pozdraví."),
                              ("Rozhodování a cykly", ["if", "for", "while"], "Skript vypíše násobilku zadaného čísla."),
                              ("Funkce a soubory", ["funkce", "práce se soubory"], "Skript uloží seznam úkolů do souboru a zase ho načte."),
                              ("Knihovny", ["pip", "requests"], "Skript stáhne počasí z veřejného API."),
                              ("Hotový nástroj", ["argumenty", "chyby a výjimky"], "Nástroj jde spustit s parametry a nespadne na špatném vstupu.")]},
    "arduino": {"title": "Chytrý senzor s Arduinem", "match": ("arduino", "elektron", "senzor", "esp"),
                "milestones": [("Blikající LED", ["digitální výstup", "rezistor k LED"], "LED bliká v nastaveném rytmu."),
                               ("Tlačítko", ["digitální vstup", "pull-up"], "Tlačítko přepíná LED."),
                               ("Senzor", ["analogový vstup", "sériový monitor"], "Hodnoty ze senzoru se vypisují do sériového monitoru."),
                               ("Displej nebo bzučák", ["I2C", "knihovny"], "Při překročení meze se ozve bzučák / ukáže hláška."),
                               ("Krabička a napájení", ["napájení z baterie", "spotřeba"], "Zařízení běží z baterie aspoň den.")]},
    "data": {"title": "Analýza dat v Excelu", "match": ("excel", "data", "tabul", "analýz", "analyz"),
             "milestones": [("Čistá data", ["typy dat", "odstranění duplicit"], "Tabulka nemá duplicity ani prázdné řádky."),
                            ("Vzorce", ["SUMIF", "XLOOKUP"], "Součty po kategoriích sedí s ruční kontrolou."),
                            ("Kontingenční tabulka", ["kontingenční tabulka", "filtry"], "Přehled po měsících a kategoriích."),
                            ("Grafy", ["volba grafu", "popisky"], "Graf vývoje v čase s popsanými osami."),
                            ("Závěry", ["interpretace", "prezentace"], "Tři věty, co z dat plyne, s čísly.")]},
    "hra": {"title": "Malá hra v Godotu", "match": ("hra", "godot", "game", "hry"),
            "milestones": [("Postava se hýbe", ["scény a uzly", "vstup z klávesnice"], "Postava jde šipkami do stran a skáče."),
                           ("Úroveň", ["TileMap", "kolize"], "Postava stojí na plošinách a nepropadne."),
                           ("Sbírání a skóre", ["signály", "UI"], "Sebrané mince zvyšují skóre na obrazovce."),
                           ("Nepřítel", ["jednoduchá AI", "životy"], "Nepřítel chodí sem a tam a ubírá život."),
                           ("Hotová hra", ["menu", "export"], "Hra má menu, konec a jde spustit jako .exe.")]},
}
LP_SQL = ("CREATE TABLE IF NOT EXISTS learn_projects (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, goal TEXT, started REAL, "
          "milestones TEXT, done TEXT, finished REAL)")


def pick_project(goal: str) -> str:
    g = fold(goal)
    for k, p in PROJECTS.items():
        if any(fold(m) in g for m in p["match"]):
            return k
    return "python"


def start_learning_project(rt, goal: str, kind: str = "", deck: bool = True) -> dict:
    rt.db.exec(LP_SQL)
    kind = kind if kind in PROJECTS else pick_project(goal)
    ms = [{"n": i + 1, "title": t, "concepts": c, "check": chk} for i, (t, c, chk) in enumerate(PROJECTS[kind]["milestones"])]
    cur = rt.db.exec("INSERT INTO learn_projects (kind, goal, started, milestones, done) VALUES (?,?,?,?,?)",
                     (kind, goal, time.time(), json.dumps(ms, ensure_ascii=False), "[]"))
    if deck and hasattr(rt, "learning"):
        for m in ms:
            for c in m["concepts"]:
                rt.learning.add_card(f"Projekt: {PROJECTS[kind]['title']}", f"Co je / k čemu slouží: {c}?", f"(doplň vlastními slovy – krok {m['n']}: {m['title']})", c)
    return learning_project(rt, cur.lastrowid)


def learning_project(rt, pid: int | None = None) -> dict | None:
    rt.db.exec(LP_SQL)
    r = rt.db.one("SELECT * FROM learn_projects WHERE id=?" if pid else "SELECT * FROM learn_projects WHERE finished IS NULL ORDER BY id DESC LIMIT 1",
                  (pid,) if pid else ())
    if not r:
        return None
    ms, done = json.loads(r["milestones"]), set(json.loads(r["done"]))
    nxt = next((m for m in ms if m["n"] not in done), None)
    return {"id": r["id"], "kind": r["kind"], "title": PROJECTS.get(r["kind"], {}).get("title", r["kind"]), "goal": r["goal"], "milestones": ms,
            "done": sorted(done), "next": nxt, "progress": round(len(done) / len(ms) * 100), "finished": bool(r["finished"])}


def complete_milestone(rt, pid: int, n: int) -> dict:
    p = learning_project(rt, pid)
    if not p:
        raise KeyError("Takový projekt nemám.")
    if not any(m["n"] == n for m in p["milestones"]):
        raise ValueError(f"Krok {n} v projektu není.")
    done = sorted(set(p["done"]) | {n})
    fin = time.time() if len(done) == len(p["milestones"]) else None
    rt.db.exec("UPDATE learn_projects SET done=?, finished=? WHERE id=?", (json.dumps(done), fin, pid))
    return learning_project(rt, pid)


# ---------------------------------------------------------------- 448 client portal
def portal_html(client: str, quotes: list[dict], requests: list[dict], company: str = "", note: str = "", now: float | None = None) -> str:
    """A static, self-contained page the client can open: their quotes and the state of their requests. No scripts."""
    now = now or time.time()
    e = html.escape
    cls = {"přijatá": "ok", "vyřízený": "ok", "odmítnutá": "bad", "propadlá": "bad", "čeká na vás": "wait"}

    def money(v):
        return f"{v:,.0f} Kč".replace(",", " ") if isinstance(v, (int, float)) else "–"
    qrows = "".join(f"<tr><td>{e(q.get('number') or '')}</td><td>{dt.date.fromtimestamp(q['created']).strftime('%d. %m. %Y') if q.get('created') else ''}</td>"
                    f"<td class=n>{money(q.get('total'))}</td><td>{e(q.get('valid_until') or '')}</td><td><span class='s {cls.get(q.get('status') or '', '')}'>{e(q.get('status') or '')}</span></td></tr>"
                    for q in quotes) or "<tr><td colspan=5>Zatím žádné nabídky.</td></tr>"
    rrows = "".join(f"<tr><td>{e((r.get('text') or '')[:160])}</td><td>{dt.date.fromtimestamp(r['created']).strftime('%d. %m. %Y') if r.get('created') else ''}</td>"
                    f"<td>{e(r.get('due') or '')}</td><td><span class='s {cls.get(r.get('status') or '', '')}'>{e('vyřízeno' if r.get('status') == 'vyřízený' else 'řeší se' if r.get('status') in (None, '', 'nový', 'otevřený') else r.get('status'))}</span></td></tr>"
                    for r in requests) or "<tr><td colspan=4>Žádné požadavky.</td></tr>"
    open_n = sum(1 for r in requests if r.get("status") != "vyřízený")
    return f"""<!doctype html><html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{e(client)} – přehled</title><style>
:root{{color-scheme:light dark;--b:#e5e7eb;--a:#2563eb}}body{{font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:0 auto;padding:24px 16px}}
h1{{font-size:24px;margin:0 0 4px}}.sub{{opacity:.7;margin:0 0 24px}}table{{width:100%;border-collapse:collapse;margin:8px 0 28px}}
th,td{{text-align:left;padding:8px;border-bottom:1px solid var(--b)}}td.n{{text-align:right;font-variant-numeric:tabular-nums}}
.s{{padding:2px 8px;border-radius:99px;background:rgba(127,127,127,.15);font-size:13px}}.ok{{background:rgba(22,163,74,.18)}}
.bad{{background:rgba(220,38,38,.15)}}.wait{{background:rgba(234,179,8,.2)}}.card{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:20px}}
.card div{{border:1px solid var(--b);border-radius:12px;padding:12px 16px}}.card b{{display:block;font-size:22px}}footer{{opacity:.6;font-size:13px}}
</style></head><body><h1>{e(client)}</h1><p class="sub">{e(company) + ' · ' if company else ''}Aktualizováno {dt.datetime.fromtimestamp(now).strftime('%d. %m. %Y %H:%M')}</p>
<div class="card"><div><b>{len(quotes)}</b>nabídek</div><div><b>{open_n}</b>otevřených požadavků</div></div>
{f'<p>{e(note)}</p>' if note else ''}<h2>Nabídky</h2><table><tr><th>Číslo</th><th>Vystaveno</th><th>Celkem</th><th>Platí do</th><th>Stav</th></tr>{qrows}</table>
<h2>Požadavky</h2><table><tr><th>Co</th><th>Zadáno</th><th>Termín</th><th>Stav</th></tr>{rrows}</table>
<footer>Tato stránka je jen pro vás – adresu nesdílejte.</footer></body></html>"""


def portal_id(client: str, existing: list[str]) -> str:
    from .tools.sites import slugify

    base = "portal-" + slugify(client)[:30]
    for e in existing:
        if e.startswith(base + "-") and re.fullmatch(re.escape(base) + r"-[0-9a-f]{10}", e):
            return e                                     # keep the same address on refresh
    return f"{base}-{secrets.token_hex(5)}"


def write_portal(client: str, page: str, sites_root: Path) -> dict:
    existing = [d.name for d in sites_root.iterdir() if d.is_dir()] if sites_root.is_dir() else []
    sid = portal_id(client, existing)
    d = sites_root / sid
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(page, encoding="utf-8")
    return {"id": sid, "path": str(d / "index.html")}


def _default_roots() -> list[Path]:
    h = Path.home()
    return [h / "Documents", h / "Downloads", h / "Desktop", paths.data_dir() / "files"]
