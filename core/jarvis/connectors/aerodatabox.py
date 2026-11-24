"""3.14 Cestovní režim (návrh 47): AeroDataBox – the real departure time, delay, terminal and gate of a flight by its
number. A free key (a few hundred lookups a month) from RapidAPI; without it JARVIS still knows the flight from your
e-mail and where the plane is right now (OpenSky), only not the gate and the delay."""
from __future__ import annotations

import re
from typing import Any

from . import ServiceError, http, need, register, value

HOST = "aerodatabox.p.rapidapi.com"


def _time(block: dict, key: str) -> str:
    t = block.get(key) or {}
    return str(t.get("local") or t.get("utc") or "") if isinstance(t, dict) else str(t or "")


def summarize(flights: list[dict]) -> dict:
    """The first flight of AeroDataBox's answer as {status, dep_sched, dep_revised, terminal, gate, arr_sched, arr_revised}."""
    if not flights:
        return {}
    f = flights[0]
    dep, arr = f.get("departure") or {}, f.get("arrival") or {}
    return {"status": str(f.get("status") or ""), "dep_sched": _time(dep, "scheduledTime"), "dep_revised": _time(dep, "revisedTime"),
            "terminal": str(dep.get("terminal") or ""), "gate": str(dep.get("gate") or ""), "arr_sched": _time(arr, "scheduledTime"),
            "arr_revised": _time(arr, "revisedTime"), "from": ((dep.get("airport") or {}).get("iata") or ""),
            "to": ((arr.get("airport") or {}).get("iata") or ""), "airline": ((f.get("airline") or {}).get("name") or "")}


async def flight(number: str, date: str, transport=None) -> dict:
    need("aerodatabox")
    num = re.sub(r"\s+", "", number or "").upper()
    async with http(transport=transport, timeout=20) as c:
        r = await c.get(f"https://{HOST}/flights/number/{num}/{date}",
                        headers={"X-RapidAPI-Key": value("aerodatabox", "api_key").strip(), "X-RapidAPI-Host": HOST})
    if r.status_code in (401, 403):
        raise ServiceError("AeroDataBox nepřijal klíč – zkopíruj ho znovu z RapidAPI.")
    if r.status_code in (204, 404):
        return {}
    r.raise_for_status()
    data = r.json()
    return summarize(data if isinstance(data, list) else [data])


async def _test(rt: Any) -> str:
    await flight("OK100", "2026-01-01")
    return "Propojeno – klíč platí."


register("aerodatabox", "AeroDataBox (lety)", "airplane-tilt", [
    {"key": "api_key", "label": "RapidAPI klíč", "secret": True, "hint": "X-RapidAPI-Key"},
], [
    "Na rapidapi.com si založ účet a otevři API „AeroDataBox“.",
    "Zvol plán Basic (zdarma) a zkopíruj X-RapidAPI-Key.",
    "Vlož ho sem – JARVIS pak u letů z tvých e-mailů hlídá zpoždění, terminál a gate.",
], url="https://rapidapi.com/aedbx-aedbx/api/aerodatabox", what="Skutečný čas odletu, zpoždění, terminál a gate tvých letů – jen čtení.",
    test=_test, group="travel",
    probe={"method": "GET", "url": f"https://{HOST}/flights/number/OK100/2026-01-01",
           "headers": {"X-RapidAPI-Key": "0" * 50, "X-RapidAPI-Host": HOST}})
