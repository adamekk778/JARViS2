"""3.20 Hlas+ (nápady 1–20 ze stránky „Nápady pro JARVISe“).

- jen do sluchátek: nasazená sluchátka → hlas jen do nich, nic do reproduktorů v domě (1)
- šepot: zesílení a vyrovnání šeptané nahrávky před rozpoznáním (2)
- sčítání nahlas: „sečti 120 a 250“, „a ještě 80“, „kolik to dělá“ – bez AI (3)
- rozhovor ve dvou: bez probouzecího slova JARVIS neodpovídá větě určené někomu jinému („Jano, podej mi…“) (4)
- budíček s ranním souhrnem (5), zpráva pro budoucí já (11) – naplánované přes plánovač
- navigace v dlouhé odpovědi: „přeskoč“, „vrať se o větu“, „jen závěr“ (6); „cože?“ = pomaleji znovu (9)
- hlasové poznámky s nahrávkou, časem a místem (7)
- předání rozhovoru mezi místnostmi: nedořečená odpověď dojde tam, kde jsi teď (8)
- čtení dlouhých textů se záložkou a rychlostí (10)
- čeština a angličtina v jedné větě: opraví počeštěná anglická slova z rozpoznávání (12)
- pohádkový hlas v dětském režimu (13), krátký tón místo „Hotovo“ (15), rychlejší čtení dlouhých odpovědí (18)
- rodinné hlasování (14), hlasová zpráva blízkým (16), nácvik prezentace (17)
- čtení oznámení podle odesílatele (19), vlastní hlas z nahrávky – jen se souhlasem (20)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def words(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s,.:%+-]", " ", fold(s)).split())


# ------------------------------------------------------------------ (1) jen do sluchátek
HEADPHONE_WORDS = ("sluchat", "headphone", "headset", "earphone", "earbud", "buds", "airpods", "hands-free",
                   "handsfree", "wh-1000", "jabra", "arctis", "hyperx cloud", "kraken")


def is_headphones(name: str) -> bool:
    n = fold(name)
    return any(w in n for w in HEADPHONE_WORDS)


def headphones_out(outputs: list[str]) -> str:
    """The first output device that is headphones ("" = none connected)."""
    return next((o for o in outputs if is_headphones(o)), "")


def _outputs() -> list[str]:
    try:
        from .voice.devices import list_devices

        return list_devices().get("outputs", [])
    except Exception:  # noqa: BLE001
        return []


def output_for(rt: Any, outputs: list[str] | None = None) -> str:
    """Which speaker JARVIS talks into: with "jen do sluchátek" and headphones connected, the headphones."""
    v = rt.cfg.voice
    if getattr(v, "headphones_only", False):
        hp = headphones_out(_outputs() if outputs is None else outputs)
        if hp:
            return hp
    return v.output_device


def house_speakers_ok(rt: Any, outputs: list[str] | None = None) -> bool:
    """False while you wear headphones with "jen do sluchátek": nothing goes to the speakers around the house."""
    if not getattr(rt.cfg.voice, "headphones_only", False):
        return True
    return not headphones_out(_outputs() if outputs is None else outputs)


# ------------------------------------------------------------------ (2) šepot
def whisper_boost(x, rate: int = 16000):
    """A whispered recording levelled up (to ~-20 dBFS), with the low rumble cut – the recognizer hears it clearly.
    Anything that is not a whisper comes back unchanged."""
    import numpy as np

    from .voice.voiceid import is_whisper

    x = np.asarray(x, np.float32)
    if len(x) < rate // 4 or not is_whisper(x, rate):
        return x
    y = x - np.convolve(x, np.ones(64, np.float32) / 64, mode="same")      # cut what is below ~250 Hz (breath, hum)
    rms = float(np.sqrt(np.mean(y ** 2))) or 1e-6
    y = y * min(30.0, 0.1 / rms)
    return np.clip(y, -0.98, 0.98).astype(np.float32)


# ------------------------------------------------------------------ (3) sčítání nahlas
UNITS = {"nula": 0, "jedna": 1, "jeden": 1, "jedno": 1, "jednu": 1, "dva": 2, "dve": 2, "tri": 3, "ctyri": 4, "pet": 5,
         "sest": 6, "sedm": 7, "osm": 8, "devet": 9, "deset": 10, "jedenact": 11, "dvanact": 12, "trinact": 13,
         "ctrnact": 14, "patnact": 15, "sestnact": 16, "sedmnact": 17, "osmnact": 18, "devatenact": 19}
TENS = {"dvacet": 20, "tricet": 30, "ctyricet": 40, "padesat": 50, "sedesat": 60, "sedmdesat": 70, "osmdesat": 80,
        "devadesat": 90}
HUNDREDS = {"sto": 100, "dveste": 200, "trista": 300, "ctyrista": 400, "petset": 500, "sestset": 600, "sedmset": 700,
            "osmset": 800, "devetset": 900}
SCALES = {"tisic": 1000, "tisice": 1000, "tisicu": 1000, "milion": 1_000_000, "miliony": 1_000_000, "milionu": 1_000_000}


def cz_number(text: str) -> float | None:
    """'250', '1 250,50', 'dvě stě padesát', 'tři tisíce dvě stě' → the number (None = no number there)."""
    t = fold(text).replace(" ", " ")
    m = re.search(r"[-−]?\d{1,3}(?:[ .]\d{3})+(?:,\d+)?|[-−]?\d+(?:[.,]\d+)?", t)
    if m:
        s = m.group(0).replace("−", "-")
        if re.fullmatch(r"-?\d{1,3}(?:[ .]\d{3})+(?:,\d+)?", s):
            s = s.replace(" ", "").replace(".", "")
        return float(s.replace(",", "."))
    t = re.sub(r"\bdve ste\b", "dveste", t)
    t = re.sub(r"\b(tri|ctyri)\s+sta\b", r"\1sta", t)
    t = re.sub(r"\b(pet|sest|sedm|osm|devet)\s+set\b", r"\1set", t)
    total, cur, seen = 0, 0, False
    for w in t.split():
        if w in UNITS:
            cur += UNITS[w]
        elif w in TENS:
            cur += TENS[w]
        elif w in HUNDREDS:
            cur += HUNDREDS[w]
        elif w in SCALES:
            total += (cur or 1) * SCALES[w]
            cur = 0
        elif w in ("a",) and seen:
            continue
        else:
            if seen:
                break
            continue
        seen = True
    return float(total + cur) if seen else None


def _fmt(n: float) -> str:
    s = f"{n:,.2f}".rstrip("0").rstrip(".") if n % 1 else f"{int(n):,}"
    return s.replace(",", " ").replace(".", ",")


TALLY_TTL = 600


def _tally(rt: Any) -> dict:
    t = getattr(rt, "voicex_tally", None)
    if not t or time.time() - t.get("ts", 0) > TALLY_TTL:
        t = rt.voicex_tally = {"items": [], "ts": time.time(), "on": False}
    return t


def tally_active(rt: Any) -> bool:
    t = getattr(rt, "voicex_tally", None)
    return bool(t and t.get("on") and time.time() - t.get("ts", 0) <= TALLY_TTL)


def _split_numbers(text: str) -> list[float]:
    parts = re.split(r"\s+(?:a|plus|\+|a jeste|pak)\s+|,\s+|;\s*", fold(text))
    out = []
    for p in parts:
        n = cz_number(p)
        if n is not None:
            out.append(-n if re.search(r"\b(minus|odecti|odeber|bez)\b", p) else n)
    return out


def tally(rt: Any, text: str) -> str:
    """One spoken step of a running sum."""
    t = _tally(rt)
    w = words(text)
    if re.search(r"\b(konec|ukonci|zrus|smaz|vynuluj|znovu|od zacatku)\w*\b.*\b(scitan\w*|soucet|souctu|pocitani)\b|\bvynuluj\b", w):
        total = sum(t["items"])
        rt.voicex_tally = {"items": [], "ts": time.time(), "on": False}
        return f"Hotovo, celkem to bylo {_fmt(total)}." if t["items"] else "Sčítání je vynulované."
    if re.search(r"\b(vrat|zrus|smaz)\w* (posledni|to posledni)\b|\bspatne\b", w) and t["items"]:
        last = t["items"].pop()
        t["ts"] = time.time()
        return f"Beru zpět {_fmt(last)}. Celkem {_fmt(sum(t['items']))}."
    if re.search(r"\b(kolik to (je|dela)|celkem|soucet|vysledek|kolik mame)\b", w) and not _split_numbers(re.sub(r"\bcelkem\b", "", w)):
        return f"Celkem {_fmt(sum(t['items']))}" + (f" ({len(t['items'])} položek)." if t["items"] else ".")
    nums = _split_numbers(re.sub(r"^\s*(sectu|secti|scitej|zacni scitat|pocitej|a jeste|jeste|pricti|plus|pridej)\b", " ", w))
    if not nums and re.search(r"\b(zacni|zacneme) (scitat|pocitat)\b", w):
        t.update(on=True, ts=time.time())
        return "Sčítám. Říkej čísla."
    if not nums:
        return "Neslyšel jsem žádné číslo."
    t["items"] += nums
    t.update(on=True, ts=time.time())
    total = sum(t["items"])
    if len(nums) > 1 and len(t["items"]) == len(nums):
        return f"{' + '.join(_fmt(n) for n in nums)} je {_fmt(total)}."
    return f"{'Mínus' if nums[-1] < 0 else 'Plus'} {_fmt(abs(nums[-1]))}, celkem {_fmt(total)}."


TALLY_START = re.compile(r"^(secti|sectu|scitej|zacni scitat|zacneme scitat)\b")
TALLY_MORE = re.compile(r"^(a jeste|jeste|plus|pricti|pridej|minus|odecti|a)\s+\S+|^(kolik to (je|dela)|celkem|soucet|vysledek)\b|"
                        r"^(konec|zrus|vynuluj)\w*\s*(scitani|soucet|scitat)?|^(vrat|zrus) posledni")


# ------------------------------------------------------------------ (4) rozhovor ve dvou
VOCATIVES = ("mami", "mamo", "tati", "tato", "babi", "dedo", "zlato", "zlatko", "milacku", "lasko", "broucku", "kluci",
             "holky", "deti", "pani", "pane", "kamo", "hele ty", "ty jo")


def _names(rt: Any) -> list[str]:
    out: list[str] = []
    for c in getattr(getattr(rt.cfg, "booking", None), "companions", []) or []:
        out.append(fold(getattr(c, "first_name", "") or getattr(c, "name", "")).split(" ")[0])
    vid = getattr(rt, "voiceid", None)
    try:
        out += [fold(n).split(" ")[0] for n in (vid.profiles.people if vid is not None else {})]
    except Exception:  # noqa: BLE001
        pass
    return [n for n in out if len(n) >= 3]


def _vocative_of(name: str) -> tuple[str, ...]:
    """Jana → jano, Petr → petre, Tomáš → tomasi, Pavel → pavle: the forms used when calling someone."""
    n = name
    forms = {n}
    if n.endswith("a"):
        forms.add(n[:-1] + "o")
    elif n.endswith("el"):
        forms.add(n[:-2] + "le")
    elif n.endswith(("s", "z", "c", "j", "x")):
        forms.add(n + "i")
    elif n.endswith("r"):
        forms.update({n + "e", n[:-1] + "re"})
    elif n.endswith("k"):
        forms.update({n[:-1] + "ku", n + "u"})
    else:
        forms.update({n + "e", n + "u"})
    return tuple(forms)


def aside(rt: Any, text: str) -> bool:
    """The words were for someone else in the room (said without "Jarvisi") – JARVIS keeps quiet."""
    if not getattr(rt.cfg.voice, "addressed_only", True):
        return False
    w = words(text)
    if not w or re.search(r"\b(j|dz)arvis\w*\b", w):
        return False
    first = re.split(r"[,.]", w, maxsplit=1)[0].strip()
    head = first.split(" ")[:2]
    if any(" ".join(head).startswith(v) for v in VOCATIVES) or head[0] in VOCATIVES:
        return True
    for n in _names(rt):
        if head and head[0] in _vocative_of(n):
            return True
    return bool(re.match(r"^(ty|vy) (jsi|jste|mas|mate|budes|chces)\b", w))


# ------------------------------------------------------------------ (5) budíček, (11) zpráva pro budoucí já
def parse_when(text: str, now: dt.datetime | None = None) -> dt.datetime | None:
    """'7:30', 'zítra v 6', 'v pondělí v 8', '24. 12.', '24. 12. 2027 9:00', 'za týden', 'za 3 dny' → a time."""
    now = now or dt.datetime.now()
    t = fold(text)
    tm = re.search(r"(\d{1,2})[:.](\d{2})(?!\.\d)(?!\s?\d{4})", t) or re.search(r"\bv (\d{1,2})\b(?! ?\.)", t)
    if tm and tm.lastindex == 2:
        h, mi = int(tm.group(1)), int(tm.group(2))
    else:
        h, mi = (int(tm.group(1)), 0) if tm else (9, 0)
    if h > 23 or mi > 59:
        return None
    day = now.date()
    m = re.search(r"\b(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?", t)
    days = {"pondel": 0, "uter": 1, "stred": 2, "ctvrt": 3, "patek": 4, "sobot": 5, "nedel": 6}
    if m:
        y = int(m.group(3)) if m.group(3) else now.year
        try:
            day = dt.date(y, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
        if not m.group(3) and day < now.date():
            day = day.replace(year=y + 1)
    elif re.search(r"\bpozitri\b", t):
        day = now.date() + dt.timedelta(days=2)
    elif re.search(r"\bzitra\b", t):
        day = now.date() + dt.timedelta(days=1)
    elif (mz := re.search(r"\bza (\d+|jeden|jednu|dva|dve|tri|ctyri|pet|tyden|mesic|rok)\s*(dn\w*|den|tyd\w*|mesic\w*|rok\w*|let)?", t)):
        k = mz.group(1)
        n = int(k) if k.isdigit() else {"jeden": 1, "jednu": 1, "dva": 2, "dve": 2, "tri": 3, "ctyri": 4, "pet": 5}.get(k, 1)
        unit = mz.group(2) or k
        mult = 7 if unit.startswith("tyd") else 30 if unit.startswith("mesic") else 365 if unit.startswith(("rok", "let")) else 1
        day = now.date() + dt.timedelta(days=n * mult)
        if not tm:
            h, mi = now.hour, now.minute
    else:
        for k, wd in days.items():
            if re.search(rf"\b(v|ve|pristi)?\s?{k}\w*", t) and k in t:
                ahead = (wd - now.weekday()) % 7 or 7
                day = now.date() + dt.timedelta(days=ahead)
                break
    at = dt.datetime.combine(day, dt.time(h, mi))
    if at <= now and day == now.date() and not m:
        at += dt.timedelta(days=1)
    return at if at > now else None


def schedule_alarm(rt: Any, when: str, days: str = "", now: dt.datetime | None = None) -> dict:
    """A wake-up at that time: a soft tone, then the morning summary in JARVIS's voice. days = "po-pa" / "denně"."""
    if days:
        m = re.search(r"(\d{1,2})[:.](\d{2})", when or "") or re.search(r"(\d{1,2})", when or "")
        if not m:
            raise ValueError("Nerozumím času budíku.")
        h, mi = int(m.group(1)), int(m.group(2)) if m.lastindex and m.lastindex > 1 else 0
        dd = fold(days)
        wd = list(range(5)) if re.search(r"po.?pa|vsedni|pracovni", dd) else [5, 6] if "vikend" in dd else list(range(7))
        spec = {"type": "daily", "days": wd, "time": f"{h:02d}:{mi:02d}"}
        return rt.scheduler.add(spec, "voice_alarm", {}, title=f"Budíček {h:02d}:{mi:02d}")
    at = parse_when(when, now)
    if at is None:
        raise ValueError("Ten čas už byl nebo mu nerozumím.")
    return rt.scheduler.add_once(at, "voice_alarm", {}, title=f"Budíček {at:%H:%M}")


