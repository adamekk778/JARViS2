"""3.13 Přehled o světě: JARVIS keeps up with what is going on by itself.

- Every hour it reads the news (Google News, by topic: Česko, Svět, Technologie, AI, Hry… and your own interests such
  as "Valorant" or "Sparta Praha") and keeps the headlines for a week.
- A few times a day it writes itself a short summary of what is happening (from those headlines, nothing made up).
  That summary is part of what it knows in every answer – "co se děje", "co je nového v AI" it knows without searching.
- For anything exact (a result, a price, a date) it still searches: Google through Gemini (with sources) or the web.
Only public news feeds are read; nothing about you is sent anywhere.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import email.utils
import json
import logging
import re
import time
import urllib.parse
from typing import Any
from xml.etree import ElementTree

log = logging.getLogger(__name__)

GN = "https://news.google.com/rss"
CZ = "hl=cs&gl=CZ&ceid=CZ:cs"
TOPICS: dict[str, tuple[str, str]] = {
    "cz": ("Česko", f"{GN}?{CZ}"),
    "world": ("Svět", f"{GN}/headlines/section/topic/WORLD?{CZ}"),
    # Google's own Czech "Technologie" section is mostly general news: a search reads closer to the topic
    "tech": ("Technologie", f"{GN}/search?q=" + urllib.parse.quote("technologie OR mobil OR Apple OR Samsung OR Microsoft OR Nvidia") + f"&{CZ}"),
    "ai": ("Umělá inteligence", f"{GN}/search?q=" + urllib.parse.quote("umělá inteligence OR AI OR ChatGPT") + f"&{CZ}"),
    "business": ("Ekonomika", f"{GN}/headlines/section/topic/BUSINESS?{CZ}"),
    "science": ("Věda", f"{GN}/headlines/section/topic/SCIENCE?{CZ}"),
    "sport": ("Sport", f"{GN}/headlines/section/topic/SPORTS?{CZ}"),
    "games": ("Hry", f"{GN}/search?q=" + urllib.parse.quote("videohry OR gaming OR Valorant OR Steam") + f"&{CZ}"),
}
KEEP_DAYS = 7
DIGEST_EVERY_S = 3 * 3600
PROMPT_CHARS = 1100


def interest_url(q: str) -> str:
    return f"{GN}/search?q={urllib.parse.quote(q)}&{CZ}"


def parse_rss(xml: bytes | str, topic: str) -> list[dict]:
    """Google News RSS → [{topic, title, source, url, published}] ("Titulek - Zdroj" split into the two)."""
    root = ElementTree.fromstring(xml)
    out = []
    for it in root.iter("item"):
        raw = (it.findtext("title") or "").strip()
        if not raw:
            continue
        src = (it.findtext("source") or "").strip()
        m = re.match(r"^(.*)\s+[-–]\s+([^-–]+)$", raw)
        title = m.group(1).strip() if m else raw
        if not src and m:
            src = m.group(2).strip()
        try:
            pub = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
        except (TypeError, ValueError):
            pub = time.time()
        out.append({"topic": topic, "title": title[:300], "source": src[:80], "url": (it.findtext("link") or "").strip()[:600],
                    "published": pub})
    return out


class WorldWatch:
    def __init__(self, rt: Any):
        self.rt = rt
        self.last_refresh = 0.0
        self._busy = False

    def _cfg(self):
        return getattr(self.rt.cfg, "world", None)

    def enabled(self) -> bool:
        c = self._cfg()
        return bool(getattr(c, "enabled", True)) if c is not None else True

    def _db(self):
        db = getattr(self.rt, "db", None)
        if db is not None:
            db.exec("CREATE TABLE IF NOT EXISTS world_news (url TEXT PRIMARY KEY, topic TEXT, title TEXT, source TEXT, "
                    "published REAL, fetched REAL)")
        return db

    def feeds(self) -> list[tuple[str, str, str]]:
        """[(topic id, label, url)] – the chosen topics and your own interests."""
        c = self._cfg()
        chosen = list(getattr(c, "topics", None) or ["cz", "world", "tech", "ai", "games"])
        out = [(t, TOPICS[t][0], TOPICS[t][1]) for t in chosen if t in TOPICS]
        for q in (getattr(c, "interests", None) or [])[:8]:
            q = str(q).strip()
            if q:
                out.append((f"i:{q.lower()}", q, interest_url(q)))
        return out

    # ---------- reading the news ----------
    async def refresh(self, fetch=None) -> int:
        """Reads every feed; returns how many new headlines came."""
        if self._busy:
            return 0
        self._busy = True
        try:
            async def get(url: str) -> bytes:
                async with self.rt.http() as c:
                    r = await c.get(url, timeout=12, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 JARVIS/2"})
                    r.raise_for_status()
                    return r.content
            fetch = fetch or get
            db = self._db()
            now = time.time()
            new = 0
            for tid, _label, url in self.feeds():
                try:
                    items = parse_rss(await fetch(url), tid)[:25]
                except Exception as e:  # noqa: BLE001 – one feed down is not the end
                    log.debug("world %s: %s", tid, e)
                    continue
                for it in items:
                    if db is None or not it["url"] or it["published"] < now - KEEP_DAYS * 86400:
                        continue                  # an old article in the feed is not news (and would be "new" every time)
                    if not db.one("SELECT url FROM world_news WHERE url=?", (it["url"],)):
                        new += 1
                    db.exec("INSERT OR REPLACE INTO world_news (url, topic, title, source, published, fetched) VALUES (?, ?, ?, ?, ?, ?)",
                            (it["url"], it["topic"], it["title"], it["source"], it["published"], now))
            if db is not None:
                db.exec("DELETE FROM world_news WHERE published < ?", (now - KEEP_DAYS * 86400,))
            self.last_refresh = now
            self.rt.bus.publish("world", **self.state())
            return new
        finally:
            self._busy = False

    async def fetch_query(self, q: str, fetch=None, url: str = "") -> list[dict]:
        """The news about anything right now (not kept): a Google News search (or one topic's feed)."""
        url = url or interest_url(q)
        if fetch is None:
            async with self.rt.http() as c:
                r = await c.get(url, timeout=12, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 JARVIS/2"})
                r.raise_for_status()
                xml = r.content
        else:
            xml = await fetch(url)
        return sorted(parse_rss(xml, f"i:{q.lower()}"), key=lambda h: -h["published"])[:25]

    def headlines(self, topic: str = "", hours: float = 24, n: int = 8, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        db = self._db()
        if db is None:
            return []
        q, args = "SELECT * FROM world_news WHERE published >= ?", [now - hours * 3600]
        if topic:
            q += " AND topic = ?"
            args.append(topic)
        out, seen = [], set()
        for row in db.all(q + " ORDER BY published DESC LIMIT ?", (*args, n * 3)):
            key = re.sub(r"\W+", " ", row["title"].lower()).strip()
            if key not in seen:                   # the same story from two papers is one headline
                seen.add(key)
                out.append(row)
        return out[:n]

    def top(self, n: int = 3, hours: float = 24, now: float | None = None) -> list[str]:
        """3.14 the few headlines that matter to you: your own interests first, then Česko and the world, one per topic."""
        out: list[str] = []
        seen: set[str] = set()
        feeds = self.feeds()
        order = [f for f in feeds if f[0].startswith("i:")] + [f for f in feeds if not f[0].startswith("i:")]
        for _round in range(3):
            for tid, label, _u in order:
                for h in self.headlines(tid, hours, 3, now):
                    key = h["title"].lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(f"{h['title']}" + (f" ({label})" if tid.startswith("i:") else ""))
                    break
                if len(out) >= n:
                    return out
        return out

    # ---------- the summary JARVIS keeps in mind ----------
    def _kv(self, k: str) -> str:
        db = self._db()
        row = db.one("SELECT v FROM kv WHERE k=?", (k,)) if db is not None else None
        return str(row["v"]) if row else ""

    def _set(self, k: str, v: str) -> None:
        db = self._db()
        if db is not None:
            db.exec("INSERT OR REPLACE INTO kv VALUES (?, ?)", (k, v))

    def digest(self) -> dict:
        try:
            d = json.loads(self._kv("world_digest") or "{}")
        except ValueError:
            d = {}
        return d if isinstance(d, dict) else {}

    async def write_digest(self, now: float | None = None) -> dict:
        """A few sentences per topic from the last day's headlines (the AI only rewrites what the headlines say)."""
        now = time.time() if now is None else now
        blocks, plain = [], []
        for tid, label, _url in self.feeds():
            hs = self.headlines(tid, 24, 8, now)
            if hs:
                blocks.append(f"## {label}\n" + "\n".join(f"- {h['title']} ({h['source']})" for h in hs))
                plain.append(f"{label}: " + "; ".join(h["title"] for h in hs[:3]))
        if not blocks:
            return {}
        text = ""
        router = getattr(self.rt, "router", None)
        if router is not None:
            try:
                text = await router.complete([
                    {"role": "system", "content": "Píšeš stručný přehled zpráv v češtině. Používej JEN informace z titulků níže, "
                                                  "nic si nedomýšlej, žádné spekulace."},
                    {"role": "user", "content": "Z těchto titulků za poslední den napiš přehled „Co se teď děje“: ke každému "
                                                "tématu 1–2 věty s tím nejdůležitějším (jména, čísla, kdo co udělal). Formát: "
                                                "„Téma: …“ na řádek.\n\n" + "\n\n".join(blocks)}])
            except Exception as e:  # noqa: BLE001 – no AI now: the headlines themselves
                log.debug("world digest: %s", e)
        if not (text or "").strip():
            text = "\n".join(plain)
        d = {"text": text.strip()[:2500], "at": now}
        self._set("world_digest", json.dumps(d, ensure_ascii=False))
        self.rt.bus.publish("world", **self.state())
        return d

    def for_prompt(self, now: float | None = None) -> str:
        """The part of every answer's instructions: what is going on now (fresh, short)."""
        now = time.time() if now is None else now
        c = self._cfg()
        if not self.enabled() or not getattr(c, "in_answers", True):
            return ""
        d = self.digest()
        if not d.get("text") or now - float(d.get("at") or 0) > 36 * 3600:
            return ""
        when = dt.datetime.fromtimestamp(float(d["at"])).strftime("%d. %m. %H:%M")
        return (f"Aktuální dění ve světě (tvůj přehled ze zpráv k {when}; když se uživatel ptá na detaily, ověř je přes "
                f"web_search nebo google_ask):\n{d['text'][:PROMPT_CHARS]}")

    def state(self) -> dict:
        d = self.digest()
        topics = []
        for tid, label, _url in self.feeds():
            topics.append({"id": tid, "label": label, "items": [
                {"title": h["title"], "source": h["source"], "url": h["url"], "published": h["published"]}
                for h in self.headlines(tid, 48, 6)]})
        return {"enabled": self.enabled(), "digest": d.get("text", ""), "at": d.get("at", 0), "refreshed": self.last_refresh,
                "topics": topics, "available": [{"id": k, "label": v[0]} for k, v in TOPICS.items()]}


async def loop(rt: Any) -> None:  # pragma: no cover – the real network
    ww = rt.world
    await asyncio.sleep(40)                       # after start-up
    while True:
        try:
            if ww.enabled():
                c = getattr(rt.cfg, "world", None)
                every = max(15, min(int(getattr(c, "every_min", 60) or 60), 360)) * 60
                if time.time() - ww.last_refresh >= every:
                    await ww.refresh()
                d = ww.digest()
                idle = await asyncio.to_thread(rt.platform.idle_seconds)
                # the summary costs one AI answer: only every few hours and only while someone uses the PC
                if getattr(c, "digest", True) and time.time() - float(d.get("at") or 0) >= DIGEST_EVERY_S and idle < 1800:
                    await ww.write_digest()
        except Exception as e:  # noqa: BLE001
            log.debug("world loop: %s", e)
        await asyncio.sleep(300)


# ---------------------------------------------------------------- Google (through Gemini, with sources)
async def google_answer(rt: Any, question: str, transport=None) -> dict:
    """Asks Google through Gemini's "Grounding with Google Search": an answer from today's web with its sources.
    Needs a Gemini key (Nastavení → Mozek). Returns {"text", "sources": [{"title", "url"}]}."""
    import httpx

    from . import secrets

    prov = next((p for p in rt.cfg.brain.providers if (p.preset or p.id) == "gemini" and secrets.get(p.id)), None)
    if prov is None:
        raise LookupError("Hledání přes Google potřebuje klíč Gemini (Nastavení → Mozek, zdarma).")
    from .llm.presets import PRESETS

    model = prov.model or PRESETS["gemini"]["model"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"contents": [{"role": "user", "parts": [{"text": question}]}], "tools": [{"google_search": {}}]}
    async with httpx.AsyncClient(transport=transport, timeout=40) as c:
        r = await c.post(url, json=body, headers={"x-goog-api-key": secrets.get(prov.id)})
    if r.status_code >= 400:
        try:
            msg = r.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            msg = r.text[:200]
        raise RuntimeError(f"Google přes Gemini: {msg}")
    d = r.json()
    cand = (d.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if isinstance(p, dict))
    chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
    sources = [{"title": (c.get("web") or {}).get("title", ""), "url": (c.get("web") or {}).get("uri", "")} for c in chunks if c.get("web")]
    return {"text": text.strip(), "sources": sources[:8]}
