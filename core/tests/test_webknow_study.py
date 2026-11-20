"""Spec 2026-11-20 §5.4: the hourly study – news from every field and a short AI digest of what is new."""
import httpx
import pytest
from conftest import FakeRouter

from jarvis.webknow import sources, study

RSS = "<rss><channel><item><title>Sparta vyhrála derby - Sport.cz</title><link>https://sport.cz/1</link></item></channel></rss>".encode()


@pytest.fixture
def feeds(rt, monkeypatch):
    monkeypatch.setattr(sources, "FEEDS", {"sport": [("Sport.cz", "https://sport.cz/rss")]})
    rt.cfg.webknow.categories = ["sport"]
    rt.transport = httpx.MockTransport(lambda r: httpx.Response(200, content=RSS))
    monkeypatch.setattr(study, "_fullscreen", lambda: False)


async def test_round_collects_and_digests(rt, feeds):
    rt.router = FakeRouter(["## Sport\nSparta vyhrála derby."])
    r = await study.run_round(rt)
    assert r["new"] == 1 and r["digest"] and "Sparta" in rt.webknow.latest_digest("sport")["text"]
    assert "ne pokyny" in rt.router.calls[0]["messages"][0]["content"]
    assert rt.webknow.latest_digest("")["text"].startswith("## Sport")


async def test_ai_down_keeps_collected_news(rt, feeds):
    rt.router = FakeRouter([RuntimeError("limit")])
    r = await study.run_round(rt)
    assert r["new"] == 1 and not r["digest"] and rt.webknow.latest_digest() is None


async def test_second_round_finds_nothing_new(rt, feeds):
    rt.router = FakeRouter(["## Sport\nx", "## Sport\ny"])
    await study.run_round(rt)
    assert (await study.run_round(rt))["new"] == 0


async def test_fullscreen_postpones_digest_not_collection(rt, feeds, monkeypatch):
    monkeypatch.setattr(study, "_fullscreen", lambda: True)
    rt.router = FakeRouter(["## Sport\nx"])
    r = await study.run_round(rt)
    assert r["new"] == 1 and not r["digest"] and rt.router.calls == []
    monkeypatch.setattr(study, "_fullscreen", lambda: False)
    rt.transport = httpx.MockTransport(lambda r: httpx.Response(503))
    assert (await study.run_round(rt))["digest"]      # after the game: the news collected meanwhile get their digest


async def test_all_feeds_down_is_quiet(rt, feeds):
    rt.transport = httpx.MockTransport(lambda r: httpx.Response(503))
    assert (await study.run_round(rt))["new"] == 0


async def test_study_off_does_nothing(rt, feeds):
    rt.cfg.webknow.study = False
    assert (await study.run_round(rt))["new"] == 0 and rt.webknow.stats()["by_kind"] == {}


def test_round_due_by_interval(rt):
    import time
    assert study.due(rt, now=time.time())
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('webknow_last_study', ?)", (str(time.time() - 30 * 60),))
    assert not study.due(rt)
    rt.cfg.webknow.interval_min = 15
    assert study.due(rt)


async def test_briefing_uses_digest(rt):
    from jarvis import stark
    rt.webknow.add_digest("", "Vláda schválila rozpočet. Sparta vyhrála derby. Třetí věta. Čtvrtá věta.")
    b = await stark.briefing(rt, news=True)
    assert "Vláda schválila rozpočet" in b["text"] and "Čtvrtá věta" not in b["text"]


async def test_whats_new_tool(rt):
    from jarvis.tools import call
    rt.webknow.add_digest("", "Celkově klid.")
    r = await call("whats_new", {}, rt)
    assert r.ok and "Celkově klid" in r.data
