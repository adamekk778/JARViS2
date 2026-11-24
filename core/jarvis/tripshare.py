"""3.19 Sdílení cesty (návrh 16): a read-only link for the family – where you are going, when, and the flight's state
(delay, gate) – valid until the day after the trip ends, revocable any time. It shows no price, no booking number and
none of your details; it works from outside your home only when JARVIS has a public HTTPS address (Tailscale Funnel,
Cloudflare Tunnel – the same as for the phone outside home)."""
from __future__ import annotations

import datetime as dt
import html
import json
import secrets
import time
from typing import Any

SQL = "CREATE TABLE IF NOT EXISTS trip_shares (token TEXT PRIMARY KEY, booking_id INTEGER, until REAL, created REAL, views INTEGER DEFAULT 0)"


def _db(rt: Any) -> Any:
    rt.db.exec(SQL)
    return rt.db


def _end_ts(b: dict) -> float:
    for k in ("end", "start"):
        try:
            d = dt.datetime.fromisoformat(str(b.get(k) or "").replace("Z", "")[:19])
            return (d + dt.timedelta(days=1)).timestamp()
        except ValueError:
            continue
    return time.time() + 7 * 86400


def base_url(rt: Any) -> tuple[str, bool]:
    """(address, reachable from outside): the public HTTPS address if set, else this PC in the home network."""
    pub = (getattr(rt.cfg.phone_link, "public_url", "") or "").strip().rstrip("/")
    if pub.startswith("https://"):
        return pub, True
    try:
        from .server.pairing import local_ips

        lan, ts = local_ips()
        host = (ts or lan or ["127.0.0.1"])[0]
    except Exception:  # noqa: BLE001
        host = "127.0.0.1"
    return f"http://{host}:{rt.cfg.phone.port}", False


def create(rt: Any, b: dict) -> dict:
    token = secrets.token_urlsafe(24)
    until = _end_ts(b)
    _db(rt).exec("INSERT INTO trip_shares (token, booking_id, until, created) VALUES (?,?,?,?)", (token, int(b["id"]), until, time.time()))
    base, public = base_url(rt)
    return {"url": f"{base}/share/{token}", "until": until, "public": public, "token": token}


def stop(rt: Any, booking_id: int | None = None, token: str = "") -> int:
    db = _db(rt)
    before = len(db.all("SELECT token FROM trip_shares"))
    if token:
        db.exec("DELETE FROM trip_shares WHERE token=?", (token,))
    elif booking_id is not None:
        db.exec("DELETE FROM trip_shares WHERE booking_id=?", (int(booking_id),))
    return before - len(db.all("SELECT token FROM trip_shares"))


def page(rt: Any, token: str, now: float | None = None) -> str | None:
    """The shared page, or None (unknown or expired link)."""
    now = now or time.time()
    db = _db(rt)
    db.exec("DELETE FROM trip_shares WHERE until < ?", (now,))
    if not token or len(token) > 64:
        return None
    row = db.one("SELECT * FROM trip_shares WHERE token=?", (token,))
    if not row:
        return None
    db.exec("UPDATE trip_shares SET views = views + 1 WHERE token=?", (token,))
    b = db.one("SELECT kind, name, city, start, end, status, data FROM bookings WHERE id=?", (row["booking_id"],))
    if not b or b["status"] == "cancelled":
        return None
    e = html.escape
    items = [("Kam", f"{b['name']}" + (f", {b['city']}" if b["city"] else "")),
             ("Od", str(b["start"]).replace("T", " ")[:16]), ("Do", str(b["end"]).replace("T", " ")[:16])]
    legs = (json.loads(b["data"] or "{}").get("offer") or {}).get("legs") or []
    flights = []
    for lg in legs:
        state = ""
        try:
            from . import travel

            num = str(lg.get("flight") or "")
            for t in travel.upcoming(rt, now - 86400, days=60):
                if t["number"].replace(" ", "") == num.replace(" ", ""):
                    info = t.get("info") or {}
                    state = ", ".join(x for x in (f"zpoždění {info['delay_min']} min" if info.get("delay_min") else "",
                                                  f"gate {info['gate']}" if info.get("gate") else "") if x) or "podle plánu"
        except Exception:  # noqa: BLE001
            pass
        flights.append((f"Let {lg.get('flight', '')}", f"{lg.get('from', '')} → {lg.get('to', '')}, "
                        f"{str(lg.get('dep', '')).replace('T', ' ')[:16]}" + (f" – {state}" if state else "")))
    rows = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in items + flights)
    return ("<!doctype html><html lang='cs'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
            "initial-scale=1'><meta name='robots' content='noindex'><title>Cesta</title><style>body{font:16px system-ui;"
            "margin:16px;background:#0b1220;color:#e8eef9}table{border-collapse:collapse;width:100%}th,td{text-align:left;"
            "padding:8px 6px;border-bottom:1px solid #253049}th{color:#8fa3c4;font-weight:500;width:30%}</style></head><body>"
            f"<h1 style='font-size:20px'>Cesta</h1><table>{rows}</table><p style='opacity:.6'>Sdíleno z JARVISe, jen pro čtení. "
            f"Odkaz platí do {dt.datetime.fromtimestamp(row['until']):%d. %m. %Y}.</p></body></html>")
