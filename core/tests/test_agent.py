import asyncio

from conftest import FakeRouter, drain

from jarvis.agent import MAX_ROUNDS
from jarvis.llm.base import AllProvidersFailed


async def test_plain_answer(rt):
    rt.router = FakeRouter(["Dobrý den, pane."])
    q = rt.bus.subscribe()
    out = await rt.agent.handle("ahoj")
    assert out.strip() == "Dobrý den, pane."
    types = [e["type"] for e in drain(q)]
    assert types[0] == "user_message" and "assistant_delta" in types and "assistant_done" in types
    assert [m["role"] for m in rt.memory.recent()] == ["user", "assistant"]


async def test_tool_then_answer(rt, monkeypatch):
    from jarvis.tools import youtube

    monkeypatch.setattr(youtube, "search_youtube", lambda q, n=1: [{"id": "X1", "title": "Trailer", "channel": "", "duration": 1}])
    rt.router = FakeRouter([[("youtube_play", {"query": "avengers"})], "Pouštím trailer."])
    q = rt.bus.subscribe()
    out = await rt.agent.handle("pusť avengers trailer")
    assert "Pouštím" in out
    ev = drain(q)
    assert any(e["type"] == "tool_start" and e["name"] == "youtube_play" for e in ev)
    assert ("open_url", "https://www.youtube.com/watch?v=X1&autoplay=1") in rt.platform.calls
    second = rt.router.calls[1]["messages"]
    assert second[-1]["role"] == "tool" and second[-2]["tool_calls"][0]["function"]["name"] == "youtube_play"


async def test_round_limit(rt):
    rt.router = FakeRouter([[("get_time", {})]] * 20)
    await rt.agent.handle("smyčka")
    assert len(rt.router.calls) == MAX_ROUNDS + 1
    assert rt.router.calls[-1]["tools"] is None


async def test_danger_rejected(rt):
    rt.router = FakeRouter([[("system_power", {"action": "shutdown"})], "Dobře, nevypínám."])
    q = rt.bus.subscribe()
    task = asyncio.create_task(rt.agent.handle("vypni počítač"))
    for _ in range(50):
        await asyncio.sleep(0.01)
        ev = [e for e in drain(q) if e["type"] == "confirm_request"]
        if ev:
            assert rt.agent.confirm(ev[0]["id"], False)
            break
    await task
    assert ("power", "shutdown") not in rt.platform.calls


async def test_danger_approved(rt):
    rt.router = FakeRouter([[("system_power", {"action": "shutdown"})], "Vypínám."])
    q = rt.bus.subscribe()
    task = asyncio.create_task(rt.agent.handle("vypni počítač"))
    for _ in range(50):
        await asyncio.sleep(0.01)
        ev = [e for e in drain(q) if e["type"] == "confirm_request"]
        if ev:
            rt.agent.confirm(ev[0]["id"], True)
            break
    await task
    assert ("power", "shutdown") in rt.platform.calls


async def test_confirm_timeout(rt, monkeypatch):
    import jarvis.agent as ag

    monkeypatch.setattr(ag, "CONFIRM_TIMEOUT", 0.05)
    rt.router = FakeRouter([[("run_shell", {"command": "rm -rf"})], "Nic."])
    await rt.agent.handle("smaž vše")
    assert not any(c[0] == "run_shell" for c in rt.platform.calls)


async def test_no_brain(rt):
    rt.router = FakeRouter([AllProvidersFailed({"omniroute": "down", "ollama": "down"})])
    q = rt.bus.subscribe()
    out = await rt.agent.handle("ahoj")
    assert "nemám spojení" in out
    assert any(e["type"] == "error" for e in drain(q))


async def test_attachment_image_needs_vision(rt):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, "PNG")
    att = await rt.store.save("a.png", buf.getvalue(), "image/png")
    rt.router = FakeRouter(["Vidím černý čtverec."])
    await rt.agent.handle("co je na obrázku?", [att.id])
    call = rt.router.calls[0]
    assert call["need_vision"]
    assert any(p.get("type") == "image_url" for p in call["messages"][-1]["content"])


async def test_tool_attachments_returned(rt):
    rt.router = FakeRouter([[("screenshot", {})], "Tady je snímek."])
    q = rt.bus.subscribe()
    await rt.agent.handle("pošli screenshot")
    done = [e for e in drain(q) if e["type"] == "assistant_done"][0]
    assert len(done["attachments"]) == 1 and done["attachments"][0]["thumb"]


async def test_stop_cancels(rt):
    class Slow(FakeRouter):
        async def stream(self, *a, **k):
            from jarvis.llm.base import Chunk

            yield Chunk(text="začínám")
            await asyncio.sleep(10)
            yield Chunk(done=True)

    rt.router = Slow([])
    task = asyncio.create_task(rt.agent.handle("dlouhá odpověď"))
    await asyncio.sleep(0.05)
    rt.agent.stop()
    out = await task
    assert "přerušeno" in out
