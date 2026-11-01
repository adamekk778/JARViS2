"""3.12: the service behind the sound (logo in the notch) and synced song lyrics (karaoke line)."""
import time

import httpx
from conftest import drain

from jarvis import nowplaying
from jarvis.desktop import media
from jarvis.server import ws


def test_source_from_app_and_window_title():
    assert nowplaying.source("Spotify.exe") == "spotify"
    assert nowplaying.source("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify") == "spotify"
    assert nowplaying.source("Chrome", "Jak postavit dům - YouTube - Google Chrome") == "youtube"
    assert nowplaying.source("MSEdge", "Lofi beats - YouTube Music - Microsoft Edge") == "youtubemusic"
    assert nowplaying.source("", "Stranger Things | Netflix") == "netflix"
    assert nowplaying.source("", "xQc - Twitch") == "twitch"
    assert nowplaying.source("Chrome", "Seznam - Google Chrome") == "browser"
    assert nowplaying.source("", "Max Verstappen onboard - YouTube") == "youtube"   # not the Max service
    assert nowplaying.source("", "Kickboxing tips - Google Chrome") == "browser"     # not Kick
    assert nowplaying.source("", "Cyberpunk 2077", fullscreen=True) == "game"
    assert nowplaying.source("", "Dokument - Word") == ""
    assert nowplaying.is_music("spotify") and not nowplaying.is_music("youtube")


LRC = """[ar:Ukázka]
[offset:+500]
[00:04.50]Svítí lampy podél cesty
[00:10.00][01:10.00]Refrén zní dvakrát
[00:15.20]<00:15.20>Slova <00:15.80>po <00:16.10>slovech
[00:20.00]
"""


def test_parse_lrc_and_current_line():
    lines = nowplaying.parse_lrc(LRC)
    assert [x["t"] for x in lines] == [4.0, 9.5, 14.7, 19.5, 69.5]          # offset +500 ms applied, sorted, repeated line twice
    assert lines[2]["text"] == "Slova po slovech" and lines[3]["text"] == ""
    assert nowplaying.line_at(lines, 1) == -1 and nowplaying.line_at(lines, 10) == 1 and nowplaying.line_at(lines, 100) == 4


def test_titles_cleaned_for_lookup():
    assert nowplaying.clean_title("Golden Hour (Official Music Video) [4K]") == "Golden Hour"
    assert nowplaying.clean_title("Here Comes the Sun - Remastered 2009") == "Here Comes the Sun"
    assert nowplaying.clean_title("Song (feat. Someone)") == "Song"
    assert nowplaying.split_artist("Imagine Dragons - Believer (Official Video)", "ImagineDragonsVEVO") == ("Believer", "Imagine Dragons")
    assert nowplaying.split_artist("Believer", "Imagine Dragons") == ("Believer", "Imagine Dragons")


def _transport(calls):
    def handler(req: httpx.Request):
        calls.append(req)
        if req.url.path.endswith("/get"):
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json=[
            {"trackName": "Song", "duration": 300, "syncedLyrics": "[00:01.00]wrong length"},
            {"trackName": "Song", "duration": 181, "syncedLyrics": "[00:02.00]první\n[00:05.00]druhá", "plainLyrics": "první\ndruhá"}])
    return httpx.MockTransport(handler)


async def test_lyrics_lookup_falls_back_to_search_and_caches():
    calls = []
    lib = nowplaying.Lyrics(transport=_transport(calls))
    r = await lib.get("Song (Official Video)", "Band", "", 180)
    assert r["synced"] and [x["text"] for x in r["lines"]] == ["první", "druhá"]          # the closest length wins
    assert calls[0].url.params["track_name"] == "Song" and calls[0].url.params["duration"] == "180"
    assert calls[0].headers["user-agent"].startswith("JARVIS")
    n = len(calls)
    await lib.get("Song", "Band", "", 180)
    assert len(calls) == n                                                                  # cached: no second request


async def test_new_song_sends_lyrics_to_the_notch(rt):
    calls = []
    rt.lyrics = nowplaying.Lyrics(transport=_transport(calls))
    snap = {"title": "Song", "artist": "Band", "source": "spotify", "duration": 181, "playing": True}
    rt.media_state = snap
    q = rt.bus.subscribe()
    await nowplaying.publish_lyrics(rt, snap)
    ev = [e for e in drain(q) if e["type"] == "lyrics"]
    assert ev and ev[0]["synced"] and ev[0]["lines"][0] == {"t": 2.0, "text": "první"} and rt.lyrics_state["title"] == "Song"
    rt.cfg.notch.lyrics = False                                                             # off in settings → nothing is looked up
    n = len(calls)
    rt.lyrics.cache.clear()
    await nowplaying.publish_lyrics(rt, {**snap, "title": "Other"})
    assert len(calls) == n
    rt.cfg.notch.lyrics, rt.cfg.brain.offline_only = True, True                             # offline mode → nothing goes out
    await nowplaying.publish_lyrics(rt, {**snap, "title": "Other"})
    assert len(calls) == n


def test_media_changes_worth_publishing():
    t = time.time()
    a = {"title": "A", "artist": "B", "playing": True, "position": 10.0, "at": t}
    assert not media.changed(a, {**a, "position": 12.0, "at": t + 2})                       # just time going on
    assert media.changed(a, {**a, "position": 60.0, "at": t + 2})                           # a seek
    assert media.changed(a, {**a, "playing": False})
    assert media.changed(a, {**a, "title": "C"})
    assert media.changed({}, a)


def test_lyrics_is_a_server_message():
    assert "lyrics" in ws.SERVER_TYPES
