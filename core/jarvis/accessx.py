"""3.20 Přístupnost+ (ideas 461–480): the interface in Slovak, German, Polish and Ukrainian (with community packs),
a magnifier by voice, plain Czech for official letters, a light flash instead of a sound, reading product labels,
volume by the room's noise, word prediction from your own writing, Moravian and Slovak words for speech recognition
and errors explained like a person would.

The visual parts (dyslexia mode, colour-blind schemes, keyboard-only, one-switch control, simple mode, darker in the
evening) live in the web UI; this module keeps their settings and the parts that need the PC."""
from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .i18npacks import NAMES, PACKS


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


# ------------------------------------------------------------------ (461, 462, 478, 487) interface languages
UI_LANGS = tuple(NAMES)
MAX_PACK = 5000


def packs_dir() -> Path:
    from . import paths

    d = paths.data_dir() / "i18n"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ui_pack(lang: str) -> dict[str, str]:
    """The dictionary Czech → `lang`: the built-in starter words, then your / the community's pack on top."""
    if lang not in UI_LANGS or lang in ("cs",):
        return {}
    out = dict(PACKS.get(lang, {}))
    f = packs_dir() / f"{lang}.json"
    if f.exists():
        try:
            extra = json.loads(f.read_text(encoding="utf-8"))
            out.update({k: v for k, v in extra.items() if isinstance(k, str) and isinstance(v, str) and v.strip()})
        except ValueError:
            pass
    return out


def clean_pack(data: Any) -> dict[str, str]:
    """A pack from the translators' page: only short text → text, no markup (the UI shows it as text, but be strict)."""
    if not isinstance(data, dict):
        raise ValueError("Čekám slovník text → překlad.")
    out = {}
    for k, v in list(data.items())[:MAX_PACK]:
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        k, v = k.strip(), v.strip()
        if not k or not v or len(k) > 400 or len(v) > 600 or "<" in v or ">" in v:
            continue
        out[k] = v
    return out


def save_pack(lang: str, data: Any) -> int:
    if lang not in UI_LANGS or lang in ("cs", "en"):
        raise ValueError(f"Jazyk {lang} nepřekládám (umím {', '.join(x for x in UI_LANGS if x not in ('cs', 'en'))}).")
    pack = clean_pack(data)
    f = packs_dir() / f"{lang}.json"
    old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    old.update(pack)
    f.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(pack)


def ui_keys() -> list[str]:
    """Every Czech text of the UI that can be translated (the web build writes the list next to the app)."""
    from . import paths

    f = paths.web_dist() / "i18n-keys.json"
    try:
        keys = json.loads(f.read_text(encoding="utf-8"))
        return [k for k in keys if isinstance(k, str)]
    except (OSError, ValueError):
        return sorted(PACKS["sk"])


VOICES = {"sk": "sk-SK-LukasNeural", "de": "de-DE-ConradNeural", "pl": "pl-PL-MarekNeural", "uk": "uk-UA-OstapNeural", "en": "en-GB-RyanNeural"}
ANSWER_RULE = {"en": "Odpověz anglicky.", "sk": "Odpovídaj po slovensky.", "de": "Antworte auf Deutsch.", "pl": "Odpowiadaj po polsku.",
               "uk": "Відповідай українською."}


# ------------------------------------------------------------------ (466) plain Czech
PLAIN_PROMPT = ("Přepiš tento úřední text do jednoduché češtiny pro člověka, kterému čtení dělá potíže: krátké věty (nejvýš 12 slov), "
                "běžná slova místo úředních, žádné cizí výrazy bez vysvětlení. Začni jednou větou „O co jde“, pak odrážky „Co musíš "
                "udělat“ (s termíny tučně) a „Co se stane, když nic neuděláš“. Nic nevynechávej z povinností, částek a termínů, nic "
                "nepřidávej. Pokud něčemu nerozumíš, napiš to.\n\nText:\n{text}")


# ------------------------------------------------------------------ (471) product labels
LABEL_PROMPT = ("Na fotce je obal výrobku nebo cenovka. Přečti a vrať JEN JSON: {\"nazev\": …, \"cena\": …, \"cena_za_jednotku\": …, "
                "\"slozeni\": …, \"alergeny\": [..], \"spotrebujte_do\": …, \"varovani\": …}. Co na fotce není, dej null. Alergeny "
                "ber ze zvýrazněných slov ve složení (lepek, mléko, vejce, ořechy, arašídy, sója, celer, hořčice, sezam, ryby, korýši, "
                "měkkýši, vlčí bob, oxid siřičitý).")
