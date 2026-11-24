"""3.14 texts from a second source, and the timing fitted to the singing by listening."""
import httpx
import numpy as np

from jarvis import lyricsync, nowplaying


def synth(line_times, delay, start=10.0, length=25.0, sr=16000, seed=1):
    """A 'song': quiet noise, and a burst of voice-band tone where each line is really sung (line time + delay)."""
    rng = np.random.default_rng(seed)
    n = int(sr * length)
    x = rng.normal(0, 0.01, n).astype("float32")
    t = np.arange(n) / sr
    for lt in line_times:
        at = lt + delay - start
        if 0 <= at < length - 1.2:
            i, j = int(at * sr), int((at + 1.2) * sr)
            x[i:j] += 0.4 * np.sin(2 * np.pi * 800 * t[i:j]) * np.hanning(j - i).astype("float32") ** 0.2
    return x


LINES = [11.0, 13.6, 16.1, 18.9, 21.2, 23.8, 26.5, 29.0, 31.7]


def test_shift_is_found_from_the_singing():
    for delay in (0.8, -0.6, 1.5):
        res = lyricsync.estimate_shift(lyricsync.onset_strength(synth(LINES, delay)), 10.0, LINES)
        assert res["shift"] is not None, res
        assert abs(res["delay"] - delay) <= 0.1 and abs(res["shift"] - (-delay + lyricsync.LEAD_S)) <= 0.11


def test_no_guess_without_singing():
    noise = np.random.default_rng(3).normal(0, 0.01, 16000 * 25).astype("float32")
    assert lyricsync.estimate_shift(lyricsync.onset_strength(noise), 10.0, LINES)["shift"] is None
    few = lyricsync.estimate_shift(lyricsync.onset_strength(synth(LINES[:2], 0.5)), 10.0, LINES[:2])
    assert few["shift"] is None                                     # 2 lines are not enough to be sure


def test_autosync_runs_once_per_song_only_on_windows(rt, monkeypatch):
    import sys

    a = lyricsync.of(rt)
    rt.lyrics_state = {"title": "Song", "artist": "Band", "synced": True, "lines": [{"t": t, "text": "x"} for t in LINES]}
    rt.media_state = {"title": "Song", "artist": "Band", "playing": True, "position": 5.0}
    monkeypatch.setattr(sys, "platform", "linux")
    assert not a.maybe_start()                                       # no loopback off Windows
    monkeypatch.setattr(sys, "platform", "win32")
    started = []
    monkeypatch.setattr(lyricsync.AutoSync, "_run", lambda self, key, times: started.append(key))
    assert a.maybe_start() and started == [("Song", "Band")]
    assert not a.maybe_start()                                       # once per song
    rt.cfg.notch.lyrics_autosync = False
    a.done.clear()
    assert not a.maybe_start()


async def test_second_source_when_lrclib_has_nothing():
    asked = []

    def handler(req: httpx.Request):
        asked.append(req.url.host)
        if req.url.host == "lrclib.net":
            return httpx.Response(404, json={}) if req.url.path.endswith("/get") else httpx.Response(200, json=[])
        assert req.url.path == "/v1/Kabát/Pohoda"
        return httpx.Response(200, json={"lyrics": "Paroles de la chanson Pohoda par Kabát\r\nMáme se dobře, je tu pohoda\r\na nikdo nic nechce"})

    lib = nowplaying.Lyrics(transport=httpx.MockTransport(handler))
    r = await lib.get("Pohoda", "Kabát", "", 200)
    assert not r["synced"] and r["plain"].startswith("Máme se dobře") and r["src_id"].startswith("ovh:")
    assert "api.lyrics.ovh" in asked
    r2 = await nowplaying.Lyrics(transport=httpx.MockTransport(handler)).get("Pohoda", "Kabát", "", 200, skip=(r["src_id"],))
    assert r2["plain"] == ""                                         # "Jiný text" on it: not shown again


async def test_what_is_playing(rt):
    import time as _t

    from jarvis import tools

    tools.load_builtin()

    def handler(req: httpx.Request):
        if req.url.host == "itunes.apple.com":
            return httpx.Response(200, json={"results": [
                {"trackName": "Stay", "artistName": "Rihanna", "collectionName": "Unapologetic", "releaseDate": "2012-01-01", "primaryGenreName": "Pop"},
                {"trackName": "Stay", "artistName": "The Kid LAROI & Justin Bieber", "collectionName": "F*CK LOVE 3", "releaseDate": "2021-07-09T07:00:00Z",
                 "primaryGenreName": "Pop"}]})
        if req.url.host == "cs.wikipedia.org":
            return httpx.Response(200, json={"type": "standard", "description": "australský rapper a zpěvák",
                                             "extract": "The Kid LAROI je australský rapper a zpěvák. Proslavil se v roce 2020. Třetí věta."})
        return httpx.Response(404)

    rt.transport = httpx.MockTransport(handler)
    rt.media_state = {"title": "Stay", "artist": "The Kid LAROI, Justin Bieber", "playing": True, "position": 60.0, "at": _t.time(),
                      "duration": 141.0}
    r = await tools.call("now_playing_info", {}, rt)
    assert r.ok and "„Stay“ od The Kid LAROI" in r.summary and "F*CK LOVE 3" in r.summary and "2021" in r.summary
    assert "Rihanna" not in r.summary and "australský rapper" in r.summary and "Třetí věta" not in r.summary
    assert "Jsme v 1:00 z 2:21" in r.summary
    rt.media_state = {}
    r = await tools.call("now_playing_info", {}, rt)
    assert not r.ok and "nic nehraje" in r.summary


async def test_wrong_wikipedia_person_is_not_used(rt):
    from jarvis import tools

    tools.load_builtin()

    def handler(req: httpx.Request):
        if req.url.host.endswith("wikipedia.org"):
            return httpx.Response(200, json={"type": "standard", "description": "řeka v Evropě", "extract": "Morava je řeka."})
        return httpx.Response(200, json={"results": []})

    rt.transport = httpx.MockTransport(handler)
    rt.media_state = {"title": "Song", "artist": "Morava", "playing": True}
    r = await tools.call("now_playing_info", {}, rt)
    assert r.ok and "řeka" not in r.summary


async def test_karaoke_opens_the_window(rt):
    from jarvis import instant, tools

    tools.load_builtin()
    opened = []
    rt.ui_hook = opened.append
    r = await tools.call("karaoke_open", {}, rt)
    assert r.ok and opened == ["karaoke"]
    assert instant.plan("pusť karaoke").calls == [("karaoke_open", {})]
    assert instant.plan("co to hraje").calls == [("now_playing_info", {})]
