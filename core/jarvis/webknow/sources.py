"""Spec 2026-11-20 §5.3 / §5.4: where JARVIS reads the internet – news feeds of every field (Google News topics and
searches, Czech and world outlets), Wikipedia, DuckDuckGo – and a page reader that only takes text pages, stops at
2 MB and gives up after a few seconds. Every function returns an empty result instead of raising: one source that is
down never stops the others. Only GET, no cookies; what comes back is data, never instructions."""
from __future__ import annotations

import asyncio
import datetime as dt
import email.utils
import html
import logging
import re
import urllib.parse
from dataclasses import dataclass
from xml.etree import ElementTree

log = logging.getLogger("jarvis.webknow")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JARVIS/3"}
MAX_PAGE_BYTES = 2 * 2 ** 20
ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class Item:
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    published: float | None = None


def GN(topic: str, en: bool = False) -> str:
    """A Google News topic feed (WORLD, NATION, BUSINESS, TECHNOLOGY, SCIENCE, HEALTH, SPORTS, ENTERTAINMENT)."""
    loc = "hl=en-US&gl=US&ceid=US:en" if en else "hl=cs&gl=CZ&ceid=CZ:cs"
    return f"https://news.google.com/rss/headlines/section/topic/{topic}?{loc}"


def google_news_search_url(query: str, lang: str = "cs") -> str:
    loc = "hl=en-US&gl=US&ceid=US:en" if lang == "en" else "hl=cs&gl=CZ&ceid=CZ:cs"
    return f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&{loc}"


CATEGORY_NAMES = {"svet": "Svět", "cesko": "Česko", "byznys": "Byznys", "technologie": "Technologie", "ai": "AI",
                  "veda": "Věda", "zdravi": "Zdraví", "sport": "Sport", "zabava": "Zábava", "hry": "Hry"}

# every URL answered with items on 2026-11-20 (the Google topic feeds redirect; rt.http() follows redirects)
FEEDS: dict[str, list[tuple[str, str]]] = {
    "svet": [("Google Zprávy", GN("WORLD")), ("Google News", GN("WORLD", en=True)),
             ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml")],
    "cesko": [("Google Zprávy", GN("NATION")), ("ČT24", "https://ct24.ceskatelevize.cz/rss"),
              ("iRozhlas", "https://www.irozhlas.cz/rss/irozhlas"), ("Novinky", "https://www.novinky.cz/rss"),
              ("Seznam Zprávy", "https://www.seznamzpravy.cz/rss")],
    "byznys": [("Google Zprávy", GN("BUSINESS")), ("E15", "https://www.e15.cz/rss")],
    "technologie": [("Google Zprávy", GN("TECHNOLOGY")), ("Živě", "https://www.zive.cz/rss/sc-47/"),
                    ("Lupa", "https://www.lupa.cz/rss/clanky/"), ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
                    ("The Verge", "https://www.theverge.com/rss/index.xml")],
    "ai": [("MIT Technology Review", "https://www.technologyreview.com/feed/"), ("Hacker News", "https://hnrss.org/frontpage"),
           ("Google Zprávy", google_news_search_url("umělá inteligence"))],
    "veda": [("Google Zprávy", GN("SCIENCE")), ("ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml"),
             ("Science News", "https://www.sciencenews.org/feed")],
    "zdravi": [("Google Zprávy", GN("HEALTH")), ("WHO", "https://www.who.int/rss-feeds/news-english.xml")],
    "sport": [("Google Zprávy", GN("SPORTS")), ("Sport.cz", "https://www.sport.cz/rss"), ("iSport", "https://isport.blesk.cz/rss")],
    "zabava": [("Google Zprávy", GN("ENTERTAINMENT"))],
    "hry": [("PC Gamer", "https://www.pcgamer.com/rss/"), ("Eurogamer", "https://www.eurogamer.net/feed")],
}


def plain(text: str, limit: int = 400) -> str:
    t = re.sub(r"<[^>]+>", " ", text or "")
    t = re.sub(r"\s+", " ", html.unescape(t)).strip()
    return t[:limit]


def _ts(s: str | None) -> float | None:
    if not s:
        return None
    s = s.strip()
    try:
        return email.utils.parsedate_to_datetime(s).timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)).timestamp()
    except ValueError:
        return None