async def run_alarm(rt: Any, payload: dict) -> None:
    """The alarm itself: a tone through the speaker, then the summary (it comes to the phone too when you are away)."""
    from . import morning

    try:
        s = await morning.build(rt)
        text = s["text"]
    except Exception as e:  # noqa: BLE001
        log.info("alarm summary: %s", e)
        text = ""
    hour = dt.datetime.now().hour
    hello = "Dobré ráno" if hour < 10 else "Dobrý den"
    rt.notify("Budíček", f"{hello}. {text}".strip(), urgent=True)


def schedule_future(rt: Any, text: str, when: str, audio: str = "", now: dt.datetime | None = None) -> dict:
    at = parse_when(when, now)
    if at is None:
        raise ValueError("Ten den už byl nebo mu nerozumím – zkus třeba „24. 12. 2027“ nebo „za rok“.")
    payload = {"text": text.strip(), "audio": audio, "made": dt.date.today().isoformat()}
    return rt.scheduler.add_once(at, "future_message", payload, title=f"Vzkaz pro budoucí já ({at:%d. %m. %Y})")


async def run_future(rt: Any, payload: dict) -> None:
    made = payload.get("made") or ""
    when = f" z {dt.date.fromisoformat(made):%d. %m. %Y}" if made else ""
    rt.notify("Vzkaz pro tebe", f"Vzkaz{when}: {payload.get('text', '')}", urgent=True)
    audio = payload.get("audio")
    if audio and Path(audio).is_file() and getattr(rt, "speaker", None) is not None:
        try:
            import asyncio

            await asyncio.to_thread(rt.speaker._play, Path(audio).read_bytes())
        except Exception as e:  # noqa: BLE001
            log.info("future message audio: %s", e)


