"""3.18 Rezervace cest: the keys for LiteAPI (hotels) and Duffel (flights + hotels). booking.py does the work; here they
are only registered (Nastavení → Propojení), with a check that the key is accepted."""
from __future__ import annotations

from typing import Any

from . import register


async def _test_lite(rt: Any) -> str:
    from ..booking import LITE_API, _lite, sandbox

    await _lite("GET", LITE_API + "/data/hotels", params={"cityName": "Praha", "countryCode": "CZ", "limit": 1})
    return "Propojeno" + (" – zkušební klíč: hledá i rezervuje naoko, nic se nezaplatí." if sandbox() else " – ostrý klíč.")


async def _test_duffel(rt: Any) -> str:
    from ..booking import _duffel

    await _duffel("GET", "/air/airlines", params={"limit": 1})
    return "Propojeno – Duffel přijal token."


register("liteapi", "LiteAPI (hotely)", "bed", [
    {"key": "api_key", "label": "API klíč", "secret": True, "hint": "sand_… (zkušební) nebo ostrý klíč"},
], [
    "Založ si zdarma účet na liteapi.travel – zkušební klíč (sand_…) je hned v profilu, nic neplatíš.",
    "Pro skutečné rezervace v jejich účtu přidej kartu (Payment Methods) – JARVIS kartu nikdy nevidí, platí ji LiteAPI.",
    "Vlož klíč sem. Každou rezervaci potvrdíš ty, dvakrát, s přesnou cenou.",
], url="https://www.liteapi.travel/", what="Hotely po celém světě: hledání podle popisu, rezervace až po tvém potvrzení.",
    test=_test_lite, group="work")

register("duffel", "Duffel (letenky a hotely)", "airplane-tilt", [
    {"key": "access_token", "label": "Přístupový token", "secret": True, "hint": "duffel_test_… nebo duffel_live_…"},
], [
    "Založ si účet na duffel.com a vytvoř přístupový token (zkušební je zdarma).",
    "Ostré rezervace se platí z tvého zůstatku u Duffelu – dobiješ ho v jejich aplikaci.",
    "Vlož token sem. Každou letenku i hotel potvrdíš ty, dvakrát, s přesnou cenou.",
], url="https://duffel.com/", what="Letenky a hotely: hledání, kontrola ceny těsně před platbou, rezervace po potvrzení.",
    test=_test_duffel, group="work")
