"""3.13 Přehled o světě: JARVIS reads the news by itself (Google News by topic + your own interests), writes itself a
short summary, keeps it in mind in every answer, and asks Google (Gemini with Google Search) with sources."""
import asyncio
import time

import httpx
from conftest import FakeRouter, drain
from fastapi.testclient import TestClient

from jarvis import secrets, tools, worldwatch
from jarvis.config import ProviderCfg
from jarvis.server.app import create_app
from jarvis.worldwatch import WorldWatch, parse_rss

NOW = time.time()


def rss(*items: tuple[str, str, float]) -> bytes:
    """Google News-like feed: (title "Titulek - Zdroj", link, published)."""
    import email.utils

    body = "".join(f"<item><title>{t}</title><link>{u}</link><pubDate>{email.utils.formatdate(p)}</pubDate>"
                   f"<source url='https://x'>{t.rsplit(' - ', 1)[-1]}</source></item>" for t, u, p in items)
    return f"<?xml version='1.0'?><rss><channel><title>x</title>{body}</channel></rss>".encode()


def fake_fetch(feeds: dict[str, bytes]):
    async def fetch(url: str) -> bytes:
        for key, xml in feeds.items():
            if key in url:
                return xml
        raise RuntimeError("offline")
    return fetch


def test_a_google_news_feed_is_read_into_headlines():
    items = parse_rss(rss(("Vláda schválila rozpočet - iROZHLAS", "https://a/1", NOW - 600),
                          ("Nový model AI – překvapení - CzechCrunch", "https://a/2", NOW - 60)), "cz")
    assert [i["title"] for i in items] == ["Vláda schválila rozpočet", "Nový model AI – překvapení"]
    assert items[0]["source"] == "iROZHLAS" and items[0]["topic"] == "cz" and abs(items[0]["published"] - (NOW - 600)) < 2


async def test_the_news_is_read_kept_and_announced(rt):
    rt.cfg.world.topics = ["cz", "tech"]
    rt.cfg.world.interests = ["Valorant"]
    ww = WorldWatch(rt)
    feeds = {"technologie": rss(("Nvidia ukázala novou kartu - Živě", "https://t/1", NOW - 3600)),
             "Valorant": rss(("Riot oznámil nového agenta - Hrej", "https://v/1", NOW - 100)),
             "news.google.com/rss?": rss(("Vláda schválila rozpočet - iROZHLAS", "https://c/1", NOW - 600),
                                         ("Starý článek - Deník", "https://c/old", NOW - 9 * 86400))}
    q = rt.bus.subscribe()
    assert await ww.refresh(fetch_fake := fake_fetch(feeds)) == 3                               # the 9-day-old one is not news
    assert any(e["type"] == "world" for e in drain(q))
    assert [h["title"] for h in ww.headlines("tech")] == ["Nvidia ukázala novou kartu"]
    assert [h["title"] for h in ww.headlines("i:valorant")] == ["Riot oznámil nového agenta"]
    assert "Starý článek" not in [h["title"] for h in ww.headlines("cz", hours=24 * 30)]       # older than a week: gone
    assert await ww.refresh(fetch_fake) == 0                                                     # nothing new the second time
    st = ww.state()
    assert [t["label"] for t in st["topics"]] == ["Česko", "Technologie", "Valorant"] and st["topics"][0]["items"]


async def test_one_feed_down_is_not_the_end(rt):
    rt.cfg.world.topics = ["cz", "tech"]
    ww = WorldWatch(rt)
    n = await ww.refresh(fake_fetch({"technologie": rss(("Nvidia ukázala novou kartu - Živě", "https://t/1", NOW))}))
    assert n == 1 and ww.headlines("tech")


async def test_the_summary_is_written_and_kept_in_every_answer(rt):
    rt.cfg.world.topics = ["cz"]
    ww = rt.world
    await ww.refresh(fake_fetch({"rss?": rss(("Vláda schválila rozpočet - iROZHLAS", "https://c/1", NOW - 600))}))
    rt.router = FakeRouter(["Česko: Vláda schválila rozpočet na příští rok."])
    d = await ww.write_digest()
    assert "rozpočet" in d["text"] and "rozpočet" in ww.for_prompt()
    asked = rt.router.calls[0]["messages"][-1]["content"]
    assert "Vláda schválila rozpočet (iROZHLAS)" in asked                     # the AI only rewrites the headlines
    msgs, _ = await rt.agent._build_messages("co je nového?", [], False, "")
    assert "Aktuální dění ve světě" in msgs[0]["content"] and "rozpočet" in msgs[0]["content"]
    rt.cfg.world.in_answers = False
    assert ww.for_prompt() == ""
    rt.cfg.world.in_answers = True
    assert ww.for_prompt(now=NOW + 40 * 3600) == ""                             # an old summary is not passed off as news


async def test_without_ai_the_summary_is_the_headlines_themselves(rt):
    rt.cfg.world.topics = ["cz"]
    ww = rt.world
    await ww.refresh(fake_fetch({"rss?": rss(("Vláda schválila rozpočet - iROZHLAS", "https://c/1", NOW - 600))}))
    rt.router = FakeRouter([RuntimeError("limit")])
    d = await ww.write_digest()
    assert d["text"] == "Česko: Vláda schválila rozpočet"


async def test_nothing_read_yet_means_no_summary(rt):
    assert await rt.world.write_digest() == {} and rt.world.for_prompt() == ""


def _gemini(rt):
    rt.cfg.brain.providers.append(ProviderCfg(id="gem1", preset="gemini", model="gemini-test"))
    secrets.set("gem1", "test-key")


