"""Wave 32: the character reacts to the world (OMEGA 72–74, 81, 242, 736–750)."""
import random

from fastapi.testclient import TestClient

from jarvis.config import CustomReaction
from jarvis.mood import MoodEngine, clean_look, part_of_day, weather_kind
from jarvis.server.app import create_app

LOCAL = ("127.0.0.1", 5000)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Wall:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def engine(rt, seed=1):
    c = Clock()
    m = MoodEngine(rt, clock=c, rng=random.Random(seed))
    m.wall = Wall()
    return m, c


def test_stretch_after_the_pc_slept(rt):
    m, c = engine(rt)
    m.tick()
    assert "reaction" not in m.current
    m.wall.t += 1.0
    c.t += 1.0
    m.tick()
    assert "reaction" not in m.current
    m.wall.t += 3 * 3600          # suspended: the wall clock jumped, the monotonic one did not
    c.t += 1.0
    m.tick()
    r = m.current["reaction"]
    assert r["name"] == "stretch" and r["detail"]["slept_s"] >= 3 * 3600
    c.t += 3.1
    assert "reaction" not in m.current


def test_volume_and_mute(rt):
    m, c = engine(rt)
    m.on_audio(40, False)                 # baseline only
    assert "reaction" not in m.current
    m.on_audio(41, False)                 # tiny jitter is ignored
    assert "reaction" not in m.current
    m.on_audio(60, False)
    r = m.current["reaction"]
    assert r["name"] == "volume" and r["detail"] == {"level": 60, "up": True}
    m.on_audio(60, True)
    assert m.current["reaction"]["name"] == "mute"
    m.on_audio(60, False)
    r2 = m.current["reaction"]
    assert r2["name"] == "unmute" and r2["id"] > r["id"]


def test_no_audio_device_never_reacts(rt):
    m, _ = engine(rt)
    m.on_audio(None, None)
    m.on_audio(None, None)
    assert "reaction" not in m.current


def test_hardware_plug_and_unplug(rt):
    m, _ = engine(rt)
    m.on_event({"type": "guardian", "key": "hardware", "text": "Připojeno: USB disk"})
    assert m.current["reaction"]["name"] == "plug"
    m.on_event({"type": "guardian", "key": "hardware", "text": "Odpojeno: USB disk"})
    assert m.current["reaction"]["name"] == "unplug"
    m.on_event({"type": "guardian", "key": "cpu", "text": "Připojeno"})       # other guardian keys do nothing
    assert m.current["reaction"]["name"] == "unplug"


def test_switching_ai_provider(rt):
    m, _ = engine(rt)
    m.on_event({"type": "brain", "provider": "groq", "model": "a"})
    assert "reaction" not in m.current            # the first answer only sets the baseline
    m.on_event({"type": "brain", "provider": "groq", "model": "a"})
    assert "reaction" not in m.current
    m.on_event({"type": "brain", "provider": "ollama", "model": "b"})
    r = m.current["reaction"]
    assert r["name"] == "switch" and r["detail"]["from"] == "groq" and r["detail"]["to"] == "ollama"


def test_copying_files(rt):
    m, _ = engine(rt)
    m.on_event({"type": "tool_start", "name": "open_app"})
    assert "reaction" not in m.current
    m.on_event({"type": "tool_start", "name": "copy_file"})
    assert m.current["reaction"]["name"] == "copy"


def test_easter_eggs(rt):
    m, _ = engine(rt)
    for text, kind in [("udělej barrel roll", "spin"), ("Jaký je smysl života?", "42"), ("mrkni na mě", "wink"),
                       ("žongluj", "juggle")]:
        m.on_event({"type": "user_message", "text": text})
        assert m.current["reaction"]["detail"]["kind"] == kind, text
    before = m.current["reaction"]["id"]
    m.on_event({"type": "user_message", "text": "jaké je počasí"})
    assert m.current["reaction"]["id"] == before


def test_toy_when_alone_depends_on_personality(rt):
    rt.cfg.character.personality = "hravý"
    m, c = engine(rt, seed=3)
    m.last_toy = -1e9
    c.t += 200                        # idle for over 3 minutes, still awake
    m.last_activity = c.t - 200
    seen = None
    for _ in range(2000):
        c.t += 1
        m.last_activity = c.t - 200
        m.tick()
        r = m.current.get("reaction")
        if r and r["name"] == "toy":
            seen = r
            break
    assert seen and seen["detail"]["toy"] in ("ball", "yoyo", "plane", "bubble")
    # at most one toy per 15 minutes
    first = m.last_toy
    for _ in range(600):
        c.t += 1
        m.last_activity = c.t - 200
        m.tick()
    assert m.last_toy == first

    rt.cfg.character.personality = "profesionální"
    m2, c2 = engine(rt, seed=3)
    m2.last_toy = -1e9
    for _ in range(3000):
        c2.t += 1
        m2.last_activity = c2.t - 200
        m2.tick()
        assert (m2.current.get("reaction") or {}).get("name") != "toy"


