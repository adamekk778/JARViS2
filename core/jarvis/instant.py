"""3.13 Okamžité příkazy: the everyday commands are done the moment you finish the sentence – no AI in between, so it is
just as fast with Ollama on this PC as with Gemini, and works when the AI limit is out.

Only short, unmistakable commands are caught here ("hlasitost na 30", "další písnička", "otevři Spotify", "zavři
Discord", "kolik je hodin", "minutka na 5 minut", "nahraj zvuk, co teď pustím", "stop nahrávání"). Anything longer
or less clear goes to the AI as before. The steps go through the agent's normal path: what asks for confirmation still
asks (or not, with full trust), a running game is still never closed unless named, and the step is in the task log.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

MAX_WORDS = 9
POLITE = r"(?:jarvis\w*|prosim\w*|hned|ted|mi|nam|bys|by|muzes|muzete|ok|hej|hey|a)"


@dataclass
class Plan:
    calls: list[tuple[str, dict]]
    say: Callable[[list[dict]], str] | None = None      # the cards → what JARVIS says (default: the steps' own words)
    fallback: bool = False                               # a failed step → let the AI try instead of saying the failure
    kind: str = field(default="")


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w\s:%]", " ", t)
    words = [w for w in t.split() if not re.fullmatch(POLITE, w)]
    return " ".join(words)


def _num(s: str) -> int:
    words = {"jednu": 1, "jedna": 1, "jeden": 1, "dve": 2, "dva": 2, "tri": 3, "ctyri": 4, "pet": 5, "deset": 10, "patnact": 15,
             "dvacet": 20, "tricet": 30, "pul": 0}
    return int(s) if s.isdigit() else words.get(s, 0)


def _time(cards: list[dict]) -> str:
    m = re.search(r"(\d{1,2}):(\d{2})", cards[0]["summary"]) if cards else None
    return f"Je {int(m.group(1))}:{m.group(2)}." if m else (cards[0]["summary"] if cards else "")


def _date(cards: list[dict]) -> str:
    s = cards[0]["summary"] if cards else ""
    return f"Dnes je {s.rsplit(' ', 1)[0]}." if s else ""


def plan(text: str) -> Plan | None:
    """The command in these words, or None (then the AI answers)."""
    t = norm(text)
    if not t or len(t.split()) > MAX_WORDS:
        return None
    # ---- recording what the PC plays
    if re.fullmatch(r"(stop|konec|zastav|ukonci|prestan|vypni|dost)\w* (nahravani|nahravat|nahravku|nahravky)|(uz )?(staci|hotovo) nahravat"
                    r"|(stop|konec) nahravky", t):
        return Plan([("sound_record_stop", {})], kind="record")
    if re.search(r"\bnahr(aj|avej|ej|at)\b", t) and re.search(r"\b(zvuk\w*|to|co|pisnick\w*|hudb\w*|audio|song\w*|video|pust\w*|hraje)\b", t) \
            and not re.search(r"\b(obrazovk\w*|hovor\w*|schuzk\w*|mikrofon\w*|video na obrazovce)\b", t):
        return Plan([("sound_record_start", {})], kind="record")
    # ---- volume
    m = re.fullmatch(r"(?:dej |nastav |zmen )?(?:hlasitost|zvuk|volume)(?: na)? (\d{1,3})(?: %| procent\w*)?", t)
    if m:
        return Plan([("volume", {"action": "set", "level": max(0, min(100, int(m.group(1))))})], kind="volume")
    if re.fullmatch(r"(?:dej |udelej )?(?:hlasitejc?i|nahlas|zesil\w*|pridej\w*(?: zvuk| hlasitost)?|hlasitej\w*)", t):
        return Plan([("volume", {"action": "up"})], kind="volume")
    if re.fullmatch(r"(?:dej |udelej )?(?:tisejc?i|potichu|zeslab\w*|(?:uber|ubrat|ubir)\w*(?: zvuk| hlasitost)?|ztis\w*)", t):
        return Plan([("volume", {"action": "down"})], kind="volume")
    if re.fullmatch(r"(?:vypni zvuk|ztlum\w*(?: zvuk| to| vse| vsechno)?|mute)", t):
        return Plan([("volume", {"action": "mute"})], kind="volume")
    if re.fullmatch(r"(?:zapni zvuk|zrus ztlumeni|unmute)", t):
        return Plan([("volume", {"action": "unmute"})], kind="volume")
    # ---- music / video playing now
    if re.fullmatch(r"(?:dalsi|preskoc|next)(?: pisnick\w*| skladb\w*| song\w*| video)?", t):
        return Plan([("media_control", {"action": "next"})], say=lambda c: "Další.", kind="media")
    if re.fullmatch(r"(?:predchozi|predesl\w*|zpet)(?: pisnick\w*| skladb\w*| song\w*| video)?", t):
        return Plan([("media_control", {"action": "previous"})], say=lambda c: "Předchozí.", kind="media")
    if re.fullmatch(r"(?:pauza|pozastav\w*)(?: hudbu| pisnick\w*| video| to)?|zastav (?:hudbu|pisnick\w*|video)|(?:pust|pokracuj)(?: hudbu| to)?(?: dal)?", t):
        return Plan([("media_control", {"action": "play_pause"})], say=lambda c: "Hotovo.", kind="media")
    # ---- time, date
    if re.fullmatch(r"(?:kolik je hodin|kolik je|jaky je cas|cas)", t):
        return Plan([("get_time", {})], say=_time, kind="time")
    if re.fullmatch(r"(?:jaky je dnes den|jakeho je dnes|kolikateho je dnes|jaky je dnes datum|datum)", t):
        return Plan([("get_time", {})], say=_date, kind="time")
    # ---- timer
    m = re.fullmatch(r"(?:nastav |dej |zapni )?(?:minutk\w*|casovac\w*|odpocet|timer)(?: na)? (\w+) (sekund\w*|vterin\w*|minut\w*|min|hodin\w*)", t)
    if m and _num(m.group(1)):
        n = _num(m.group(1))
        sec = n * (3600 if m.group(2).startswith("hodin") else 1 if m.group(2).startswith(("sek", "vter")) else 60)
        return Plan([("set_timer", {"seconds": sec})], kind="timer")
    # ---- weather, screenshot
    if re.fullmatch(r"(?:jake je |jak je )?(?:venku )?pocasi(?: dnes| ted| venku)?|(?:bude prset|je venku zima|kolik je venku stupnu)", t):
        return Plan([("weather", {})], kind="weather")
    if re.fullmatch(r"(?:udelej |vyfot\w* |zachyt\w* )?(?:screenshot|snimek obrazovky|screen)", t):
        return Plan([("screenshot", {})], say=lambda c: "Hotovo, snímek je v chatu." if c and c[0]["ok"] else c[0]["summary"], kind="screenshot")
    # ---- 3.14 voice & personality
    full = " ".join(re.sub(r"[^\w\s:%]", " ", "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower())
                                                       if not unicodedata.combining(c))).split())
    if re.fullmatch(r"(?:prepni|prepnout|zmen|chci|vrat)\s+(?:se\s+)?(?:(?:na|zpatky|zpet)\s+)+(?:j|dz)arvis\w*", full):
        return Plan([("persona_switch", {"name": "jarvis"})], kind="voice")      # "Jarvis" is a polite word elsewhere
    m = re.fullmatch(r"(?:prepni|prepnout|zmen|chci)\s+(?:se\s+)?(?:na |zpatky |zpet )*(fr[ae]j?d[ae]j\w*|friday\w*|jarvis\w*|dzarvis\w*)", t)
    if m:
        return Plan([("persona_switch", {"name": "friday" if m.group(1).startswith("fr") else "jarvis"})], kind="voice")
    if re.fullmatch(r"(?:pojdme si |budeme si |chci si )?povid(?:at|ej|ejme)(?: si)?(?: se mnou)?|zivy rozhovor", t):
        return Plan([("live_conversation", {"on": True})], kind="voice")
    m = re.fullmatch(r"(?:tlumoc|prekladej)(?: me| muj hlas)?(?: do| v)? (anglictin\w*|nemcin\w*|slovenstin\w*|polstin\w*|francouzstin\w*|spanelstin\w*|italstin\w*|ukrajinstin\w*)", t)
    if m:
        code = {"ang": "en", "nem": "de", "slo": "sk", "pol": "pl", "fra": "fr", "spa": "es", "ita": "it", "ukr": "uk"}[m.group(1)[:3]]
        return Plan([("interpreter", {"on": True, "lang": code})], kind="voice")
    if re.fullmatch(r"(?:vypni|ukonci|zastav|konec)\s+(?:tlumoceni|prekladani)", t):
        return Plan([("interpreter", {"on": False})], kind="voice")
    # ---- 3.14 music: what is playing, karaoke
    if re.fullmatch(r"(?:co (?:to )?(?:ted )?hraje|co je to za (?:pisnick\w*|pisen|song|skladb\w*)|jaka je to pisnick\w*|kdo to zpiva|co to je za pisnick\w*)", t):
        return Plan([("now_playing_info", {})], kind="music")
    if re.fullmatch(r"(?:pust |zapni |otevri |spust )?karaoke", t):
        return Plan([("karaoke_open", {})], kind="music")
    # ---- 3.14 the brain: "přepni na Ollamu", "použij Claude Sonnet", "přepni model na qwen3:8b" – works even when
    # the AI answering now does not (that is when you want to switch)
    m = re.fullmatch(r"(?:prepni|prepnout|pouzij|pouzivej|zmen|vyber)\s+(?:(mozek|model|ai|umelou inteligenci)\s+)?(?:na |do )?(.{2,40})", t)
    if m:
        from . import brainpick

        target = m.group(2)
        brain = brainpick.preset_from_words(target)
        if brain:
            model = brainpick.claude_model_from_words(target) if brain == "anthropic" else ""
            if brain == "ollama":
                rest = re.sub(r"\b(ollam\w*|olam\w*|lokaln\w*|offline)\b", " ", target).split()
                model = rest[0] if rest and re.search(r"[:\d]", rest[0]) else ""
            return Plan([("brain_switch", {"brain": brain, **({"model": model} if model else {})})], kind="brain")
        if m.group(1) == "model" and re.fullmatch(r"[\w.:/-]{2,60}", target):
            return Plan([("brain_switch", {"model": target})], kind="brain")
    # ---- apps: open, close
    m = re.fullmatch(r"(?:otevri|spust|zapni aplikaci|nastartuj)\s+(.{2,40})", t)
    if m and not re.search(r"\b(soubor\w*|slozk\w*|web\w*|strank\w*|dokument\w*|posledni|email\w*|mail\w*|fotk\w*|obrazek|pdf)\b", m.group(1)):
        return Plan([("open_app", {"name": m.group(1)})], fallback=True, kind="app")
    m = re.fullmatch(r"(?:zavri|ukonci|vypni aplikaci|killni)\s+(.{2,40})", t)
    if m and not re.search(r"\b(okn\w*|vsechn\w*|vse|zbytecn\w*|tab\w*|zalozk\w*|pocitac|pc)\b", m.group(1)):
        return Plan([("close_app", {"name": m.group(1)})], kind="app")
    return None


_APPS: dict = {"at": 0.0, "names": []}


def app_known(rt, name: str) -> bool:
    """"otevři X" goes the instant way only for an app this PC knows – not a protocol ("spusť herní režim"), not a
    file or a web page (those the AI handles)."""
    import time

    n = norm(name).replace(" ", "")
    if len(n) < 2:
        return False
    for p in getattr(getattr(rt.cfg, "stark", None), "protocols", []) or []:
        words = [norm(getattr(p, k, "") or "").replace(" ", "") for k in ("name", "id")] + \
                [norm(t).replace(" ", "") for t in (getattr(p, "triggers", None) or getattr(p, "phrases", None) or [])]
        if any(w and (w == n or n in w or w in n) for w in words):
            return False
    try:
        from .tools.platform.windows import ALIASES

        if n in {norm(k).replace(" ", "") for k in ALIASES}:
            return True
    except Exception:  # noqa: BLE001 – not Windows
        pass
    if time.time() - _APPS["at"] > 600:
        try:
            _APPS["names"] = [norm(a).replace(" ", "") for a in rt.platform.list_apps()]
        except Exception:  # noqa: BLE001
            _APPS["names"] = []
        _APPS["at"] = time.time()
    return any(a == n or (len(n) >= 4 and n in a) for a in _APPS["names"])


def answer(p: Plan, cards: list[dict]) -> str | None:
    """What JARVIS says after the steps; None = let the AI handle it (a step failed where the AI may do better)."""
    if not cards:
        return None
    if p.fallback and not all(c["ok"] for c in cards):
        return None
    if p.say:
        try:
            out = p.say(cards)
            if out:
                return out
        except Exception:  # noqa: BLE001
            pass
    return " ".join(c["summary"] for c in cards if c.get("summary")).strip() or "Hotovo."
