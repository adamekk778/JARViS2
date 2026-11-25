"""3.20 Učení+ (nápady 361–380 ze stránky „Nápady pro JARVISe“).

- ladička a metronom (361 – stránka /learn/tuner), slovíčko dne (362), konverzace v cizím jazyce s opravami (363)
- vysvětli jako dítěti (364), shrnutí videa z YouTube s časy (365 – titulky přes yt-dlp), hudební nauka (366)
- psaní všemi deseti (367 – stránka /learn/typing), šachy (368 – rozbor partie AI, bez šachového enginu)
- domácí úkol krok za krokem (369), cvičné otázky z pravidel silničního provozu (370 – oficiální testy jsou na etesty)
- citace podle ISO 690 (371), slepá mapa – hlavní města (372), čtenářský deník (373), rychločtení v notchi (374)
- čtení s dítětem (375), fakt dne (376), zpětná vazba ke slohu bez přepisování (377), peníze pro děti (378)
- dějepis v souvislostech (379), překlad slova při čtení (380 – označ slovo a zeptej se)
"""
from __future__ import annotations

import datetime as dt
import difflib
import html
import json
import logging
import math
import re
import time
import unicodedata
from typing import Any

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS ln_books (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, author TEXT, status TEXT, started TEXT, finished TEXT,
  rating INT, notes TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS ln_typing (ts REAL, wpm REAL, accuracy REAL);
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_learnx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._learnx_ready = True
    return rt.db


# ------------------------------------------------------------------ (361, 366) hudba
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "H"]
FLAT = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "B": "A#", "Hb": "A#", "Cb": "H", "Fb": "E", "Es": "D#", "As": "G#"}


