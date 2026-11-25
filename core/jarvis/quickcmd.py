"""3.16 Víc povelů bez AI (návrh 6): everyday commands with a slot ("přidej mléko na nákup", "rozsviť v kuchyni",
"pozastav tisk", "rozlož model", "ukaž glóbus", "pusť lo-fi na YouTube", "kolik stojí bitcoin", "počasí v Brně") are
done the moment you finish the sentence – no AI in between.

The words are matched without accents, but what goes to the tool (an item, a room, a song) is taken from what you
said, with its accents. What asks for confirmation still asks; a step that fails hands the request to the AI.
Together with the learnt reflexes (toolmind) JARVIS does hundreds of things without asking the AI at all.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

P = r"^(?:(?:jarvis\w*|prosim\w*|hej|hey|muzes|muzete|bys|by|mi|nam|ted|hned|ok)[\s,]+)*"
_DEVICE = r"(?:svetl\w*|lamp\w*|lustr\w*|zasuvk\w*|led\w*|pasek|ventilator\w*|topeni|klimatizac\w*|zaluzi\w*|rolet\w*)"


def fold_keep(text: str) -> str:
    """Lower case without accents, every character kept in its place (so a match points into the original text)."""
    out = []
    for c in text.lower():
        base = "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
        out.append(base if len(base) == 1 else c)
    return "".join(out)


def _clean(text: str) -> str:
    return re.sub(r"[?!.…]+$", "", text.strip()).strip(" ,")


def _items(s: str) -> list[str]:
    parts = re.split(r"\s*,\s*|\s+a\s+|\s+i\s+", s.strip())
    return [p.strip() for p in parts if p.strip()][:10]


Rule = tuple[str, Callable[[Any, str], list[tuple[str, dict]]], str]


def _g(m: Any, orig: str, name: str) -> str:
    """The slot, as you said it (accents and capitals kept)."""
    a, b = m.span(name)
    return _clean(orig[a:b])


RULES: list[Rule] = []


def rule(pattern: str, kind: str):
    def deco(fn):
        RULES.append((P + pattern + r"\s*$", fn, kind))
        return fn
    return deco


# ---- lists
@rule(r"(?:pridej|pripis|napis|dej|zapis)\s+(?P<item>.{2,80}?)\s+(?:na|do)\s+(?P<list>nakup\w*|nakupni seznam|seznam\w*(?:\s+\w+)?)", "list")
def _list_add(m, o):
    lst = _g(m, o, "list")
    return [("list_add", {"items": _items(_g(m, o, "item")), "list": "nákup" if fold_keep(lst).startswith("nakup") else lst})]


@rule(r"(?:co (?:mam|mame|musim) (?:koupit|nakoupit|na nakupu)|(?:ukaz|precti|rekni)\w*\s+(?:mi\s+)?(?:nakup\w*|nakupni seznam|seznam nakupu))", "list")
def _list_show(m, o):
    return [("list_show", {})]


@rule(r"(?:koupil\w*|nakoupil\w*|odskrtni|smaz z nakupu|uz mam)\s+(?:jsem\s+)?(?P<item>.{2,80})", "list")
def _list_done(m, o):
    return [("list_done", {"items": _items(_g(m, o, "item"))})]


# ---- the home (Home Assistant)
@rule(r"(?P<act>zapni|vypni|rozsvit\w*|zhasni|zhasn\w*|pust)\s+(?P<target>" + _DEVICE + r"(?:\s+(?:v|ve|na|u|nad)\s+\S+(?:\s+\S+)?)?)", "home")
def _home_device(m, o):
    act = fold_keep(m.group("act"))
    on = act.startswith(("zapn", "rozsvit", "pust"))
    return [("home_control", {"target": _g(m, o, "target"), "action": "on" if on else "off"})]


@rule(r"(?P<act>rozsvit\w*|zhasni|zhasn\w*)\s+(?:v|ve|na|u)\s+(?P<room>.{2,30})", "home")
def _home_room(m, o):
    on = fold_keep(m.group("act")).startswith("rozsvit")
    return [("home_control", {"target": "světlo " + _g(m, o, "room"), "action": "on" if on else "off", "domain": "light"})]


@rule(r"(?:zapni|spust|aktivuj)\s+scen\w*\s+(?P<name>.{2,30})", "home")
def _scene(m, o):
    return [("home_scene", {"name": _g(m, o, "name")})]


@rule(r"(?:spust|aktivuj|zapni)\s+protokol\s+(?P<name>.{2,30})", "protocol")
def _protocol(m, o):
    return [("run_protocol", {"name": _g(m, o, "name")})]


# ---- the workshop
@rule(r"(?:pozastav|zastav na chvili|pauzni)\s+(?:3d\s+)?tisk\w*", "printer")
def _p_pause(m, o):
    return [("printer_control", {"action": "pause"})]


@rule(r"(?:pokracuj|obnov|pust)\w*\s+(?:v\s+|dal\s+)?(?:3d\s+)?tisk\w*", "printer")
def _p_resume(m, o):
    return [("printer_control", {"action": "resume"})]


@rule(r"(?:jak (?:je|jde)(?: na tom)?|stav|kolik zbyva(?: do konce)?|co dela)\s+(?:3d\s+)?(?:tisk\w*|tiskarn\w*)", "printer")
def _p_status(m, o):
    return [("printer_control", {"action": "status"})]


@rule(r"(?:rozloz|rozlozit|rozloz mi)\s+(?:ten\s+|tu\s+)?(?:model\w*|sestav\w*)", "model")
def _m_explode(m, o):
    return [("model_explode", {"action": "explode"})]


@rule(r"(?:sloz|slozit)\s+(?:ten\s+|tu\s+)?(?:model\w*|sestav\w*)(?:\s+zpet|\s+dohromady)?", "model")
def _m_collapse(m, o):
    return [("model_explode", {"action": "collapse"})]


@rule(r"(?:otoc|natoc)\s+(?:ten\s+)?model\w*\s+(?P<dir>doleva|doprava|vlevo|vpravo)", "model")
def _m_rotate(m, o):
    return [("model_explode", {"action": "rotate_left" if m.group("dir") in ("doleva", "vlevo") else "rotate_right"})]


@rule(r"(?P<z>priblizi?|zvetsi|oddali?|zmensi)\s+(?:ten\s+)?model\w*", "model")
def _m_zoom(m, o):
    return [("model_explode", {"action": "zoom_in" if m.group("z").startswith(("pribl", "zvet")) else "zoom_out"})]


@rule(r"(?:co mi chybi|co chybi)\s+(?:na|do|k)\s+(?P<proj>.{2,40})", "workshop")
def _w_missing(m, o):
    return [("workshop_project", {"action": "missing", "project": _g(m, o, "proj")})]


# ---- the HUD
@rule(r"(?:ukaz|otevri|zobraz)\s+(?:mi\s+)?(?:3d\s+)?(?:globus|zemekouli)", "hud")
def _h_globe(m, o):
    return [("hud_control", {"action": "globe"})]


@rule(r"(?:ukaz|otevri|zobraz)\s+(?:mi\s+)?mapu(?:\s+sveta)?", "hud")
def _h_map(m, o):
    return [("hud_control", {"action": "map"})]


@rule(r"(?:schovej|skryj)\s+panely", "hud")
def _h_hide(m, o):
    return [("hud_control", {"action": "hide_panels"})]


@rule(r"(?:ukaz|vrat)\s+panely(?:\s+zpet)?", "hud")
def _h_show(m, o):
    return [("hud_control", {"action": "show_panels"})]


@rule(r"(?P<l>minimalni|plne|holo|prezentacni)\s+rozlozeni(?:\s+hud)?", "hud")
def _h_layout(m, o):
    return [("hud_control", {"action": {"minimalni": "minimal", "plne": "full", "holo": "holo", "prezentacni": "presentation"}[m.group("l")]})]


@rule(r"(?:zavri|schovej)\s+hud", "hud")
def _h_close(m, o):
    return [("hud_control", {"action": "close"})]


# ---- media, phone, money, weather
@rule(r"(?:pust|zahraj|pustit|dej)\s+(?:mi\s+)?(?P<q>.{2,60}?)\s+(?:na|z|ze)\s+(?:youtube|youtubu|yt|jutubu)", "media")
def _yt(m, o):
    return [("youtube_play", {"query": _g(m, o, "q")})]


@rule(r"(?:najdi|kde je|prozvon)\s+(?:muj\s+)?(?:telefon|mobil)", "phone")
def _phone_find(m, o):
    return [("find_phone", {})]


@rule(r"kolik (?:ma|mam|je)\s+(?:na\s+)?(?:mobil\w*|telefon\w*)\s+(?:baterk\w*|baterie|procent)|(?:baterka|baterie) (?:mobilu|telefonu)", "phone")
def _phone_bat(m, o):
    return [("phone_battery", {})]


@rule(r"(?:kolik (?:stoji|je)|cena|jaka je cena)\s+(?P<asset>bitcoin\w*|btc|ethereum\w*|eth|solan\w*|zlat\w*|stribr\w*|dogecoin\w*)", "money")
def _price(m, o):
    a = m.group("asset")
    asset = {"btc": "bitcoin", "eth": "ethereum"}.get(a, re.sub(r"(u|a|e|y)$", "", a) if a.startswith(("zlat", "stribr")) else a)
    asset = {"zlat": "zlato", "stribr": "stříbro"}.get(asset, asset)
    return [("price", {"asset": asset})]


@rule(r"kolik (?:je|stoji)\s+(?P<n>\d+(?:[.,]\d+)?)?\s*(?P<cur>eur\w*|dolar\w*|usd|libr\w*|gbp|frank\w*|zlot\w*)(?:\s+v\s+korunach)?", "money")
def _fx(m, o):
    cur = m.group("cur")
    code = "EUR" if cur.startswith("eur") else "USD" if cur.startswith(("dolar", "usd")) else "GBP" if cur.startswith(("libr", "gbp")) \
        else "CHF" if cur.startswith("frank") else "PLN"
    n = float((m.group("n") or "1").replace(",", "."))
    return [("exchange_rate", {"amount": n, "from_currency": code, "to_currency": "CZK"})]


CITY_CASE = {  # "v Brně" → Brno (the places people ask about most; anything else goes as said)
    "brne": "Brno", "praze": "Praha", "ostrave": "Ostrava", "plzni": "Plzeň", "olomouci": "Olomouc", "liberci": "Liberec",
    "ceskych budejovicich": "České Budějovice", "budejovicich": "České Budějovice", "hradci kralove": "Hradec Králové",
    "hradci": "Hradec Králové", "pardubicich": "Pardubice", "zline": "Zlín", "jihlave": "Jihlava", "kladne": "Kladno",
    "karlovych varech": "Karlovy Vary", "usti nad labem": "Ústí nad Labem", "usti": "Ústí nad Labem", "opave": "Opava",
    "frydku-mistku": "Frýdek-Místek", "havirove": "Havířov", "most": "Most", "teplicich": "Teplice", "decine": "Děčín",
    "chomutove": "Chomutov", "prerove": "Přerov", "jablonci": "Jablonec nad Nisou", "mlade boleslavi": "Mladá Boleslav",
    "prostejove": "Prostějov", "trebici": "Třebíč", "tabore": "Tábor", "znojme": "Znojmo", "pisku": "Písek",
    "bratislave": "Bratislava", "kosicich": "Košice", "vidni": "Vídeň", "berline": "Berlín", "mnichove": "Mnichov",
    "londyne": "Londýn", "parizi": "Paříž", "rime": "Řím", "madridu": "Madrid", "barcelone": "Barcelona",
    "amsterdamu": "Amsterdam", "varsave": "Varšava", "krakove": "Krakov", "budapesti": "Budapešť", "new yorku": "New York",
    "tokiu": "Tokio", "dubaji": "Dubaj", "milane": "Milán", "benatkach": "Benátky", "chorvatsku": "Chorvatsko",
    "itali": "Itálie", "alpach": "Alpy", "krkonosich": "Krkonoše", "tatrach": "Tatry",
}


@rule(r"(?:jake je|jak je|jaky je|jake bude)?\s*pocasi\s+(?:v|ve|na|pro)\s+(?P<city>[^\s].{1,30}?)", "weather")
def _weather_city(m, o):
    said = _g(m, o, "city")
    return [("weather", {"city": CITY_CASE.get(fold_keep(said), said)})]


@rule(r"(?:brifink|brifing|ranni brifink|co me dnes ceka|co mam dnes v planu)", "briefing")
def _briefing(m, o):
    return [("briefing", {})]


def plan(text: str) -> tuple[list[tuple[str, dict]], str] | None:
    """(the steps, the kind) for these words, or None."""
    orig = text.strip()
    if not orig or len(orig) > 120:
        return None
    t = fold_keep(orig)
    t2 = re.sub(r"[?!.…]+$", "", t).rstrip()
    t2 = re.sub(r"[\s,]+(?:prosim\w*|dik\w*|jarvis\w*|pane)$", "", t2).rstrip()
    o2 = orig[: len(t2)]
    for pattern, fn, kind in RULES:
        m = re.match(pattern, t2)
        if m:
            try:
                return fn(m, o2), kind
            except Exception:  # noqa: BLE001 – an odd slot: the AI takes it
                return None
    return None
