"""Groq kept saying "no brain" after one message: every message carried all ~650 tools (~85 000 tokens) while the
free tier allows ~8 000 a minute and ~200 000 a day. Now a message carries a small, fitting set of tools; a short
rate limit is waited out; a model used up for the day is swapped for another Groq model."""
import json

import httpx

from jarvis import tools
from jarvis.config import Brain, ProviderCfg
from jarvis.llm import router as router_mod
from jarvis.llm.router import Router
from jarvis.tools import select as sel

tools.load_builtin()


def sse(text):
    body = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': t}}]})}\n\n" for t in text.split(" ")) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


def groq_brain():
    return Brain(providers=[ProviderCfg(id="groq", preset="groq", model="openai/gpt-oss-120b")], chain=["groq"],
                 first_token_timeout=5)


async def collect(r):
    out = ""
    async for ch in r.stream([{"role": "user", "content": "ahoj"}], None):
        out += ch.text
    return out


def test_a_message_carries_a_small_fitting_set_of_tools(rt):
    all_size = len(json.dumps(tools.schemas(rt.cfg.tools.disabled, rt.cfg), ensure_ascii=False))
    for text, must in [("pošli e-mail Petrovi", "email_send"), ("napiš mi web pro pekárnu", "make_website"),
                       ("najdi duplicitní fotky", "find_duplicates"), ("zavolej mámě", "phone_call"),
                       ("pusť na youtube lofi", "youtube_play")]:
        s = rt.agent._tool_schemas(text)
        names = [x["function"]["name"] for x in s]
        assert must in names and "find_tools" in names and len(names) <= 45
        assert len(json.dumps(s, ensure_ascii=False)) < all_size / 12      # was ~264 000 characters every time


def test_disabled_tools_are_never_offered(rt):
    rt.cfg.tools.disabled = ["email_send"]
    assert "email_send" not in [x["function"]["name"] for x in rt.agent._tool_schemas("pošli e-mail")]


async def test_find_tools_lists_what_fits(rt):
    from types import SimpleNamespace

    res = await tools.call("find_tools", {"query": "převést video do mp4"}, SimpleNamespace(cfg=rt.cfg, rt=rt, knowledge=None))
    assert res.ok and res.data["tools"] and all(n in tools.REGISTRY for n in res.data["tools"])


async def test_agent_adds_found_tools_for_the_next_step(rt):
    """The AI calls find_tools → the tools it found go with the next request."""
    from jarvis.llm.base import Chunk, ToolCall

    sent = []

    async def fake_stream(msgs, tools_, **kw):
        sent.append([t["function"]["name"] for t in tools_ or []])
        if len(sent) == 1:
            yield Chunk(tool_calls=[ToolCall("c1", "find_tools", {"query": "duplicitní soubory"})], done=True)
        else:
            yield Chunk(text="Hotovo", done=True)

    rt.router.stream = fake_stream
    await rt.agent.handle("ukliď mi disk", [], "chat")
    assert "find_duplicates" not in sent[0] and "find_duplicates" in sent[1]


async def test_short_rate_limit_is_waited_out(monkeypatch):
    waits, calls = [], []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr(router_mod.asyncio, "sleep", fake_sleep)

    def handler(req):
        calls.append(json.loads(req.content)["model"])
        if len(calls) == 1:
            return httpx.Response(429, text='{"error":{"message":"Rate limit reached ... on tokens per minute (TPM): '
                                            'Limit 8000, Used 7000, Requested 4000. Please try again in 6.5s."}}')
        return sse("ahoj")

    r = Router(groq_brain(), lambda _: "gsk_x", httpx.MockTransport(handler))
    assert await collect(r) == "ahoj"
    assert calls == ["openai/gpt-oss-120b"] * 2 and waits and 6.5 <= waits[0] < 8


