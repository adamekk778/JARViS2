"""OMEGA §34 smart home, more: rooms (Home Assistant areas) and control by room, energy use per meter over days, low
batteries, firmware updates waiting, the event history of devices, and a simulator that tests JARVIS's "Když … tak …"
rules against made-up events without running anything."""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict
from typing import Any

from .stark import _fold


async def template(rt, tpl: str) -> str:
    async with rt.http() as c:
        r = await c.post(rt.home._url("/api/template"), headers=rt.home._headers(), json={"template": tpl}, timeout=10)
    r.raise_for_status()
    return r.text


AREAS_TPL = "{% set ns = namespace(o={}) %}{% for a in areas() %}{% set ns.o = dict(ns.o, **{a: {'name': area_name(a), 'entities': area_entities(a)}}) %}{% endfor %}{{ ns.o | tojson }}"


async def rooms(rt) -> list[dict]:
    raw = await template(rt, AREAS_TPL)
    areas = json.loads(raw or "{}")
    states = {s["id"]: s for s in await rt.home.states(fresh=True)}
    out = []
    for aid, a in areas.items():
        ents = [states[e] for e in a.get("entities", []) if e in states]
        out.append({"id": aid, "name": a.get("name") or aid, "devices": ents,
                    "lights_on": sum(1 for e in ents if e["domain"] == "light" and e["state"] == "on"),
                    "temperature": next((e["state"] for e in ents if e["domain"] == "sensor" and e.get("unit") in ("°C", "°F")), None)})
    return sorted(out, key=lambda r: r["name"])


def find_room(rooms_: list[dict], name: str) -> dict | None:
    f = _fold(name)
    return next((r for r in rooms_ if _fold(r["name"]) == f), None) or next((r for r in rooms_ if f in _fold(r["name"]) or _fold(r["name"]) in f), None)


