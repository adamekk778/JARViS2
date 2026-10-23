"""Now-playing info from Windows media sessions (Spotify, browsers, …) via winsdk."""
from __future__ import annotations

import asyncio
import base64
import logging

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
    out = {"title": props.title or "", "artist": props.artist or "", "app": s.source_app_user_model_id or "",
           "playing": info.playback_status == Status.PLAYING, "thumb": None}
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


async def watch(rt, interval: float = 2.0) -> None:
    try:
        import winsdk  # noqa: F401
    except ImportError:
        return
    last_key = None
    while True:
        try:
            snap = await _snapshot()
            key = (snap.get("title"), snap.get("artist"), snap.get("playing"))
            if key != last_key:
                last_key = key
                rt.media_state = snap
                rt.bus.publish("media", **snap)
        except Exception as e:
            log.debug("media watch: %s", e)
        await asyncio.sleep(interval)
