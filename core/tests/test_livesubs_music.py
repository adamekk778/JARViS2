"""A song from a music app is not turned into subtitles (the recogniser turns songs into nonsense)."""
import queue
import threading
from types import SimpleNamespace

from jarvis import livesubs
from jarvis.devicelisten import DeviceListen


class _STT:
    def __init__(self):
        self.calls = 0

    def caption(self, piece):
        self.calls += 1
        return "some heard words", "en"


def _rt(source, playing=True):
    bus = SimpleNamespace(publish_threadsafe=lambda *a, **k: None)
    cfg = SimpleNamespace(notch=SimpleNamespace(subs_translate=False))
    return SimpleNamespace(media_state={"playing": playing, "source": source, "title": "Reflections"}, bus=bus, cfg=cfg)


def _run(subs, stt):
    subs._jobs = queue.Queue()
    subs._jobs.put(b"x")
    subs._stop = threading.Event()
    t = threading.Thread(target=subs._recognise, args=(stt,))
    t.start()
    for _ in range(50):
        if subs._jobs.empty():
            break
        threading.Event().wait(0.02)
    threading.Event().wait(0.05)
    subs._stop.set()
    t.join(2)


def test_spotify_song_is_not_transcribed():
    subs = livesubs.LiveSubs(_rt("spotify"))
    subs.text = "old nonsense"
    stt = _STT()
    _run(subs, stt)
    assert stt.calls == 0 and subs.text == ""


def test_video_is_still_transcribed():
    subs = livesubs.LiveSubs(_rt("youtube"))
    stt = _STT()
    _run(subs, stt)
    assert stt.calls == 1 and subs.text == "some heard words"


def test_paused_music_does_not_block_subtitles():
    subs = livesubs.LiveSubs(_rt("spotify", playing=False))
    stt = _STT()
    _run(subs, stt)
    assert stt.calls == 1


def test_device_listening_keeps_everything():
    assert DeviceListen.SKIP_MUSIC is False and livesubs.LiveSubs.SKIP_MUSIC is True