# ============================================================================================== 427 batteries / 431 firmware
async def raw_states(rt) -> list[dict]:
    async with rt.http() as c:
        r = await c.get(rt.home._url("/api/states"), headers=rt.home._headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def low_batteries(states: list[dict], threshold: float = 20) -> list[dict]:
    out = []
    for e in states:
        a = e.get("attributes") or {}
        lvl = None
        if a.get("device_class") == "battery" and e["entity_id"].startswith("sensor."):
            try:
                lvl = float(e["state"])
            except (TypeError, ValueError):
                lvl = None
        elif a.get("battery_level") is not None:
            lvl = float(a["battery_level"])
        elif a.get("device_class") == "battery" and e["entity_id"].startswith("binary_sensor."):
            lvl = 5.0 if e["state"] == "on" else None                     # binary battery sensor: on = low
        if lvl is not None:
            out.append({"id": e["entity_id"], "name": (a.get("friendly_name") or e["entity_id"]).replace(" Battery", "").replace(" baterie", ""),
                        "level": lvl, "low": lvl <= threshold})
    return sorted(out, key=lambda x: x["level"])


def firmware(states: list[dict]) -> list[dict]:
    out = []
    for e in states:
        if not e["entity_id"].startswith("update."):
            continue
        a = e.get("attributes") or {}
        out.append({"id": e["entity_id"], "name": a.get("title") or a.get("friendly_name") or e["entity_id"], "installed": a.get("installed_version"),
                    "latest": a.get("latest_version"), "pending": e.get("state") == "on", "notes": (a.get("release_summary") or "")[:200],
                    "auto": bool(a.get("auto_update"))})
    return sorted(out, key=lambda x: (not x["pending"], x["name"]))


# ============================================================================================== 422 energy
def _is_energy(e: dict) -> bool:
    a = e.get("attributes") or {}
    return a.get("device_class") == "energy" or a.get("unit_of_measurement") in ("kWh", "Wh")


async def energy(rt, days: int = 7) -> dict:
    states = await raw_states(rt)
    meters = [e for e in states if _is_energy(e) and e["entity_id"].startswith("sensor.")]
    if not meters:
        return {"meters": [], "total_kwh": 0}
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    ids = ",".join(m["entity_id"] for m in meters[:40])
    async with rt.http() as c:
        r = await c.get(rt.home._url(f"/api/history/period/{start}"), headers=rt.home._headers(),
                        params={"filter_entity_id": ids, "minimal_response": "", "no_attributes": ""}, timeout=30)
    r.raise_for_status()
    hist = r.json()
    unit = {m["entity_id"]: (m.get("attributes") or {}).get("unit_of_measurement", "kWh") for m in meters}
    names = {m["entity_id"]: (m.get("attributes") or {}).get("friendly_name") or m["entity_id"] for m in meters}
    out = []
    for series in hist:
        if not series:
            continue
        eid = series[0].get("entity_id")
        vals, day = [], defaultdict(float)
        prev = None
        for p in series:
            try:
                v = float(p["state"])
            except (TypeError, ValueError, KeyError):
                continue
            if prev is not None:
                d = v - prev if v >= prev else v          # a meter reset (total_increasing) starts again from 0
                day[str(p.get("last_changed", ""))[:10]] += d
            prev = v
            vals.append(v)
        if not vals:
            continue
        k = 0.001 if unit.get(eid) == "Wh" else 1.0
        total = sum(day.values()) * k
        out.append({"id": eid, "name": names.get(eid, eid), "kwh": round(total, 2), "per_day": {d: round(x * k, 2) for d, x in sorted(day.items())}})
    out.sort(key=lambda m: -m["kwh"])
    return {"meters": out, "total_kwh": round(sum(m["kwh"] for m in out), 2), "days": days}


# ============================================================================================== 433 history
async def logbook(rt, hours: int = 24, entity: str = "") -> list[dict]:
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).isoformat()
    params = {"entity": entity} if entity else {}
    async with rt.http() as c:
        r = await c.get(rt.home._url(f"/api/logbook/{start}"), headers=rt.home._headers(), params=params, timeout=20)
    r.raise_for_status()
    out = []
    for e in r.json():
        out.append({"when": e.get("when", ""), "name": e.get("name") or e.get("entity_id", ""), "entity": e.get("entity_id", ""),
                    "state": e.get("state") or "", "message": e.get("message") or ""})
    return out


# ============================================================================================== 430 simulator
WEEK = {"po": 0, "út": 1, "ut": 1, "st": 2, "čt": 3, "ct": 3, "pá": 4, "pa": 4, "so": 5, "ne": 6}


def simulate(automations: list, events: list[dict]) -> dict:
    """Run the rules against made-up events (nothing is executed): which rule would fire on which event, with the
    steps it would do; rules that never fire; several rules firing on one event."""
    from .automations import describe_steps, fill, match_event

    fired, per_rule = [], defaultdict(int)
    for i, ev in enumerate(events, 1):
        t = ev.get("type")
        hits = []
        for a in automations:
            if not a.enabled:
                continue
            tr = a.trigger
            vars_: dict[str, Any] | None = None
            if t in ("mail", "phone_message", "phone_call"):
                bus = {"mail": {"type": "mail_new", "from": ev.get("from", ""), "from_name": ev.get("from", ""), "subject": ev.get("subject", "")},
                       "phone_message": {"type": "phone_notification", "messaging": True, "title": ev.get("from", ""), "text": ev.get("text", ""), "app": ev.get("app", "")},
                       "phone_call": {"type": "phone_notification", "messaging": True, "call": True, "title": ev.get("from", ""), "app": ev.get("app", "")}}[t]
                vars_ = match_event(a, bus)
            elif t == "time" and tr.type == "time":
                days = tr.days or list(range(7))
                wd = WEEK.get(_fold(str(ev.get("day", "po")))[:2], 0) if isinstance(ev.get("day"), str) else int(ev.get("day", 0))
                if (tr.value or "").strip() == str(ev.get("at", "")).strip() and wd in days:
                    vars_ = {}
            elif t == "battery" and tr.type == "battery":
                if float(ev.get("percent", 100)) < float(tr.value or 20) and not ev.get("plugged"):
                    vars_ = {"percent": ev.get("percent")}
            elif t == "power" and tr.type == "power":
                if (tr.value == "out") == (not ev.get("plugged", False)):
                    vars_ = {}
            elif t in ("app_open", "app_close") and tr.type == t:
                if _fold(tr.value or "") in _fold(str(ev.get("app", ""))):
                    vars_ = {"app": ev.get("app")}
            elif t in ("away", "back") and tr.type == t:
                if float(ev.get("minutes", 0)) >= float(tr.value or 10):
                    vars_ = {}
            elif t == "boot" and tr.type == "boot":
                vars_ = {}
            if vars_ is not None:
                steps = [fill(s, vars_) for s in describe_steps(a.steps)]
                hits.append({"rule": a.name, "steps": steps})
                per_rule[a.name] += 1
        fired.append({"n": i, "event": ev, "rules": hits})
    never = [a.name for a in automations if a.enabled and not per_rule.get(a.name)]
    crowded = [f for f in fired if len(f["rules"]) > 1]
    return {"events": fired, "never_fired": never, "multiple": [{"n": f["n"], "rules": [r["rule"] for r in f["rules"]]} for f in crowded]}


