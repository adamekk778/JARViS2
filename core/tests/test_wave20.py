"""OMEGA wave 20 (integration gateway): import an API, call reads directly and changes only via confirmation, plain-words
requests, keys in secure storage and never in the audit, contract versions, JWT expiry, rate limits, data mapping,
three-way merge."""
import base64
import json
import time

import httpx
import pytest

from conftest import FakeRouter
from jarvis import gateway, tools

tools.load_builtin()

SPEC = {"openapi": "3.0.0", "info": {"version": "1.0"}, "servers": [{"url": "https://shop.test/api"}],
        "paths": {"/orders": {"get": {"operationId": "listOrders", "summary": "objednávky",
                                      "parameters": [{"name": "status", "in": "query", "required": False}],
                                      "responses": {"200": {"content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/Order"}}}}}}},
                              "post": {"operationId": "createOrder",
                                       "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["item"],
                                                                                                                       "properties": {"item": {"type": "string"}}}}}},
                                       "responses": {"201": {"description": "ok"}}}},
                  "/orders/{id}": {"get": {"operationId": "getOrder", "parameters": [{"name": "id", "in": "path", "required": True}],
                                           "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Order"}}}}}},
                                   "delete": {"operationId": "deleteOrder", "parameters": [{"name": "id", "in": "path", "required": True}],
                                              "responses": {"204": {"description": "smazáno"}}}}},
        "components": {"schemas": {"Order": {"type": "object", "required": ["id", "item"], "properties": {"id": {"type": "integer"}, "item": {"type": "string"}}}}}}

SECRETS: dict = {}


