"""Real checks behind the specialist agents: a read-only SQLite query (Database agent), an HTML accessibility audit
against WCAG basics (Accessibility agent) and a translation file check (Localization agent)."""
from __future__ import annotations

import json
import re
import sqlite3
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------------------------- 064 database
def sql_query(path: Path, query: str, limit: int = 200) -> dict:
    """Opens the database READ-ONLY (SQLite URI mode=ro); only SELECT / PRAGMA / EXPLAIN / WITH."""
    q = query.strip().rstrip(";")
    if not re.match(r"(?is)^(select|pragma|explain|with)\b", q) or ";" in q:
        raise ValueError("Jen čtení: SELECT, WITH, PRAGMA nebo EXPLAIN (jeden dotaz).")
    if re.search(r"(?i)\b(insert|update|delete|drop|alter|create|attach|replace|vacuum)\b", re.sub(r"'[^']*'", "", q)):
        raise ValueError("Dotaz obsahuje příkaz, který mění data – ten nespustím.")
    if not path.is_file():
        raise ValueError(f"Databáze neexistuje: {path}")
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        cur = con.execute(q)
        cols = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(limit)
    finally:
        con.close()
    return {"columns": cols, "rows": [list(r) for r in rows], "truncated": len(rows) == limit}


def sql_schema(path: Path) -> list[dict]:
    r = sql_query(path, "SELECT name, sql FROM sqlite_master WHERE type IN ('table','index') ORDER BY type, name", 1000)
    return [{"name": n, "sql": s} for n, s in r["rows"]]


# ---------------------------------------------------------------------------------------------- 067 accessibility
def _lum(hex_: str) -> float | None:
    h = hex_.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        return None
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(fg: str, bg: str) -> float | None:
    a, b = _lum(fg), _lum(bg)
    if a is None or b is None:
        return None
    hi, lo = max(a, b), min(a, b)
    return round((hi + 0.05) / (lo + 0.05), 2)


class _A11y(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.issues: list[dict] = []
        self.lang = False
        self.title = False
        self._in_title = False
        self.labels: set[str] = set()
        self.inputs: list[dict] = []
        self.headings: list[int] = []
        self._btn: list[dict] = []
        self._a: list[dict] = []
        self.line = 0

    def add(self, level: str, rule: str, text: str):
        self.issues.append({"level": level, "rule": rule, "text": text, "line": self.getpos()[0]})

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "html" and a.get("lang"):
            self.lang = True
        if tag == "title":
            self._in_title = True
        if tag == "img" and "alt" not in a and a.get("role") != "presentation" and a.get("aria-hidden") != "true":
            self.add("bad", "1.1.1", f"Obrázek bez popisku alt: {a.get('src', '')[:60]}")
        if tag == "label" and a.get("for"):
            self.labels.add(a["for"])
        if tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit", "button", "image", "reset"):
            self.inputs.append({"id": a.get("id", ""), "aria": bool(a.get("aria-label") or a.get("aria-labelledby") or a.get("title")),
                                "name": a.get("name") or a.get("id") or tag, "line": self.getpos()[0], "wrapped": False})
        if re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))
        if tag == "button":
            self._btn.append({"text": "", "aria": bool(a.get("aria-label") or a.get("title")), "line": self.getpos()[0]})
        if tag == "a" and "href" in a:
            self._a.append({"text": "", "aria": bool(a.get("aria-label")), "line": self.getpos()[0]})
        style = a.get("style", "")
        fg = re.search(r"(?<![-\w])color\s*:\s*(#[0-9a-fA-F]{3,6})", style)
        bg = re.search(r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,6})", style)
        if fg and bg:
            c = contrast(fg.group(1), bg.group(1))
            if c is not None and c < 4.5:
                self.add("bad" if c < 3 else "warn", "1.4.3", f"Nízký kontrast textu {fg.group(1)} na {bg.group(1)}: {c}:1 (potřeba 4.5:1)")
        if a.get("tabindex", "").lstrip("-").isdigit() and int(a["tabindex"]) > 0:
            self.add("warn", "2.4.3", f"tabindex={a['tabindex']} mění pořadí ovládání klávesnicí")
        if tag in ("div", "span") and a.get("onclick") and not a.get("role"):
            self.add("bad", "2.1.1", f"<{tag}> s onclick bez role a klávesnice – použij <button>")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "button" and self._btn:
            b = self._btn.pop()
            if not b["text"].strip() and not b["aria"]:
                self.issues.append({"level": "bad", "rule": "4.1.2", "text": "Tlačítko bez textu i aria-label", "line": b["line"]})
        if tag == "a" and self._a:
            x = self._a.pop()
            t = x["text"].strip().lower()
            if not t and not x["aria"]:
                self.issues.append({"level": "bad", "rule": "2.4.4", "text": "Odkaz bez textu", "line": x["line"]})
            elif t in ("klikni zde", "zde", "tady", "click here", "here", "více", "more", "odkaz"):
                self.issues.append({"level": "warn", "rule": "2.4.4", "text": f"Odkaz „{t}“ neříká, kam vede", "line": x["line"]})

    def handle_data(self, data):
        if self._in_title and data.strip():
            self.title = True
        for b in self._btn:
            b["text"] += data
        for x in self._a:
            x["text"] += data


