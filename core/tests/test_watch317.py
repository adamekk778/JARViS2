"""3.17 Hodinky (návrh 20): the way in from a Wear OS watch – a quiet notice with ready questions, the answer comes back
as a notice you can answer again (the phone's notices are what the watch shows)."""
from __future__ import annotations

from pathlib import Path

from jarvis import tools


async def test_watch_entry_goes_to_the_phone(rt, monkeypatch):
    tools.load_builtin()
    pushed: list[tuple[str, dict]] = []
    monkeypatch.setattr(rt, "phone_push", lambda kind, **d: pushed.append((kind, d)) or True)
    r = await tools.call("watch_ask", {}, rt)
    assert r.ok and pushed[0][0] == "notify"
    d = pushed[0][1]
    assert d["quiet"] is True and d["actions"] == [] and 1 <= len(d["quick"]) <= 5 and "Co mám dnes v plánu?" in d["quick"]
    pushed.clear()
    r = await tools.call("watch_ask", {"questions": ["Kolik je hodin?", "  ", "x" * 200]}, rt)
    assert pushed[0][1]["quick"] == ["Kolik je hodin?", "x" * 60]


async def test_without_the_phone_it_says_so(rt, monkeypatch):
    tools.load_builtin()
    monkeypatch.setattr(rt, "phone_push", lambda kind, **d: False)
    r = await tools.call("watch_ask", {}, rt)
    assert not r.ok and "Telefon" in r.summary


async def test_a_question_from_the_watch_is_answered_back_to_it(rt, monkeypatch):
    import asyncio

    from conftest import FakeRouter

    rt.router = FakeRouter(["Tiskárna tiskne, zbývá hodina."])
    pushed: list[tuple[str, dict]] = []
    tasks: list[asyncio.Task] = []
    monkeypatch.setattr(rt, "phone_push", lambda kind, **d: pushed.append((kind, d)) or True)
    monkeypatch.setattr(rt, "submit", lambda coro: tasks.append(asyncio.get_running_loop().create_task(coro)))
    await rt.notice_action("ask", {"text": "Řekni mi, jak to vypadá s tou dlouhou prací", "from_phone": True})
    await asyncio.wait_for(asyncio.gather(*tasks), 10)
    notes = [d for k, d in pushed if k == "notify"]
    assert notes and "zbývá hodina" in notes[0]["body"]                     # back as a notice → "Odpovědět" again


def test_the_phone_app_shows_it_quietly_with_the_choices():
    src = (Path(__file__).resolve().parents[2] / "mobile" / "native" / "JarvisLink.java").read_text(encoding="utf-8")
    assert 'cmd.optBoolean("quiet", false), cmd.optJSONArray("quick")' in src
    assert "IMPORTANCE_LOW" in src and "rb.setChoices(cs)" in src