def parse_feed(content: bytes, source: str = "") -> list[Item]:
    """RSS 2.0 and Atom → items. A Google News title "Titulek - Zdroj" gives the title and the source apart."""
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return []
    out: list[Item] = []
    for it in root.iter("item"):
        title = plain(it.findtext("title") or "", 300)
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        src = (src_el.text or "").strip() if src_el is not None and src_el.text else ""
        if src or "news.google.com" in link:
            m = re.match(r"^(.*\S)\s+[-–]\s+([^-–]+)$", title)
            if m:
                title, src = m.group(1), src or m.group(2).strip()
        snippet = plain(it.findtext("description") or "")
        if snippet.startswith(title):            # Google News repeats the headline as the description
            snippet = ""
        if title and link:
            out.append(Item(title, link, snippet, src or source, _ts(it.findtext("pubDate"))))
    for e in root.iter(f"{ATOM}entry"):
        title = plain(e.findtext(f"{ATOM}title") or "", 300)
        link = ""
        for ln in e.findall(f"{ATOM}link"):
            if ln.get("rel", "alternate") == "alternate" and ln.get("href"):
                link = ln.get("href", "")
                break
        snippet = plain(e.findtext(f"{ATOM}summary") or e.findtext(f"{ATOM}content") or "")
        if title and link:
            out.append(Item(title, link, snippet, source, _ts(e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated"))))
    return out


async def fetch_feed(rt, url: str, source: str = "", timeout: float = 8) -> list[Item]:
    try:
        async with rt.http() as c:
            r = await c.get(url, headers=UA, timeout=timeout)
        if r.status_code >= 400:
            return []
        return parse_feed(r.content, source)
    except Exception as e:  # noqa: BLE001 – one feed down never stops the others
        log.debug("feed %s: %s", url, e)
        return []


async def ddg(query: str, n: int = 6, news: bool = False) -> list[Item]:
    try:
        from ..tools.web import _ddg

        rows = await asyncio.to_thread(_ddg, query, n, news)
    except Exception as e:  # noqa: BLE001 – DuckDuckGo limits automated queries now and then
        log.debug("ddg: %s", e)
        return []
    return [Item(plain(r.get("title") or "", 300), r.get("href") or r.get("url") or "", plain(r.get("body") or r.get("excerpt") or ""),
                 r.get("source") or "", _ts(r.get("date"))) for r in rows if r.get("href") or r.get("url")]


async def wikipedia(rt, query: str, langs: tuple[str, ...] = ("cs", "en"), timeout: float = 4) -> list[Item]:
    """The introduction of the best one or two articles (Czech first; English only when Czech has nothing)."""
    for lang in langs:
        params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": query, "gsrlimit": "2",
                  "prop": "extracts|info", "exintro": "1", "explaintext": "1", "inprop": "url"}
        try:
            async with rt.http() as c:
                r = await c.get(f"https://{lang}.wikipedia.org/w/api.php", params=params, headers=UA, timeout=timeout)
            pages = (r.json().get("query") or {}).get("pages") or {}
        except Exception as e:  # noqa: BLE001
            log.debug("wikipedia %s: %s", lang, e)
            continue
        items = [Item(p.get("title", ""), p.get("fullurl") or f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(p.get('title', ''))}",
                      (p.get("extract") or "").strip()[:2000], "Wikipedie")
                 for p in sorted(pages.values(), key=lambda p: p.get("index", 0)) if (p.get("extract") or "").strip()]
        if items:
            return items
    return []


def _extract(raw: str) -> tuple[str, str]:
    m = re.search(r"<title[^>]*>(.*?)</title>", raw[:200_000], re.I | re.S)
    title = plain(m.group(1), 300) if m else ""
    text = ""
    try:
        import trafilatura

        text = trafilatura.extract(raw, include_links=False) or ""
    except Exception:  # noqa: BLE001 – a page trafilatura cannot read: plain text below
        text = ""
    if not text:
        body = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
        text = plain(body, 10 ** 9)
    return title, text


async def read_page(rt, url: str, max_chars: int = 6000, timeout: float = 4) -> tuple[str, str]:
    """(title, main text) of a web page; ("", "") for anything that is not a text page or does not answer in time."""
    async def go() -> tuple[str, str]:
        async with rt.http() as c:
            async with c.stream("GET", url, headers=UA, timeout=timeout) as r:
                ctype = r.headers.get("content-type", "").lower()
                if r.status_code >= 400 or not ctype.startswith(("text/html", "text/plain", "application/xhtml")):
                    return "", ""
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) >= MAX_PAGE_BYTES:
                        break
                raw = bytes(buf[:MAX_PAGE_BYTES]).decode(r.encoding or "utf-8", errors="replace")
        if ctype.startswith("text/plain"):
            return "", plain(raw, max_chars)
        title, text = await asyncio.to_thread(_extract, raw)
        return title, text[:max_chars]

    try:
        return await asyncio.wait_for(go(), timeout + 2)
    except Exception as e:  # noqa: BLE001
        log.debug("read %s: %s", url, e)
        return "", ""


LOGIN = re.compile(r"přihlásit|přihlášení|prihlasit|prihlaseni|sign in|sign-in|log in|login|anmelden", re.I)


def looks_like_login(title: str, text: str) -> bool:
    return len((text or "").strip()) < 300 or bool(LOGIN.search(title or ""))