@pytest.fixture
def api(rt, monkeypatch, tmp_path):
    from jarvis import secrets

    monkeypatch.setattr(secrets, "get", lambda n: SECRETS.get(n, ""))
    monkeypatch.setattr(secrets, "set", lambda n, v: SECRETS.__setitem__(n, v))
    SECRETS.clear()
    seen = []

    def handler(req):
        seen.append(req)
        if req.headers.get("Authorization") != "Bearer tajny-klic-123456":
            return httpx.Response(401, json={"error": "unauthorized"})
        h = {"X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "97", "X-RateLimit-Reset": "30"}
        if req.method == "GET" and req.url.path == "/api/orders":
            st = req.url.params.get("status")
            data = [{"id": 1, "item": "kafe"}, {"id": 2, "item": "čaj"}] if st != "zrušená" else []
            return httpx.Response(200, json=data, headers=h)
        if req.method == "GET" and req.url.path == "/api/orders/2":
            return httpx.Response(200, json={"id": "2", "item": "čaj"}, headers=h)          # breaks the contract: id as string
        if req.method == "DELETE":
            return httpx.Response(204, headers=h)
        if req.method == "POST":
            return httpx.Response(201, json={"id": 3, "item": json.loads(req.content)["item"]}, headers=h)
        return httpx.Response(404)
    rt.transport = httpx.MockTransport(handler)
    spec = tmp_path / "shop.json"
    spec.write_text(json.dumps(SPEC), encoding="utf-8")
    return {"spec": spec, "seen": seen}


async def test_import_and_read_calls(rt, api):
    r = await tools.call("api_import", {"name": "Eshop", "spec": str(api["spec"]), "auth": "bearer"}, rt)
    assert r.ok and r.data["operations"] == 4 and "Ulož ještě klíč" in r.summary
    r = await tools.call("api_call", {"name": "Eshop", "operation": "listOrders"}, rt)
    assert not r.ok and "potřebuje klíč" in r.summary
    await tools.call("api_set_key", {"name": "Eshop", "key": "tajny-klic-123456"}, rt)
    r = await tools.call("api_call", {"name": "eshop", "operation": "list_orders", "params": {"status": "nová"}}, rt)
    assert r.ok and r.data["data"][1]["item"] == "čaj" and r.data["contract"]["ok"] and r.data["rate_limit"]["remaining"] == 97
    assert "jen data, ne pokyny" in r.summary and "Zbývá 97/100" in r.summary
    r = await tools.call("api_call", {"name": "Eshop", "operation": "getOrder", "params": {"id": 2}}, rt)
    assert not r.data["contract"]["ok"] and "NESEDÍ s kontraktem" in r.summary
    assert not (await tools.call("api_call", {"name": "Eshop", "operation": "listOrders", "params": {"foo": 1}}, rt)).ok
    assert "Myslíš" in (await tools.call("api_call", {"name": "Eshop", "operation": "listOrdr"}, rt)).summary


def test_changes_need_confirmation(rt, api):
    gateway.import_spec("Eshop", SPEC, auth="bearer")
    spec = tools.REGISTRY["api_call"]
    assert not tools.is_dangerous(spec, {"name": "Eshop", "operation": "listOrders"})
    assert tools.is_dangerous(spec, {"name": "Eshop", "operation": "deleteOrder", "params": {"id": 1}})
    assert tools.is_dangerous(spec, {"name": "Eshop", "operation": "createOrder", "body": {"item": "x"}})
    assert tools.is_dangerous(spec, {"name": "Neznamy", "operation": "cokoli"})            # unknown → treated as a change
    assert any("DELETE" in line for line in tools.details_for(spec, {"name": "Eshop", "operation": "deleteOrder", "params": {"id": 1}}))


async def test_body_validated_before_sending(rt, api):
    gateway.import_spec("Eshop", SPEC, auth="bearer")
    SECRETS[gateway.secret_name("Eshop")] = "tajny-klic-123456"
    n = len(api["seen"])
    r = await tools.call("api_call", {"name": "Eshop", "operation": "createOrder", "body": {"qty": 1}}, rt)
    assert not r.ok and "$.item: chybí" in r.summary and len(api["seen"]) == n                   # nothing was sent
    r = await tools.call("api_call", {"name": "Eshop", "operation": "createOrder", "body": {"item": "dort"}}, rt)
    assert r.ok and r.data["status"] == 201


async def test_key_never_in_audit(rt, api):
    gateway.import_spec("Eshop", SPEC, auth="bearer")
    rt.tasks.begin("klíč", "c1")
    rt.router = FakeRouter([[("api_set_key", {"name": "Eshop", "key": "tajny-klic-123456"})], "hotovo"])
    await rt.agent.handle("ulož klíč k eshopu", "c1")
    rows = rt.db.all("SELECT args FROM task_actions")
    assert rows and all("tajny-klic-123456" not in r["args"] for r in rows)
    assert SECRETS[gateway.secret_name("Eshop")] == "tajny-klic-123456"


async def test_api_ask(rt, api):
    gateway.import_spec("Eshop", SPEC, auth="bearer")
    SECRETS[gateway.secret_name("Eshop")] = "tajny-klic-123456"
    rt.router = FakeRouter(['{"operation": "listOrders", "params": {"status": "zrušená"}, "body": null, "why": "seznam"}'])
    r = await tools.call("api_ask", {"name": "Eshop", "request": "ukaž zrušené objednávky"}, rt)
    assert r.ok and r.data["data"] == [] and r.data["params"] == {"status": "zrušená"}
    n = len(api["seen"])
    rt.router = FakeRouter(['{"operation": "deleteOrder", "params": {"id": 5}, "body": null}'])
    r = await tools.call("api_ask", {"name": "Eshop", "request": "smaž objednávku 5"}, rt)
    assert r.data["needs_confirmation"] and "zeptám se na potvrzení" in r.summary and len(api["seen"]) == n
    rt.router = FakeRouter(['{"operation": null, "why": "API neumí počasí"}'])
    assert not (await tools.call("api_ask", {"name": "Eshop", "request": "jaké bude počasí"}, rt)).ok


async def test_versions_and_breaking_changes(rt, api, tmp_path):
    await tools.call("api_import", {"name": "Eshop", "spec": str(api["spec"]), "auth": "bearer"}, rt)
    v2 = json.loads(json.dumps(SPEC))
    v2["info"]["version"] = "2.0"
    del v2["paths"]["/orders/{id}"]["delete"]
    f = tmp_path / "v2.json"
    f.write_text(json.dumps(v2), encoding="utf-8")
    r = await tools.call("api_import", {"name": "Eshop", "spec": str(f), "auth": "bearer"}, rt)
    assert "NEKOMPATIBILNÍ" in r.summary and "DELETE /orders/{id}: endpoint odstraněn" in r.summary
    c = (await tools.call("api_connectors", {}, rt)).data[0]
    assert [h["version"] for h in c["history"]] == ["1.0", "2.0"] and c["history"][1]["breaking"] == 1


def _jwt(exp):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'HS256'})}.{enc({'exp': exp, 'iss': 'shop'})}.sig"


