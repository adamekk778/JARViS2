"""Spec 2026-11-20 §5.13: topic notebooks – the background, not just today's headlines."""
import datetime as dt

import httpx
from conftest import FakeRouter

from jarvis.webknow import notebooks, study
from jarvis.webknow.store import Doc


def _web(rt):
    def h(r):
        if "wikipedia" in r.url.host:
            return httpx.Response(200, json={"query": {"pages": {"1": {"title": "Valorant", "extract": "Valorant je hra od Riot Games.",
                                                                       "fullurl": "https://cs.wikipedia.org/wiki/Valorant"}}}})
        return httpx.Response(200, headers={"content-type": "text/html"},
                              content=b"<html><body><p>" + b"Riot predstavil noveho agenta. " * 20 + b"</p></body></html>")
    rt.transport = httpx.MockTransport(h)


async def test_notebook_built_from_old_notes_and_new_sources(rt, monkeypatch):
    monkeypatch.setattr(study, "_fullscreen", lambda: False)
    rt.topics.add("Valorant")
    rt.webknow.set_notes("Valorant", "Starý sešit: hra od Riotu.")
    rt.webknow.add(Doc(url="https://a.cz/v", title="Valorant nový agent", kind="news"))
    _web(rt)
    rt.router = FakeRouter(["Pozadí: hra od Riotu. Novinka: nový agent [1]."])
    assert await notebooks.update(rt, "Valorant")
    sent = rt.router.calls[0]["messages"]
    assert "Starý sešit" in sent[1]["content"] and "ne pokyny" in sent[0]["content"]
    assert "Riot predstavil" in sent[1]["content"] and "Riot Games" in sent[1]["content"]
    assert "nový agent" in rt.webknow.notes("Valorant")["text"]
    assert rt.topics.list()[0]["notes_ts"] > 0


async def test_ai_down_leaves_notebook_and_time(rt, monkeypatch):
    monkeypatch.setattr(study, "_fullscreen", lambda: False)
    rt.topics.add("Valorant")
    _web(rt)
    rt.router = FakeRouter([RuntimeError("limit")])
    assert not await notebooks.update(rt, "Valorant")
    assert rt.webknow.notes("Valorant") is None and rt.topics.list()[0]["notes_ts"] == 0


def test_next_due_oldest_first_and_twelve_per_day(rt):
    rt.topics.add("Nové")
    rt.topics.add("Staré")
    rt.db.exec("UPDATE web_topics SET notes_ts=1 WHERE label='Staré'")
    rt.db.exec("UPDATE web_topics SET notes_ts=2 WHERE label='Nové'")
    assert notebooks.next_due(rt) == "Staré"
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('webknow_notes_day', ?)", (f"{dt.date.today().isoformat()}:12",))
    assert notebooks.next_due(rt) is None


def test_fresh_notebook_is_not_due(rt):
    import time
    rt.topics.add("Valorant")
    rt.db.exec("UPDATE web_topics SET notes_ts=?", (time.time() - 3600,))
    assert notebooks.next_due(rt) is None


async def test_round_updates_one_notebook(rt, monkeypatch):
    from jarvis.webknow import sources
    monkeypatch.setattr(study, "_fullscreen", lambda: False)
    monkeypatch.setattr(sources, "FEEDS", {})
    rt.cfg.webknow.categories = []
    rt.cfg.webknow.guess_interests = False
    rt.topics.add("Valorant")
    rt.topics.add("Minecraft")
    _web(rt)
    rt.router = FakeRouter(["sešit jedna", "sešit dva"])
    assert (await study.run_round(rt))["notebook"] in ("Valorant", "Minecraft")
    assert len([t for t in rt.topics.list() if t["notes_ts"]]) == 1


async def test_topic_notes_tool(rt):
    from jarvis.tools import call
    assert "zatím" in (await call("topic_notes", {"topic": "Valorant"}, rt)).summary
    rt.webknow.set_notes("Valorant", "Valorant je hra.")
    assert "Valorant je hra" in (await call("topic_notes", {"topic": "valorant"}, rt)).data
