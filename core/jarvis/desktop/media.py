"""Now-playing info from Windows media sessions (Spotify, browsers, …) via winsdk."""
from __future__ import annotations

import asyncio
import base64
import logging
import time

log = logging.getLogger(__name__)


async def _snapshot() -> dict:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
    )

    mgr = await Manager.request_async()
    s = mgr.get_current_session()
    if not s:
        return {}
    props = await s.try_get_media_properties_async()
    info = s.get_playback_info()
    out = {"title": props.title or "", "artist": props.artist or "", "album": getattr(props, "album_title", "") or "",
           "app": s.source_app_user_model_id or "", "playing": info.playback_status == Status.PLAYING, "thumb": None}
    out.update(_timeline(s, out["playing"]))
    if props.thumbnail:
        try:
            from winsdk.windows.storage.streams import Buffer, InputStreamOptions

            stream = await props.thumbnail.open_read_async()
            buf = Buffer(stream.size)
            await stream.read_async(buf, buf.capacity, InputStreamOptions.READ_AHEAD)
            data = bytes(memoryview(buf))
            if data:
                out["thumb"] = "data:image/png;base64," + base64.b64encode(data).decode()
        except Exception:
            pass
    return out


def _timeline(s, playing: bool) -> dict:
    """Where in the song / video we are: position now (s), length (s) and when it was read (for the lyrics bar).
    Players update the timeline only on play / pause / seek, so the time since then is added while playing."""
    try:
        import datetime as dt

        tl = s.get_timeline_properties()
        pos = tl.position.total_seconds()
        dur = (tl.end_time - tl.start_time).total_seconds()
        upd = tl.last_updated_time
        if playing and upd and upd.year > 2000:
            pos += max(0.0, (dt.datetime.now(dt.timezone.utc) - upd).total_seconds())
        if dur <= 0:
            return {}
        return {"position": round(min(max(pos, 0.0), dur), 2), "duration": round(dur, 2), "at": time.time()}
    except Exception:
        return {}


async def seek(seconds: float) -> bool:
    """Jump to a place in the song (3.12 music screen: the progress bar and a click on a lyric line). Windows asks the
    player; Spotify, browsers and most players allow it. False when there is no player or it refused."""
    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager

    mgr = await Manager.request_async()
    s = mgr.get_current_session()
    if not s:
        return False
    return bool(await s.try_change_playback_position_async(int(max(0.0, seconds) * 10_000_000)))   # 100 ns ticks


def changed(prev: dict, snap: dict, tolerance: float = 2.5) -> bool:
    """A new song, play / pause, or a jump in the song (seek) – worth telling the notch."""
    if (prev.get("title"), prev.get("artist"), prev.get("playing")) != (snap.get("title"), snap.get("artist"), snap.get("playing")):
        return True
    if "position" in snap and "position" in prev:
        expect = prev["position"] + ((snap.get("at", 0) - prev.get("at", 0)) if prev.get("playing") else 0)
        return abs(snap["position"] - expect) > tolerance
    return "position" in snap and "position" not in prev


async def watch(rt, interval: float = 2.0) -> None:
    try:
        import winsdk  # noqa: F401
    except ImportError as e:
        log.warning("hudba v notchi nejde: chybí winsdk (%s)", e)    # the reason in the log, not silence
        return
    from .. import nowplaying

    prev: dict = {}
    last_err = ""
    while True:
        try:
            snap = await _snapshot()
            if snap:
                try:
                    front = rt.platform.foreground_info() or {}
                except Exception:
                    front = {}
                # a music app names itself; a browser tab is told by the window title ("… - YouTube - Google Chrome")
                snap["source"] = nowplaying.source(snap.get("app", ""), front.get("title", ""), snap.get("title", ""))
            new_song = (snap.get("title"), snap.get("artist")) != (prev.get("title"), prev.get("artist"))
            if changed(prev, snap):
                rt.media_state = snap
                rt.bus.publish("media", **snap)
                if new_song and snap.get("title"):
                    rt.lyrics_state = {}
                    asyncio.get_running_loop().create_task(nowplaying.publish_lyrics(rt, snap))
            prev = snap
        except Exception as e:
            if f"{type(e).__name__}: {e}" != last_err:              # each new reason once at warning level
                last_err = f"{type(e).__name__}: {e}"
                log.warning("hudba v notchi: %s", last_err)
            else:
                log.debug("media watch: %s", e)
        await asyncio.sleep(interval)
