"""3.12 Zvuk z PC do telefonu: the PC's own sound → an AAC stream any phone player can play; only the paired phone."""
import asyncio
import io

import numpy as np
import pytest

from jarvis import pcaudio

av = pytest.importorskip("av")


class FakeLoopback:
    """A 440 Hz tone, like the PC playing music (and nothing at all after a while, like a pause)."""

    def __init__(self):
        self.t = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def record(self, numframes):
        n = np.arange(self.t, self.t + numframes) / pcaudio.SR
        self.t += numframes
        import time
        time.sleep(numframes / pcaudio.SR)
        tone = (0.3 * np.sin(2 * np.pi * 440 * n)).astype(np.float32)
        return np.stack([tone, tone], axis=1)


def collect(p: pcaudio.PcAudio, seconds: float) -> bytes:
    async def main():
        got = bytearray()
        gen = p.listen()

        async def read():
            async for chunk in gen:
                got.extend(chunk)

        task = asyncio.create_task(read())
        await asyncio.sleep(seconds)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await gen.aclose()
        p.stop()
        await asyncio.sleep(0.3)
        return bytes(got)

    return asyncio.run(main())


def test_the_stream_is_playable_aac(rt):
    notes = []
    rt.bus.publish = lambda kind, **d: notes.append((kind, d.get("title")))
    p = pcaudio.PcAudio(rt, source=FakeLoopback)
    data = collect(p, 1.5)
    assert data[:2] == b"\xff\xf1" or (data[0] == 0xFF and data[1] & 0xF0 == 0xF0)      # ADTS frames
    frames = list(av.open(io.BytesIO(data), format="adts").decode(audio=0))
    assert sum(f.samples for f in frames) > pcaudio.SR * 0.5                             # most of the time came through
    assert frames[0].layout.name == "stereo" and frames[0].sample_rate == pcaudio.SR
    loud = np.abs(np.concatenate([f.to_ndarray()[0] for f in frames[5:]])).max()
    assert 0.15 < loud < 0.5                                                            # the tone, not silence or noise
    assert ("notify", "Zvuk z PC jde do telefonu") in notes                             # the PC says it is on


def test_silence_keeps_the_stream_going_and_a_broken_capture_ends_it(rt):
    class Quiet(FakeLoopback):
        def record(self, numframes):
            import time
            time.sleep(10)                                                              # nothing plays: loopback blocks
            return super().record(numframes)

    rt.bus.publish = lambda *a, **k: None
    quiet = collect(pcaudio.PcAudio(rt, source=Quiet), 1.2)
    frames = list(av.open(io.BytesIO(quiet), format="adts").decode(audio=0))
    assert sum(f.samples for f in frames) > pcaudio.SR * 0.6                            # silence still flows (no stall)

    class Broken(FakeLoopback):
        def __enter__(self):
            raise OSError("no speaker")

    p = pcaudio.PcAudio(rt, source=Broken)
    collect(p, 1.0)
    assert "nejde zachytit" in p.error


def test_only_the_paired_phone_listens(rt):
    from starlette.testclient import TestClient

    from jarvis.server.app import create_app

    c = TestClient(create_app(rt, manage_runtime=False), client=("100.70.1.2", 5000))
    assert c.get("/api/phone/audio").status_code == 401
