"""3.14 the notch showed a different song's words: only this song's lyrics, and only the newest lookup wins."""
import asyncio

import httpx

from jarvis import nowplaying


def _lib(search=None, get=None, calls=None):
    def handler(req: httpx.Request):
        if calls is not None:
            calls.append(req)
        if req.url.path.endswith("/get"):
            return httpx.Response(200, json=get) if get else httpx.Response(404, json={})
        return httpx.Response(200, json=search or [])
    return nowplaying.Lyrics(transport=httpx.MockTransport(handler))


def item(track, artist, dur, lrc="[00:01.00]a\n[00:03.00]b", plain="a\nb"):
    return {"trackName": track, "artistName": artist, "duration": dur, "syncedLyrics": lrc, "plainLyrics": plain}


def test_same_title_and_artist():
    assert not nowplaying.same_artist("The Weeknd", "The Beatles")          # "The" is not a match
    assert nowplaying.same_artist("The Kid LAROI, Justin Bieber", "The Kid LAROI")
    assert nowplaying.same_artist("AC/DC", "ACDC")
    assert not nowplaying.same_title("Stay", "Stay With Me")
    assert nowplaying.same_title("Here Comes the Sun - Remastered 2009", "Here Comes The Sun")


async def test_another_artists_song_with_the_same_title_is_refused():
    lib = _lib(search=[item("Stay", "Rihanna", 240, "[00:01.00]rihanna"), item("Stay With Me", "Sam Smith", 172)])
    r = await lib.get("Stay", "The Kid LAROI, Justin Bieber", "", 141)
    assert r["lines"] == [] and r["plain"] == ""                           # nothing rather than another song's words


async def test_the_right_song_among_wrong_ones():
    right = item("Stay", "The Kid LAROI", 141, "[00:02.00]I do the same thing I told you that I never would")
    lib = _lib(search=[item("Stay", "Rihanna", 240, "[00:01.00]rihanna"), right])
    r = await lib.get("Stay", "The Kid LAROI, Justin Bieber", "", 141)
    assert r["synced"] and r["lines"][0]["text"].startswith("I do the same thing")


async def test_another_version_is_shown_without_timing():
    live = item("Song", "Band", 260, "[00:05.00]live timing", "live text")       # 80 s longer: a live version
    lib = _lib(search=[live])
    r = await lib.get("Song", "Band", "", 180)
    assert not r["synced"] and r["plain"] == "live text"                   # the words, but no karaoke out of step


async def test_get_result_is_checked_too():
    lib = _lib(get=item("Totally Different", "Someone Else", 180))
    r = await lib.get("Song", "Band", "", 180)
    assert r["lines"] == [] and r["plain"] == ""


async def test_older_lookup_cannot_overwrite_the_newer_one(rt):
    slow = asyncio.Event()

    class Lib:
        async def get(self, title, artist, album="", duration=0):
            if artist == "Old Artist":            # Windows said the new title with the old artist for a moment
                await slow.wait()
                return {"lines": [{"t": 1.0, "text": "wrong song"}], "synced": True, "plain": ""}
            return {"lines": [{"t": 1.0, "text": "right song"}], "synced": True, "plain": ""}

    rt.lyrics = Lib()
    rt.cfg.notch.lyrics_translate = False
    first = {"title": "New", "artist": "Old Artist", "source": "spotify", "playing": True}
    rt.media_state = first
    t1 = asyncio.create_task(nowplaying.publish_lyrics(rt, first))
    await asyncio.sleep(0)
    second = {**first, "artist": "New Artist"}
    rt.media_state = second
    await nowplaying.publish_lyrics(rt, second)
    slow.set()
    await t1
    assert rt.lyrics_state["lines"][0]["text"] == "right song" and rt.lyrics_state["artist"] == "New Artist"


async def test_settle_takes_the_song_as_it_is_a_moment_later(rt):
    seen = []

    class Lib:
        async def get(self, title, artist, album="", duration=0):
            seen.append((artist, duration))
            return {"lines": [{"t": 1.0, "text": "x"}], "synced": True, "plain": ""}

    rt.lyrics = Lib()
    rt.cfg.notch.lyrics_translate = False
    snap = {"title": "New", "artist": "Old Artist", "duration": 200, "source": "spotify", "playing": True}
    rt.media_state = snap
    task = asyncio.create_task(nowplaying.publish_lyrics(rt, snap, settle=0.05))
    rt.media_state = {**snap, "artist": "New Artist", "duration": 141}
    await task
    assert seen == [("New Artist", 141.0)]


async def test_other_lyrics_button_skips_that_text(rt):
    from jarvis import tools

    tools.load_builtin()
    a = {**item("Song", "Band", 180, "[00:01.00]wrong words"), "id": 11}
    b = {**item("Song", "Band", 181, "[00:01.00]right words"), "id": 22}
    calls = []
    rt.lyrics = _lib(search=[a, b], calls=calls)
    rt.cfg.notch.lyrics_translate = False
    snap = {"title": "Song", "artist": "Band", "duration": 180, "source": "spotify", "playing": True}
    rt.media_state = snap
    await nowplaying.publish_lyrics(rt, snap)
    assert rt.lyrics_state["lines"][0]["text"] == "wrong words" and rt.lyrics_state["src_id"] == 11
    r = await tools.call("lyrics_wrong", {}, rt)
    assert r.ok and rt.lyrics_state["lines"][0]["text"] == "right words"
    assert nowplaying.wrong_ids(rt, "Song", "Band") == (11,)
    r = await tools.call("lyrics_wrong", {}, rt)                            # the last one too: nothing rather than wrong
    assert r.ok and "nenašel" in r.summary and not rt.lyrics_state.get("lines")
    rt.lyrics_state = {}
    r = await tools.call("lyrics_wrong", {}, rt)
    assert not r.ok
