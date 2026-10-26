"""OMEGA wave 21 (super browser): tabs, sessions, recording + replay of a workflow in a real browser, page structure
changes, click route, cookie banner, privacy report, expiring logins, download verification, subscriptions."""
import datetime as dt
import hashlib
import http.server
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from jarvis import browserplus as bp, tools

tools.load_builtin()
CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
needs_browser = pytest.mark.skipif(not (sys.platform == "win32" or Path(CHROMIUM).exists()), reason="žádný prohlížeč")

PAGES = {
    "/": """<html><body><h1>Obchod</h1><label>Hledat <input id="q"></label><label>Heslo <input type="password" id="pw"></label>
            <button onclick="document.getElementById('out').textContent='KOUPENO ' + document.getElementById('q').value">Koupit</button>
            <p id="out"></p><a href="/kosik">Košík</a></body></html>""",
    "/kosik": "<html><body><h1>Košík</h1><p>Prázdný</p></body></html>",
    "/cookies": """<html><body><div id="banner">Používáme cookies <button onclick="document.cookie='consent=denied';
                   document.getElementById('banner').remove()">Odmítnout vše</button><button>Přijmout vše</button></div><h1>Zprávy</h1></body></html>""",
    "/sledovani": """<html><body><h1>Blog</h1><script src="/x/googletagmanager.com/gtm.js"></script>
                     <img src="/x/facebook.com/tr?id=1"><script>localStorage.setItem('a', 'x'.repeat(2048))</script></body></html>""",
}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0], "ok" if self.path.startswith("/x/") else None)
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if self.path == "/sledovani":
            self.send_header("Set-Cookie", "_ga=GA1.2.3; Max-Age=63072000; Path=/")
        self.end_headers()
        self.wfile.write((body or "nic").encode())


@pytest.fixture(scope="module")
def site():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture
def browser(monkeypatch):
    if sys.platform != "win32":
        monkeypatch.setenv("JARVIS_CHROMIUM", CHROMIUM)
    monkeypatch.setenv("JARVIS_HEADLESS", "1")
    from jarvis.tools import browser as br

    br.SESSION = br.BrowserSession()
    yield br.SESSION


def test_sort_tabs_and_classify():
    tabs = [{"url": "https://github.com/x"}, {"url": "https://www.alza.cz/a"}, {"url": "https://www.youtube.com/watch?v=1"},
            {"url": "https://www.alza.cz/a#top"}, {"url": "https://www.idnes.cz/"}, {"url": "https://example.org"}]
    r = bp.sort_tabs(tabs)
    assert set(r["groups"]) == {"práce", "nákupy", "video a hudba", "zprávy", "ostatní"} and len(r["duplicates"]) == 1


@needs_browser
async def test_sessions_and_recording(rt, site, browser):
    from jarvis.tools.browser import SESSION

    await tools.call("browser_open", {"url": site + "/"}, rt)
    p2 = await SESSION.ctx.new_page()
    await p2.goto(site + "/kosik")
    r = await tools.call("save_browser_session", {"name": "Nákup", "note": "chybí platba"}, rt)
    assert r.ok and len(r.data["tabs"]) == 2
    await SESSION.close()
    r = await tools.call("restore_browser_session", {"name": "nákup"}, rt)
    assert r.data["opened"] == 2 and "chybí platba" in r.summary
    assert sorted(p.url for p in SESSION.ctx.pages if p.url.startswith("http"))[-1].endswith("/kosik")
    assert (await tools.call("sort_tabs", {}, rt)).data["count"] >= 2

    r = await tools.call("record_workflow_start", {"url": site + "/"}, rt)
    page = SESSION.page
    await page.fill("#q", "mléko")
    await page.fill("#pw", "tajne-heslo-1")
    await page.click("text=Koupit")
    await page.click("text=Košík")
    await page.wait_for_load_state("load")
    r = await tools.call("record_workflow_stop", {"name": "nakup mleka"}, rt)
    assert r.data["steps"] == ["vyplň Hledat = mléko", "vyplň Heslo = {heslo}", "klikni na Koupit", "klikni na Košík"]
    assert "tajne-heslo-1" not in Path(r.data["path"]).read_text(encoding="utf-8")
    assert not (await tools.call("replay_workflow", {"name": "nakup mleka"}, rt)).ok             # needs the password
    r = await tools.call("replay_workflow", {"name": "nakup mleka", "secrets": {"heslo": "x"}}, rt)
    assert r.ok and r.data["ok"] and r.data["total"] == 4, r.summary
    await SESSION.close()


