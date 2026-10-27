"""Wave 40: local AI (GPU split, inference queue, answer cache, adaptive local models), offline knowledge packs, webhooks,
event replay, a connector sandbox and a connector from curl."""
import asyncio
import hashlib
import hmac
import json
import zipfile

import httpx
import pytest

from jarvis import aiplus, automations, gateway, tools
from jarvis.config import Automation, AutoTrigger, Brain, ProviderCfg, Webhook
from jarvis.llm.router import Router

tools.load_builtin()

VAULT: dict = {}


@pytest.fixture
def vault(monkeypatch):
    from jarvis import secrets

    VAULT.clear()
    monkeypatch.setattr(secrets, "get", lambda n: VAULT.get(n, ""))
    monkeypatch.setattr(secrets, "set", lambda n, v: VAULT.__setitem__(n, v) if v else VAULT.pop(n, None))
    return VAULT


def test_gpu_layers():
    full = aiplus.gpu_layers(8, 24)
    assert full["gpu_layers"] == full["layers"] and full["mode"] == "celý model na grafice"
    part = aiplus.gpu_layers(14, 6)
    assert 0 < part["gpu_layers"] < part["layers"] and part["mode"] == "napůl grafika / procesor"
    assert 1 < part["relative_speed"] < full["relative_speed"]
    assert aiplus.gpu_layers(32, 1)["gpu_layers"] == 0


def test_ollama_gets_num_gpu():
    from jarvis.llm.router import build_provider

    p = ProviderCfg(id="o", preset="ollama", model="qwen2.5:7b")
    assert "num_gpu" not in build_provider(p, "", Brain()).options
    assert build_provider(p, "", Brain(local_gpu_layers=20)).options["num_gpu"] == 20


async def test_queue_interactive_first_and_cancel():
    q = aiplus.InferenceQueue()
    order = []
    gate = asyncio.Event()

    async def job(name, prio, hold=None):
        async with q.slot(prio):
            order.append(name)
            if hold:
                await hold.wait()

    first = asyncio.create_task(job("první", "background", gate))
    await asyncio.sleep(0)
    bg = asyncio.create_task(job("pozadí", "background"))
    gone = asyncio.create_task(job("zrušený", "interactive"))
    await asyncio.sleep(0)
    me = asyncio.create_task(job("ty", "interactive"))
    await asyncio.sleep(0)
    gone.cancel()
    await asyncio.sleep(0)
    assert q.status()["waiting"] == 2
    gate.set()
    await asyncio.gather(first, bg, me)
    assert order == ["první", "ty", "pozadí"]
    assert q.status() == {**q.status(), "busy": False, "waiting": 0} and q.served == {"interactive": 1, "background": 2}
    with aiplus.background():
        assert aiplus.PRIORITY.get() == "background"
    assert aiplus.PRIORITY.get() == "interactive"


def ollama_reply(text):
    lines = [json.dumps({"message": {"content": text}, "done": False}), json.dumps({"message": {"content": ""}, "done": True})]
    return httpx.Response(200, content=("\n".join(lines) + "\n").encode())


async def test_router_uses_queue_and_cache(rt):
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return ollama_reply("ahoj")
    b = Brain(providers=[ProviderCfg(id="o", preset="ollama", base_url="http://o", model="m:7b")], chain=["o"], first_token_timeout=2)
    r = Router(b, lambda _: "", httpx.MockTransport(handler))
    r.local_queue = aiplus.InferenceQueue()
    r.cache = aiplus.AICache(rt.db)
    msgs = [{"role": "user", "content": "kolik je hodin"}]
    assert await r.complete(msgs, cache=True) == "ahoj"
    assert await r.complete(msgs, cache=True) == "ahoj"
    assert len(calls) == 1 and r.cache.stats() == {"entries": 1, "hits": 1}
    assert await r.complete(msgs) == "ahoj" and len(calls) == 2           # no cache unless asked
    assert r.local_queue.served["interactive"] == 2 and not r.local_queue.status()["busy"]
    assert r.cache.clear() == 1


def test_cache_expiry_and_cap(rt):
    c = aiplus.AICache(rt.db, ttl_s=100, max_rows=3)
    for i in range(5):
        c.put(f"k{i}", f"t{i}")
    assert c.stats()["entries"] == 3 and c.get("k0") is None and c.get("k4") == "t4"
    rt.db.exec("UPDATE ai_cache SET ts=ts-1000 WHERE k='k4'")
    assert c.get("k4") is None
    c.put("prazdne", "  ")
    assert c.get("prazdne") is None


def test_local_should_yield():
    assert "obrazovku" in aiplus.local_should_yield({"fullscreen": True})
    assert "baterie" in aiplus.local_should_yield({"battery": 20, "plugged": False})
    assert aiplus.local_should_yield({"battery": 20, "plugged": True}) == ""
    assert "RAM" in aiplus.local_should_yield({"ram_percent": 95})


