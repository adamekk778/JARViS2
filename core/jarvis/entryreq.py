"""3.19 Vstupní podmínky (návrh 5): what a Czech citizen needs to enter the destination – an ID card is enough, a
passport, an online travel permit (UK ETA, US ESTA, Canada eTA…) or a visa – said when searching, not after booking.

The table is a summary for short tourist trips of Czech citizens (state 2026); rules change, so every answer ends with
where to check it (MZV ČR). Countries not in the table get only that link – JARVIS never guesses.
"""
from __future__ import annotations

from typing import Any

MZV = "https://mzv.gov.cz/jnp/cz/cestujeme/rady_a_informace_pro_cestovani_podle_zemi/index.html"
EU_ID = set("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE IS LI NO CH AD MC SM VA".split())
ID_OK = {"RS", "ME", "AL", "BA", "MK", "MD", "GE"}          # an ID card is accepted for a short tourist stay
NAMES = {"GB": "Velká Británie", "US": "USA", "CA": "Kanada", "AU": "Austrálie", "NZ": "Nový Zéland", "TR": "Turecko",
         "EG": "Egypt", "TH": "Thajsko", "AE": "Spojené arabské emiráty", "JP": "Japonsko", "TN": "Tunisko", "MA": "Maroko",
         "IL": "Izrael", "IN": "Indie", "MX": "Mexiko", "BR": "Brazílie", "UA": "Ukrajina", "RU": "Rusko", "BY": "Bělorusko",
         "RS": "Srbsko", "ME": "Černá Hora", "AL": "Albánie", "BA": "Bosna a Hercegovina", "MK": "Severní Makedonie",
         "MD": "Moldavsko", "GE": "Gruzie"}
# code → (document, what else is needed before the trip, a note)
RULES: dict[str, tuple[str, str, str]] = {
    "GB": ("pas", "elektronické povolení UK ETA (online předem, platí 2 roky)", ""),
    "US": ("biometrický pas", "ESTA (online aspoň 72 hodin před odletem)", "pas musí platit po celou dobu pobytu"),
    "CA": ("pas", "eTA (při příletu letadlem, online předem)", ""),
    "AU": ("pas", "eVisitor (online předem)", ""),
    "NZ": ("pas", "NZeTA (online předem)", ""),
    "TR": ("pas", "", "bez víza do 90 dní"),
    "EG": ("pas", "vízum (při příletu nebo e-vízum předem)", ""),
    "TH": ("pas", "", "krátký pobyt bez víza – délku ověř, mění se"),
    "AE": ("pas", "", "bez víza do 90 dní"),
    "JP": ("pas", "", "bez víza do 90 dní"),
    "TN": ("pas", "", "bez víza do 90 dní"),
    "MA": ("pas", "", "bez víza do 90 dní"),
    "IL": ("pas", "elektronické povolení ETA-IL (online předem)", ""),
    "IN": ("pas", "e-vízum (online předem)", ""),
    "MX": ("pas", "", "bez víza do 180 dní"),
    "BR": ("pas", "", "bez víza do 90 dní"),
    "UA": ("pas", "", "MZV ČR nedoporučuje cesty"),
    "RU": ("pas", "vízum", "MZV ČR nedoporučuje cesty"),
    "BY": ("pas", "", "MZV ČR nedoporučuje cesty"),
}


def check(country: str) -> dict:
    """{code, name, doc, needs, note, ok_with_id, known, line} for a Czech citizen; known=False → only the MZV link."""
    c = (country or "").strip().upper()[:2]
    if not c:
        return {"code": "", "known": False, "line": ""}
    if c in EU_ID:
        return {"code": c, "name": c, "doc": "občanský průkaz", "needs": "", "note": "", "ok_with_id": True, "known": True,
                "line": ""}                                                  # nothing to say
    if c in ID_OK:
        return {"code": c, "name": NAMES.get(c, c), "doc": "občanský průkaz", "needs": "", "note": "krátký turistický pobyt",
                "ok_with_id": True, "known": True,
                "line": f"{NAMES.get(c, c)}: stačí občanský průkaz (krátký turistický pobyt). Ověř na MZV: {MZV}"}
    if c in RULES:
        doc, needs, note = RULES[c]
        parts = [f"{NAMES.get(c, c)}: potřebuješ {doc}"] + ([f"a {needs}"] if needs else []) + ([f"({note})"] if note else [])
        return {"code": c, "name": NAMES.get(c, c), "doc": doc, "needs": needs, "note": note, "ok_with_id": False, "known": True,
                "line": " ".join(parts) + f". Ověř na MZV: {MZV}"}
    return {"code": c, "name": NAMES.get(c, c), "doc": "", "needs": "", "note": "", "ok_with_id": False, "known": False,
            "line": f"Vstupní podmínky pro {NAMES.get(c, c)} si ověř na MZV: {MZV}"}


def warn(rt: Any, country: str) -> str:
    """One line for the search answer ('' inside the EU or when switched off)."""
    if not getattr(getattr(rt.cfg, "booking", None), "entry_warnings", True):
        return ""
    return check(country)["line"]
