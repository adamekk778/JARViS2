"""Checks GitHub Releases for a newer JARVIS-Setup.exe; installs only when the user asks (spec §3)."""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from . import __version__, paths

log = logging.getLogger(__name__)
ASSET = "JARVIS-Setup.exe"


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
                       "notes": ""}
        self._url: str | None = None
        self._task: asyncio.Task | None = None
        self._notified: str | None = None

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._loop())

    async def _loop(self) -> None:
        await asyncio.sleep(30)
        while True:
            await self.check()
            await asyncio.sleep(24 * 3600)

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
                self.rt.notify("Nová verze JARVISe", f"Je k dispozici verze {version}. Aktualizuješ v panelu → Systém.",
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
        self.status.update(state="downloading", progress=0.0)
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
        self.status.update(state="ready", progress=1.0)
        self._publish()
        return dest

    def install(self, path: Path) -> None:
        if sys.platform != "win32":
            raise RuntimeError("instalace aktualizace funguje jen na Windows")
        subprocess.Popen([str(path), "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS"], close_fds=True)
        self.rt.loop.call_later(1.5, lambda: os._exit(0))

    async def download_and_install(self) -> None:
        """Called only from an explicit user action (panel button / confirmed voice request)."""
        try:
            path = await self.download()
            self.install(path)
        except Exception as e:
            self.status.update(state="error", progress=None)
            self._publish()
            self.rt.bus.publish("error", message=f"Aktualizace selhala: {e}")
