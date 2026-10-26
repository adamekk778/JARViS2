"""OMEGA wave 13 (developer lab): dependency risks / vulnerabilities / SBOM / update plan, coverage reports, mutation
testing on a copy, API contracts and breaking changes, a migration preview, code ownership, regressions and flaky
tests, build failures, environment snapshots, release notes, feature flags, the module map and the monorepo map."""
import json
import os
import shutil
import sqlite3
import subprocess

import httpx
import pytest

from jarvis import devlab, tools

tools.load_builtin()
needs_git = pytest.mark.skipif(not shutil.which("git"), reason="git není nainstalovaný")


@pytest.fixture
def proj(tmp_path, rt):
    root = tmp_path / "projekty"
    p = root / "app"
    p.mkdir(parents=True)
    rt.update_config({"tools": {"allowed_folders": [str(root)]}})
    return p


def git(p, *args, who="Adam"):
    env = {**os.environ, "GIT_AUTHOR_NAME": who, "GIT_AUTHOR_EMAIL": f"{who}@x.cz", "GIT_COMMITTER_NAME": who,
           "GIT_COMMITTER_EMAIL": f"{who}@x.cz"}
    subprocess.run(["git", *args], cwd=p, check=True, capture_output=True, env=env)


def write_deps(p):
    (p / "requirements.txt").write_text("requests>=2\nreqeusts==1.0  # typo\ngit+https://example.com/x/y.git#egg=ylib\n"
                                        "flask==2.0.1\n", encoding="utf-8")
    (p / "package.json").write_text(json.dumps({"name": "app", "dependencies": {"react": "^18.2.0", "lodash": "^4.17.20"},
                                                "devDependencies": {"vite": "^5.0.0"}}), encoding="utf-8")
    (p / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {
        "": {"name": "app"},
        "node_modules/react": {"version": "18.2.0", "resolved": "https://registry.npmjs.org/react/-/react-18.2.0.tgz", "license": "MIT"},
        "node_modules/lodash": {"version": "4.17.20", "resolved": "https://evil.example/lodash.tgz", "license": "MIT"},
        "node_modules/vite": {"version": "5.0.0", "resolved": "https://registry.npmjs.org/vite/-/vite-5.0.0.tgz", "hasInstallScript": True},
        "node_modules/vite/node_modules/esbuild": {"version": "0.19.0"}}}), encoding="utf-8")


async def test_dependency_risks(rt, proj):
    write_deps(proj)
    r = await tools.call("dependency_risks", {"project": str(proj)}, rt)
    why = {(x["name"], x["why"].split(" ")[0]) for x in r.data["risks"]}
    assert ("requests", "verze") in why and ("reqeusts", "název") in why and ("ylib", "instaluje") in why
    assert ("vite", "spouští") in why and ("lodash", "stahuje") in why
    assert not any(x["name"] == "flask" for x in r.data["risks"]) and not any(x["name"] == "react" for x in r.data["risks"])
    react = next(d for d in r.data["deps"] if d["name"] == "react")
    assert react["version"] == "18.2.0" and react.get("locked")


async def test_vulnerabilities_and_update_plan(rt, proj):
    write_deps(proj)
    seen = {}

    def handler(req):
        if "osv.dev" in str(req.url):
            q = json.loads(req.content)["queries"]
            seen["osv"] = [x["package"]["name"] for x in q]
            return httpx.Response(200, json={"results": [{"vulns": [{"id": "GHSA-xxxx"}]} if x["package"]["name"] == "flask" else {} for x in q]})
        name = req.url.path.strip("/").split("/")[1 if "pypi" in str(req.url) else 0]
        latest = {"flask": "3.1.0", "reqeusts": "1.0", "react": "18.3.1", "lodash": "4.17.21", "vite": "5.4.0"}
        if name not in latest:
            return httpx.Response(404)
        return httpx.Response(200, json={"info": {"version": latest[name]}} if "pypi" in str(req.url) else {"version": latest[name]})
    rt.transport = httpx.MockTransport(handler)
    r = await tools.call("dependency_vulnerabilities", {"project": str(proj)}, rt)
    assert r.data["vulns"] == [{"name": "flask", "version": "2.0.1", "ecosystem": "pypi", "vulns": ["GHSA-xxxx"]}]
    assert "requests" not in seen["osv"]                    # no exact version → not asked
    r = await tools.call("dependency_update_plan", {"project": str(proj)}, rt)
    g = r.data["groups"]
    assert [x["name"] for x in g["patch"]] == ["lodash"] and {x["name"] for x in g["minor"]} == {"react", "vite"}
    assert [x["name"] for x in g["major"]] == ["flask"] and r.data["steps"][0].startswith("1. Opravné")


