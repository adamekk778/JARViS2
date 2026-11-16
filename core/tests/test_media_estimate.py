"""A player without a timeline: JARVIS counts the song's position itself, so the lyrics can still follow."""
import time

from jarvis.desktop import media


def test_position_is_counted_when_the_player_gives_none(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(time, "time", lambda: t[0])
    media._EST.clear()
    key = ("Spotify.exe", "NIGHTS LIKE THIS", "The Kid LAROI")
    assert media._estimate(key, True)["position"] == 0
    t[0] += 12
    assert media._estimate(key, True)["position"] == 12
    assert media._estimate(key, False)["position"] == 12          # paused
    t[0] += 30
    assert media._estimate(key, False)["position"] == 12          # stays while paused
    assert media._estimate(key, True)["position"] == 12
    t[0] += 3
    r = media._estimate(key, True)
    assert r["position"] == 15 and r["estimated"]
    assert media._estimate(("x", "Other", "y"), True)["position"] == 0   # a new song starts from zero


def test_no_timeline_object_falls_back_to_the_count():
    media._EST.clear()

    class Broken:
        def get_timeline_properties(self):
            raise RuntimeError("no timeline")

    r = media._timeline(Broken(), True, ("a", "b", "c"))
    assert "position" in r and r["estimated"]
