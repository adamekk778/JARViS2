"""What is playing and where (3.12): the service behind the sound (YouTube, Netflix, Spotify…) for its logo in the notch,
and synced song lyrics so the notch can show the line being sung with a bar running under it (karaoke).

The source comes from the Windows media session's app id and the active window title (a browser tab says
"… - YouTube"). Lyrics come from LRCLIB (lrclib.net, free and open, no account): only the song title, artist,
album and length are sent, never any sound. It can be turned off (Nastavení → Notch) and is off in offline mode.
"""
from __future__ import annotations

import asyncio

import logging
import os
import re
from collections import OrderedDict

log = logging.getLogger(__name__)

LRCLIB = "https://lrclib.net/api"
UA = "JARVIS desktop assistant (https://github.com/adamekk778/JARViS2)"

# media session app ids (Windows) → service
_APPS = (("spotify", "spotify"), ("applemusic", "applemusic"), ("itunes", "applemusic"), ("deezer", "deezer"),
         ("tidal", "tidal"), ("vlc", "vlc"), ("netflix", "netflix"), ("soundcloud", "soundcloud"), ("plex", "plex"),
         ("steam", "steam"), ("twitch", "twitch"))
# window / tab title → service (a browser tab title ends with the site name)
_TITLES = (("youtube music", "youtubemusic"), ("youtube", "youtube"), ("netflix", "netflix"), ("twitch", "twitch"),
           ("spotify", "spotify"), ("soundcloud", "soundcloud"), ("deezer", "deezer"), ("tidal", "tidal"),
           ("crunchyroll", "crunchyroll"), ("vimeo", "vimeo"), ("kick", "kick"), ("hbo max", "hbomax"), ("max", "hbomax"),
           ("plex", "plex"), ("apple music", "applemusic"))
_LOOSE = {"youtube music", "youtube", "netflix", "twitch", "spotify", "soundcloud", "crunchyroll"}   # distinctive anywhere in a title
_BROWSERS = ("chrome", "msedge", "edge", "firefox", "opera", "brave", "vivaldi", "arc")
_MUSIC = {"spotify", "applemusic", "deezer", "tidal", "soundcloud", "youtubemusic"}


def source(app_id: str = "", window_title: str = "", media_title: str = "", fullscreen: bool = False) -> str:
    """The service for the logo: "youtube", "spotify"… or "browser" / "game" / "" when it is not known."""
    a = (app_id or "").lower()
    for key, sid in _APPS:
        if key in a:
            return sid
    t = (window_title or "").lower()
    tail = re.split(r"\s[-–—|]\s", t)        # "Video - YouTube - Google Chrome" → the parts after the first dash
    for key, sid in _TITLES:
        if any(part.strip() == key or part.strip().startswith(key + " ") for part in tail[1:]) or (key in _LOOSE and key in t):
            return sid
    if any(b in a for b in _BROWSERS) or any(b in t for b in ("chrome", "edge", "firefox", "opera", "brave")):
        return "browser"
    return "game" if fullscreen else ""


def is_music(src: str) -> bool:
    return src in _MUSIC


# ---------------------------------------------------------------- lyrics
_TS = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")