async def test_sbom(rt, proj):
    write_deps(proj)
    r = await tools.call("make_sbom", {"project": str(proj)}, rt)
    bom = json.loads((proj / "sbom.cdx.json").read_text(encoding="utf-8"))
    purls = {c["purl"] for c in bom["components"]}
    assert r.ok and bom["bomFormat"] == "CycloneDX" and "pkg:npm/react@18.2.0" in purls and "pkg:pypi/flask@2.0.1" in purls
    assert next(c for c in bom["components"] if c["name"] == "react")["licenses"] == [{"license": {"id": "MIT"}}]
    assert next(c for c in bom["components"] if c["name"] == "vite")["scope"] == "optional"
    (proj / "other.json").write_text("{}", encoding="utf-8")
    assert not (await tools.call("make_sbom", {"project": str(proj), "target": str(proj / "other.json")}, rt)).ok


def test_coverage_formats(tmp_path):
    xml = tmp_path / "coverage.xml"
    xml.write_text("""<coverage><packages><package><classes>
      <class filename="app/a.py"><lines><line number="1" hits="1"/><line number="2" hits="0"/><line number="3" hits="0"/><line number="5" hits="0"/></lines></class>
      <class filename="app/b.py"><lines><line number="1" hits="3"/></lines></class></classes></package></packages></coverage>""", encoding="utf-8")
    r = devlab.coverage(xml)
    assert r["total_pct"] == 40.0 and r["files"][0]["file"] == "app/a.py" and r["files"][0]["ranges"] == ["2–3", "5"]
    lcov = tmp_path / "lcov.info"
    lcov.write_text("SF:src/x.ts\nDA:1,1\nDA:2,0\nend_of_record\n", encoding="utf-8")
    assert devlab.coverage(lcov)["total_pct"] == 50.0
    js = tmp_path / "coverage.json"
    js.write_text(json.dumps({"files": {"m.py": {"summary": {"num_statements": 4, "covered_lines": 3}, "missing_lines": [7]}}}), encoding="utf-8")
    assert devlab.coverage(js)["files"][0]["ranges"] == ["7"]
    (tmp_path / "x.txt").write_text("nic", encoding="utf-8")
    with pytest.raises(ValueError):
        devlab.coverage(tmp_path / "x.txt")


CALC = "def price(n, vip):\n    total = n * 10\n    if vip and n > 2:\n        total = total - 5\n    return total\n"


