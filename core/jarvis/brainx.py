"""3.20 Mozek+ (nápady 21–40 ze stránky „Nápady pro JARVISe“).

- hloubka přemýšlení podle rizika: peníze, mazání, odesílání, zdraví, právo → důkladněji (21)
- „promysli to důkladně“: hlubší přemýšlení a viditelný postup (22)
- jistota v procentech u faktů z internetu – podle počtu a druhu zdrojů (23)
- tvůj styl psaní z odeslané pošty (24), slovník tvých zkratek (25)
- vlastní malý model: příklady z tvých povelů zapečené do místního modelu Ollama (26)
- kontrola po dokončení delšího úkolu (27), přepočítání čísel v odpovědi (28)
- plán ke schválení před velkým úkolem (29), styl odpovědí včetně „jako učitel“ (30)
- kontext z obrazovky u otázek „co to je / oprav tohle“ (31), úkoly na noc levnějším mozkem (32)
- „proč jsi to udělal“ ke každému kroku (33), hned krátce a pak přesněji (34)
- rozpočet AI zvlášť pro práci a pro hraní (35), režim učitele (36), poctivé „nevím“ (37)
- odhad doby úkolu (38), co se JARVIS za týden naučil (39), kreativní režim (40)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import statistics
import time
import unicodedata
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def _kv_get(rt: Any, key: str, default: Any = None) -> Any:
    rt.db.exec("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    r = rt.db.one("SELECT v FROM kv WHERE k=?", (key,))
    if not r:
        return default
    try:
        return json.loads(r["v"])
    except (TypeError, ValueError):
        return default


def _kv_set(rt: Any, key: str, value: Any) -> None:
    rt.db.exec("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))


# ------------------------------------------------------------------ (21) hloubka podle rizika, (22) důkladně
RISK = re.compile(r"\b(zaplat\w*|plat\w*|prevod\w*|posli\w* penize|kup\w*|objednej|rezerv\w*|smaz\w*|vymaz\w*|odstran\w*|"
                  r"zformatuj|preinstaluj|odesl\w*|posli\w*( e-?mail| zpravu)?|odpovez\w*|podepis\w*|vypovez\w*|smlouv\w*|"
                  r"zalob\w*|soud\w*|danov\w*|dan[ei]?\b|lek\w*|davk\w*|diagnoz\w*|investuj\w*|prodej\w*|akci[ei]?\b)\b")
DEEP = re.compile(r"\b(promysli|zamysli se|rozmysli)\w*\b.*\b(dukladne|poradne|do hloubky|peclive)\b|\bkrok za krokem\b|"
                  r"\b(dukladne|do hloubky) (promysli|zvaz|analyzuj|rozeber)\w*\b")
STEPS_RULE = ("Uživatel chce důkladné promyšlení: nejdřív napiš stručný očíslovaný postup, jak jsi uvažoval („Postup: 1. … 2. …“), "
              "potom výsledek. Postup drž krátký – jen kroky, které vedly k závěru.")


def risky_action(text: str) -> bool:
    return bool(RISK.search(fold(text)))


def deep_request(text: str) -> bool:
    return bool(DEEP.search(fold(text)))


# ------------------------------------------------------------------ (23) jistota
TRUSTED = ("gov.cz", ".gov", "europa.eu", "wikipedia.org", "ct24.cz", "irozhlas.cz", "ceskatelevize.cz", "ctk.cz",
           "reuters.com", "apnews.com", "bbc.", "cnb.cz", "czso.cz", "who.int", "nature.com", "mzv.cz", "mvcr.cz")
CONF_RULE = ("Když odpověď stojí na faktech z internetu, zakonči ji řádkem „Jistota: NN % – proč“ (kolik zdrojů se shoduje, "
             "jak jsou spolehlivé a čerstvé). Když si nejsi jistý, řekni to otevřeně.")


def _domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return (m.group(1) if m else url or "").lower().removeprefix("www.")


def confidence(sources: list[dict | str], verified: bool | None = None) -> tuple[int, str]:
    """(percent, why) from the sources an answer used: more independent sites and reliable ones → higher."""
    doms = []
    for s in sources or []:
        u = s.get("url", "") if isinstance(s, dict) else str(s)
        d = _domain(u)
        if d and d not in doms:
            doms.append(d)
    if not doms:
        return 0, ""
    n = len(doms)
    pct = 60 if n == 1 else 75 if n == 2 else 85
    good = [d for d in doms if any(t in d for t in TRUSTED)]
    if good:
        pct += 5
    if verified is True:
        pct += 5
    elif verified is False:
        pct -= 20
    pct = max(20, min(95, pct))
    why = f"{n} {'zdroj' if n == 1 else 'zdroje' if n < 5 else 'zdrojů'}"
    if good:
        why += f", z toho spolehlivé: {', '.join(good[:2])}"
    if n == 1:
        why += "; jen jeden zdroj, ověř si to"
    return pct, why


def confidence_line(answer: str, sources: list) -> str:
    if not sources or re.search(r"\bjistota\b", fold(answer)):
        return ""
    pct, why = confidence(sources)
    return f"\n\nJistota: {pct} % – {why}." if pct else ""


# ------------------------------------------------------------------ (24) tvůj styl psaní
GREET = re.compile(r"^(dobry den|dobre rano|ahoj|cau|zdravim|vazen\w+ \w+|hezky den|mily \w+|mila \w+|hi|hello|dear \w+)", re.M)
SIGN = re.compile(r"(s pozdravem|s pratelskym pozdravem|diky|dekuji|hezky den|mej se|zdravim|pa\b|regards|best)[^\n]{0,40}$", re.M)


def style_profile(texts: list[str]) -> dict:
    """How you write: greeting, sign-off, vykání / tykání, sentence length, emoji – from your own e-mails or messages."""
    texts = [t for t in texts if t and len(t.strip()) > 20][:80]
    if not texts:
        return {}
    greets: dict[str, int] = {}
    signs: dict[str, int] = {}
    vy = ty = emoji = 0
    lens: list[int] = []
    for t in texts:
        f = fold(t)
        g = GREET.search(f)
        if g:
            greets[g.group(1)] = greets.get(g.group(1), 0) + 1
        s = SIGN.search(f)
        if s:
            signs[s.group(1)] = signs.get(s.group(1), 0) + 1
        vy += len(re.findall(r"\b(vam|vas|vami|jste|muzete|budete|mate|prosim vas)\b", f))
        ty += len(re.findall(r"\b(tobe|tebe|tebou|jsi|muzes|budes|mas|prosim te)\b", f))
        emoji += len(re.findall(r"[\U0001F300-\U0001FAFF☀-➿]", t))
        lens += [len(x.split()) for x in re.split(r"[.!?]\s", t) if x.strip()]
    top = lambda d: max(d, key=d.get) if d else ""   # noqa: E731
    return {"greeting": top(greets), "sign_off": top(signs), "address": "vykání" if vy >= ty else "tykání",
            "sentence_words": round(statistics.median(lens)) if lens else 0, "emoji": emoji / max(1, len(texts)) > 0.3,
            "samples": len(texts)}


def style_prompt(p: dict) -> str:
    if not p:
        return ""
    bits = [f"oslovení „{p['greeting']}“" if p.get("greeting") else "", f"rozloučení „{p['sign_off']}“" if p.get("sign_off") else "",
            p.get("address", ""), f"věty kolem {p['sentence_words']} slov" if p.get("sentence_words") else "",
            "občas emoji" if p.get("emoji") else "bez emoji"]
    return "Když píšeš e-mail nebo zprávu jménem uživatele, piš jeho stylem: " + ", ".join(b for b in bits if b) + "."


WRITES = re.compile(r"\b(napis|odpovez|odepis|posli|koncept|navrhni)\w*\b.*\b(e-?mail\w*|mail\w*|zprav\w*|odpoved\w*|dopis\w*)\b")


# ------------------------------------------------------------------ (25) slovník zkratek
COMMON_ABBR = {"PC", "AI", "USB", "OK", "PDF", "DPH", "IČO", "IC", "DIC", "CZ", "EU", "USA", "GPS", "SMS", "TV", "HDMI", "CPU",
               "GPU", "RAM", "SSD", "HDD", "WIFI", "IT", "HR", "CEO", "API", "URL", "QR", "LED", "DIY", "MHD", "ČR", "SK", "PS"}


def glossary(rt: Any) -> dict[str, str]:
    return dict(_kv_get(rt, "glossary", {}) or {})


def glossary_add(rt: Any, term: str, meaning: str) -> dict[str, str]:
    g = glossary(rt)
    term, meaning = term.strip(), meaning.strip()
    if not term or not meaning:
        raise ValueError("Potřebuju zkratku i co znamená.")
    g[term] = meaning
    _kv_set(rt, "glossary", g)
    return g


def glossary_remove(rt: Any, term: str) -> bool:
    g = glossary(rt)
    hit = next((k for k in g if k.lower() == term.strip().lower()), None)
    if hit is None:
        return False
    g.pop(hit)
    _kv_set(rt, "glossary", g)
    return True


def unknown_abbreviations(rt: Any, text: str) -> list[str]:
    g = {k.upper() for k in glossary(rt)}
    out = []
    for w in re.findall(r"\b[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]{2,6}\b", text or ""):
        if w not in COMMON_ABBR and w not in g and w not in out:
            out.append(w)
    return out


def glossary_prompt(rt: Any, text: str) -> str:
    g = glossary(rt)
    if not g:
        return ""
    f = fold(text)
    used = {k: v for k, v in g.items() if fold(k) in f} or dict(list(g.items())[:25])
    return "Uživatelovy zkratky a přezdívky: " + "; ".join(f"{k} = {v}" for k, v in used.items()) + "."


# ------------------------------------------------------------------ (26) vlastní malý model
def reflex_examples(rt: Any, limit: int = 60) -> list[dict]:
    """Your commands that went well at least twice (from the tool memory): phrase → tool + arguments."""
    try:
        rows = rt.db.all("SELECT phrase, tool, args, ok, bad FROM tool_memory WHERE ok >= 2 AND bad = 0 ORDER BY ok DESC, last DESC LIMIT ?",
                         (limit,))
    except Exception:  # noqa: BLE001 – no tool memory yet
        return []
    return [{"phrase": r["phrase"], "tool": r["tool"], "args": json.loads(r["args"] or "{}")} for r in rows]


def modelfile(base: str, examples: list[dict]) -> str:
    """An Ollama Modelfile: the base model with your own commands as worked examples (fast, offline, no training)."""
    sysmsg = ("Jsi rychlý rozhodovač povelů JARVISe. Na krátký český povel odpověz JEN JSON {\"tool\": jméno, \"args\": {…}, "
              "\"conf\": 0–1}. Když si nejsi jistý, conf dej nízko.")
    lines = [f"FROM {base}", "PARAMETER temperature 0", f'SYSTEM """{sysmsg}"""']
    for e in examples:
        out = json.dumps({"tool": e["tool"], "args": e["args"], "conf": 0.95}, ensure_ascii=False)
        lines.append(f'MESSAGE user """{e["phrase"]}"""')
        lines.append(f'MESSAGE assistant """{out}"""')
    return "\n".join(lines) + "\n"


def write_modelfile(rt: Any, base: str) -> tuple[Path, int]:
    from .paths import data_dir

    ex = reflex_examples(rt)
    if len(ex) < 5:
        raise ValueError(f"Mám zatím jen {len(ex)} ověřených povelů – potřebuju aspoň 5 (každý povel, který dvakrát dobře dopadl).")
    p = data_dir() / "models" / "jarvis-reflex.Modelfile"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(modelfile(base, ex), encoding="utf-8")
    return p, len(ex)


# ------------------------------------------------------------------ (27) kontrola po dokončení
CHECK_PROMPT = ("Jsi kontrola kvality. Dostaneš zadání uživatele, kroky, které JARVIS udělal, a jeho odpověď. Odpovídá výsledek "
                "zadání? Odpověz JSON {\"ok\": true/false, \"why\": \"krátce česky, co chybí nebo nesedí\"}.")


async def after_check(rt: Any, goal: str, cards: list[dict], answer: str, timeout: float = 20.0) -> dict | None:
    """A second look after a longer task (3+ steps): does the result match what was asked?"""
    import asyncio

    if len(cards) < 3:
        return None
    steps = "\n".join(f"- {c.get('tool', c.get('name', ''))}: {'OK' if c.get('ok') else 'CHYBA'} – {str(c.get('summary', ''))[:160]}"
                      for c in cards[:15])
    try:
        out = await asyncio.wait_for(rt.router.complete([
            {"role": "system", "content": CHECK_PROMPT},
            {"role": "user", "content": f"Zadání: {goal[:800]}\n\nKroky:\n{steps}\n\nOdpověď: {answer[:1500]}"}], fast=True), timeout)
    except Exception as e:  # noqa: BLE001
        log.debug("after check: %s", e)
        return None
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        r = json.loads(m.group(0)) if m else {}
    except ValueError:
        return None
    return {"ok": bool(r.get("ok", True)), "why": str(r.get("why", ""))[:300]}


# ------------------------------------------------------------------ (28) přepočítání čísel
_NUM = r"-?\d[\d\s ]*(?:[.,]\d+)?"
ARITH = re.compile(rf"(?<![\w.,])({_NUM})\s*([+\-−×x*·/:÷])\s*({_NUM})\s*=\s*({_NUM})(?![\d])")
PCT = re.compile(rf"(?<![\w.,])({_NUM})\s*%\s*z\s*({_NUM})\s*(?:je|jsou|=|činí|dělá)\s*({_NUM})")


def _n(s: str) -> float:
    return float(re.sub(r"[\s ]", "", s).replace(",", "."))


def _show(x: float) -> str:
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x)):,}".replace(",", " ")
    return f"{x:,.2f}".replace(",", " ").replace(".", ",").rstrip("0").rstrip(",")


def check_numbers(text: str) -> list[str]:
    """Simple calculations written in the answer, recomputed: the wrong ones with the right result."""
    fixes = []
    for m in ARITH.finditer(text or ""):
        a, op, b, c = _n(m.group(1)), m.group(2), _n(m.group(3)), _n(m.group(4))
        if op in "+":
            r = a + b
        elif op in "-−":
            r = a - b
        elif op in "×x*·":
            r = a * b
        else:
            if b == 0:
                continue
            r = a / b
        if abs(r - c) > max(0.01, abs(r) * 0.005):
            fixes.append(f"{m.group(1).strip()} {op} {m.group(3).strip()} = {_show(r)} (ne {m.group(4).strip()})")
    for m in PCT.finditer(text or ""):
        p, base, c = _n(m.group(1)), _n(m.group(2)), _n(m.group(3))
        r = p / 100 * base
        if abs(r - c) > max(0.01, abs(r) * 0.005):
            fixes.append(f"{m.group(1).strip()} % z {m.group(2).strip()} je {_show(r)} (ne {m.group(3).strip()})")
    return fixes


def numbers_line(text: str) -> str:
    fixes = check_numbers(text)
    return ("\n\nOprava výpočtu (přepočítáno kalkulačkou): " + "; ".join(fixes) + ".") if fixes else ""


# ------------------------------------------------------------------ (29) plán ke schválení
PLAN_PROMPT = ("Uživatel zadal větší úkol. Napiš jen plán: 3–8 očíslovaných kroků, každý jednou krátkou větou, česky. "
               "Nic nedělej, nevysvětluj, jen kroky.")
BIG = re.compile(r"\b(a pak|a potom|potom|nakonec|zaroven|kazd\w+|vsechn\w+|projdi|zpracuj|priprav|uspořadej|usporadej|udelej mi|"
                 r"naplanuj|zorganizuj|preved|presun|prejmenuj vse|vytvor projekt)\b")


def needs_plan(rt: Any, text: str, tier: str = "") -> bool:
    if not getattr(rt.cfg.agent, "plan_first", False):
        return False
    w = fold(text)
    return (len(w.split()) >= 18 and len(BIG.findall(w)) >= 2) or (tier == "strong" and len(w.split()) >= 25)


async def make_plan(rt: Any, text: str) -> list[str]:
    out = await rt.router.complete([{"role": "system", "content": PLAN_PROMPT}, {"role": "user", "content": text[:2000]}])
    steps = [re.sub(r"^\s*\d+[.)]\s*", "", ln).strip() for ln in (out or "").splitlines() if re.match(r"^\s*\d+[.)]", ln)]
    return [s for s in steps if s][:8]


# ------------------------------------------------------------------ (30) styl odpovědí, (36) režim učitele, (37) nevím
STYLES = {
    "brief": "Odpovídej co nejstručněji – jedna až dvě věty, jen podstata.",
    "normal": "",
    "detailed": "Odpovídej podrobně: souvislosti, příklady a na konci krátké shrnutí.",
    "teacher": "Odpovídej jako trpělivý učitel: vysvětli od základů, krok za krokem, s jednoduchým příkladem, a na konci se zeptej, "
               "jestli je to jasné.",
}
STYLE_WORDS = {"brief": r"strucn\w*|kratc\w*|kratce|jednou vetou", "detailed": r"podrobn\w*|detailn\w*|obsahl\w*",
               "teacher": r"jako ucitel\w*|jako pro zacatecnik\w*|vysvetlujic\w*", "normal": r"normaln\w*|bezn\w*|jako obvykle"}


def style_from_words(text: str) -> str:
    w = fold(text)
    if not re.search(r"\b(odpovidej|mluv|pis|vysvetluj|bud|odpovez)\w*\b", w):
        return ""
    for k, rx in STYLE_WORDS.items():
        if re.search(rf"\b({rx})\b", w):
            return k
    return ""


TEACH = re.compile(r"\b(nauc|ukaz)\w* (me|mi)\b.*\b(jak|sam|sama|sami)\b|\bjak (to )?(mam|muzu|udelam) (udelat )?sam\b|"
                   r"\bchci (se )?(to )?(naucit|zvladnout) sam\b|\bnedelej to za me\b")
TEACH_RULE = ("Režim učitele: nic nedělej za uživatele (žádné akce, jen čtení). Vysvětli mu krok za krokem, jak to udělá sám – "
              "přesná tlačítka, menu a klávesové zkratky, s ověřením na konci.")
HONEST_RULE = ("Když něco nevíš jistě, nevymýšlej si: řekni „nevím jistě“, napiš, co by bylo potřeba zjistit, a nabídni, že to "
               "dohledáš.")


def teach_request(text: str) -> bool:
    return bool(TEACH.search(fold(text)))


# ------------------------------------------------------------------ (31) kontext z obrazovky
DEICTIC = re.compile(r"^(co (to|tohle|tamto) (je|znamena|tady pise|rika)|co je (to|tohle) za|co s tim|oprav (to|tohle)|"
                     r"prelož? (to|tohle)|preloz (to|tohle)|vysvetli (to|tohle|mi to)|je to spravne|proc (to|tohle) nefunguje|"
                     r"jak (to|tohle) (opravim|vyresim|nastavim)|co mi tu chybi|co tady mam delat)\b")


def wants_screen(rt: Any, text: str, attachments: list | None) -> bool:
    if attachments or not getattr(rt.cfg.brain, "screen_context", True):
        return False
    perms = getattr(rt.cfg, "permissions", None)
    if perms is not None and not getattr(perms, "screen", True):
        return False
    w = fold(text).strip(" ?!.")
    m = DEICTIC.search(w)
    if not m:
        return False
    rest = [x for x in re.split(r"[\s,]+", w[m.end():]) if x]
    return all(x in SCREEN_WORDS for x in rest)


SCREEN_WORDS = {"za", "tady", "tu", "tam", "na", "obrazovce", "obrazovka", "chyba", "chybu", "hlaska", "hlasku", "okno", "okne",
                "tohle", "to", "prosim", "mi", "me", "ted", "tim", "s", "vlastne", "jarvisi", "jarvis"}


async def screen_attachment(rt: Any) -> str | None:
    """The active window's picture as an attachment (only in this message)."""
    import asyncio

    try:
        png = await asyncio.to_thread(rt.platform.screenshot)
    except Exception as e:  # noqa: BLE001
        log.debug("screen context: %s", e)
        return None
    if not png:
        return None
    try:
        att = await rt.store.save("obrazovka.png", png, "image/png")
    except Exception as e:  # noqa: BLE001
        log.debug("screen context save: %s", e)
        return None
    return getattr(att, "id", None)


