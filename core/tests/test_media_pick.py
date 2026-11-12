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
