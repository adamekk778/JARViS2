"""3.14 Auto (návrhy 11, 46): your car through Home Assistant.

Almost every carmaker's app has a Home Assistant integration (MySkoda, Volkswagen, Tesla, BMW, Kia/Hyundai, Renault,
Mercedes, Polestar, Toyota…) and an OBD adapter can report through it too (ESPHome / Torque Pro). JARVIS finds the
car's entities there by itself – battery or fuel, range, where it stands, the lock, the climate – and then:
"jak je na tom auto", "předehřej auto", "zamkni auto", "připrav auto na 7:30" (the heating starts 15 minutes before).
Unlocking always asks first.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
import re
import unicodedata
from typing import Any

log = logging.getLogger("jarvis.car")

CAR_WORDS = ("car", "auto", "vehicle", "vuz", "skoda", "enyaq", "octavia", "superb", "kodiaq", "fabia", "elroq", "tesla",
             "model_3", "model_y", "volkswagen", "vw_", "id_3", "id_4", "id_7", "bmw", "kia", "hyundai", "ioniq", "niro", "ev6",
             "renault", "zoe", "megane", "peugeot", "polestar", "volvo", "mercedes", "audi", "cupra", "mg4", "byd", "ford",
             "toyota", "nissan", "leaf", "obd", "torque", "mini_", "porsche", "taycan", "seat", "opel", "citroen", "dacia")
ROLES = ("battery", "fuel", "range", "location", "lock", "climate", "charging", "odometer")
LABEL = {"battery": "baterie", "fuel": "palivo", "range": "dojezd", "location": "poloha", "lock": "zámek",
         "climate": "klimatizace / topení", "charging": "nabíjení", "odometer": "najeto"}
PREHEAT_MIN = 15
HOME_KM = 0.3


def _fold(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", s)


def _is_car(e: dict) -> bool:
    key = _fold(e.get("id", "")) + "_" + _fold(e.get("name", "")) + "_"
    return any(w in key for w in CAR_WORDS)


def _role(e: dict) -> str:
    """Which part of the car an entity is ("" = none)."""
    if not _is_car(e):
        return ""
    d = e.get("domain") or e.get("id", "").split(".", 1)[0]
    key = _fold(e.get("id", "")) + "_" + _fold(e.get("name", ""))
    unit = (e.get("unit") or "").lower()
    if d == "device_tracker":
        return "location"
    if d == "lock":
        return "lock"
    if d == "climate" or (d in ("switch", "button") and re.search(r"clima|klima|preheat|predehr|hvac|air_condition|heater|topen", key)):
        return "climate"
    if d in ("switch", "binary_sensor") and re.search(r"charg|nabij", key):
        return "charging"
    if d == "sensor":
        if re.search(r"range|dojezd", key) and unit in ("km", "mi"):
            return "range"
        if re.search(r"odometer|mileage|najet|tachomet", key):
            return "odometer"
        if re.search(r"fuel|palivo|tank", key) and unit == "%":
            return "fuel"
        if re.search(r"battery|baterie|soc|state_of_charge|charge_level", key) and unit == "%":
            return "battery"
    return ""


def discover(states: list[dict]) -> dict[str, str]:
    """role → entity id, the first good candidate for each part of the car."""
    out: dict[str, str] = {}
    for e in states:
        r = _role(e)
        if r and r not in out:
            out[r] = e["id"]
    return out


def entities(rt: Any) -> dict[str, str]:
    return {k: v for k, v in (getattr(rt.cfg.home, "car", None) or {}).items() if k in ROLES and v}


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def describe(parts: dict[str, dict], home: tuple[float, float] | None = None, name: str = "Auto") -> tuple[str, dict]:
    """The sentence and the numbers from the car's entities (role → state dict from Home Assistant)."""
    data: dict[str, Any] = {}
    bits = []
    for role, unit in (("battery", "%"), ("fuel", "%")):
        v = _num((parts.get(role) or {}).get("state"))
        if v is not None:
            data[role] = v
            bits.append(f"{LABEL[role]} {int(v)} {unit}")
    rng = _num((parts.get("range") or {}).get("state"))
    if rng is not None:
        data["range_km"] = rng
        bits.append(f"dojezd {int(rng)} {(parts['range'].get('unit') or 'km')}")
    ch = (parts.get("charging") or {}).get("state")
    if ch in ("on", "charging", "true"):
        data["charging"] = True
        bits.append("nabíjí se")
    lk = (parts.get("lock") or {}).get("state")
    if lk in ("locked", "unlocked"):
        data["locked"] = lk == "locked"
        bits.append("zamčené" if lk == "locked" else "ODEMČENÉ")
    cl = (parts.get("climate") or {}).get("state")
    if cl and cl not in ("off", "unavailable", "unknown"):
        data["climate"] = cl
        bits.append("topí / klimatizuje")
    loc = parts.get("location") or {}
    if loc.get("lat") is not None and loc.get("lon") is not None:
        data["lat"], data["lon"] = float(loc["lat"]), float(loc["lon"])
        if home:
            km = _km(home, (data["lat"], data["lon"]))
            data["home_km"] = round(km, 1)
            bits.append("stojí doma" if km <= HOME_KM else f"je {str(round(km, 1)).replace('.', ',')} km od domova")
    elif loc.get("state") in ("home", "not_home"):
        bits.append("stojí doma" if loc["state"] == "home" else "není doma")
    odo = _num((parts.get("odometer") or {}).get("state"))
    if odo is not None:
        data["odometer"] = odo
    text = f"{name}: " + (", ".join(bits) if bits else "Home Assistant o něm zatím nic neví") + "."
    if data.get("locked") is False and data.get("home_km", 0) > HOME_KM:
        text += " Pozor, auto je odemčené a není doma."
    return text, data


