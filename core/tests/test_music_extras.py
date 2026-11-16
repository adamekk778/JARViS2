"""3.12 Hudba: Spotify's exact clock and cover, a Czech translation of the lyrics, the notch in the wallpaper's colour."""
import asyncio
import json
from types import SimpleNamespace as NS

import httpx
import pytest

from jarvis import connectors, nowplaying, secrets
from jarvis.desktop import media


@pytest.fixture
def vault(monkeypatch):
    store = {}
    monkeypatch.setattr(secrets, "get", lambda k: store.get(k, ""))
    monkeypatch.setattr(secrets, "set", lambda k, v: store.__setitem__(k, v))
    connectors.load()
    return store


def test_spotify_gives_the_exact_place_and_the_cover(vault, monkeypatch):
    from jarvis.connectors import spotify

    vault.update({"conn.spotify.client_id": "cid", "conn.spotify.refresh_token": "RT"})
    spotify._ACCESS.update(token="", until=0)
    media._SPOT.update(at=0.0, now=None, covers={})

    def handler(req: httpx.Request):
        if req.url.host == "accounts.spotify.com":
            return httpx.Response(200, json={"access_token": "AT", "expires_in": 3600, "refresh_token": "RT2"})
        if req.url.host == "api.spotify.com":
            return httpx.Response(200, json={"is_playing": True, "progress_ms": 61500, "item": {
                "name": "NIGHTS LIKE THIS", "duration_ms": 204000, "artists": [{"name": "The Kid LAROI"}, {"name": "Ty Dolla $ign"}],
                "album": {"images": [{"url": "https://i.scdn.co/image/big", "width": 640}]}}})
        return httpx.Response(200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg"})

    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(handler))
    snap = {"title": "NIGHTS LIKE THIS", "artist": "The Kid LAROI, Ty Dolla $ign", "position": 3.0, "estimated": True, "thumb": None}
    assert asyncio.run(media.spotify_sync(snap))
    assert 61.4 < snap["position"] < 62.5 and snap["duration"] == 204.0 and "estimated" not in snap
    assert snap["thumb"].startswith("data:image/jpeg;base64,") and vault["conn.spotify.refresh_token"] == "RT2"
    other = {"title": "Something else", "artist": "X", "position": 1.0}
    assert not asyncio.run(media.spotify_sync(other)) and other["position"] == 1.0     # a different song: untouched


def test_spotify_not_connected_changes_nothing(vault):
    snap = {"title": "A", "position": 1.0}
    assert not asyncio.run(media.spotify_sync(snap)) and snap == {"title": "A", "position": 1.0}


def test_lyrics_translation_once_per_song(monkeypatch):
    nowplaying._TR.clear()
    calls = []

    async def complete(msgs, **kw):
        calls.append(kw)
        return json.dumps(["Drž mě za ruku", "", "Noci jako tahle"])

    sent = []
    rt = NS(router=NS(complete=complete), media_state={"title": "Song"},
            lyrics_state={"title": "Song", "lines": []}, bus=NS(publish=lambda t, **k: sent.append((t, k))))
    lines = [{"t": 1, "text": "Hold my hand"}, {"t": 2, "text": ""}, {"t": 3, "text": "Nights like this"}]
    tr = asyncio.run(nowplaying.translate_lyrics(rt, "Song", lines))
    assert tr[0] == "Drž mě za ruku" and rt.lyrics_state["tr"] == tr and sent[-1][0] == "lyrics"
    asyncio.run(nowplaying.translate_lyrics(rt, "Song", lines))
    assert len(calls) == 1 and calls[0].get("fast")                      # remembered; the quick model


def test_czech_lyrics_are_not_translated():
    assert nowplaying.looks_czech([{"text": "Řekni mi, kde ty kytky jsou"}, {"text": "Co se s nimi stalo"}])
    assert not nowplaying.looks_czech([{"text": "Hold my hand"}, {"text": "until we turn to ashes"}])


def test_wallpaper_thumbnail(tmp_path, monkeypatch):
    from PIL import Image

    from jarvis import wallpaper

    p = tmp_path / "wall.png"
    Image.new("RGB", (800, 600), (30, 80, 200)).save(p)
    monkeypatch.setenv("JARVIS_WALLPAPER", str(p))
    wallpaper._CACHE.update(key=None, thumb="")
    t = wallpaper.thumb()
    assert t.startswith("data:image/jpeg;base64,") and len(t) < 4000
    monkeypatch.setenv("JARVIS_WALLPAPER", str(tmp_path / "missing.png"))
    assert wallpaper.thumb() == ""