async def test_mutation_testing_finds_weak_tests(rt, proj):
    (proj / "calc.py").write_text(CALC, encoding="utf-8")
    (proj / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (proj / "test_calc.py").write_text("from calc import price\n\ndef test_runs():\n    assert price(1, False) is not None\n", encoding="utf-8")
    weak = await tools.call("mutation_test", {"project": str(proj), "file": "calc.py", "max_mutants": 8}, rt)
    assert weak.ok and weak.data["tested"] == 8 and weak.data["survived"]
    (proj / "test_calc.py").write_text("from calc import price\n\ndef test_all():\n    assert price(1, False) == 10\n    assert price(3, True) == 25\n"
                                       "    assert price(2, True) == 20\n    assert price(3, False) == 30\n", encoding="utf-8")
    strong = await tools.call("mutation_test", {"project": str(proj), "file": "calc.py", "max_mutants": 8}, rt)
    assert strong.data["score"] > weak.data["score"]
    assert (proj / "calc.py").read_text(encoding="utf-8") == CALC          # the original never changes
    (proj / "test_calc.py").write_text("def test_x():\n    assert False\n", encoding="utf-8")
    r = await tools.call("mutation_test", {"project": str(proj), "file": "calc.py"}, rt)
    assert not r.ok and "neprošly už bez úprav" in r.summary
    assert tools.REGISTRY["mutation_test"].danger


def junit_xml(path, results):
    cases = "".join(f'<testcase classname="t" name="{n}" time="{t}">' + ('<failure message="boom"/>' if st == "F" else "<skipped/>" if st == "S" else "") + "</testcase>"
                    for n, st, t in results)
    path.write_text(f'<testsuites><testsuite name="s">{cases}</testsuite></testsuites>', encoding="utf-8")
    return path


async def test_regressions_and_flaky(rt, tmp_path):
    a = junit_xml(tmp_path / "a.xml", [("login", "P", 0.1), ("pay", "F", 0.1), ("slow", "P", 0.2), ("old", "P", 0.1)])
    b = junit_xml(tmp_path / "b.xml", [("login", "F", 0.1), ("pay", "P", 0.1), ("slow", "P", 0.9), ("new", "P", 0.1)])
    r = await tools.call("test_regressions", {"before": str(a), "after": str(b)}, rt)
    assert r.data["regressions"] == [{"test": "t::login", "message": "boom"}] and r.data["fixed"] == ["t::pay"]
    assert r.data["removed"] == ["t::old"] and r.data["new"] == ["t::new"] and r.data["slower"][0]["test"] == "t::slow"
    runs = [junit_xml(tmp_path / f"r{i}.xml", [("stable", "P", 0), ("wobbly", "F" if i % 2 else "P", 0), ("skip", "S", 0)]) for i in range(4)]
    r = await tools.call("flaky_tests", {"results": [str(x) for x in runs]}, rt)
    assert r.data == [{"test": "t::wobbly", "failed": 2, "runs": 4, "rate": 50}]


async def test_find_flaky_tests_runs_pytest(rt, proj):
    (proj / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (proj / "test_f.py").write_text("import os, itertools\nfrom pathlib import Path\n\ndef test_ok():\n    assert True\n\n"
                                    "def test_alternating():\n    f = Path(__file__).with_name('n.txt')\n    n = int(f.read_text()) if f.exists() else 0\n"
                                    "    f.write_text(str(n + 1))\n    assert n % 2 == 0\n", encoding="utf-8")
    r = await tools.call("find_flaky_tests", {"project": str(proj), "runs": 4}, rt)
    assert r.ok and [x["test"].split("::")[-1] for x in r.data["flaky"]] == ["test_alternating"]
    assert tools.REGISTRY["find_flaky_tests"].danger


SPEC_V1 = """
openapi: 3.0.0
servers: [{url: "http://api.test/v1"}]
paths:
  /users/{id}:
    get:
      parameters: [{name: id, in: path, required: true, schema: {type: integer}}]
      responses:
        "200":
          content:
            application/json:
              schema: {$ref: "#/components/schemas/User"}
  /health:
    get:
      responses: {"200": {content: {application/json: {schema: {type: object}}}}}
components:
  schemas:
    User:
      type: object
      required: [id, name]
      properties:
        id: {type: integer}
        name: {type: string}
        email: {type: string, nullable: true}
        role: {type: string, enum: [admin, user]}
        tags: {type: array, items: {type: string}}
"""


async def test_api_contract(rt, tmp_path):
    spec = tmp_path / "api.yaml"
    spec.write_text(SPEC_V1, encoding="utf-8")
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"id": 1, "name": "Adam", "email": None, "role": "admin", "tags": ["a"]}), encoding="utf-8")
    r = await tools.call("api_contract_check", {"spec": str(spec), "path": "/users/1", "response_file": str(good)}, rt)
    assert r.data["ok"] and "odpovídá" in r.summary

    def handler(req):
        return httpx.Response(200, json={"id": "1", "role": "boss", "tags": ["a", 2]})
    rt.transport = httpx.MockTransport(handler)
    r = await tools.call("api_contract_check", {"spec": str(spec), "url": "http://api.test/v1/users/7"}, rt)
    errs = r.data["errors"]
    assert not r.data["ok"] and "$.name: chybí (povinné)" in errs and "$.id: čekám integer, je str" in errs
    assert any(e.startswith("$.role: hodnota 'boss'") for e in errs) and "$.tags[1]: čekám string, je int" in errs
    assert not (await tools.call("api_contract_check", {"spec": str(spec), "path": "/nope", "response_file": str(good)}, rt)).ok


async def test_api_breaking_changes(rt, tmp_path):
    old = tmp_path / "v1.yaml"
    old.write_text(SPEC_V1, encoding="utf-8")
    import yaml

    s = yaml.safe_load(SPEC_V1)
    del s["components"]["schemas"]["User"]["properties"]["email"]
    s["components"]["schemas"]["User"]["properties"]["id"] = {"type": "string"}
    s["components"]["schemas"]["User"]["properties"]["avatar"] = {"type": "string"}
    s["paths"]["/users/{id}"]["get"]["parameters"].append({"name": "tenant", "in": "query", "required": True})
    del s["paths"]["/health"]
    new = tmp_path / "v2.json"
    new.write_text(json.dumps(s), encoding="utf-8")
    r = await tools.call("api_breaking_changes", {"old_spec": str(old), "new_spec": str(new)}, rt)
    b = r.data["breaking"]
    assert "GET /health: endpoint odstraněn" in b and "GET /users/{id}: nový povinný parametr tenant" in b
    assert "GET /users/{id}: v odpovědi 200 chybí pole email" in b and "GET /users/{id}: pole id změnilo typ integer → string" in b
    assert "GET /users/{id}: nové pole avatar v odpovědi" in r.data["added"] and "NEKOMPATIBILNÍ" in r.summary
    same = await tools.call("api_breaking_changes", {"old_spec": str(old), "new_spec": str(old)}, rt)
    assert same.data["compatible"]