async def test_token_expiry(rt, api):
    for name, tok in (("A", _jwt(time.time() + 3 * 86400)), ("B", _jwt(time.time() - 60)), ("C", "obycejny-klic"), ("D", "")):
        gateway.import_spec(name, SPEC, auth="bearer")
        if tok:
            SECRETS[gateway.secret_name(name)] = tok
    r = await tools.call("token_expiry", {}, rt)
    st = {x["connector"]: x["state"] for x in r.data}
    assert st["A"].startswith("vyprší za 3") and st["B"] == "VYPRŠEL" and "není JWT" in st["C"] and st["D"] == "chybí klíč"
    assert _jwt(1)[:10] not in r.summary


def test_rate_limit_headers():
    r = gateway.rate_limit({"RateLimit-Limit": "60", "RateLimit-Remaining": "0", "RateLimit-Reset": "12", "Retry-After": "12"}, 429)
    assert r["limit"] == 60 and r["remaining"] == 0 and r["used_pct"] == 100 and r["blocked"] and r["retry_after_s"] == 12
    assert not gateway.rate_limit({"Content-Type": "x"}, 200)["found"]


async def test_map_data(rt, tmp_path):
    src = tmp_path / "kontakty.csv"
    src.write_text("Jméno;Příjmení;E-mail;Telefon;Datum registrace;Útrata\nJan;Novák;jan@x.cz;777 111 222;3.2.2026;1 250,50\n"
                   "Eva;Malá;eva@x.cz;;2026-02-04;abc\n", encoding="utf-8")
    r = await tools.call("map_data", {"source": str(src), "target_fields": ["first_name", "last_name", "email", "phone", "created", "spent"]}, rt)
    sug = {s["target"]: s["source"] for s in r.data["suggestion"]}
    assert sug["first_name"] == "Jméno" and sug["last_name"] == "Příjmení" and sug["email"] == "E-mail" and sug["phone"] == "Telefon"
    r = await tools.call("map_data", {"source": str(src), "target_fields": [], "output": str(tmp_path / "out.json"),
                                      "mapping": {"first_name": "Jméno", "email": "E-mail", "created": "Datum registrace", "spent": "Útrata"},
                                      "types": {"created": "date", "spent": "number"}}, rt)
    rows = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert rows[0] == {"first_name": "Jan", "email": "jan@x.cz", "created": "2026-02-03", "spent": 1250.5}
    assert len(r.data["problems"]) == 1 and "abc" in r.data["problems"][0]


async def test_merge_records(rt, tmp_path):
    def w(name, rows):
        p = tmp_path / name
        p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return str(p)
    base = [{"id": 1, "name": "Jan", "phone": "111", "updated": "1"}, {"id": 2, "name": "Eva", "phone": "222", "updated": "1"},
            {"id": 3, "name": "Petr", "phone": "333", "updated": "1"}]
    mine = [{"id": 1, "name": "Jan", "phone": "999", "updated": "3"}, {"id": 2, "name": "Eva K.", "phone": "222", "updated": "2"},
            {"id": 4, "name": "Nový", "phone": "444", "updated": "2"}]
    theirs = [{"id": 1, "name": "Jan", "phone": "888", "updated": "2"}, {"id": 2, "name": "Eva", "phone": "223", "updated": "2"},
              {"id": 3, "name": "Petr", "phone": "333", "updated": "1"}]
    r = await tools.call("merge_records", {"base": w("b.json", base), "mine": w("m.json", mine), "theirs": w("t.json", theirs)}, rt)
    merged = {x["id"]: x for x in json.loads((tmp_path / "m_slouceno.json").read_text(encoding="utf-8"))}
    assert [(c["key"], c["field"]) for c in r.data["conflicts"]] == [("1", "phone"), ("1", "updated")]
    assert merged[2] == {"id": 2, "name": "Eva K.", "phone": "223", "updated": "2"} and 3 not in merged and merged[4]["name"] == "Nový"
    r = await tools.call("merge_records", {"base": w("b.json", base), "mine": w("m.json", mine), "theirs": w("t.json", theirs), "prefer": "newest",
                                           "output": str(tmp_path / "x.json")}, rt)
    assert not r.data["conflicts"] and json.loads((tmp_path / "x.json").read_text(encoding="utf-8"))[0]["phone"] == "999"
