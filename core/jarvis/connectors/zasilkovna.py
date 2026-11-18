"""3.13 Zásilkovna (Packeta): kde jsou zásilky – stav a historie podle čísla zásilky (jen čtení). API heslo z klientské
sekce Zásilkovny; REST API posílá XML na www.zasilkovna.cz/api/rest."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Annotated, Any
from xml.sax.saxutils import escape

from ..tools.base import ToolResult, tool
from . import ServiceError, guarded, http, need, register, value

URL = "https://www.zasilkovna.cz/api/rest"
DELIVERED, READY, RETURNED = 7, 5, 10
FAULTS = {"IncorrectApiPasswordFault": "Zásilkovna nepřijala API heslo – zkopíruj ho znovu z klientské sekce.",
          "PacketIdFault": "Takové číslo zásilky Zásilkovna nezná.",
          "AccessDeniedFault": "K téhle zásilce nemá tvůj účet přístup."}


def parse(data: bytes) -> ET.Element:
    if b"<!DOCTYPE" in data[:2000] or b"<!ENTITY" in data[:2000]:
        raise ServiceError("Zásilkovna poslala neočekávanou odpověď.")
    root = ET.fromstring(data)
    if (root.findtext("status") or "").strip() != "ok":
        fault = (root.findtext("fault") or "").strip()
        raise ServiceError(FAULTS.get(fault) or f"Zásilkovna: {root.findtext('string') or fault or 'chyba'}")
    return root.find("result") if root.find("result") is not None else root


async def rest(method: str, transport=None, **args: str) -> ET.Element:
    need("zasilkovna")
    body = f"<{method}><apiPassword>{escape(value('zasilkovna', 'api_password').strip())}</apiPassword>" + \
        "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in args.items()) + f"</{method}>"
    async with http(transport=transport, timeout=30) as c:
        r = await c.post(URL, content=body.encode("utf-8"), headers={"Content-Type": "application/xml"})
    r.raise_for_status()
    return parse(r.content)


def packet_id(s: str) -> str:
    """"Z 123 456 7890" → "1234567890" (the barcode's Z is not part of the number)."""
    return re.sub(r"[^0-9]", "", str(s or ""))


def _record(e: ET.Element) -> dict:
    return {c.tag: (c.text or "").strip() for c in e if (c.text or "").strip()}


async def _test(rt: Any) -> str:
    try:
        await rest("packetStatus", packetId="1")
    except ServiceError as e:
        if "nezná" in str(e) or "přístup" in str(e):      # the password is right, only the made-up packet is not
            return "Propojeno – API heslo platí."
        raise
    return "Propojeno."


register("zasilkovna", "Zásilkovna (zásilky)", "package", [
    {"key": "api_password", "label": "API heslo", "secret": True, "hint": "32 znaků z klientské sekce"},
], [
    "Přihlas se do klientské sekce Zásilkovny (client.packeta.com).",
    "V nastavení klienta najdi API heslo (API key / API password) a zkopíruj ho.",
    "Vlož ho sem a ulož – JARVIS jen zjišťuje stav zásilek.",
], url="https://client.packeta.com/", what="Stav a historie zásilek podle čísla (doručeno, čeká na výdejně, vrací se) – jen čtení.",
    test=_test, group="sales",
    probe={"method": "POST", "url": URL, "headers": {"Content-Type": "application/xml"},
           "data": "<packetStatus><apiPassword>00000000000000000000000000000000</apiPassword><packetId>1</packetId></packetStatus>"})


@tool("zasilkovna_status", "Zásilkovna: aktuální stav zásilek podle čísel (doručeno, čeká na výdejně do…, vrací se).",
      category="propojení", perm="network")
@guarded
async def zasilkovna_status(ctx, packets: Annotated[list[str], "čísla zásilek, např. [\"Z1234567890\"] (nejvýš 25)"]) -> ToolResult:
    out = []
    for p in [packet_id(x) for x in packets or []][:25]:
        if not p:
            continue
        try:
            r = _record(await rest("packetStatus", packetId=p))
            out.append({"packet": p, "code": int(r.get("statusCode") or 0), "status": r.get("statusText") or r.get("codeText"),
                        "when": r.get("dateTime", "")[:16].replace("T", " "), "stored_until": r.get("storedUntil") or None,
                        "returning": r.get("isReturning") == "true", "carrier": r.get("carrierName")})
        except ServiceError as e:
            if "heslo" in str(e):
                raise
            out.append({"packet": p, "error": str(e)})
    n = lambda c: sum(1 for x in out if x.get("code") == c)  # noqa: E731
    return ToolResult(True, f"{len(out)} zásilek: doručeno {n(DELIVERED)}, čeká na výdejně {n(READY)}, vráceno {n(RETURNED)}, "
                            f"vrací se {sum(1 for x in out if x.get('returning'))}.", data=out)


@tool("zasilkovna_tracking", "Zásilkovna: celá cesta jedné zásilky (kdy kde byla).", category="propojení", perm="network")
@guarded
async def zasilkovna_tracking(ctx, packet: Annotated[str, "číslo zásilky"]) -> ToolResult:
    res = await rest("packetTracking", packetId=packet_id(packet))
    recs = [_record(r) for r in res.iter("record")]
    out = [{"when": r.get("dateTime", "")[:16].replace("T", " "), "status": r.get("statusText") or r.get("codeText"),
            "code": r.get("statusCode")} for r in recs]
    return ToolResult(True, f"Zásilka {packet_id(packet)}: {len(out)} záznamů, naposledy „{out[-1]['status'] if out else '?'}“.", data=out)