async def status(rt: Any) -> tuple[str, dict]:
    ents = entities(rt)
    if not ents:
        raise LookupError("Auto zatím nemám propojené – řekni „najdi auto v Home Assistantu“.")
    states = {e["id"]: e for e in await rt.home.states(fresh=True)}
    parts = {r: states[i] for r, i in ents.items() if i in states}
    home = None
    try:
        from .eyes import home_coords

        lat, lon, _ = await home_coords(rt)
        home = (lat, lon)
    except Exception as e:  # noqa: BLE001 – no city / offline: no distance
        log.debug("car home: %s", e)
    return describe(parts, home, (getattr(rt.cfg.home, "car", {}) or {}).get("name") or "Auto")


async def climate(rt: Any, on: bool = True) -> str:
    eid = entities(rt).get("climate")
    if not eid:
        raise LookupError("U auta jsem nenašel ovládání topení / klimatizace.")
    d = eid.split(".", 1)[0]
    if d == "button":
        await rt.home.service("button", "press", {"entity_id": eid})
    elif d == "climate":
        await rt.home.service("climate", "turn_on" if on else "turn_off", {"entity_id": eid})
    else:
        await rt.home.service(d, "turn_on" if on else "turn_off", {"entity_id": eid})
    return "Předehřívám auto." if on else "Vypínám topení v autě."


async def lock(rt: Any, locked: bool = True) -> str:
    eid = entities(rt).get("lock")
    if not eid:
        raise LookupError("U auta jsem nenašel zámek.")
    await rt.home.service("lock", "lock" if locked else "unlock", {"entity_id": eid})
    return "Zamykám auto." if locked else "Odemykám auto."


def ready_at(rt: Any, when: str, now: dt.datetime | None = None) -> dict:
    """"Připrav auto na 7:30": the heating starts PREHEAT_MIN before; returns the scheduled job."""
    m = re.match(r"^\s*(\d{1,2})(?:[:.](\d{2}))?\s*$", when or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2) or 0) > 59:
        raise ValueError("Čas zadej jako 7:30.")
    now = now or dt.datetime.now()
    at = now.replace(hour=int(m.group(1)), minute=int(m.group(2) or 0), second=0, microsecond=0)
    if at <= now:
        at += dt.timedelta(days=1)
    start = max(now + dt.timedelta(minutes=1), at - dt.timedelta(minutes=PREHEAT_MIN))
    return rt.scheduler.add_once(start, "car_ready", {"ready": at.strftime("%H:%M")}, title=f"Auto připravené na {at:%H:%M}")


async def run_ready(rt: Any, payload: dict) -> None:
    """The scheduled job: heat (or cool) the car and say so on the phone."""
    try:
        await climate(rt, True)
        text, data = await status(rt)
        extra = ""
        if data.get("battery") is not None and data["battery"] < 25 and not data.get("charging"):
            extra = f" Baterie má jen {int(data['battery'])} %."
        rt.notify("Auto", f"Předehřívám auto, v {payload.get('ready', '')} bude připravené.{extra}", target="all")
    except Exception as e:  # noqa: BLE001
        rt.notify("Auto", f"Auto se nepodařilo připravit: {e}", target="all")
