"""OMEGA §58 Everyday Intelligence: life events as checklists on a timeline, packing by the real forecast, the best
day/hour for something outside, ingredient substitutes, a shopping list sorted by shop section, a daily focus report,
how hard a text is to read, and a setup check of what JARVIS can already do here.

Deterministic where it can be (tables, rules, the forecast numbers); nothing is bought, booked or sent."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from .comms import fold

# ---------------------------------------------------------------------------------------------- 781 life events
LIFE_EVENTS: dict[str, list[tuple[int, str]]] = {   # (days before the date; negative = after)
    "stěhování": [(42, "Výpověď nájmu / domluva termínu předání"), (30, "Objednat stěhovací firmu nebo dodávku"),
                  (21, "Začít vyřazovat a balit věci, které nepotřebuješ"), (14, "Nahlásit změnu adresy: banka, pojišťovna, práce, škola"),
                  (14, "Přepsat elektřinu, plyn, internet na nový byt"), (7, "Sehnat krabice, pásku, popisovač"),
                  (2, "Zabalit kuchyň a koupelnu, nechat si krabici „první noc“"), (0, "Stěhování: fotky stavu bytu, odečet měřidel"),
                  (-3, "Změna trvalého pobytu na úřadě, adresa v občance a v autě"), (-14, "Přeposílání pošty zrušit / zkontrolovat")],
    "svatba": [(365, "Termín, rozpočet, seznam hostů"), (300, "Obřadní místo a matrika"), (240, "Fotograf, hudba, catering"),
               (180, "Šaty a oblek"), (120, "Oznámení"), (60, "Prstýnky, zasedací pořádek"), (30, "Doklady na matriku"),
               (7, "Finální počty hostů"), (0, "Svatba"), (-30, "Změna jména v dokladech (pokud se mění)")],
    "narození dítěte": [(120, "Vybrat porodnici a pediatra"), (90, "Kočárek, autosedačka, výbavička"), (60, "Taška do porodnice"),
                        (30, "Doklady: OP, průkaz pojištěnce, oddací list / souhlasné prohlášení"), (0, "Termín porodu"),
                        (-3, "Rodný list na matrice"), (-8, "Přihlásit dítě u zdravotní pojišťovny"), (-30, "Rodičovský příspěvek – žádost")],
    "dovolená": [(60, "Letenky / ubytování"), (30, "Cestovní pojištění, platnost pasu"), (14, "Kdo zalije květiny / pohlídá zvíře"),
                 (3, "Zabalit (packing_list), nabíječky, léky"), (1, "Odbavení online, vytisknout potvrzení"), (0, "Odjezd")],
    "nová práce": [(14, "Doklady: zápočtový list, OP, číslo účtu, průkaz pojištěnce"), (7, "Cesta do práce a čas"), (0, "První den"),
                   (-7, "Prohlášení poplatníka, pojišťovna"), (-90, "Konec zkušební doby")],
    "narozeniny": [(21, "Pozvat hosty"), (14, "Dárek"), (7, "Objednat dort / místo"), (1, "Nákup"), (0, "Oslava")],
    "stk": [(30, "Objednat termín STK"), (7, "Kontrola světel, stěračů, pneu, lékárničky"), (0, "STK"), (-1, "Uložit protokol")],
}


EVENT_WORDS = {"stěhování": r"stehov|stehuj|novy byt|prestehov", "svatba": r"svatb|svatebn|beru se|zenim|vdavam",
               "narození dítěte": r"miminko|porod|narozeni ditete|dite|tehoten", "dovolená": r"dovolen|vylet do|cest|prazdnin",
               "nová práce": r"nova prace|nastup|nove zamestn", "narozeniny": r"narozenin|oslav", "stk": r"\bstk\b|technick"}


def life_event(kind: str, date: dt.date, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    f = fold(kind)
    k = next((x for x, rx in EVENT_WORDS.items() if re.search(rx, f)), None)
    if not k:
        raise ValueError(f"Na „{kind}“ šablonu nemám. Umím: {', '.join(LIFE_EVENTS)}.")
    steps = []
    for before, text in LIFE_EVENTS[k]:
        d = date - dt.timedelta(days=before)
        steps.append({"date": d.isoformat(), "text": text, "late": d < today})
    return {"event": k, "date": date.isoformat(), "steps": steps, "late": sum(s["late"] for s in steps)}


# ---------------------------------------------------------------------------------------------- 782 / 783 weather
async def forecast(rt, city: str, days: int = 7) -> dict:
    async with rt.http() as c:
        g = (await c.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1, "language": "cs"}, timeout=15)).json()
        if not g.get("results"):
            raise ValueError(f"Město „{city}“ nenalezeno")
        loc = g["results"][0]
        w = (await c.get("https://api.open-meteo.com/v1/forecast", timeout=15, params={
            "latitude": loc["latitude"], "longitude": loc["longitude"], "timezone": "auto", "forecast_days": max(1, min(16, days)),
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max,uv_index_max",
            "hourly": "temperature_2m,precipitation_probability,wind_speed_10m"})).json()
    d, h = w["daily"], w.get("hourly") or {}
    out = [{"date": d["time"][i], "code": d["weather_code"][i], "max": d["temperature_2m_max"][i], "min": d["temperature_2m_min"][i],
            "rain_pct": d["precipitation_probability_max"][i], "rain_mm": d["precipitation_sum"][i], "wind": d["wind_speed_10m_max"][i],
            "uv": (d.get("uv_index_max") or [None] * 99)[i]} for i in range(len(d["time"]))]
    hours = [{"time": t, "temp": tp, "rain_pct": rp, "wind": wi} for t, tp, rp, wi in
             zip(h.get("time", []), h.get("temperature_2m", []), h.get("precipitation_probability", []), h.get("wind_speed_10m", []))]
    return {"city": loc["name"], "days": out, "hours": hours}


ACTIVITY = {"běh": (8, 20), "kolo": (12, 26), "grilování": (16, 30), "výlet": (10, 26), "koupání": (24, 35), "zahrada": (10, 28),
            "mytí auta": (8, 28), "venku": (10, 28)}


def best_time(fc: dict, activity: str = "venku", from_hour: int = 8, to_hour: int = 20) -> dict:
    lo, hi = next((v for k, v in ACTIVITY.items() if fold(k) in fold(activity)), ACTIVITY["venku"])
    best = []
    for hr in fc.get("hours") or []:
        t = dt.datetime.fromisoformat(hr["time"])
        if not from_hour <= t.hour < to_hour or t < dt.datetime.now() - dt.timedelta(hours=1):
            continue
        score = 100 - (hr["rain_pct"] or 0) - max(0, lo - (hr["temp"] or 0)) * 5 - max(0, (hr["temp"] or 0) - hi) * 5 - max(0, (hr["wind"] or 0) - 25) * 2
        best.append({**hr, "score": round(score)})
    best.sort(key=lambda x: -x["score"])
    days = sorted(fc["days"], key=lambda x: (x["rain_pct"] or 0) + max(0, lo - x["max"]) * 5 + max(0, x["max"] - hi) * 5)
    return {"best_hours": best[:5], "best_days": days[:3], "range": (lo, hi)}


BASE_PACK = ["doklady (OP / pas)", "peněženka, karta", "telefon + nabíječka", "léky", "hygiena", "spodní prádlo", "ponožky", "pyžamo"]


def packing_list(nights: int, fc_days: list[dict] | None = None, activities: str = "", abroad: bool = False) -> dict:
    n = max(1, nights)
    items = list(BASE_PACK)
    items[5] = f"spodní prádlo ×{n + 1}"
    items[6] = f"ponožky ×{n + 1}"
    items.append(f"trička ×{min(n + 1, 7)}")
    reasons = []
    if fc_days:
        tmax = max(d["max"] for d in fc_days)
        tmin = min(d["min"] for d in fc_days)
        rain = max(d["rain_pct"] or 0 for d in fc_days)
        uv = max(d.get("uv") or 0 for d in fc_days)
        if tmin < 8:
            items += ["teplá bunda", "čepice a rukavice" if tmin < 2 else "mikina"]
            reasons.append(f"ráno až {tmin:.0f} °C")
        if tmax > 24:
            items += ["kraťasy", "sluneční brýle", "láhev na vodu"]
            reasons.append(f"až {tmax:.0f} °C")
        if rain >= 40:
            items += ["deštník nebo pláštěnka", "nepromokavé boty"]
            reasons.append(f"déšť až {rain:.0f} %")
        if uv >= 6:
            items.append("opalovací krém")
            reasons.append(f"UV {uv:.0f}")
    a = fold(activities)
    if "more" in a or "kou" in a or "bazen" in a:
        items += ["plavky", "ručník", "žabky"]
    if "hory" in a or "turist" in a or "vylet" in a:
        items += ["pohorky", "batoh", "lékárnička", "čelovka"]
    if "prace" in a or "sluzeb" in a:
        items += ["notebook + nabíječka", "společenské oblečení"]
    if abroad:
        items += ["cestovní pojištění (kartička)", "adaptér do zásuvky", "kopie dokladů v telefonu"]
    return {"items": list(dict.fromkeys(items)), "because": reasons}


# ---------------------------------------------------------------------------------------------- 786 substitutions
SUBSTITUTES = {
    "vejce": ["1 lžíce mletého lnu + 3 lžíce vody (na 1 vejce)", "1/2 rozmačkaného banánu (do sladkého)", "60 g bílého jogurtu"],
    "máslo": ["stejné množství margarínu", "3/4 množství oleje (do těsta)", "kokosový tuk"],
    "mléko": ["rostlinné mléko 1:1", "voda + trocha smetany", "jogurt ředěný vodou 1:1"],
    "smetana": ["zakysaná smetana / bílý jogurt (nevařit)", "mléko + máslo (3:1)", "kokosové mléko"],
    "podmáslí": ["mléko + 1 lžíce citronové šťávy na 250 ml, nechat 10 min"],
    "prášek do pečiva": ["1/4 lžičky jedlé sody + 1/2 lžičky citronové šťávy na 1 lžičku prášku"],
    "droždí": ["sušené droždí: 7 g místo 21 g čerstvého", "kvásek (delší kynutí)"],
    "hladká mouka": ["polohrubá mouka (jemnější výsledek)", "bezlepková směs 1:1 + trocha xanthanu"],
    "cukr": ["med (3/4 množství, méně tekutiny)", "javorový sirup", "erythritol 1:1"],
    "strouhanka": ["rozdrcené kukuřičné lupínky", "ovesné vločky namleté", "mandlová mouka"],
    "zakysaná smetana": ["řecký jogurt", "tvaroh rozmíchaný s mlékem"],
    "parmazán": ["grana padano", "jiný tvrdý sýr", "lahůdkové droždí (veganské)"],
    "víno do omáčky": ["vývar + lžička octa", "hroznový džus + ocet"],
    "pivo do těsta": ["perlivá voda"],
    "citron": ["limetka", "ocet (jen do slaného, méně)"],
}


def substitute(ingredient: str) -> list[str]:
    f = fold(ingredient)
    for k, v in SUBSTITUTES.items():
        if fold(k) in f or f in fold(k):
            return v
    return []


# ---------------------------------------------------------------------------------------------- 785 grocery by section
AISLES = [("Ovoce a zelenina", r"jabl|banan|hrus|pomeran|citron|limet|rajc|okurk|paprik|cibul|cesnek|brambor|mrkev|salat|zeli|avokad|hrozn|jahod|bylink|petrzel|kopr"),
          ("Pečivo", r"chleb|rohlik|houska|bageta|kaiserk|toust|vanock|kolac"),
          ("Mléčné a vejce", r"mlek|jogurt|syr|tvaroh|maslo|smetan|vejc|kefir|podmasl|eidam|mozzarel|parmez"),
          ("Maso a uzeniny", r"maso|kure|vepr|hovez|mlet|salam|sunk|parek|klobas|slanin|ryb|losos|tunak"),
          ("Trvanlivé", r"mouk|cukr|ryze|testovin|spaget|olej|ocet|sul|koren|kafe|kava|caj|cokolad|susenk|konzerv|lusten|vlock|musli|med\b|dzem|kecup|horcic"),
          ("Mražené", r"mrazen|zmrzlin|pizza"),
          ("Nápoje", r"voda|dzus|limonad|pivo|vino|cola|sirup"),
          ("Drogerie", r"mydl|sampon|pasta|kartacek|papir|prasek|avivaz|jar\b|houbick|sacky|ubrous|baterie|zarovk")]


def by_aisle(items: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for it in items:
        f = fold(it)
        sec = next((name for name, rx in AISLES if re.search(rx, f)), "Ostatní")
        out.setdefault(sec, []).append(it)
    order = [a for a, _ in AISLES] + ["Ostatní"]
    return {k: out[k] for k in order if k in out}


# ---------------------------------------------------------------------------------------------- 787 focus
KINDS = [("hry", r"steam|epic|minecraft|league|valorant|fortnite|roblox|battle\.net|riot|game|hra"),
         ("zábava", r"youtube|netflix|spotify|twitch|tiktok|instagram|facebook|reddit|disney|hbo|prime video|9gag|x\.com|twitter"),
         ("komunikace", r"outlook|mail|thunderbird|teams|slack|discord|whatsapp|messenger|telegram|signal|zoom|skype"),
         ("práce", r"word|excel|powerpoint|onenote|code|visual studio|pycharm|intellij|figma|photoshop|illustrator|blender|acrobat|libreoffice|notion|obsidian|terminal|powershell|cmd|explorer|průzkumník|jarvis")]


def classify_app(app: str) -> str:
    a = app.lower()
    return next((k for k, rx in KINDS if re.search(rx, a)), "ostatní")


def focus_report(rt, day: dt.date | None = None) -> dict:
    day = day or dt.date.today()
    rows = rt.db.all("SELECT app, seconds FROM app_usage WHERE day=?", (day.isoformat(),))
    by: dict[str, float] = {}
    for r in rows:
        by[classify_app(r["app"])] = by.get(classify_app(r["app"]), 0) + r["seconds"]
    total = sum(by.values())
    work = by.get("práce", 0)
    hours = rt.db.all("SELECT hour, app, seconds FROM app_hours WHERE day=?", (day.isoformat(),)) if \
        rt.db.one("SELECT 1 FROM sqlite_master WHERE name='app_hours'") else []
    per_hour: dict[int, dict[str, float]] = {}
    for h in hours:
        per_hour.setdefault(h["hour"], {}).setdefault(classify_app(h["app"]), 0)
        per_hour[h["hour"]][classify_app(h["app"])] += h["seconds"]
    best = max(per_hour.items(), key=lambda kv: kv[1].get("práce", 0), default=(None, {}))
    return {"day": day.isoformat(), "minutes": {k: round(v / 60) for k, v in sorted(by.items(), key=lambda kv: -kv[1])},
            "total_min": round(total / 60), "focus_pct": round(work * 100 / total) if total else None,
            "best_hour": best[0] if best[1].get("práce") else None}


# ---------------------------------------------------------------------------------------------- 791 reading
def readability(text: str) -> dict:
    """Czech-friendly: average sentence length and share of long words (≥ 4 syllables ~ ≥ 10 letters)."""
    sents = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    words = re.findall(r"[A-Za-zÁ-ž]+", text)
    if not words:
        return {"level": "–", "words": 0}
    avg = len(words) / max(1, len(sents))
    long_pct = sum(1 for w in words if len(w) >= 10) * 100 / len(words)
    score = avg * 1.5 + long_pct * 2
    level = "snadný" if score < 25 else "střední" if score < 40 else "náročný"
    return {"level": level, "score": round(score, 1), "words": len(words), "sentences": len(sents),
            "avg_sentence": round(avg, 1), "long_words_pct": round(long_pct, 1),
            "minutes": max(1, round(len(words) / 200))}


# ---------------------------------------------------------------------------------------------- 795 setup check
def _has_backup() -> bool:
    from pathlib import Path

    for folder in (Path.home() / "Documents", Path.home()):
        if folder.is_dir() and any(folder.glob("JARVIS-zaloha_*.jarvisvault")):
            return True
    return False


def setup_status(rt) -> list[dict]:
    cfg = rt.cfg
    from . import secrets

    def has_key(pid: str) -> bool:
        try:
            return bool(secrets.get(pid))
        except Exception:  # noqa: BLE001
            return False
    provs = [p for p in cfg.brain.providers if p.enabled]
    ai_ok = any(has_key(p.id) or p.preset in ("ollama", "omniroute") for p in provs)
    items: list[dict[str, Any]] = [
        {"key": "ai", "title": "Mozek (AI)", "ok": ai_ok, "next": "Nastavení → Mozek: vlož klíč (Groq a Gemini mají bezplatný tarif)."},
        {"key": "name", "title": "Jak ti říkat", "ok": bool(cfg.general.user_name), "next": "Nastavení → Obecné: tvoje jméno a oslovení."},
        {"key": "city", "title": "Domovské město (počasí)", "ok": bool(cfg.general.city), "next": "Nastavení → Obecné: město."},
        {"key": "voice", "title": "Hlas", "ok": getattr(rt, "voice", None) is not None and getattr(rt.voice, "available", False),
         "next": "Nastavení → Hlas: mikrofon a slovo „Hey JARVIS“."},
        {"key": "mail", "title": "E-mail", "ok": bool(cfg.mail.accounts), "next": "E-mail a telefon → Přidat účet."},
        {"key": "calendar", "title": "Kalendář", "ok": bool(cfg.calendar.ics_urls) or bool(rt.db.one("SELECT 1 FROM cal_events LIMIT 1")),
         "next": "E-mail a telefon → Kalendář: odkaz iCal z Google / Outlook."},
        {"key": "phone", "title": "Telefon", "ok": bool(getattr(getattr(rt, "phone", None), "link_alive", lambda: False)()),
         "next": "Nastavení → Telefon: naskenuj QR kód v aplikaci JARVIS."},
        {"key": "home", "title": "Chytrá domácnost", "ok": bool(cfg.home.url), "next": "Domov → Připojit Home Assistant (nepovinné)."},
        {"key": "backup", "title": "Záloha", "ok": _has_backup(), "next": "Bezpečí a soukromí → Šifrovaná záloha."},
    ]
    return items
