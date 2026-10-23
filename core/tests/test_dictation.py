"""3.0 dictation anywhere: words, snippets, clean-up, paste, history, statistics, the key and the weekly recap."""
import asyncio
import time
from datetime import date, datetime, timedelta

from conftest import FakeRouter, drain

from jarvis import config
from jarvis.desktop.dictation_keys import HOLD_S, DictationKeys
from jarvis.dictation import apply_words, count_words, recap, week_bounds


def cfg(**kw):
    return config.Config.model_validate({"dictation": kw}).dictation


class FakeSTT:
    def __init__(self, text):
        self.text = text
        self.prompts = []

    def transcribe(self, pcm, sr=16000, prompt=""):
        self.prompts.append(prompt)
        return self.text


def test_replacements_whole_words_any_case():
    c = cfg(replacements=[{"src": "jarvis", "dst": "JARVIS"}, {"src": "gitub", "dst": "GitHub"}])
    assert apply_words("jarvisi, otevři Gitub a jarvis", c) == "jarvisi, otevři GitHub a JARVIS"


def test_snippet_replaces_whole_dictation():
    c = cfg(snippets=[{"trigger": "můj podpis", "text": "S pozdravem\nAdam"}])
    assert apply_words("Můj podpis.", c) == "S pozdravem\nAdam"
    assert apply_words("tady je můj podpis", c) == "tady je můj podpis"


def test_count_words_czech():
    assert count_words("Ahoj, jak se máš? Řekni mi to.") == 7


async def test_dictation_pastes_and_restores_clipboard(rt):
    rt.cfg = config.apply_patch(rt.cfg, {"dictation": {"words": ["Bartók", "OmniRoute"]}})
    stt = FakeSTT("zavolej panu Bartókovi")
    rt.dictation._own_stt = stt
    rt.platform.clipboard = "původní"
    rt.platform.front_app = "Discord"
    out = await rt.dictation.handle_audio(b"\0" * 32000, 2.0, "Discord")
    assert out == "zavolej panu Bartókovi"
    assert stt.prompts == ["Bartók, OmniRoute"]
    calls = [c for c in rt.platform.calls if c[0] in ("clipboard_set", "hotkey")]
    assert calls[0] == ("clipboard_set", "zavolej panu Bartókovi") and ("hotkey", ("ctrl", "v")) in calls
    assert rt.platform.clipboard == "původní"
    h = rt.dictation.history()
    assert h[0]["text"] == "zavolej panu Bartókovi" and h[0]["app"] == "Discord" and h[0]["words"] == 3


async def test_cleanup_uses_fast_ai_and_keeps_snippets(rt):
    rt.cfg = config.apply_patch(rt.cfg, {"dictation": {"cleanup": "natural",
                                                       "snippets": [{"trigger": "adresa", "text": "Dlouhá 1, Praha"}]}})
    rt.router = FakeRouter(["Pošli mi to zítra, prosím."])
    rt.dictation._own_stt = FakeSTT("ehm pošli mi to jakoby zítra prosím")
    assert await rt.dictation.handle_audio(b"\0" * 32000, 2.0) == "Pošli mi to zítra, prosím."
    rt.dictation._own_stt = FakeSTT("Adresa")
    assert await rt.dictation.handle_audio(b"\0" * 32000, 1.0) == "Dlouhá 1, Praha"
    assert len(rt.router.calls) == 1   # the snippet did not go to the AI


async def test_cleanup_failure_keeps_raw_text(rt):
    rt.cfg = config.apply_patch(rt.cfg, {"dictation": {"cleanup": "polished"}})
    rt.router = FakeRouter([RuntimeError("offline")])
    rt.dictation._own_stt = FakeSTT("tohle je text bez úprav")
    assert await rt.dictation.handle_audio(b"\0" * 32000, 2.0) == "tohle je text bez úprav"


async def test_nothing_heard_pastes_nothing(rt):
    rt.dictation._own_stt = FakeSTT("  ")
    q = rt.bus.subscribe()
    assert await rt.dictation.handle_audio(b"\0" * 3200, 1.0) == ""
    assert not any(c[0] == "hotkey" for c in rt.platform.calls)
    assert rt.dictation.state == "idle"


def test_stats_and_streak(rt):
    d = rt.dictation
    now = time.time()
    for i, (words, app) in enumerate([(30, "Chrome"), (10, "Discord"), (60, "Chrome")]):
        rt.db.exec("INSERT INTO dictations (ts, text, raw, words, seconds, app, style) VALUES (?,?,?,?,?,?,?)",
                   (now - i * 86400, "x", "x", words, 20, app, "off"))
    s = d.stats("week")
    assert s["words"] == 100 and s["dictations"] == 3 and s["streak"] == 3
    assert s["wpm"] == 100 and s["saved_s"] == 100 / 40 * 60 - 60
    assert s["apps"][0] == {"app": "Chrome", "words": 90, "share": 90}
    assert len(s["series"]) == 7 and s["series"][-1]["words"] == 30


def test_keep_days_zero_keeps_no_words(rt):
    rt.cfg = config.apply_patch(rt.cfg, {"dictation": {"keep_days": 0}})
    rt.dictation.add("tajný text", "tajný text", 2.0, "Word")
    assert rt.dictation.history() == []
    assert rt.dictation.stats("all")["words"] == 2


