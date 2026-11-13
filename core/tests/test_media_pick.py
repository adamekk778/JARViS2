"""3.12 the notch showed nothing while Spotify played: Windows' "current" media session was a paused browser tab."""
from types import SimpleNamespace as NS

from jarvis.desktop.media import pick_session

PLAYING, PAUSED = 4, 5


def sess(name, status):
    return NS(name=name, get_playback_info=lambda: NS(playback_status=status))


def mgr(current, *others):
    return NS(get_current_session=lambda: current, get_sessions=lambda: [current, *others] if current else list(others))


def test_the_playing_one_wins_over_a_paused_current():
    chrome, spotify = sess("chrome", PAUSED), sess("spotify", PLAYING)
    assert pick_session(mgr(chrome, spotify), PLAYING).name == "spotify"


def test_current_when_it_plays_and_fallbacks():
    a, b = sess("a", PLAYING), sess("b", PLAYING)
    assert pick_session(mgr(a, b), PLAYING).name == "a"
    p = sess("p", PAUSED)
    assert pick_session(mgr(p), PLAYING).name == "p"                    # nothing plays: show the paused one
    assert pick_session(mgr(None, sess("x", PAUSED)), PLAYING).name == "x"
    assert pick_session(mgr(None), PLAYING) is None


def test_a_player_that_never_answers_is_skipped(monkeypatch):
    """On a real PC (3.10.186) one media session never answered Windows – the whole music watcher waited forever and
    the notch never showed a song. Now that player is skipped and the next one that plays is shown."""
    import asyncio
    import sys
    import types

    from jarvis.desktop import media

    class Never:
        def __await__(self):
            return asyncio.get_event_loop().create_future().__await__()     # never resolves

    async def props_of(title):
        return NS(title=title, artist="X", album_title="", thumbnail=None)

    hang = NS(source_app_user_model_id="G HUB", get_playback_info=lambda: NS(playback_status=PLAYING),
              try_get_media_properties_async=lambda: Never(), get_timeline_properties=lambda: (_ for _ in ()).throw(RuntimeError()))
    good = NS(source_app_user_model_id="Spotify.exe", get_playback_info=lambda: NS(playback_status=PLAYING),
              try_get_media_properties_async=lambda: props_of("Song"), get_timeline_properties=lambda: (_ for _ in ()).throw(RuntimeError()))
    ctl = types.ModuleType("winsdk.windows.media.control")
    ctl.GlobalSystemMediaTransportControlsSessionPlaybackStatus = NS(PLAYING=PLAYING)
    for name in ("winsdk", "winsdk.windows", "winsdk.windows.media"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "winsdk.windows.media.control", ctl)
    monkeypatch.setattr(media, "_MGR", mgr(hang, good))
    snap = asyncio.run(asyncio.wait_for(media._snapshot(), 6))
    assert snap["title"] == "Song" and snap["app"] == "Spotify.exe"

    monkeypatch.setattr(media, "_MGR", mgr(hang))                      # only the silent one: a clear error, no hang
    try:
        asyncio.run(asyncio.wait_for(media._snapshot(), 6))
        raise AssertionError("expected a timeout")
    except asyncio.TimeoutError as e:
        assert "G HUB" in str(e)


def test_the_player_you_touched_last_wins():
    """Video, then music: the video tab still said "playing" and the notch kept showing the video."""
    import datetime as dt

    def at(name, secs):
        t = dt.datetime(2026, 11, 13, 12, 0, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=secs)
        return NS(name=name, get_playback_info=lambda: NS(playback_status=PLAYING),
                  get_timeline_properties=lambda: NS(last_updated_time=t))

    video, music = at("youtube", 0), at("spotify", 60)
    assert pick_session(mgr(video, music), PLAYING).name == "spotify"     # Windows still calls the video "current"
    assert pick_session(mgr(music, video), PLAYING).name == "spotify"
    newer_video = at("youtube", 120)
    assert pick_session(mgr(music, newer_video), PLAYING).name == "youtube"


def test_an_old_song_is_not_kept_when_windows_stops_answering(monkeypatch, rt):
    import asyncio

    from jarvis.desktop import media

    calls = {"n": 0}

    async def snap():
        calls["n"] += 1
        if calls["n"] == 1:
            return {"title": "Old Song", "artist": "A", "playing": True}
        raise asyncio.TimeoutError("neodpovídá: X")

    published = []
    monkeypatch.setattr(media, "_snapshot", snap)
    monkeypatch.setitem(__import__("sys").modules, "winsdk", __import__("types").ModuleType("winsdk"))
    rt.bus.publish = lambda t, **kw: published.append((t, kw))

    async def run():
        task = asyncio.ensure_future(media.watch(rt, interval=0.01))
        await asyncio.sleep(0.5)
        task.cancel()

    asyncio.run(run())
    medias = [kw for t, kw in published if t == "media"]
    assert medias[0].get("title") == "Old Song" and medias[-1] == {}            # cleared, not stuck on the old song
