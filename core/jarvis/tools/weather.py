from __future__ import annotations

from typing import Annotated

from .base import ToolResult, tool

CODES = {0: "jasno", 1: "skoro jasno", 2: "polojasno", 3: "zataženo", 45: "mlha", 48: "mrznoucí mlha",
         51: "slabé mrholení", 53: "mrholení", 55: "silné mrholení", 61: "slabý déšť", 63: "déšť", 65: "silný déšť",
         66: "mrznoucí déšť", 67: "silný mrznoucí déšť", 71: "slabé sněžení", 73: "sněžení", 75: "silné sněžení",
         77: "sněhová zrna", 80: "přeháňky", 81: "přeháňky", 82: "silné přeháňky", 85: "sněhové přeháňky",
         86: "silné sněhové přeháňky", 95: "bouřka", 96: "bouřka s kroupami", 99: "silná bouřka s kroupami"}


async def fetch_weather(ctx, city: str) -> dict:
    async with ctx.http() as c:
        g = (await c.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": city, "count": 1, "language": "cs"}, timeout=15)).json()
        if not g.get("results"):
            raise ValueError(f"Město „{city}“ nenalezeno")
        loc = g["results"][0]
        w = (await c.get("https://api.open-meteo.com/v1/forecast", timeout=15, params={
            "latitude": loc["latitude"], "longitude": loc["longitude"], "timezone": "auto",
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": 4})).json()
    cur = w["current"]
    days = [{"date": d, "desc": CODES.get(code, "?"), "max": mx, "min": mn, "rain_pct": rp}
            for d, code, mx, mn, rp in zip(w["daily"]["time"], w["daily"]["weather_code"],
                                           w["daily"]["temperature_2m_max"], w["daily"]["temperature_2m_min"],
                                           w["daily"]["precipitation_probability_max"])]
    return {"city": loc["name"], "temp": cur["temperature_2m"], "feels": cur["apparent_temperature"],
            "humidity": cur["relative_humidity_2m"], "wind": cur["wind_speed_10m"],
            "desc": CODES.get(cur["weather_code"], "?"), "code": cur["weather_code"], "days": days}


@tool("weather", "Počasí teď a předpověď na 3 dny (zdarma přes Open-Meteo).", category="info")
async def weather(ctx, city: Annotated[str, "město; prázdné = domovské"] = "") -> ToolResult:
    d = await fetch_weather(ctx, city or ctx.cfg.general.city)
    return ToolResult(True, f"{d['city']}: {d['desc']}, {round(d['temp'])} °C (pocitově {round(d['feels'])} °C)", data=d)