def test_delete_and_clear(rt):
    rt.dictation.add("jedna dva", "jedna dva", 1.0)
    rt.dictation.add("tři", "tři", 1.0)
    rt.dictation.delete(rt.dictation.history()[0]["id"])
    assert [h["text"] for h in rt.dictation.history()] == ["jedna dva"]
    rt.dictation.clear()
    assert rt.dictation.history() == [] and rt.dictation.stats("all")["words"] == 3


def test_history_search_ignores_diacritics(rt):
    rt.dictation.add("Napiš Žanetě", "x", 1.0)
    rt.dictation.add("něco jiného", "x", 1.0)
    assert [h["text"] for h in rt.dictation.history("zanete")] == ["Napiš Žanetě"]


# ---------- the key ----------
class FakeDictation:
    def __init__(self):
        self.state, self.hands_free, self.log = "idle", False, []

    def start(self, hands_free=False):
        self.state, self.hands_free = "listening", hands_free
        self.log.append(("start", hands_free))
        return True

    def finish(self):
        self.state = "idle"
        self.log.append("finish")

    def cancel(self):
        self.state = "idle"
        self.log.append("cancel")


def keys(rt):
    clock = [0.0]
    timers = []
    rt.dictation = FakeDictation()
    k = DictationKeys(rt, clock=lambda: clock[0], later=lambda d, fn: timers.append((clock[0] + d, fn)))

    def advance(dt):
        clock[0] += dt
        for t in [t for t in timers if t[0] <= clock[0]]:
            timers.remove(t)
            t[1]()
    return k, advance, rt.dictation


def test_hold_dictates(rt):
    k, adv, d = keys(rt)
    k.on_event("right ctrl", "down")
    adv(HOLD_S + 0.01)
    assert d.log == [("start", False)]
    adv(2)
    k.on_event("right ctrl", "up")
    assert d.log[-1] == "finish"


def test_combo_with_other_key_never_records(rt):
    k, adv, d = keys(rt)
    k.on_event("right ctrl", "down")
    adv(0.05)
    k.on_event("c", "down")
    adv(0.5)
    k.on_event("right ctrl", "up")
    assert d.log == []


def test_other_key_while_listening_cancels(rt):
    k, adv, d = keys(rt)
    k.on_event("right ctrl", "down")
    adv(0.3)
    k.on_event("v", "down")
    assert d.log == [("start", False), "cancel"]


def test_double_tap_hands_free_then_tap_to_paste(rt):
    k, adv, d = keys(rt)
    for _ in range(2):
        k.on_event("right ctrl", "down")
        adv(0.1)
        k.on_event("right ctrl", "up")
        adv(0.1)
    assert d.log == [("start", True)]
    adv(5)
    k.on_event("right ctrl", "down")
    k.on_event("right ctrl", "up")
    assert d.log[-1] == "finish"


def test_esc_cancels_and_disabled_does_nothing(rt):
    k, adv, d = keys(rt)
    k.on_event("right ctrl", "down")
    adv(0.3)
    k.on_event("esc", "down")
    assert d.log[-1] == "cancel"
    rt.cfg = config.apply_patch(rt.cfg, {"dictation": {"enabled": False}})
    k.on_event("right ctrl", "up")
    k.on_event("right ctrl", "down")
    adv(1)
    assert d.log == [("start", False), "cancel"]


def test_custom_key(rt):
    rt.cfg = config.apply_patch(rt.cfg, {"dictation": {"key": "f8"}})
    k, adv, d = keys(rt)
    k.on_event("right ctrl", "down")
    adv(1)
    assert d.log == []
    k.on_event("f8", "down")
    adv(1)
    assert d.log == [("start", False)]


# ---------- weekly recap ----------
def test_recap_counts_last_week(rt):
    start, _ = week_bounds(date(2026, 10, 26))       # a Monday
    assert start == date(2026, 10, 19)
    wed = datetime(2026, 10, 21, 10).timestamp()
    rt.db.exec("INSERT INTO dictations (ts, text, raw, words, seconds, app, style) VALUES (?,?,?,?,?,?,?)",
               (wed, "x", "x", 120, 60, "Chrome", "off"))
    rt.db.exec("INSERT INTO tasks VALUES ('t1','c','pusť hudbu','done',?,?, '')", (wed, wed + 30))
    rt.db.exec("INSERT INTO tasks VALUES ('t2','c','najdi','failed',?,?, '')", (wed - 86400 * 9, wed))  # week before
    r = recap(rt, date(2026, 10, 26))
    assert r["words"] == 120 and r["tasks"] == 1 and r["tasks_done"] == 1
    assert r["busiest_day"] == "středa" and r["top_app"] == "Chrome" and not r["empty"]


def test_recap_due_until_seen(rt, monkeypatch):
    rt.dictation.add("ahoj světe", "ahoj světe", 1.0)
    from jarvis import dictation

    monkeypatch.setattr(dictation, "week_bounds", lambda today=None: (date.today() - timedelta(days=3), date.today() + timedelta(days=4)))
    assert rt.recap_due()
    rt.recap_seen()
    assert not rt.recap_due()
