"""3.13 POHODA (Stormware): vydané a přijaté faktury přes POHODA mServer (jen čtení). mServer běží u tebe ve firmě
(POHODA → Databáze → POHODA mServer): JARVIS posílá XML požadavek na http://server:port/xml s hlavičkou STW-Authorization."""
from __future__ import annotations

import base64
import datetime as dt
import xml.etree.ElementTree as ET
from typing import Annotated, Any
from xml.sax.saxutils import escape

from ..tools.base import ToolResult, tool
from . import ServiceError, guarded, http, need, register, value

NS = {"dat": "http://www.stormware.cz/schema/version_2/data.xsd", "lst": "http://www.stormware.cz/schema/version_2/list.xsd",
      "ftr": "http://www.stormware.cz/schema/version_2/filter.xsd", "inv": "http://www.stormware.cz/schema/version_2/invoice.xsd",
      "typ": "http://www.stormware.cz/schema/version_2/type.xsd"}
KINDS = {"vydane": "issuedInvoice", "prijate": "receivedInvoice"}


def server() -> str:
    u = value("pohoda", "url").strip().rstrip("/")
    if u.lower().endswith("/xml"):
        u = u[:-4]
    return u if u.startswith("http") else "http://" + u


def headers() -> dict:
    auth = base64.b64encode(f"{value('pohoda', 'user')}:{value('pohoda', 'password')}".encode("utf-8")).decode()
    return {"STW-Authorization": f"Basic {auth}", "STW-Application": "JARVIS", "Content-Type": "application/xml"}


def request_xml(kind: str, since: dt.date | None, count: int = 200) -> bytes:
    flt = f"<ftr:filter><ftr:dateFrom>{since}</ftr:dateFrom></ftr:filter>" if since else ""
    ns = " ".join(f'xmlns:{k}="{v}"' for k, v in NS.items() if k in ("dat", "lst", "ftr"))
    xml = (f'<?xml version="1.0" encoding="Windows-1250"?>'
           f'<dat:dataPack version="2.0" id="jarvis" ico="{escape(value("pohoda", "ico").strip())}" application="JARVIS" note="JARVIS – čtení faktur" {ns}>'
           f'<dat:dataPackItem version="2.0" id="1">'
           f'<lst:listInvoiceRequest version="2.0" invoiceVersion="2.0" invoiceType="{kind}">'
           f'<lst:limit><ftr:count>{int(count)}</ftr:count></lst:limit>'
           f'<lst:requestInvoice>{flt}</lst:requestInvoice></lst:listInvoiceRequest></dat:dataPackItem></dat:dataPack>')
    return xml.encode("cp1250", errors="replace")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(e: ET.Element, *path: str) -> str:
    """The text at a path of local names (namespaces ignored) – POHODA's schema versions differ in prefixes."""
    cur: list[ET.Element] = [e]
    for name in path:
        cur = [c for x in cur for c in x.iter() if _local(c.tag) == name]
        if not cur:
            return ""
    return (cur[0].text or "").strip()


def _num(s: str) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def parse(data: bytes) -> list[dict]:
    if b"<!DOCTYPE" in data[:3000] or b"<!ENTITY" in data[:3000]:
        raise ServiceError("POHODA poslala neočekávanou odpověď.")
    root = ET.fromstring(data)
    if root.get("state") == "error" or any(i.get("state") == "error" for i in root.iter() if _local(i.tag) == "responsePackItem"):
        note = root.get("note") or next((i.get("note") for i in root.iter() if _local(i.tag) == "responsePackItem" and i.get("note")), "")
        raise ServiceError(f"POHODA odmítla požadavek: {note or 'chyba'} (zkontroluj IČO účetní jednotky a práva uživatele).")
    out = []
    for inv in (x for x in root.iter() if _local(x.tag) == "invoice"):
        head = next((c for c in inv if _local(c.tag) == "invoiceHeader"), inv)
        summ = next((c for c in inv if _local(c.tag) == "invoiceSummary"), None)
        total = 0.0
        if summ is not None:
            home = next((c for c in summ.iter() if _local(c.tag) == "homeCurrency"), summ)
            total = sum(_num(_find(home, k)) for k in ("priceNone", "priceLowSum", "priceHighSum", "price3Sum"))
        out.append({"number": _find(head, "number", "numberRequested") or _find(head, "numberRequested"), "date": _find(head, "date"),
                    "due": _find(head, "dateDue"), "company": _find(head, "partnerIdentity", "company") or _find(head, "partnerIdentity", "name"),
                    "ico": _find(head, "partnerIdentity", "ico"), "vs": _find(head, "symVar"), "text": _find(head, "text")[:200],
                    "total": round(total, 2)})
    return out


async def post(body: bytes, transport=None) -> bytes:
    need("pohoda")
    async with http(transport=transport, timeout=90) as c:
        r = await c.post(server() + "/xml", content=body, headers=headers())
    if r.status_code in (401, 403):
        raise ServiceError("POHODA mServer nepřijal jméno nebo heslo (používá se uživatel z POHODY).")
    r.raise_for_status()
    return r.content


async def _test(rt: Any) -> str:
    need("pohoda")
    async with http(timeout=20) as c:
        r = await c.post(server() + "/status", headers=headers())
    if "mServer" not in r.text:
        raise ServiceError("Na té adrese POHODA mServer neodpovídá – je spuštěný (POHODA → Databáze → POHODA mServer) a je správně port?")
    parse(await post(request_xml("issuedInvoice", None, 1)))
    return "Propojeno – POHODA mServer odpovídá a přijal přihlášení."


register("pohoda", "POHODA (účetnictví)", "calculator", [
    {"key": "url", "label": "Adresa POHODA mServeru", "secret": False, "hint": "např. http://192.168.0.10:444"},
    {"key": "ico", "label": "IČO účetní jednotky", "secret": False, "hint": "8 číslic"},
    {"key": "user", "label": "Uživatel POHODY", "secret": False, "hint": ""},
    {"key": "password", "label": "Heslo", "secret": True, "hint": ""},
], [
    "V POHODĚ otevři Databáze → POHODA mServer a spusť ho pro svou účetní jednotku (zapamatuj si port, např. 444).",
    "Adresa je http://<počítač s POHODOU>:<port> – ve firemní síti, nebo přes VPN.",
    "Vyplň IČO účetní jednotky, uživatele POHODY a heslo a ulož – JARVIS faktury jen čte.",
], url="https://www.stormware.cz/pohoda/xml/mserver/", what="Vydané a přijaté faktury z POHODY přes mServer – jen čtení.",
    test=_test, group="money")


@tool("pohoda_invoices", "POHODA: vydané nebo přijaté faktury za posledních N dní (číslo, firma, částka, splatnost).",
      category="propojení", perm="network")
@guarded
async def pohoda_invoices(ctx, kind: Annotated[str, "vydane / prijate"] = "vydane", days: Annotated[int, "kolik dní zpět"] = 30) -> ToolResult:
    since = dt.date.today() - dt.timedelta(days=max(1, min(int(days or 30), 730)))
    out = parse(await post(request_xml(KINDS.get(str(kind).lower().strip(), "issuedInvoice"), since)))
    today = str(dt.date.today())
    late = [i for i in out if i["due"] and i["due"] < today]
    return ToolResult(True, f"{len(out)} faktur od {since}, celkem {sum(i['total'] for i in out):,.2f} Kč"
                      + (f", {len(late)} se splatností v minulosti (ověř úhradu)" if late else "") + ".", data=out[:200])