async def test_daily_limit_switches_to_another_groq_model_and_remembers():
    calls = []

    def handler(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m} for m in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "whisper-large-v3")]})
        model = json.loads(req.content)["model"]
        calls.append(model)
        if model == "openai/gpt-oss-120b":
            return httpx.Response(429, text='{"error":{"message":"Rate limit reached ... on tokens per day (TPD): '
                                            'Limit 200000, Used 199000. Please try again in 41m12s."}}')
        return sse("jsemtu")

    r = Router(groq_brain(), lambda _: "gsk_x", httpx.MockTransport(handler))
    assert await collect(r) == "jsemtu"
    assert calls == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    calls.clear()
    assert await collect(r) == "jsemtu"
    assert calls == ["openai/gpt-oss-20b"]                 # the used-up model is not asked again for now


def test_retry_after_parsing():
    f = router_mod.retry_after
    assert f(Exception("Please try again in 7.66s.")) == 7.66
    assert f(Exception("Please try again in 1m12.5s")) == 72.5
    assert f(Exception("try again in 450ms")) == 0.45
    assert f(Exception("boom")) is None


def test_search_matches_word_starts():
    assert "make_website" in sel.search(tools.REGISTRY, "web pro pekárnu", 10)


async def test_a_broken_tool_call_is_asked_again_and_tools_stay_on():
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(bool(body.get("tools")))
        if len(calls) == 1:
            return httpx.Response(400, text='{"error":{"message":"Failed to call a function. Please adjust your prompt.",'
                                            '"code":"tool_use_failed"}}')
        return sse("ok")

    r = Router(groq_brain(), lambda _: "gsk_x", httpx.MockTransport(handler))
    out = ""
    async for ch in r.stream([{"role": "user", "content": "ahoj"}], [{"type": "function", "function": {"name": "x", "parameters": {}}}]):
        out += ch.text
    assert out == "ok" and calls == [True, True] and "groq" not in r.no_tools


# ---------- a fake Groq that counts tokens per minute per model, like the real free tier ----------
class FakeGroq:
    """Refuses like Groq: a request over the model's minute → 413; the minute used up → 429 'try again in Ns'."""

    def __init__(self, clock):
        self.clock = clock
        self.used: dict[str, list[tuple[float, int]]] = {}
        self.models_seen: list[str] = []
        self.step = 0

    def handler(self, req):
        from jarvis.llm import budget

        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m} for m in budget.GROQ_TPM]})
        body = json.loads(req.content)
        model = body["model"]
        limit = budget.GROQ_TPM[model]
        asked = len(req.content.decode()) // 3 + body.get("max_tokens", 0)
        now = self.clock[0]
        window = [(t, n) for t, n in self.used.get(model, []) if now - t < 60]
        self.used[model] = window
        if asked > limit:
            return httpx.Response(413, text=f'{{"error":{{"message":"Request too large for model `{model}` on tokens per minute '
                                            f'(TPM): Limit {limit}, Requested {asked}, please reduce your message size"}}}}')
        if sum(n for _, n in window) + asked > limit:
            wait = 60 - (now - window[0][0])
            return httpx.Response(429, text=f'{{"error":{{"message":"Rate limit reached for model `{model}` on tokens per minute '
                                            f'(TPM): Limit {limit}, Used {sum(n for _, n in window)}, Requested {asked}. '
                                            f'Please try again in {wait:.2f}s."}}}}')
        window.append((now, asked))
        self.models_seen.append(model)
        self.step += 1
        if body.get("tools") and self.step < 3:      # two tool steps, then the answer
            ev = {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": f"c{self.step}", "type": "function",
                  "function": {"name": "web_read", "arguments": json.dumps({"url": "https://example.com"})}}]}}]}
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=f"data: {json.dumps(ev)}\n\ndata: [DONE]\n\n".encode())
        return sse("Hotovo,recept_je_na_telefonu")