async def test_migration_preview(rt, tmp_path):
    db = tmp_path / "app.db"
    con = sqlite3.connect(db)
    con.executescript("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT); INSERT INTO users (name) VALUES ('a'),('b'),('c');")
    con.close()
    before = db.read_bytes()
    r = await tools.call("migration_preview", {"database": str(db), "sql": "ALTER TABLE users ADD COLUMN email TEXT;\n"
                                               "CREATE INDEX ix_users_email ON users(email);\nDELETE FROM users WHERE name='c';"}, rt)
    assert r.ok and r.data["drift"]["changed"]["users"]["added_columns"] == ["email"] and r.data["rows"]["users"] == {"before": 3, "after": 2}
    assert "+email" in r.summary and "index +ix_users_email" in r.summary
    sql = tmp_path / "002.sql"
    sql.write_text("CREATE TABLE logs (x);\nALTER TABLE missing_tbl ADD COLUMN y TEXT;", encoding="utf-8")
    r = await tools.call("migration_preview", {"database": str(db), "sql": str(sql)}, rt)
    assert not r.ok and "no such table: missing_tbl" in r.summary and "nové tabulky logs)" in r.summary
    assert db.read_bytes() == before


def test_build_failures():
    py = 'Traceback (most recent call last):\n  File "C:\\app\\main.py", line 3, in <module>\n    import yaml\nModuleNotFoundError: No module named \'yaml\'\n'
    r = devlab.build_failure(py)
    assert r["what"] == "chybí Python balíček yaml" and r["fix"].startswith("pip install yaml") and r["where"].endswith("main.py:3")
    ts = "> tsc\nsrc/app.ts(12,5): error TS2322: Type 'string' is not assignable to type 'number'.\n"
    r = devlab.build_failure(ts)
    assert r["what"] == "chyba TypeScriptu" and r["where"] == "src/app.ts:12"
    assert devlab.build_failure("npm ERR! code ERESOLVE\nnpm ERR! ERESOLVE unable to resolve")["what"].startswith("konflikt verzí")
    assert devlab.build_failure("FATAL ERROR: Reached heap limit - JavaScript heap out of memory")["what"] == "došla paměť"
    assert not devlab.build_failure("all good\nbuilt in 3s")["found"]


async def test_explain_build_failure_tool_reads_a_log_file(rt, tmp_path):
    log = tmp_path / "ci.log"
    log.write_text("step 1 ok\nerror: linker `link.exe` not found\n", encoding="utf-8")
    r = await tools.call("explain_build_failure", {"log": str(log)}, rt)
    assert "linker" in r.summary and r.data["line_no"] == 2


@needs_git
async def test_code_owners_and_release_notes(rt, proj):
    git(proj, "init", "-q")
    (proj / "core").mkdir()
    (proj / "web").mkdir()
    for i in range(3):
        (proj / "core" / "a.py").write_text(f"x = {i}\n", encoding="utf-8")
        git(proj, "add", "-A")
        git(proj, "commit", "-q", "-m", f"feat: core {i}", who="Adam")
    git(proj, "tag", "v1.0")
    (proj / "web" / "b.ts").write_text("1", encoding="utf-8")
    git(proj, "add", "-A")
    git(proj, "commit", "-q", "-m", "fix(web): crash on start", who="Eva")
    for msg in ("feat!: drop old API", "oprava tisku faktur", "docs: readme", "Přidán export do PDF"):
        (proj / "web" / "b.ts").write_text(msg, encoding="utf-8")
        git(proj, "add", "-A")
        git(proj, "commit", "-q", "-m", msg, who="Eva")
    r = await tools.call("code_owners", {"project": str(proj)}, rt)
    assert r.data["authors"] == {"Eva": 5, "Adam": 3} and r.data["bus_factor"] == 1
    assert r.data["folders"]["core"]["owner"] == "Adam" and r.data["folders"]["web"]["owner"] == "Eva"
    assert "core/a.py" in r.data["single_owner"]
    r = await tools.call("release_notes", {"project": str(proj), "title": "Verze 1.1"}, rt)
    g = r.data["groups"]
    assert r.data["since"] == "v1.0" and r.data["commits"] == 5
    assert g["breaking"][0].startswith("Drop old API") and len(g["fix"]) == 2 and g["feat"][0].startswith("Přidán export")
    assert r.summary.startswith("# Verze 1.1") and "## Zásadní změny" in r.summary and "Eva (5)" in r.summary


