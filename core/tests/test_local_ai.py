import asyncio
import json

import httpx
import pytest
from conftest import drain

from jarvis.llm import local


def _rt_with(rt, handler):
    rt.local.transport = httpx.MockTransport(handler)
    return rt.local


async def test_status_not_running(rt):
    def h(req):
        raise httpx.ConnectError("refused", request=req)

    st = await _rt_with(rt, h).status()
    assert st["running"] is False and st["catalog"] and st["installed"] == []
    assert st["recommended"][0] == "qwen2.5:3b"


async def test_status_lists_installed_and_loaded(rt):
    def h(req):
        p = req.url.path
        if p == "/api/version":
            return httpx.Response(200, json={"version": "0.12.0"})
        if p == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b", "size": 1_929_000_000}]})
        if p == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b", "size_vram": 2_000_000_000}]})
        return httpx.Response(404)

    st = await _rt_with(rt, h).status()
    assert st["running"] and st["version"] == "0.12.0"
    assert st["installed"] == [{"name": "qwen2.5:3b", "size_gb": 1.9}]
    assert st["loaded"] == [{"name": "qwen2.5:3b", "size_vram_gb": 2.0}]


async def test_pull_progress_and_cancel(rt):
    started = asyncio.Event()

    async def stream():
        for i in range(1, 50):
            yield (json.dumps({"status": "pulling", "total": 100, "completed": i * 2}) + "\n").encode()
            started.set()
            await asyncio.sleep(0.02)

    def h(req):
        assert req.url.path == "/api/pull"
        return httpx.Response(200, content=stream())

    mgr = _rt_with(rt, h)
    q = rt.bus.subscribe()
    task = asyncio.create_task(mgr.pull("qwen2.5:3b"))
    await asyncio.wait_for(started.wait(), 2)
    await asyncio.sleep(0.1)
    mgr.cancel_pull()
    await asyncio.wait_for(task, 2)
    ev = [e for e in drain(q) if e["type"] == "local_pull_progress"]
    done = [e["completed"] for e in ev if "completed" in e and not e.get("cancelled")]
    assert len(done) >= 2 and done == sorted(done)
    assert ev[-1].get("cancelled") is True


async def test_gpu_test_cpu_only(rt):
    def h(req):
        if req.url.path == "/api/generate":
            return httpx.Response(200, json={"response": "ok", "done": True})
        if req.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b", "size_vram": 0}]})
        return httpx.Response(200, json={})

    msg = await _rt_with(rt, h).gpu_test()
    assert "jen na procesoru" in msg and rt.cfg.brain.local_gpu == "cpu"


async def test_gpu_test_gpu(rt):
    def h(req):
        if req.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b", "size_vram": 3_200_000_000}]})
        return httpx.Response(200, json={"response": "ok", "done": True})

    msg = await _rt_with(rt, h).gpu_test()
    assert "GPU" in msg and "3.2" in msg.replace(",", ".") and rt.cfg.brain.local_gpu == "gpu"


@pytest.mark.parametrize("mode,expected", [
    ("eco", ({"num_ctx": 2048, "num_thread": 3}, "1m")),
    ("balanced", ({"num_ctx": 4096, "num_thread": 6}, "5m")),
    ("performance", ({"num_ctx": 8192, "num_thread": 11}, "30m")),
])
def test_mode_options(mode, expected):
    assert local.mode_options(mode, 12) == expected


def test_mode_options_few_cores():
    assert local.mode_options("eco", 4)[0]["num_thread"] == 2


def test_bootstrap_never_pulls(monkeypatch):
    from jarvis import bootstrap

    calls = []
    monkeypatch.setattr(bootstrap, "_up", lambda url: True)
    monkeypatch.setattr(bootstrap.httpx, "get", lambda url, timeout=5: httpx.Response(200, json={"models": []},
                                                                                         request=httpx.Request("GET", url)))
    monkeypatch.setattr(bootstrap.httpx, "stream", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError))
    published = []
    out = bootstrap.ensure_ollama_model("http://localhost:11434", "qwen2.5:3b",
                                        publish=lambda t, **d: published.append((t, d)))
    assert calls == [] and out == "chybí model"
    assert published == [("local_model_missing", {"name": "qwen2.5:3b", "size_gb": 1.9})]


def test_router_skips_local_when_disabled(rt):
    rt.update_config({"brain": {"local_enabled": False}})
    ids = [p.id for p in rt.router.providers()]
    assert "ollama" not in ids and "omniroute" in ids


def test_recommend():
    assert all(m["size_gb"] <= 3.5 for m in local.MODELS if m["name"] in local.recommend({"ram_gb": 8}))
    big = local.recommend({"ram_gb": 32})
    assert "qwen2.5:7b" in big and big[0] == "qwen2.5:3b"


async def test_ollama_sends_mode_options(rt):
    from jarvis.llm.ollama import Ollama

    seen = {}

    def h(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, content=b'{"message":{"content":"ahoj"},"done":true}\n')

    o = Ollama("ollama", "http://x:11434", "qwen2.5:3b", transport=httpx.MockTransport(h),
               options={"num_ctx": 2048, "num_thread": 2}, keep_alive="1m")
    out = [c async for c in o.stream([{"role": "user", "content": "hi"}], None)]
    assert out and seen["options"]["num_ctx"] == 2048 and seen["keep_alive"] == "1m"


def test_ws_local_status(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    def h(req):
        raise httpx.ConnectError("refused", request=req)

    rt.local.transport = httpx.MockTransport(h)
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_json({"type": "local_status"})
            m = ws.receive_json()
            while m["type"] != "local_info":
                m = ws.receive_json()
            assert m["running"] is False and m["catalog"]