# ------------------------------------------------------------------ (32) úkoly na noc
NIGHT = re.compile(r"\b(v noci|pres noc|az budu spat|do rana|nespecha|az bude cas)\b")


def night_time(rt: Any, now: dt.datetime | None = None) -> dt.datetime:
    h = int(getattr(rt.cfg.brain, "night_hour", 2) or 2)
    now = now or dt.datetime.now()
    at = now.replace(hour=h, minute=0, second=0, microsecond=0)
    return at if at > now else at + dt.timedelta(days=1)


def queue_night(rt: Any, goal: str, now: dt.datetime | None = None) -> dict:
    goal = re.sub(r"\b(v noci|přes noc|pres noc|až budu spát|az budu spat|do rána|do rana|nespěchá|nespecha|až bude čas|az bude cas)\b",
                  " ", goal, flags=re.I)
    goal = " ".join(goal.split()).strip(" ,.")
    at = night_time(rt, now)
    return rt.scheduler.add_once(at, "prompt", {"prompt": goal, "cheap": True}, title=f"V noci: {goal[:60]}")


def cheap_provider(rt: Any) -> str:
    """The cheapest brain for work nobody waits for: the easy one of chytré rozdělení, else the AI on this PC."""
    easy = getattr(rt.cfg.brain, "split_easy", "")
    if easy:
        return easy
    try:
        from .brainplus import local_provider

        return local_provider(rt) or ""
    except Exception:  # noqa: BLE001
        return ""


