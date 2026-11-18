"""3.13 ABRA Flexi (FlexiBee): účetnictví – vydané a přijaté faktury (nezaplacené, po splatnosti), banka a adresář
(jen čtení). REST API na tvém serveru Flexi: https://server/c/<firma>/<evidence>.json, přihlášení jménem a heslem."""
from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Any
from urllib.parse import quote

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value

INVOICE = "custom:kod,nazFirmy,sumCelkem,mena,datVyst,datSplat,stavUhrK,zbyvaUhradit,varSym"
KINDS = {"vydane": "faktura-vydana", "prijate": "faktura-prijata"}


def server() -> str:
    u = value("flexi", "url").strip().rstrip("/")
    if u and not u.startswith("http"):
        u = "https://" + u
    return re.sub(r"/c/.*$", "", u)


def company() -> str:
    return value("flexi", "company").strip().strip("/")


def safe(text: str) -> str:
    """A search word inside Flexi's filter: no quotes or brackets that would change the filter."""
    return re.sub(r"[^\w\s.@/-]", "", str(text or ""))[:60].strip()


async def api(evidence: str, flt: str = "", transport=None, **params: Any) -> list[dict]:
    need("flexi")
    path = f"/c/{quote(company())}/{evidence}" + (f"/({quote(flt, safe='')})" if flt else "") + ".json"
    r = await call("GET", server() + path, transport=transport, auth=(value("flexi", "user"), value("flexi", "password")),
                   params=params, timeout=45)
    w = (r or {}).get("winstrom") or {}
    if str(w.get("success", "true")) == "false":
        raise ServiceError(f"ABRA Flexi: {w.get('message') or 'chyba'}")
    return w.get(evidence) or []


def _money(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _cur(x: Any) -> str:
    return str(x or "").replace("code:", "")


async def _test(rt: Any) -> str:
    await api("faktura-vydana", limit=1, detail="custom:kod")
    return f"Propojeno – firma {company()} na {server().split('//')[-1]}."


register("flexi", "ABRA Flexi (účetnictví)", "calculator", [
    {"key": "url", "label": "Adresa serveru", "secret": False, "hint": "např. https://mojefirma.flexibee.eu:5434"},
    {"key": "company", "label": "Identifikátor firmy", "secret": False, "hint": "z adresy …/c/<firma>/…"},
    {"key": "user", "label": "Uživatel", "secret": False, "hint": "uživatel s právem na REST API"},
    {"key": "password", "label": "Heslo", "secret": True, "hint": ""},
], [
    "Ve Flexi otevři firmu – v adrese prohlížeče je …/c/<identifikátor firmy>/… a začátek adresy je adresa serveru.",
    "Použij uživatele, který má povolené REST API (Nastavení → Uživatelé → oprávnění), ideálně jen pro čtení.",
    "Vyplň adresu, firmu, uživatele a heslo a ulož – JARVIS z účetnictví jen čte.",
], url="https://www.flexibee.eu/", what="Vydané a přijaté faktury (nezaplacené, po splatnosti), pohyby v bance a adresář – jen čtení.",
    test=_test, group="money",
    probe={"method": "GET", "url": "https://demo.flexibee.eu/c/demo/faktura-vydana.json?limit=1", "auth": ["winstrom", "FAKE"]})


@tool("flexi_invoices", "ABRA Flexi: vydané nebo přijaté faktury – nezaplacené, po splatnosti nebo hledání podle odběratele / čísla.",
      category="propojení", perm="network")
@guarded
async def flexi_invoices(ctx, kind: Annotated[str, "vydane (odběratelé dluží nám) / prijate (dlužíme my)"] = "vydane",
                         unpaid: Annotated[bool, "jen nezaplacené"] = True, overdue: Annotated[bool, "jen po splatnosti"] = False,
                         query: Annotated[str, "hledat firmu nebo číslo faktury (nepovinné)"] = "") -> ToolResult:
    ev = KINDS.get(str(kind).lower().strip(), "faktura-vydana")
    parts = ["storno eq false"]
    if unpaid or overdue:
        parts.append("stavUhrK != 'stavUhr.uhrazeno'")
    if overdue:
        parts.append("datSplat lt now()")
    q = safe(query)
    if q:
        parts.append(f"(nazFirmy like '{q}' or kod like '{q}')")
    rows = await api(ev, " and ".join(parts), detail=INVOICE, limit=100, order="datSplat@A", **{"add-row-count": "true"})
    out = [{"number": r.get("kod"), "company": r.get("nazFirmy"), "total": _money(r.get("sumCelkem")), "currency": _cur(r.get("mena")),
            "issued": (r.get("datVyst") or "")[:10], "due": (r.get("datSplat") or "")[:10], "left": _money(r.get("zbyvaUhradit")),
            "vs": r.get("varSym")} for r in rows]
    owed: dict[str, float] = {}
    for r in out:
        owed[r["currency"]] = round(owed.get(r["currency"], 0) + r["left"], 2)
    what = "vydaných" if ev == "faktura-vydana" else "přijatých"
    more = " (nejstarších 100 podle splatnosti)" if len(out) >= 100 else ""
    return ToolResult(True, f"{len(out)} {what} faktur{more}" + (f", zbývá uhradit {owed}" if any(owed.values()) else "") + ".", data=out)


@tool("flexi_bank", "ABRA Flexi: pohyby v bance za posledních N dní (příjmy a výdaje, VS, popis, firma).", category="propojení",
      perm="network")
@guarded
async def flexi_bank(ctx, days: Annotated[int, "kolik dní zpět"] = 14) -> ToolResult:
    since = dt.date.today() - dt.timedelta(days=max(1, min(int(days or 14), 366)))
    rows = await api("banka", f"datVyst gte '{since}'", detail="custom:kod,datVyst,sumCelkem,mena,typPohybuK,popis,varSym,nazFirmy",
                     limit=300, order="datVyst@D")
    out = [{"date": (r.get("datVyst") or "")[:10], "amount": _money(r.get("sumCelkem")) * (-1 if "vydej" in str(r.get("typPohybuK")) else 1),
            "currency": _cur(r.get("mena")), "vs": r.get("varSym"), "text": r.get("popis"), "company": r.get("nazFirmy"),
            "number": r.get("kod")} for r in rows]
    inc = round(sum(r["amount"] for r in out if r["amount"] > 0), 2)
    outg = round(sum(r["amount"] for r in out if r["amount"] < 0), 2)
    return ToolResult(True, f"{len(out)} pohybů za {days} dní: příjmy {inc:,.2f}, výdaje {outg:,.2f}.", data=out)


@tool("flexi_contacts", "ABRA Flexi: adresář firem – hledání podle názvu nebo IČO.", category="propojení", perm="network")
@guarded
async def flexi_contacts(ctx, query: Annotated[str, "název nebo IČO"]) -> ToolResult:
    q = safe(query)
    rows = await api("adresar", f"nazev like '{q}' or ic eq '{q}'" if q else "", detail="custom:kod,nazev,ic,dic,email,tel,mesto", limit=30)
    out = [{"code": r.get("kod"), "name": r.get("nazev"), "ico": r.get("ic"), "dic": r.get("dic"), "email": r.get("email"),
            "phone": r.get("tel"), "city": r.get("mesto")} for r in rows]
    return ToolResult(True, f"{len(out)} firem v adresáři.", data=out)