def parse_lrc(text: str) -> list[dict]:
    """LRC ("[01:02.50] line") → [{"t": seconds, "text": line}] sorted by time; a line with two stamps appears twice."""
    out, offset = [], 0.0
    for raw in (text or "").splitlines():
        m = re.match(r"\[offset:\s*([+-]?\d+)\]", raw.strip(), re.I)
        if m:
            offset = int(m.group(1)) / 1000
            continue
        stamps = _TS.findall(raw)
        if not stamps:
            continue
        line = _TS.sub("", raw).strip()
        line = re.sub(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>", "", line).strip()      # word stamps of "enhanced" LRC
        for mm, ss in stamps:
            out.append({"t": round(max(0.0, int(mm) * 60 + float(ss.replace(":", ".")) - offset), 2), "text": line})
    out.sort(key=lambda x: x["t"])
    return out


def line_at(lines: list[dict], pos: float) -> int:
    """Index of the line being sung at `pos` seconds (-1 before the first one)."""
    idx = -1
    for i, ln in enumerate(lines):
        if ln["t"] <= pos:
            idx = i
        else:
            break
    return idx


def clean_title(title: str) -> str:
    """"Song (Official Video) [4K]", "Song - Remastered 2011", "Song (feat. X)" → "Song" for the lyrics lookup."""
    t = re.sub(r"\s*[\(\[][^)\]]*(official|video|audio|lyrics?|visualizer|remaster|live|4k|hd|mv|feat\.?|ft\.?)[^)\]]*[\)\]]", "", title or "", flags=re.I)
    t = re.sub(r"\s+-\s+(\d{4}\s+)?remaster(ed)?(\s+\d{4})?.*$", "", t, flags=re.I)
    t = re.sub(r"\s+(feat\.?|ft\.?)\s.+$", "", t, flags=re.I)
    return t.strip(" -–|")


def split_artist(title: str, artist: str) -> tuple[str, str]:
    """A YouTube video "Artist - Song" with the channel as artist → (song, artist)."""
    if " - " in (title or "") and (not artist or artist.lower().endswith(("vevo", " - topic")) or artist.lower() in title.lower()):
        a, s = title.split(" - ", 1)
        return clean_title(s), a.strip()
    return clean_title(title), re.sub(r"\s*(VEVO| - Topic)$", "", artist or "").strip()


class Lyrics:
    def __init__(self, transport=None, cache_size: int = 64):
        self.transport = transport
        self.cache: OrderedDict = OrderedDict()
        self.size = cache_size

    async def get(self, title: str, artist: str, album: str = "", duration: float = 0) -> dict:
        """{"lines": [{t, text}], "synced": bool, "plain": str} – empty lines when nothing was found."""
        song, singer = split_artist(title, artist)
        key = (song.lower(), singer.lower())
        if not song:
            return {"lines": [], "synced": False, "plain": ""}
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        res = {"lines": [], "synced": False, "plain": ""}
        if not os.environ.get("JARVIS_NO_NET") or self.transport is not None:
            try:
                res = await self._fetch(song, singer, album, duration)
            except Exception as e:  # noqa: BLE001
                log.info("lyrics %s – %s: %s", singer, song, e)
                return {**res, "error": f"{type(e).__name__}: {e}"}    # not cached: a network error may pass
        self.cache[key] = res
        while len(self.cache) > self.size:
            self.cache.popitem(last=False)
        return res

    async def _fetch(self, song: str, artist: str, album: str, duration: float) -> dict:
        import httpx

        async with httpx.AsyncClient(transport=self.transport, timeout=8, headers={"User-Agent": UA}) as c:
            item = None
            params = {"track_name": song, "artist_name": artist}
            if album:
                params["album_name"] = album
            if duration:
                params["duration"] = str(int(round(duration)))
            r = await c.get(f"{LRCLIB}/get", params=params)
            if r.status_code == 200:
                item = r.json()
            if not item or not item.get("syncedLyrics"):
                r = await c.get(f"{LRCLIB}/search", params={"track_name": song, "artist_name": artist} if artist else {"q": song})
                if r.status_code == 200:
                    found = [x for x in r.json() or [] if isinstance(x, dict)]
                    if duration:
                        found.sort(key=lambda x: abs(float(x.get("duration") or 0) - duration))
                    item = next((x for x in found if x.get("syncedLyrics")), item or (found[0] if found else None))
        if not item:
            return {"lines": [], "synced": False, "plain": ""}
        lines = parse_lrc(item.get("syncedLyrics") or "")
        return {"lines": lines, "synced": bool(lines), "plain": (item.get("plainLyrics") or "")[:6000]}


async def publish_lyrics(rt, snap: dict) -> None:
    """New song playing → look its lyrics up and send them to the notch (once per song)."""
    if not getattr(rt.cfg.notch, "lyrics", True) or rt.cfg.brain.offline_only:
        return
    src = snap.get("source", "")
    if not snap.get("title") or not (is_music(src) or snap.get("artist")):
        return
    lib = getattr(rt, "lyrics", None)
    if lib is None:
        lib = rt.lyrics = Lyrics()
    res = await lib.get(snap.get("title", ""), snap.get("artist", ""), snap.get("album", ""), float(snap.get("duration") or 0))
    for wait in (10, 30, 90):                    # no internet for a moment (or blocked): try again while the song plays
        if not res.get("error"):
            break
        await asyncio.sleep(wait)
        if (rt.media_state or {}).get("title") != snap.get("title"):
            return
        res = await lib.get(snap.get("title", ""), snap.get("artist", ""), snap.get("album", ""), float(snap.get("duration") or 0))
    if (rt.media_state or {}).get("title") != snap.get("title"):
        return                                   # the song changed meanwhile
    rt.lyrics_state = {"title": snap.get("title", ""), "artist": snap.get("artist", ""), "synced": res["synced"],
                       "lines": res["lines"][:400], "plain": "" if res["synced"] else (res.get("plain") or "")[:6000]}
    rt.bus.publish("lyrics", **rt.lyrics_state)