# ------------------------------------------------------------------ (33) proč
def log_why(rt: Any, tool: str, args: dict, reason: str) -> None:
    rt.db.exec("CREATE TABLE IF NOT EXISTS why_log (ts REAL, tool TEXT, args TEXT, reason TEXT)")
    rt.db.exec("INSERT INTO why_log VALUES (?,?,?,?)", (time.time(), tool, json.dumps(args, ensure_ascii=False)[:400],
                                                        (reason or "").strip()[:400]))
    rt.db.exec("DELETE FROM why_log WHERE ts < ?", (time.time() - 30 * 86400,))


def why_last(rt: Any, n: int = 5) -> list[dict]:
    rt.db.exec("CREATE TABLE IF NOT EXISTS why_log (ts REAL, tool TEXT, args TEXT, reason TEXT)")
    return [dict(r) for r in rt.db.all("SELECT * FROM why_log ORDER BY ts DESC LIMIT ?", (n,))]


WHY = re.compile(r"^(proc|z jakeho duvodu|jak to) (jsi|si|ses) (to )?(udelal|provedl|zvolil|spustil|pustil|otevrel|smazal|poslal)\w*"
                 r"|^proc (zrovna )?(tohle|to)$|^vysvetli (mi )?proc\b")


def why_text(rt: Any) -> str:
    rows = why_last(rt, 4)
    if not rows:
        return "Teď jsem neudělal nic, co bych musel vysvětlovat."
    from .tools.base import REGISTRY

    out = []
    for r in reversed(rows):
        spec = REGISTRY.get(r["tool"])
        what = spec.description.split(".")[0] if spec else r["tool"]
        out.append(f"{what[:80]}: {r['reason'] or 'tak to vyplynulo z tvého požadavku'}")
    return "Udělal jsem: " + " | ".join(out)


