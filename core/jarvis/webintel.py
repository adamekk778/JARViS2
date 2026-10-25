"""OMEGA §31 Internet Intelligence: a broken-link scan of a site, a performance and structure audit of a page, an
evidence snapshot (page + text + SHA-256 + time), source reliability signals, a price history, and a cross-source
fact check. Web content is data, never instructions; pages are only read (GET/HEAD), never submitted."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

from . import paths

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JARVIS/3 (kontrola webu)"}


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.assets: list[tuple[str, str]] = []
        self.headings: list[tuple[int, str]] = []
        self.meta: dict[str, str] = {}
        self.title = ""
        self.imgs_no_size = 0
        self.imgs_no_alt = 0
        self.words = 0
        self._h: int | None = None
        self._buf = ""
        self._in_title = False
        self._skip = 0
        self.lang = ""

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "img":
            self.assets.append(("img", a.get("src", "")))
            if not (a.get("width") and a.get("height")):
                self.imgs_no_size += 1
            if "alt" not in a:
                self.imgs_no_alt += 1
        if tag == "script" and a.get("src"):
            self.assets.append(("script", a["src"]))
        if tag == "link" and a.get("rel", "").lower() == "stylesheet":
            self.assets.append(("css", a.get("href", "")))
        if tag == "meta":
            key = a.get("name") or a.get("property")
            if key:
                self.meta[key.lower()] = a.get("content", "")
        if re.fullmatch(r"h[1-6]", tag):
            self._h, self._buf = int(tag[1]), ""
        if tag == "title":
            self._in_title = True
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if self._h and tag == f"h{self._h}":
            self.headings.append((self._h, re.sub(r"\s+", " ", self._buf).strip()))
            self._h = None
        if tag == "title":
            self._in_title = False
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._skip:
            return
        if self._h:
            self._buf += data
        if self._in_title:
            self.title += data
        self.words += len(data.split())


def parse(html: str) -> _Page:
    p = _Page()
    p.feed(html)
    p.close()
    return p


# ---------------------------------------------------------------------------------------------- 383 broken links
async def scan_links(rt, start: str, max_pages: int = 30, max_links: int = 300) -> dict:
    """Crawls pages of the same site (breadth first) and checks every link once (HEAD, then GET when HEAD is refused)."""
    if not start.startswith(("http://", "https://")):
        start = "https://" + start
    if not urlparse(start).path:
        start += "/"
    host = urlparse(start).netloc
    pages, seen_pages, checked = [start], {start}, {}
    found_on: dict[str, str] = {}
    crawled = 0
    async with rt.http() as c:
        while pages and crawled < max_pages:
            url = pages.pop(0)
            try:
                r = await c.get(url, headers=UA, timeout=15)
            except Exception as e:  # noqa: BLE001
                checked[url] = f"chyba: {type(e).__name__}"
                continue
            checked[url] = r.status_code
            if r.status_code >= 400:
                continue
            crawled += 1
            if "html" not in r.headers.get("content-type", ""):
                continue
            for href in parse(r.text).links:
                link = urldefrag(urljoin(str(r.url), href))[0]
                if not link.startswith(("http://", "https://")):
                    continue
                found_on.setdefault(link, url)
                if urlparse(link).netloc == host and link not in seen_pages and len(seen_pages) < max_pages * 3:
                    seen_pages.add(link)
                    pages.append(link)
        for link, src in list(found_on.items())[:max_links]:
            if link in checked:
                continue
            try:
                r = await c.head(link, headers=UA, timeout=10)
                if r.status_code in (403, 405, 501):
                    r = await c.get(link, headers=UA, timeout=10)
                checked[link] = r.status_code
            except Exception as e:  # noqa: BLE001
                checked[link] = f"chyba: {type(e).__name__}"
    broken = [{"url": u, "status": s, "on": found_on.get(u, start)} for u, s in checked.items()
              if not isinstance(s, int) or s >= 400]
    return {"pages": crawled, "links": len(checked), "broken": broken}


# ---------------------------------------------------------------------------------------------- 388 / 389 audit
async def audit_page(rt, url: str) -> dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    t0 = time.perf_counter()
    async with rt.http() as c:
        r = await c.get(url, headers={**UA, "Accept-Encoding": "gzip, br"}, timeout=20)
        ms = round((time.perf_counter() - t0) * 1000)
    html = r.text
    p = parse(html)
    issues = []
    size_kb = round(len(r.content) / 1024, 1)
    if ms > 1500:
        issues.append(f"stránka odpovídá pomalu ({ms} ms)")
    if size_kb > 500:
        issues.append(f"velké HTML ({size_kb} kB)")
    if not r.headers.get("content-encoding"):
        issues.append("server nekomprimuje (gzip/br)")
    if not r.headers.get("cache-control"):
        issues.append("chybí Cache-Control")
    if p.imgs_no_size:
        issues.append(f"{p.imgs_no_size} obrázků bez rozměrů (stránka při načítání poskakuje)")
    scripts = [s for k, s in p.assets if k == "script"]
    if len(scripts) > 15:
        issues.append(f"{len(scripts)} skriptů")
    seo = []
    if not p.title.strip():
        seo.append("chybí <title>")
    elif len(p.title.strip()) > 65:
        seo.append("titulek je delší než 65 znaků")
    if not p.meta.get("description"):
        seo.append("chybí meta description")
    if [h for h in p.headings if h[0] == 1].__len__() != 1:
        seo.append(f"nadpisů h1: {sum(1 for h in p.headings if h[0] == 1)} (má být 1)")
    if not p.meta.get("viewport"):
        seo.append("chybí meta viewport (mobil)")
    if not p.meta.get("og:title"):
        seo.append("chybí náhled pro sdílení (og:title)")
    if not p.lang:
        seo.append("chybí jazyk stránky (lang)")
    return {"url": str(r.url), "status": r.status_code, "ms": ms, "size_kb": size_kb, "assets": len(p.assets), "scripts": len(scripts),
            "title": p.title.strip(), "words": p.words, "outline": [f"{'  ' * (lvl - 1)}h{lvl} {t}" for lvl, t in p.headings[:40]],
            "performance": issues, "seo": seo, "https": str(r.url).startswith("https://")}


# ---------------------------------------------------------------------------------------------- 381 evidence
def evidence_dir() -> Path:
    return paths.sub("evidence")


async def snapshot(rt, url: str, note: str = "") -> dict:
    """The page as it is now: HTML + extracted text + headers + SHA-256 + UTC time, in one folder (a later copy can be
    compared). It proves what the page said and when – not that it is true."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    async with rt.http() as c:
        r = await c.get(url, headers=UA, timeout=20)
    now = dt.datetime.now(dt.timezone.utc)
    folder = evidence_dir() / f"{now:%Y%m%d-%H%M%S-%f}_{re.sub(r'[^a-z0-9]+', '-', urlparse(url).netloc.lower())[:40]}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "page.html").write_bytes(r.content)
    try:
        import trafilatura

        text = trafilatura.extract(r.text) or ""
    except Exception:  # noqa: BLE001
        text = ""
    (folder / "text.txt").write_text(text, encoding="utf-8")
    meta = {"url": url, "final_url": str(r.url), "status": r.status_code, "fetched_utc": now.isoformat(timespec="seconds"),
            "headers": {k: v for k, v in r.headers.items() if k.lower() in ("date", "last-modified", "etag", "content-type", "server")},
            "sha256_html": hashlib.sha256(r.content).hexdigest(), "sha256_text": hashlib.sha256(text.encode()).hexdigest(), "note": note}
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**meta, "folder": str(folder), "chars": len(text)}