# ------------------------------------------------------------------ (6) navigace, (9) pomaleji
def sentences(text: str) -> list[str]:
    from .voice.stream import speakable

    t = " ".join(speakable(text or "").split())
    parts = re.split(r"(?<=[.!?…])\s+(?=[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ0-9„\"(])", t)
    return [p.strip() for p in parts if re.search(r"\w", p)]


def remember_answer(rt: Any, text: str, stream: Any = None) -> None:
    """What JARVIS just said (or is saying) – for "přeskoč", "vrať se", "jen závěr", "cože?"."""
    rt.voicex_said = {"text": text, "stream": stream, "ts": time.time()}


def _position(said: dict) -> int:
    st = said.get("stream")
    if st is not None and getattr(st, "queued", None):
        heard = max(0, int(getattr(st, "played", 0)))
        done = " ".join(st.queued[:heard])
        return len(sentences(done))
    return 0


NAV_WINDOW = 30


def nav_active(rt: Any) -> bool:
    said = getattr(rt, "voicex_said", None)
    if not said or len(sentences(said["text"])) < 3:
        return False
    sp = getattr(rt, "speaker", None)
    return bool(sp is not None and sp.speaking) or time.time() - said["ts"] < NAV_WINDOW


NAV = re.compile(r"^(preskoc( to| tuhle vetu| dal)?|dal|vrat se( o vetu| zpet)?|zopakuj (posledni|tu) vetu|"
                 r"(rekni |rekni mi )?(jen|jenom|rovnou) (zaver|konec|shrnuti|vysledek)|(jak|co) to (konci|je na konci))$")
