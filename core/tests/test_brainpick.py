"""3.14 Kdo odpovídá: a click (or "přepni na Ollamu") picks the brain; its models switch right in JARVIS."""
import httpx
from conftest import FakeRouter

from jarvis import brainpick, instant, tools

tools.load_builtin()


def ids(rt):
    return [p.id for p in rt.router.providers()]


def test_claude_is_added_and_answers_first(rt):
    res = brainpick.use(rt, "anthropic")
    assert res["preset"] == "anthropic" and res["model"] == "claude-opus-5-5"
    assert ids(rt)[0] == res["id"] and rt.cfg.brain.chain[0] == res["id"]
    assert not res["key"] and any("console.anthropic.com" in n for n in res["notes"])   # says where the key comes from
    res = brainpick.use(rt, "anthropic", "claude-sonnet-5-5")
    assert rt.router.providers()[0].model == "claude-sonnet-5-5"
    assert sum(1 for p in rt.cfg.brain.providers if p.preset == "anthropic") == 1          # not added twice


def test_ollama_turns_local_ai_on_and_cloud_lifts_offline(rt):
    rt.update_config({"brain": {"local_enabled": False}})
    brainpick.use(rt, "ollama", "qwen3:8b")
    assert rt.cfg.brain.local_enabled and ids(rt)[0] == "ollama" and rt.router.providers()[0].model == "qwen3:8b"
    rt.update_config({"brain": {"offline_only": True}})
    res = brainpick.use(rt, "groq")
    assert not rt.cfg.brain.offline_only and any("Jen offline" in n for n in res["notes"])


def test_only_this_brain(rt):
    brainpick.use(rt, "ollama", only=True)
    assert rt.cfg.brain.only_primary and brainpick.current(rt)["only"]
    brainpick.use(rt, "ollama", only=False)
    assert not rt.cfg.brain.only_primary


async def test_router_uses_only_the_picked_brain(rt):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url.host)
        return httpx.Response(500, json={"error": "down"})

    from jarvis.llm.router import Router

    brainpick.use(rt, "groq")
    rt.update_config({"brain": {"only_primary": True}})
    r = Router(rt.cfg.brain, lambda _: "k", httpx.MockTransport(handler))
    try:
        async for _ in r.stream([{"role": "user", "content": "ahoj"}], None):
            pass
    except Exception:  # noqa: BLE001 – all fail here; what matters is who was asked
        pass
    assert seen and set(seen) == {"api.groq.com"}


async def test_claude_models_and_ollama_models(rt):
    out = await brainpick.models(rt, "anthropic")
    assert [m["id"] for m in out["models"]] == ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-2"]

    def handler(req: httpx.Request):
        assert req.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [
            {"name": "qwen3:8b", "size": 5_200_000_000, "details": {"parameter_size": "8.2B"}},
            {"name": "nomic-embed-text:latest", "size": 270_000_000, "details": {"parameter_size": "137M"}}]})

    rt.transport = httpx.MockTransport(handler)
    out = await brainpick.models(rt, "ollama")
    assert [m["id"] for m in out["models"]] == ["qwen3:8b"]                 # embedding models are not brains

    rt.transport = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    out = await brainpick.models(rt, "ollama")
    assert out["models"] == [] and "Ollama neběží" in out["error"]


def test_tiles(rt):
    brainpick.use(rt, "ollama")
    t = {x["preset"]: x for x in brainpick.tiles(rt)}
    assert t["ollama"]["active"] and t["ollama"]["key"] and t["anthropic"]["needs_key"] and not t["anthropic"]["active"]


def test_instant_switch_phrases():
    def call(text):
        p = instant.plan(text)
        return p.calls[0] if p else None

    assert call("přepni na ollamu") == ("brain_switch", {"brain": "ollama"})
    assert call("použij Claude Sonnet") == ("brain_switch", {"brain": "anthropic", "model": "claude-sonnet-5-5"})
    assert call("přepni model na qwen3:8b") == ("brain_switch", {"model": "qwen3:8b"})
    assert call("přepni na ollamu qwen3:8b") == ("brain_switch", {"brain": "ollama", "model": "qwen3:8b"})
    assert call("přepni na další písničku") is None and call("použij google") is None


async def test_switch_tool(rt):
    r = await tools.call("brain_switch", {"brain": "claude", "model": "claude-haiku-5-5"}, rt)
    assert r.ok and "Claude" in r.summary and rt.router.providers()[0].model == "claude-haiku-5-5"
    r = await tools.call("brain_switch", {}, rt)
    assert r.ok and "claude-haiku-5-5" in r.summary


async def test_switch_by_voice_works_without_the_ai(rt):
    rt.router = FakeRouter([RuntimeError("the AI is down")])
    await rt.agent.handle("přepni na ollamu", [], "chat")
    assert rt.cfg.brain.chain[0] == "ollama"