# ------------------------------------------------------------------ (35) rozpočet podle činnosti
def context_now(rt: Any) -> str:
    """game / work / other – what you are doing now (a running game, work hours with a work app in front)."""
    try:
        att = getattr(rt, "attention", None)
        if att is not None and getattr(att, "game", None):
            return "game"
    except Exception:  # noqa: BLE001
        pass
    try:
        front = (rt.platform.foreground_info() or {}).get("app", "").lower()
    except Exception:  # noqa: BLE001
        front = ""
    if any(g in front for g in ("steam", "valorant", "cs2", "league", "minecraft", "roblox", "fortnite", "epicgames", "battle.net")):
        return "game"
    if any(w in front for w in ("outlook", "teams", "excel", "winword", "word", "powerpnt", "code", "slack", "zoom", "pycharm", "idea")):
        return "work"
    h = dt.datetime.now()
    if h.weekday() < 5 and 8 <= h.hour < 17:
        return "work"
    return "other"


def spend_today(rt: Any, ctx: str) -> float:
    d = _kv_get(rt, f"ctx_spend_{dt.date.today().isoformat()}", {}) or {}
    return float(d.get(ctx, 0.0))


def add_spend(rt: Any, ctx: str, czk: float) -> None:
    key = f"ctx_spend_{dt.date.today().isoformat()}"
    d = _kv_get(rt, key, {}) or {}
    d[ctx] = round(float(d.get(ctx, 0.0)) + max(0.0, czk), 4)
    _kv_set(rt, key, d)