ALLERGENS = ("lepek", "mleko", "vejce", "orech", "arasid", "soja", "celer", "horcic", "sezam", "ryb", "korys", "mekkys", "vlci bob", "sirici")


def parse_label(text: str, my_allergies: list[str] | None = None) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("Etiketu se nepodařilo přečíst – zkus ostřejší fotku zblízka.")
    d = json.loads(m.group(0))
    found = [a for a in d.get("alergeny") or [] if isinstance(a, str)]
    mine = [a for a in (my_allergies or []) if any(fold(a)[:4] in fold(x) for x in found + [str(d.get("slozeni") or "")])]
    d["pozor"] = mine
    return d


def label_text(d: dict) -> str:
    bits = [str(d.get("nazev") or "Výrobek")]
    if d.get("cena"):
        bits.append(f"cena {d['cena']}" + (f" ({d['cena_za_jednotku']})" if d.get("cena_za_jednotku") else ""))
    if d.get("spotrebujte_do"):
        bits.append(f"spotřebujte do {d['spotrebujte_do']}")
    if d.get("alergeny"):
        bits.append("alergeny: " + ", ".join(d["alergeny"]))
    out = ", ".join(bits) + "."
    if d.get("pozor"):
        out = "POZOR, obsahuje to, na co jsi alergický(á): " + ", ".join(d["pozor"]) + ". " + out
    return out


# ------------------------------------------------------------------ (463) magnifier (Windows Lupa)
ZOOM_KEYS = {"in": ["win", "+"], "out": ["win", "-"], "off": ["win", "esc"]}


def zoom_action(text: str) -> str:
    t = fold(text)
    if any(w in t for w in ("vypn", "zavri", "konec", "zrus")):
        return "off"
    if any(w in t for w in ("oddal", "zmens", "mene")):
        return "out"
    return "in"


# ------------------------------------------------------------------ (467) a light instead of a sound
FLASH_KINDS = ("doorbell", "zvon", "alarm", "budik", "kour", "smoke", "pozar", "unik", "sos")


def should_flash(title: str, body: str, urgent: bool) -> bool:
    t = fold(f"{title} {body}")
    return urgent or any(k in t for k in FLASH_KINDS)


async def flash(rt: Any, lights: list[str], times: int = 3) -> int:
    """Blinks the lights (Home Assistant's own flash, or on/off) so a deaf person notices the doorbell or an alarm."""
    n = 0
    for e in lights:
        try:
            await rt.home.service("light", "turn_on", {"entity_id": e, "flash": "long"})
            n += 1
        except Exception:  # noqa: BLE001 – a light without flash support: on/off
            for _ in range(times):
                await rt.home.service("homeassistant", "toggle", {"entity_id": e})
            n += 1
    return n


# ------------------------------------------------------------------ (475) volume by the room's noise
def volume_for_noise(db: float | None, base: int = 50, quiet_db: float = 35, loud_db: float = 70) -> int:
    """The speaking volume for the noise in the room (dB from the microphone): base in a quiet room, up to +35 % in noise,
    a little softer at night-quiet."""
    if db is None:
        return base
    if db <= quiet_db:
        return max(15, base - 10)
    k = min(1.0, (db - quiet_db) / (loud_db - quiet_db))
    return min(100, round(base + 35 * k))


def rms_db(samples: Any) -> float:
    import numpy as np

    a = np.asarray(samples, dtype=np.float32)
    if a.size == 0:
        return 0.0
    if a.dtype.kind == "f" and np.abs(a).max() > 1.5:
        a = a / 32768.0
    rms = float(np.sqrt(np.mean(a ** 2)))
    return round(20 * math.log10(max(rms, 1e-6)) + 94, 1)      # rough: full scale ≈ 94 dB SPL


