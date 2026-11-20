"""Spec 2026-11-20 §5.5: learning from the user's browser – never banks, e-mail, logins or private windows."""
import sqlite3
import time

import httpx

from jarvis.webknow import browser


def _chromium(p, rows):
    c = sqlite3.connect(p)
    c.executescript("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, last_visit_time INTEGER);"
                    "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER);")
    for i, (url, title, ts) in enumerate(rows, 1):
        c.execute("INSERT INTO urls VALUES (?,?,?,?)", (i, url, title, 0))
        c.execute("INSERT INTO visits (url, visit_time) VALUES (?,?)", (i, int((ts + 11644473600) * 1e6)))
    c.commit()
    c.close()


def test_reads_chromium_and_firefox_times(tmp_path):
    t = time.time() - 60
    _chromium(tmp_path / "History", [("https://a.cz/clanek", "Článek", t)])
    rows = browser.read_history(tmp_path / "History", "chromium", t - 10)
    assert rows[0][0] == "https://a.cz/clanek" and abs(rows[0][2] - t) < 1
    assert browser.read_history(tmp_path / "History", "chromium", t + 10) == []
    f = sqlite3.connect(tmp_path / "places.sqlite")
    f.executescript("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT);"
                    "CREATE TABLE moz_historyvisits (id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER);")
    f.execute("INSERT INTO moz_places VALUES (1, 'https://b.cz/x', 'B')")
    f.execute("INSERT INTO moz_historyvisits (place_id, visit_date) VALUES (1, ?)", (int(t * 1e6),))
    f.commit()
    f.close()
    assert browser.read_history(tmp_path / "places.sqlite", "firefox", t - 10)[0][1] == "B"


def test_missing_or_garbage_history_is_empty(tmp_path):
    (tmp_path / "History").write_bytes(b"not a database")
    assert browser.read_history(tmp_path / "History", "chromium", 0) == []
    assert browser.read_history(tmp_path / "nope", "chromium", 0) == []


def test_locked_history_is_read_from_a_copy(tmp_path):
    t = time.time() - 60
    _chromium(tmp_path / "History", [("https://a.cz/1", "A", t)])
    lock = sqlite3.connect(tmp_path / "History")
    lock.execute("BEGIN EXCLUSIVE")              # the browser holds the file
    try:
        assert browser.read_history(tmp_path / "History", "chromium", t - 10)[0][0] == "https://a.cz/1"
    finally:
        lock.rollback()
        lock.close()


def test_history_files_finds_profiles(tmp_path):
    local, roaming = tmp_path / "L", tmp_path / "R"
    for p in (local / "Google/Chrome/User Data/Default", local / "Microsoft/Edge/User Data/Profile 1",
              roaming / "Mozilla/Firefox/Profiles/abc.default"):
        p.mkdir(parents=True)
    (local / "Google/Chrome/User Data/Default/History").write_bytes(b"")
    (local / "Microsoft/Edge/User Data/Profile 1/History").write_bytes(b"")
    (roaming / "Mozilla/Firefox/Profiles/abc.default/places.sqlite").write_bytes(b"")
    found = {(b, f) for b, f, _ in browser.history_files(local, roaming)}
    assert found == {("Chrome", "chromium"), ("Edge", "chromium"), ("Firefox", "firefox")}


def test_blocked_and_search_query():
    never = ["email.seznam.cz"]
    assert browser.blocked("https://ib.airbank.cz/x", never) and browser.blocked("https://email.seznam.cz/#inbox", never)
    assert browser.blocked("http://192.168.1.1/", never) and browser.blocked("https://x.cz/cb?code=abc", never)
    assert browser.blocked("chrome://settings", never) and browser.blocked("https://accounts.google.com/x", never)
    assert browser.blocked("http://localhost:3000/", never)
    assert not browser.blocked("https://www.novinky.cz/clanek", never)
    assert browser.search_query("https://www.google.com/search?q=kvantov%C3%BD+po%C4%8D%C3%ADta%C4%8D") == "kvantový počítač"
    assert browser.search_query("https://search.seznam.cz/?q=gta") == "gta"
    assert browser.search_query("https://www.novinky.cz/?q=x") is None


async def test_learn_round_stores_pages_titles_and_queries(rt, tmp_path, monkeypatch):
    t = time.time() - 60
    _chromium(tmp_path / "History", [("https://a.cz/clanek", "Článek", t), ("https://www.google.com/search?q=gta+6", "gta 6", t),
                                     ("https://login.x.cz/", "Login", t), ("https://b.cz/zed", "Přihlásit se", t)])
    monkeypatch.setattr(browser, "history_files", lambda *a, **k: [("Chrome", "chromium", tmp_path / "History")])
    rt.cfg.webknow.browser = True

    def h(r):
        body = b"Robot uvaril obed. " * 40 if r.url.host == "a.cz" else b"Heslo"
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html><title>X</title><body><p>" + body + b"</p></body></html>")
    rt.transport = httpx.MockTransport(h)
    assert await browser.learn_round(rt, now=t + 60) == 3
    assert rt.webknow.search("robot uvaril", kinds=("browser",)) and rt.webknow.search("hledal gta", kinds=("browser",))
    assert not rt.webknow.search("login")
    zed = rt.db.one("SELECT * FROM web_docs WHERE url='https://b.cz/zed'")     # a login wall: the anonymous title only
    assert zed["text"] == "" and zed["title"] == "X" and abs(zed["visited"] - t) < 1
    assert await browser.learn_round(rt, now=t + 120) == 0        # the same visits are not read twice


async def test_off_or_private_learns_nothing(rt, tmp_path, monkeypatch):
    t = time.time() - 60
    _chromium(tmp_path / "History", [("https://a.cz/clanek", "Článek", t)])
    monkeypatch.setattr(browser, "history_files", lambda *a, **k: [("Chrome", "chromium", tmp_path / "History")])
    assert await browser.learn_round(rt) == 0
    rt.cfg.webknow.browser = True
    rt.memory.set_private(True)
    assert await browser.learn_round(rt) == 0


def test_offer_once_and_switch_on(rt, monkeypatch):
    sent = []
    monkeypatch.setattr(rt, "notify", lambda title, body, **kw: sent.append((title, kw)) or 1)
    browser.offer(rt)
    browser.offer(rt)
    assert len(sent) == 1 and sent[0][1]["actions"][0]["action"] == "webknow_browser_on"
    import asyncio
    asyncio.run(rt.notice_action("webknow_browser_on", {}))
    assert rt.cfg.webknow.browser is True