def over_budget(rt: Any, ctx: str | None = None) -> str:
    """'' or why the cloud AI should not be used now (the day's budget for this activity is used up)."""
    lim = getattr(rt.cfg, "limits", None)
    ctx = ctx or context_now(rt)
    cap = float(getattr(lim, f"ai_czk_{ctx}", 0) or 0) if lim is not None else 0.0
    if cap <= 0:
        return ""
    spent = spend_today(rt, ctx)
    if spent < cap:
        return ""
    label = {"game": "hraní", "work": "práci"}.get(ctx, "ostatní")
    return f"Dnešní rozpočet AI na {label} ({cap:.0f} Kč) je vyčerpaný – odpovídám AI v tomhle PC."


# ------------------------------------------------------------------ (38) odhad doby
def estimate(rt: Any, goal: str) -> dict:
    """How long a task will take: from how long similar past tasks took, else from its size."""
    words = set(re.findall(r"\w{4,}", fold(goal)))
    durs = []
    try:
        rows = rt.db.all("SELECT goal, created, finished FROM tasks WHERE status='done' AND finished IS NOT NULL ORDER BY created DESC LIMIT 400")
    except Exception:  # noqa: BLE001
        rows = []
    for r in rows:
        w = set(re.findall(r"\w{4,}", fold(r["goal"] or "")))
        if words and len(words & w) / max(1, len(words)) >= 0.5 and r["finished"] > r["created"]:
            durs.append(float(r["finished"]) - float(r["created"]))
    if len(durs) >= 2:
        sec = statistics.median(durs)
        how = f"podle {len(durs)} podobných úkolů"
    else:
        steps = 1 + len(re.findall(r"\b(a pak|potom|a taky|a zaroven|kazd\w+|vsechn\w+)\b", fold(goal))) + len(goal) // 120
        sec = 20 + 35 * steps
        how = "odhad podle velikosti zadání"
    m = max(1, round(sec / 60))
    return {"seconds": round(sec), "text": (f"asi {m} min" if sec >= 90 else f"asi {round(sec)} s") + f" ({how})"}