def note_for_freq(freq: float, a4: float = 440.0) -> dict:
    """The nearest note to a frequency and how many cents off (for the tuner)."""
    if freq <= 0:
        raise ValueError("frekvence")
    n = 12 * math.log2(freq / a4) + 57                    # 57 = A4 counted from C0
    k = round(n)
    cents = round((n - k) * 100)
    return {"note": NOTES[k % 12], "octave": k // 12, "cents": cents, "in_tune": abs(cents) <= 5}


def freq_of(note: str, octave: int = 4, a4: float = 440.0) -> float:
    n = NOTES.index(FLAT.get(note, note)) + 12 * octave
    return round(a4 * 2 ** ((n - 57) / 12), 2)


SCALES = {"dur": [0, 2, 4, 5, 7, 9, 11], "major": [0, 2, 4, 5, 7, 9, 11], "moll": [0, 2, 3, 5, 7, 8, 10], "minor": [0, 2, 3, 5, 7, 8, 10],
          "pentatonika": [0, 3, 5, 7, 10], "blues": [0, 3, 5, 6, 7, 10], "harmonicka moll": [0, 2, 3, 5, 7, 8, 11]}
CHORDS = {"": [0, 4, 7], "m": [0, 3, 7], "7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11], "m7": [0, 3, 7, 10], "dim": [0, 3, 6], "aug": [0, 4, 8],
          "sus2": [0, 2, 7], "sus4": [0, 5, 7], "6": [0, 4, 7, 9], "9": [0, 4, 7, 10, 14], "add9": [0, 4, 7, 14]}


def _root(name: str) -> tuple[str, str]:
    m = re.match(r"([A-H][#b]?)(.*)", name.strip())
    if not m:
        raise ValueError("Akord napiš třeba Am7, F#m nebo Cmaj7.")
    root = FLAT.get(m.group(1), m.group(1))
    if root not in NOTES:
        raise ValueError("Neznám tón " + m.group(1))
    return root, m.group(2)


def chord_notes(name: str) -> list[str]:
    root, kind = _root(name)
    if kind not in CHORDS:
        raise ValueError("Typ akordu: " + ", ".join(k or "dur" for k in CHORDS))
    i = NOTES.index(root)
    return [NOTES[(i + s) % 12] for s in CHORDS[kind]]


def scale_notes(root: str, kind: str = "dur") -> list[str]:
    r, _ = _root(root)
    i = NOTES.index(r)
    return [NOTES[(i + s) % 12] for s in SCALES.get(fold(kind), SCALES["dur"])]


def chord_wav(notes: list[str], seconds: float = 1.6, rate: int = 22050) -> bytes:
    """A soft chord as a WAV (sine tones with a fade) to hear it."""
    import io
    import struct
    import wave

    freqs = [freq_of(n, 4 if i == 0 or NOTES.index(n) > NOTES.index(notes[0]) else 5) for i, n in enumerate(notes)]
    frames = bytearray()
    total = int(seconds * rate)
    for k in range(total):
        env = min(1.0, k / (0.02 * rate)) * (1 - k / total) ** 1.5
        v = sum(math.sin(2 * math.pi * f * k / rate) for f in freqs) / max(1, len(freqs))
        frames += struct.pack("<h", int(v * env * 12000))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


# ------------------------------------------------------------------ (362) slovíčko dne
WORDS = {
    "en": [("thorough", "důkladný", "She did a thorough job."), ("reliable", "spolehlivý", "My car is very reliable."),
           ("to postpone", "odložit", "Let's postpone the meeting."), ("eager", "dychtivý", "He is eager to learn."),
           ("to tackle", "pustit se do", "We need to tackle this problem."), ("convenient", "výhodný, pohodlný", "Is Monday convenient?"),
           ("to figure out", "přijít na", "I can't figure out the answer."), ("awkward", "trapný, nešikovný", "There was an awkward silence."),
           ("to overwhelm", "zahltit", "Don't let the work overwhelm you."), ("versatile", "všestranný", "A versatile tool."),
           ("to estimate", "odhadnout", "Can you estimate the cost?"), ("deadline", "termín", "The deadline is Friday."),
           ("to rely on", "spolehnout se na", "You can rely on me."), ("straightforward", "jednoduchý, přímočarý", "The answer is straightforward."),
           ("to apologize", "omluvit se", "I apologize for the delay."), ("sustainable", "udržitelný", "Sustainable energy."),
           ("to persuade", "přesvědčit", "She persuaded me to come."), ("occasionally", "občas", "I occasionally play chess."),
           ("to struggle", "zápasit, mít potíže", "I struggle with grammar."), ("insight", "vhled, postřeh", "A great insight.")],
    "de": [("die Erfahrung", "zkušenost", "Ich habe viel Erfahrung."), ("gemütlich", "útulný", "Ein gemütliches Café."),
           ("sich freuen auf", "těšit se na", "Ich freue mich auf das Wochenende."), ("die Ahnung", "tušení", "Keine Ahnung!"),
           ("erledigen", "vyřídit", "Ich muss noch etwas erledigen."), ("übrigens", "mimochodem", "Übrigens, wie geht's?"),
           ("die Rechnung", "účet", "Die Rechnung, bitte."), ("vorschlagen", "navrhnout", "Ich schlage vor, wir gehen."),
           ("pünktlich", "dochvilný", "Der Zug ist pünktlich."), ("die Gelegenheit", "příležitost", "Eine gute Gelegenheit.")],
}


def word_of_day(lang: str = "en", day: dt.date | None = None) -> dict:
    words = WORDS.get(lang, WORDS["en"])
    w = words[(day or dt.date.today()).toordinal() % len(words)]
    return {"word": w[0], "cs": w[1], "example": w[2], "lang": lang}


# ------------------------------------------------------------------ (363, 364, 369, 377, 379) režimy pro AI
def practice_rule(lang: str) -> str:
    name = {"en": "anglicky", "de": "německy", "es": "španělsky", "fr": "francouzsky", "it": "italsky"}.get(lang, lang)
    return (f"Konverzační trénink: mluv s uživatelem {name}, jednoduše a přirozeně, ptej se na jeho den a zájmy. Po každé jeho větě "
            f"s chybou nejdřív krátce napiš opravu ve formátu „✎ původně → správně (proč, česky)“ a pak pokračuj v rozhovoru {name}.")


ELI5_RULE = ("Vysvětli to jako desetiletému dítěti: krátké věty, žádný odborný žargon (nebo ho hned vysvětli), jeden obrázek ze "
             "života (přirovnání) a na konci jedna věta „Takže zkráceně:“.")
HOMEWORK_RULE = ("Pomáháš s domácím úkolem: NEPROZRAZUJ hned výsledek. Zeptej se, co už žák ví, a veď ho po malých krocích otázkami. "
                 "Když se zasekne, dej nápovědu, ne řešení. Výsledek ukaž, až ho žák sám napíše, nebo když o něj výslovně požádá po pokusu.")
ESSAY_RULE = ("Ohodnoť slohovou práci: co je dobře (2–3 věci), co zlepšit (obsah, stavba, styl, pravopis – s konkrétními místy z textu) "
              "a jednu radu na příště. NEPŘEPISUJ text za autora a nepiš novou verzi.")
HISTORY_RULE = ("Ukaž dějiny v souvislostech: co se v tom roce / období dělo v českých zemích, v Evropě a ve světě (věda, umění, "
                "politika), v krátkých odrážkách s letopočty, a jednu zajímavou souvislost mezi nimi.")


def ask_rule(kind: str) -> str:
    return {"eli5": ELI5_RULE, "homework": HOMEWORK_RULE, "essay": ESSAY_RULE, "history": HISTORY_RULE}.get(kind, "")


# ------------------------------------------------------------------ (365) shrnutí videa
def parse_vtt(text: str) -> list[tuple[int, str]]:
    """WebVTT subtitles → [(second, text)] without the duplicated rolling lines YouTube makes."""
    out: list[tuple[int, str]] = []
    cur = None
    for line in text.splitlines():
        m = re.match(r"(\d+):(\d{2}):(\d{2})[.,]\d+\s+-->", line) or re.match(r"(\d{2}):(\d{2})[.,]\d+\s+-->", line)
        if m:
            g = [int(x) for x in m.groups()]
            cur = g[0] * 3600 + g[1] * 60 + g[2] if len(g) == 3 else g[0] * 60 + g[1]
            continue
        t = re.sub(r"<[^>]+>", "", line).strip()
        if cur is None or not t or t == "WEBVTT" or "-->" in t or t.startswith(("Kind:", "Language:")):
            continue
        if out and (t == out[-1][1] or out[-1][1].endswith(t)):
            continue
        out.append((cur, html.unescape(t)))
    return out


def transcript_text(lines: list[tuple[int, str]], max_chars: int = 40_000) -> str:
    chunks, last = [], -999
    for s, t in lines:
        stamp = f"[{s // 60}:{s % 60:02d}] " if s - last >= 30 else ""
        last = s if stamp else last
        chunks.append(stamp + t)
    return " ".join(chunks)[:max_chars]


async def youtube_transcript(url: str, lang: str = "cs") -> list[tuple[int, str]]:
    import asyncio
    import os
    import tempfile

    if not re.match(r"https?://(www\.|m\.)?(youtube\.com|youtu\.be)/", url):
        raise ValueError("To není odkaz na YouTube.")
    with tempfile.TemporaryDirectory() as d:
        cmd = ["yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs", "--sub-langs", f"{lang},en,{lang}-orig,en-orig",
               "--sub-format", "vtt", "-o", os.path.join(d, "v"), url]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            await asyncio.wait_for(proc.wait(), 90)
        except asyncio.TimeoutError:
            proc.kill()
            raise
        files = sorted(f for f in os.listdir(d) if f.endswith(".vtt"))
        if not files:
            raise ValueError("Video nemá titulky – shrnout ho neumím.")
        pick = next((f for f in files if f".{lang}." in f), files[0])
        with open(os.path.join(d, pick), encoding="utf-8", errors="ignore") as fh:
            return parse_vtt(fh.read())


VIDEO_PROMPT = ("Shrň toto video podle přepisu česky: 5–10 hlavních bodů, u každého čas [mm:ss], kde se o tom mluví, a na konci jednu "
                "větu, pro koho video je. Přepis:\n")


# ------------------------------------------------------------------ (367) psaní, (374) rychločtení, (375) čtení s dítětem
TYPING_TEXTS = ["Příliš žluťoučký kůň úpěl ďábelské ódy.", "Na shledanou zítra ráno v devět hodin u hlavního vchodu.",
                "Programátor napsal krátký skript, který ušetřil celý den práce.", "V lese rostou houby, borůvky a maliny.",
                "Každý den trochu – a za měsíc píšeš o polovinu rychleji."]


def typing_score(target: str, typed: str, seconds: float) -> dict:
    sm = difflib.SequenceMatcher(None, target, typed)
    acc = round(sm.ratio() * 100, 1)
    words = len(typed) / 5
    wpm = round(words / (seconds / 60), 1) if seconds > 0 else 0
    return {"wpm": wpm, "accuracy": acc, "net_wpm": round(wpm * acc / 100, 1)}


def rsvp_words(text: str, wpm: int = 300) -> dict:
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    ms = round(60000 / max(100, min(1000, wpm)))
    return {"words": words[:3000], "ms": ms, "minutes": round(len(words) / max(100, wpm), 1)}


def reading_check(target: str, heard: str) -> dict:
    """The child read `target` aloud (STT gave `heard`): which words were missed or misread."""
    tw = [w for w in re.findall(r"\w+", fold(target))]
    hw = [w for w in re.findall(r"\w+", fold(heard))]
    sm = difflib.SequenceMatcher(None, tw, hw)
    hard = []
    for op, a1, a2, _b1, _b2 in sm.get_opcodes():
        if op in ("replace", "delete"):
            hard += tw[a1:a2]
    orig = re.findall(r"\w+", target)
    by_fold = {fold(w): w for w in orig}
    hard_orig = [by_fold.get(w, w) for w in hard]
    return {"ok": round(sm.ratio() * 100), "hard": list(dict.fromkeys(hard_orig))[:12]}


def syllables(word: str) -> str:
    """A rough Czech split into syllables to read a hard word slowly (vo-dy, ko-lo-běž-ka); "ch" is one sound."""
    vowels = set("aeiouyáéěíóúůý")
    w = word.lower()
    toks: list[str] = []
    i = 0
    while i < len(w):
        step = 2 if w[i:i + 2] == "ch" else 1
        toks.append(w[i:i + step])
        i += step
    vs = [k for k, t in enumerate(toks) if t[0] in vowels]
    cuts = [a + 1 if b - a - 1 <= 1 else a + 2 for a, b in zip(vs, vs[1:])]
    parts, prev = [], 0
    for c in cuts:
        parts.append("".join(toks[prev:c]))
        prev = c
    parts.append("".join(toks[prev:]))
    return "-".join(p for p in parts if p)


# ------------------------------------------------------------------ (370) autoškola
DRIVING_QA = [
    ("Jaká je nejvyšší povolená rychlost osobního auta v obci?", "50 km/h", ["30 km/h", "50 km/h", "60 km/h"],
     "V obci platí 50 km/h, pokud značka neříká jinak."),
    ("Jaká je nejvyšší povolená rychlost osobního auta mimo obec?", "90 km/h", ["80 km/h", "90 km/h", "110 km/h"],
     "Mimo obec 90 km/h, na dálnici a silnici pro motorová vozidla 130 km/h (v obci 80 km/h)."),
    ("Jaká je nejvyšší povolená rychlost na dálnici?", "130 km/h", ["120 km/h", "130 km/h", "150 km/h"], "Na dálnici 130 km/h."),
    ("Kolik alkoholu smí mít řidič v krvi?", "Žádný", ["0,2 promile", "0,5 promile", "Žádný"], "V Česku platí nulová tolerance."),
    ("Musí mít auto rozsvícená světla i ve dne?", "Ano, celoročně", ["Jen v zimě", "Ano, celoročně", "Jen mimo obec"],
     "Za jízdy svítí celoročně (potkávací nebo denní svícení)."),
    ("Do jaké výšky / hmotnosti musí dítě jezdit v autosedačce?", "Do 150 cm nebo 36 kg", ["Do 120 cm", "Do 150 cm nebo 36 kg", "Do 12 let"],
     "Dítě menší než 150 cm a lehčí než 36 kg musí být v zádržném systému."),
    ("Od kdy do kdy jsou povinné zimní pneumatiky při zimních podmínkách?", "1. 11. – 31. 3.", ["1. 10. – 30. 4.", "1. 11. – 31. 3.",
     "1. 12. – 28. 2."], "Od 1. listopadu do 31. března, když jsou na silnici zimní podmínky (nebo to značka přikazuje)."),
    ("Jaká je minimální hloubka dezénu letních pneumatik osobního auta?", "1,6 mm", ["1 mm", "1,6 mm", "3 mm"],
     "1,6 mm; zimní pneumatiky pro zimní provoz aspoň 4 mm."),
    ("Kdo má přednost na neoznačené křižovatce?", "Vozidlo zprava", ["Vozidlo zleva", "Vozidlo zprava", "Rychlejší vozidlo"],
     "Na křižovatce bez značek platí pravidlo pravé ruky."),
    ("Smí řidič za jízdy držet telefon v ruce?", "Ne", ["Ano, krátce", "Ne", "Jen na dálnici"], "Telefon v ruce za jízdy je zakázaný, i krátce."),
    ("Jaká je nejvyšší rychlost v obytné zóně?", "20 km/h", ["10 km/h", "20 km/h", "30 km/h"], "V obytné a pěší zóně max. 20 km/h."),
    ("Na jakou vzdálenost se za zatáčkou nebo za vrcholem stoupání staví výstražný trojúhelník mimo dálnici?", "Asi 50 m",
     ["Asi 10 m", "Asi 50 m", "Asi 300 m"], "Mimo dálnici zhruba 50 m za vozidlem, na dálnici 100 m."),
]


def driving_question(k: int) -> dict:
    q, a, opts, why = DRIVING_QA[k % len(DRIVING_QA)]
    return {"q": q, "options": opts, "answer": a, "why": why}


def driving_check(k: int, answer: str) -> tuple[bool, str]:
    q = driving_question(k)
    ok = fold(answer) == fold(q["answer"]) or (answer.strip().isdigit() and q["options"][int(answer) - 1] == q["answer"]
                                               if answer.strip().isdigit() and 0 < int(answer) <= len(q["options"]) else False)
    return ok, ("Správně! " if ok else f"Ne – správně je „{q['answer']}“. ") + q["why"] + " (Oficiální testy: etesty2.mdcr.cz)"


# ------------------------------------------------------------------ (371) ISO 690
def iso690(kind: str, authors: list[str], title: str, year: str = "", publisher: str = "", place: str = "", url: str = "",
           accessed: str = "", journal: str = "", volume: str = "", pages: str = "", isbn: str = "", edition: str = "") -> str:
    def name(a: str) -> str:
        parts = a.strip().split()
        return f"{parts[-1].upper()}, {' '.join(parts[:-1])}" if len(parts) > 1 else a.upper()

    who = "; ".join(name(a) for a in authors[:3]) + (" et al." if len(authors) > 3 else "")
    who = (who + ". ") if who else ""
    title = title.rstrip(".") if not title.endswith("..") else title
    if kind == "article":
        return f"{who}{title}. {journal}. {year}, {volume}" + (f", {pages}" if pages else "") + "." + (f" Dostupné z: {url}" if url else "")
    if kind == "web":
        acc = f" [cit. {accessed}]" if accessed else ""
        return f"{who}{title} [online]. {publisher + ', ' if publisher else ''}{year}{acc}. Dostupné z: {url}".replace(", .", ".")
    ed = f" {edition}. vyd." if edition else ""
    return (f"{who}{title}.{ed} {place + ': ' if place else ''}{publisher}{', ' if publisher and year else ''}{year}." +
            (f" ISBN {isbn}." if isbn else "")).replace("  ", " ")


# ------------------------------------------------------------------ (372) slepá mapa
CAPITALS = {"Česko": "Praha", "Slovensko": "Bratislava", "Polsko": "Varšava", "Německo": "Berlín", "Rakousko": "Vídeň", "Maďarsko": "Budapešť",
            "Slovinsko": "Lublaň", "Chorvatsko": "Záhřeb", "Itálie": "Řím", "Francie": "Paříž", "Španělsko": "Madrid", "Portugalsko": "Lisabon",
            "Spojené království": "Londýn", "Irsko": "Dublin", "Nizozemsko": "Amsterdam", "Belgie": "Brusel", "Lucembursko": "Lucemburk",
            "Švýcarsko": "Bern", "Dánsko": "Kodaň", "Norsko": "Oslo", "Švédsko": "Stockholm", "Finsko": "Helsinky", "Estonsko": "Tallinn",
            "Lotyšsko": "Riga", "Litva": "Vilnius", "Ukrajina": "Kyjev", "Rumunsko": "Bukurešť", "Bulharsko": "Sofie", "Srbsko": "Bělehrad",
            "Bosna a Hercegovina": "Sarajevo", "Černá Hora": "Podgorica", "Albánie": "Tirana", "Severní Makedonie": "Skopje",
            "Řecko": "Atény", "Turecko": "Ankara", "Island": "Reykjavík", "Moldavsko": "Kišiněv", "Bělorusko": "Minsk", "Malta": "Valletta",
            "Kypr": "Nikósie"}


def capital_question(k: int) -> tuple[str, str]:
    items = sorted(CAPITALS.items())
    country, cap = items[k % len(items)]
    return country, cap


def capital_check(country: str, answer: str) -> tuple[bool, str]:
    cap = CAPITALS.get(country, "")
    ok = bool(cap) and (fold(answer) == fold(cap) or difflib.SequenceMatcher(None, fold(answer), fold(cap)).ratio() >= 0.85)
    return ok, ("Správně!" if ok else f"Ne, hlavní město {country} je {cap}.")


# ------------------------------------------------------------------ (373) čtenářský deník
def book_add(rt: Any, title: str, author: str = "", status: str = "čtu") -> int:
    cur = db(rt).exec("INSERT INTO ln_books (title, author, status, started) VALUES (?,?,?,?)", (title[:120], author[:80], status,
                                                                                                  dt.date.today().isoformat()))
    return int(getattr(cur, "lastrowid", 0) or 0)


def book_find(rt: Any, title: str) -> dict | None:
    f = fold(title)
    return next((dict(r) for r in db(rt).all("SELECT * FROM ln_books ORDER BY id DESC") if f in fold(r["title"])), None)


def book_note(rt: Any, title: str, text: str, quote: bool = False) -> bool:
    b = book_find(rt, title)
    if not b:
        return False
    notes = json.loads(b["notes"] or "[]") + [{"text": text[:500], "quote": quote, "ts": time.time()}]
    db(rt).exec("UPDATE ln_books SET notes=? WHERE id=?", (json.dumps(notes, ensure_ascii=False), b["id"]))
    return True


def book_done(rt: Any, title: str, rating: int = 0) -> bool:
    b = book_find(rt, title)
    if not b:
        return False
    db(rt).exec("UPDATE ln_books SET status='přečteno', finished=?, rating=? WHERE id=?", (dt.date.today().isoformat(), int(rating), b["id"]))
    return True


# ------------------------------------------------------------------ (378) peníze pro děti
MONEY_LESSONS = [
    ("Potřeba, nebo přání?", "Potřeba je to, bez čeho se neobejdeš (jídlo, boty). Přání je hezké, ale počká (nová hra). Než něco koupíš, zeptej se: potřebuju to, nebo to jen chci?"),
    ("Spoření", "Když si odložíš kousek kapesného každý týden, za pár týdnů máš na větší věc. Zkus si určit cíl a nakreslit ho."),
    ("Cena a hodnota", "Dražší neznamená lepší. Porovnej dvě věci – co umí, jak dlouho vydrží a kolik stojí."),
    ("Úrok", "Když dáš peníze do banky, banka ti přidá malou odměnu – úrok. Když si půjčíš, platíš úrok ty."),
    ("Reklama", "Reklama chce, abys něco chtěl. Počkej den – jestli to pořád chceš, je to dobré znamení."),
    ("Rozpočet", "Rozděl kapesné na tři hromádky: utratit, ušetřit, darovat. Kolik dáš kam, je na tobě."),
    ("Karty a internet", "Kartou platíš skutečné peníze. Na internetu nikdy nezadávej údaje z karty bez rodičů."),
]


def money_lesson(k: int) -> dict:
    t, body = MONEY_LESSONS[k % len(MONEY_LESSONS)]
    return {"title": t, "text": body, "n": k % len(MONEY_LESSONS) + 1, "of": len(MONEY_LESSONS)}


# ------------------------------------------------------------------ (361, 367) the practice pages
def tuner_page() -> str:
    return """<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Ladička a metronom</title>
<style>body{font:16px system-ui;background:#0b0f14;color:#e8eef5;text-align:center;margin:24px}#note{font-size:72px;font-weight:800}
#cents{font-size:20px}button{font:inherit;padding:10px 18px;border-radius:10px;border:0;background:#4fc3ff;margin:6px}.ok{color:#30d158}</style>
<h1>Ladička</h1><div id=note>–</div><div id=cents>Pusť mikrofon</div><button id=go>Ladit</button>
<h1>Metronom</h1><input id=bpm type=range min=30 max=240 value=90><div><b id=bv>90</b> BPM</div><button id=met>Start</button>
<script>
const N=["C","C#","D","D#","E","F","F#","G","G#","A","A#","H"];
function pitch(buf,rate){let best=-1,bc=0;for(let lag=Math.floor(rate/1000);lag<Math.floor(rate/60);lag++){let c=0;for(let i=0;i<buf.length-lag;i++)c+=buf[i]*buf[i+lag];if(c>bc){bc=c;best=lag}}return best>0?rate/best:0}
go.onclick=async()=>{const s=await navigator.mediaDevices.getUserMedia({audio:true});const ac=new AudioContext();const an=ac.createAnalyser();an.fftSize=4096;ac.createMediaStreamSource(s).connect(an);const b=new Float32Array(an.fftSize);
(function loop(){an.getFloatTimeDomainData(b);let r=0;for(const v of b)r+=v*v;if(Math.sqrt(r/b.length)>0.01){const f=pitch(b,ac.sampleRate);if(f){const n=12*Math.log2(f/440)+57,k=Math.round(n),c=Math.round((n-k)*100);note.textContent=N[(k%12+12)%12]+Math.floor(k/12);cents.textContent=(c>0?"+":"")+c+" centů";cents.className=Math.abs(c)<=5?"ok":""}}requestAnimationFrame(loop)})()};
let t=0,ac2;bpm.oninput=()=>bv.textContent=bpm.value;met.onclick=()=>{if(t){clearInterval(t);t=0;met.textContent="Start";return}ac2=ac2||new AudioContext();let k=0;const tick=()=>{const o=ac2.createOscillator(),g=ac2.createGain();o.frequency.value=k++%4?880:1320;g.gain.setValueAtTime(.3,ac2.currentTime);g.gain.exponentialRampToValueAtTime(.001,ac2.currentTime+.08);o.connect(g).connect(ac2.destination);o.start();o.stop(ac2.currentTime+.09)};tick();t=setInterval(tick,60000/bpm.value);met.textContent="Stop"};
</script>"""


def typing_page() -> str:
    texts = json.dumps(TYPING_TEXTS, ensure_ascii=False)
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Psaní všemi deseti</title>
<style>body{{font:18px system-ui;background:#0b0f14;color:#e8eef5;margin:24px;max-width:760px}}#t{{font-size:24px;line-height:1.5}}
#t .ok{{color:#30d158}}#t .bad{{color:#ff453a;text-decoration:underline}}textarea{{width:100%;font:inherit;padding:10px;border-radius:10px}}</style>
<h1>Psaní všemi deseti</h1><p>Prsty na F a J, piš bez dívání na klávesnici.</p><div id=t></div><textarea id=i rows=3></textarea><p id=r></p>
<script>const T={texts};let k=0,start=0;function show(){{const s=T[k%T.length],v=i.value;t.innerHTML=[...s].map((c,j)=>`<span class="${{j<v.length?(v[j]===c?'ok':'bad'):''}}">${{c.replace(/&/g,'&amp;').replace(/</g,'&lt;')}}</span>`).join("")}}
i.oninput=()=>{{if(!start)start=Date.now();show();const s=T[k%T.length];if(i.value.length>=s.length){{const sec=(Date.now()-start)/1000;let ok=0;for(let j=0;j<s.length;j++)if(i.value[j]===s[j])ok++;const acc=Math.round(ok/s.length*100),wpm=Math.round(i.value.length/5/(sec/60));r.textContent=`${{wpm}} slov/min, přesnost ${{acc}} %`;fetch("/api/learn/typing",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify({{wpm,accuracy:acc}})}}).catch(()=>{{}});k++;i.value="";start=0;show()}}}};show();</script>"""


# ------------------------------------------------------------------ the daily look
async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    from .proactiveplus import due_today

    now = now or dt.datetime.now()
    said: list[str] = []
    c = getattr(rt.cfg, "learnx", None)
    if c is None:
        return said
    if c.word_of_day and due_today(rt, "ln_word", "08:30", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("ln_word", now.date().isoformat()))
        w = word_of_day(c.word_of_day, now.date())
        t = f"{w['word']} = {w['cs']}. {w['example']}"
        rt.notify("Slovíčko dne", t, speak=False)
        said.append(t)
    if c.fact_topic and due_today(rt, "ln_fact", "19:30", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("ln_fact", now.date().isoformat()))
        try:
            out = await rt.router.complete([{"role": "user", "content": f"Napiš jednu ověřitelnou zajímavost z oboru „{c.fact_topic}“ "
                                             "česky ve 2 větách. Bez úvodu. Když si nejsi jistý fakty, vyber známější zajímavost."}], fast=True)
            if out:
                rt.notify("Fakt dne", str(out).strip()[:400], speak=False)
                said.append(str(out).strip())
        except Exception as e:  # noqa: BLE001
            log.debug("fact of the day: %s", e)
    return said
