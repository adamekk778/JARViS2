"""Spec 2026-11-20 §5.3 / §5.4: feeds, Wikipedia and a page reader that never chokes on huge or binary pages."""
import json
from pathlib import Path

import httpx

from jarvis.webknow import sources

FX = Path(__file__).parent / "fixtures" / "webknow"


def test_parse_rss_and_google_news_title_split():
    items = sources.parse_feed((FX / "rss.xml").read_bytes())
    assert items[0].title == "Vláda schválila rozpočet" and items[0].source == "ČT24" and items[0].published
    assert items[1].snippet == "Pražské derby skončilo 2:1." and items[1].source == ""


def test_parse_atom():
    it = sources.parse_feed((FX / "atom.xml").read_bytes(), source="The Verge")[0]
    assert it.url.startswith("https://") and it.snippet == "A new phone is here." and it.source == "The Verge"


def test_parse_garbage_is_empty():
    assert sources.parse_feed(b"<html>not a feed") == []


async def test_wikipedia_intro(rt):
    rt.transport = httpx.MockTransport(lambda r: httpx.Response(200, json=json.loads((FX / "wiki.json").read_text("utf-8"))))
    it = (await sources.wikipedia(rt, "Praha"))[0]
    assert it.source == "Wikipedie" and "hlavní město" in it.snippet and it.url.startswith("https://cs.wikipedia.org/")


async def test_fetch_feed_error_is_empty(rt):
    rt.transport = httpx.MockTransport(lambda r: httpx.Response(503))
    assert await sources.fetch_feed(rt, "https://x.cz/rss") == []


async def test_read_page_skips_pdf_and_caps_huge(rt):
    def h(r):
        if r.url.path.endswith(".pdf"):
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
        return httpx.Response(200, headers={"content-type": "text/html"},
                              content=b"<html><title>T</title><body><p>" + b"slovo " * 1_000_000 + b"</p></body></html>")
    rt.transport = httpx.MockTransport(h)
    assert await sources.read_page(rt, "https://a.cz/x.pdf") == ("", "")
    title, text = await sources.read_page(rt, "https://a.cz/big", max_chars=6000)
    assert 0 < len(text) <= 6000


def test_login_wall():
    assert sources.looks_like_login("Přihlášení | Seznam", "Zadejte heslo")
    assert not sources.looks_like_login("Článek", "a" * 1000)


def test_google_news_urls():
    assert sources.google_news_search_url("GTA 6") == "https://news.google.com/rss/search?q=GTA%206&hl=cs&gl=CZ&ceid=CZ:cs"
    assert sources.GN("WORLD", en=True).endswith("/topic/WORLD?hl=en-US&gl=US&ceid=US:en")
    assert set(sources.FEEDS) == set(sources.CATEGORY_NAMES)
