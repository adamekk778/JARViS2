"""3.13 Heureka – Ověřeno zákazníky: recenze obchodu (posledních 500, Heureka je obnovuje každých 6 hodin) – jen čtení.
The shop's secret key from Heureka's administration of the service; export-review.php gives them as XML."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value

SCORES = ("total_rating", "delivery_time", "transport_quality", "web_usability", "communication")


def url(key: str | None = None) -> str:
    host = "www.heureka.sk" if value("heureka", "country").strip().lower() in ("sk", "slovensko") else "www.heureka.cz"
    return f"https://{host}/direct/dotaznik/export-review.php?key={key if key is not None else value('heureka', 'key').strip()}"


def parse(text: str) -> list[dict]:
    if "<!DOCTYPE" in text[:2000] or "<!ENTITY" in text[:2000]:
        raise ServiceError("Heureka poslala neočekávanou odpověď.")
    if text.lstrip().startswith("ERROR"):
        raise ServiceError("Heureka nepřijala klíč – zkopíruj ho znovu (Ověřeno zákazníky → nastavení).")
    root = ET.fromstring(text.encode("utf-8"))
    out = []
    for r in root.iter("review"):
        d: dict[str, Any] = {c.tag: (c.text or "").strip() for c in r if (c.text or "").strip()}
        for k in SCORES:
            if k in d:
                try:
                    d[k] = float(d[k])
                except ValueError:
                    pass
        out.append(d)
    return out


def score(r: dict) -> float | None:
    """The review's overall stars: Heureka's total, or the average of the parts."""
    if isinstance(r.get("total_rating"), float):
        return r["total_rating"]
    parts = [r[k] for k in SCORES[1:] if isinstance(r.get(k), float)]
    return round(sum(parts) / len(parts), 2) if parts else None


async def reviews(transport=None) -> list[dict]:
    import httpx

    need("heureka")
    try:
        r = await call("GET", url(), transport=transport, timeout=40)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ServiceError("Heureka nepřijala klíč – zkopíruj ho znovu (Ověřeno zákazníky → nastavení).") from None
        raise
    return parse(r.get("text", "") if isinstance(r, dict) else str(r))


async def _test(rt: Any) -> str:
    rs = await reviews()
    s = [x for x in (score(r) for r in rs) if x is not None]
    return f"Propojeno – {len(rs)} recenzí" + (f", průměr {sum(s) / len(s):.1f} z 5." if s else ".")


register("heureka", "Heureka (recenze obchodu)", "star", [
    {"key": "key", "label": "Tajný klíč Ověřeno zákazníky", "secret": True, "hint": "32 znaků"},
    {"key": "country", "label": "Země (cz / sk)", "secret": False, "hint": "prázdné = cz", "optional": True},
], [
    "Přihlas se do administrace Heureky (sluzby.heureka.cz) → Ověřeno zákazníky.",
    "Zkopíruj tajný klíč obchodu (ten, který používá e-shop pro Ověřeno zákazníky).",
    "Vlož ho sem a ulož – JARVIS čte recenze obchodu (Heureka je obnovuje každých 6 hodin).",
], url="https://sluzby.heureka.cz/", what="Recenze obchodu od zákazníků – hodnocení, klady, zápory, odpovědi; jen čtení.",
    test=_test, group="sales", probe={"method": "GET", "url": "https://www.heureka.cz/direct/dotaznik/export-review.php?key=" + "0" * 32,
                                       "accept": [404]})


@tool("heureka_reviews", "Heureka: recenze obchodu za posledních N dní – hodnocení, klady, zápory, souhrn; špatné zvlášť.",
      category="propojení", perm="network")
@guarded
async def heureka_reviews(ctx, days: Annotated[int, "kolik dní zpět"] = 30,
                          only_bad: Annotated[bool, "jen špatné (pod 3 hvězdy nebo se zápory)"] = False) -> ToolResult:
    since = time.time() - max(1, int(days or 30)) * 86400
    rs = await reviews()
    picked = []
    for r in rs:
        ts = r.get("unix_timestamp")
        try:
            if ts and float(ts) < since:
                continue
        except ValueError:
            pass
        s = score(r)
        bad = (s is not None and s < 3) or bool(r.get("cons"))
        if only_bad and not bad:
            continue
        picked.append({"id": r.get("rating_id"), "stars": s, "pros": r.get("pros"), "cons": r.get("cons"), "summary": r.get("summary"),
                       "reply": r.get("reaction"), "order": r.get("order_id"), "bad": bad})
    stars = [p["stars"] for p in picked if p["stars"] is not None]
    return ToolResult(True, f"{len(picked)} recenzí" + (f", průměr {sum(stars) / len(stars):.1f}/5" if stars else "")
                      + f", špatných {sum(1 for p in picked if p['bad'])}.", data=picked[:100])
