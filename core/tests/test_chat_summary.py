"""3.12 Chytřejší paměť chatu: a long chat's older part is summarised; requests carry the summary + recent messages."""
from jarvis import chatsummary


async def test_long_chat_gets_summarised_and_requests_use_the_summary(rt):
    asked = []

    async def fake_complete(msgs, **kw):
        asked.append((msgs, kw))
        return "Uživatel se jmenuje Adam, hledá sluchátka do 1000 Kč a domluvili jsme se na Sony."

    rt.router.complete = fake_complete
    for i in range(10):
        rt.memory.add_message("user", f"otázka {i} " + "o sluchátkách " * 30)
        rt.memory.add_message("assistant", f"odpověď {i} " + "Sony jsou dobré. " * 30)
    assert await chatsummary.refresh(rt) is True
    assert asked[0][1].get("fast") is True                       # the quick model (own allowance on Groq)
    history = rt.memory.recent(rt.cfg.memory.context_messages + 1)
    summary, rest = chatsummary.apply(rt, history)
    assert "Adam" in summary and len(rest) == chatsummary.KEEP   # only the newest messages word for word
    msgs, _ = await rt.agent._build_messages("a co ty Sony?", [], False, "")
    assert "Shrnutí dřívější části" in msgs[0]["content"] and len(msgs) == chatsummary.KEEP + 2


async def test_short_chat_and_private_mode_are_left_alone(rt):
    async def boom(*a, **k):
        raise AssertionError("no AI call for a short chat")

    rt.router.complete = boom
    for i in range(4):
        rt.memory.add_message("user", f"q{i}")
        rt.memory.add_message("assistant", f"a{i}")
    assert await chatsummary.refresh(rt) is False
    rt.memory.set_private(True)
    assert await chatsummary.refresh(rt) is False
    assert chatsummary.apply(rt, [{"role": "user", "text": "x", "created": 1}]) == ("", [{"role": "user", "text": "x", "created": 1}])


async def test_no_ai_means_no_summary_and_no_crash(rt):
    async def down(*a, **k):
        raise RuntimeError("offline")

    rt.router.complete = down
    for i in range(10):
        rt.memory.add_message("user", f"q{i}")
        rt.memory.add_message("assistant", f"a{i}")
    assert await chatsummary.refresh(rt) is False and chatsummary.load(rt) == {}