@needs_browser
async def test_reject_cookies(rt, site, browser):
    from jarvis.tools.browser import SESSION

    r = await tools.call("reject_cookies", {"url": site + "/cookies"}, rt)
    assert r.data["clicked"] and r.data["how"] == "Odmítnout vše"
    assert any(c["name"] == "consent" and c["value"] == "denied" for c in await SESSION.ctx.cookies())
    r = await tools.call("reject_cookies", {"url": site + "/kosik"}, rt)
    assert not r.data["clicked"]
    await SESSION.close()


@needs_browser
async def test_page_structure_and_privacy(rt, site, browser, tmp_path):
    f = tmp_path / "p.html"
    f.write_text("<h1>Ceník</h1><h2>Základ</h2><form action='/a'><input name='email'></form><button>Koupit</button>", encoding="utf-8")
    r = await tools.call("page_structure_check", {"url": str(f)}, rt)
    assert r.data["first"]
    f.write_text("<h1>Ceník</h1><h2>Premium</h2><form action='/a'><input name='email'><input name='phone'></form><button>Objednat</button>", encoding="utf-8")
    r = await tools.call("page_structure_check", {"url": str(f)}, rt)
    assert "h2: Premium" in r.data["headings"]["added"] and "Objednat" in r.data["buttons"]["added"] and r.data["forms"]["removed"]
    assert (await tools.call("page_structure_check", {"url": str(f)}, rt)).data["same"]
    r = await tools.call("privacy_report", {"url": site + "/sledovani"}, rt)
    assert {"Google Tag Manager", "Facebook pixel"} <= set(r.data["trackers"]) and "_ga" in r.data["long_lived"] and r.data["storage_kb"] >= 2


def test_expiring_logins():
    now = time.time()
    cookies = [{"name": "sessionid", "domain": ".shop.cz", "expires": now + 5 * 3600}, {"name": "auth_token", "domain": "bank.cz", "expires": -1},
               {"name": "_ga", "domain": ".shop.cz", "expires": now + 9e7}, {"name": "remember_me", "domain": "mail.cz", "expires": now + 30 * 86400},
               {"name": "PHPSESSID", "domain": "old.cz", "expires": now - 10}]
    r = bp.expiring_logins(cookies, 48, now)
    st = {s["site"]: s["state"] for s in r["sites"]}
    assert st["shop.cz"] == "vyprší za 5 h" and st["bank.cz"] == "jen do zavření prohlížeče" and st["old.cz"] == "vypršelo"
    assert st["mail.cz"].startswith("platné do") and set(r["soon"]) == {"shop.cz", "old.cz"}


async def test_find_route(rt):
    pages = {"/": '<a href="/o-nas">O nás</a><a href="/podpora">Podpora</a>', "/o-nas": "<p>Kdo jsme</p>",
             "/podpora": '<a href="/podpora/reklamace">Vrácení zboží</a><a href="https://jinde.cz/x">cizí</a>',
             "/podpora/reklamace": "<h1>Reklamační formulář</h1>"}
    rt.transport = httpx.MockTransport(lambda req: httpx.Response(200 if req.url.path in pages else 404, text=pages.get(req.url.path, ""),
                                                                  headers={"content-type": "text/html"}))
    r = await tools.call("find_page_route", {"site": "obchod.test", "target": "reklamační formulář"}, rt)
    assert r.data["found"] and r.data["clicks"] == ["Podpora", "Vrácení zboží"] and r.data["url"].endswith("/podpora/reklamace")
    assert not (await tools.call("find_page_route", {"site": "obchod.test", "target": "kariéra"}, rt)).data["found"]