SLOWER = re.compile(r"^(coze|cos rikal|co jsi rikal|cos to rikal|nerozumel jsem|nerozumim|zopakuj( to)?( pomaleji| jeste jednou)?|"
                    r"pomaleji|rekni to pomaleji|jeste jednou( pomaleji)?|prosim)$")


def navigate(rt: Any, how: str) -> tuple[str, str]:
    """(what to say, the rate change) for skip / back / end / slow."""
    said = getattr(rt, "voicex_said", None)
    if not said:
        return "Zatím jsem nic neříkal.", ""
    ss = sentences(said["text"])
    pos = _position(said)
    sp = getattr(rt, "speaker", None)
    if sp is not None:
        sp.stop()
    if how == "slow":
        last = ss[pos - 1 if 0 < pos <= len(ss) else 0:][:3] if pos else ss[-3:]
        return " ".join(last or ss[-1:]), "-20%"
    if how == "end":
        return ss[-1], ""
    if how == "back":
        start = max(0, pos - 2)
        return " ".join(ss[start:]), ""
    rest = ss[pos + 1:] if pos + 1 < len(ss) else []
    return (" ".join(rest) if rest else "To byl konec."), ""


def nav_kind(text: str) -> str:
    w = words(text).strip(" .?!")
    if SLOWER.match(w):
        return "slow"
    if not NAV.match(w):
        return ""
    if re.search(r"zaver|konec|shrnuti|vysledek|konci", w):
        return "end"
    if re.search(r"vrat|zopakuj", w):
        return "back"
    return "skip"


