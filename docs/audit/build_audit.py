"""Builds docs/FEATURE_AUDIT.md and docs/FEATURE_MATRIX.md from the spec (OMEGA_SPEC.md) and audit/status.txt +
audit/original.txt. Run after changing a status:  python docs/audit/build_audit.py"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
STATES = ["HOTOVO", "ČÁSTEČNĚ", "ROZBITÉ", "VYŽADUJE_INTEGRACI", "BLOKOVÁNO_PLATFORMOU", "PLÁNOVÁNO", "CHYBÍ"]
ICON = {"HOTOVO": "✅", "ČÁSTEČNĚ": "🟡", "ROZBITÉ": "🔴", "VYŽADUJE_INTEGRACI": "🔌", "BLOKOVÁNO_PLATFORMOU": "⛔",
        "PLÁNOVÁNO": "🗓️", "CHYBÍ": "⬜"}


def catalog() -> tuple[list[tuple[str, list[tuple[int, str]]]], dict[int, str]]:
    text = (DOCS / "OMEGA_SPEC.md").read_text(encoding="utf-8")
    sections: list[tuple[str, list[tuple[int, str]]]] = []
    names: dict[int, str] = {}
    for line in text.splitlines():
        m = re.match(r"^### (\d\d)\. (.+)", line)
        if m:
            sections.append((f"{m.group(1)}. {m.group(2)}", []))
            continue
        m = re.match(r"^(\d{3})\. (.+)", line)
        if m and sections:
            n = int(m.group(1))
            name = m.group(2).replace("**", "").strip()
            sections[-1][1].append((n, name))
            names[n] = name
    return sections, names


def statuses() -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    for line in (DOCS / "audit" / "status.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        ids, st, ev = (x.strip() for x in line.split("|", 2))
        assert st in STATES, f"neznámý stav {st!r} v řádku: {line}"
        a, _, b = ids.partition("-")
        for n in range(int(a), int(b or a) + 1):
            out[n] = (st, ev)
    return out


def original() -> list[dict]:
    out = []
    for line in (DOCS / "audit" / "original.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        pid, st, ev, links, name = (x.strip() for x in line.split("|", 4))
        assert st in STATES, line
        out.append({"id": pid, "status": st, "evidence": ev, "links": links, "name": name})
    return out


def main() -> None:
    sections, names = catalog()
    st = statuses()
    orig = original()
    assert len(names) == 795, f"katalog má {len(names)} položek, čekáno 795"
    total = Counter(st.get(n, ("CHYBÍ", ""))[0] for n in names)
    ototal = Counter(o["status"] for o in orig)

    a = ["# FEATURE AUDIT – JARVIS OMEGA ∞", "",
         "Stav každé schopnosti ze zadání (docs/OMEGA_SPEC.md): katalog 001–795 a původní seznam 110+ schopností.",
         "Generováno skriptem `docs/audit/build_audit.py` z `docs/audit/status.txt` a `docs/audit/original.txt` – "
         "**neupravuj ručně**, uprav zdrojové soubory a spusť skript.", "",
         "Stavy: " + " · ".join(f"{ICON[s]} {s}" for s in STATES) + ". Co není výslovně ověřeno, je vedeno jako CHYBÍ.", "",
         "## Souhrn", "", "| Stav | Katalog 001–795 | Původní seznam |", "|---|---:|---:|"]
    for s in STATES:
        a.append(f"| {ICON[s]} {s} | {total.get(s, 0)} | {ototal.get(s, 0)} |")
    a += [f"| **Celkem** | **{sum(total.values())}** | **{len(orig)}** |", "",
          "Pozn.: položky se překrývají (viz FEATURE_MATRIX.md), součty nejsou počtem unikátních modulů.", ""]
    for title, items in sections:
        c = Counter(st.get(n, ("CHYBÍ", ""))[0] for n, _ in items)
        a += [f"## {title}", "", " · ".join(f"{ICON[s]} {c[s]}" for s in STATES if c.get(s)), "",
              "| ID | Funkce | Stav | Důkaz / modul / omezení |", "|---|---|---|---|"]
        for n, name in items:
            s, ev = st.get(n, ("CHYBÍ", ""))
            a.append(f"| {n:03d} | {name} | {ICON[s]} {s} | {ev or '—'} |")
        a.append("")
    a += ["## Původní seznam 110+ schopností", "", "| ID | Schopnost | Stav | Důkaz / modul | Překryv s katalogem |", "|---|---|---|---|---|"]
    for o in orig:
        a.append(f"| {o['id']} | {o['name']} | {ICON[o['status']]} {o['status']} | {o['evidence']} | {o['links']} |")
    (DOCS / "FEATURE_AUDIT.md").write_text("\n".join(a) + "\n", encoding="utf-8")

    # ---------- matrix: which shared module carries which features ----------
    mods: dict[str, list[str]] = defaultdict(list)
    pat = re.compile(r"([a-z_/]+\.(?:py|ts|java)|[a-z_]+_[a-z_]+|STOP|Home Assistant|Claude Code|UI Automation|computer_use)")
    for n in sorted(names):
        s, ev = st.get(n, ("CHYBÍ", ""))
        if s in ("HOTOVO", "ČÁSTEČNĚ", "VYŽADUJE_INTEGRACI"):
            for key in dict.fromkeys(pat.findall(ev)):
                mods[key].append(f"{n:03d}")
    for o in orig:
        if o["status"] in ("HOTOVO", "ČÁSTEČNĚ", "VYŽADUJE_INTEGRACI"):
            for key in dict.fromkeys(pat.findall(o["evidence"])):
                mods[key].append(o["id"])
    m = ["# FEATURE MATRIX – funkce → sdílené jádro", "",
         "Které existující moduly/nástroje nesou které funkce. Jedna schopnost = jedna implementace; překrývající se "
         "položky katalogu i původního seznamu ukazují na stejný modul (žádné duplikáty: jeden plánovač `scheduler.py`, "
         "jedna paměť `memory.py`, jeden systém oprávnění `permissions.py`, jedny mise `tasks.py`, jedna postavička "
         "`character/blob.ts`). Generováno `docs/audit/build_audit.py`.", "",
         "| Modul / nástroj | Funkce (ID) |", "|---|---|"]
    for key in sorted(mods, key=lambda k: (-len(mods[k]), k)):
        m.append(f"| `{key}` | {', '.join(mods[key])} |")
    m += ["", "## Překryvy původního seznamu s katalogem", "", "| Původní | Katalog | Schopnost |", "|---|---|---|"]
    for o in orig:
        if o["links"] not in ("—", ""):
            m.append(f"| {o['id']} | {o['links']} | {o['name']} |")
    (DOCS / "FEATURE_MATRIX.md").write_text("\n".join(m) + "\n", encoding="utf-8")
    print("katalog:", dict(total), "| původní:", dict(ototal))


if __name__ == "__main__":
    main()
