"""OMEGA wave 12 (database intelligence): schema, integrity, query plans with index advice, slow queries, backup check
and a restore rehearsal, schema drift, sensitive columns, an anonymised copy that leaves the original untouched,
growth and change audit."""
import hashlib
import sqlite3
import time

import pytest

from jarvis import dbintel, tools

tools.load_builtin()


@pytest.fixture
def work(tmp_path):
    d = tmp_path / "w"
    d.mkdir()
    return d


def make_db(path, customers=40, with_fk_error=False):
    con = sqlite3.connect(path)
    con.executescript("""
        PRAGMA foreign_keys = OFF;
        CREATE TABLE customers (id INTEGER PRIMARY KEY, jmeno TEXT, email TEXT, phone TEXT, rodne_cislo TEXT, city TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), total REAL, created TEXT);
        CREATE INDEX ix_orders_customer ON orders(customer_id);
    """)
    for i in range(1, customers + 1):
        con.execute("INSERT INTO customers VALUES (?,?,?,?,?,?)",
                    (i, f"Jan Novák {i}", f"jan{i}@seznam.cz", f"+420 777 {i:03d} 123", f"{800101 + i:06d}/{1000 + i}", "Brno"))
        con.execute("INSERT INTO orders (customer_id, total, created) VALUES (?,?,?)", (i, i * 10.5, "2026-10-01"))
    if with_fk_error:
        con.execute("INSERT INTO orders (customer_id, total, created) VALUES (9999, 1, '2026-10-02')")
    con.commit()
    con.close()
    return path


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


async def test_schema_relations_and_rows(rt, work):
    db = make_db(work / "shop.db")
    r = await tools.call("db_schema", {"path": str(db)}, rt)
    assert r.ok and "customers (6 sloupců, 40 řádků)" in r.summary and "orders (4 sloupců, 40 řádků → customers)" in r.summary
    orders = next(t for t in r.data["tables"] if t["name"] == "orders")
    assert orders["indexes"][0]["columns"] == ["customer_id"]
    (work / "x.db").write_text("hello")
    assert not (await tools.call("db_schema", {"path": str(work / "x.db")}, rt)).ok
    assert not (await tools.call("db_schema", {"path": str(work / "nic.db")}, rt)).ok


async def test_integrity_finds_broken_references(rt, work):
    good = make_db(work / "good.db")
    bad = make_db(work / "bad.db", with_fk_error=True)
    assert "v pořádku" in (await tools.call("db_integrity", {"path": str(good)}, rt)).summary
    r = await tools.call("db_integrity", {"path": str(bad)}, rt)
    assert not r.data["ok"] and "1 řádků odkazuje" in r.summary and "orders" in r.summary


def test_plan_suggests_an_index(work):
    db = make_db(work / "shop.db")
    p = dbintel.plan(db, "SELECT * FROM customers WHERE email = 'jan3@seznam.cz'")
    assert p["full_scans"] == ["customers"] and p["advice"][0] == "CREATE INDEX ix_customers_email ON customers(email);"
    ok = dbintel.plan(db, "SELECT * FROM orders WHERE customer_id = 3")
    assert not ok["full_scans"] and any("ix_orders_customer" in line for line in ok["tree"])
    sorted_ = dbintel.plan(db, "SELECT * FROM customers ORDER BY city")
    assert sorted_["temp_sorts"] == 1
    with pytest.raises(ValueError):
        dbintel.plan(db, "DELETE FROM customers")
    with pytest.raises(ValueError):
        dbintel.plan(db, "SELECT 1; DROP TABLE customers")


async def test_slow_queries_and_runaway_stop(rt, work):
    db = make_db(work / "shop.db")
    r = await tools.call("db_slow_queries", {"path": str(db), "queries": ["SELECT * FROM customers", "SELECT COUNT(*) FROM orders"],
                                             "slow_ms": 10000}, rt)
    assert r.ok and "Žádný z 2 dotazů" in r.summary and all(x["rows"] is not None for x in r.data)
    endless = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT COUNT(*) FROM c"
    t0 = time.monotonic()
    out = dbintel.time_queries(db, [endless], repeat=1, limit_s=0.5)
    assert out[0]["stopped"] and out[0]["slow"] and time.monotonic() - t0 < 5


async def test_backup_verify_and_rehearsal(rt, work):
    live = make_db(work / "live.db", customers=40)
    backup = make_db(work / "backup.db", customers=30)
    before = sha(backup)
    r = await tools.call("db_verify_backup", {"backup": str(backup), "live": str(live)}, rt)
    assert r.ok and r.data["row_diff"]["customers"] == {"backup": 30, "live": 40} and "customers 30 vs. 40" in r.summary
    con = sqlite3.connect(live)
    con.execute("CREATE TABLE invoices (id)")
    con.commit()
    con.close()
    r = await tools.call("db_verify_backup", {"backup": str(backup), "live": str(live)}, rt)
    assert not r.ok and "chybí tabulky invoices" in r.summary
    r = await tools.call("db_restore_rehearsal", {"backup": str(backup)}, rt)
    assert r.ok and r.data["readable"] == r.data["tables"] == 2
    assert sha(backup) == before   # the backup itself never changes


def test_rehearsal_reports_a_corrupt_backup(work):
    db = make_db(work / "broken.db", customers=400)
    data = bytearray(db.read_bytes())
    for i in range(4096, 4096 + 12):                   # scribble over the b-tree header of page 2
        data[i] = 0xAB
    db.write_bytes(bytes(data))
    r = dbintel.restore_rehearsal(db)
    assert not r["ok"] and r["failed"]
    assert not dbintel.integrity(db)["ok"]


