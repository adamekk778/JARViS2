"""OMEGA wave 12 by voice: database intelligence for SQLite files – schema and relations, integrity, query plans with
index advice, slow queries, backup verification and a real restore rehearsal, schema drift, sensitive columns, an
anonymised copy, growth forecast and change audit. The database is only ever opened read-only."""
from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path
from typing import Annotated

from .base import ToolResult, tool
from .files import resolve


def _db(path: str) -> Path:
    p = resolve(path)
    if not p.is_file():
        raise ValueError(f"Databáze neexistuje: {p}")
    with open(p, "rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            raise ValueError(f"{p.name} není databáze SQLite.")
    return p


def _size(n: float) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "?"


async def _run(fn, *a):
    try:
        return await asyncio.to_thread(fn, *a), None
    except (ValueError, OSError) as e:
        return None, ToolResult(False, str(e))
    except Exception as e:  # noqa: BLE001 – sqlite3.DatabaseError etc. → a readable answer
        return None, ToolResult(False, f"Databázi nejde přečíst: {e}")


@tool("db_schema", "Popíše databázi SQLite: tabulky, sloupce, počty řádků, vazby (cizí klíče) a indexy. Jen čtení.",
      category="soubory", perm="files_read")
async def db_schema(ctx, path: Annotated[str, "soubor databáze (.db, .sqlite)"]) -> ToolResult:
    from .. import dbintel

    try:
        p = _db(path)
    except ValueError as e:
        return ToolResult(False, str(e))
    s, err = await _run(dbintel.schema, p)
    if err:
        return err
    parts = []
    for t in s["tables"]:
        rel = f" → {', '.join(sorted({f['table'] for f in t['foreign_keys']}))}" if t["foreign_keys"] else ""
        parts.append(f"{t['name']} ({len(t['columns'])} sloupců, {t['rows'] if t['rows'] is not None else '?'} řádků{rel})")
    return ToolResult(True, f"{p.name}, {_size(s['bytes'])}, {len(s['tables'])} tabulek: " + "; ".join(parts[:20]), data=s)


@tool("db_integrity", "Zkontroluje, jestli databáze SQLite není poškozená (integrity check) a jestli sedí vazby mezi "
      "tabulkami (cizí klíče). Jen čtení.", category="soubory", perm="files_read")
async def db_integrity(ctx, path: str) -> ToolResult:
    from .. import dbintel

    try:
        p = _db(path)
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(dbintel.integrity, p)
    if err:
        return err
    if r["ok"]:
        return ToolResult(True, f"{p.name} je v pořádku: struktura neporušená, vazby sedí.", data=r)
    msg = []
    if r["integrity"] != ["ok"]:
        msg.append("poškozená struktura: " + "; ".join(r["integrity"][:3]))
    if r["foreign_key_errors"]:
        tabs = sorted({e["table"] for e in r["foreign_key_errors"]})
        msg.append(f"{len(r['foreign_key_errors'])} řádků odkazuje na neexistující záznam (tabulky {', '.join(tabs)})")
    return ToolResult(True, f"{p.name} má problém – " + "; ".join(msg) + ".", data=r)


@tool("db_query_plan", "Vysvětlí, jak databáze provede dotaz SELECT (plán), najde procházení celé tabulky a navrhne index. "
      "Nic nemění.", category="soubory", perm="files_read")
async def db_query_plan(ctx, path: str, sql: Annotated[str, "dotaz SELECT"]) -> ToolResult:
    from .. import dbintel

    try:
        p = _db(path)
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(dbintel.plan, p, sql)
    if err:
        return err
    msg = f"Náročnost {r['cost']}. Plán: " + " | ".join(x.strip() for x in r["tree"][:6])
    if r["full_scans"]:
        msg += f". Prochází celou tabulku: {', '.join(r['full_scans'])}"
    if r["advice"]:
        msg += ". Doporučení: " + " ".join(r["advice"])
    return ToolResult(True, msg + ".", data=r)


@tool("db_slow_queries", "Změří, jak dlouho trvají dotazy SELECT (každý víckrát, bere nejlepší čas), a označí pomalé.",
      category="soubory", perm="files_read")
async def db_slow_queries(ctx, path: str, queries: Annotated[list[str], "dotazy SELECT"], slow_ms: float = 100) -> ToolResult:
    from .. import dbintel

    try:
        p = _db(path)
    except ValueError as e:
        return ToolResult(False, str(e))
    if not queries:
        return ToolResult(False, "Zadej aspoň jeden dotaz.")
    r, err = await _run(dbintel.time_queries, p, queries, 3, slow_ms)
    if err:
        return err
    slow = [x for x in r if x["slow"]]
    head = f"{len(slow)} z {len(r)} dotazů je pomalých (≥ {slow_ms:g} ms)." if slow else f"Žádný z {len(r)} dotazů není pomalý."
    return ToolResult(True, head + " " + "; ".join(f"{x['ms']} ms: {x['sql'][:60]}" for x in r[:5]), data=r)


@tool("db_verify_backup", "Ověří zálohu databáze: je čitelná a nepoškozená, a (když zadáš živou databázi) jestli v ní nechybí "
      "tabulky a kolik řádků se liší.", category="soubory", perm="files_read")
async def db_verify_backup(ctx, backup: str, live: Annotated[str, "živá databáze pro porovnání (nepovinné)"] = "") -> ToolResult:
    from .. import dbintel

    try:
        b = _db(backup)
        lv = _db(live) if live else None
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(dbintel.verify_backup, b, lv)
    if err:
        return err
    msg = f"Záloha {b.name}: {'v pořádku' if r['ok'] else 'NENÍ v pořádku'}, {r['tables']} tabulek, {_size(r['bytes'])}"
    if r.get("missing_tables"):
        msg += f"; chybí tabulky {', '.join(r['missing_tables'])}"
    if r.get("row_diff"):
        msg += "; jiný počet řádků: " + ", ".join(f"{k} {v['backup']} vs. {v['live']}" for k, v in list(r["row_diff"].items())[:5])
    return ToolResult(r["ok"], msg + ".", data=r)


@tool("db_restore_rehearsal", "Zkouška obnovy: zálohu databáze opravdu obnoví do dočasné složky, zkontroluje ji, přečte každou "
      "tabulku a ověří zápis – pak kopii smaže. Originál ani zálohy se nemění.", category="soubory", perm="files_read")
async def db_restore_rehearsal(ctx, backup: str) -> ToolResult:
    from .. import dbintel

    try:
        b = _db(backup)
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(dbintel.restore_rehearsal, b)
    if err:
        return err
    if r["ok"]:
        return ToolResult(True, f"Obnova ze {b.name} funguje: {r['readable']}/{r['tables']} tabulek čitelných, zápis jde, "
                                f"trvala {r['seconds']} s.", data=r)
    return ToolResult(False, f"Obnova ze {b.name} NEFUNGUJE: " + "; ".join(r["failed"][:3] or r["integrity"]), data=r)


@tool("db_compare_schema", "Porovná strukturu dvou databází (např. vývojová a ostrá, nebo dnes a záloha): chybějící tabulky, "
      "přidané/odebrané sloupce, změněné typy, indexy.", category="soubory", perm="files_read")
async def db_compare_schema(ctx, first: str, second: str) -> ToolResult:
    from .. import dbintel

    try:
        a, b = _db(first), _db(second)
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(dbintel.drift, a, b)
    if err:
        return err
    if r["same"]:
        return ToolResult(True, "Struktura obou databází je stejná.", data=r)
    parts = []
    if r["only_in_a"]:
        parts.append(f"jen v {a.name}: {', '.join(r['only_in_a'])}")
    if r["only_in_b"]:
        parts.append(f"jen v {b.name}: {', '.join(r['only_in_b'])}")
    for t, ch in r["changed"].items():
        d = []
        if ch["added_columns"]:
            d.append("+" + ", +".join(ch["added_columns"]))
        if ch["removed_columns"]:
            d.append("−" + ", −".join(ch["removed_columns"]))
        if ch["type_changes"]:
            d.append(", ".join(f"{c}: {x} → {y}" for c, (x, y) in ch["type_changes"].items()))
        if ch["added_indexes"] or ch["removed_indexes"]:
            d.append("indexy " + ", ".join(["+" + i for i in ch["added_indexes"]] + ["−" + i for i in ch["removed_indexes"]]))
        parts.append(f"{t}: {'; '.join(d)}")
    return ToolResult(True, "Rozdíly – " + " | ".join(parts) + ".", data=r)


@tool("db_sensitive_data", "Najde v databázi citlivé údaje (e-maily, telefony, rodná čísla, hesla, adresy, čísla účtů…) podle "
      "názvů sloupců i obsahu. Hodnoty neukazuje.", category="soubory", perm="files_read")
async def db_sensitive_data(ctx, path: str) -> ToolResult:
    from .. import dbintel

    try:
        p = _db(path)
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(dbintel.sensitive_columns, p)
    if err:
        return err
    if not r:
        return ToolResult(True, f"V {p.name} jsem citlivé údaje nenašel.", data=[])
    return ToolResult(True, f"Citlivé údaje v {p.name}: " + "; ".join(f"{x['table']}.{x['column']} ({', '.join(x['kinds'])})" for x in r[:15]), data=r)


def _anon_details(a: dict, ctx=None) -> list[str]:
    return [f"Vytvoří NOVÝ soubor s anonymizovanou kopií {a.get('path', '')} (citlivé sloupce nahradí smyšlenými hodnotami).",
            "Originál se nemění."]


@tool("db_anonymize_copy", "Vytvoří anonymizovanou KOPII databáze: citlivé sloupce nahradí smyšlenými hodnotami (stejná hodnota → "
      "stejná náhrada, takže vazby fungují). Originál se nemění. Na testování nebo sdílení.", category="soubory",
      perm="files_write", details=_anon_details)
async def db_anonymize_copy(ctx, path: str, target: Annotated[str, "nový soubor (prázdné = <název>_anonymni.db)"] = "") -> ToolResult:
    from .. import dbintel

    try:
        p = _db(path)
    except ValueError as e:
        return ToolResult(False, str(e))
    dest = resolve(target) if target else None
    if dest is not None and dest.resolve() == p.resolve():
        return ToolResult(False, "Cíl nesmí být původní databáze.")
    r, err = await _run(dbintel.anonymize_copy, p, dest)
    if err:
        return err
    leaks, err = await _run(dbintel.verify_anonymized, p, Path(r["path"]), r["columns"])
    if err:
        return err
    r["leaks"] = leaks
    if leaks:
        return ToolResult(False, f"Kopie {r['path']} pořád obsahuje původní hodnoty ve sloupcích {', '.join(leaks)} – nesdílej ji.", data=r)
    return ToolResult(True, f"Anonymní kopie: {r['path']} – nahrazeno {r['values']} hodnot ve sloupcích {', '.join(r['columns']) or '(žádné)'}.",
                      data=r)


@tool("db_snapshot", "Zapíše si aktuální velikost, počty řádků a strukturu databáze – pro sledování růstu a změn.",
      category="soubory", perm="files_read")
async def db_snapshot(ctx, path: str) -> ToolResult:
    from .. import dbintel

    try:
        p = _db(path)
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(dbintel.snapshot_db, ctx, p)
    if err:
        return err
    return ToolResult(True, f"Zapsáno: {p.name}, {_size(r['bytes'])}, {sum(v or 0 for v in r['rows'].values())} řádků celkem.", data=r)


@tool("db_growth", "Jak databáze roste a co se v ní změnilo od minulého zápisu (řádky po tabulkách, změna struktury), "
      "a odhad velikosti za N dní.", category="soubory", perm="files_read")
async def db_growth(ctx, path: str, days: int = 90) -> ToolResult:
    from .. import dbintel

    try:
        p = _db(path)
    except ValueError as e:
        return ToolResult(False, str(e))
    h = dbintel.history(ctx, p)
    if len(h) < 2:
        return ToolResult(True, f"Pro {p.name} mám {len(h)} záznam(ů) – potřebuju aspoň dva (db_snapshot), ideálně s odstupem dne.",
                          data={"history": h})
    fc, ch = dbintel.forecast(h, days), dbintel.changes(h)
    msg = f"Od {dt.datetime.fromtimestamp(ch['since']):%d. %m. %H:%M}: "
    msg += (", ".join(f"{t} {d:+d}" for t, d in sorted(ch["rows"].items())) or "řádky beze změny")
    msg += "; struktura se ZMĚNILA" if ch["schema_changed"] else "; struktura stejná"
    if fc["known"]:
        msg += f". Roste o {_size(fc['bytes_per_day'])}/den, za {days} dní asi {_size(fc['expected_bytes'])}"
    return ToolResult(True, msg + ".", data={"history": h, "forecast": fc, "changes": ch})


@tool("db_incident", "Co je s databází špatně a co s tím dělat: poškození, zámek jiným programem, přerostlý -wal soubor, "
      "prázdné místo, rozbité vazby – s konkrétními kroky. Nic sám neopravuje.", category="soubory", perm="files_read")
async def db_incident(ctx, path: str) -> ToolResult:
    from .. import dbintel

    try:
        p = _db(path)
    except ValueError as e:
        return ToolResult(False, str(e))
    r, err = await _run(dbintel.incident, p)
    if err:
        return err
    if not r["findings"]:
        return ToolResult(True, f"{p.name}: žádný problém – struktura v pořádku, vazby sedí, žádný zámek ani přerostlý -wal.", data=r)
    return ToolResult(True, f"{p.name}: " + " | ".join(f"[{f['level']}] {f['what']} → {f['fix']}" for f in r["findings"]), data=r)
