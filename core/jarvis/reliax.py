"""3.20 Spolehlivost+ (ideas 441–460): crashed parts restarted with the reason said, one health score 0–100 with what to
do, the settings' history by day, the PC clock checked against internet time, the phone's photo backup checked, a safe
mode (only the core), answer speed over weeks, a UPS that saves the day on a power cut, a restore drill, JARVIS's own
files checked, an alarm that nobody reacted to rings again, a stress test, a settings check, backup internet through
the phone, a check after an AI model changes, the silent errors of the week, a morning voice check and a monthly report.

Nothing here changes anything on its own except what you switch on (UPS shutdown, hotspot)."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
import os
import re
import socket
import sqlite3
import statistics
import struct
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS rx_events (ts REAL, kind TEXT, name TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS rx_speed (day TEXT, stage TEXT, median INTEGER, n INTEGER, PRIMARY KEY (day, stage));
CREATE TABLE IF NOT EXISTS rx_score (day TEXT PRIMARY KEY, score INTEGER, problems TEXT);
"""


def db(rt: Any):
    if not getattr(rt, "_reliax_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._reliax_ready = True
    return rt.db


def cfg(rt: Any) -> Any:
    from .config import ReliaXCfg

    return getattr(rt.cfg, "reliax", None) or ReliaXCfg()


def event(rt: Any, kind: str, name: str, detail: str = "") -> None:
    db(rt).exec("INSERT INTO rx_events VALUES (?,?,?,?)", (time.time(), kind, name, detail[:400]))


def kv_get(rt: Any, key: str) -> str | None:
    row = rt.db.one("SELECT v FROM kv WHERE k=?", (key,))
    return row["v"] if row else None


def kv_set(rt: Any, key: str, v: str) -> None:
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, v))


# ------------------------------------------------------------------ (441) self-healing
SAFE_ERR = {"ConnectionError": "spojení vypadlo", "TimeoutError": "nic neodpovídalo včas", "PermissionError": "chybí oprávnění",
            "FileNotFoundError": "chybí soubor", "MemoryError": "došla paměť", "OSError": "chyba systému"}


def human_reason(e: BaseException) -> str:
    name = type(e).__name__
    return f"{SAFE_ERR.get(name, name)}: {str(e)[:120]}".rstrip(": ")


async def supervise(rt: Any, name: str, factory: Callable[[], Awaitable[Any]], max_restarts: int = 5, base_wait: float = 5.0,
                    sleep=asyncio.sleep) -> None:
    """Runs a background part; when it crashes it is started again (5 s, 10 s, 20 s … apart) and you are told why. After
    `max_restarts` crashes within an hour it stays off and the health score says so."""
    crashes: list[float] = []
    while True:
        try:
            await factory()
            return                                         # finished normally
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            now = time.time()
            crashes = [t for t in crashes if now - t < 3600] + [now]
            why = human_reason(e)
            log.warning("part %s crashed: %s", name, why)
            event(rt, "crash", name, why)
            if len(crashes) > max_restarts:
                event(rt, "gave_up", name, why)
                rt.notify("Část JARVISe je vypnutá", f"{name} za hodinu spadla {len(crashes)}× ({why}). Nechal jsem ji vypnutou – "
                                                     "zbytek běží. Pomůže restart JARVISe nebo „zdraví JARVISe“.", speak=False)
                return
            rt.notify("Samoopravení", f"{name} spadla ({why}) – spouštím ji znovu.", speak=False)
            await sleep(base_wait * 2 ** (len(crashes) - 1))


def crashed_tasks(tasks: list[asyncio.Task]) -> list[tuple[str, str]]:
    """Background tasks that ended with an error: (name, reason)."""
    out = []
    for t in tasks:
        if t.done() and not t.cancelled() and t.exception() is not None:
            coro = t.get_coro()
            name = getattr(coro, "__qualname__", None) or t.get_name()
            out.append((str(name), human_reason(t.exception())))    # type: ignore[arg-type]
    return out


