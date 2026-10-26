"""3.2 "Stark": protocols, the morning briefing, the guardian and the "JARVIS online" greeting.

Everything here talks like the JARVIS of the films: short, polite, a little dry, addressing the user ("pane").
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

log = logging.getLogger(__name__)

DAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]
MONTHS = ["ledna", "února", "března", "dubna", "května", "června", "července", "srpna", "září", "října", "listopadu", "prosince"]
NEWS_RSS = "https://news.google.com/rss?hl=cs&gl=CZ&ceid=CZ:cs"


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()


def address(rt) -> str:
    return rt.cfg.general.address_as or "pane"


def hello(now: dt.datetime) -> str:
    h = now.hour
    return "Dobrou noc" if h < 5 else "Dobré ráno" if h < 10 else "Dobrý den" if h < 18 else "Dobrý večer"


# ---------------------------------------------------------------------------------------------- protocols
def find_protocol(rt, name: str):
    """By id or name, ignoring case and diacritics; "párty" finds "Párty", "noc" finds "Dobrou noc"."""
    want = _fold(re.sub(r"(?i)^\s*protokol\s+", "", name or ""))
    if not want:
        return None
    items = rt.cfg.stark.protocols
    for p in items:
        if want in (_fold(p.id), _fold(p.name)):
            return p
    return next((p for p in items if want in _fold(p.name) or _fold(p.name) in want), None)


async def run_protocol(rt, proto, kind: str = "Protokol", extra_system: str = "") -> str:
    """Runs the steps in order. Plain steps go in one go (no AI); an "ask" step is a normal request to the AI."""
    title = f"▶ {kind} {proto.name}"
    out: list[str] = []
    chunk: list = []
    for st in proto.steps:
        if st.ask:
            if chunk:
                out.append(await rt.agent.run_steps(title, chunk))
                chunk, title = [], f"▶ {kind} {proto.name} (pokračuje)"
            out.append(await rt.agent.handle(st.ask, [], "protocol", extra_system=(
                extra_system or f"Tohle je krok protokolu „{proto.name}“, který si uživatel spustil. Rovnou ho proveď, bez ptaní.")))
        else:
            chunk.append(st)
    if chunk or not out:
        out.append(await rt.agent.run_steps(title, chunk))
    return "\n".join(o for o in out if o)


def start_protocol(rt, proto) -> None:
    """From a button, the HUD or a voice tool: runs after whatever JARVIS is doing now (it waits for the agent)."""
    rt.bus.publish("protocol", id=proto.id, name=proto.name, icon=proto.icon)
    asyncio.get_running_loop().create_task(run_protocol(rt, proto))


# ---------------------------------------------------------------------------------------------- briefing
async def headlines(rt, n: int = 3) -> list[str]:
    try:
        async with rt.http() as c:
            r = await c.get(NEWS_RSS, timeout=6)
        root = ElementTree.fromstring(r.content)
        titles = [(i.findtext("title") or "").strip() for i in root.iter("item")]
        # "Titulek - Zdroj" → just the headline
        return [re.sub(r"\s+[-–]\s+[^-–]+$", "", t) for t in titles if t][:n]
    except Exception as e:
        log.debug("headlines: %s", e)
        return []


def _today_jobs(rt, now: dt.datetime) -> list[dict]:
    if not getattr(rt, "scheduler", None):
        return []
    end = now.replace(hour=23, minute=59, second=59)
    return [j for j in rt.scheduler.list() if j["enabled"] and now.timestamp() <= j["next_run"] <= end.timestamp()]


async def briefing(rt, now: dt.datetime | None = None, news: bool | None = None) -> dict:
    """The morning briefing: greeting, date, weather, today's plans, the PC and the news. Each part may be missing."""
    from .tools.system import system_snapshot
    from .tools.weather import fetch_weather

    now = now or dt.datetime.now()
    a = address(rt)
    parts: list[str] = [f"{hello(now)}, {a}. Je {DAYS[now.weekday()]} {now.day}. {MONTHS[now.month - 1]}, {now:%H:%M}."]
    data: dict[str, Any] = {"date": now.isoformat(timespec="minutes")}

    try:
        w = await asyncio.wait_for(fetch_weather(rt, rt.cfg.general.city), 9)
        d0 = (w.get("days") or [{}])[0]
        line = f"V {w['city']} je {round(w['temp'])} °C a {w['desc']}"
        if d0:
            line += f", přes den až {round(d0['max'])} °C"
            if (d0.get("rain_pct") or 0) >= 40:
                line += f" a {d0['rain_pct']} % šance na déšť – vezměte si deštník"
        parts.append(line + ".")
        data["weather"] = w
    except Exception as e:
        log.debug("briefing weather: %s", e)

    cal = getattr(rt, "calendar", None)
    if cal is not None:
        try:
            from .calendar_ import fmt_event

            evs = await asyncio.wait_for(cal.day(now.date()), 8)
            evs = [e for e in evs if e["end"] >= now.timestamp()]
            if evs:
                parts.append("V kalendáři: " + "; ".join(fmt_event(e) for e in evs[:5]) + ".")
            data["calendar"] = evs
        except Exception as e:
            log.debug("briefing calendar: %s", e)
    mail = getattr(rt, "mail", None)
    if mail is not None and rt.cfg.mail.accounts:
        try:
            unread = await asyncio.wait_for(asyncio.to_thread(mail.account().list, True, 30), 10)
            real = [m for m in unread if not m["newsletter"]]
            if real:
                who = ", ".join(dict.fromkeys(m["from_name"] for m in real[:3]))
                parts.append(f"Máte {len(real)} nepřečtených e-mailů, mimo jiné od: {who}.")
            data["mail_unread"] = len(real)
        except Exception as e:
            log.debug("briefing mail: %s", e)

    jobs = _today_jobs(rt, now)
    timers = rt.timers.list()
    if jobs or timers:
        items = [f"{dt.datetime.fromtimestamp(j['next_run']):%H:%M} {j['title']}" for j in jobs[:4]]
        items += [t.get("label", "časovač") for t in timers[:2]]
        parts.append(("Dnes máte v plánu: " if jobs else "Běží: ") + ", ".join(items) + ".")
    else:
        parts.append("Na dnešek nemáte nic naplánováno.")
    data["jobs"], data["timers"] = jobs, timers

    try:
        s = await asyncio.to_thread(system_snapshot)
        sys_line = "Všechny systémy v normě"
        notes = []
        if s.get("battery_percent") is not None and s["battery_percent"] < 40 and not s.get("charging"):
            notes.append(f"baterie je na {s['battery_percent']} %")
        if s.get("disk_free_gb") is not None and s["disk_free_gb"] < max(10, rt.cfg.stark.disk_low_gb):
            notes.append(f"na disku zbývá jen {s['disk_free_gb']} GB")
        if notes:
            sys_line = "Upozornění: " + " a ".join(notes)
        parts.append(sys_line + ".")
        data["system"] = s
    except Exception as e:
        log.debug("briefing system: %s", e)

    if news if news is not None else rt.cfg.stark.briefing_news:
        hl = await headlines(rt)
        if hl:
            parts.append("Ze zpráv: " + "; ".join(hl) + ".")
            data["news"] = hl
    text = " ".join(parts)
    data["text"] = text
    return data


