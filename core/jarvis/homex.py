"""3.20 Domácnost+ (nápady 161–180 ze stránky „Nápady pro JARVISe“) – everything through Home Assistant's states.

- otevřené okno vypne topení v místnosti (161), zapomenuté spotřebiče (162), odpověď u zvonku hlasem (163)
- teploty po místnostech a kde se zbytečně topí (164), prádlo hotovo podle odběru (165), CO₂ a vlhkost (166)
- noční tlumené světlo při pohybu (167), simulace přítomnosti na dovolené (168), únik vody (169), mapa domu (170)
- baterie v čidlech s předpovědí (171), přebytek z fotovoltaiky pustí spotřebiče (172), zalévání podle počasí (173)
- „je zamčeno?“ s fotkou (174), vysavač, když nikdo není doma (175), rodinné profily (176)
- Matter přímo přes python-matter-server, bez cloudu (177), otevřená vrata garáže (178), zapomenutý sporák (179)
- kamery v domě se vypnou, když jsi doma (180)

Each check works on a plain list of states (testable without a house); `tick` reads Home Assistant once a minute.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import random
import re
import time
import unicodedata
from typing import Any, Callable

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS hx_batt (day TEXT, id TEXT, level REAL, PRIMARY KEY (day, id));
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def _cfg(rt: Any) -> Any:
    return getattr(rt.cfg, "homex", None)


def _get(rt: Any, name: str, default: Any = None) -> Any:
    c = _cfg(rt)
    return getattr(c, name, default) if c is not None else default


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ states
def norm(raw: list[dict]) -> list[dict]:
    """Home Assistant's /api/states → small dicts: id, domain, name, state, cls, unit, value (a number), attrs."""
    out = []
    for e in raw:
        eid = str(e.get("entity_id") or e.get("id") or "")
        if "." not in eid:
            continue
        a = e.get("attributes") or {}
        out.append({"id": eid, "domain": eid.split(".", 1)[0], "name": str(a.get("friendly_name") or eid), "state": str(e.get("state", "")),
                    "cls": str(a.get("device_class") or ""), "unit": str(a.get("unit_of_measurement") or ""),
                    "value": _num(e.get("state")), "attrs": a})
    return out


GENERIC = {"okno", "okna", "window", "dvere", "door", "kontakt", "contact", "senzor", "sensor", "cidlo", "topeni", "termostat",
           "thermostat", "hlavice", "radiator", "climate", "trv", "svetlo", "light", "lampa", "pohyb", "motion", "teplota",
           "temperature", "vlhkost", "humidity", "co2", "the", "v", "na", "ve", "u"}