async def test_environment_snapshot_and_compare(rt, tmp_path):
    r = await tools.call("environment_snapshot", {"name": "muj-pc"}, rt)
    snap = json.loads(open(r.data["path"], encoding="utf-8").read())
    assert snap["python"] and "httpx" in snap["packages"] and "PATH" not in json.dumps(snap)
    other = dict(snap, python="3.11.0", packages={**snap["packages"], "httpx": "0.1.0"})
    other["packages"].pop("pytest", None)
    f = tmp_path / "kolega.json"
    f.write_text(json.dumps(other), encoding="utf-8")
    r = await tools.call("environment_compare", {"first": "muj-pc", "second": str(f)}, rt)
    assert r.data["python"][1] == "3.11.0" and r.data["packages"]["httpx"][1] == "0.1.0" and r.data["packages"]["pytest"][1] is None
    assert (await tools.call("environment_compare", {"first": "muj-pc", "second": "muj-pc"}, rt)).data["same"]
    assert "httpx==" in devlab.requirements_lock(snap, ["httpx"])


async def test_feature_flags(rt, proj):
    (proj / "flags.json").write_text(json.dumps({"new_ui": True, "old_flag": False, "beta": {"enabled": False, "owner": "Eva"}}), encoding="utf-8")
    (proj / "src").mkdir()
    (proj / "src" / "app.ts").write_text('if (isEnabled("new_ui")) render();\nconst b = flags["beta"];\nif (flag("ghost")) x();\n', encoding="utf-8")
    (proj / "src" / "srv.py").write_text('if is_enabled("new_ui"):\n    pass\n', encoding="utf-8")
    r = await tools.call("feature_flags", {"project": str(proj)}, rt)
    rows = {f["name"]: f for f in r.data["flags"]}
    assert rows["new_ui"]["count"] == 2 and rows["new_ui"]["on"] and rows["beta"]["uses"] == ["src/app.ts:2"]
    assert r.data["stale"] == ["old_flag"] and list(r.data["undefined"]) == ["ghost"]
    r = await tools.call("set_feature_flag", {"project": str(proj), "name": "beta", "on": True}, rt)
    data = json.loads((proj / "flags.json").read_text(encoding="utf-8"))
    assert r.ok and data["beta"] == {"enabled": True, "owner": "Eva"} and data["new_ui"] is True
    assert not (await tools.call("set_feature_flag", {"project": str(proj), "name": "bad name!", "on": True}, rt)).ok


async def test_module_map_and_cycles(rt, proj):
    pkg = proj / "shop"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "orders.py").write_text("from .customers import Customer\nimport json\n", encoding="utf-8")
    (pkg / "customers.py").write_text("from shop import orders\n", encoding="utf-8")
    (pkg / "util.py").write_text("x = 1\n" * 900, encoding="utf-8")
    (proj / "web").mkdir()
    (proj / "web" / "a.ts").write_text("import { b } from './b';\n", encoding="utf-8")
    (proj / "web" / "b.ts").write_text("import { a } from './a';\nimport x from 'react';\n", encoding="utf-8")
    (proj / "web" / "c.tsx").write_text("import { a } from './a';\n", encoding="utf-8")
    r = await tools.call("module_map", {"project": str(proj)}, rt)
    cycles = r.data["cycles"]
    assert ["shop.customers", "shop.orders"] in cycles and ["web/a.ts", "web/b.ts"] in cycles
    assert any("shop.util má 900 řádků" in p for p in r.data["plan"]) and r.data["fan_in"][0] == ("web/a.ts", 2)


async def test_monorepo_map(rt, proj):
    for path, data in (("packages/shared", {"name": "@x/shared"}), ("apps/web", {"name": "@x/web", "dependencies": {"@x/shared": "*", "react": "^18"}})):
        (proj / path).mkdir(parents=True)
        (proj / path / "package.json").write_text(json.dumps(data), encoding="utf-8")
    (proj / "apps" / "api").mkdir()
    (proj / "apps" / "api" / "pyproject.toml").write_text('[project]\nname = "api"\ndependencies = ["fastapi>=0.1"]\n', encoding="utf-8")
    r = await tools.call("monorepo_map", {"project": str(proj)}, rt)
    by = {p["name"]: p for p in r.data["packages"]}
    assert by["@x/web"]["internal"] == ["@x/shared"] and by["@x/web"]["external"] == 1 and by["api"]["kind"] == "python"
    assert "@x/web (npm, apps/web) → @x/shared" in r.summary