async def test_schema_drift(rt, work):
    a = make_db(work / "dev.db")
    b = make_db(work / "prod.db")
    con = sqlite3.connect(b)
    con.executescript("ALTER TABLE customers ADD COLUMN vip INTEGER; CREATE INDEX ix_c_city ON customers(city); CREATE TABLE logs (x);")
    con.close()
    r = await tools.call("db_compare_schema", {"first": str(a), "second": str(b)}, rt)
    assert r.data["only_in_b"] == ["logs"] and r.data["changed"]["customers"]["added_columns"] == ["vip"]
    assert r.data["changed"]["customers"]["added_indexes"] == ["ix_c_city"] and "+vip" in r.summary
    assert (await tools.call("db_compare_schema", {"first": str(a), "second": str(a)}, rt)).data["same"]


async def test_sensitive_columns_by_name_and_content(rt, work):
    db = make_db(work / "shop.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, kontakt TEXT)")
    con.executemany("INSERT INTO notes (kontakt) VALUES (?)", [(f"petr{i}@firma.cz",) for i in range(5)])
    con.commit()
    con.close()
    r = await tools.call("db_sensitive_data", {"path": str(db)}, rt)
    found = {f"{x['table']}.{x['column']}": x["kinds"] for x in r.data}
    assert found["customers.email"] == ["e-mail"] and "rodné číslo" in found["customers.rodne_cislo"]
    assert "telefon" in found["customers.phone"] and "jméno" in found["customers.jmeno"]
    assert found["notes.kontakt"] == ["e-mail"]          # found by content, not by name
    assert "customers.city" not in found and "jan1@seznam.cz" not in r.summary


async def test_anonymized_copy_keeps_original_and_joins(rt, work):
    db = make_db(work / "shop.db")
    before = sha(db)
    r = dbintel.anonymize_copy(db)
    assert sha(db) == before
    out = sqlite3.connect(r["path"])
    emails = [x[0] for x in out.execute("SELECT email FROM customers")]
    assert all(e.endswith("@example.invalid") for e in emails) and len(set(emails)) > 30
    assert not any("seznam.cz" in x[0] for x in out.execute("SELECT email FROM customers"))
    assert out.execute("SELECT COUNT(*) FROM orders o JOIN customers c ON c.id = o.customer_id").fetchone()[0] == 40
    assert out.execute("SELECT city FROM customers LIMIT 1").fetchone()[0] == "Brno"
    out.close()
    assert dbintel.verify_anonymized(db, work / "shop_anonymni.db", r["columns"]) == []
    assert dbintel.verify_anonymized(db, db, ["customers.email"]) == ["customers.email"]   # the check really compares
    with pytest.raises(ValueError):
        dbintel.anonymize_copy(db)                     # never overwrites an existing file


async def test_anonymize_tool_needs_confirmation_and_refuses_original(rt, work):
    db = make_db(work / "shop.db")
    spec = tools.REGISTRY["db_anonymize_copy"]
    assert spec.perm == "files_write" and tools.details_for(spec, {"path": str(db)})
    r = await tools.call("db_anonymize_copy", {"path": str(db), "target": str(db)}, rt)
    assert not r.ok and "původní" in r.summary
    r = await tools.call("db_anonymize_copy", {"path": str(db), "target": str(work / "share.db")}, rt)
    assert r.ok and r.data["leaks"] == [] and (work / "share.db").is_file()


async def test_growth_and_change_audit(rt, work):
    db = make_db(work / "shop.db")
    assert "potřebuju aspoň dva" in (await tools.call("db_growth", {"path": str(db)}, rt)).summary
    await tools.call("db_snapshot", {"path": str(db)}, rt)
    rt.db.exec("UPDATE db_snapshots SET ts = ts - 2 * 86400, bytes = bytes - 8192")
    con = sqlite3.connect(db)
    con.executemany("INSERT INTO orders (customer_id, total, created) VALUES (1, 5, '2026-10-20')", [()] * 15)
    con.execute("ALTER TABLE orders ADD COLUMN note TEXT")
    con.commit()
    con.close()
    await tools.call("db_snapshot", {"path": str(db)}, rt)
    r = await tools.call("db_growth", {"path": str(db), "days": 30}, rt)
    assert r.data["changes"]["rows"] == {"orders": 15} and r.data["changes"]["schema_changed"]
    assert r.data["forecast"]["known"] and r.data["forecast"]["bytes_per_day"] > 0 and "orders +15" in r.summary


async def test_incident_assistant(rt, work):
    db = make_db(work / "shop.db")
    assert "žádný problém" in (await tools.call("db_incident", {"path": str(db)}, rt)).summary
    bad = make_db(work / "bad.db", with_fk_error=True)
    r = await tools.call("db_incident", {"path": str(bad)}, rt)
    assert r.data["ok"] and r.data["findings"][0]["level"] == "varování" and "neexistující záznam" in r.summary
    broken = make_db(work / "broken.db", customers=400)
    data = bytearray(broken.read_bytes())
    data[4096:4108] = b"\xab" * 12
    broken.write_bytes(bytes(data))
    r = await tools.call("db_incident", {"path": str(broken)}, rt)
    assert not r.data["ok"] and r.data["findings"][0]["level"] == "kritické" and "zálohu" in r.summary