async def test_a_real_task_with_history_fits_groqs_free_limits(rt, monkeypatch):
    """The user's case: a task with tools and earlier chat on Groq's free tier must finish, not end with 'limit'."""
    from jarvis.llm import router as rmod
    from jarvis.tools.base import ToolResult

    clock = [1000.0]

    async def fake_sleep(s):
        clock[0] += s                                # waiting moves the fake minute on

    monkeypatch.setattr(rmod.asyncio, "sleep", fake_sleep)
    g = FakeGroq(clock)
    rt.cfg.brain.providers = [ProviderCfg(id="groq", preset="groq", model="openai/gpt-oss-120b")]
    rt.cfg.brain.chain = ["groq"]
    rt.router = Router(rt.cfg.brain, lambda _: "gsk_x", httpx.MockTransport(g.handler))
    for _ in range(10):                                # a normal chat history before the task
        rt.memory.add_message("user", "Najdi mi na webu nejlepší levné sluchátka do 1000 Kč a porovnej je " * 2)
        rt.memory.add_message("assistant", "Tady je přehled: " + "Sluchátka XY mají dobrý zvuk a výdrž 30 hodin. " * 12)

    async def big_page(ctx, url: str = "") -> ToolResult:
        return ToolResult(True, "Recept na svíčkovou: " + "Maso, kořenová zelenina, smetana. " * 400)   # ~14 000 chars

    monkeypatch.setitem(tools.REGISTRY, "web_read", tools.ToolSpec("web_read", "Přečte stránku.", big_page,
                                                                   {"type": "object", "properties": {"url": {"type": "string"}}}))
    answer = await rt.agent.handle("Najdi mi na webu recept na svíčkovou a pošli ho na telefon", [], "chat")
    assert "Hotovo" in answer and "limit" not in answer.lower()
    assert g.step >= 3


async def test_retries_used_up_say_limit_not_no_brain():
    from jarvis.llm.base import AllProvidersFailed

    def handler(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(429, text='{"error":{"message":"Rate limit reached ... Please try again in 3m2s."}}')

    r = Router(groq_brain(), lambda _: "gsk_x", httpx.MockTransport(handler))
    try:
        await collect(r)
        raise AssertionError("should fail")
    except AllProvidersFailed as e:
        assert e.errors.get("groq") and e.is_limit           # not "žádný poskytovatel není nastaven"


def test_fit_shrinks_a_big_request_under_the_limit_and_keeps_the_task():
    from jarvis.llm import budget

    msgs = [{"role": "system", "content": "S" * 4700}]
    for i in range(10):
        msgs += [{"role": "user", "content": f"stará otázka {i} " * 20}, {"role": "assistant", "content": "odpověď " * 120}]
    msgs += [{"role": "user", "content": "Najdi recept"}, {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
             {"role": "tool", "tool_call_id": "c1", "content": "x" * 14000}]
    tools_ = [tools.REGISTRY[n].schema() for n in list(tools.REGISTRY)[:32]]
    m2, t2, mt = budget.fit(msgs, tools_, 8000, 2048)
    assert budget.estimate(m2, t2) + mt <= 8000 and mt == 1024
    assert m2[0]["role"] == "system" and m2[-3]["content"] == "Najdi recept" and m2[-1]["role"] == "tool"


async def test_a_minute_limit_of_40_s_is_waited_out_and_the_user_told(monkeypatch):
    waits, told, calls = [], [], []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr(router_mod.asyncio, "sleep", fake_sleep)

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, text='{"error":{"message":"Rate limit reached ... tokens per minute (TPM): Limit 8000, '
                                            'Used 7900, Requested 3000. Please try again in 41.2s."}}')
        return sse("pokračuju")

    r = Router(groq_brain(), lambda _: "gsk_x", httpx.MockTransport(handler))
    r.on_wait = lambda pid, s: told.append((pid, round(s)))
    assert await collect(r) == "pokračuju"
    assert told == [("groq", 41)] and waits and waits[0] >= 41
