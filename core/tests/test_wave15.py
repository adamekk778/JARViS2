"""OMEGA wave 15 (software factory): requirements + acceptance criteria with deterministic checks, a mock server and
generated clients exercised against it end to end, a rollback plan from real git tags, background jobs (Task Scheduler
on Windows for real, parsing everywhere) and App Links / Universal Links."""
import json
import os
import shutil
import subprocess
import sys
import time

import httpx
import pytest
import yaml

from conftest import FakeRouter
from jarvis import factory, tools

tools.load_builtin()
needs_git = pytest.mark.skipif(not shutil.which("git"), reason="git není nainstalovaný")

REQ = {"title": "Rezervace stolů", "functional": [
    {"id": "F1", "text": "Host si vybere datum, čas a počet osob a odešle rezervaci.", "priority": "musí"},
    {"id": "F2", "text": "Restaurace vidí přehled rezervací na den.", "priority": "musí"},
    {"id": "F3", "text": "Aplikace bude rychlá a intuitivní.", "priority": "mělo by"}],
    "nonfunctional": [{"id": "N1", "text": "Odezva rezervace", "measure": "do 2 s pro 95 % požadavků"},
                      {"id": "N2", "text": "Bezpečné ukládání", "measure": "šifrovaně"}],
    "acceptance": [{"req": "F1", "given": "volný stůl pro 4 v 19:00", "when": "host odešle rezervaci", "then": "dostane potvrzení e-mailem"},
                   {"req": "F2", "given": "3 rezervace na dnešek", "when": "obsluha otevře přehled", "then": "vidí 3 řádky seřazené podle času"},
                   {"req": "N1", "given": "100 souběžných hostů", "when": "odesílají rezervace", "then": ""}],
    "questions": ["Jde rezervaci zrušit?"], "out_of_scope": ["platby"]}


def test_requirement_checks():
    c = factory.check_requirements(REQ)
    issues = " | ".join(c["issues"])
    assert "F3: chybí akceptační kritérium" in issues and "F3: vágní „rychlá“" in issues
    assert "N2: nefunkční požadavek bez čísla" in issues and "kritérium 3 (N1): chybí then" in issues
    assert "F1:" not in issues and not c["ok"]
    feat = factory.gherkin(REQ)
    assert "Feature: Rezervace stolů" in feat and "    Given volný stůl pro 4 v 19:00" in feat and feat.count("Scenario:") == 3


async def test_requirements_tool(rt):
    rt.router = FakeRouter(["Tady je:\n```json\n" + json.dumps(REQ, ensure_ascii=False) + "\n```"])
    r = await tools.call("requirements_from_idea", {"idea": "Chci aplikaci pro rezervaci stolů v restauraci, hosté si vyberou čas."}, rt)
    assert r.ok and "3 funkčních, 2 nefunkčních" in r.summary and "1 otevřených otázek" in r.summary and "K upřesnění" in r.summary
    md = open(r.data["markdown"], encoding="utf-8").read()
    assert "## Akceptační kritéria" in md and "⚠ F3: chybí akceptační kritérium" in md
    assert "<popis>" in rt.router.calls[0]["messages"][1]["content"]           # the description is fenced as data
    assert not (await tools.call("requirements_from_idea", {"idea": "web"}, rt)).ok


SPEC = """
openapi: 3.0.0
servers: [{url: "http://localhost/api"}]
paths:
  /items:
    get:
      operationId: listItems
      parameters: [{name: limit, in: query, required: false, schema: {type: integer}}]
      responses: {"200": {content: {application/json: {schema: {type: array, items: {$ref: "#/components/schemas/Item"}}}}}}
    post:
      operationId: createItem
      requestBody: {required: true, content: {application/json: {schema: {$ref: "#/components/schemas/NewItem"}}}}
      responses: {"201": {content: {application/json: {schema: {$ref: "#/components/schemas/Item"}}}}}
  /items/{itemId}:
    get:
      operationId: getItem
      parameters: [{name: itemId, in: path, required: true, schema: {type: integer}}]
      responses:
        "200":
          content:
            application/json:
              example: {id: 7, name: "Kafe", price: 59.0, tags: ["teplé"], created: "2026-01-01T12:00:00Z"}
    delete:
      operationId: deleteItem
      parameters: [{name: itemId, in: path, required: true}]
      responses: {"204": {description: smazáno}}
components:
  schemas:
    NewItem:
      type: object
      required: [name, price]
      properties: {name: {type: string, minLength: 1}, price: {type: number}}
    Item:
      allOf:
        - $ref: "#/components/schemas/NewItem"
        - type: object
          properties: {id: {type: integer}, tags: {type: array, items: {type: string}}, created: {type: string, format: date-time}, kind: {type: string, enum: [jídlo, pití]}}
"""


@pytest.fixture
def spec_file(tmp_path):
    f = tmp_path / "api.yaml"
    f.write_text(SPEC, encoding="utf-8")
    return f