async def test_google_answers_with_its_sources(rt):
    _gemini(rt)
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers.get("x-goog-api-key"), req.content
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Sparta vyhrála 2:1."}]},
                                                          "groundingMetadata": {"groundingChunks": [
                                                              {"web": {"uri": "https://sport.cz/a", "title": "sport.cz"}}]}}]})
    try:
        r = await worldwatch.google_answer(rt, "Jak hrála Sparta?", transport=httpx.MockTransport(handler))
    finally:
        secrets.set("gem1", "")
    assert r == {"text": "Sparta vyhrála 2:1.", "sources": [{"title": "sport.cz", "url": "https://sport.cz/a"}]}
    assert "models/gemini-test:generateContent" in seen["url"] and seen["key"] == "test-key" and b"google_search" in seen["body"]


async def test_google_errors_are_said_plainly(rt):
    _gemini(rt)
    try:
        r = worldwatch.google_answer(rt, "x", transport=httpx.MockTransport(
            lambda req: httpx.Response(429, json={"error": {"message": "Quota exceeded"}})))
        try:
            await r
            raise AssertionError("no error")
        except RuntimeError as e:
            assert "Quota exceeded" in str(e)
    finally:
        secrets.set("gem1", "")


async def test_google_ask_without_a_gemini_key_searches_the_web(rt, monkeypatch):
    from jarvis.tools import web

    monkeypatch.setattr(web, "_ddg", lambda q, n, news: [{"title": "Výsledky", "href": "https://x/1", "body": "Sparta 2:1"}])
    r = await tools.call("google_ask", {"question": "Jak hrála Sparta?"}, rt)
    assert r.ok and "Sparta 2:1" in r.summary


async def test_world_news_tool_tells_the_summary_and_headlines(rt):
    rt.cfg.world.topics = ["cz"]
    await rt.world.refresh(fake_fetch({"rss?": rss(("Vláda schválila rozpočet - iROZHLAS", "https://c/1", NOW - 600))}))
    rt.router = FakeRouter(["Česko: rozpočet schválen."])
    await rt.world.write_digest()
    r = await tools.call("world_news", {}, rt)
    assert r.ok and "rozpočet schválen" in r.summary and "Vláda schválila rozpočet (iROZHLAS" in r.summary
    r = await tools.call("world_news", {"topic": "Česko"}, rt)
    assert r.ok and "Vláda schválila rozpočet" in r.summary


async def test_news_about_anything_on_request(rt, monkeypatch):
    async def fq(q, fetch=None, url=""):
        return [{"topic": "i:x", "title": "Bitcoin nad 100 000", "source": "Kurzy", "url": "u", "published": NOW}]
    monkeypatch.setattr(rt.world, "fetch_query", fq)
    r = await tools.call("world_news", {"topic": "Bitcoin"}, rt)
    assert r.ok and "Bitcoin nad 100 000" in r.summary


async def test_follow_a_topic_by_voice(rt, monkeypatch):
    async def no_refresh(fetch=None):
        return 0
    monkeypatch.setattr(rt.world, "refresh", no_refresh)
    r = await tools.call("world_interest", {"topic": "Valorant"}, rt)
    assert r.ok and rt.cfg.world.interests == ["Valorant"]
    r = await tools.call("world_interest", {"topic": "valorant", "add": False}, rt)
    assert r.ok and rt.cfg.world.interests == []
    await asyncio.sleep(0)


def test_the_notch_asks_for_the_world(rt):
    c = TestClient(create_app(rt, manage_runtime=False))
    with c.websocket_connect(f"/ws?token={rt.cfg.phone.token}") as ws:
        ws.receive_json()
        ws.send_json({"type": "world_get"})
        for _ in range(30):
            m = ws.receive_json()
            if m["type"] == "world":
                break
        assert m["type"] == "world" and {t["id"] for t in m["available"]} >= {"cz", "ai", "games"}


def test_the_tools_are_always_offered_and_the_prompt_knows_the_internet(rt):
    from jarvis.prompt import build_system_prompt
    from jarvis.tools import select

    assert {"google_ask", "world_news"} <= set(select.CORE)
    sp = build_system_prompt(rt.cfg, [])
    assert "google_ask" in sp and "NIKDY netvrď, že nemůžeš na internet" in sp


async def test_the_same_story_from_two_papers_is_one_headline(rt):
    rt.cfg.world.topics = ["ai"]
    ww = WorldWatch(rt)
    await ww.refresh(fake_fetch({"inteligence": rss(("AI potřebuje elektřinu. Zachrání ji jádro? - Novinky", "https://a/1", NOW - 60),
                                                    ("AI potřebuje elektřinu, zachrání ji jádro - Seznam Zprávy", "https://b/1", NOW - 90),
                                                    ("Jiná zpráva - ČT24", "https://c/1", NOW - 120))}))
    assert [h["title"] for h in ww.headlines("ai")] == ["AI potřebuje elektřinu. Zachrání ji jádro?", "Jiná zpráva"]


async def test_a_topic_that_is_switched_off_is_read_on_request(rt, monkeypatch):
    rt.cfg.world.topics = ["cz"]
    asked = []

    async def fq(q, fetch=None, url=""):
        asked.append(url)
        return [{"topic": "sport", "title": "Jílek ovládl bitvu titánů", "source": "Sport.cz", "url": "u", "published": NOW}]
    monkeypatch.setattr(rt.world, "fetch_query", fq)
    r = await tools.call("world_news", {"topic": "sport"}, rt)
    assert r.ok and "Jílek" in r.summary and "SPORTS" in asked[0]
