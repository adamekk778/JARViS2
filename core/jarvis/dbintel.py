"""OMEGA §46 Database Intelligence for SQLite files (the database most local apps use): schema, integrity, query plans
with index advice, slow queries, backup verification and a restore rehearsal, schema drift, sensitive columns, an
anonymised copy, growth forecast, change audit.

The database itself is only ever opened READ-ONLY (URI mode=ro). Writing happens only into NEW files (the anonymised
copy, the rehearsal copy in TEMP) – never into the original."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path


def ro(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError(f"Databáze neexistuje: {path}")
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# ---------------------------------------------------------------------------------------------- 601 schema
def schema(path: Path) -> dict:
    con = ro(path)
    try:
        tables = []
        for t in con.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            name = t["name"]
            cols = [{"name": c["name"], "type": c["type"], "notnull": bool(c["notnull"]), "pk": bool(c["pk"])}
                    for c in con.execute(f"PRAGMA table_info({_q(name)})")]
            fks = [{"from": f["from"], "table": f["table"], "to": f["to"]} for f in con.execute(f"PRAGMA foreign_key_list({_q(name)})")]
            idx = [{"name": i["name"], "unique": bool(i["unique"]),
                    "columns": [c["name"] for c in con.execute(f"PRAGMA index_info({_q(i['name'])})")]}
                   for i in con.execute(f"PRAGMA index_list({_q(name)})")]
            try:
                rows = con.execute(f"SELECT COUNT(*) FROM {_q(name)}").fetchone()[0]
            except sqlite3.DatabaseError:
                rows = None
            tables.append({"name": name, "columns": cols, "foreign_keys": fks, "indexes": idx, "rows": rows})
        return {"path": str(path), "bytes": path.stat().st_size, "tables": tables}
    finally:
        con.close()


# ---------------------------------------------------------------------------------------------- 605 integrity
def integrity(path: Path) -> dict:
    con = ro(path)
    try:
        ic = [r[0] for r in con.execute("PRAGMA integrity_check")]
        fk = [dict(r) for r in con.execute("PRAGMA foreign_key_check")]
        return {"ok": ic == ["ok"] and not fk, "integrity": ic[:20], "foreign_key_errors": fk[:50]}
    except sqlite3.DatabaseError as e:       # so damaged that the check itself cannot run
        return {"ok": False, "integrity": [str(e)], "foreign_key_errors": []}
    finally:
        con.close()


# ---------------------------------------------------------------------------------------------- 603 / 602 / 612 plans
def _check_readonly_sql(sql: str) -> str:
    q = sql.strip().rstrip(";")
    if not re.match(r"(?is)^(select|with)\b", q) or ";" in q:
        raise ValueError("Jen SELECT / WITH (jeden dotaz).")
    return q


def plan(path: Path, sql: str) -> dict:
    """EXPLAIN QUERY PLAN as a tree; full scans with a WHERE/JOIN column → a suggested index; a rough cost."""
    q = _check_readonly_sql(sql)
    con = ro(path)
    try:
        rows = [dict(r) for r in con.execute(f"EXPLAIN QUERY PLAN {q}")]
    finally:
        con.close()
    nodes = {r["id"]: {**r, "children": []} for r in rows}
    roots = []
    for r in rows:
        (nodes[r["parent"]]["children"] if r["parent"] in nodes else roots).append(nodes[r["id"]])

    def lines(ns: list, depth: int = 0) -> list[str]:
        out = []
        for n in ns:
            out.append("  " * depth + n["detail"])
            out += lines(n["children"], depth + 1)
        return out
    details = [r["detail"] for r in rows]
    scans = [m.group(1) for d in details if (m := re.match(r"SCAN (?:TABLE )?(\w+)", d)) and "USING" not in d]
    temp = sum(1 for d in details if "TEMP B-TREE" in d)
    advice = []
    wh = re.findall(r"(?i)\b(?:(\w+)\.)?(\w+)\s*(?:=|<|>|<=|>=|LIKE|IN)\s*", re.sub(r"'[^']*'", "''", q.split("WHERE", 1)[1] if re.search(r"(?i)\bwhere\b", q) else ""))
    for t in scans:
        cols = [c for a, c in wh if (not a or a == t) and c.lower() not in ("and", "or", "not")]
        if cols:
            advice.append(f"CREATE INDEX ix_{t}_{cols[0]} ON {t}({', '.join(dict.fromkeys(cols[:2]))});")
    if temp:
        advice.append("ORDER BY / GROUP BY třídí přes dočasný strom – index na řazené sloupce to zrychlí")
    cost = len(scans) * 10 + temp * 3 + sum(1 for d in details if d.startswith("SEARCH"))
    return {"tree": lines(roots), "full_scans": scans, "temp_sorts": temp, "advice": advice,
            "cost": "nízká" if cost < 5 else "střední" if cost < 15 else "vysoká"}


# ---------------------------------------------------------------------------------------------- 604 slow queries
def time_queries(path: Path, queries: list[str], repeat: int = 3, slow_ms: float = 100, limit_s: float = 15) -> list[dict]:
    con = ro(path)
    out = []
    try:
        con.execute("PRAGMA query_only = 1")
        for sql in queries[:30]:
            q = _check_readonly_sql(sql)
            best, n = None, 0
            for _ in range(max(1, repeat)):
                t0 = time.perf_counter()
                con.set_progress_handler(lambda t0=t0: time.perf_counter() - t0 > limit_s, 10000)   # a runaway query is stopped
                try:
                    n = len(con.execute(q).fetchall())
                except sqlite3.OperationalError as e:
                    if "interrupt" not in str(e):
                        raise
                    best = limit_s * 1000
                    out.append({"sql": q[:200], "ms": round(best, 2), "rows": None, "slow": True, "stopped": True})
                    break
                ms = (time.perf_counter() - t0) * 1000
                best = ms if best is None else min(best, ms)
            else:
                out.append({"sql": q[:200], "ms": round(best, 2), "rows": n, "slow": best >= slow_ms})
    finally:
        con.close()
    return sorted(out, key=lambda x: -x["ms"])


# ---------------------------------------------------------------------------------------------- 606 / 607 backups
def verify_backup(backup: Path, live: Path | None = None) -> dict:
    """Is the backup a healthy database, and how does it compare with the live one (tables, row counts)?"""
    integ = integrity(backup)
    b = schema(backup)
    res = {"ok": integ["ok"], "integrity": integ["integrity"][:3], "tables": len(b["tables"]), "bytes": b["bytes"]}
    if live:
        lv = schema(live)
        bt = {t["name"]: t["rows"] for t in b["tables"]}
        lt = {t["name"]: t["rows"] for t in lv["tables"]}
        res["missing_tables"] = sorted(set(lt) - set(bt))
        res["row_diff"] = {k: {"backup": bt.get(k), "live": lt[k]} for k in lt if k in bt and bt[k] != lt[k]}
        res["ok"] = res["ok"] and not res["missing_tables"]
    return res


def restore_rehearsal(backup: Path) -> dict:
    """A real restore into TEMP: copy, open read-write there, run integrity + a query on every table, then delete."""
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-restore-"))
    target = tmp / backup.name
    t0 = time.perf_counter()
    try:
        shutil.copy2(backup, target)
        con = sqlite3.connect(str(target))
        try:
            try:
                ic = [r[0] for r in con.execute("PRAGMA integrity_check")]
            except sqlite3.DatabaseError as e:
                return {"ok": False, "seconds": round(time.perf_counter() - t0, 2), "tables": 0, "readable": 0,
                        "failed": [str(e)], "integrity": [str(e)]}
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            readable, failed = 0, []
            for t in tables:
                try:
                    con.execute(f"SELECT COUNT(*) FROM {_q(t)}").fetchone()
                    readable += 1
                except sqlite3.DatabaseError as e:
                    failed.append(f"{t}: {e}")
            con.execute("CREATE TABLE __jarvis_rehearsal (x)")       # the restored copy is writable
            con.execute("DROP TABLE __jarvis_rehearsal")
        finally:
            con.close()
        return {"ok": ic == ["ok"] and not failed, "seconds": round(time.perf_counter() - t0, 2), "tables": len(tables),
                "readable": readable, "failed": failed, "integrity": ic[:3]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------------------------- 608 drift
def drift(a: Path, b: Path) -> dict:
    sa, sb = schema(a), schema(b)
    ta = {t["name"]: t for t in sa["tables"]}
    tb = {t["name"]: t for t in sb["tables"]}
    out = {"only_in_a": sorted(set(ta) - set(tb)), "only_in_b": sorted(set(tb) - set(ta)), "changed": {}}
    for name in sorted(set(ta) & set(tb)):
        ca = {c["name"]: c["type"] for c in ta[name]["columns"]}
        cb = {c["name"]: c["type"] for c in tb[name]["columns"]}
        ia = {i["name"] for i in ta[name]["indexes"]}
        ib = {i["name"] for i in tb[name]["indexes"]}
        ch = {"added_columns": sorted(set(cb) - set(ca)), "removed_columns": sorted(set(ca) - set(cb)),
              "type_changes": {c: [ca[c], cb[c]] for c in set(ca) & set(cb) if ca[c] != cb[c]},
              "added_indexes": sorted(ib - ia), "removed_indexes": sorted(ia - ib)}
        if any(ch.values()):
            out["changed"][name] = ch
    out["same"] = not (out["only_in_a"] or out["only_in_b"] or out["changed"])
    return out


# ---------------------------------------------------------------------------------------------- 609 / 611 sensitive data
NAME_RX = [("e-mail", r"e_?mail"), ("telefon", r"phone|tel|mobil"), ("heslo", r"pass(word)?|heslo|pwd|secret|token"),
           ("rodné číslo", r"rodn[ée]?_?cislo|birth_?number|\brc\b|ssn"), ("adresa", r"address|adresa|ulice|street|psc|zip"),
           ("jméno", r"^(jmeno|prijmeni|name|first_?name|last_?name|surname)$"), ("datum narození", r"birth|narozen|dob"),
           ("platební údaje", r"iban|account|ucet|card|karta|cvv"), ("IP adresa", r"^ip(_?addr(ess)?)?$")]
VALUE_RX = [("e-mail", r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$"), ("telefon", r"^\+?\d[\d ]{8,14}$"),
            ("rodné číslo", r"^\d{6}/?\d{3,4}$"), ("platební údaje", r"^(CZ\d{22}|\d{13,19})$")]


def sensitive_columns(path: Path, sample: int = 50) -> list[dict]:
    con = ro(path)
    out = []
    try:
        for t in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            name = t[0]
            for c in con.execute(f"PRAGMA table_info({_q(name)})").fetchall():
                col = c[1]
                kinds = {k for k, rx in NAME_RX if re.search(rx, col, re.I)}
                try:
                    vals = [str(r[0]) for r in con.execute(f"SELECT {_q(col)} FROM {_q(name)} WHERE {_q(col)} IS NOT NULL LIMIT ?", (sample,))]
                except sqlite3.DatabaseError:
                    vals = []
                for k, rx in VALUE_RX:
                    hits = sum(1 for v in vals if re.match(rx, v.strip(), re.I))
                    if vals and hits >= max(1, len(vals) // 2):
                        kinds.add(k)
                if kinds:
                    out.append({"table": name, "column": col, "kinds": sorted(kinds), "by": "název i obsah" if vals else "název"})
    finally:
        con.close()
    return out


def _fake(kind: str, value: str, salt: str) -> str:
    h = hashlib.sha256((salt + value).encode()).hexdigest()
    n = int(h[:12], 16)
    return {"e-mail": f"uzivatel{n % 100000}@example.invalid", "telefon": f"+420 000 {n % 1000:03d} {n // 1000 % 1000:03d}",
            "rodné číslo": "000000/0000", "heslo": "***", "adresa": f"Testovací {n % 200}, 000 00 Město",
            "jméno": f"Osoba{n % 10000}", "datum narození": "1900-01-01", "platební údaje": "CZ0000000000000000000000",
            "IP adresa": f"192.0.2.{n % 254 + 1}"}.get(kind, f"anon-{h[:10]}")


def anonymize_copy(path: Path, dest: Path | None = None) -> dict:
    """A NEW file with the sensitive columns replaced by consistent fake values (the same input → the same fake, so
    joins still work). The original is not touched."""
    found = sensitive_columns(path)
    dest = dest or path.with_name(path.stem + "_anonymni" + path.suffix)
    if dest.exists():
        raise ValueError(f"{dest.name} už existuje.")
    src = ro(path)
    try:
        out = sqlite3.connect(str(dest))
        src.backup(out)
    finally:
        src.close()
    salt = os.urandom(8).hex()
    changed = 0
    try:
        for f in found:
            kind = f["kinds"][0]
            rows = out.execute(f"SELECT rowid, {_q(f['column'])} FROM {_q(f['table'])} WHERE {_q(f['column'])} IS NOT NULL").fetchall()
            for rid, v in rows:
                out.execute(f"UPDATE {_q(f['table'])} SET {_q(f['column'])}=? WHERE rowid=?", (_fake(kind, str(v), salt), rid))
                changed += 1
        out.commit()
        out.execute("VACUUM")
    finally:
        out.close()
    return {"path": str(dest), "columns": [f"{f['table']}.{f['column']}" for f in found], "values": changed}


def verify_anonymized(original: Path, copy: Path, columns: list[str]) -> list[str]:
    """Columns of the copy where any row still holds its original value (row by row via rowid)."""
    con = ro(copy)
    leaks = []
    try:
        con.execute("ATTACH DATABASE ? AS orig", (f"file:{original.as_posix()}?mode=ro",))
        for tc in columns:
            t, c = tc.split(".", 1)
            n = con.execute(f"SELECT COUNT(*) FROM main.{_q(t)} a JOIN orig.{_q(t)} b ON a.rowid=b.rowid "
                            f"WHERE a.{_q(c)} IS NOT NULL AND a.{_q(c)} = b.{_q(c)}").fetchone()[0]
            if n:
                leaks.append(tc)
    finally:
        con.close()
    return leaks


# ---------------------------------------------------------------------------------------------- 610 / 613 history
def snapshot_db(rt, path: Path) -> dict:
    """Size, row counts and a schema fingerprint – kept in JARVIS (for growth and change audit)."""
    rt.db.exec("CREATE TABLE IF NOT EXISTS db_snapshots (path TEXT, ts REAL, bytes INTEGER, rows TEXT, schema_sha TEXT, schema TEXT)")
    s = schema(path)
    rows = {t["name"]: t["rows"] for t in s["tables"]}
    sch = json.dumps([[t["name"], [c["name"] + ":" + c["type"] for c in t["columns"]], sorted(i["name"] for i in t["indexes"])] for t in s["tables"]])
    sha = hashlib.sha256(sch.encode()).hexdigest()
    rt.db.exec("INSERT INTO db_snapshots VALUES (?,?,?,?,?,?)", (str(path.resolve()), time.time(), s["bytes"], json.dumps(rows), sha, sch))
    return {"bytes": s["bytes"], "rows": rows, "schema_sha": sha}


def history(rt, path: Path) -> list[dict]:
    rt.db.exec("CREATE TABLE IF NOT EXISTS db_snapshots (path TEXT, ts REAL, bytes INTEGER, rows TEXT, schema_sha TEXT, schema TEXT)")
    return [{**r, "rows": json.loads(r["rows"])} for r in rt.db.all("SELECT ts, bytes, rows, schema_sha FROM db_snapshots WHERE path=? ORDER BY ts",
                                                                      (str(path.resolve()),))]


def forecast(hist: list[dict], days: float = 90) -> dict:
    """Linear growth from the first to the last snapshot (needs two, a day or more apart)."""
    if len(hist) < 2 or hist[-1]["ts"] - hist[0]["ts"] < 3600:
        return {"known": False}
    per_day = (hist[-1]["bytes"] - hist[0]["bytes"]) / ((hist[-1]["ts"] - hist[0]["ts"]) / 86400)
    return {"known": True, "bytes_per_day": round(per_day), "in_days": days, "expected_bytes": round(hist[-1]["bytes"] + per_day * days)}


def changes(hist: list[dict]) -> dict:
    """OMEGA 613: between the last two snapshots – rows added/removed per table and whether the schema changed."""
    if len(hist) < 2:
        return {"known": False}
    a, b = hist[-2], hist[-1]
    rows = {t: b["rows"].get(t, 0) - a["rows"].get(t, 0) for t in set(a["rows"]) | set(b["rows"])
            if (b["rows"].get(t) or 0) != (a["rows"].get(t) or 0)}
    return {"known": True, "since": a["ts"], "rows": rows, "schema_changed": a["schema_sha"] != b["schema_sha"]}


# ---------------------------------------------------------------------------------------------- 615 incident
def incident(path: Path) -> dict:
    """OMEGA 615: what is wrong with a database right now and what to do – damage, a lock held by another program,
    an oversized WAL, empty pages, a huge file – with concrete next steps (never done automatically)."""
    findings: list[dict] = []
    wal = path.with_name(path.name + "-wal")
    con = ro(path)
    try:
        try:
            con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        except sqlite3.DatabaseError as e:
            msg = str(e)
            if "locked" in msg or "busy" in msg:
                findings.append({"level": "varování", "what": "Databázi právě drží zamčenou jiný program.",
                                 "fix": "Zavři program, který ji používá, a zkus to znovu."})
            else:
                findings.append({"level": "kritické", "what": f"Databázi nejde otevřít: {msg}.",
                                 "fix": "Obnov ji z ověřené zálohy (db_verify_backup, db_restore_rehearsal); originál si nejdřív zkopíruj."})
            return {"ok": False, "findings": findings}
        page_size = con.execute("PRAGMA page_size").fetchone()[0]
        pages = con.execute("PRAGMA page_count").fetchone()[0]
        free = con.execute("PRAGMA freelist_count").fetchone()[0]
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        con.close()
    integ = integrity(path)
    if integ["integrity"] != ["ok"]:
        findings.append({"level": "kritické", "what": "Databáze je poškozená: " + "; ".join(integ["integrity"][:2]),
                         "fix": "Nepiš do ní. Obnov poslední ověřenou zálohu; data jde zkusit zachránit příkazem sqlite3 „.recover“ do nového souboru."})
    if integ["foreign_key_errors"]:
        tabs = sorted({e["table"] for e in integ["foreign_key_errors"]})
        findings.append({"level": "varování", "what": f"{len(integ['foreign_key_errors'])} řádků odkazuje na neexistující záznam ({', '.join(tabs)}).",
                         "fix": "Dohledej, kdo mazal nadřazené záznamy; zapni PRAGMA foreign_keys v aplikaci."})
    if pages and free / pages > 0.25 and free * page_size > 5 * 2**20:
        findings.append({"level": "info", "what": f"{free * page_size // 2**20} MB prázdného místa ({free * 100 // pages} % souboru).",
                         "fix": "VACUUM (když databázi nic nepoužívá) soubor zmenší."})
    if wal.is_file() and wal.stat().st_size > max(64 * 2**20, path.stat().st_size):
        findings.append({"level": "varování", "what": f"Soubor -wal má {wal.stat().st_size // 2**20} MB – změny se nepřenáší do databáze.",
                         "fix": "Nějaký program drží dlouhé čtení; zavři ho, pak PRAGMA wal_checkpoint(TRUNCATE)."})
    return {"ok": not any(f["level"] == "kritické" for f in findings), "findings": findings, "journal_mode": mode,
            "bytes": path.stat().st_size, "free_pages": free, "pages": pages}
