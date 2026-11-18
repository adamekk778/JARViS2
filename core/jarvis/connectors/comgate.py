"""3.13 Comgate: platby e-shopu – stav platby, převody na účet a platby v nich (jen čtení). ID e-shopu (merchant) a heslo
z Klientského portálu Comgate; REST API 2.0 na payments.comgate.cz s HTTP Basic."""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

import httpx

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value

BASE = "https://payments.comgate.cz/v2.0"


async def api(path: str, transport=None, **kw) -> Any:
    need("comgate")
    try:
        r = await call("GET", BASE + path, transport=transport, auth=(value("comgate", "merchant").strip(), value("comgate", "secret").strip()), **kw)
    except httpx.HTTPStatusError as e:
        try:
            err = (e.response.json() or {}).get("error") or {}
        except ValueError:
            err = {}
        if err.get("code") == 1400 or e.response.status_code in (401, 403):
            raise ServiceError("Comgate nepřijal ID e-shopu nebo heslo – zkontroluj je v Klientském portálu "
                               "(a že má e-shop povolené API a IP adresu tohoto PC).") from None
        raise
    if isinstance(r, dict) and r.get("code") not in (None, 0, "0"):
        raise ServiceError(f"Comgate: {r.get('message') or r.get('code')}")
    return r


async def _test(rt: Any) -> str:
    r = await api("/method.json", params={"lang": "cs"})
    return f"Propojeno – Comgate nabízí {len(r.get('methods') or [])} platebních metod."


register("comgate", "Comgate (platby)", "credit-card", [
    {"key": "merchant", "label": "ID e-shopu (merchant)", "secret": False, "hint": "číslo z Klientského portálu"},
    {"key": "secret", "label": "Heslo pro API", "secret": True, "hint": ""},
], [
    "V Klientském portálu Comgate otevři Nastavení e-shopu → Propojení e-shopu.",
    "Zkopíruj identifikátor e-shopu (merchant) a heslo; v portálu povol přístup k API (případně IP adresu tohoto PC).",
    "Ulož – JARVIS jen čte platby a převody.",
], url="https://portal.comgate.cz/", what="Stav plateb, denní převody na účet a platby v nich – jen čtení.", test=_test, group="money",
    probe={"method": "GET", "url": BASE + "/method.json", "auth": ["000000", "FAKE"]})


@tool("comgate_payment", "Comgate: stav jedné platby podle transId (zaplaceno, čeká, zrušeno), částka a plátce.",
      category="propojení", perm="network")
@guarded
async def comgate_payment(ctx, trans_id: Annotated[str, "ID transakce Comgate, např. AB12-CD34-EF56"]) -> ToolResult:
    r = await api(f"/payment/transId/{str(trans_id).strip()}.json")
    amount = int(r.get("price") or 0) / 100
    out = {"id": r.get("transId"), "status": r.get("status"), "amount": amount, "currency": r.get("curr"), "label": r.get("label"),
           "ref": r.get("refId"), "email": r.get("email"), "method": r.get("method"), "vs": r.get("vs")}
    return ToolResult(True, f"Platba {out['id']}: {amount:,.2f} {out['currency']} – {out['status']}.", data=out)


@tool("comgate_transfers", "Comgate: převody peněz z Comgate na účet za posledních N dní (a kolik plateb v nich bylo).",
      category="propojení", perm="network")
@guarded
async def comgate_transfers(ctx, days: Annotated[int, "kolik dní zpět"] = 7) -> ToolResult:
    out = []
    today = dt.date.today()
    for k in range(max(1, min(int(days or 7), 31))):
        d = today - dt.timedelta(days=k)
        r = await api(f"/transferList/date/{d}.json")
        for t in r if isinstance(r, list) else []:
            out.append({"id": t.get("transferId"), "date": t.get("transferDate"), "account": t.get("accountCounterparty"),
                        "vs": t.get("variableSymbol")})
    return ToolResult(True, f"{len(out)} převodů za {days} dní.", data=out)


def _num(s: Any) -> float:
    try:
        return float(str(s).replace(" ", "").replace(",", "."))
    except ValueError:
        return 0.0


@tool("comgate_transfer_payments", "Comgate: platby v jednom převodu (kdo, kolik, za co, poplatky).", category="propojení", perm="network")
@guarded
async def comgate_transfer_payments(ctx, transfer_id: Annotated[int, "ID převodu z comgate_transfers"]) -> ToolResult:
    r = await api(f"/singleTransfer/transferId/{int(transfer_id)}.json")
    out = [{"id": p.get("ID Comgate"), "paid": p.get("Datum zaplacení"), "method": p.get("Metoda"), "label": p.get("Popis"),
            "email": p.get("E-mail plátce"), "ref": p.get("ID od klienta"), "currency": p.get("Měna"),
            "amount": _num(p.get("Potvrzená částka")), "fee": _num(p.get("Poplatek celkem"))} for p in (r if isinstance(r, list) else [])]
    return ToolResult(True, f"{len(out)} plateb, celkem {sum(p['amount'] for p in out):,.2f}, poplatky {sum(p['fee'] for p in out):,.2f}.",
                      data=out)
