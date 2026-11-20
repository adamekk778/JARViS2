"""Spec 2026-11-20 §5.10 / §5.11: watched topics (one notice, never a flood) and topics JARVIS guesses itself."""
import time

import pytest
from conftest import FakeRouter

from jarvis.webknow import topics as T
from jarvis.webknow.store import Doc


def _notes(rt, monkeypatch):
    sent = []
    monkeypatch.setattr(rt, "notify", lambda title, body, **kw: sent.append((title, body, kw)) or 1)
    return sent


async def test_new_hit_gives_one_bundled_notice_then_silence(rt, monkeypatch):
    sent = _notes(rt, monkeypatch)
    rt.topics.watch("GTA 6")
    ids = [rt.webknow.add(Doc(url=f"https://a.cz/{i}", title=f"GTA 6 novinka {i}", kind="news")) for i in range(4)]
    assert await T.check_watches(rt, ids) == 1
    assert sent[0][0] == "Novinka: GTA 6" and sent[0][1].count(" · ") == 2 and sent[0][2]["actions"][0]["action"] == "web_more"
    assert sent[0][2]["speak"] is False and sent[0][2]["url"] == "https://a.cz/0"
    assert await T.check_watches(rt, ids) == 0


async def test_daily_cap_of_six(rt, monkeypatch):
    sent = _notes(rt, monkeypatch)
    rt.topics.watch("GTA 6")
    for i in range(8):
        await T.check_watches(rt, [rt.webknow.add(Doc(url=f"https://a.cz/{i}", title=f"GTA 6 zpráva {i}", kind="news"))])
    assert len(sent) == 6


async def test_guessed_topics_never_notify(rt, monkeypatch):
    sent = _notes(rt, monkeypatch)
    rt.topics.add("Valorant", kind="auto")
    await T.check_watches(rt, [rt.webknow.add(Doc(url="https://a.cz/v", title="Valorant patch", kind="news"))])
    assert sent == []


async def test_unrelated_news_does_not_notify(rt, monkeypatch):
    sent = _notes(rt, monkeypatch)
    rt.topics.watch("GTA 6")
    await T.check_watches(rt, [rt.webknow.add(Doc(url="https://a.cz/x", title="Sparta vyhrála derby", kind="news"))])
    assert sent == []


def test_watch_limit_and_dismissed_auto_stays_gone(rt):
    for i in range(10):
        rt.topics.watch(f"tema {i}")
    with pytest.raises(ValueError):
        rt.topics.watch("jedenacte")
    rt.topics.add("Krypto", kind="auto")
    rt.topics.remove("Krypto")
    rt.topics.add("Krypto", kind="auto")
    assert "krypto" not in [t["name"] for t in rt.topics.active()]


def test_star_and_remove_own_with_its_notebook(rt):
    rt.topics.add("Valorant", kind="auto")
    rt.topics.star("Valorant")
    assert rt.topics.list()[0]["kind"] == "own"
    rt.webknow.set_notes("Valorant", "sešit")
    rt.topics.remove("Valorant")
    assert rt.topics.list() == [] and rt.webknow.notes("Valorant") is None


def test_matches_all_words_any_ending():
    assert T.matches("GTA 6", "Nový trailer na GTA 6 je venku")
    assert T.matches("umělá inteligence", "Umělou inteligenci reguluje EU")
    assert not T.matches("GTA 6", "Sparta vyhrála")


async def test_watch_tool(rt):
    from jarvis.tools import call
    r = await call("watch_topic", {"topic": "GTA 6"}, rt)
    assert r.ok and rt.topics.watched()[0]["label"] == "GTA 6"
    assert (await call("unwatch_topic", {"topic": "gta 6"}, rt)).ok and rt.topics.watched() == []


async def test_study_round_notifies_watched_topic(rt, monkeypatch):
    import httpx
    from jarvis.webknow import sources, study
    sent = _notes(rt, monkeypatch)
    monkeypatch.setattr(sources, "FEEDS", {"hry": [("PC Gamer", "https://pcgamer.com/rss")]})
    monkeypatch.setattr(study, "_fullscreen", lambda: True)
    rt.cfg.webknow.categories = ["hry"]
    rt.topics.watch("GTA 6")
    rss = b"<rss><channel><item><title>GTA 6 m\xc3\xa1 datum vyd\xc3\xa1n\xc3\xad</title><link>https://pcgamer.com/gta</link></item></channel></rss>"
    rt.transport = httpx.MockTransport(lambda r: httpx.Response(200, content=rss))
    assert (await study.run_round(rt))["notified"] == 1 and sent[0][0] == "Novinka: GTA 6"