# ------------------------------------------------------------------ (39) co se JARVIS naučil
def learned_week(rt: Any, now: float | None = None) -> dict:
    now = now or time.time()
    since = now - 7 * 86400
    out: dict[str, list[str]] = {"rules": [], "reflexes": [], "skills": [], "glossary": []}
    try:
        out["rules"] = [r["text"] for r in rt.db.all("SELECT text FROM learned_rules WHERE created >= ? ORDER BY created DESC LIMIT 10", (since,))]
    except Exception:  # noqa: BLE001
        pass
    try:
        out["reflexes"] = [f"„{r['phrase']}“ → {r['tool']}" for r in rt.db.all(
            "SELECT phrase, tool FROM tool_memory WHERE ok >= 2 AND last >= ? ORDER BY last DESC LIMIT 10", (since,))]
    except Exception:  # noqa: BLE001
        pass
    try:
        from .paths import data_dir

        sk = data_dir() / "skills"
        out["skills"] = [p.stem for p in sk.glob("*.py") if p.stat().st_mtime >= since][:10] if sk.is_dir() else []
    except Exception:  # noqa: BLE001
        pass
    added = _kv_get(rt, "glossary_added", {}) or {}
    out["glossary"] = [k for k, ts in added.items() if ts >= since]
    return out


