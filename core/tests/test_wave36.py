"""Wave 36: developers and testers – migrations, backend performance, staging, canary, property tests, crash
reproduction, battery profiler, browser compatibility, file relationships."""
import sqlite3
import sys
import textwrap
from pathlib import Path

import pytest

from jarvis import devplus, tools


def _db(path: Path, sql: str) -> Path:
    con = sqlite3.connect(path)
    con.executescript(sql)
    con.close()
    return path


def test_migration_sql(tmp_path):
    a = _db(tmp_path / "a.db", "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT); CREATE TABLE old (x INT);"
                               "INSERT INTO users(name) VALUES ('Adam');")
    b = _db(tmp_path / "b.db", "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT DEFAULT '', active INT NOT NULL DEFAULT 1);"
                               "CREATE INDEX ix_email ON users(email); CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INT);")
    r = devplus.migration_sql(a, b)
    assert r["statements"] == 4 and r["risky"] == 1
    assert 'ALTER TABLE "users" ADD COLUMN "active" INT DEFAULT 1 NOT NULL;' in r["sql"]
    assert "-- DROP TABLE \"old\"" in r["sql"]
    con = sqlite3.connect(a)                 # the script really works and keeps the data
    con.executescript(r["sql"])
    cols = [c[1] for c in con.execute("PRAGMA table_info(users)")]
    assert cols == ["id", "name", "email", "active"] and con.execute("SELECT name, active FROM users").fetchone() == ("Adam", 1)
    assert con.execute("SELECT COUNT(*) FROM old").fetchone()[0] == 0          # nothing dropped
    con.close()
    assert devplus.migration_sql(b, b)["same"]


LOG = """1.2.3.4 - - [27/Oct/2026:10:00:00 +0100] "GET /api/users/12 HTTP/1.1" 200 512 "-" "x" 0.120
1.2.3.4 - - [27/Oct/2026:10:00:01 +0100] "GET /api/users/13?x=1 HTTP/1.1" 200 512 "-" "x" 0.180
1.2.3.4 - - [27/Oct/2026:10:00:02 +0100] "POST /api/orders HTTP/1.1" 500 12 "-" "x" 2.400
1.2.3.4 - - [27/Oct/2026:10:00:03 +0100] "GET /health HTTP/1.1" 200 2 "-" "x" 0.001
nesmysl"""


def test_endpoint_stats():
    r = devplus.endpoint_stats(LOG.splitlines())
    assert r["parsed"] == 4 and r["with_times"] == 4
    top = r["endpoints"][0]
    assert top["endpoint"] == "POST /api/orders" and top["error_pct"] == 100.0 and top["p95_ms"] == 2400
    users = next(e for e in r["endpoints"] if e["endpoint"] == "GET /api/users/{id}")
    assert users["requests"] == 2 and users["p50_ms"] == 150