def a11y_audit(html: str) -> dict:
    p = _A11y()
    p.feed(html)
    p.close()
    if not p.lang:
        p.issues.append({"level": "bad", "rule": "3.1.1", "text": "Chybí jazyk stránky (<html lang=\"cs\">)", "line": 1})
    if not p.title:
        p.issues.append({"level": "warn", "rule": "2.4.2", "text": "Stránka nemá <title>", "line": 1})
    for i in p.inputs:
        if not i["aria"] and not (i["id"] and i["id"] in p.labels):
            p.issues.append({"level": "bad", "rule": "1.3.1", "text": f"Pole „{i['name']}“ nemá popisek (label/aria-label)", "line": i["line"]})
    if p.headings and p.headings[0] != 1:
        p.issues.append({"level": "warn", "rule": "1.3.1", "text": "Stránka nezačíná nadpisem h1", "line": 1})
    for a, b in zip(p.headings, p.headings[1:]):
        if b > a + 1:
            p.issues.append({"level": "warn", "rule": "1.3.1", "text": f"Přeskočená úroveň nadpisu (h{a} → h{b})", "line": 1})
            break
    order = {"bad": 0, "warn": 1}
    issues = sorted(p.issues, key=lambda x: (order.get(x["level"], 2), x["line"]))
    score = max(0, 100 - 12 * sum(1 for x in issues if x["level"] == "bad") - 4 * sum(1 for x in issues if x["level"] == "warn"))
    return {"issues": issues, "score": score}


# ---------------------------------------------------------------------------------------------- 068 translations
PH = re.compile(r"\{[\w.]*\}|%\(?\w*\)?[sdif]|%\d\$[sd]|\$\{\w+\}|\{\{\s*\w+\s*\}\}")


def load_strings(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8-sig")
    ext = path.suffix.lower()
    if ext == ".json":
        def flat(d: Any, pre: str = "") -> dict[str, str]:
            out: dict[str, str] = {}
            for k, v in d.items():
                key = f"{pre}.{k}" if pre else str(k)
                if isinstance(v, dict):
                    out.update(flat(v, key))
                else:
                    out[key] = str(v)
            return out
        return flat(json.loads(text))
    if ext == ".po":
        out, msgid = {}, None
        for m in re.finditer(r'^(msgid|msgstr)\s+"(.*)"\s*$', text, re.M):
            if m.group(1) == "msgid":
                msgid = m.group(2)
            elif msgid:
                out[msgid] = m.group(2)
        return out
    if ext == ".properties":
        return {k.strip(): v.strip() for k, _, v in (ln.partition("=") for ln in text.splitlines()) if k.strip() and not k.lstrip().startswith("#")}
    raise ValueError("Umím JSON, .po a .properties.")


def check_translation(src: Path, dst: Path) -> dict:
    a, b = load_strings(src), load_strings(dst)
    missing = sorted(k for k in a if k not in b or not b[k].strip())
    extra = sorted(k for k in b if k not in a)
    ph = sorted(k for k in a if k in b and b[k].strip() and sorted(PH.findall(a[k])) != sorted(PH.findall(b[k])))
    same = sorted(k for k in a if k in b and b[k] == a[k] and len(a[k]) > 3 and re.search(r"[A-Za-z]{4}", a[k]))
    return {"keys": len(a), "missing": missing, "extra": extra, "placeholders": ph, "untranslated": same,
            "ok": not missing and not ph}