def learned_text(d: dict) -> str:
    parts = []
    if d["rules"]:
        parts.append("Pravidla z tvých oprav: " + "; ".join(d["rules"][:5]))
    if d["reflexes"]:
        parts.append(f"Nové rychlé povely ({len(d['reflexes'])}): " + ", ".join(d["reflexes"][:5]))
    if d["skills"]:
        parts.append("Nové dovednosti: " + ", ".join(d["skills"]))
    if d["glossary"]:
        parts.append("Nové zkratky: " + ", ".join(d["glossary"]))
    return " ".join(parts) if parts else "Tento týden jsem se nic nového nenaučil – žádné opravy, nové povely ani dovednosti."


def ensure_week_job(rt: Any) -> None:
    """Every Sunday at 18:00 a short note: what JARVIS learned this week."""
    try:
        if any(j and j.get("kind") == "brain_week" for j in rt.scheduler.list()):
            return
        rt.scheduler.add({"type": "daily", "days": [6], "time": "18:00"}, "brain_week", {}, title="Co jsem se naučil")
    except Exception as e:  # noqa: BLE001
        log.debug("week job: %s", e)


# ------------------------------------------------------------------ (40) kreativní režim
CREATIVE = re.compile(r"\b(silen\w*|blazniv\w*|odvazn\w*|kreativn\w*|netradicn\w*|ujet\w*|originaln\w*|brainstorm\w*|"
                      r"co nejvic napadu|hodne napadu)\b")
