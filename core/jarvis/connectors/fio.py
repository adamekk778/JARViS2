"""3.12 Fio banka: zůstatek a pohyby na účtu (jen čtení – token z internetového bankovnictví, stačí „jen pro čtení“).
Fio allows one question per 30 s per token; the answer for the same days is kept for that time."""
from __future__ import annotations

import datetime as dt
import time
from typing import Annotated, Any

from ..tools.base import ToolResult, tool
from . import ServiceError, call, guarded, need, register, value

API = "https://fioapi.fio.cz/v1/rest"
_CACHE: dict[str, Any] = {}
COLS = {"column22": "id", "column0": "date", "column1": "amount", "column14": "currency", "column2": "account",
        "column10": "account_name", "column3": "bank", "column5": "vs", "column4": "ks", "column6": "ss", "column7": "note",
        "column16": "message", "column8": "type", "column25": "comment", "column9": "by"}


def parse(d: dict) -> dict:
    st = d.get("accountStatement") or {}
    info = st.get("info") or {}
    moves = []
    for t in ((st.get("transactionList") or {}).get("transaction") or []):
        row = {}
        for col, key in COLS.items():
            v = (t.get(col) or {}).get("value") if isinstance(t.get(col), dict) else None
            if v not in (None, ""):
                row[key] = v[:10] if key == "date" and isinstance(v, str) else v
        moves.append(row)
    return {"account": f"{info.get('accountId', '')}/{info.get('bankId', '')}", "iban": info.get("iban"), "currency": info.get("currency"),
            "opening": info.get("openingBalance"), "balance": info.get("closingBalance"), "from": (info.get("dateStart") or "")[:10],
            "to": (info.get("dateEnd") or "")[:10], "moves": moves}


async def statement(days: int, transport=None) -> dict:
    need("fio")
    today = dt.date.today()
    since = today - dt.timedelta(days=max(0, min(int(days), 365)))
    key = f"{since}:{today}"
    if _CACHE.get("key") == key and time.time() - _CACHE.get("at", 0) < 60:
        return _CACHE["v"]
    try:
        d = await call("GET", f"{API}/periods/{value('fio', 'token')}/{since}/{today}/transactions.json", transport=transport, timeout=40)
    except Exception as e:  # noqa: BLE001
        import httpx

        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 409:
            raise ServiceError("Fio dovoluje dotaz jen jednou za 30 sekund – zkus to za chvíli.") from None
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 403, 500):
            raise ServiceError("Fio token nepřijala – zkontroluj ho (Nastavení → API v internetovém bankovnictví), "
                               "nové tokeny se aktivují až po 5 minutách.") from None
        raise
    v = parse(d)
    _CACHE.update(key=key, at=time.time(), v=v)
    return v


async def _test(rt: Any) -> str:
    s = await statement(1)
    return f"Propojeno – účet {s['account']}, zůstatek {s['balance']} {s['currency']}."


register("fio", "Fio banka", "bank", [
    {"key": "token", "label": "API token", "secret": True, "hint": "64 znaků"},
], [
    "Přihlas se do internetového bankovnictví Fio → Nastavení → API → Přidat nový token.",
    "Vyber účet a oprávnění „Pouze sledovat účet“ (jen čtení), potvrď a token zkopíruj sem.",
    "Nový token začne fungovat asi po 5 minutách.",
], url="https://ib.fio.cz/", what="Zůstatek a pohyby na účtu, příchozí platby podle VS – jen čtení.", test=_test, group="money",
    probe={"method": "GET", "url": API + "/last/FAKE0000000000000000000000000000000000000000000000000000000000/transactions.json",
           "accept": [500], "timeout": 45})        # Fio answers a wrong token with 500 after ~30 s


@tool("fio_account", "Fio banka: zůstatek a pohyby na účtu za posledních N dní (příjmy, výdaje, protiúčet, VS, zpráva).",
      category="propojení", perm="network")
@guarded
async def account(ctx, days: Annotated[int, "kolik dní zpět"] = 14) -> ToolResult:
    s = await statement(days)
    inc = round(sum(float(m.get("amount", 0)) for m in s["moves"] if float(m.get("amount", 0)) > 0), 2)
    out = round(sum(float(m.get("amount", 0)) for m in s["moves"] if float(m.get("amount", 0)) < 0), 2)
    return ToolResult(True, f"Zůstatek {s['balance']} {s['currency']}; za {days} dní příjmy {inc}, výdaje {out}.",
                      data={**s, "income": inc, "spent": out, "moves": s["moves"][-150:]})


@tool("fio_find_payment", "Fio banka: přišla platba? Najde pohyb podle variabilního symbolu, částky nebo jména.", category="propojení",
      perm="network")
@guarded
async def find_payment(ctx, vs: Annotated[str, "variabilní symbol"] = "", amount: Annotated[float, "částka"] = 0,
                       text: Annotated[str, "jméno / zpráva"] = "", days: Annotated[int, "kolik dní zpět"] = 60) -> ToolResult:
    s = await statement(days)
    hits = [m for m in s["moves"] if (not vs or str(m.get("vs", "")).lstrip("0") == vs.lstrip("0"))
            and (not amount or abs(float(m.get("amount", 0)) - float(amount)) < 0.01)
            and (not text or text.lower() in f"{m.get('account_name', '')} {m.get('message', '')} {m.get('note', '')} {m.get('comment', '')}".lower())]
    return ToolResult(True, f"{len(hits)} odpovídajících pohybů." if hits else "Žádná taková platba nepřišla.", data=hits[-30:])