def watch_tasks(rt: Any) -> list[str]:
    said = []
    seen: set[str] = getattr(rt, "_rx_seen_crash", set())
    for name, why in crashed_tasks(list(getattr(rt, "_sys_tasks", []) or [])):
        if name in seen:
            continue
        seen.add(name)
        event(rt, "crash", name, why)
        said.append(f"{name}: {why}")
    rt._rx_seen_crash = seen
    if said:
        rt.notify("Něco spadlo", "Tyhle části skončily s chybou: " + "; ".join(said) + ". Restart JARVISe je obnoví.", speak=False)
    return said


# ------------------------------------------------------------------ (444) the clock
def sntp_offset(server: str = "pool.ntp.org", timeout: float = 3.0, sock_factory=socket.socket) -> float:
    """Seconds the PC clock is ahead (+) or behind (−) internet time (SNTP, one query)."""
    packet = b"\x1b" + 47 * b"\0"
    s = sock_factory(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        t0 = time.time()
        s.sendto(packet, (server, 123))
        data, _ = s.recvfrom(48)
        t3 = time.time()
    finally:
        s.close()
    if len(data) < 48:
        raise ValueError("Krátká odpověď časového serveru.")
    secs, frac = struct.unpack("!II", data[40:48])
    server_time = secs - 2208988800 + frac / 2**32
    return round(((t0 + t3) / 2) - server_time, 2)


def clock_text(offset: float) -> str:
    if abs(offset) < 5:
        return f"Hodiny jdou přesně (odchylka {offset:+.1f} s)."
    side = "napřed" if offset > 0 else "pozadu"
    return (f"Hodiny PC jdou o {abs(offset):.0f} s {side} – připomínky a budíky by se posunuly. Oprava: Nastavení Windows → Čas a jazyk → "
            "Synchronizovat teď (nebo zapnout automatický čas).")


# ------------------------------------------------------------------ (443) settings history
def history_dir() -> Path:
    from . import paths

    d = paths.data_dir() / "config-history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def snapshot(day: dt.date | None = None, keep: int = 180) -> Path | None:
    """A copy of today's settings (once a day; an unchanged day is not copied again)."""
    from .config import config_path

    src = config_path()
    if not src.exists():
        return None
    dst = history_dir() / f"config-{(day or dt.date.today()).isoformat()}.toml"
    data = src.read_bytes()
    if dst.exists() and dst.read_bytes() == data:
        return dst
    dst.write_bytes(data)
    old = sorted(history_dir().glob("config-*.toml"))
    for p in old[:-keep]:
        p.unlink()
    return dst


def history() -> list[str]:
    return sorted((p.stem.removeprefix("config-") for p in history_dir().glob("config-*.toml")), reverse=True)


def restore_settings(rt: Any, day: str) -> str:
    """Your settings as they were on `day` (or the nearest earlier day). Today's settings are kept in the history too."""
    import tomllib

    from .config import Config

    days = [d for d in history() if d <= day]
    if not days:
        raise ValueError(f"Z {day} ani dřív nemám uložené nastavení. Mám: {', '.join(history()[:5]) or 'nic'}.")
    p = history_dir() / f"config-{days[0]}.toml"
    old = Config.model_validate(tomllib.loads(p.read_text(encoding="utf-8")))
    snapshot()
    rt.update_config(old.model_dump(mode="json"))
    event(rt, "settings_restore", days[0])
    return days[0]


# ------------------------------------------------------------------ (454) settings check
def config_issues(rt: Any) -> list[dict]:
    """Mistakes in the settings, each with what to do."""
    c = rt.cfg
    out: list[dict] = []

    def add(what: str, fix: str) -> None:
        out.append({"what": what, "fix": fix})

    for f in getattr(c.tools, "allowed_folders", []) or []:
        if not Path(f).expanduser().exists():
            add(f"Povolená složka „{f}“ neexistuje.", "Oprav ji nebo odeber v Nastavení → Nástroje.")
    for i, url in enumerate(getattr(c.calendar, "ics_urls", []) or []):
        if not re.match(r"^(https?|webcal)://", url):
            add(f"Kalendář {i + 1} nemá platnou adresu.", "Adresa musí začínat https:// nebo webcal://.")
    try:
        enabled = [p for p in c.brain.providers if p.enabled]
        if not enabled:
            add("Není zapnutý žádný mozek (AI).", "Zapni aspoň jeden v Nastavení → Mozek.")
        for p in enabled:
            if p.base_url and not p.base_url.startswith(("http://", "https://")):
                add(f"Mozek {p.id}: adresa „{p.base_url}“ není URL.", "Oprav adresu serveru.")
    except AttributeError:
        pass
    port = getattr(c.phone, "port", 8765)
    if not 1024 <= int(port) <= 65535:
        add(f"Port {port} je mimo rozsah.", "Použij číslo 1024–65535 (výchozí 8765).")
    hx = getattr(c, "homex", None)
    if hx is not None and getattr(hx, "solar_loads", None) and not getattr(hx, "solar_entity", ""):
        add("Přebytky z FVE mají spotřebiče, ale chybí čidlo výkonu.", "Doplň solar_entity (Domácnost → Fotovoltaika).")
    sx = getattr(c, "shopx", None)
    if sx is not None and sx.iron_plug and not sx.iron_plug.startswith("switch."):
        add(f"Páječka „{sx.iron_plug}“ není vypínač.", "Zadej entitu switch.* chytré zásuvky.")
    fx = getattr(c, "funx", None)
    if fx is not None:
        for kid, mins in (fx.play_limits or {}).items():
            if not 0 < mins <= 600:
                add(f"Limit hraní pro {kid} je {mins} min.", "Zadej 1–600 minut.")
    rx = cfg(rt)
    if rx.ups and rx.ups_shutdown_pct and not 5 <= rx.ups_shutdown_pct <= 80:
        add(f"Vypnutí při {rx.ups_shutdown_pct} % baterie UPS.", "Rozumné je 15–40 %.")
    return out


# ------------------------------------------------------------------ (445) the phone's photo backup
def photo_backup_state(folder: Path, now: float | None = None, max_days: float = 3) -> dict:
    now = time.time() if now is None else now
    if not folder.is_dir():
        return {"ok": False, "why": "Záloha fotek z telefonu není zapnutá (složka neexistuje)."}
    newest = 0.0
    n = 0
    for p in folder.rglob("*"):
        if p.is_file():
            n += 1
            newest = max(newest, p.stat().st_mtime)
    if not n:
        return {"ok": False, "why": "Ve složce zálohy fotek nic není."}
    days = (now - newest) / 86400
    return {"ok": days <= max_days, "files": n, "days": round(days, 1),
            "why": "" if days <= max_days else f"Poslední fotka z telefonu přišla před {days:.0f} dny – otevři aplikaci JARVIS v telefonu "
                                              "a zkontroluj, že má povolené fotky a běží na pozadí."}


# ------------------------------------------------------------------ (447) speed over weeks
def speed_record(rt: Any, day: dt.date | None = None) -> int:
    from .latency import get

    st = get(rt).stats()
    d = (day or dt.date.today()).isoformat()
    n = 0
    for stage, v in (st.get("stages") or {}).items():
        db(rt).exec("INSERT OR REPLACE INTO rx_speed VALUES (?,?,?,?)", (d, stage, int(v["median"]), int(v["n"])))
        n += 1
    return n


def speed_weeks(rt: Any, stage: str = "done", weeks: int = 8, today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    out = []
    for w in range(weeks - 1, -1, -1):
        end = today - dt.timedelta(days=7 * w)
        start = end - dt.timedelta(days=6)
        rows = db(rt).all("SELECT median FROM rx_speed WHERE stage=? AND day BETWEEN ? AND ?", (stage, start.isoformat(), end.isoformat()))
        vals = [r["median"] for r in rows]
        out.append({"week": f"{start:%d.%m.}", "ms": int(statistics.median(vals)) if vals else None})
    return out


# ------------------------------------------------------------------ (449) UPS
def ups_decision(battery: Any, on_battery_since: float | None, now: float, shutdown_pct: int, shutdown_minutes: int) -> tuple[str, float | None]:
    """('', since) nothing / ('outage', since) power just failed / ('restored', None) / ('shutdown', since)."""
    if battery is None:
        return "", None
    if battery.power_plugged:
        return ("restored", None) if on_battery_since is not None else ("", None)
    if on_battery_since is None:
        return "outage", now
    low = shutdown_pct and battery.percent is not None and battery.percent <= shutdown_pct
    long_ = shutdown_minutes and now - on_battery_since >= shutdown_minutes * 60
    return ("shutdown", on_battery_since) if (low or long_) else ("", on_battery_since)


# ------------------------------------------------------------------ (450) restore drill
def restore_drill(backup: Path, password: str, workdir: Path) -> dict:
    """Decrypts a backup into a scratch folder and checks the database and the settings in it – the live data is not touched."""
    import tomllib

    from . import privacy
    from .config import Config

    files = privacy.restore_encrypted(backup, password, workdir)
    found = {Path(f).name: workdir / f for f in files}
    report: dict[str, Any] = {"files": len(files), "db": None, "config": None}
    dbf = next((p for n, p in found.items() if n.endswith(".db")), None)
    if dbf and dbf.exists():
        con = sqlite3.connect(dbf)
        try:
            report["db"] = con.execute("PRAGMA integrity_check").fetchone()[0]
            report["tables"] = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        finally:
            con.close()
    cf = found.get("config.toml")
    if cf and cf.exists():
        try:
            Config.model_validate(tomllib.loads(cf.read_text(encoding="utf-8")))
            report["config"] = "ok"
        except Exception as e:  # noqa: BLE001
            report["config"] = f"chyba: {str(e)[:120]}"
    report["ok"] = report["db"] == "ok" and report["config"] in ("ok", None)
    return report


# ------------------------------------------------------------------ (451) JARVIS's own files
def file_hashes(root: Path, patterns: tuple[str, ...] = ("*.py", "*.js", "*.html", "*.css", "*.json")) -> dict[str, str]:
    out = {}
    for pat in patterns:
        for p in root.rglob(pat):
            if "__pycache__" in p.parts or not p.is_file():
                continue
            out[str(p.relative_to(root)).replace("\\", "/")] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def integrity_check(root: Path, baseline: dict[str, str]) -> dict:
    now = file_hashes(root)
    changed = sorted(k for k in baseline if k in now and now[k] != baseline[k])
    missing = sorted(k for k in baseline if k not in now)
    added = sorted(k for k in now if k not in baseline)
    return {"ok": not (changed or missing), "changed": changed, "missing": missing, "added": added, "files": len(now)}


def integrity(rt: Any, root: Path | None = None) -> dict:
    """The first run of each version remembers the files' fingerprints; later runs compare. Catches a change after
    installation (malware, a broken disk, someone editing JARVIS) – not one made before the first run."""
    from . import __version__, paths

    root = root or Path(__file__).resolve().parent
    f = paths.data_dir() / f"integrity-{__version__}.json"
    if not f.exists():
        f.write_text(json.dumps(file_hashes(root)), encoding="utf-8")
        return {"ok": True, "first": True, "files": len(json.loads(f.read_text(encoding="utf-8")))}
    return integrity_check(root, json.loads(f.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ (452) an alarm nobody reacted to
def alarm_fired(rt: Any, title: str, now: float | None = None) -> None:
    kv_set(rt, "rx_alarm", json.dumps({"title": title, "at": time.time() if now is None else now, "idle0": rt.platform.idle_seconds()}))


def alarm_check(rt: Any, now: float | None = None, wait_min: int = 8) -> str:
    raw = kv_get(rt, "rx_alarm")
    if not raw:
        return ""
    a = json.loads(raw)
    now = time.time() if now is None else now
    if now - a["at"] < wait_min * 60:
        return ""
    rt.db.exec("DELETE FROM kv WHERE k='rx_alarm'")
    idle = rt.platform.idle_seconds()
    from .latency import get as latency

    spoke = any(t.get("ts", 0) > a["at"] for t in latency(rt).turns)       # you said or wrote something to JARVIS since
    reacted = bool(idle and idle < now - a["at"]) or spoke
    event(rt, "alarm", a["title"], "reacted" if reacted else "no reaction")
    if reacted:
        return ""
    rt.phone_push("ring", reason="alarm")
    rt.notify("Budík", f"{a['title']} – nevidím, že bys vstal(a). Zvoním znovu.", speak=True, urgent=True)
    return a["title"]


# ------------------------------------------------------------------ (453) stress test
async def stress(rt: Any, n: int = 300, concurrency: int = 20) -> dict:
    """Hundreds of commands through what runs before the AI (instant commands, tool choice, the database) at once –
    where the time goes when many come together."""
    from . import instant, tools
    from .evals.cases import INSTANT, PICK
    from .tools import select

    tools.load_builtin()
    texts = [t for t, *_ in INSTANT] + [t for t, _ in PICK]
    times: dict[str, list[float]] = {"instant": [], "pick": [], "db": []}
    slow: list[tuple[float, str]] = []
    sem = asyncio.Semaphore(concurrency)
    allowed = set(tools.REGISTRY)

    async def one(i: int) -> None:
        text = texts[i % len(texts)]
        async with sem:
            t0 = time.perf_counter()
            try:
                instant.plan(text)
            except Exception:  # noqa: BLE001
                pass
            t1 = time.perf_counter()
            await asyncio.to_thread(select.pick, tools.REGISTRY, allowed, text, [])
            t2 = time.perf_counter()
            await asyncio.to_thread(rt.db.one, "SELECT COUNT(*) n FROM kv")
            t3 = time.perf_counter()
        times["instant"].append((t1 - t0) * 1000)
        times["pick"].append((t2 - t1) * 1000)
        times["db"].append((t3 - t2) * 1000)
        slow.append(((t3 - t0) * 1000, text))

    t_all = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(n)))
    total = time.perf_counter() - t_all

    def pct(v: list[float], q: float) -> float:
        s = sorted(v)
        return round(s[min(len(s) - 1, int(len(s) * q))], 2) if s else 0.0

    stages = {k: {"p50": pct(v, 0.5), "p95": pct(v, 0.95)} for k, v in times.items()}
    worst = max(stages, key=lambda k: stages[k]["p95"])
    return {"n": n, "seconds": round(total, 2), "per_s": round(n / total, 1) if total else 0, "stages": stages, "bottleneck": worst,
            "slowest": [t for _, t in sorted(slow, reverse=True)[:3]]}


# ------------------------------------------------------------------ (455) backup internet
def online(hosts: tuple[tuple[str, int], ...] = (("1.1.1.1", 443), ("8.8.8.8", 53)), timeout: float = 2.0,
           connect=socket.create_connection) -> bool:
    for h in hosts:
        try:
            connect(h, timeout=timeout).close()
            return True
        except OSError:
            continue
    return False


def hotspot_command(ssid: str) -> str:
    safe = re.sub(r'["&|<>^%]', "", ssid)[:64]
    return f'netsh wlan connect name="{safe}"'


# ------------------------------------------------------------------ (442) the health score, (460) the month
def score(rt: Any, extra: list[dict] | None = None) -> dict:
    """0–100 and the list of problems, the worst first, each with what to do."""
    from . import quality

    problems: list[dict] = []

    def bad(points: int, what: str, fix: str) -> None:
        problems.append({"points": points, "what": what, "fix": fix})

    errors = quality.crashes(7)
    if errors > 50:
        bad(15, f"{errors} chyb v logu za týden", "Pošli zprávu o chybě (Diagnostika → Nahlásit) – je to víc než obvykle.")
    elif errors > 10:
        bad(5, f"{errors} chyb v logu za týden", "Mrkni do Diagnostiky, co se opakuje.")
    for t in quality.tool_health(rt, 7)[:20]:
        if t.get("rate", 0) >= 0.3 and t.get("calls", 0) >= 5:
            bad(5, f"nástroj {t['tool']} selhává v {int(t['rate'] * 100)} % případů", "Zkontroluj jeho propojení nebo klíč.")
    gave_up = db(rt).all("SELECT name, detail FROM rx_events WHERE kind='gave_up' AND ts >= ?", (time.time() - 86400,))
    for g in gave_up:
        bad(15, f"část {g['name']} je vypnutá ({g['detail']})", "Restartuj JARVISe.")
    for i in config_issues(rt):
        bad(4, i["what"], i["fix"])
    try:
        import psutil

        from . import paths

        free = psutil.disk_usage(str(paths.data_dir())).free / 1e9
        if free < 2:
            bad(20, f"na disku zbývá jen {free:.1f} GB", "Uvolni místo (úklid PC: „ukliď disk“).")
        elif free < 10:
            bad(5, f"na disku zbývá {free:.0f} GB", "Brzy bude potřeba uklidit.")
    except Exception:  # noqa: BLE001
        pass
    off = kv_get(rt, "rx_clock")
    if off is not None and abs(float(off)) >= 30:
        bad(10, f"hodiny PC jdou o {abs(float(off)):.0f} s vedle", "Synchronizuj čas ve Windows.")
    if getattr(rt, "safe_mode", False):
        bad(10, "JARVIS běží v nouzovém režimu", "Restartuj ho normálně, až bude problém vyřešený.")
    v = quality.voice_latency(rt)
    if v.get("median_ms") and v["median_ms"] > 2 * v["target_ms"]:
        bad(5, f"hlas odpovídá pomalu ({v['median_ms']} ms)", "Zkus rychlejší mozek nebo „změř rychlost“.")
    for e in extra or []:
        bad(int(e.get("points", 5)), e["what"], e.get("fix", ""))
    total = max(0, 100 - sum(p["points"] for p in problems))
    problems.sort(key=lambda p: -p["points"])
    return {"score": total, "problems": problems, "word": "výborné" if total >= 90 else "dobré" if total >= 75 else "slabší" if total >= 50 else "špatné"}


def month_report(rt: Any, year: int, month: int) -> dict:
    a = dt.datetime(year, month, 1).timestamp()
    b = dt.datetime(year + (month == 12), month % 12 + 1, 1).timestamp()
    ev = [dict(r) for r in db(rt).all("SELECT kind, name, detail FROM rx_events WHERE ts >= ? AND ts < ?", (a, b))]
    sc = [r["score"] for r in db(rt).all("SELECT score FROM rx_score WHERE day >= ? AND day < ?",
                                          (f"{year}-{month:02d}-01", dt.date.fromtimestamp(b).isoformat()))]
    crashes = [e for e in ev if e["kind"] == "crash"]
    by: dict[str, int] = {}
    for e in crashes:
        by[e["name"]] = by.get(e["name"], 0) + 1
    out = {"month": f"{month:02d}/{year}", "crashes": len(crashes), "fixed": len(crashes) - sum(1 for e in ev if e["kind"] == "gave_up"),
           "worst": sorted(by.items(), key=lambda x: -x[1])[:3], "score_avg": round(statistics.mean(sc)) if sc else None,
           "score_min": min(sc) if sc else None, "alarms_missed": sum(1 for e in ev if e["kind"] == "alarm" and e["detail"] == "no reaction"),
           "restores": sum(1 for e in ev if e["kind"] == "settings_restore")}
    return out


def month_text(r: dict, prev: dict | None = None) -> str:
    s = f"Spolehlivost za {r['month']}: "
    s += (f"skóre zdraví v průměru {r['score_avg']} (nejhůř {r['score_min']}), " if r["score_avg"] is not None else "")
    s += f"{r['crashes']} pádů částí, {r['fixed']} opraveno samo"
    if r["worst"]:
        s += " (nejčastěji " + ", ".join(f"{n} {c}×" for n, c in r["worst"]) + ")"
    if r["alarms_missed"]:
        s += f", {r['alarms_missed']}× budík zazvonil znovu, protože nikdo nereagoval"
    if prev and prev.get("score_avg") is not None and r["score_avg"] is not None:
        d = r["score_avg"] - prev["score_avg"]
        s += f". Oproti minulému měsíci {'+' if d >= 0 else ''}{d} bodů"
    return s + "."


# ------------------------------------------------------------------ (457) a new AI model → a check
def model_signature(rt: Any) -> dict[str, str]:
    try:
        return {p.id: f"{p.model}|{p.fast_model}" for p in rt.cfg.brain.providers if p.enabled}
    except AttributeError:
        return {}


def models_changed(rt: Any) -> list[str]:
    now = model_signature(rt)
    raw = kv_get(rt, "rx_models")
    kv_set(rt, "rx_models", json.dumps(now))
    if raw is None:
        return []
    before = json.loads(raw)
    return [pid for pid, sig in now.items() if pid in before and before[pid] != sig]


async def model_check(rt: Any, pid: str, limit: int = 10) -> dict:
    """A small live eval of the provider whose model changed, compared with its last result."""
    from . import evals

    res = await evals.live(rt, limit=limit, providers=[pid])
    score_now = float(res.get("score", 0) or 0)
    key = f"rx_model_score_{pid}"
    prev = kv_get(rt, key)
    kv_set(rt, key, str(score_now))
    return {"provider": pid, "score": score_now, "before": float(prev) if prev else None}


# ------------------------------------------------------------------ every minute (proactx)
async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    from .proactiveplus import due_today

    now = now or dt.datetime.now()
    ts = now.timestamp()
    c = cfg(rt)
    said: list[str] = []
    said += watch_tasks(rt)
    t = alarm_check(rt, ts)
    if t:
        said.append(f"budík {t} znovu")
    if c.ups:
        try:
            import psutil

            batt = psutil.sensors_battery()
        except Exception:  # noqa: BLE001
            batt = None
        since = kv_get(rt, "rx_ups")
        what, new_since = ups_decision(batt, float(since) if since else None, ts, c.ups_shutdown_pct, c.ups_shutdown_minutes)
        if what == "outage":
            kv_set(rt, "rx_ups", str(new_since))
            rt.notify("Výpadek proudu", f"PC jede z UPS ({batt.percent:.0f} %). Ulož si práci.", speak=True, urgent=True)
            event(rt, "power", "outage")
            said.append("outage")
        elif what == "restored":
            rt.db.exec("DELETE FROM kv WHERE k='rx_ups'")
            rt.notify("Proud je zpět", "UPS se nabíjí.", speak=False)
            event(rt, "power", "restored")
        elif what == "shutdown" and not kv_get(rt, "rx_ups_off"):
            kv_set(rt, "rx_ups_off", "1")
            rt.notify("Vypínám PC", "UPS dochází. Za 2 minuty vypnu počítač – ulož si práci. Zrušíš to příkazem „nevypínej“.",
                      speak=True, urgent=True)
            event(rt, "power", "shutdown")
            if os.name == "nt":
                await asyncio.to_thread(rt.platform.run_shell, 'shutdown /s /t 120 /c "JARVIS: dochází UPS, vypínám PC."', 15)
            said.append("shutdown")
    if c.hotspot_ssid and ts - getattr(rt, "_rx_net_at", 0.0) >= 60:
        rt._rx_net_at = ts
        up = await asyncio.to_thread(online)
        down = int(kv_get(rt, "rx_net_down") or 0)
        if not up:
            down += 1
            kv_set(rt, "rx_net_down", str(down))
            if down == 2:
                rt.phone_push("notify", title="Internet vypadl", body="Zapni prosím hotspot – PC se k němu připojí.")
                if os.name == "nt":
                    await asyncio.to_thread(rt.platform.run_shell, hotspot_command(c.hotspot_ssid), 20)
                event(rt, "net", "down")
                said.append("hotspot")
        elif down:
            rt.db.exec("DELETE FROM kv WHERE k='rx_net_down'")
            if down >= 2:
                rt.notify("Internet je zpět", "Hotspot v telefonu můžeš vypnout.", speak=False)
                event(rt, "net", "up")
    if due_today(rt, "rx_daily", "03:30", now):
        kv_set(rt, "rx_daily", now.date().isoformat())
        try:
            snapshot(now.date())
        except OSError:
            pass
        speed_record(rt, now.date() - dt.timedelta(days=1))
        try:
            kv_set(rt, "rx_clock", str(await asyncio.to_thread(sntp_offset)))
        except (OSError, ValueError):
            pass
        sc = score(rt)
        db(rt).exec("INSERT OR REPLACE INTO rx_score VALUES (?,?,?)", (now.date().isoformat(), sc["score"], json.dumps(sc["problems"][:8], ensure_ascii=False)))
        integ = integrity(rt)
        if not integ.get("ok"):
            rt.notify("Soubory JARVISe se změnily", f"Změněno {len(integ['changed'])}, chybí {len(integ['missing'])} (např. "
                                                    f"{(integ['changed'] + integ['missing'])[0]}). Pokud jsi nic neupravoval(a), přeinstaluj JARVIS.")
            said.append("integrity")
        changed = models_changed(rt)
        if changed and c.model_evals:
            for pid in changed[:2]:
                try:
                    m = await model_check(rt, pid)
                    worse = m["before"] is not None and m["score"] < m["before"] - 0.05
                    rt.notify("Nový model AI", f"{pid}: výsledek testu {m['score']:.0%}" + (f" (dřív {m['before']:.0%})" if m["before"] is not None else "")
                              + (" – je horší, zvaž návrat k předchozímu modelu." if worse else "."), speak=False)
                    event(rt, "model", pid, f"{m['score']:.2f}")
                except Exception as e:  # noqa: BLE001
                    log.info("model check %s: %s", pid, e)
    off = kv_get(rt, "rx_clock")
    if off is not None and abs(float(off)) >= 30 and due_today(rt, "rx_clock_told", "09:00", now):
        kv_set(rt, "rx_clock_told", now.date().isoformat())
        rt.notify("Hodiny PC", clock_text(float(off)), speak=False)
        said.append("clock")
    if c.voice_check and due_today(rt, "rx_voice", c.voice_check, now) and getattr(rt, "voice", None) is not None:
        kv_set(rt, "rx_voice", now.date().isoformat())
        try:
            from . import speedcheck

            res = await speedcheck.run_voice(rt)
            if not res or any(not r.get("ok", True) for r in res):
                rt.notify("Ranní kontrola hlasu", "Rozpoznávání nebo hlas dnes ráno neprošlo – zkus „kontrola hlasu“.", speak=False)
                said.append("voice_check")
        except Exception as e:  # noqa: BLE001
            rt.notify("Ranní kontrola hlasu", f"Hlas se nepodařilo ověřit ({human_reason(e)}).", speak=False)
    if now.weekday() == 0 and due_today(rt, "rx_week", "09:15", now):
        kv_set(rt, "rx_week", now.date().isoformat())
        from . import quality

        errs = quality.crashes(7)
        crashes = db(rt).all("SELECT name, COUNT(*) n FROM rx_events WHERE kind='crash' AND ts >= ? GROUP BY name", (ts - 7 * 86400,))
        if errs or crashes:
            rt.notify("Tiché chyby za týden", f"{errs} chyb v logu" + ("; spadlo: " + ", ".join(f"{r['name']} {r['n']}×" for r in crashes) if crashes else "")
                      + ". Detail: „zdraví JARVISe“.", speak=False)
            said.append("week")
    if now.day == 1 and due_today(rt, "rx_month", "09:30", now):
        kv_set(rt, "rx_month", now.date().isoformat())
        last = now.date().replace(day=1) - dt.timedelta(days=1)
        prev = last.replace(day=1) - dt.timedelta(days=1)
        r = month_report(rt, last.year, last.month)
        rt.notify("Měsíční zpráva o spolehlivosti", month_text(r, month_report(rt, prev.year, prev.month)), speak=False)
        said.append("month")
    return said