def test_staging_files(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n")
    (tmp_path / "app.py").write_text("import os\nKEY = os.environ.get('STRIPE_KEY')\nDB = os.getenv('DATABASE_URL', 'x')\n")
    f = devplus.staging_files(tmp_path, "Můj Web")
    assert "uvicorn" in f["Dockerfile.staging"] and "pip install" in f["Dockerfile.staging"]
    assert "mj-web-staging" in f["docker-compose.staging.yml"] or "m-j-web-staging" in f["docker-compose.staging.yml"]
    assert "DATABASE_URL=\n" in f[".env.staging.example"] and "STRIPE_KEY=\n" in f[".env.staging.example"]
    node = tmp_path / "n"
    node.mkdir()
    (node / "package.json").write_text('{"scripts": {"start": "node s.js", "build": "vite build"}}')
    assert "RUN npm run build" in devplus.staging_files(node)["Dockerfile.staging"]


async def test_staging_create_never_overwrites(rt, tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<h1>x</h1>")
    (tmp_path / "STAGING.md").write_text("můj vlastní")
    monkeypatch.setattr("jarvis.tools.devplus_tools._proj", lambda ctx, p: tmp_path)
    assert tools.REGISTRY["staging_create"].danger
    r = await tools.call("staging_create", {"project": str(tmp_path)}, rt)
    assert r.ok and "STAGING.md" in r.data["kept"] and (tmp_path / "Dockerfile.staging").exists()
    assert (tmp_path / "STAGING.md").read_text() == "můj vlastní"


def test_canary():
    ok = devplus.canary_decision({"requests": 10000, "errors": 50, "p95_ms": 200}, {"requests": 1000, "errors": 6, "p95_ms": 210})
    assert ok["decision"] == "pustit dál" and devplus.canary_next(5, ok["decision"]) == 25
    bad = devplus.canary_decision({"requests": 10000, "errors": 50, "p95_ms": 200}, {"requests": 1000, "errors": 40, "p95_ms": 200})
    assert bad["decision"] == "vrátit" and devplus.canary_next(25, bad["decision"]) == 0
    slow = devplus.canary_decision({"requests": 10000, "errors": 50, "p95_ms": 200}, {"requests": 1000, "errors": 5, "p95_ms": 400})
    assert slow["decision"] == "vrátit" and "pomalejší" in slow["reason"]
    assert devplus.canary_decision({"requests": 100, "errors": 0}, {"requests": 50, "errors": 0})["decision"] == "počkat"
    assert devplus.canary_next(50, "pustit dál") == 100 and devplus.canary_next(100, "pustit dál") == 100


def test_property_tests(tmp_path):
    src = tmp_path / "lib.py"
    src.write_text(textwrap.dedent("""
        def clean(s: str) -> str:
            return " ".join(s.split())
        def first(xs: list[int]) -> int:
            return xs[0]
        def enc(s: str) -> str:
            return s[::-1]
        def dec(s: str) -> str:
            return s[::-1]
        def bad_sort(xs: list[int]) -> list[int]:
            return xs
    """))
    assert devplus.property_test(src, "clean", "idempotent")["ok"]
    r = devplus.property_test(src, "first", "no_crash")
    assert not r["ok"] and "IndexError" in r["fails"][0]["problem"] and r["fails"][0]["args"] == "[[]]"
    assert devplus.property_test(src, "enc", "roundtrip", "dec")["ok"]
    assert not devplus.property_test(src, "bad_sort", "sorted")["ok"]
    with pytest.raises(ValueError):
        devplus.property_test(src, "clean; import os", "no_crash")
    with pytest.raises(ValueError):
        devplus.property_test(src, "enc", "roundtrip")


def test_crash_reproduction(tmp_path):
    (tmp_path / "shop.py").write_text("def total(items):\n    s = 0\n    for i in items:\n        s += i['price'] * i['qty']\n    return s\n")
    tb = f"""Traceback (most recent call last):
  File "{tmp_path}/main.py", line 3, in <module>
    print(total(load()))
  File "/usr/lib/python3.12/site-packages/x/y.py", line 9, in helper
    return f()
  File "{tmp_path}/shop.py", line 4, in total
    s += i['price'] * i['qty']
KeyError: 'qty'"""
    r = devplus.parse_crash(tb, tmp_path)
    assert r["exception"] == "KeyError: 'qty'" and r["culprit"]["func"] == "total" and r["culprit"]["line"] == 4
    assert len(r["own_frames"]) == 2 and any("→" in ln and "qty" in ln for ln in r["context"])
    assert "from shop import total" in r["test"] and "pytest.raises(KeyError)" in r["test"]
    js = devplus.parse_crash("TypeError: Cannot read properties of undefined (reading 'map')\n    at render (app.js:42:13)\n    at main (index.js:7:2)")
    assert js["language"] == "javascript" and js["culprit"]["file"] == "app.js" and js["culprit"]["line"] == 42


def test_battery_profile():
    s = [{"t": 0, "percent": 90, "plugged": False, "procs": {"chrome.exe": 100, "Teams.exe": 50}},
         {"t": 1800, "percent": 84, "plugged": False, "procs": {"chrome.exe": 400, "Teams.exe": 150, "nove.exe": 0}}]
    r = devplus.battery_profile(s)
    assert r["pct_per_hour"] == 12.0 and r["hours_left"] == 7.0
    assert r["top"][0]["app"] == "chrome.exe" and r["top"][0]["share_pct"] == 75.0
    assert not devplus.battery_profile(s[:1])["ok"]
    assert not devplus.battery_profile([dict(x, plugged=True) for x in s])["ok"]


def test_file_relations(tmp_path):
    (tmp_path / "zprava.docx").write_bytes(b"docx")
    (tmp_path / "zprava.pdf").write_bytes(b"pdf")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text('<img src="logo.png"><a href="kontakt.html">')
    (tmp_path / "web" / "logo.png").write_bytes(b"\x89PNGlogo")
    (tmp_path / "web" / "kontakt.html").write_text("<p>kontakt</p>")
    (tmp_path / "kopie-loga.png").write_bytes(b"\x89PNGlogo")
    (tmp_path / "samotar.txt").write_text("nic")
    r = devplus.file_relations(tmp_path)
    kinds = {(e["a"], e["b"], e["kind"]) for e in r["edges"]}
    assert any(k[2] == "stejný název (jiný formát)" for k in kinds)
    assert ("web/index.html", "web/logo.png", "používá") in kinds and ("web/index.html", "web/kontakt.html", "používá") in kinds
    assert any(k[2] == "stejný obsah" for k in kinds)
    assert r["hubs"][0]["file"] == "web/index.html" and "samotar.txt" in r["lonely"]
    assert devplus.relations_svg(r).startswith("<svg")


@pytest.mark.skipif(sys.platform == "win32", reason="Chromium in CI on Linux only")
async def test_browser_compat(tmp_path, monkeypatch):
    chromium = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if chromium.exists():
        monkeypatch.setenv("JARVIS_CHROMIUM", str(chromium))
    page = tmp_path / "p.html"
    page.write_text("<html><head><meta charset='utf-8'></head><body><h1>Ahoj</h1><script>throw new Error('rozbité')</script></body></html>")
    try:
        r = await devplus.engine_matrix(str(page), tmp_path, engines=("chromium", "nonexistent_engine"))
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no browser: {e}")
    ch = r["engines"]["chromium"]
    if not ch.get("available"):
        pytest.skip("chromium not available")
    assert any("rozbité" in e for e in ch["errors"]) and r["engines"]["nonexistent_engine"]["available"] is False


async def test_tools(rt, tmp_path):
    a = _db(tmp_path / "a.db", "CREATE TABLE t (id INT);")
    b = _db(tmp_path / "b.db", "CREATE TABLE t (id INT, name TEXT);")
    r = await tools.call("db_migration", {"current": str(a), "target": str(b)}, rt)
    assert r.ok and Path(r.attachments[0]).read_text().count("ADD COLUMN") == 1
    log = tmp_path / "access.log"
    log.write_text(LOG)
    r = await tools.call("backend_performance", {"log_file": str(log)}, rt)
    assert r.ok and "POST /api/orders" in r.summary
    r = await tools.call("canary_check", {"old_requests": 5000, "old_errors": 10, "new_requests": 500, "new_errors": 30}, rt)
    assert r.ok and r.summary.startswith("Vrátit")
    r = await tools.call("crash_repro", {"crash": "Traceback (most recent call last):\n  File \"x.py\", line 1, in f\nZeroDivisionError: division by zero"}, rt)
    assert r.ok and "ZeroDivisionError" in r.summary
    assert tools.REGISTRY["property_test"].danger
