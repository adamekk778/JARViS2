"""JARVIS watching its own quality (návrhy 12, 16, 17, 20).

- every tool call is counted per day and version (calls, failures, time) → Zdraví JARVISe: which tools fail, how
  fast the AIs answer, crashes, and whether the new version is better or worse than the one before
- the check after an update compares itself with the last check of the previous version: what worked before and
  now does not is a regression; a broken notch or two broken core parts → back to the previous version
- "Nahlásit chybu" builds a GitHub issue (title + diagnostics without keys / passwords / tokens) for one click
- how much battery and processor JARVIS itself takes (sampled every minute while it runs)
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import time
import urllib.parse
from collections import deque
from typing import Any

log = logging.getLogger(__name__)

# parts of Kontrola funkcí that JARVIS itself makes work (the rest depends on the PC, the network, the AI keys)
CORE_KEYS = {"notch", "wake", "speech", "tts", "media", "mic"}
CRITICAL_KEYS = {"notch"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_stats (day TEXT, version TEXT, tool TEXT, calls INT, fails INT, ms_total INT,
  PRIMARY KEY (day, version, tool));
"""


def _db(rt: Any):
    db = rt.db
    if not getattr(db, "_quality_schema", False):
        db.conn.executescript(SCHEMA)
        db._quality_schema = True
    return db


def _version() -> str:
    from . import __version__

    return __version__


# ---------- 16: every tool call counted ----------
def record_tool(rt: Any, tool: str, ok: bool, ms: int) -> None:
    try:
        day = time.strftime("%Y-%m-%d")
        _db(rt).exec("INSERT INTO tool_stats VALUES (?,?,?,1,?,?) ON CONFLICT(day, version, tool) DO UPDATE SET "
                     "calls = calls + 1, fails = fails + excluded.fails, ms_total = ms_total + excluded.ms_total",
                     (day, _version(), tool, 0 if ok else 1, max(0, int(ms))))
    except Exception as e:  # noqa: BLE001 – counting must never break a tool call
        log.debug("tool stats: %s", e)


def tool_health(rt: Any, days: int = 7, min_calls: int = 3) -> list[dict]:
    """Tools by failure rate over the last `days` (only those used at least `min_calls` times)."""
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    rows = _db(rt).all("SELECT tool, SUM(calls) c, SUM(fails) f, SUM(ms_total) ms FROM tool_stats WHERE day >= ? "
                       "GROUP BY tool", (since,))
    out = [{"tool": r["tool"], "calls": int(r["c"]), "fails": int(r["f"]), "rate": round(r["f"] / r["c"], 3),
            "avg_ms": int(r["ms"] / r["c"])} for r in rows if r["c"] >= min_calls]
    return sorted(out, key=lambda x: (-x["rate"], -x["calls"]))


def by_version(rt: Any, limit: int = 6) -> list[dict]:
    """Failure rate of each version JARVIS ran (newest first): is the new one better than the one before?"""
    rows = _db(rt).all("SELECT version, SUM(calls) c, SUM(fails) f, MIN(day) since FROM tool_stats GROUP BY version")
    from .updater import parse

    out = [{"version": r["version"], "calls": int(r["c"]), "fails": int(r["f"]),
            "rate": round(r["f"] / r["c"], 3) if r["c"] else 0.0, "since": r["since"]} for r in rows]
    return sorted(out, key=lambda x: parse(x["version"]), reverse=True)[:limit]


def model_latency(rt: Any) -> list[dict]:
    """Median time to the first word of each AI (from the router's last 20 answers)."""
    router = getattr(rt, "router", None)
    out = []
    for pid, q in (getattr(router, "ttft", None) or {}).items():
        vals = [v for v in q if isinstance(v, (int, float))]
        if vals:
            out.append({"provider": pid, "median_ms": int(statistics.median(vals)), "answers": len(vals),
                        "error": (getattr(router, "last_errors", {}) or {}).get(pid, "")})
    return sorted(out, key=lambda x: x["median_ms"])


def crashes(days: int = 7) -> int:
    """Errors JARVIS wrote to its log in the last days (a crashed thread, a failed handler)."""
    from . import paths

    n, since = 0, time.time() - days * 86400
    for f in (paths.data_dir() / "logs").glob("*.log*") if (paths.data_dir() / "logs").exists() else []:
        try:
            if f.stat().st_mtime < since:
                continue
            with open(f, encoding="utf-8", errors="replace") as fh:
                n += sum(1 for ln in fh if " ERROR " in ln or " CRITICAL " in ln)
        except OSError:
            continue
    return n


def health(rt: Any, days: int = 7) -> dict:
    tools_ = tool_health(rt, days)
    vers = by_version(rt)
    verdict = ""
    if len(vers) >= 2 and vers[0]["calls"] >= 20 and vers[1]["calls"] >= 20:
        d = vers[0]["rate"] - vers[1]["rate"]
        verdict = ("lepší" if d < -0.01 else "horší" if d > 0.01 else "stejná")
    return {"tools": tools_[:15], "failing": [t for t in tools_ if t["rate"] >= 0.3][:8], "models": model_latency(rt),
            "versions": vers, "verdict": verdict, "errors": crashes(days), "power": POWER.report() if POWER else None,
            "voice": voice_latency(rt)}


# ---------- 1 / 16: how fast the voice answers ----------
VOICE_TARGET_MS = 1200