def briefing_due(rt, now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now()
    if not rt.cfg.stark.briefing_auto or not 5 <= now.hour < 12:
        return False
    row = rt.db.one("SELECT v FROM kv WHERE k='briefing_day'")
    return not (row and row["v"] == now.date().isoformat())


def briefing_done(rt, now: dt.datetime | None = None) -> None:
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('briefing_day', ?)", ((now or dt.datetime.now()).date().isoformat(),))


async def deliver_briefing(rt, spoken_intro: str = "") -> dict:
    briefing_done(rt)
    b = await briefing(rt)
    text = (spoken_intro + " " + b["text"]).strip()
    rt.bus.publish("briefing", **b)
    rt.notify("Ranní brífink", text, speak=rt.cfg.stark.briefing_speak and rt.cfg.voice.speak_mode != "never")
    return b


async def boot(rt) -> None:
    """The PC app has started: "JARVIS online", or the whole morning briefing when it is due."""
    rt.bus.publish("boot")
    if briefing_due(rt) and _user_present(rt):
        await deliver_briefing(rt, "JARVIS online.")
    elif rt.cfg.stark.boot_greeting and rt.cfg.voice.speak_mode != "never":
        rt.speak(f"JARVIS online. Všechny systémy připraveny, {address(rt)}.")


def _user_present(rt) -> bool:
    try:
        return rt.platform.idle_seconds() < 120
    except Exception:
        return True


# ---------------------------------------------------------------------------------------------- guardian
@dataclass
class GuardState:
    cpu: list[float] = field(default_factory=list)
    ram: list[float] = field(default_factory=list)
    last: dict[str, float] = field(default_factory=dict)    # alert key → when it was said
    battery_said: int = 101                                  # the lowest battery level already announced
    offline_since: float = 0.0
    offline_said: bool = False
    disk_day: str = ""


COOLDOWN = {"cpu": 1800, "ram": 1800}


def evaluate(st: GuardState, snap: dict, now: float, cfg, offline: bool = False, today: str = "") -> list[tuple[str, str, str]]:
    """New alerts for this snapshot: (key, title, text). Pure, so it can be tested without a PC."""
    out: list[tuple[str, str, str]] = []
    st.cpu = (st.cpu + [snap.get("cpu_percent", 0)])[-6:]
    st.ram = (st.ram + [snap.get("ram_percent", 0)])[-3:]

    bat, charging = snap.get("battery_percent"), snap.get("charging")
    if bat is not None:
        if charging:
            st.battery_said = 101
        else:
            for level in (cfg.battery_low, 10, 5):
                if bat <= level < st.battery_said:
                    st.battery_said = level
                    out.append(("battery", "Baterie", f"Baterie je na {bat} %. Doporučuji připojit nabíječku."
                                if level > 5 else f"Baterie je kriticky nízko, {bat} %. Uložte si práci."))
                    break

    def cooled(key: str) -> bool:
        return now - st.last.get(key, -1e9) >= COOLDOWN.get(key, 0)

    if len(st.cpu) == 6 and min(st.cpu) >= 90 and cooled("cpu"):
        st.last["cpu"] = now
        top = snap.get("top_cpu") or ""
        out.append(("cpu", "Procesor", f"Procesor je už dvě minuty vytížený na {round(sum(st.cpu) / 6)} %"
                    + (f", nejvíc ho bere {top}." if top else ".")))
    if len(st.ram) == 3 and min(st.ram) >= 92 and cooled("ram"):
        st.last["ram"] = now
        out.append(("ram", "Paměť", f"Operační paměť je zaplněná na {round(st.ram[-1])} %. Možná zavřete pár aplikací."))

    free = snap.get("disk_free_gb")
    if free is not None and free < cfg.disk_low_gb and st.disk_day != today:
        st.disk_day = today
        out.append(("disk", "Disk", f"Na systémovém disku zbývá jen {free} GB místa."))

    if offline:
        if not st.offline_since:
            st.offline_since = now
        elif now - st.offline_since >= 30 and not st.offline_said:
            st.offline_said = True
            out.append(("offline", "Internet", "Ztratil jsem spojení s internetem. Pracuji dál offline, co to půjde."))
    else:
        if st.offline_said:
            out.append(("online", "Internet", "Spojení s internetem je zpět."))
        st.offline_since, st.offline_said = 0.0, False
    return out


class Guardian:
    def __init__(self, rt):
        self.rt = rt
        self.state = GuardState()
        self._task: asyncio.Task | None = None
        self.last_snap: dict = {}

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def check(self) -> list[tuple[str, str, str]]:
        from .tools.system import system_snapshot

        rt = self.rt
        snap = await asyncio.to_thread(system_snapshot)
        self.last_snap = snap
        if (snap.get("cpu_percent") or 0) >= 90:
            snap["top_cpu"] = await asyncio.to_thread(_top_cpu_name)
        alerts = evaluate(self.state, snap, time.monotonic(), rt.cfg.stark, getattr(rt.mood, "offline", False),
                          dt.date.today().isoformat())
        for key, title, text in alerts:
            rt.bus.publish("guardian", key=key, title=title, text=text)
            rt.notify(title, f"{text}", speak=rt.cfg.stark.guardian_speak and rt.cfg.voice.speak_mode != "never")
        return alerts

    async def check_network(self) -> list[dict]:
        """3.5: a device the PC has never seen joined the network → say who (its name, if it announces one)."""
        from . import network

        items = await network.devices(self.rt)
        fresh = [d for d in items if d["new"]]
        network.remember(self.rt, network.known(self.rt) | {d["mac"] for d in items})
        for d in fresh[:3]:
            text = f"Do sítě se připojilo nové zařízení{' ' + d['name'] if d['name'] else ''} ({d['ip']})."
            self.rt.bus.publish("guardian", key="network", title="Síť", text=text)
            self.rt.notify("Síť", text, speak=self.rt.cfg.stark.guardian_speak and self.rt.cfg.voice.speak_mode != "never")
        return fresh

    async def record_perf(self) -> dict:
        """OMEGA 312: one row of the performance history (reuses the guardian's last snapshot when fresh)."""
        from .tools.system import system_snapshot

        snap = self.last_snap or await asyncio.to_thread(system_snapshot)
        self.last_snap = {}
        g = (snap.get("gpu") or {}).get("util") if isinstance(snap.get("gpu"), dict) else None
        return self.rt.perf.record(snap.get("cpu_percent"), snap.get("ram_percent"), g)

    async def check_hardware(self) -> tuple[list[str], list[str]]:
        """OMEGA 290: a device was plugged in or removed since the last look → say which."""
        from . import rescue
        from .tools.rescue_tools import hw_diff

        r = await asyncio.to_thread(rescue.run_probe, "devices")
        if not r["ok"]:
            return [], []
        added, removed, _now = hw_diff(self.rt, rescue.device_snapshot(r["data"]))
        if not added and not removed:
            return [], []
        parts = ([f"Připojeno: {', '.join(a.split(': ', 1)[-1] for a in added[:3])}"] if added else []) + \
                ([f"Odpojeno: {', '.join(x.split(': ', 1)[-1] for x in removed[:3])}"] if removed else [])
        text = ". ".join(parts) + "."
        self.rt.bus.publish("guardian", key="hardware", title="Zařízení", text=text)
        self.rt.notify("Zařízení", text, speak=False)     # the character shows the notification badge
        return added, removed

    async def care(self, layout_due: bool, crashes_due: bool) -> None:
        """OMEGA 31 / 32: keep the window layout (offer it back once after a restart); a program that keeps crashing."""
        from . import pccare, rescue

        rt = self.rt
        if layout_due and rt.cfg.stark.layout_memory:
            offer = await asyncio.to_thread(pccare.restore_offer, rt)
            if offer:
                rt.notify("Okna z minula", f"Před restartem jsi měl otevřené {', '.join(offer['apps'][:5])}. Mám je otevřít a rozmístit? "
                                           f"Řekni „obnov okna z minula“.", speak=False)
            await asyncio.to_thread(pccare.autosave_layout, rt)
        if crashes_due and rt.cfg.stark.crash_help:
            r = await asyncio.to_thread(rescue.run_probe, "crashes")
            if r["ok"]:
                pccare.offer_crash_help(rt, rescue.L(r["data"].get("app_errors")))

    async def _loop(self) -> None:
        await asyncio.sleep(60)          # let the PC settle after start-up
        net_at = perf_at = hw_at = layout_at = crash_at = 0.0
        while True:
            try:
                if self.rt.cfg.stark.guardian:
                    await self.check()
                if self.rt.cfg.stark.network_watch and time.monotonic() - net_at > 600:
                    net_at = time.monotonic()
                    await self.check_network()
                if self.rt.cfg.stark.perf_history and time.monotonic() - perf_at > 300:
                    perf_at = time.monotonic()
                    await self.record_perf()
                if self.rt.cfg.stark.hardware_watch and sys.platform == "win32" and time.monotonic() - hw_at > 300:
                    hw_at = time.monotonic()
                    await self.check_hardware()
                if sys.platform == "win32":
                    layout_due, crash_due = time.monotonic() - layout_at > 600, time.monotonic() - crash_at > 1800
                    layout_at = time.monotonic() if layout_due else layout_at
                    crash_at = time.monotonic() if crash_due else crash_at
                    if layout_due or crash_due:
                        await self.care(layout_due, crash_due)
                if briefing_due(self.rt) and _user_present(self.rt) and self.rt.clients:
                    await deliver_briefing(self.rt)
            except Exception as e:
                log.debug("guardian: %s", e)
            await asyncio.sleep(20)


def _top_cpu_name() -> str:
    import psutil

    procs = list(psutil.process_iter(["name"]))
    for p in procs:
        try:
            p.cpu_percent(None)     # the first reading only starts the measurement
        except (psutil.Error, OSError):
            pass
    time.sleep(0.5)
    best = (0.0, "")
    for p in procs:
        try:
            name = p.info.get("name") or ""
            if name.lower() in ("system idle process", "idle", ""):
                continue
            best = max(best, (p.cpu_percent(None), name))
        except (psutil.Error, OSError):
            pass
    return best[1]