# ------------------------------------------------------------------ (7) hlasové poznámky
def notes_dir() -> Path:
    from .paths import data_dir

    p = data_dir() / "hlasove-poznamky"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_voice_note(rt: Any, text: str, pcm16: bytes | None = None, place: str = "") -> dict:
    """The words, the recording (WAV) and when / where – in Dokumenty-like data folder and in the notes list."""
    now = dt.datetime.now()
    stem = now.strftime("%Y-%m-%d_%H-%M-%S")
    wav = ""
    if pcm16:
        import wave

        p = notes_dir() / f"{stem}.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm16)
        wav = str(p)
    if not place:
        loc = getattr(rt, "phone_location", None) or {}
        place = str(loc.get("place") or loc.get("name") or "")
    rt.db.exec("CREATE TABLE IF NOT EXISTS voice_notes (ts REAL, text TEXT, wav TEXT, place TEXT)")
    rt.db.exec("INSERT INTO voice_notes VALUES (?,?,?,?)", (now.timestamp(), text.strip(), wav, place))
    return {"text": text.strip(), "wav": wav, "place": place, "when": now.strftime("%d. %m. %Y %H:%M")}


def voice_notes(rt: Any, limit: int = 20) -> list[dict]:
    rt.db.exec("CREATE TABLE IF NOT EXISTS voice_notes (ts REAL, text TEXT, wav TEXT, place TEXT)")
    return [dict(r) for r in rt.db.all("SELECT * FROM voice_notes ORDER BY ts DESC LIMIT ?", (limit,))]


NOTE = re.compile(r"^(poznamenej si|zapis si|hlasova poznamka|poznamka)\b[:,]?\s*(.+)$")


# ------------------------------------------------------------------ (8) předání rozhovoru mezi místnostmi
HANDOFF_S = 90


def unspoken_rest(rt: Any) -> str:
    """What JARVIS has not said yet of the answer he is (or was just) saying."""
    said = getattr(rt, "voicex_said", None)
    if not said or time.time() - said["ts"] > HANDOFF_S:
        return ""
    st = said.get("stream")
    if st is not None and getattr(st, "queued", None):
        left = st.queued[max(0, int(getattr(st, "played", 0))):]
        return " ".join(left).strip()
    sp = getattr(rt, "speaker", None)
    return said["text"] if sp is not None and sp.speaking else ""


async def handoff(rt: Any, room: str) -> str:
    """You went to another room: the rest of the answer is said there, the conversation goes on there."""
    rest = unspoken_rest(rt)
    rt.voicex_room = {"room": room, "ts": time.time()}
    if not rest:
        return ""
    sp = getattr(rt, "speaker", None)
    if sp is not None:
        sp.stop()
    from . import house

    try:
        await house.announce(rt, rest, room)
    except Exception as e:  # noqa: BLE001
        log.info("handoff: %s", e)
        return ""
    rt.voicex_said = None
    return rest


def room_context(rt: Any, room: str) -> str:
    """A line for the AI: the talk continues from another room (it has the history, it should not start over)."""
    last = getattr(rt, "voicex_room", None) or {}
    prev = last.get("room") or "u počítače"
    if time.time() - float(last.get("ts", 0) or 0) > HANDOFF_S * 2 or prev == room:
        rt.voicex_room = {"room": room, "ts": time.time()}
        return ""
    rt.voicex_room = {"room": room, "ts": time.time()}
    return f"Uživatel přešel z místa „{prev}“ do místnosti „{room}“ a pokračuje ve stejném rozhovoru – navaž na něj."


# ------------------------------------------------------------------ (10) čtení dlouhých textů
def _reading_state(rt: Any) -> dict:
    rt.db.exec("CREATE TABLE IF NOT EXISTS read_aloud (key TEXT PRIMARY KEY, title TEXT, pos INTEGER, total INTEGER, ts REAL)")
    st = getattr(rt, "voicex_read", None)
    if st is None:
        st = rt.voicex_read = {"key": "", "sentences": [], "pos": 0, "rate": 0, "title": ""}
    return st


def doc_key(source: str, text: str) -> str:
    import hashlib

    return hashlib.sha1((source or text[:2000]).encode("utf-8", "ignore")).hexdigest()[:16]


def start_reading(rt: Any, title: str, text: str, source: str = "") -> dict:
    st = _reading_state(rt)
    ss = sentences(text)
    key = doc_key(source, text)
    row = rt.db.one("SELECT pos FROM read_aloud WHERE key=?", (key,))
    pos = int(row["pos"]) if row and row["pos"] < len(ss) else 0
    st.update(key=key, sentences=ss, pos=pos, title=title or source or "text")
    rt.db.exec("INSERT OR REPLACE INTO read_aloud VALUES (?,?,?,?,?)", (key, st["title"], pos, len(ss), time.time()))
    return {"resumed": pos > 0, "pos": pos, "total": len(ss)}