def room_words(name: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", fold(name)) if len(w) > 2 and w not in GENERIC}


def pair(a: dict, pool: list[dict]) -> dict | None:
    """The entity in `pool` from the same room as `a` (by the words of their names: "Okno ložnice" ↔ "Topení ložnice")."""
    wa = room_words(a["name"]) | room_words(a["id"].split(".", 1)[1])
    best, score = None, 0
    for b in pool:
        wb = room_words(b["name"]) | room_words(b["id"].split(".", 1)[1])
        s = len(wa & wb)
        if s > score:
            best, score = b, s
    return best


def _is(e: dict, domain: str, classes: tuple[str, ...] = (), words: str = "") -> bool:
    if e["domain"] != domain:
        return False
    if classes and e["cls"] in classes:
        return True
    return bool(words) and bool(re.search(words, fold(e["name"] + " " + e["id"])))


def windows(st: list[dict]) -> list[dict]:
    return [e for e in st if _is(e, "binary_sensor", ("window", "opening"), r"\bokn|window")]


def power_sensors(st: list[dict]) -> list[dict]:
    return [e for e in st if e["domain"] == "sensor" and (e["cls"] == "power" or e["unit"] in ("W", "kW")) and e["value"] is not None]


def watts(e: dict) -> float:
    return float(e["value"] or 0) * (1000 if e["unit"] == "kW" else 1)


class State:
    """What the minute checks remember between minutes (since when a thing is on, what was said)."""

    def __init__(self) -> None:
        self.since: dict[str, float] = {}
        self.said: dict[str, float] = {}
        self.saved_hvac: dict[str, str] = {}
        self.washer: dict[str, str] = {}
        self.night_on: dict[str, float] = {}
        self.sim_on: set[str] = set()
        self.last_presence: bool | None = None
        self.solar_day = ""
        self.vacuum_day = ""
        self.water_day = ""

    def held(self, key: str, cond: bool, now: float) -> float:
        """How long `cond` has been true (seconds); 0 when it is not."""
        if not cond:
            self.since.pop(key, None)
            return 0.0
        self.since.setdefault(key, now)
        return now - self.since[key]

    def once(self, key: str, now: float, every: float) -> bool:
        if key in self.said and now - self.said[key] < every:
            return False
        self.said[key] = now
        return True


def state(rt: Any) -> State:
    s = getattr(rt, "homex_state", None)
    if s is None:
        s = rt.homex_state = State()
    return s


Service = Callable[[str, str, dict], Any]


# ------------------------------------------------------------------ (161) okno a topení
async def window_heating(rt: Any, st: list[dict], now: float, service: Service) -> list[str]:
    s = state(rt)
    out: list[str] = []
    climates = [e for e in st if e["domain"] == "climate"]
    overrides = _get(rt, "window_climate", {}) or {}
    for w in windows(st):
        cl_id = overrides.get(w["id"])
        cl = next((c for c in climates if c["id"] == cl_id), None) if cl_id else pair(w, climates)
        if cl is None:
            continue
        open_for = s.held(f"win:{w['id']}", w["state"] == "on", now)
        if open_for >= 120 and cl["state"] not in ("off", "unavailable") and cl["id"] not in s.saved_hvac:
            s.saved_hvac[cl["id"]] = cl["state"]
            await service("climate", "set_hvac_mode", {"entity_id": cl["id"], "hvac_mode": "off"})
            out.append(f"{w['name']} je otevřené – vypnul jsem {cl['name']}. Po zavření ho zase zapnu.")
        elif w["state"] == "off" and cl["id"] in s.saved_hvac:
            mode = s.saved_hvac.pop(cl["id"])
            await service("climate", "set_hvac_mode", {"entity_id": cl["id"], "hvac_mode": mode})
            out.append(f"{w['name']} zavřené – {cl['name']} zase topí.")
    return out


# ------------------------------------------------------------------ (162) zapomenuté spotřebiče, (179) sporák
STOVE = r"sporak|varn|trouba|stove|oven|cooktop|hob"


def forgotten(rt: Any, st: list[dict], away: bool, now: float) -> list[dict]:
    """Power sensors drawing a lot for long while nobody is home (162) – and the stove with nobody in the kitchen (179)."""
    s = state(rt)
    out = []
    min_w = float(_get(rt, "forgotten_watts", 60) or 60)
    kitchen_motion = [e for e in st if _is(e, "binary_sensor", ("motion", "occupancy", "presence"), r"pohyb|motion")
                      and re.search(r"kuchyn|kitchen", fold(e["name"] + e["id"]))]
    for e in power_sensors(st):
        w = watts(e)
        stove = bool(re.search(STOVE, fold(e["name"] + " " + e["id"])))
        if stove:
            nobody = not any(m["state"] == "on" for m in kitchen_motion)
            quiet = s.held(f"kitchen_quiet:{e['id']}", nobody, now)
            on_for = s.held(f"stove:{e['id']}", w > 300, now)
            if on_for >= 45 * 60 and (quiet >= 20 * 60 or away) and s.once(f"stove:{e['id']}", now, 1800):
                out.append({"id": e["id"], "kind": "stove", "watts": round(w), "minutes": int(on_for // 60),
                            "text": f"{e['name']} je zapnutý {int(on_for // 60)} min a v kuchyni nikdo není."})
            continue
        on_for = s.held(f"pow:{e['id']}", away and w >= min_w, now)
        if on_for >= 30 * 60 and s.once(f"pow:{e['id']}", now, 4 * 3600):
            out.append({"id": e["id"], "kind": "power", "watts": round(w), "minutes": int(on_for // 60),
                        "text": f"Nikdo není doma a {e['name']} bere {round(w)} W už {int(on_for // 60)} min."})
    return out


def switch_for(e_id: str, st: list[dict]) -> dict | None:
    """The plug / switch that powers a power sensor (sensor.pracka_power → switch.pracka)."""
    base = re.sub(r"_(power|vykon|spotreba|watts?|current_consumption|energy_power)$", "", e_id.split(".", 1)[1])
    sw = [e for e in st if e["domain"] == "switch"]
    return next((e for e in sw if e["id"].split(".", 1)[1] == base), None) or next((e for e in sw if base in e["id"]), None)


# ------------------------------------------------------------------ (165) prádlo hotovo
WASHER = r"prack|washer|washing|susick|dryer|mycka|dishwasher"


def washer(rt: Any, st: list[dict], now: float) -> list[str]:
    s = state(rt)
    out = []
    for e in power_sensors(st):
        if not re.search(WASHER, fold(e["name"] + " " + e["id"])):
            continue
        w = watts(e)
        key = e["id"]
        phase = s.washer.get(key, "idle")
        if phase == "idle" and s.held(f"wash_run:{key}", w > 10, now) >= 300:
            s.washer[key] = "running"
        elif phase == "running" and s.held(f"wash_end:{key}", w < 3, now) >= 180:
            s.washer[key] = "idle"
            what = "Myčka doběhla – nádobí je čisté." if re.search(r"mycka|dish", fold(e["name"] + e["id"])) else (
                "Sušička doběhla." if re.search(r"susick|dryer", fold(e["name"] + e["id"])) else "Prádlo je hotové – pračka doprala.")
            out.append(what)
    return out


# ------------------------------------------------------------------ (166) vzduch
def air(rt: Any, st: list[dict], now: float) -> list[str]:
    s = state(rt)
    out = []
    co2_max = float(_get(rt, "co2_max", 1200) or 1200)
    for e in st:
        if e["domain"] != "sensor" or e["value"] is None:
            continue
        v = float(e["value"])
        if e["cls"] == "carbon_dioxide" or e["unit"] == "ppm":
            if v >= co2_max and s.once(f"co2:{e['id']}", now, 2 * 3600):
                out.append(f"{e['name']}: CO₂ {int(v)} ppm – vyvětrej na pár minut, soustředění se vrátí.")
        elif e["cls"] == "humidity" or (e["unit"] == "%" and re.search(r"vlhk|humid", fold(e["name"]))):
            if v >= 65 and s.once(f"hum:{e['id']}", now, 4 * 3600):
                out.append(f"{e['name']}: vlhkost {int(v)} % – vyvětrej, ať se nedělá plíseň.")
            elif v <= 30 and s.once(f"dry:{e['id']}", now, 12 * 3600):
                out.append(f"{e['name']}: vlhkost jen {int(v)} % – vzduch je suchý, pomůže zvlhčovač nebo mokrý ručník.")
    return out


# ------------------------------------------------------------------ (167) noční světlo
def in_window(spec: str, clock: dt.datetime) -> bool:
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*-\s*(\d{1,2})[:.](\d{2})\s*", spec or "")
    if not m:
        return False
    a, b = int(m.group(1)) * 60 + int(m.group(2)), int(m.group(3)) * 60 + int(m.group(4))
    t = clock.hour * 60 + clock.minute
    return a <= t < b if a < b else (t >= a or t < b)


async def night_light(rt: Any, st: list[dict], now: float, clock: dt.datetime, service: Service) -> list[str]:
    spec = str(_get(rt, "night_light", "") or "")
    if not spec:
        return []
    s = state(rt)
    out = []
    lights = [e for e in st if e["domain"] == "light"]
    night = in_window(spec, clock)
    for m in [e for e in st if _is(e, "binary_sensor", ("motion", "occupancy"), r"pohyb|motion")]:
        lt = pair(m, lights)
        if lt is None:
            continue
        if night and m["state"] == "on" and lt["state"] == "off" and lt["id"] not in s.night_on:
            await service("light", "turn_on", {"entity_id": lt["id"], "brightness_pct": int(_get(rt, "night_brightness", 8) or 8)})
            s.night_on[lt["id"]] = now
            out.append(lt["id"])
    for lid, at in list(s.night_on.items()):
        if now - at >= 120:
            await service("light", "turn_off", {"entity_id": lid})
            s.night_on.pop(lid, None)
    return out


# ------------------------------------------------------------------ (168) simulace přítomnosti
async def simulate(rt: Any, st: list[dict], away: bool, clock: dt.datetime, service: Service,
                   rnd: random.Random | None = None) -> list[str]:
    if not _get(rt, "simulate", True):
        return []
    from .phonex import vacation_on

    s = state(rt)
    if not (vacation_on(rt, clock.date()) and away):
        for lid in list(s.sim_on):
            await service("light", "turn_off", {"entity_id": lid})
        s.sim_on.clear()
        return []
    rnd = rnd or random.Random()
    pool = [e for e in st if e["domain"] == "light" and (not _get(rt, "simulate_lights") or e["id"] in _get(rt, "simulate_lights"))]
    evening = 17 <= clock.hour < 23
    changed = []
    if not evening:
        for lid in list(s.sim_on):
            await service("light", "turn_off", {"entity_id": lid})
            s.sim_on.discard(lid)
            changed.append(f"-{lid}")
        return changed
    if pool and rnd.random() < 0.12:                    # about every 8 minutes something changes, like people moving
        lt = rnd.choice(pool)
        if lt["id"] in s.sim_on:
            await service("light", "turn_off", {"entity_id": lt["id"]})
            s.sim_on.discard(lt["id"])
            changed.append(f"-{lt['id']}")
        elif len(s.sim_on) < 3:
            await service("light", "turn_on", {"entity_id": lt["id"]})
            s.sim_on.add(lt["id"])
            changed.append(f"+{lt['id']}")
    return changed


# ------------------------------------------------------------------ (169) únik vody, (178) garáž
def leaks(rt: Any, st: list[dict], now: float) -> list[str]:
    s = state(rt)
    out = []
    for e in st:
        if _is(e, "binary_sensor", ("moisture",), r"unik|zaplav|leak|water_leak|voda") and e["state"] == "on":
            if s.once(f"leak:{e['id']}", now, 1800):
                out.append(f"Únik vody: {e['name']}! Zavři přívod vody a podívej se tam.")
    return out


def garage(rt: Any, st: list[dict], now: float) -> list[dict]:
    s = state(rt)
    out = []
    for e in st:
        is_door = e["domain"] == "cover" and (e["cls"] in ("garage", "gate") or re.search(r"garaz|vrata|brana|gate|garage", fold(e["name"] + e["id"])))
        is_sensor = _is(e, "binary_sensor", ("garage_door",), r"garaz|vrata|garage")
        if not (is_door or is_sensor):
            continue
        opened = e["state"] in ("open", "opening") or (is_sensor and e["state"] == "on")
        held = s.held(f"garage:{e['id']}", opened, now)
        if held >= 10 * 60 and s.once(f"garage:{e['id']}", now, 1800):
            out.append({"id": e["id"], "cover": is_door, "text": f"{e['name']} jsou otevřená už {int(held // 60)} min."})
    return out


# ------------------------------------------------------------------ (164) teploty po místnostech
def room_temps(st: list[dict], away: bool = False, open_windows: list[dict] | None = None) -> dict:
    climates = [e for e in st if e["domain"] == "climate"]
    temps = [e for e in st if e["domain"] == "sensor" and (e["cls"] == "temperature" or e["unit"] in ("°C", "°F")) and e["value"] is not None]
    rows, tips = [], []
    wins = open_windows if open_windows is not None else [w for w in windows(st) if w["state"] == "on"]
    for c in climates:
        a = c["attrs"]
        cur = _num(a.get("current_temperature"))
        if cur is None:
            t = pair(c, temps)
            cur = float(t["value"]) if t else None
        target = _num(a.get("temperature"))
        heating = c["state"] in ("heat", "auto") and (a.get("hvac_action") in (None, "heating"))
        rows.append({"id": c["id"], "name": c["name"], "current": cur, "target": target, "heating": heating})
        if heating and cur is not None and target is not None and cur > target + 1.5:
            tips.append(f"{c['name']}: {cur:.1f} °C při cíli {target:.0f} °C – přetápí se, zkontroluj hlavici.")
        if heating and any(pair(w, [c]) for w in wins):
            tips.append(f"{c['name']}: topí se při otevřeném okně.")
        if heating and away and target is not None and target > 19:
            tips.append(f"{c['name']}: nikdo není doma a cíl je {target:.0f} °C – útlum na 17 °C ušetří.")
        if c["state"] == "heat" and target is not None and target >= 24:
            tips.append(f"{c['name']}: {target:.0f} °C je hodně – každý stupeň dolů je zhruba 6 % úspora.")
    if not climates:
        rows = [{"id": t["id"], "name": t["name"], "current": float(t["value"]), "target": None, "heating": None} for t in temps]
    return {"rooms": rows, "tips": tips}


# ------------------------------------------------------------------ (171) baterie v čidlech s předpovědí
def batt_record(rt: Any, items: list[dict], day: dt.date) -> None:
    with rt.db.lock:
        rt.db.conn.executescript(SCHEMA)
    for b in items:
        rt.db.exec("INSERT OR REPLACE INTO hx_batt VALUES (?,?,?)", (day.isoformat(), b["id"], float(b["level"])))


def batt_forecast(rt: Any, eid: str, today: dt.date) -> int | None:
    """Days until 10 % from the last 60 days' readings (a straight line); None when it does not drop."""
    with rt.db.lock:
        rt.db.conn.executescript(SCHEMA)
    rows = rt.db.all("SELECT day, level FROM hx_batt WHERE id=? AND day >= ? ORDER BY day", (eid, (today - dt.timedelta(days=60)).isoformat()))
    if len(rows) < 5:
        return None
    xs = [(dt.date.fromisoformat(r["day"]) - today).days for r in rows]
    ys = [float(r["level"]) for r in rows]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if not den:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    if slope >= -0.01:
        return None
    level_now = my + slope * (0 - mx)
    return max(0, int((10 - level_now) / slope))


# ------------------------------------------------------------------ (172) fotovoltaika, (173) zalévání
async def solar(rt: Any, st: list[dict], now: float, clock: dt.datetime, service: Service) -> str:
    ent = str(_get(rt, "solar_entity", "") or "")
    loads = list(_get(rt, "solar_loads", []) or [])
    if not ent or not loads:
        return ""
    s = state(rt)
    e = next((x for x in st if x["id"] == ent), None)
    if e is None or e["value"] is None:
        return ""
    surplus = watts(e)
    need = float(_get(rt, "solar_watts", 1500) or 1500)
    held = s.held("solar", surplus >= need, now)
    if held >= 600 and s.solar_day != clock.date().isoformat():
        s.solar_day = clock.date().isoformat()
        for ld in loads:
            await service(ld.split(".", 1)[0], "turn_on", {"entity_id": ld})
        return f"Slunce dává {int(surplus)} W navíc – pustil jsem {', '.join(loads)}."
    return ""


def rain_expected(rt: Any, day: dt.date) -> tuple[bool, str]:
    from .proactx import weather

    w = weather(rt) or {}
    d = w.get("daily") or {}
    days = d.get("time") or []
    probs = d.get("precipitation_probability_max") or []
    for k, ds in enumerate(days):
        if ds in (day.isoformat(), (day + dt.timedelta(days=1)).isoformat()) and k < len(probs) and (probs[k] or 0) >= 60:
            return True, f"{'dnes' if ds == day.isoformat() else 'zítra'} {probs[k]} % na déšť"
    return False, ""


async def watering(rt: Any, clock: dt.datetime, service: Service) -> str:
    ent = str(_get(rt, "watering_entity", "") or "")
    at = str(_get(rt, "watering_time", "06:00") or "06:00")
    if not ent or clock.strftime("%H:%M") != at:
        return ""
    s = state(rt)
    if s.water_day == clock.date().isoformat():
        return ""
    s.water_day = clock.date().isoformat()
    rain, why = rain_expected(rt, clock.date())
    if rain:
        return f"Zalévání dnes vynechám – {why}."
    mins = int(_get(rt, "watering_minutes", 15) or 15)
    await service(ent.split(".", 1)[0], "turn_on", {"entity_id": ent})
    s.since["water_off"] = time.time() + mins * 60
    return f"Zalévám {mins} min (déšť se nečeká)."


async def watering_off(rt: Any, now: float, service: Service) -> bool:
    s = state(rt)
    off_at = s.since.get("water_off")
    ent = str(_get(rt, "watering_entity", "") or "")
    if off_at and now >= off_at and ent:
        s.since.pop("water_off", None)
        await service(ent.split(".", 1)[0], "turn_off", {"entity_id": ent})
        return True
    return False


# ------------------------------------------------------------------ (175) vysavač, (180) kamery a soukromí
async def vacuum(rt: Any, st: list[dict], away: bool, now: float, clock: dt.datetime, service: Service) -> str:
    days = _get(rt, "vacuum_days", []) or []
    if not days or clock.weekday() not in days or not 9 <= clock.hour < 18:
        return ""
    s = state(rt)
    if s.vacuum_day == clock.date().isoformat():
        return ""
    away_for = s.held("away", away, now)
    vac = next((e for e in st if e["domain"] == "vacuum" and e["state"] in ("docked", "idle")), None)
    if vac is None or away_for < 15 * 60:
        return ""
    s.vacuum_day = clock.date().isoformat()
    await service("vacuum", "start", {"entity_id": vac["id"]})
    return f"Nikdo není doma – {vac['name']} jde uklízet."


async def camera_privacy(rt: Any, home_now: bool | None, service: Service) -> str:
    ents = list(_get(rt, "privacy_cameras", []) or [])
    if not ents or home_now is None:
        return ""
    s = state(rt)
    if s.last_presence == home_now:
        return ""
    s.last_presence = home_now
    for e in ents:
        await service(e.split(".", 1)[0], "turn_off" if home_now else "turn_on", {"entity_id": e})
    return "Jsi doma – kamery uvnitř jsem vypnul." if home_now else "Nikdo není doma – kamery uvnitř hlídají."


# ------------------------------------------------------------------ (170) mapa domu
def house_map(st: list[dict], rooms: list[dict] | None = None, positions: dict | None = None) -> dict:
    """Rooms (from Home Assistant's areas, or guessed from names) with their lights, doors, windows and temperatures."""
    shown = [e for e in st if e["domain"] in ("light", "lock", "cover", "climate") or (e["domain"] == "binary_sensor" and e["cls"] in
             ("door", "window", "opening", "garage_door", "moisture", "motion")) or (e["domain"] == "sensor" and e["cls"] == "temperature")]
    out_rooms = []
    if rooms:
        for r in rooms:
            ids = {d["id"] for d in r.get("devices", [])}
            out_rooms.append({"name": r["name"], "items": [_item(e) for e in shown if e["id"] in ids]})
    else:
        groups: dict[str, list[dict]] = {}
        for e in shown:
            w = sorted(room_words(e["name"]))
            groups.setdefault(w[0] if w else "ostatní", []).append(e)
        out_rooms = [{"name": k, "items": [_item(e) for e in v]} for k, v in sorted(groups.items())]
    pins = [{"id": k, "x": float(v[0]), "y": float(v[1]), **_item(next(e for e in st if e["id"] == k))}
            for k, v in (positions or {}).items() if any(e["id"] == k for e in st)]
    return {"rooms": out_rooms, "pins": pins}


def _item(e: dict) -> dict:
    v = e["state"]
    if e["domain"] == "sensor" and e["value"] is not None:
        v = f"{e['value']:.1f} {e['unit']}".strip()
    elif e["domain"] == "climate":
        v = f"{e['attrs'].get('current_temperature', '?')} °C"
    alert = (e["domain"] == "binary_sensor" and e["state"] == "on" and e["cls"] in ("moisture",)) or (e["domain"] == "lock" and e["state"] == "unlocked")
    return {"id": e["id"], "name": e["name"], "domain": e["domain"], "value": str(v), "on": e["state"] in ("on", "open", "unlocked", "heat"),
            "alert": bool(alert)}


def map_html(data: dict, floorplan: str = "") -> str:
    def esc(x: Any) -> str:
        return html.escape(str(x))

    tiles = "".join(f"<section><h2>{esc(r['name'])}</h2>" + "".join(
        f"<div class='i{' on' if i['on'] else ''}{' alert' if i['alert'] else ''}'><span>{esc(i['name'])}</span><b>{esc(i['value'])}</b></div>"
        for i in r["items"]) + "</section>" for r in data["rooms"] if r["items"])
    plan = ""
    if floorplan:
        plan = f"<div class=plan><img src='{esc(floorplan)}' alt='Půdorys'>" + "".join(
            f"<i class='pin{' on' if p['on'] else ''}{' alert' if p['alert'] else ''}' style='left:{p['x']:.1f}%;top:{p['y']:.1f}%' "
            f"title='{esc(p['name'])}: {esc(p['value'])}'></i>" for p in data["pins"]) + "</div>"
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<meta http-equiv=refresh content=15><title>Mapa domu</title><style>body{font:14px system-ui;margin:16px;background:#0b0f14;"
            "color:#e8eef5}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}section{background:#121a23;"
            "border-radius:14px;padding:12px}h2{font-size:15px;margin:0 0 8px;text-transform:capitalize}.i{display:flex;justify-content:"
            "space-between;padding:4px 0;color:#9fb4c8}.i.on b{color:#ffd36e}.i.alert b{color:#ff453a}.plan{position:relative;"
            "max-width:900px;margin-bottom:16px}.plan img{width:100%;border-radius:12px}.pin{position:absolute;width:14px;height:14px;"
            "margin:-7px;border-radius:50%;background:#556}.pin.on{background:#ffd36e}.pin.alert{background:#ff453a}</style>"
            f"<h1>Mapa domu</h1>{plan}<main>{tiles or '<p>Žádná zařízení k zobrazení.</p>'}</main>")


# ------------------------------------------------------------------ (174) zámek, (176) profily, (163) zvonek
def locks(st: list[dict]) -> dict:
    ls = [e for e in st if e["domain"] == "lock"]
    open_ = [e for e in ls if e["state"] != "locked"]
    doors = [e for e in st if _is(e, "binary_sensor", ("door",), r"dvere|door") and e["state"] == "on"]
    if not ls and not doors:
        return {"ok": None, "text": "Nemám v domě žádný zámek ani čidlo dveří."}
    if not open_ and not doors:
        return {"ok": True, "text": "Ano, všechno je zamčené" + (f" ({', '.join(e['name'] for e in ls)})." if ls else ".")}
    parts = [f"{e['name']} je {'odemčený' if e['state'] == 'unlocked' else e['state']}" for e in open_]
    parts += [f"{e['name']} jsou otevřené" for e in doors]
    return {"ok": False, "text": "Ne – " + ", ".join(parts) + "."}


async def lock_photo(rt: Any) -> bytes:
    cam = str(_get(rt, "lock_camera", "") or getattr(rt.cfg.home, "door_camera", "") or "")
    if not cam or getattr(rt, "home", None) is None:
        return b""
    try:
        async with rt.http() as c:
            r = await c.get(rt.home._url(f"/api/camera_proxy/{cam}"), headers=rt.home._headers(), timeout=8)
        return r.content if r.status_code == 200 else b""
    except Exception:  # noqa: BLE001
        return b""


def profile_actions(rt: Any, person: str) -> list[tuple[str, str, dict]]:
    """(176) "moje světla" for each member of the family: their lights and temperatures as service calls."""
    profiles = _get(rt, "profiles", {}) or {}
    key = next((k for k in profiles if fold(k) == fold(person)), None)
    if key is None:
        return []
    p = profiles[key] or {}
    calls: list[tuple[str, str, dict]] = []
    for ent, val in (p.get("lights") or {}).items():
        if int(val) <= 0:
            calls.append(("light", "turn_off", {"entity_id": ent}))
        else:
            calls.append(("light", "turn_on", {"entity_id": ent, "brightness_pct": int(val)}))
    for ent, temp in (p.get("climate") or {}).items():
        calls.append(("climate", "set_temperature", {"entity_id": ent, "temperature": float(temp)}))
    for ent in p.get("scenes") or []:
        calls.append(("scene", "turn_on", {"entity_id": ent}))
    return calls


async def door_say(rt: Any, text: str) -> dict:
    """(163) the answer at the doorbell: your words through the door's speaker ("Hned jsem tam", "Nechte to u dveří")."""
    from . import house

    where = str(_get(rt, "door_speaker", "") or "dveře")
    return await house.announce(rt, text, where)


# ------------------------------------------------------------------ (177) Matter přímo (python-matter-server)
class Matter:
    """A thin client of python-matter-server (the same local server Home Assistant uses; ws://<host>:5580/ws). No cloud:
    the commands go from this PC to the server on your network and over Thread / Wi-Fi to the device."""

    def __init__(self, url: str, connect: Callable[..., Any] | None = None):
        self.url = url
        self._connect = connect
        self._n = 0

    def message(self, command: str, **args: Any) -> dict:
        self._n += 1
        return {"message_id": str(self._n), "command": command, "args": args}

    async def call(self, command: str, **args: Any) -> Any:
        if self._connect is None:
            import websockets

            connect: Callable[..., Any] = websockets.connect
        else:
            connect = self._connect
        msg = self.message(command, **args)
        async with connect(self.url) as ws:
            await ws.recv()                                    # the server's info first
            await ws.send(json.dumps(msg))
            while True:
                r = json.loads(await ws.recv())
                if r.get("message_id") == msg["message_id"]:
                    if "error_code" in r:
                        raise RuntimeError(r.get("details") or f"Matter chyba {r['error_code']}")
                    return r.get("result")

    async def nodes(self) -> list[dict]:
        out = []
        for n in await self.call("get_nodes") or []:
            attrs = n.get("attributes") or {}
            out.append({"node": n.get("node_id"), "name": attrs.get("0/40/5") or attrs.get("0/40/3") or f"Uzel {n.get('node_id')}",
                        "vendor": attrs.get("0/40/1") or "", "available": n.get("available", True),
                        "on": attrs.get("1/6/0")})
        return out

    async def onoff(self, node: int, on: bool, endpoint: int = 1) -> Any:
        return await self.call("device_command", node_id=int(node), endpoint_id=endpoint, cluster_id=6,
                               command_name="On" if on else "Off", payload={})

    async def commission(self, code: str) -> Any:
        if not re.fullmatch(r"(MT:[0-9A-Z.\-]+|\d{11}|\d{21})", code.strip()):
            raise ValueError("Kód napiš tak, jak je u zařízení (MT:… z QR kódu nebo 11 číslic).")
        return await self.call("commission_with_code", code=code.strip())


def matter(rt: Any) -> Matter:
    return Matter(str(_get(rt, "matter_url", "") or "ws://localhost:5580/ws"))


# ------------------------------------------------------------------ the minute tick
async def tick(rt: Any, now: float | None = None, clock: dt.datetime | None = None, raw: list[dict] | None = None) -> list[str]:
    """One look at the house (every minute when Home Assistant is set). Returns what was said (for tests)."""
    from . import home

    if raw is None:
        if not home.configured(rt):
            return []
        from .homeplus import raw_states

        raw = await raw_states(rt)
    now = now or time.time()
    clock = clock or dt.datetime.fromtimestamp(now)
    st = norm(raw)
    hs = getattr(rt, "house", None)
    home_now = getattr(hs, "home", None) if hs is not None else None
    away = home_now is False

    async def service(domain: str, svc: str, data: dict) -> None:
        await rt.home.service(domain, svc, data)

    said: list[str] = []

    def tell(title: str, body: str, urgent: bool = False, actions: list[dict] | None = None) -> None:
        rt.notify(title, body, speak=urgent, urgent=urgent, actions=actions)
        if urgent or away:
            rt.phone_push("notify", title=title, body=body[:400])
        said.append(body)

    for t in await window_heating(rt, st, now, service):
        tell("Okno a topení", t)
    for f in forgotten(rt, st, away, now):
        sw = switch_for(f["id"], st)
        acts = [{"label": "Vypnout", "action": "ask", "args": {"text": f"vypni {sw['name']}"}}] if sw else None
        tell("Zapomenutý spotřebič" if f["kind"] == "power" else "Sporák", f["text"], urgent=f["kind"] == "stove", actions=acts)
    for t in washer(rt, st, now):
        tell("Hotovo", t)
    for t in air(rt, st, now):
        tell("Vzduch", t)
    await night_light(rt, st, now, clock, service)
    await simulate(rt, st, away, clock, service)
    for t in leaks(rt, st, now):
        tell("Únik vody", t, urgent=True)
        try:
            from .phonex import watch_tap

            watch_tap(rt, "urgent", t)
        except Exception:  # noqa: BLE001
            pass
    for g in garage(rt, st, now):
        tell("Garáž", g["text"], actions=[{"label": "Zavřít", "action": "ask", "args": {"text": f"zavři {g['id']}"}}] if g["cover"] else None)
    t = await solar(rt, st, now, clock, service)
    if t:
        tell("Fotovoltaika", t)
    t = await watering(rt, clock, service)
    if t:
        tell("Zalévání", t)
    await watering_off(rt, now, service)
    t = await vacuum(rt, st, away, now, clock, service)
    if t:
        tell("Úklid", t)
    t = await camera_privacy(rt, home_now, service)
    if t:
        said.append(t)
    if clock.hour == 9 and clock.minute == 0:
        from .homeplus import low_batteries

        items = low_batteries(raw)
        batt_record(rt, items, clock.date())
        if clock.weekday() == 5:                              # Saturday morning: what will run out within two weeks
            soon = []
            for b in items:
                days = batt_forecast(rt, b["id"], clock.date())
                if b["low"] or (days is not None and days <= 14):
                    soon.append(f"{b['name']} ({int(b['level'])} %" + (f", asi {days} dní" if days is not None else "") + ")")
            if soon:
                tell("Baterie v čidlech", "Brzy vyměnit: " + ", ".join(soon[:8]) + ".")
    return said
