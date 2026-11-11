"""3.12 search music across services from the notch.

Results (top result, artists with photos, songs with covers, an artist's page) come from Deezer's public catalogue
(no key, no account; only the words you search for are sent). A song then plays where you choose: Spotify (the app
opens its search for the song), YouTube (plays it right away), YouTube Music, Apple Music, SoundCloud, Amazon Music or
Deezer (the exact song). Nothing is downloaded and nothing is logged in on your behalf.
"""
from __future__ import annotations

import asyncio
from urllib.parse import quote

API = "https://api.deezer.com"
SERVICES = ("auto", "spotify", "youtube", "youtubemusic", "applemusic", "soundcloud", "amazonmusic", "deezer")


def _track(t: dict) -> dict:
    al, ar = t.get("album") or {}, t.get("artist") or {}
    return {"id": t.get("id"), "title": t.get("title_short") or t.get("title") or "", "artist": ar.get("name", ""), "artist_id": ar.get("id"),
            "album": al.get("title", ""), "cover": al.get("cover_medium") or al.get("cover") or "", "cover_big": al.get("cover_big") or "",
            "duration": t.get("duration") or 0, "preview": t.get("preview") or "", "explicit": bool(t.get("explicit_lyrics"))}


def _artist(a: dict) -> dict:
    return {"id": a.get("id"), "name": a.get("name", ""), "picture": a.get("picture_medium") or a.get("picture") or "",
            "picture_big": a.get("picture_big") or "", "fans": a.get("nb_fan") or 0}


async def _get(rt, path: str, params: dict | None = None) -> dict:
    async with rt.http() as c:
        r = await c.get(f"{API}{path}", params=params or {}, timeout=12)
        r.raise_for_status()
        data = r.json()
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(str(data["error"].get("message") or "chyba katalogu"))
    return data


async def search(rt, q: str) -> dict:
    q = " ".join((q or "").split())[:120]
    if not q:
        return {"q": "", "top": None, "artists": [], "tracks": [], "albums": []}
    tracks, artists, albums = await asyncio.gather(
        _get(rt, "/search", {"q": q, "limit": 12}), _get(rt, "/search/artist", {"q": q, "limit": 6}),
        _get(rt, "/search/album", {"q": q, "limit": 6}), return_exceptions=True)
    tr = [_track(t) for t in (tracks.get("data", []) if isinstance(tracks, dict) else [])]
    ar = [_artist(a) for a in (artists.get("data", []) if isinstance(artists, dict) else [])]
    al = [{"id": a.get("id"), "title": a.get("title", ""), "artist": (a.get("artist") or {}).get("name", ""), "cover": a.get("cover_medium") or ""}
          for a in (albums.get("data", []) if isinstance(albums, dict) else [])]
    if not (tr or ar or al) and all(isinstance(x, Exception) for x in (tracks, artists, albums)):
        raise RuntimeError("Hudební katalog teď neodpovídá – zkontroluj internet")
    # the top result: an artist whose name is what you typed, else the first song
    low = q.lower()
    top = next(({"kind": "artist", **a} for a in ar if a["name"].lower() == low), None) or (
        {"kind": "track", **tr[0]} if tr else ({"kind": "artist", **ar[0]} if ar else None))
    return {"q": q, "top": top, "artists": ar, "tracks": tr, "albums": al}


async def artist(rt, aid: int) -> dict:
    a, top = await asyncio.gather(_get(rt, f"/artist/{int(aid)}"), _get(rt, f"/artist/{int(aid)}/top", {"limit": 10}))
    return {**_artist(a), "tracks": [_track(t) for t in top.get("data", [])], "albums_count": a.get("nb_album") or 0}


def link(service: str, track: dict) -> str:
    """Where a song opens on each service (Spotify / Apple Music / … get a search for exactly that song)."""
    title, art = str(track.get("title") or "")[:120], str(track.get("artist") or "")[:80]
    q = f"{art} {title}".strip()
    if service == "spotify":
        return f"spotify:search:{quote(q)}"
    if service == "youtubemusic":
        return f"https://music.youtube.com/search?q={quote(q)}"
    if service == "applemusic":
        return f"https://music.apple.com/search?term={quote(q)}"
    if service == "soundcloud":
        return f"https://soundcloud.com/search/sounds?q={quote(q)}"
    if service == "amazonmusic":
        return f"https://music.amazon.com/search/{quote(q)}"
    if service == "deezer":
        tid = track.get("id")
        return f"https://www.deezer.com/track/{int(tid)}" if str(tid or "").isdigit() else f"https://www.deezer.com/search/{quote(q)}"
    return ""


async def play(rt, service: str, track: dict) -> dict:
    service = service if service in SERVICES else "auto"
    title, art = str(track.get("title") or ""), str(track.get("artist") or "")
    if not title:
        return {"ok": False, "message": "Chybí název skladby"}
    if service in ("auto", "youtube"):                     # plays straight away (the first YouTube result)
        from . import tools

        r = await tools.call("youtube_play", {"query": f"{art} {title} official audio".strip()}, rt)
        return {"ok": r.ok, "message": r.message}
    url = link(service, track)
    await asyncio.to_thread(rt.platform.open_url, url)
    names = {"spotify": "Spotify", "youtubemusic": "YouTube Music", "applemusic": "Apple Music", "soundcloud": "SoundCloud",
             "amazonmusic": "Amazon Music", "deezer": "Deezer"}
    return {"ok": True, "message": f"Otevírám {title} v {names.get(service, service)}"}
