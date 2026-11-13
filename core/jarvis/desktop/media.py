"""Now-playing info from Windows media sessions (Spotify, browsers, …) via winsdk."""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

log = logging.getLogger(__name__)


_MGR: Any = None


async def _within(aw, secs: float):
    """Await a Windows media call, but never forever: some players (and headset apps) never answer Windows' "what is
    playing?" – the whole music watcher then hung and the notch never showed a song (seen on a real PC, 3.10.186)."""
    fut = asyncio.ensure_future(aw)
    done, _ = await asyncio.wait({fut}, timeout=secs)
    if not done:
        fut.cancel()
        raise asyncio.TimeoutError(f"Windows media call did not answer in {secs:g} s")
    return fut.result()


async def _manager():
    global _MGR
    if _MGR is None:
        from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager

        _MGR = await _within(Manager.request_async(), 5)
    return _MGR


def forget_manager() -> None:
    """After a hang: ask Windows for a fresh manager next time."""
    global _MGR
    _MGR = None


async def _snapshot() -> dict:
    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status

    mgr = await _manager()
    stuck: list[str] = []
    for s in ordered_sessions(mgr, Status.PLAYING)[:5]:
        try:
            props = await _within(s.try_get_media_properties_async(), 2.5)
        except asyncio.TimeoutError:
            app = str(getattr(s, "source_app_user_model_id", "") or "?")   # this player does not answer: try the next one
            stuck.append(app.split("!")[0].split("\\")[-1])
            log.debug("media: %s did not answer", app)
            continue
        if props is None:
            continue
        info = s.get_playback_info()
        out = {"title": props.title or "", "artist": props.artist or "", "album": getattr(props, "album_title", "") or "",
               "app": s.source_app_user_model_id or "", "playing": info.playback_status == Status.PLAYING, "thumb": None}
        if not out["title"]:
            continue
        out.update(_timeline(s, out["playing"]))
        if props.thumbnail:
            try:
                from winsdk.windows.storage.streams import Buffer, InputStreamOptions

                stream = await _within(props.thumbnail.open_read_async(), 2)
                buf = Buffer(stream.size)
                await _within(stream.read_async(buf, buf.capacity, InputStreamOptions.READ_AHEAD), 2)
                data = bytes(memoryview(buf))
                if data:
                    out["thumb"] = "data:image/png;base64," + base64.b64encode(data).decode()
            except Exception:  # noqa: BLE001 – a song without its cover is fine
                pass
        return out
    if stuck:
        raise asyncio.TimeoutError("neodpovídá: " + ", ".join(dict.fromkeys(stuck)))
    return {}


def ordered_sessions(mgr, playing_status) -> list:
    """Players in the order worth asking: the current one if it plays, other playing ones, then the current, the rest."""
    try:
        cur = mgr.get_current_session()
    except Exception:  # noqa: BLE001
        cur = None
    try:
        sessions = list(mgr.get_sessions())
    except Exception:  # noqa: BLE001
        sessions = []

    def plays(x) -> bool:
        try:
            return x.get_playback_info().playback_status == playing_status
        except Exception:  # noqa: BLE001
            return False

    def touched(x) -> float:
        """When this player last moved (play, pause, a new song, a seek) – the one you just started is the newest."""
        try:
            t = x.get_timeline_properties().last_updated_time
            return t.timestamp() if t and t.year > 2000 else 0.0
        except Exception:  # noqa: BLE001
            return 0.0

    # several "playing" at once (a video tab that still says so, a game, Spotify): the one you touched last wins
    playing = sorted([x for x in sessions if plays(x)], key=touched, reverse=True)
    if cur is not None and plays(cur) and not any(touched(x) > touched(cur) + 1 for x in playing):
        playing.insert(0, cur)
    out: list = []
    for x in playing + ([cur] if cur is not None else []) + sessions:
        if x is not None and all(x is not y for y in out):
            out.append(x)
    return out


def pick_session(mgr, playing_status):
    """The player that really plays. Windows' "current" session is often a paused browser tab or a game while
    Spotify plays – then the notch showed nothing. Playing first (the current one if it plays), else the current."""
    o = ordered_sessions(mgr, playing_status)
    return o[0] if o else None


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
    mgr = await _manager()
    s = mgr.get_current_session()
    if not s:
        return False
    return bool(await _within(s.try_change_playback_position_async(int(max(0.0, seconds) * 10_000_000)), 3))   # 100 ns ticks


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
    fails = 0
    while True:
        try:
            try:
                snap = await _within(_snapshot(), 8)
            except asyncio.TimeoutError:
                forget_manager()                   # a fresh start next round; the song stays as it was meanwhile
                raise
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
            fails = 0
        except Exception as e:
            fails += 1
            if fails >= 3 and prev:                # ~half a minute without an answer: never keep showing an old song
                prev = {}
                rt.media_state = {}
                rt.bus.publish("media")
            if f"{type(e).__name__}: {e}" != last_err:              # each new reason once at warning level
                last_err = f"{type(e).__name__}: {e}"
                log.warning("hudba v notchi: %s", last_err)
            else:
                log.debug("media watch: %s", e)
        await asyncio.sleep(interval)