CREATIVE_RULE = ("Kreativní režim: buď odvážný a pestrý – nabídni i neobvyklé, překvapivé nápady, ne jen ty první, které "
                 "napadnou každého. Klidně víc variant.")


def creative_request(text: str) -> bool:
    w = fold(text)
    return bool(CREATIVE.search(w) and re.search(r"\b(vymysl\w*|napad\w*|navrhni|navrh\w*|brainstorm\w*|napis|wymysli)\b", w))


# ------------------------------------------------------------------ the prompt lines of one message
def prompt_lines(rt: Any, text: str) -> list[str]:
    b = rt.cfg.brain
    lines = []
    if getattr(b, "honest", True):
        lines.append(HONEST_RULE)
    style = getattr(rt.cfg.general, "answer_style", "auto")
    if STYLES.get(style):
        lines.append(STYLES[style])
    if getattr(b, "confidence", True):
        lines.append(CONF_RULE)
    if deep_request(text):
        lines.append(STEPS_RULE)
    if creative_request(text):
        lines.append(CREATIVE_RULE)
    if teach_request(text) or getattr(b, "teach", False):
        lines.append(TEACH_RULE)
    g = glossary_prompt(rt, text)
    if g:
        lines.append(g)
    if WRITES.search(fold(text)):
        sp = style_prompt(_kv_get(rt, "writing_style", {}) or {})
        if sp:
            lines.append(sp)
    if getattr(rt, "driving", False):                  # 3.20 (123) the phone is in the car
        from .phonex import DRIVE_RULE

        lines.append(DRIVE_RULE)
    return lines