def voice_latency(rt: Any) -> dict:
    """End of your sentence → JARVIS's first sound (the voice loop measures each answer)."""
    vals = list(getattr(rt, "voice_lat", None) or [])
    if not vals:
        return {"answers": 0, "median_ms": None, "p90_ms": None, "target_ms": VOICE_TARGET_MS}
    s = sorted(vals)
    return {"answers": len(s), "median_ms": int(statistics.median(s)), "p90_ms": int(s[min(len(s) - 1, int(len(s) * 0.9))]),
            "target_ms": VOICE_TARGET_MS, "ok": statistics.median(s) <= VOICE_TARGET_MS}


# ---------- 12: regressions after an update ----------
def regressions(before: list[dict], now: list[dict]) -> list[dict]:
    """Core parts that worked in the last check of the previous version and fail now."""
    was_ok = {i.get("key") for i in before or [] if i.get("ok") is True}
    return [i for i in now or [] if i.get("key") in CORE_KEYS and i.get("key") in was_ok and i.get("ok") is False]


def should_roll_back(regs: list[dict]) -> bool:
    keys = {r.get("key") for r in regs}
    return bool(keys & CRITICAL_KEYS) or len(keys) >= 2


# ---------- 17: one-click bug report ----------
def repo_of(update_url: str) -> str:
    """'owner/repo' from the update address (api.github.com/repos/OWNER/REPO/releases/latest)."""
    p = urllib.parse.urlparse(update_url or "")
    parts = [x for x in p.path.split("/") if x]
    if p.netloc == "api.github.com" and len(parts) >= 3 and parts[0] == "repos":
        return f"{parts[1]}/{parts[2]}"
    if p.netloc == "github.com" and len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return ""


MAX_BODY = 5500        # a GitHub "new issue" link stays well under the 8 KB browsers and GitHub accept


def issue_url(rt: Any, title: str, what: str = "") -> str:
    """A pre-filled GitHub issue: what happened (your words) + diagnostics without keys, passwords or tokens."""
    from . import upkeep
    from .redact import redact

    repo = repo_of(rt.cfg.general.update_url)
    if not repo:
        return ""
    diag = upkeep.summary(rt)
    body = (f"**Co se stalo:**\n{redact(what.strip()) or '(popiš, co jsi dělal a co se stalo)'}\n\n"
            f"**Diagnostika** (bez klíčů a hesel):\n```\n{diag}\n```")
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY - 40] + "\n…(zkráceno)\n```"
    q = urllib.parse.urlencode({"title": redact(title.strip())[:120] or "Chyba v JARVISovi", "body": body,
                                "labels": "bug"})
    return f"https://github.com/{repo}/issues/new?{q}"


# ---------- 20: what JARVIS takes from the battery ----------
class PowerMeter:
    """Every minute: JARVIS's processor time vs the whole PC's, and the battery level while on battery."""

    def __init__(self) -> None:
        self.samples: deque = deque(maxlen=180)     # 3 hours
        self._last: tuple[float, float, float] | None = None

    def sample(self) -> dict | None:
        try:
            import psutil

            me = psutil.Process(os.getpid())
            cpu_me = sum(me.cpu_times()[:2]) + sum(sum(c.cpu_times()[:2]) for c in me.children(recursive=True))
            cpu_all = sum(psutil.cpu_times()[:3])
            bat = psutil.sensors_battery()
        except Exception as e:  # noqa: BLE001
            log.debug("power sample: %s", e)
            return None
        now = time.time()
        row = None
        if self._last:
            t0, me0, all0 = self._last
            d_all = max(1e-6, cpu_all - all0)
            row = {"ts": now, "share": max(0.0, min(1.0, (cpu_me - me0) / d_all)),
                   "pc_cpu": round(d_all / max(1e-6, (now - t0) * (os.cpu_count() or 1)) * 100, 1),
                   "battery": bat.percent if bat else None, "plugged": bat.power_plugged if bat else None}
            self.samples.append(row)
        self._last = (now, cpu_me, cpu_all)
        return row

    def report(self) -> dict:
        s = list(self.samples)
        if not s:
            return {"samples": 0}
        share = statistics.mean(x["share"] for x in s)
        out: dict = {"samples": len(s), "cpu_share": round(share * 100, 2)}
        unplugged = [x for x in s if x["plugged"] is False and x["battery"] is not None]
        if len(unplugged) >= 2 and unplugged[-1]["ts"] > unplugged[0]["ts"]:
            hours = (unplugged[-1]["ts"] - unplugged[0]["ts"]) / 3600
            drain = (unplugged[0]["battery"] - unplugged[-1]["battery"]) / hours if hours > 0 else 0
            if drain > 0:
                out["drain_per_h"] = round(drain, 1)
                # what JARVIS takes is roughly its share of the processor time (the screen and Wi-Fi are not counted)
                out["jarvis_per_h"] = round(drain * share, 2)
        return out


POWER: PowerMeter | None = PowerMeter()


async def power_loop(stop_after: float | None = None) -> None:
    import asyncio

    started = time.time()
    while POWER is not None and (stop_after is None or time.time() - started < stop_after):
        await asyncio.to_thread(POWER.sample)
        await asyncio.sleep(60)


def dumps(d: Any) -> str:
    return json.dumps(d, ensure_ascii=False, default=str)
