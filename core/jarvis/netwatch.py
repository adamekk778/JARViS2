"""OMEGA 708 / 709 / 719: continuous watching of chosen webs (is it up, how fast, when the HTTPS certificate expires) and
a packet-loss / latency history of the internet line. Read-only checks (HTTP GET, TLS handshake, TCP handshake to
1.1.1.1); the user picks what is watched, nothing is added on its own. A notice only when something CHANGES (a web
went down / came back, a certificate is close to expiring), never every round."""
from __future__ import annotations

import asyncio
import logging
import time

from . import netdiag, perf

log = logging.getLogger("jarvis.netwatch")

SQL = """
CREATE TABLE IF NOT EXISTS net_watch (url TEXT PRIMARY KEY, added REAL, last_up INTEGER, last_days INTEGER, warned_days INTEGER);
CREATE TABLE IF NOT EXISTS net_watch_log (ts REAL, url TEXT, up INTEGER, status INTEGER, ms REAL, days_left INTEGER);
CREATE TABLE IF NOT EXISTS net_loss (ts REAL, host TEXT, avg_ms REAL, jitter_ms REAL, loss_pct REAL);
"""
CERT_WARN = (30, 14, 7, 3, 1)       # a certificate notice at each of these thresholds, once
KEEP_DAYS = 30
MAX_WATCHED = 25


def norm_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u.rstrip("/")[:300]


def domain_of(url: str) -> str:
    return url.removeprefix("https://").removeprefix("http://").split("/")[0].split(":")[0]


def cert_threshold(days: int | None, warned: int | None) -> int | None:
    """The threshold just crossed (30 / 14 / 7 / 3 / 1 days) that was not announced yet, else None."""
    if days is None:
        return None
    hit = min((t for t in CERT_WARN if days <= t), default=None)
    if hit is None:
        return None
    return hit if warned is None or hit < warned else None


