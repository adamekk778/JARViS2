"""Checks GitHub Releases for a newer JARVIS-Setup.exe; installs when the user asks (spec §3) – or, if the user
switched on "Aktualizovat sám v noci" (Settings → Obecné), by itself at night while nobody uses the PC."""
from __future__ import annotations

import asyncio
import logging
import os
import json
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, paths

log = logging.getLogger(__name__)
ASSET = "JARVIS-Setup.exe"
NIGHT = range(2, 6)            # 2:00–5:59
IDLE_S = 20 * 60               # nobody touched the PC for 20 minutes


def parse(v: str) -> tuple[int, ...]:
    v = v.strip().lstrip("vV")
    out = []
    for part in v.split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def newer(a: str, b: str) -> bool:
    """True when version a is newer than b."""
    pa, pb = parse(a), parse(b)
    n = max(len(pa), len(pb))
    return pa + (0,) * (n - len(pa)) > pb + (0,) * (n - len(pb))


class Updater:
    def __init__(self, rt, transport=None, current: str = __version__):
        self.rt = rt
        self.transport = transport
        self.status = {"current": current, "latest": None, "available": False, "state": "idle", "progress": None,
                       "notes": "", "error": ""}
        self._url: str | None = None
        self._task: asyncio.Task | None = None
        self._notified: str | None = None
        self.min_size = 5_000_000  # a real JARVIS-Setup.exe is far bigger

    def start(self) -> None:
        self._after_update()
        self._task = asyncio.get_running_loop().create_task(self._loop())

    async def _loop(self) -> None:
        await asyncio.sleep(30)
        last = 0.0
        while True:
            if time.time() - last >= 3 * 3600:     # 3.12 a new version shows up in the notch the same day
                last = time.time()
                await self.check()
            try:
                if self.night_ready():
                    await self.download_and_install(silent=True)
            except Exception as e:  # noqa: BLE001 – the nightly try must never stop the checks
                log.info("night update: %s", e)
            await asyncio.sleep(10 * 60)

    # ---------- 3.12 Aktualizace sama v noci ----------
    def _marker(self) -> Path:
        return paths.data_dir() / "update_pending.json"

    def night_ready(self, now: float | None = None) -> bool:
        """A new version, switched on, and a quiet night (see _quiet)."""
        if not getattr(self.rt.cfg.general, "auto_update", False) or self.status["state"] != "available" or not self._url:
            return False
        if self.status["latest"] == self._skip():
            return False                                   # this version already failed once at night: wait for the button
        return self._quiet(now)

    def _quiet(self, now: float | None = None) -> bool:
        """At night, nobody at the PC, nothing running that an update would cut off, not on battery."""
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
        notes = getattr(rt, "notetaker", None)
        if notes is not None and getattr(notes, "state", "idle") != "idle":    # a meeting being recorded / processed
            return False
        try:
            import psutil

            bat = psutil.sensors_battery()
            if bat is not None and not bat.power_plugged:
                return False
        except Exception:  # noqa: BLE001
            pass
        return True

    def _skip(self) -> str:
        try:
            return (paths.data_dir() / "update_skip.txt").read_text("utf-8").strip()
        except OSError:
            return ""

    def _after_update(self) -> None:
        """The first start after a night update: say what happened (or that it did not work)."""
        try:
            m = json.loads(self._marker().read_text("utf-8"))
        except (OSError, ValueError):
            return
        self._marker().unlink(missing_ok=True)
        to = str(m.get("to", ""))
        if not to:
            return
        if not newer(to, self.status["current"]):
            self.rt.notify("JARVIS je aktualizovaný", f"V noci se nainstalovala verze {to}. Co je nového najdeš v notchi.",
                           speak=False)
        else:
            try:
                (paths.data_dir() / "update_skip.txt").write_text(to, "utf-8")
            except OSError:
                pass
            self.rt.notify("Noční aktualizace se nepovedla",
                           f"Verze {to} se v noci nenainstalovala. Klikni v notchi na Aktualizovat, až budeš u PC.", speak=False)

    def _publish(self) -> None:
        self.rt.bus.publish("update_status", **self.status)

    async def check(self, force: bool = False) -> dict | None:
        import httpx

        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=15, follow_redirects=True) as c:
                r = await c.get(self.rt.cfg.general.update_url, headers={"Accept": "application/vnd.github+json"})
            if r.status_code != 200:
                log.info("update check: HTTP %s", r.status_code)
                return None
            data = r.json()
            version = (data.get("tag_name") or "").lstrip("vV")
            url = next((a.get("browser_download_url") for a in data.get("assets", []) if a.get("name") == ASSET), None)
        except Exception as e:  # offline, private repo, rate limit…
            log.info("update check failed: %s", e)
            return None
        if not version or not url:
            return None
        self.status.update(latest=version, notes=(data.get("body") or "")[:2000])
        if newer(version, self.status["current"]):
            self._url = url
            self.status.update(available=True, state="available")
            self._publish()
            if self._notified != version:
                self._notified = version
                self.rt.notify("Nová verze JARVISe", f"Je k dispozici verze {version}. Klikni v notchi na Aktualizovat – nainstaluje se a JARVIS se sám znovu spustí.",
                               speak=False)
            return {"version": version, "url": url}
        if force:
            self._publish()
        return None

    async def download(self) -> Path:
        import httpx

        if not self._url:
            raise RuntimeError("žádná aktualizace")
        dest = paths.sub("updates") / f"JARVIS-Setup-{self.status['latest']}.exe"
        self.status.update(state="downloading", progress=0.0, error="")
        self._publish()
        async with httpx.AsyncClient(transport=self.transport, timeout=None, follow_redirects=True) as c:
            async with c.stream("GET", self._url) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or 0)
                got = 0
                last = 0.0
                with open(dest, "wb") as f:
                    async for chunk in r.aiter_bytes(1 << 16):
                        f.write(chunk)
                        got += len(chunk)
                        p = got / total if total else 0.0
                        if p - last >= 0.02:
                            last = p
                            self.status["progress"] = round(p, 3)
                            self._publish()
        if total and got != total:
            dest.unlink(missing_ok=True)
            raise RuntimeError("stažení se nedokončilo")
        with open(dest, "rb") as f:
            magic = f.read(2)
        if dest.stat().st_size < self.min_size or magic != b"MZ":
            dest.unlink(missing_ok=True)
            raise RuntimeError("stažený soubor není instalátor JARVISe")
        self.status.update(state="ready", progress=1.0)
        self._publish()
        return dest

    def install(self, path: Path, silent: bool = False) -> None:
        if sys.platform != "win32":
            raise RuntimeError("instalace aktualizace funguje jen na Windows")
        try:                                    # the next start tells whether it worked
            self._marker().write_text(json.dumps({"from": self.status["current"], "to": self.status["latest"],
                                                  "night": silent, "at": time.time()}), "utf-8")
        except OSError:
            pass
        args = ["/VERYSILENT", "/SUPPRESSMSGBOXES"] if silent else ["/SILENT"]
        subprocess.Popen([str(path), *args, "/NORESTART", "/CLOSEAPPLICATIONS"], close_fds=True)
        self.rt.loop.call_later(1.5, lambda: os._exit(0))

    async def download_and_install(self, silent: bool = False) -> None:
        """An explicit user action (panel button / confirmed voice request) – or the night update the user switched on."""
        if self.status["state"] in ("downloading", "ready"):
            return  # already in progress
        try:
            path = await self.download()
            if silent and not self._quiet():
                self.status.update(state="available", progress=None)   # someone sat down at the PC meanwhile: next night
                self._publish()
                return
            self.install(path, silent)
        except Exception as e:
            log.warning("update failed: %s", e)
            self.status.update(state="error", progress=None, error=str(e)[:300] or e.__class__.__name__)
            self._publish()
            self.rt.bus.publish("error", message=f"Aktualizace selhala: {e}")