def test_adaptive_gate_steps_aside_only_with_alternative(rt, monkeypatch):
    rt.cfg.brain.providers = [ProviderCfg(id="cloud", preset="custom", base_url="http://c/v1", model="m"),
                              ProviderCfg(id="o", preset="ollama", model="m")]
    rt.router.update(rt.cfg.brain)
    monkeypatch.setattr(aiplus, "local_should_yield", lambda snap: "běží hra nebo video přes celou obrazovku")
    rt.router._aiplus = False
    rt.router.gate = None
    aiplus.install(rt)
    local = next(p for p in rt.router.providers() if p.id == "o")
    cloud = next(p for p in rt.router.providers() if p.id == "cloud")
    assert "ustupuje" in rt.router.gate(local) and rt.router.gate(cloud) == ""
    rt.cfg.brain.adaptive_local = False
    assert rt.router.gate(local) == ""


def test_knowledge_packs(rt, tmp_path):
    src = tmp_path / "manual.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("kotel/navod.txt", "Kotel Thermona: tlak vody má být 1,5 baru. Chyba E04 znamená nízký tlak.")
        z.writestr("../utek.txt", "ven")
        z.writestr("virus.exe", "MZ")
    r = aiplus.install_pack(src, "Kotel")
    assert r["files"] == 1 and not (tmp_path / "utek.txt").exists()
    with pytest.raises(ValueError):
        aiplus.install_pack(src, "Kotel")
    assert aiplus.list_packs()[0]["name"] == "Kotel"
    assert aiplus.remove_pack("Kotel") and not aiplus.list_packs()
    assert not aiplus.remove_pack("../..")


async def test_pack_tools_search(rt, tmp_path):
    d = tmp_path / "wiki"
    d.mkdir()
    (d / "rostliny.md").write_text("Fíkus se zalévá jednou týdně, nesnáší průvan.", encoding="utf-8")
    r = await tools.call("knowledge_pack_add", {"source": str(d), "name": "Rostliny"}, rt)
    assert r.ok and r.data["index"]["chunks"] >= 1
    hits = await tools.call("search_documents", {"query": "fikus zalevat"}, rt)
    assert hits.ok and "rostliny.md" in hits.summary
    r = await tools.call("knowledge_packs", {"remove": "Rostliny"}, rt)
    assert r.ok
    assert (await tools.call("search_documents", {"query": "fikus"}, rt)).data == []


def test_webhook_verify():
    h = aiplus.new_webhook("Shop")
    body = b'{"order": {"id": 7, "total": 990}}'
    assert aiplus.verify_webhook(h, body, token=h["secret"])
    assert not aiplus.verify_webhook(h, body, token="spatny")
    sig = "sha256=" + hmac.new(h["secret"].encode(), body, hashlib.sha256).hexdigest()
    assert aiplus.verify_webhook(h, body, signature=sig) and not aiplus.verify_webhook(h, body + b" ", signature=sig)
    assert aiplus.summarize_payload(body)["text"] == "order.id: 7; order.total: 990"
    with pytest.raises(ValueError):
        aiplus.new_webhook("x", "shell")


async def test_webhook_endpoint_feeds_automations(rt, vault):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    r = await tools.call("webhook_create", {"name": "Eshop"}, rt)
    assert r.ok and "/api/hook/" in r.summary
    hid = r.data["id"]
    secret = vault[aiplus.secret_key(hid)]
    assert secret not in r.summary and rt.cfg.integrations.webhooks[0].name == "Eshop"
    assert secret not in json.dumps(rt.cfg.model_dump())                      # the secret is only in the vault
    assert rt.platform.clipboard.endswith(secret)
    q = rt.bus.subscribe()
    client = TestClient(create_app(rt, manage_runtime=False))
    assert client.post(f"/api/hook/{hid}", content=b'{"a": 1}').status_code == 401
    assert client.post("/api/hook/neznamy?token=x", content=b"{}").status_code == 404
    res = client.post(f"/api/hook/{hid}?token={secret}", content=b'{"order": "nova objednavka"}')
    assert res.status_code == 200
    evs = []
    while not q.empty():
        evs.append(q.get_nowait())
    hook_ev = next(e for e in evs if e["type"] == "webhook")
    assert hook_ev["name"] == "Eshop" and "nova objednavka" in hook_ev["text"]
    assert any(e["type"] == "notify" for e in evs)
    a = Automation(id="a1", name="Objednávka", trigger=AutoTrigger(type="webhook", value="eshop", text="objednavka"))
    assert automations.match_event(a, hook_ev) == {"sender": "Eshop", "text": hook_ev["text"]}
    assert "webhook „eshop“" in automations.describe_trigger(a.trigger)
    r = await tools.call("webhooks", {"remove": "Eshop"}, rt)
    assert r.ok and not rt.cfg.integrations.webhooks and aiplus.secret_key(hid) not in vault


def test_webhook_rate_limit(rt, vault):
    rt.cfg.integrations.webhooks = [Webhook(id="h1", name="Spam", action="automation")]
    vault[aiplus.secret_key("h1")] = "s3cret"
    aiplus._HOOK_HITS.clear()
    codes = [aiplus.handle_webhook(rt, "h1", b"{}", "s3cret")[0] for _ in range(32)]
    assert codes[:30] == [200] * 30 and codes[-1] == 429
    assert aiplus.handle_webhook(rt, "h1", b"x" * 300_000, "s3cret")[0] == 413