def test_no_toy_while_busy_or_asleep(rt):
    rt.cfg.character.personality = "hravý"
    m, c = engine(rt, seed=3)
    m.last_toy = -1e9
    m.on_event({"type": "state", "state": "thinking"})
    for _ in range(1500):
        c.t += 1
        m.last_activity = c.t - 200
        m.tick()
    assert (m.current.get("reaction") or {}).get("name") != "toy"
    m.on_event({"type": "state", "state": "idle"})
    for _ in range(1500):
        c.t += 1
        m.last_activity = c.t - 5000      # asleep
        m.tick()
    assert m.last_toy == -1e9


def test_custom_reactions(rt):
    rt.cfg.character.reactions = [
        CustomReaction(name="Šéf", when="notify", match="Petr, faktura",
                       look={"eyes": "wide", "icon": "bell<script>", "motion": "spin", "color": "#ff0000", "seconds": 99}),
        CustomReaction(name="Vypnutá", when="message", match="", enabled=False),
        CustomReaction(name="Pošta", when="mail", match=""),
    ]
    m, _ = engine(rt)
    m.on_event({"type": "notify", "title": "Teams", "body": "Ahoj"})
    assert "reaction" not in m.current
    m.on_event({"type": "notify", "title": "Teams", "body": "Petr: posílám fakturu"})   # "Petr" matches
    r = m.current["reaction"]
    assert r["name"] == "custom" and r["detail"]["name"] == "Šéf"
    assert r["detail"]["icon"] == "bellscript" and r["detail"]["seconds"] == 15 and r["detail"]["motion"] == "spin"
    rid = r["id"]
    m.on_event({"type": "user_message", "text": "ahoj"})              # disabled reaction
    assert m.current["reaction"]["id"] == rid
    m.on_event({"type": "mail_new", "from_name": "Eva", "subject": "Oběd"})
    assert m.current["reaction"]["detail"]["name"] == "Pošta"


def test_clean_look():
    assert clean_look({"eyes": "x\"><img", "icon": "../evil", "motion": "fly", "color": "red;}", "seconds": "abc"}) == {
        "eyes": "ximg", "icon": "evil", "motion": "hop", "color": "", "seconds": 3.0}
    assert clean_look(None)["icon"] == "star"
    assert clean_look({"seconds": 0, "color": "#abc"})["color"] == "#abc"
    assert clean_look({"seconds": 0.1})["seconds"] == 0.5


def test_secondary_feeling(rt):
    m, c = engine(rt)
    m.on_event({"type": "assistant_done", "tools": [{"ok": True, "summary": "x"}]})
    assert m.current["mood"] == "success"
    m.on_event({"type": "state", "state": "thinking"})
    cur = m.current
    assert cur["mood"] == "thinking" and cur["secondary"] == "success"
    m.on_event({"type": "state", "state": "idle"})
    c.t += 5
    assert m.current["secondary"] is None


def test_ambient_part_of_day_and_weather(rt):
    assert [part_of_day(h) for h in (23, 3, 7, 12, 19)] == ["night", "night", "morning", "day", "evening"]
    assert [weather_kind(c) for c in (None, 0, 2, 45, 61, 81, 73, 95)] == [None, "sun", "cloud", "fog", "rain", "rain", "snow", "storm"]
    m, _ = engine(rt)
    m.weather = {"code": 63, "temp": 8.5}
    amb = m.current["ambient"]
    assert amb["weather"] == "rain" and amb["temp"] == 8.5 and amb["part"] in ("night", "morning", "day", "evening")


def test_preview_from_settings(rt):
    with TestClient(create_app(rt, manage_runtime=False), client=LOCAL) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "mood_set", "react": "custom", "look": {"icon": "heart", "motion": "dance", "seconds": 2}})
        for _ in range(80):
            m = ws.receive_json()
            if m.get("type") == "mood" and m.get("reaction"):
                assert m["reaction"]["name"] == "custom" and m["reaction"]["detail"]["icon"] == "heart"
                break
        else:
            raise AssertionError("no reaction")
