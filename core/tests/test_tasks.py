import asyncio

from conftest import FakeRouter, drain

from jarvis.llm.base import AllProvidersFailed


class SlowRouter(FakeRouter):
    """Gives the test time to act between LLM rounds."""

    async def stream(self, messages, tools, need_vision=False, fast=False):
        await asyncio.sleep(0.1)
        async for ch in super().stream(messages, tools, need_vision, fast):
            yield ch


async def _wait_for(q, pred, timeout=2.0):
    seen = []
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        while not q.empty():
            e = q.get_nowait()
            seen.append(e)
            if pred(e):
                return e, seen
        await asyncio.sleep(0.01)
    raise AssertionError(f"event not seen; got {[e['type'] for e in seen]}")


async def test_text_answer_creates_no_task(rt):
    rt.router = FakeRouter(["Dobrý den."])
    await rt.agent.handle("ahoj")
    assert rt.tasks.list() == []


async def test_tool_call_creates_task(rt):
    rt.router = FakeRouter([[("get_time", {})], "Je 10:00. A ještě něco."])
    await rt.agent.handle("kolik je hodin")
    items = rt.tasks.list()
    assert len(items) == 1
    t = rt.tasks.get(items[0]["id"])
    assert t["status"] == "done" and t["goal"] == "kolik je hodin"
    assert t["summary"].startswith("Je 10:00")
    assert [(a["tool"], a["ok"]) for a in t["actions"]] == [("get_time", 1)]
    assert rt.tasks.current is None


async def test_update_plan(rt):
    rt.router = FakeRouter([[("update_plan", {"steps": ["a", "b", "c"], "current": 1})], [("get_time", {})], "Hotovo."])
    q = rt.bus.subscribe()
    await rt.agent.handle("udělej tři věci")
    ev = [e for e in drain(q) if e["type"] == "task_update"]
    assert any(e["task"]["steps"] and e["task"]["steps"][0]["status"] == "done"
               and e["task"]["steps"][1]["status"] == "running" for e in ev)
    final = rt.tasks.get(rt.tasks.list()[0]["id"])
    assert final["total"] == 3 and final["done"] == 3
    assert all(s["status"] == "done" for s in final["steps"])


async def test_pause_resume(rt):
    rt.router = SlowRouter([[("get_time", {})], [("get_time", {})], "Hotovo."])
    q = rt.bus.subscribe()
    task = asyncio.create_task(rt.agent.handle("dva kroky"))
    await _wait_for(q, lambda e: e["type"] == "tool_end")
    assert rt.tasks.pause()
    await asyncio.sleep(0.2)
    assert not any(e["type"] == "tool_start" for e in drain(q))
    assert rt.tasks.current["status"] == "paused"
    assert rt.tasks.resume()
    await asyncio.wait_for(task, 2)
    assert rt.tasks.get(rt.tasks.list()[0]["id"])["status"] == "done"


async def test_stop_while_paused(rt):
    rt.router = SlowRouter([[("get_time", {})], [("get_time", {})], "Hotovo."])
    q = rt.bus.subscribe()
    task = asyncio.create_task(rt.agent.handle("dva kroky"))
    await _wait_for(q, lambda e: e["type"] == "tool_end")
    rt.tasks.pause()
    await asyncio.sleep(0.05)
    rt.agent.stop()
    await asyncio.wait_for(task, 1)
    assert rt.tasks.get(rt.tasks.list()[0]["id"])["status"] == "cancelled"
    # the next request is not stuck behind the old pause
    rt.router = FakeRouter([[("get_time", {})], "Hotovo."])
    await asyncio.wait_for(rt.agent.handle("znovu"), 2)
    assert rt.tasks.list()[0]["status"] == "done"


async def test_failed_task(rt):
    rt.router = FakeRouter([[("get_time", {})], AllProvidersFailed({"x": "nedostupný"})])
    await rt.agent.handle("něco")
    assert rt.tasks.list()[0]["status"] == "failed"


async def test_args_redacted(rt):
    tid = rt.tasks.begin("cíl", "c1")
    rt.tasks.log_action("web_read", {"url": "https://x?token=ABCDEF0123456789abcdef"}, True, "ok", 5)
    t = rt.tasks.get(tid)
    assert "ABCDEF0123456789abcdef" not in t["actions"][0]["args"]


async def test_agent_mode_rounds(rt):
    rt.update_config({"agent": {"mode": True}})
    rt.router = FakeRouter([[("get_time", {})]] * 40)
    await rt.agent.handle("dlouhý úkol")
    assert len(rt.router.calls) == 26


async def test_list_filters_and_clear(rt):
    a = rt.tasks.begin("najdi PDF", "c1")
    rt.tasks.finish("done", "ok")
    rt.tasks.begin("smaž koš", "c1")
    rt.tasks.finish("failed", "chyba")
    assert [t["id"] for t in rt.tasks.list(q="pdf")] == [a]
    assert [t["goal"] for t in rt.tasks.list(status="failed")] == ["smaž koš"]
    assert rt.tasks.clear() == 2 and rt.tasks.list() == []