def next_chunk(rt: Any, n: int = 4) -> str:
    st = _reading_state(rt)
    ss = st["sentences"]
    if st["pos"] >= len(ss):
        return ""
    chunk = ss[st["pos"]:st["pos"] + n]
    st["pos"] += len(chunk)
    rt.db.exec("UPDATE read_aloud SET pos=?, ts=? WHERE key=?", (st["pos"], time.time(), st["key"]))
    return " ".join(chunk)


def reading_rate(rt: Any, delta: int) -> int:
    st = _reading_state(rt)
    st["rate"] = max(-40, min(60, int(st.get("rate", 0)) + delta))
    return st["rate"]


def where_reading(rt: Any) -> str:
    st = _reading_state(rt)
    if not st["sentences"]:
        rows = rt.db.all("SELECT title, pos, total FROM read_aloud ORDER BY ts DESC LIMIT 3")
        if not rows:
            return "Nic teď nečtu."
        return "Rozečtené: " + "; ".join(f"{r['title']} ({round(100 * r['pos'] / max(1, r['total']))} %)" for r in rows)
    pct = round(100 * st["pos"] / max(1, len(st["sentences"])))
    return f"„{st['title']}“ – mám přečteno {pct} % ({st['pos']} z {len(st['sentences'])} vět), rychlost {st['rate']:+d} %."


async def read_loop(rt: Any) -> None:
    """Reads the current text piece by piece until it ends, the speaker is stopped or reading is paused."""
    st = _reading_state(rt)
    st["paused"] = False
    sp = getattr(rt, "speaker", None)
    if sp is None:
        return
    while not st.get("paused"):
        chunk = next_chunk(rt)
        if not chunk:
            rt.notify("Čtení", f"Dočteno: {st['title']}.", speak=False)
            break
        audio, _ = await sp.synth(chunk, "cs", override={"tts_rate": f"{st['rate']:+d}%"} if st["rate"] else None)
        sp._stop.clear()
        import asyncio

        await asyncio.to_thread(sp._play, audio)
        if sp._stop.is_set():
            st["paused"] = True
            st["pos"] = max(0, st["pos"] - 4)     # stopped in the middle: next time from that piece
            rt.db.exec("UPDATE read_aloud SET pos=? WHERE key=?", (st["pos"], st["key"]))
            break


# ------------------------------------------------------------------ (12) čeština + angličtina v jedné větě
CODESWITCH = {
    "cil vajbs": "chill vibes", "cil vajbz": "chill vibes", "cill vajbs": "chill vibes", "lofaj": "lo-fi", "lou faj": "lo-fi",
    "plejlist": "playlist", "plejlistu": "playlistu", "plejlistem": "playlistem", "spotifaj": "Spotify", "jutub": "YouTube",
    "jutjub": "YouTube", "netfliks": "Netflix", "diskord": "Discord", "majkrosoft": "Microsoft", "vord": "Word",
    "eksel": "Excel", "pauerpoint": "PowerPoint", "goglu": "Googlu", "gugl": "Google", "fidbek": "feedback",
    "dedlajn": "deadline", "mítink": "meeting", "mitink": "meeting", "tím": "team", "tímu": "týmu", "apdejt": "update",
    "brejk": "break", "lajk": "like", "stím": "Steam", "fortnajt": "Fortnite", "majnkraft": "Minecraft",
    "valorent": "Valorant", "čatdžípítý": "ChatGPT", "čet džípítí": "ChatGPT", "klód": "Claude", "olama": "Ollama",
    "best of": "best of", "gud mornink": "good morning", "dárk mód": "dark mode", "dark mód": "dark mode",
    "hepi": "happy", "rok end rol": "rock and roll", "houm ofis": "home office", "houmofis": "home office",
}


def codeswitch(rt: Any, text: str) -> str:
    """English words the Czech recognizer wrote the Czech way, back to English (your own names from settings too)."""
    if not getattr(rt.cfg.voice, "code_switch", True) or not text:
        return text
    pairs = {fold(k): v for k, v in CODESWITCH.items()}
    for r in getattr(rt.cfg.voice, "pronounce", None) or []:       # "how to say it" works the other way round here
        if getattr(r, "src", "") and getattr(r, "dst", "") and re.search(r"[a-zA-Z]", r.src):
            pairs[fold(r.dst)] = r.src
    out = text
    for k in sorted(pairs, key=len, reverse=True):            # matched without accents, replaced in the original
        f = fold(out)
        if len(f) != len(out):
            break
        spans = [m.span() for m in re.finditer(rf"(?<!\w){re.escape(k)}(?!\w)", f)]
        for a, b in reversed(spans):
            out = out[:a] + pairs[k] + out[b:]
    return out


# ------------------------------------------------------------------ (13) pohádkový hlas, (15) tón, (18) rychlost
KIDS_VOICE = {"tts_voice": "cs-CZ-VlastaNeural", "tts_rate": "-8%", "tts_pitch": "+12Hz"}