async def test_mock_server(rt, spec_file):
    rt.transport = None
    r = await tools.call("mock_server_start", {"spec": str(spec_file)}, rt)
    url = r.data["url"]
    assert r.ok and url.endswith("/api") and r.data["operations"] == 4
    async with httpx.AsyncClient() as c:
        items = (await c.get(url + "/items")).json()
        assert items == [{"name": "ukázka name", "price": 1.5, "id": 1, "tags": ["ukázka tags"], "created": "2026-01-01T12:00:00Z", "kind": "jídlo"}]
        assert (await c.get(url + "/items/3")).json()["name"] == "Kafe"
        bad = await c.post(url + "/items", json={"name": ""})
        assert bad.status_code == 400 and "$.price: chybí (povinné)" in bad.json()["details"] and "$.name: kratší než 1" in bad.json()["details"]
        ok = await c.post(url + "/items", json={"name": "Čaj", "price": 39})
        assert ok.status_code == 201
        assert (await c.delete(url + "/items/3")).status_code == 204
        assert (await c.get(url + "/nic")).status_code == 404
        assert (await c.put(url + "/items")).status_code == 405
    stop = await tools.call("mock_server_stop", {}, rt)
    assert "Přišlo 7 požadavků, z toho 3 mimo kontrakt" in stop.summary


