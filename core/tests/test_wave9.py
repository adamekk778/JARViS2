"""OMEGA wave 9 (internet intelligence) against a fake website: broken links, page audit, evidence snapshots,
source reliability, price history from quotes, cross-source fact check."""
import json

import httpx
from conftest import FakeRouter

from jarvis import tools, webintel

tools.load_builtin()

SITE = {
    "https://shop.cz/": '<html lang="cs"><head><title>Obchod</title><meta name="description" content="x"><meta name="viewport" content="w">'
                        '<meta property="og:title" content="O"></head><body><h1>Obchod</h1><a href="/o-nas">O nás</a>'
                        '<a href="/stara">Stará</a><a href="https://jinde.cz/x">Jinde</a><img src="a.png" alt="a"></body></html>',
    "https://shop.cz/o-nas": '<html><body><h1>O nás</h1><a href="/">Domů</a><a href="/kontakt#mapa">Kontakt</a></body></html>',
    "https://shop.cz/kontakt": "<html><body>Kontakt</body></html>",
    "https://jinde.cz/x": "<html>ok</html>",
}


def handler(req):
    url = str(req.url)
    if url in SITE:
        return httpx.Response(200, text=SITE[url], headers={"content-type": "text/html", "content-encoding": "", "cache-control": "max-age=60"})
    return httpx.Response(404, text="nenalezeno", headers={"content-type": "text/html"})


async def test_broken_links_crawls_the_site(rt):
    rt.transport = httpx.MockTransport(handler)
    r = await tools.call("broken_links", {"url": "shop.cz"}, rt)
    assert r.ok and r.data["pages"] == 3
    assert [b["url"] for b in r.data["broken"]] == ["https://shop.cz/stara"] and r.data["broken"][0]["on"] == "https://shop.cz/"


async def test_website_audit(rt):
    page = '<html><head><title>' + "Dlouhý titulek " * 6 + '</title></head><body><h1>A</h1><h1>B</h1><h2>C</h2>' + \
           '<img src="x.png"><script src="a.js"></script></body></html>'
    rt.transport = httpx.MockTransport(lambda req: httpx.Response(200, text=page, headers={"content-type": "text/html"}))
    r = await tools.call("website_audit", {"url": "https://web.cz"}, rt)
    seo = " ".join(r.data["seo"])
    perf = " ".join(r.data["performance"])
    for s in ("delší než 65", "meta description", "h1: 2", "viewport", "og:title", "jazyk"):
        assert s in seo, s
    assert "nekomprimuje" in perf and "Cache-Control" in perf and "bez rozměrů" in perf
    assert r.data["outline"] == ["h1 A", "h1 B", "  h2 C"]


async def test_evidence_snapshot_detects_change(rt):
    content = {"t": "<html><body><p>Cena 100 Kč. Podmínky platí do konce roku a vrácení je možné do 30 dní.</p></body></html>"}
    rt.transport = httpx.MockTransport(lambda req: httpx.Response(200, text=content["t"], headers={"content-type": "text/html", "date": "x"}))
    rt.tasks.begin("důkaz", rt.memory.current_conversation)
    a = await tools.call("save_web_evidence", {"url": "https://e-shop.cz/podminky"}, rt)
    assert a.ok and len(a.data["sha256_html"]) == 64
    import pathlib

    folder = pathlib.Path(a.data["folder"])
    assert (folder / "page.html").read_bytes() and json.loads((folder / "meta.json").read_text(encoding="utf-8"))["url"] == "https://e-shop.cz/podminky"
    content["t"] = content["t"].replace("30 dní", "14 dní")
    b = await tools.call("save_web_evidence", {"url": "https://e-shop.cz/podminky"}, rt)
    assert "ZMĚNIL" in b.summary or a.data["sha256_html"] != b.data["sha256_html"]
    lst = await tools.call("save_web_evidence", {"url": "https://e-shop.cz/podminky", "list_only": True}, rt)
    assert lst.summary.startswith("2 uložených")


def test_reliability_signals():
    gov = webintel.reliability("https://www.mfcr.gov.cz/x")
    assert gov["level"] == "vysoká"
    bad = webintel.reliability("http://zpravy-dnes.xyz/clanek",
                               '<html><head><title>Šokující: lékaři nenávidí tento trik</title></head><body>Komerční sdělení</body></html>')
    assert bad["level"] == "nízká" and any("bulvární" in s for s in bad["signals"]) and any("placený" in s for s in bad["signals"])
    news = webintel.reliability("https://ct24.ceskatelevize.cz/a", '<meta name="author" content="ČT"><meta property="article:published_time" content="2026">')
    assert news["level"] == "vysoká" and "+ uvedený autor" in news["signals"]


async def test_price_history_from_quotes(rt, monkeypatch):
    from jarvis import finance

    prices = iter([100.0, 120.0, 90.0])

    async def fake(rt_, asset, vs="czk"):
        return {"name": "BTC", "price": next(prices), "currency": "CZK", "change": None}
    monkeypatch.setattr(finance, "_quote", fake)
    for _ in range(3):
        await tools.call("price", {"asset": "bitcoin"}, rt)
    r = await tools.call("price_history", {"asset": "bitcoin"}, rt)
    assert r.ok and r.data["points"] == 3 and r.data["min"] == 90 and r.data["max"] == 120 and r.data["change_pct"] == -10.0


async def test_fact_check(rt, monkeypatch):
    from jarvis.tools import web

    pages = {"https://a.cz/1": "Sněžka je vysoká 1603 metrů. " * 20, "https://b.org/2": "Nejvyšší hora Česka Sněžka měří 1603 m. " * 20}
    monkeypatch.setattr(web, "_ddg", lambda q, n, news: [{"title": u, "href": u} for u in pages])
    rt.transport = httpx.MockTransport(lambda req: httpx.Response(200, text=f"<html><body><p>{pages[str(req.url)]}</p></body></html>"))
    rt.router = FakeRouter([json.dumps({"sources": [{"n": 1, "stance": "potvrzuje", "quote": "1603 metrů"}, {"n": 2, "stance": "potvrzuje", "quote": "1603 m"}],
                                        "verdict": "pravdivé", "why": "oba zdroje"})])
    r = await tools.call("fact_check", {"claim": "Sněžka měří 1603 m"}, rt)
    assert r.ok and r.summary.startswith("Verdikt: pravdivé") and "[2] b.org" in r.summary
