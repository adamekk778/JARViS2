"""Spec 2026-11-20 §5.12: JARVIS knows what the videos you watch were about – from their subtitles."""
import datetime as dt
import time

from jarvis.webknow import youtube

INFO = {"title": "Robot vaří", "channel": "Tech", "duration": 60, "description": "popis", "subtitles": "robot uvaril obed"}


def test_video_id_variants():
    for u in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "https://youtu.be/dQw4w9WgXcQ", "https://m.youtube.com/shorts/dQw4w9WgXcQ"):
        assert youtube.video_id(u) == "dQw4w9WgXcQ"
    assert youtube.video_id("https://www.youtube.com/") is None
    assert youtube.video_id("https://www.novinky.cz/watch?v=dQw4w9WgXcQ") is None


def test_vtt_rolling_captions_deduped():
    vtt = ("WEBVTT\nKind: captions\nLanguage: cs\n\n00:00:00.000 --> 00:00:02.000 align:start position:0%\nahoj <c>lidi</c>\n\n"
           "00:00:02.000 --> 00:00:04.000\nahoj lidi\ndnes <00:00:03.000>vaříme\n")
    assert youtube.vtt_to_text(vtt) == "ahoj lidi dnes vaříme"


async def test_learn_video_and_daily_cap(rt, monkeypatch):
    monkeypatch.setattr(youtube, "fetch_info", lambda url: dict(INFO))
    assert await youtube.learn_video(rt, "https://youtu.be/aaaaaaaaaaa")
    hit = rt.webknow.search("robot uvaril", kinds=("video",))[0]
    assert hit["url"] == "https://www.youtube.com/watch?v=aaaaaaaaaaa" and hit["source"] == "Tech"
    assert await youtube.learn_video(rt, "https://www.youtube.com/watch?v=aaaaaaaaaaa") is None
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('webknow_yt_day', ?)", (f"{dt.date.today().isoformat()}:30",))
    assert await youtube.learn_video(rt, "https://youtu.be/bbbbbbbbbbb") is None


async def test_no_subtitles_keeps_title_and_description(rt, monkeypatch):
    monkeypatch.setattr(youtube, "fetch_info", lambda url: {**INFO, "title": "Hudba", "description": "jen hudba", "subtitles": ""})
    d = rt.webknow.get(await youtube.learn_video(rt, "https://youtu.be/ccccccccccc"))
    assert d["text"] == "jen hudba"


async def test_off_private_or_broken_learns_nothing(rt, monkeypatch):
    monkeypatch.setattr(youtube, "fetch_info", lambda url: dict(INFO))
    rt.cfg.webknow.youtube = False
    assert await youtube.learn_video(rt, "https://youtu.be/ddddddddddd") is None
    rt.cfg.webknow.youtube = True
    rt.memory.set_private(True)
    assert await youtube.learn_video(rt, "https://youtu.be/ddddddddddd") is None
    rt.memory.set_private(False)

    def boom(url):
        raise RuntimeError("yt-dlp failed")
    monkeypatch.setattr(youtube, "fetch_info", boom)
    assert await youtube.learn_video(rt, "https://youtu.be/eeeeeeeeeee") is None


async def test_browser_sends_youtube_visits_here(rt, tmp_path, monkeypatch):
    import sqlite3
    from jarvis.webknow import browser
    monkeypatch.setattr(youtube, "fetch_info", lambda url: dict(INFO))
    t = time.time() - 60
    c = sqlite3.connect(tmp_path / "History")
    c.executescript("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, last_visit_time INTEGER);"
                    "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER);")
    c.execute("INSERT INTO urls VALUES (1, 'https://www.youtube.com/watch?v=fffffffffff', 'Robot vaří - YouTube', 0)")
    c.execute("INSERT INTO visits (url, visit_time) VALUES (1, ?)", (int((t + 11644473600) * 1e6),))
    c.commit()
    c.close()
    monkeypatch.setattr(browser, "history_files", lambda *a, **k: [("Chrome", "chromium", tmp_path / "History")])
    rt.cfg.webknow.browser = True
    assert await browser.learn_round(rt, now=t + 60) == 1
    assert rt.webknow.search("robot uvaril", kinds=("video",))