def kids_override(rt: Any) -> dict | None:
    try:
        from .safety import kids_on

        if kids_on(rt) and getattr(rt.cfg.voice, "kids_voice", True):
            return dict(KIDS_VOICE)
    except Exception:  # noqa: BLE001
        return None
    return None


ACK = re.compile(r"^(hotovo|udelano|provedeno|zapnuto|vypnuto|ztlumeno|pousti?m\w*|otviram\w*|zaviram\w*|rozumim|ok|dobre|"
                 r"jasne|zapisuji|zapsano|ulozeno|nastaveno|spusteno|zastaveno|dalsi|predchozi)\b[^.!?]{0,40}[.!]?$")


def plain_ack(text: str) -> bool:
    w = words(text).strip()
    w = re.sub(r",? ?(pane|sefe|pani)\b", "", w).strip(" .!")
    return bool(w) and len(w) <= 48 and bool(ACK.match(w))


def tone_wav(freqs: tuple[float, ...] = (880.0, 1320.0), ms: int = 90, sr: int = 24000) -> bytes:
    """A short soft two-note confirmation (WAV)."""
    import io
    import wave

    import numpy as np

    parts = []
    for f in freqs:
        n = int(sr * ms / 1000)
        t = np.arange(n) / sr
        env = np.minimum(1, np.minimum(t * 200, (n / sr - t) * 60))
        parts.append(0.25 * np.sin(2 * math.pi * f * t) * env)
    pcm = (np.concatenate(parts) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def length_rate(rt: Any, text: str, rate: str) -> str:
    """Long answers a little faster (up to +12 %), short ones as set."""
    if not getattr(rt.cfg.voice, "length_rate", True):
        return rate
    n = len(text or "")
    add = 0 if n < 280 else 6 if n < 700 else 12
    m = re.match(r"\s*([+-]?\d+)", str(rate or "0"))
    base = int(m.group(1)) if m else 0
    return f"{max(-50, min(100, base + add)):+d}%"


# ------------------------------------------------------------------ (14) rodinné hlasování
def poll_start(rt: Any, question: str, options: list[str] | None = None, minutes: int = 5) -> dict:
    opts = [o.strip() for o in (options or []) if o and o.strip()] or ["ano", "ne"]
    rt.voicex_poll = {"q": question.strip(), "options": opts, "votes": {}, "until": time.time() + 60 * max(1, minutes)}
    return rt.voicex_poll


def poll_active(rt: Any) -> dict | None:
    p = getattr(rt, "voicex_poll", None)
    return p if p and time.time() < p["until"] else None


def poll_answer(rt: Any, text: str, who: str = "") -> str | None:
    """A vote from a room or the PC while a poll runs ("já chci pizzu", "ano", "ne", "pro mě sushi")."""
    p = poll_active(rt)
    if not p:
        return None
    w = words(text)
    hit = None
    for o in p["options"]:
        fo = fold(o)
        if re.search(rf"\b{re.escape(fo[:max(3, len(fo) - 1)])}\w*", w):
            hit = o
            break
    if hit is None and set(fold(o) for o in p["options"]) == {"ano", "ne"}:
        hit = "ano" if re.search(r"\b(ano|jo|chci|jasne|beru|souhlas)\b", w) else "ne" if re.search(r"\b(ne|nechci|nemam zajem)\b", w) else None
    if hit is None:
        return None
    voter = who or f"hlas {len(p['votes']) + 1}"
    p["votes"][voter] = hit
    return f"Zapsáno: {hit}."


def poll_result(rt: Any) -> str:
    p = getattr(rt, "voicex_poll", None)
    if not p:
        return "Žádné hlasování neběží."
    counts: dict[str, int] = {o: 0 for o in p["options"]}
    for v in p["votes"].values():
        counts[v] = counts.get(v, 0) + 1
    if not p["votes"]:
        return f"Na „{p['q']}“ zatím nikdo neodpověděl."
    best = max(counts.values())
    win = [o for o, c in counts.items() if c == best]
    parts = ", ".join(f"{o} {c}" for o, c in counts.items())
    head = f"Vyhrává {win[0]}" if len(win) == 1 else "Je to nerozhodně (" + " / ".join(win) + ")"
    return f"{head}. Hlasy: {parts}."


# ------------------------------------------------------------------ (16) hlasová zpráva blízkým
async def voice_file(rt: Any, text: str) -> tuple[Path, str]:
    """The message in JARVIS's voice as an audio file (to send as a voice message)."""
    audio, mime = await rt.speaker.synth(text, "cs")
    ext = "mp3" if "mpeg" in mime else "wav"
    p = notes_dir() / f"zprava-{dt.datetime.now():%Y%m%d-%H%M%S}.{ext}"
    p.write_bytes(audio)
    return p, mime


# ------------------------------------------------------------------ (17) nácvik prezentace
FILLERS = ("ehm", "eee", "eh", "hm", "jako", "prostě", "vlastně", "takže", "jakoby", "no", "tak", "teda", "vole", "fakt")


def coach(text: str, seconds: float, pauses: list[float] | None = None) -> dict:
    """Tempo, filler words, length and long pauses of a practised talk – with one or two tips."""
    toks = re.findall(r"\w+", (text or "").lower())
    n = len(toks)
    wpm = round(n / (seconds / 60), 0) if seconds > 0 else 0
    fill: dict[str, int] = {}
    for t in toks:
        if t in FILLERS:
            fill[t] = fill.get(t, 0) + 1
    fill_n = sum(fill.values())
    long_p = [p for p in (pauses or []) if p >= 3.0]
    tips = []
    if wpm > 170:
        tips.append("Mluvíš rychle – zkus zpomalit k 130–150 slovům za minutu a dělat pauzy po hlavních myšlenkách.")
    elif 0 < wpm < 100:
        tips.append("Tempo je pomalé – zkus plynuleji, kolem 130 slov za minutu.")
    if n and fill_n / n > 0.04:
        top = sorted(fill.items(), key=lambda x: -x[1])[:2]
        tips.append("Hodně výplňových slov (" + ", ".join(f"„{k}“ {v}×" for k, v in top) + ") – místo nich raději krátká pauza.")
    if long_p:
        tips.append(f"{len(long_p)}× pauza delší než 3 s – připrav si přechody mezi částmi.")
    if not tips:
        tips.append("Tempo i plynulost jsou dobré. Zkus ještě zdůraznit hlavní myšlenku na začátku a na konci.")
    m, s = divmod(int(seconds), 60)
    return {"words": n, "wpm": int(wpm), "fillers": fill, "filler_share": round(fill_n / n, 3) if n else 0.0,
            "long_pauses": len(long_p), "length": f"{m}:{s:02d}", "tips": tips}


def pauses_of(pcm16: bytes, rate: int = 16000) -> list[float]:
    import numpy as np

    x = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    if not len(x):
        return []
    hop = int(rate * 0.05)
    e = np.array([float(np.sqrt(np.mean(x[i:i + hop] ** 2))) for i in range(0, len(x) - hop, hop)])
    if not len(e):
        return []
    thr = max(0.008, float(np.percentile(e, 30)) * 1.5)
    out, run = [], 0
    for v in e:
        if v < thr:
            run += 1
        else:
            if run:
                out.append(run * 0.05)
            run = 0
    return [p for p in out if p >= 0.4]


# ------------------------------------------------------------------ (19) oznámení podle odesílatele
SHOP_HINT = re.compile(r"(noreply|no-reply|newsletter|info@|obchod|shop|eshop|e-shop|sleva|akce|nabidk|objednavk|faktur|"
                       r"notifikac|notification|marketing|mailer|news@|alza|mall|rohlik|zalando|temu|aliexpress)", re.I)


def notice_text(rt: Any, sender: str, address: str, subject: str, preview: str = "") -> tuple[str, str]:
    """(title, what to say) for a new e-mail / message: family and close people in full, shops as one short line."""
    s = fold(f"{sender} {address}")
    close = [fold(x) for x in (getattr(rt.cfg.voice, "read_full_from", None) or []) if x.strip()]
    family = any(c and c in s for c in close)
    if family:
        body = preview.strip() or subject
        return "Zpráva od blízkého", f"Píše {sender or address}: {subject}. {body[:400]}".strip()
    if SHOP_HINT.search(f"{address} {sender}") and getattr(rt.cfg.voice, "short_shops", True):
        return "Nový e-mail", f"Přišel e-mail od {sender or address}."
    return "Nový e-mail", f"Píše vám {sender or address}: {subject}"


# ------------------------------------------------------------------ (20) vlastní hlas
CLONE_URL = "https://api.elevenlabs.io/v1/voices/add"


async def clone_voice(rt: Any, path: str, name: str = "Můj hlas", consent: bool = False) -> dict:
    """Your own voice from your recording (ElevenLabs instant voice clone) – only with your explicit consent, only
    your own voice, used only by this JARVIS."""
    if not consent:
        raise ValueError("Bez tvého výslovného souhlasu hlas neklonuji (consent=true).")
    p = Path(path)
    if not p.is_file() or p.stat().st_size < 20_000:
        raise ValueError("Potřebuju nahrávku tvého hlasu (aspoň ~30 s, WAV nebo MP3).")
    from . import secrets

    key = secrets.get("elevenlabs")
    if not key:
        raise ValueError("Na klon hlasu potřebuju klíč ElevenLabs (Nastavení → Hlas → Studio).")
    async with rt.http() as c:
        r = await c.post(CLONE_URL, headers={"xi-api-key": key}, data={"name": name, "description": "JARVIS – vlastní hlas"},
                         files={"files": (p.name, p.read_bytes(), "audio/mpeg" if p.suffix.lower() == ".mp3" else "audio/wav")},
                         timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs odmítl nahrávku ({r.status_code}): {r.text[:200]}")
    vid = r.json().get("voice_id", "")
    if not vid:
        raise RuntimeError("ElevenLabs nevrátil hlas.")
    rt.update_config({"voice": {"eleven_voice_id": vid, "tts_engine": "elevenlabs"}})
    rt.db.exec("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('voice_clone', ?)", (json.dumps({"id": vid, "name": name, "ts": time.time()}),))
    return {"voice_id": vid, "name": name}