# ------------------------------------------------------------------ (476) word prediction
class Predictor:
    """Next words from what you have written to JARVIS (bigrams and trigrams, your own words first)."""

    def __init__(self) -> None:
        self.bi: dict[str, Counter] = defaultdict(Counter)
        self.tri: dict[tuple[str, str], Counter] = defaultdict(Counter)
        self.uni: Counter = Counter()

    @staticmethod
    def words(text: str) -> list[str]:
        return re.findall(r"[\wáčďéěíňóřšťúůýž]+", (text or "").lower())

    def learn(self, text: str) -> None:
        w = self.words(text)
        self.uni.update(w)
        for a, b in zip(w, w[1:], strict=False):
            self.bi[a][b] += 1
        for a, b, c in zip(w, w[1:], w[2:], strict=False):
            self.tri[(a, b)][c] += 1

    def next(self, prefix: str, n: int = 3) -> list[str]:
        """Suggestions for what comes next. A half-typed word is completed instead."""
        ends_space = prefix.endswith((" ", "\n"))
        w = self.words(prefix)
        if not ends_space and w:
            part = w[-1]
            ctx = w[:-1]
            pool: Counter = Counter()
            if len(ctx) >= 2:
                pool.update({k: v * 3 for k, v in self.tri.get((ctx[-2], ctx[-1]), Counter()).items()})
            if ctx:
                pool.update({k: v * 2 for k, v in self.bi.get(ctx[-1], Counter()).items()})
            pool.update(self.uni)
            return [x for x, _ in pool.most_common(200) if x.startswith(part) and x != part][:n]
        pool = Counter()
        if len(w) >= 2:
            pool.update({k: v * 3 for k, v in self.tri.get((w[-2], w[-1]), Counter()).items()})
        if w:
            pool.update(self.bi.get(w[-1], Counter()))
        return [x for x, _ in pool.most_common(n)]


def predictor(rt: Any) -> Predictor:
    p = getattr(rt, "_predictor", None)
    if p is not None and time.time() - getattr(rt, "_predictor_at", 0) < 3600:
        return p
    p = Predictor()
    try:
        rows = rt.db.all("SELECT content FROM messages WHERE role='user' ORDER BY rowid DESC LIMIT 3000")
        for r in rows:
            p.learn(str(r["content"])[:2000])
    except Exception:  # noqa: BLE001 – no history yet
        pass
    rt._predictor, rt._predictor_at = p, time.time()
    return p


# ------------------------------------------------------------------ (477) Moravian and Slovak words
DIALECT_PROMPT = ("Mluvčí může mluvit moravsky nebo slovensky: šak, šufánek, šlapky, rožni, zhasni, pocem, teho, temu, kerý, kaj, "
                  "kde, gde, čo, ako, hej, dobre, ďakujem, prosím ťa, zapni svetlo, vypni, kolko, zajtra.")


# ------------------------------------------------------------------ (480) errors a person understands
ERRORS = [
    (r"ConnectError|ConnectionError|Name or service not known|getaddrinfo|Temporary failure in name resolution",
     "Nejde se připojit k internetu nebo ke službě.", "Zkontroluj připojení; když jinde internet jde, služba má výpadek – zkus to za chvíli."),
    (r"Timeout|timed out|ReadTimeout", "Služba neodpověděla včas.", "Zkus to za chvíli znovu, případně v době menšího provozu."),
    (r"401|Unauthorized|invalid api key|Invalid authentication|forbidden|403", "Služba nepřijala klíč nebo přihlášení.",
     "V Nastavení → Propojení zkontroluj klíč (nevypršel?) a ulož ho znovu."),
    (r"429|rate limit|Too Many Requests|quota", "Služba hlásí, že je dotazů moc najednou nebo došel limit.",
     "Počkej pár minut, nebo v Nastavení → Mozek přepni na jiný mozek."),
    (r"PermissionError|Access is denied|Přístup byl odepřen|EACCES", "Na tohle nemám oprávnění.",
     "Soubor může mít otevřený jiný program, nebo je potřeba spustit JARVISe jako správce."),
    (r"FileNotFoundError|No such file|nenalezen", "Soubor nebo složka neexistuje.", "Zkontroluj cestu – nepřesunul se soubor?"),
    (r"No space left|disk full|ENOSPC", "Na disku došlo místo.", "Uvolni místo (řekni „ukliď disk“) a zkus to znovu."),
    (r"MemoryError|out of memory|CUDA out of memory", "Došla paměť.", "Zavři náročné programy, nebo použij menší model AI."),
    (r"5\d\d|Internal Server Error|Bad Gateway|Service Unavailable", "Služba má u sebe chybu.", "Není to tvoje chyba – zkus to později."),
    (r"JSONDecodeError|Expecting value|ValidationError", "Služba poslala odpověď, které nerozumím.",
     "Zkus to znovu; když to trvá, nahlas chybu (Diagnostika → Nahlásit)."),
]


def explain_error(e: BaseException | str) -> dict:
    raw = e if isinstance(e, str) else f"{type(e).__name__}: {e}"
    for pat, what, fix in ERRORS:
        if re.search(pat, raw, re.I):
            return {"what": what, "fix": fix}
    return {"what": "Něco se nepovedlo.", "fix": "Zkus to znovu. Když se to opakuje, řekni „zdraví JARVISe“ – ukážu, kde je problém."}


def error_text(e: BaseException | str) -> str:
    x = explain_error(e)
    return f"{x['what']} {x['fix']}"
