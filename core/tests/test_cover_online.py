"""3.12 the notch showed a grey note instead of the album cover: Windows never handed Spotify's picture over on the
user's PC. Then the cover comes from a public music catalogue (Deezer, then iTunes) by the song's title and artist."""
import asyncio
import sys
import types
from types import SimpleNamespace as NS

import httpx

from jarvis import nowplaying
from jarvis.desktop import media

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 64


def transport(seen, deezer=None, itunes=None, fail=False):
    def handler(req: httpx.Request):
        seen.append(str(req.url))
        if fail:
            raise httpx.ConnectError("blocked")
        if req.url.host == "api.deezer.com":
            return httpx.Response(200, json={"data": deezer or []})
        if req.url.host == "itunes.apple.com":
            return httpx.Response(200, json={"results": itunes or []})
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})
    return httpx.MockTransport(handler)


def test_cover_from_deezer_for_the_right_song(monkeypatch):
    monkeypatch.setattr(nowplaying, "_COVERS", type(nowplaying._COVERS)())
    seen: list = []
    deezer = [{"title": "Jiná písnička", "artist": {"name": "Yzomandias"}, "album": {"cover_xl": "https://img.test/wrong.jpg"}},
              {"title": "dřív bylo líp", "artist": {"name": "Yzomandias"}, "album": {"cover_xl": "https://img.test/right.jpg"}}]
    url = asyncio.run(nowplaying.find_cover("dřív bylo líp", "Yzomandias", transport(seen, deezer=deezer)))
    assert url.startswith("data:image/jpeg;base64,")
    assert seen[-1] == "https://img.test/right.jpg"                 # not the other song's cover
    assert nowplaying.cached_cover("dřív bylo líp", "Yzomandias") == url
    n = len(seen)
    asyncio.run(nowplaying.find_cover("dřív bylo líp", "Yzomandias", transport(seen)))
    assert len(seen) == n                                           # asked once per song


def test_cover_falls_back_to_itunes_and_never_a_wrong_artist(monkeypatch):
    monkeypatch.setattr(nowplaying, "_COVERS", type(nowplaying._COVERS)())
    seen: list = []
    itunes = [{"trackName": "Song", "artistName": "Someone Else", "artworkUrl100": "https://a.test/x/100x100bb.jpg"},
              {"trackName": "Song (Remastered)", "artistName": "The Band", "artworkUrl100": "https://a.test/y/100x100bb.jpg"}]
    url = asyncio.run(nowplaying.find_cover("Song", "The Band", transport(seen, itunes=itunes)))
    assert url and seen[-1] == "https://a.test/y/600x600bb.jpg"
    assert asyncio.run(nowplaying.find_cover("Nothing", "Nobody", transport([]))) == ""
    assert nowplaying.cached_cover("Nothing", "Nobody") == ""      # looked up, none: not asked every second


def test_no_internet_is_not_remembered_as_no_cover(monkeypatch):
    monkeypatch.setattr(nowplaying, "_COVERS", type(nowplaying._COVERS)())
    assert asyncio.run(nowplaying.find_cover("Song", "Band", transport([], fail=True))) == ""
    assert nowplaying.cached_cover("Song", "Band") is None


def test_snapshot_uses_the_online_cover_when_windows_gives_none(monkeypatch):
    monkeypatch.setattr(nowplaying, "_COVERS", type(nowplaying._COVERS)())
    nowplaying._COVERS[("Song", "X")] = "data:image/jpeg;base64,AAAA"

    async def props():
        return NS(title="Song", artist="X", album_title="", thumbnail=None)

    s = NS(source_app_user_model_id="Spotify.exe", get_playback_info=lambda: NS(playback_status=4),
           try_get_media_properties_async=props, get_timeline_properties=lambda: (_ for _ in ()).throw(RuntimeError()))
    ctl = types.ModuleType("winsdk.windows.media.control")
    ctl.GlobalSystemMediaTransportControlsSessionPlaybackStatus = NS(PLAYING=4)
    for name in ("winsdk", "winsdk.windows", "winsdk.windows.media"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "winsdk.windows.media.control", ctl)
    monkeypatch.setattr(media, "_MGR", NS(get_current_session=lambda: s, get_sessions=lambda: [s]))
    snap = asyncio.run(media._snapshot())
    assert snap["thumb"] == "data:image/jpeg;base64,AAAA"


def test_a_failing_windows_cover_is_not_read_every_second(monkeypatch):
    calls = []

    async def bad(ref):
        calls.append(1)
        raise RuntimeError("empty")

    async def props():
        return NS(title="Song2", artist="X", album_title="", thumbnail=object())

    s = NS(source_app_user_model_id="Spotify.exe", get_playback_info=lambda: NS(playback_status=4),
           try_get_media_properties_async=props, get_timeline_properties=lambda: (_ for _ in ()).throw(RuntimeError()))
    ctl = types.ModuleType("winsdk.windows.media.control")
    ctl.GlobalSystemMediaTransportControlsSessionPlaybackStatus = NS(PLAYING=4)
    for name in ("winsdk", "winsdk.windows", "winsdk.windows.media"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "winsdk.windows.media.control", ctl)
    monkeypatch.setattr(media, "_MGR", NS(get_current_session=lambda: s, get_sessions=lambda: [s]))
    monkeypatch.setattr(media, "_thumb", bad)
    monkeypatch.setattr(media, "_THUMB_FAIL", {})
    for _ in range(4):
        asyncio.run(media._snapshot())
    assert len(calls) == 1 and "empty" in media.COVER["error"]