async def test_event_replay(rt):
    rt.cfg.automations.items = [Automation(id="a", name="Šéf píše", trigger=AutoTrigger(type="mail", value="šéf")),
                                Automation(id="b", name="Doma", trigger=AutoTrigger(type="zone_enter", value="Domov"))]
    aiplus.record_event(rt, {"type": "mail_new", "from": "šéf@firma.cz", "subject": "Porada", "body": "x" * 9000})
    aiplus.record_event(rt, {"type": "phone_zone", "zone": "Práce", "event": "enter"})
    evs = aiplus.recent_events(rt)
    assert [e["type"] for e in evs] == ["phone_zone", "mail_new"] and "body" not in evs[1]["data"]
    r = aiplus.replay(rt, evs[1]["id"])
    assert [h["automation"] for h in r["would_fire"]] == ["Šéf píše"]
    assert aiplus.replay(rt, evs[0]["id"])["would_fire"] == []
    t = await tools.call("event_replay", {"event_id": evs[1]["id"]}, rt)
    assert t.ok and "Šéf píše" in t.summary
    with pytest.raises(KeyError):
        aiplus.replay(rt, 999)


SPEC = {"openapi": "3.0.0", "info": {"version": "1"}, "servers": [{"url": "https://shop.test/api"}],
        "paths": {"/orders/{id}": {"get": {"operationId": "getOrder", "parameters": [{"name": "id", "in": "path", "required": True}],
                                           "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Order"}}}}}}}},
        "components": {"schemas": {"Order": {"type": "object", "required": ["id", "state"],
                                             "properties": {"id": {"type": "integer"}, "state": {"type": "string", "enum": ["nová", "odeslaná"]},
                                                            "items": {"type": "array", "items": {"type": "string", "example": "kafe"}}}}}}}


async def test_connector_sandbox(rt, vault, monkeypatch):
    sent = []
    monkeypatch.setattr(httpx.AsyncClient, "send", _no_real(httpx.AsyncClient.send, sent))
    gateway.import_spec("Shop", SPEC, auth="bearer")
    r = await tools.call("connector_sandbox", {"name": "Shop", "operation": "getOrder", "params": {"id": 5}}, rt)
    assert r.ok and r.data["response"] == {"id": 1, "state": "nová", "items": ["kafe"]}
    assert r.data["contract"]["ok"] and r.data["request"]["url"] == "https://shop.test/api/orders/5"
    assert r.data["request"]["headers"]["authorization"] == "***"
    assert not sent                                                          # no real network call
    bad = await tools.call("connector_sandbox", {"name": "Shop", "operation": "getOrder"}, rt)
    assert not bad.ok and "Chybí parametr" in bad.summary


def _no_real(orig, sent):
    async def send(self, request, **kw):
        if not isinstance(self._transport, httpx.MockTransport):
            sent.append(str(request.url))
            raise AssertionError("skutečná síť")
        return await orig(self, request, **kw)
    return send


def test_curl_to_spec():
    r = aiplus.curl_to_spec("curl -X POST 'https://api.firma.cz/v2/tasks?project=7' -H 'Authorization: Bearer abc.def.ghi' "
                            "-H 'Content-Type: application/json' -d '{\"title\": \"Nákup\"}'")
    op = r["spec"]["paths"]["/v2/tasks"]["post"]
    assert r["auth"] == "bearer" and r["base_url"] == "https://api.firma.cz" and r["secret_values"] == ["abc.def.ghi"]
    assert op["parameters"][0]["name"] == "project" and op["requestBody"]["content"]["application/json"]["example"] == {"title": "Nákup"}
    assert "abc.def.ghi" not in json.dumps(r["spec"])
    q = aiplus.curl_to_spec("curl https://api.x.io/items?api_key=SECRET1&limit=5")
    assert q["auth"] == "query" and q["header"] == "api_key" and "SECRET1" not in json.dumps(q["spec"]) and q["spec"]["paths"]["/items"]["get"]
    with pytest.raises(ValueError):
        aiplus.curl_to_spec("wget https://x")


async def test_connector_from_curl_tool(rt):
    r = await tools.call("connector_from_curl", {"name": "Firma", "curl": "curl -H 'X-API-Key: k123' https://api.firma.cz/v1/stats"}, rt)
    assert r.ok and "api_set_key" in r.summary and "k123" not in r.summary
    conn = gateway.load("Firma")
    assert conn["auth"] == "header" and conn["header"] == "X-API-Key"


async def test_queue_tool(rt):
    r = await tools.call("ai_queue", {}, rt)
    assert r.ok and "Mezipaměť" in r.summary
    r = await tools.call("gpu_split", {"model": "llama3.1:8b", "vram_gb": 6}, rt)
    assert r.ok and r.data["gpu_layers"] > 0 and rt.cfg.brain.local_gpu_layers == -1
    assert tools.REGISTRY["gpu_split"].danger_if({"apply": True})