class NetWatch:
    def __init__(self, rt):
        self.rt = rt
        rt.db.conn.executescript(SQL)

    # ---------------------------------------------------------------- the watch list
    def add(self, url: str) -> dict:
        u = norm_url(url)
        if not u or "." not in domain_of(u):
            return {"ok": False, "error": "Tohle nevypadá jako adresa webu."}
        if self.rt.db.one("SELECT url FROM net_watch WHERE url=?", (u,)):
            return {"ok": True, "url": u, "already": True}
        if (self.rt.db.one("SELECT COUNT(*) AS n FROM net_watch") or {"n": 0})["n"] >= MAX_WATCHED:
            return {"ok": False, "error": f"Hlídám už {MAX_WATCHED} webů – nejdřív nějaký odeber."}
        self.rt.db.exec("INSERT INTO net_watch (url, added) VALUES (?, ?)", (u, time.time()))
        return {"ok": True, "url": u}

    def remove(self, url: str) -> bool:
        u = norm_url(url)
        n = self.rt.db.exec("DELETE FROM net_watch WHERE url=?", (u,))
        self.rt.db.exec("DELETE FROM net_watch_log WHERE url=?", (u,))
        return bool(getattr(n, "rowcount", 1))

    def list(self) -> list[dict]:
        rows = self.rt.db.all("SELECT * FROM net_watch ORDER BY added")
        out = []
        for r in rows:
            last = self.rt.db.one("SELECT * FROM net_watch_log WHERE url=? ORDER BY ts DESC LIMIT 1", (r["url"],))
            day = self.rt.db.all("SELECT up FROM net_watch_log WHERE url=? AND ts>=?", (r["url"], time.time() - 86400))
            out.append({"url": r["url"], "up": None if r["last_up"] is None else bool(r["last_up"]), "days_left": r["last_days"],
                        "status": last and last["status"], "ms": last and last["ms"], "checked": last and last["ts"],
                        "uptime_24h": round(100 * sum(x["up"] for x in day) / len(day), 1) if day else None})
        return out

    def history(self, url: str, hours: float = 24) -> list[dict]:
        return self.rt.db.all("SELECT ts, up, status, ms, days_left FROM net_watch_log WHERE url=? AND ts>=? ORDER BY ts",
                              (norm_url(url), time.time() - hours * 3600))

    # ---------------------------------------------------------------- checks
    async def check(self, url: str) -> dict:
        h = await netdiag.http_check(self.rt, url)
        tls = await asyncio.to_thread(netdiag.tls_check, domain_of(url)) if url.startswith("https://") else {}
        days = tls.get("days_left") if tls.get("valid") else (0 if tls and not tls.get("valid") and h.get("up") else None)
        return {"url": url, "up": bool(h.get("up")), "status": h.get("status"), "ms": h.get("ms"), "days_left": days,
                "tls_error": None if not tls or tls.get("valid") else tls.get("error")}

    def apply(self, r: dict) -> list[dict]:
        """Store one result; answer the events worth a notice (down / back up / certificate threshold)."""
        row = self.rt.db.one("SELECT * FROM net_watch WHERE url=?", (r["url"],)) or {}
        self.rt.db.exec("INSERT INTO net_watch_log VALUES (?,?,?,?,?,?)",
                        (time.time(), r["url"], int(r["up"]), r.get("status"), r.get("ms"), r.get("days_left")))
        events = []
        prev = row.get("last_up")
        if prev is not None and bool(prev) != r["up"]:
            events.append({"kind": "down" if not r["up"] else "up", "url": r["url"],
                           "text": f"{domain_of(r['url'])} nefunguje ({r.get('status') or 'neodpovídá'})." if not r["up"]
                           else f"{domain_of(r['url'])} zase funguje ({r.get('ms')} ms)."})
        warned = row.get("warned_days")
        hit = cert_threshold(r.get("days_left"), warned)
        if hit is not None:
            d = r["days_left"]
            events.append({"kind": "cert", "url": r["url"],
                           "text": f"Certifikát {domain_of(r['url'])} " + ("už neplatí!" if d <= 0 else f"vyprší za {d} {'den' if d == 1 else 'dny' if d < 5 else 'dní'}.")})
            warned = hit
        elif r.get("days_left") is not None and r["days_left"] > CERT_WARN[0]:
            warned = None                                   # renewed → watch the next expiry afresh
        self.rt.db.exec("UPDATE net_watch SET last_up=?, last_days=?, warned_days=? WHERE url=?",
                        (int(r["up"]), r.get("days_left"), warned, r["url"]))
        return events

    async def check_all(self) -> list[dict]:
        events = []
        for row in self.rt.db.all("SELECT url FROM net_watch"):
            try:
                events += self.apply(await self.check(row["url"]))
            except Exception as e:  # noqa: BLE001
                log.debug("watch %s: %s", row["url"], e)
        self.rt.db.exec("DELETE FROM net_watch_log WHERE ts < ?", (time.time() - KEEP_DAYS * 86400,))
        return events

    # ---------------------------------------------------------------- 719 packet loss history
    def record_loss(self, lat: dict) -> None:
        self.rt.db.exec("INSERT INTO net_loss VALUES (?,?,?,?,?)",
                        (time.time(), lat.get("host", ""), lat.get("avg_ms"), lat.get("jitter_ms"), lat.get("loss_pct")))
        self.rt.db.exec("DELETE FROM net_loss WHERE ts < ?", (time.time() - KEEP_DAYS * 86400,))

    def loss_series(self, hours: float = 24) -> list[dict]:
        return self.rt.db.all("SELECT ts, avg_ms, jitter_ms, loss_pct FROM net_loss WHERE ts>=? ORDER BY ts", (time.time() - hours * 3600,))

    def loss_summary(self, hours: float = 24) -> dict:
        rows = self.loss_series(hours)
        if not rows:
            return {"samples": 0, "hours": hours}
        loss = [r["loss_pct"] or 0 for r in rows]
        ms = [r["avg_ms"] for r in rows if r["avg_ms"] is not None]
        bad = [r for r in rows if (r["loss_pct"] or 0) >= 10 or r["avg_ms"] is None]
        return {"samples": len(rows), "hours": hours, "loss_avg": round(sum(loss) / len(loss), 1), "loss_max": max(loss),
                "ms_avg": round(sum(ms) / len(ms), 1) if ms else None, "ms_max": max(ms) if ms else None,
                "outages": len([r for r in rows if r["avg_ms"] is None]), "bad_rounds": len(bad),
                "worst_ts": max(rows, key=lambda r: (r["loss_pct"] or 0, r["avg_ms"] or 0))["ts"]}


async def loop(rt, every: float = 600.0) -> None:
    """Every 10 minutes: one latency/loss sample of the line, then the watched webs (if any). Off with powers.net_watch."""
    nw: NetWatch = rt.netwatch
    await asyncio.sleep(60)
    while True:
        if getattr(rt.cfg.powers, "net_watch", True):
            try:
                lat = await asyncio.to_thread(perf.tcp_latency, "1.1.1.1", 443, 10)
                nw.record_loss(lat)
                for ev in await nw.check_all():
                    rt.notify("Hlídání webu" if ev["kind"] != "cert" else "Certifikát", ev["text"], speak=False, urgent=ev["kind"] == "down")
                    rt.bus.publish("netwatch", event=ev)
            except Exception as e:  # noqa: BLE001
                log.debug("netwatch: %s", e)
        await asyncio.sleep(every)