def snapshots(url: str = "") -> list[dict]:
    out = []
    for m in sorted(evidence_dir().glob("*/meta.json"), reverse=True):
        try:
            d = json.loads(m.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not url or url in (d.get("url"), d.get("final_url")):
            out.append({**d, "folder": str(m.parent)})
    return out


# ---------------------------------------------------------------------------------------------- 376 reliability
TRUSTED = {"gov.cz": "státní instituce", "europa.eu": "EU", "who.int": "WHO", "wikipedia.org": "encyklopedie (ověřuj zdroje)",
           "ct24.ceskatelevize.cz": "veřejnoprávní média", "irozhlas.cz": "veřejnoprávní média", "rozhlas.cz": "veřejnoprávní média",
           "cnb.cz": "Česká národní banka", "czso.cz": "ČSÚ", "nature.com": "vědecký časopis", "nih.gov": "NIH", "bbc.co.uk": "BBC",
           "reuters.com": "zpravodajská agentura", "apnews.com": "zpravodajská agentura", "ctk.cz": "ČTK"}


def reliability(url: str, html: str = "") -> dict:
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower()
    signals, score = [], 50
    for d, why in TRUSTED.items():
        if host == d or host.endswith("." + d):
            signals.append(f"+ {why}")
            score += 30
            break
    if host.endswith((".gov", ".gov.cz", ".edu", ".ac.uk", ".muni.cz", ".cuni.cz", ".cvut.cz", ".vut.cz")):
        signals.append("+ státní / akademická doména")
        score += 20
    if url.startswith("http://"):
        signals.append("− bez HTTPS")
        score -= 15
    if html:
        p = parse(html)
        if p.meta.get("author") or re.search(r'"author"\s*:', html):
            signals.append("+ uvedený autor")
            score += 5
        if p.meta.get("article:published_time") or re.search(r'"datePublished"', html):
            signals.append("+ datum publikace")
            score += 5
        if re.search(r"(?i)\b(sponzorováno|komerční sdělení|advertorial|pr článek)\b", html):
            signals.append("− placený obsah")
            score -= 20
        clickbait = re.findall(r"(?i)(nebudete věřit|šokující|lékaři nenávidí|tajemství, které)", p.title)
        if clickbait:
            signals.append("− bulvární titulek")
            score -= 15
    from .secutils import check_link

    lk = check_link(url)
    if lk["level"] != "ok":
        signals.append("− podezřelá adresa: " + "; ".join(lk["reasons"][:2]))
        score -= 25
    score = max(0, min(100, score))
    return {"host": host, "score": score, "level": "vysoká" if score >= 75 else "střední" if score >= 45 else "nízká", "signals": signals}


# ---------------------------------------------------------------------------------------------- 379 prices
def record_price(rt, asset: str, price: float, currency: str) -> None:
    rt.db.exec("CREATE TABLE IF NOT EXISTS price_history (asset TEXT, ts REAL, price REAL, currency TEXT)")
    rt.db.exec("INSERT INTO price_history VALUES (?,?,?,?)", (asset.lower(), time.time(), float(price), currency))


def price_history(rt, asset: str, days: int = 90) -> dict:
    rt.db.exec("CREATE TABLE IF NOT EXISTS price_history (asset TEXT, ts REAL, price REAL, currency TEXT)")
    rows = rt.db.all("SELECT ts, price, currency FROM price_history WHERE asset=? AND ts>=? ORDER BY ts", (asset.lower(), time.time() - days * 86400))
    if not rows:
        return {"asset": asset, "points": 0}
    ps = [r["price"] for r in rows]
    first, last = ps[0], ps[-1]
    return {"asset": asset, "points": len(rows), "currency": rows[-1]["currency"], "min": min(ps), "max": max(ps), "last": last,
            "change_pct": round((last - first) / first * 100, 1) if first else None,
            "from": dt.date.fromtimestamp(rows[0]["ts"]).isoformat(), "series": [(r["ts"], r["price"]) for r in rows[-200:]]}