def parse_events(text: str) -> list[dict]:
    """„po 7:00; e-mail od šéf: Porada; zpráva od Máma: ahoj; baterie 15; otevřu Spotify; odejdu 20; start“ → events."""
    out = []
    for part in [p.strip() for p in re.split(r"[;\n]", text) if p.strip()]:
        f = _fold(part)
        if m := re.match(r"(po|ut|st|ct|pa|so|ne)\w*\s+(\d{1,2}:\d{2})", f):
            out.append({"type": "time", "day": m.group(1), "at": m.group(2) if len(m.group(2)) == 5 else "0" + m.group(2)})
        elif m := re.match(r"(?:e-?mail|mail)\s+od\s+(.+?)(?::\s*(.*))?$", part, re.I):
            out.append({"type": "mail", "from": m.group(1).strip(), "subject": (m.group(2) or "").strip()})
        elif m := re.match(r"(?:zpráva|sms|zprava)\s+od\s+(.+?)(?::\s*(.*))?$", part, re.I):
            out.append({"type": "phone_message", "from": m.group(1).strip(), "text": (m.group(2) or "").strip()})
        elif m := re.match(r"(?:hovor|volá|vola)\s+(?:od\s+)?(.+)$", part, re.I):
            out.append({"type": "phone_call", "from": m.group(1).strip()})
        elif m := re.match(r"baterie\s+(\d+)", f):
            out.append({"type": "battery", "percent": int(m.group(1))})
        elif re.match(r"odpoj\w*\s+nabije", f):
            out.append({"type": "power", "plugged": False})
        elif re.match(r"pripoj\w*\s+nabije", f):
            out.append({"type": "power", "plugged": True})
        elif m := re.match(r"(otevru|otevre|zavru|zavre)\s+(.+)$", f):
            out.append({"type": "app_open" if m.group(1).startswith("otev") else "app_close", "app": part.split(maxsplit=1)[1]})
        elif m := re.match(r"(odejdu|vratim se)\s*(\d+)?", f):
            out.append({"type": "away" if m.group(1) == "odejdu" else "back", "minutes": int(m.group(2) or 30)})
        elif f in ("start", "zapnuti", "boot", "spusteni"):
            out.append({"type": "boot"})
        else:
            raise ValueError(f"Událost „{part}“ nerozumím. Příklady: „po 7:00“, „e-mail od šéf: Porada“, „zpráva od Máma: ahoj“, "
                             "„volá Petr“, „baterie 15“, „otevřu Spotify“, „odejdu 20“, „start“.")
    return out
