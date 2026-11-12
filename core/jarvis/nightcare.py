"""3.12 Noční údržba PC: once a night (2–6 h, nobody at the PC, nothing running, not on battery) JARVIS
- deletes temporary files older than a week (only %TEMP% – never documents, photos, downloads or the recycle bin),
- removes its own old update installers,
- checks the disks' health and which Windows updates wait (it installs nothing – that stays with Windows Update).
The result goes into the morning summary and Settings → Obecné; a failing disk is said at once.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import sys
import time
from typing import Any

from . import paths

log = logging.getLogger("jarvis.nightcare")
NIGHT = range(2, 6)
IDLE_S = 20 * 60
TEMP_AGE_S = 7 * 86400

DISK_PS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Get-PhysicalDisk | Select-Object FriendlyName, HealthStatus, OperationalStatus | ConvertTo-Json -Compress
"""


def disk_health() -> list[dict]:
    """Windows' own verdict on each physical disk (Healthy / Warning / Unhealthy) – no admin rights needed."""
    if sys.platform != "win32":
        return []
    from .pcreport import run_quiet

    try:
        _, out, _ = run_quiet(["powershell", "-NoProfile", "-Command", DISK_PS], 30)
        return parse_disks(out)
    except Exception:  # noqa: BLE001
        return []


def parse_disks(out: str) -> list[dict]:
    try:
        s = out.strip()
        d = json.loads(s[s.find("["):] if s.startswith("[") else s[s.find("{"):])
    except Exception:  # noqa: BLE001
        return []
    items = d if isinstance(d, list) else [d]
    return [{"name": str(i.get("FriendlyName") or "Disk"), "health": str(i.get("HealthStatus") or "")} for i in items]


def old_installers(keep: str = "") -> tuple[int, int]:
    """JARVIS's own downloaded update installers older than a week."""
    n = freed = 0
    cutoff = time.time() - TEMP_AGE_S
    for f in paths.sub("updates").glob("JARVIS-Setup-*.exe"):
        try:
            if keep and keep in f.name:
                continue
            st = f.stat()
            if st.st_mtime < cutoff:
                f.unlink()
                n, freed = n + 1, freed + st.st_size
        except OSError:
            continue
    return n, freed


class NightCare:
    def __init__(self, rt: Any):
        self.rt = rt
        self._file = paths.data_dir() / "nightcare.json"
        try:
            self.last: dict = json.loads(self._file.read_text("utf-8"))
        except (OSError, ValueError):
            self.last = {}
        self.running = False

    def quiet(self, now: float | None = None) -> bool:
        rt = self.rt
        if time.localtime(now if now is not None else time.time()).tm_hour not in NIGHT:
            return False
        try:
            if float(rt.platform.idle_seconds()) < IDLE_S:
                return False
        except Exception:  # noqa: BLE001
            return False
        if getattr(rt.agent, "busy", False) or getattr(getattr(rt, "remote_desk", None), "on", False):
            return False
        if getattr(getattr(rt, "phone_mirror", None), "active", False):
            return False
        try:
            import psutil

            bat = psutil.sensors_battery()
            if bat is not None and not bat.power_plugged:
                return False
        except Exception:  # noqa: BLE001
            pass
        return True

    def due(self, now: float | None = None) -> bool:
        if not getattr(self.rt.cfg.general, "night_care", True) or self.running:
            return False
        today = dt.date.fromtimestamp(now if now is not None else time.time()).isoformat()
        return self.last.get("day") != today and self.quiet(now)

    async def run(self) -> dict:
        from . import winupd
        from .powers import clean_temp, temp_dirs

        self.running = True
        try:
            files, freed = await asyncio.to_thread(clean_temp, temp_dirs(), TEMP_AGE_S)
            n2, f2 = await asyncio.to_thread(old_installers)
            disks = await asyncio.to_thread(disk_health)
            try:
                upd = await asyncio.to_thread(winupd.pending)
            except Exception as e:  # noqa: BLE001
                upd = {"updates": [], "error": str(e)[:120]}
            bad = [d for d in disks if d["health"] and d["health"].lower() not in ("healthy", "0")]
            self.last = {"day": dt.date.today().isoformat(), "at": time.time(), "files": files + n2, "freed": freed + f2,
                         "disks": disks, "disks_bad": [d["name"] for d in bad], "updates": len(upd.get("updates") or []),
                         "reboot": bool(upd.get("reboot")), "updates_error": upd.get("error") or ""}
            self._save()
            if bad:
                self.rt.notify("Disk hlásí problém", f"Windows hlásí u disku {', '.join(d['name'] for d in bad)} stav "
                               f"{bad[0]['health']}. Zálohuj si důležité soubory.", speak=False)
            return self.last
        finally:
            self.running = False

    def summary(self) -> str:
        """One sentence for the morning summary (empty when it did not run last night)."""
        L = self.last
        if not L or time.time() - float(L.get("at", 0)) > 18 * 3600:
            return ""
        from .powers import fmt_bytes

        parts = [f"Noční údržba uvolnila {fmt_bytes(L.get('freed', 0))}"]
        if L.get("disks_bad"):
            parts.append(f"disk {', '.join(L['disks_bad'])} hlásí problém")
        if L.get("updates"):
            parts.append(f"Windows má {L['updates']} aktualizací k instalaci" + (" a chce restart" if L.get("reboot") else ""))
        return ", ".join(parts) + "."

    def status(self) -> dict:
        return {"on": bool(getattr(self.rt.cfg.general, "night_care", True)), "running": self.running, "last": self.last,
                "summary": self.summary()}

    def _save(self) -> None:
        try:
            self._file.write_text(json.dumps(self.last), "utf-8")
        except OSError as e:
            log.debug("nightcare save: %s", e)

    async def loop(self) -> None:
        while True:
            await asyncio.sleep(10 * 60)
            try:
                upd = getattr(self.rt, "updater", None)
                if upd is not None and upd.night_ready():
                    continue                       # the night update goes first (it restarts JARVIS)
                if self.due():
                    await self.run()
            except Exception as e:  # noqa: BLE001
                log.debug("nightcare: %s", e)