async def test_verify_download(rt):
    exe = b"MZ" + b"\x00" * 5000
    good = b"%PDF-1.7 " + b"x" * 1000

    def handler(req):
        p = req.url.path
        if "rdap.org" in str(req.url):
            reg = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat() if "novy-web" in p else "2008-01-01T00:00:00Z"
            return httpx.Response(200, json={"events": [{"eventAction": "registration", "eventDate": reg}]})
        if p == "/navod.pdf" and req.url.host == "cdn.firma.cz":
            return httpx.Response(200, content=good, headers={"content-type": "application/pdf"})
        if p == "/navod.pdf":
            return httpx.Response(302, headers={"location": "https://cdn.firma.cz/navod.pdf"})
        if p == "/faktura.pdf":
            return httpx.Response(200, content=exe, headers={"content-type": "application/octet-stream"})
        return httpx.Response(404)
    rt.transport = httpx.MockTransport(handler)
    sha = hashlib.sha256(good).hexdigest()
    r = await tools.call("verify_download", {"url": "https://www.firma.cz/navod.pdf", "expected_sha256": sha}, rt)
    assert r.data["ok"] and r.data["checksum_ok"] and r.data["redirects"] == ["https://cdn.firma.cz/navod.pdf"] and r.data["type"] == "PDF"
    r = await tools.call("verify_download", {"url": "https://novy-web.cz/faktura.pdf"}, rt)
    issues = " | ".join(r.data["issues"])
    assert "neodpovídá obsahu (program Windows" in issues and "stará jen" in issues and r.summary.startswith("POZOR")
    r = await tools.call("verify_download", {"url": "https://www.firma.cz/navod.pdf", "expected_sha256": "00" * 32}, rt)
    assert r.data["checksum_ok"] is False and "NESEDÍ" in r.summary


def test_subscriptions():
    today = dt.date(2026, 10, 26)

    def m(sender, day, subj, body):
        return {"from_name": sender, "from": "x@y", "date": dt.datetime.combine(day, dt.time(9)).timestamp(), "subject": subj, "body": body}
    msgs = [m("Netflix", dt.date(2026, d, 5), "Vaše platba za předplatné", "Částka 259 Kč") for d in (7, 8, 9)]
    msgs.append(m("Netflix", dt.date(2026, 10, 5), "Vaše platba za předplatné", "Částka 299 Kč"))
    msgs += [m("Spotify AB", dt.date(2026, d, 12), "Receipt", "Total €10.99 monthly subscription") for d in (8, 9, 10)]
    msgs += [m("Antivir", dt.date(y, 3, 1), "Obnovení licence – faktura", "Celkem 1 200 Kč roční") for y in (2025, 2026)]
    msgs += [m("Posilovna", dt.date(2026, d, 1), "Faktura", "Částka 900 Kč") for d in (1, 2, 3)]       # stopped in March
    msgs.append(m("Alza", dt.date(2026, 9, 1), "Faktura", "Částka 4 999 Kč"))                           # a one-off purchase
    r = bp.subscriptions(msgs, today)
    s = {x["service"]: x for x in r["subscriptions"]}
    assert set(s) == {"Netflix", "Spotify AB", "Antivir", "Posilovna"} and s["Netflix"]["price_up"] and s["Netflix"]["amount"] == 299
    assert s["Spotify AB"]["per_month_czk"] == round(10.99 * 25) and s["Antivir"]["period"] == "ročně" and s["Posilovna"]["stale"]
    assert s["Netflix"]["next"] == "2026-11-05" and r["monthly_czk"] == 299 + 275 + 100