async def test_python_client_against_mock(rt, spec_file, tmp_path):
    rt.transport = None
    r = await tools.call("generate_api_client", {"spec": str(spec_file), "language": "python"}, rt)
    assert r.ok and "list_items, create_item, get_item, delete_item" in r.summary
    url = (await tools.call("mock_server_start", {"spec": str(spec_file)}, rt)).data["url"]
    try:
        script = tmp_path / "use.py"
        script.write_text("import sys, json\nsys.path.insert(0, sys.argv[1])\nfrom api_client import ApiClient\n"
                          "c = ApiClient(sys.argv[2])\nprint(json.dumps([c.get_item(7)['name'], len(c.list_items(limit=5)), "
                          "c.create_item({'name': 'Čaj', 'price': 39})['id'], c.delete_item(7)]))\n", encoding="utf-8")
        out = subprocess.run([sys.executable, str(script), str(spec_file.parent), url], capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert json.loads(out.stdout.strip().splitlines()[-1]) == ["Kafe", 1, 1, None], out.stderr
    finally:
        await tools.call("mock_server_stop", {}, rt)
    ts = await tools.call("generate_api_client", {"spec": str(spec_file), "language": "ts"}, rt)
    code = open(ts.data["path"], encoding="utf-8").read()
    assert "getItem(itemId: string | number)" in code and "createItem(body: unknown)" in code and 'listItems(query: { "limit"?: unknown } = {})' in code
    assert code.count("{") == code.count("}")
    (spec_file.parent / "mine.py").write_text("print('ruční kód')", encoding="utf-8")
    assert not (await tools.call("generate_api_client", {"spec": str(spec_file), "language": "python", "target": str(spec_file.parent / "mine.py")}, rt)).ok


@needs_git
async def test_rollback_plan(rt, tmp_path):
    root = tmp_path / "projekty"
    p = root / "eshop"
    p.mkdir(parents=True)
    rt.update_config({"tools": {"allowed_folders": [str(root)]}})
    env = {**os.environ, "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@x", "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@x"}

    def g(*a):
        subprocess.run(["git", *a], cwd=p, check=True, capture_output=True, env=env)
    g("init", "-q")
    (p / "app.py").write_text("v1", encoding="utf-8")
    g("add", "-A")
    g("commit", "-q", "-m", "v1")
    g("tag", "v1.0")
    time.sleep(1.1)                                     # tag dates must differ (sorted by creation)
    (p / "migrations").mkdir()
    (p / "migrations" / "002_add_email.sql").write_text("ALTER TABLE u ADD email;", encoding="utf-8")
    (p / "settings.yaml").write_text("x: 1", encoding="utf-8")
    (p / "requirements.txt").write_text("flask==3", encoding="utf-8")
    (p / "app.py").write_text("v2", encoding="utf-8")
    g("add", "-A")
    g("commit", "-q", "-m", "v2")
    g("tag", "v2.0")
    r = await tools.call("rollback_plan", {"project": str(p)}, rt)
    assert r.data["current"] == "v2.0" and r.data["target"] == "v1.0" and r.data["risk"] == "vysoké"
    assert r.data["migrations"] == ["migrations/002_add_email.sql"] and r.data["config"] == ["settings.yaml"] and r.data["dependencies"] == ["requirements.txt"]
    assert "git checkout v1.0" in r.summary and "migrace" in r.summary


def test_task_classification():
    ok = factory.classify_task({"Name": "Záloha", "State": "Ready", "Result": 0, "NextRun": "2099-01-01T00:00:00"})
    fail = factory.classify_task({"Name": "Sync", "State": "Ready", "Result": 2147942402})
    neg = factory.classify_task({"Name": "X", "State": "Ready", "Result": -2147024894})   # same code as a signed int
    stuck = factory.classify_task({"Name": "Old", "State": "Ready", "Result": 0, "NextRun": "2020-01-01T00:00:00"})
    off = factory.classify_task({"Name": "Off", "State": "Disabled", "Result": 1})
    assert not ok["problem"] and fail["problem"] == "poslední běh selhal: soubor nenalezen" and neg["problem"] == fail["problem"]
    assert "v minulosti" in stuck["problem"] and not off["problem"]


def test_scheduled_tasks_parsing_with_fake_powershell():
    out = json.dumps({"tasks": [{"Name": "A", "Path": "\\", "State": "Ready", "Action": "a.exe", "LastRun": "", "NextRun": "", "Result": 267011, "Missed": 0},
                                {"Name": "B", "Path": "\\", "State": "Ready", "Action": "b.exe", "LastRun": "", "NextRun": "", "Result": 1, "Missed": 0}]})
    res = factory.scheduled_tasks(runner=lambda cmd, t: (0, out, ""))
    assert [t["result"] for t in res] == ["ještě neběželo", "chyba 0x00000001"] and res[1]["problem"]
    with pytest.raises(ValueError, match="nejde přečíst"):
        factory.scheduled_tasks(runner=lambda cmd, t: (0, json.dumps({"tasks": {"error": "Access denied"}}), ""))


async def test_background_jobs_tool(rt):
    rt.db.exec("INSERT INTO jobs VALUES ('j1', 'remind', '0 8 * * *', '{}', ?, 1, ?, 'Ranní brífink')", (time.time() - 3600, time.time()))
    rt.db.exec("INSERT INTO jobs VALUES ('j2', 'remind', '0 9 * * *', '{}', ?, 1, ?, 'Zítřek')", (time.time() + 3600, time.time()))
    r = await tools.call("background_jobs", {}, rt)
    assert r.ok and [j["name"] for j in r.data["problems"] if j.get("kind")] == ["Ranní brífink"]
    if sys.platform == "win32":                       # the real Task Scheduler on Windows
        assert "Plánovač Windows:" in r.summary and "úloh" in r.summary.split(";")[0]


ASSET = [{"relation": ["delegate_permission/common.handle_all_urls"],
          "target": {"namespace": "android_app", "package_name": "cz.jarvis.app",
                     "sha256_cert_fingerprints": [":".join(["AB"] * 32)]}}]
AASA = {"applinks": {"details": [{"appIDs": ["ABCDE12345.cz.jarvis.app"], "components": [{"/": "/produkt/*"}, {"/": "/admin/*", "exclude": True}]}]}}


async def test_app_links(rt):
    def good(req):
        if req.url.path.endswith("assetlinks.json"):
            return httpx.Response(200, json=ASSET)
        return httpx.Response(200, content=json.dumps(AASA).encode(), headers={"content-type": "application/json"})
    rt.transport = httpx.MockTransport(good)
    r = await tools.call("check_app_links", {"domain": "https://jarvis.cz/", "android_package": "cz.jarvis.app",
                                             "ios_app_id": "ABCDE12345.cz.jarvis.app", "path": "/produkt/42"}, rt)
    assert r.data["ok"] and r.data["ios"]["path_opens_app"]
    adm = await tools.call("check_app_links", {"domain": "jarvis.cz", "path": "/admin/x"}, rt)
    assert adm.data["ios"]["path_opens_app"] is False and "Android: v pořádku (cz.jarvis.app)" in r.summary

    def bad(req):
        if req.url.path.endswith("assetlinks.json"):
            return httpx.Response(200, text=json.dumps([{**ASSET[0], "target": {**ASSET[0]["target"], "sha256_cert_fingerprints": ["abc"]}}]),
                                  headers={"content-type": "text/plain"})
        return httpx.Response(301, headers={"location": "https://www.jarvis.cz/.well-known/apple-app-site-association"})
    rt.transport = httpx.MockTransport(bad)
    r = await tools.call("check_app_links", {"domain": "jarvis.cz", "android_package": "cz.jiny.app", "path": "/kosik"}, rt)
    a, i = r.data["android"]["problems"], r.data["ios"]["problems"]
    assert any("Content-Type" in x for x in a) and any("otisk" in x for x in a) and any("cz.jiny.app" in x for x in a)
    assert any("přesměrovává" in x for x in i) and not r.data["ok"]
    assert not (await tools.call("check_app_links", {"domain": "nic"}, rt)).ok


def test_sdk_from_spec_without_operation_ids():
    spec = yaml.safe_load("paths:\n  /users/{user-id}/orders:\n    get:\n      parameters: [{name: user-id, in: path, required: true}, {name: from, in: query, required: true}]\n"
                          "      responses: {'200': {description: ok}}\n")
    py = factory.sdk_python(spec)
    compile(py, "x.py", "exec")
    assert "def get_users_user_id_orders(self, user_id: str | int, from_: Any)" in py and '{"from": from_}' in py
