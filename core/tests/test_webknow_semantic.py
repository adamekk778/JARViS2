"""Spec 2026-11-20 §5.15: search by meaning in what JARVIS read – only with a model the user chose to download."""
import asyncio

from jarvis.webknow import inject, semantic, study
from jarvis.webknow.store import Doc


def _fake(rt, monkeypatch, slow=False):
    async def model(_rt):
        return "paraphrase-multilingual"

    async def emb(m, texts):
        if slow:
            await asyncio.sleep(2)
        return [[1.0, 0.0] if ("robot" in t.lower() or "stroj" in t.lower()) else [0.0, 1.0] for t in texts]
    monkeypatch.setattr(semantic, "model", model)
    monkeypatch.setattr(rt.knowledge, "_embed", emb)


async def test_meaning_finds_other_words(rt, monkeypatch):
    _fake(rt, monkeypatch)
    rt.webknow.add(Doc(url="https://a.cz/r", title="Robot uvařil oběd", kind="read"))
    rt.webknow.add(Doc(url="https://a.cz/p", title="Počasí na víkend", kind="news"))
    assert await semantic.embed_pending(rt) == 2
    assert await semantic.embed_pending(rt) == 0
    hits = await semantic.search(rt, "stroj co umí vařit")
    assert hits[0]["url"] == "https://a.cz/r" and len(hits) == 1
    assert "Robot uvařil oběd" in await inject.block_for(rt, "ten stroj co umí vařit")


async def test_no_model_means_full_text_only(rt, monkeypatch):
    async def none(_rt):
        return ""
    monkeypatch.setattr(semantic, "model", none)
    rt.webknow.add(Doc(url="https://a.cz/r", title="Robot uvařil oběd", kind="read"))
    assert await semantic.embed_pending(rt) == 0 and await semantic.search(rt, "stroj") == []


async def test_budget_is_kept(rt, monkeypatch):
    _fake(rt, monkeypatch, slow=True)
    assert await semantic.search(rt, "stroj", budget_s=0.3) == []


async def test_fullscreen_postpones_embedding(rt, monkeypatch):
    _fake(rt, monkeypatch)
    monkeypatch.setattr(study, "_fullscreen", lambda: True)
    rt.webknow.add(Doc(url="https://a.cz/r", title="Robot uvařil oběd", kind="read"))
    assert await semantic.embed_pending(rt) == 0


async def test_forget_drops_vectors(rt, monkeypatch):
    _fake(rt, monkeypatch)
    rt.webknow.add(Doc(url="https://a.cz/r", title="Robot uvařil oběd", kind="read"))
    await semantic.embed_pending(rt)
    rt.webknow.forget(domain="a.cz")
    assert rt.db.one("SELECT COUNT(*) AS n FROM web_emb")["n"] == 0


async def test_model_picks_installed_multilingual(rt, monkeypatch):
    import httpx
    rt.transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}, {"name": "paraphrase-multilingual:latest"}]}))
    assert await semantic.model(rt) == "paraphrase-multilingual:latest"
    rt.transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]}))
    assert await semantic.model(rt) == ""


async def test_knowledge_search_and_forget_tools(rt, monkeypatch):
    from jarvis.tools import REGISTRY, call
    _fake(rt, monkeypatch)
    rt.webknow.add(Doc(url="https://a.cz/r", title="Robot uvařil oběd", kind="read", source="A"))
    await semantic.embed_pending(rt)
    r = await call("web_knowledge_search", {"query": "stroj co vaří"}, rt)
    assert r.ok and r.data[0]["url"] == "https://a.cz/r"
    assert REGISTRY["web_knowledge_forget"].danger
    assert rt.webknow.forget(everything=True) == 1
