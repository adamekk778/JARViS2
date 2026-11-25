"""3.14 Osobnost a hlas (13–16): JARVIS and FRIDAY, humour that knows when, running jokes, who is speaking.

- "přepni na FRIDAY" / "přepni na JARVISe": the personality AND its voice change together
  (JARVIS: a calm male voice, British in English, with the film-like "jarvis" sound; FRIDAY: a quicker female voice,
  Irish in English). Original voices from the speech service – not a copy of any actor.
- humour: a dry joke only when it fits – never on a sad or serious topic, in focus / a meeting, or late at night;
  when you laugh at something, JARVIS remembers it and may come back to it once in a while (a running joke)
- someone the voice prints do not know is speaking → treated like a guest for that sentence
"""
from __future__ import annotations

import json
import random
import re
import time
from typing import Any

VOICES: dict[str, dict] = {
    "jarvis": {"tts_engine": "edge", "tts_voice": "cs-CZ-AntoninNeural", "tts_voice_en": "en-GB-RyanNeural",
               "tts_rate": "+4%", "tts_pitch": "-2Hz", "effect": "jarvis"},
    "friday": {"tts_engine": "edge", "tts_voice": "cs-CZ-VlastaNeural", "tts_voice_en": "en-IE-EmilyNeural",
               "tts_rate": "+8%", "tts_pitch": "+0Hz", "effect": "jarvis"},
}
NAMES = {"jarvis": "JARVIS", "friday": "FRIDAY"}
SAY = {"friday": re.compile(r"\bfr[ae]j?d[ae]j\w*|\bfriday\w*", re.I), "jarvis": re.compile(r"\bd?ž?jarvis\w*|\bdžarvis\w*", re.I)}
SERIOUS = re.compile(r"\b(umřel|zemřel|smrt|pohřeb|nemoc|rakovin|nemocnic|úraz|nehod|rozchod|rozvod|deprese|smutn|bolí|"
                     r"pláč|dluh|exekuc|výpověď|propustili|krize|pomoc|sebevra|zneužit|násilí)", re.I)
LAUGH = re.compile(r"(\bhaha+\b|\bhehe+\b|\bxd\b|😂|🤣|😄|😆|\blol\b|to je dobr[ýé]|vtipn[ýé]|dobrej vtip|pobavil)", re.I)
KV = "running_jokes"
MAX_JOKES = 20


def switch(rt: Any, name: str, voice: bool = True) -> dict:
    name = (name or "").strip().lower()
    if name not in VOICES:
        raise ValueError("Umím přepnout na JARVISe nebo FRIDAY.")
    patch: dict = {"general": {"personality": name}}
    if voice:
        patch["voice"] = dict(VOICES[name])
    rt.update_config(patch)
    return {"persona": name, "name": NAMES[name], "voice": patch.get("voice", {})}


def from_words(text: str) -> str:
    for name, rx in SAY.items():
        if rx.search(text or ""):
            return name
    return ""


# ---------- humour ----------
def humour_line(rt: Any, text: str, now: float | None = None) -> str:
    """One line for the system prompt: may JARVIS joke now – and maybe a running joke to come back to."""
    hour = time.localtime(now or time.time()).tm_hour
    att = getattr(rt, "attention", None)
    try:
        busy = bool(att and att.busy_reason())
    except Exception:  # noqa: BLE001
        busy = False
    if SERIOUS.search(text or "") or busy or hour >= 23 or hour < 6:
        return "Teď žádné vtipy – téma nebo chvíle na to není (vážně, klidně, věcně)."
    if getattr(rt.cfg.general, "personality", "jarvis") == "brief":
        return ""
    line = "Jemný suchý vtip si dovolit můžeš, jen když sedí – nejvýš jeden, nikdy na úkor uživatele."
    jokes = _jokes(rt)
    if jokes and random.random() < 0.12:
        j = random.choice(jokes)
        if time.time() - float(j.get("used", 0)) > 86400 * 3:
            j["used"] = time.time()
            _save(rt, jokes)
            line += f" Můžeš (jen pokud to přirozeně sedí) lehce odkázat na váš starší vtip: „{j['text']}“."
    return line


def _jokes(rt: Any) -> list[dict]:
    try:
        rt.db.conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
        r = rt.db.one("SELECT v FROM kv WHERE k=?", (KV,))
        data = json.loads(r["v"]) if r else []
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def _save(rt: Any, jokes: list[dict]) -> None:
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?, ?)", (KV, json.dumps(jokes[-MAX_JOKES:], ensure_ascii=False)))


def note_reaction(rt: Any, user_text: str, last_answer: str) -> bool:
    """You laughed at JARVIS's last answer → its witty sentence becomes a running joke."""
    if not last_answer or not LAUGH.search(user_text or "") or getattr(getattr(rt, "memory", None), "private", False):
        return False
    sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", last_answer) if 8 <= len(x.strip()) <= 160]
    if not sents:
        return False
    line = sents[-1] if len(sents) > 1 else sents[0]
    jokes = [j for j in _jokes(rt) if j.get("text") != line]
    jokes.append({"text": line, "at": time.time(), "used": time.time()})
    _save(rt, jokes)
    return True


# ---------- 16: who is speaking ----------
def speaker_line(rt: Any) -> str:
    """Somebody the voice prints do not know said this (while prints exist) → a guest for this sentence."""
    vid = getattr(rt, "voiceid", None)
    if vid is None or not getattr(vid.profiles, "people", None):
        return ""
    if time.time() - getattr(vid, "last_at", 0) > 30 or vid.last_speaker:
        return ""
    from . import shield

    return "Tuhle větu řekl někdo, koho po hlase neznáš (host). " + shield.GUEST_RULE
