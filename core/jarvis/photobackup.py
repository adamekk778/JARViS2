"""3.12 Záloha fotek z telefonu: the paired phone sends its new photos and videos to this PC by itself.

They land in Obrázky\\JARVIS Telefon\\YYYY-MM (by the date the photo was taken), or a folder you choose in Settings.
Only the paired phone (its token) can upload, never a guest. A file that is already there (same name and size) is
skipped, so a backup can be repeated or interrupted at any time. Nothing ever leaves the PC: this only receives.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, AsyncIterator

from .paths import data_dir

log = logging.getLogger("jarvis.photobackup")

MAX_FILE = 8 * 2**30                     # a single long 4K video at most
KEEP_FREE = 1 * 2**30                    # never fill the disk: keep 1 GB free
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".dng", ".avif", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".3gp", ".mkv", ".webm", ".avi", ".m4v"}
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class BackupError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def default_folder() -> Path:
    """Obrázky\\JARVIS Telefon (Windows shows the Pictures folder as "Obrázky")."""
    return Path.home() / "Pictures" / "JARVIS Telefon"


def safe_name(name: str) -> str:
    """Only the file's own name, without anything Windows would refuse or treat as a path."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _BAD.sub("_", name).strip().rstrip(". ")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if not stem or stem.lower() in _RESERVED:
        stem = f"foto_{stem}" if stem else "foto"
    stem = stem[:150]
    return f"{stem}.{ext.lower()}" if ext else stem


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in PHOTO_EXT:
        return "photo"
    if ext in VIDEO_EXT:
        return "video"
    return ""


class PhotoBackup:
    def __init__(self, rt: Any):
        self.rt = rt
        self._file = data_dir() / "photo_backup.json"
        self.stats: dict[str, Any] = {"count": 0, "bytes": 0, "last": 0.0, "last_name": "", "session": 0}
        try:
            self.stats.update(json.loads(self._file.read_text("utf-8")))
        except (OSError, ValueError):
            pass

    # ---------- where ----------
    def folder(self) -> Path:
        chosen = (self.rt.cfg.phone_link.photo_folder or "").strip().strip('"')
        if chosen:
            p = Path(os.path.expandvars(os.path.expanduser(chosen)))
            if p.is_absolute():
                return p
        return default_folder()

    def _month(self, taken_ms: int) -> str:
        t = taken_ms / 1000 if taken_ms > 0 else time.time()
        if t > time.time() + 86400 * 2 or t < 315532800:   # nonsense dates (1970, the future) → today's month
            t = time.time()
        return time.strftime("%Y-%m", time.localtime(t))

    def target(self, name: str, taken_ms: int) -> Path:
        return self.folder() / self._month(taken_ms) / safe_name(name)

    def has(self, name: str, size: int, taken_ms: int) -> bool:
        """Already backed up: the same name with the same size (also "name (2).jpg" made after a name clash)."""
        p = self.target(name, taken_ms)
        try:
            if p.is_file() and p.stat().st_size == size:
                return True
            for i in range(2, 6):
                q = p.with_name(f"{p.stem} ({i}){p.suffix}")
                if not q.exists():
                    break
                if q.stat().st_size == size:
                    return True
        except OSError:
            return False
        return False

    def have(self, items: list[dict]) -> list[bool]:
        out = []
        for it in items[:500]:
            try:
                out.append(self.has(str(it.get("name", "")), int(it.get("size", -1)), int(it.get("taken", 0) or 0)))
            except (TypeError, ValueError):
                out.append(False)
        return out

    # ---------- receive ----------
    async def receive(self, chunks: AsyncIterator[bytes], name: str, size: int, taken_ms: int = 0) -> dict:
        """Stream one file to disk. It appears under its real name only when complete (an interrupted upload leaves nothing)."""
        if not kind_of(safe_name(name)):
            raise BackupError(415, "Tohle není fotka ani video")
        if size < 0:
            raise BackupError(411, "Chybí velikost souboru")
        if size > MAX_FILE:
            raise BackupError(413, "Soubor je moc velký")
        if self.has(name, size, taken_ms):
            return {"ok": True, "skipped": True}
        dest = self.target(name, taken_ms)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise BackupError(507, f"Do složky pro fotky nejde zapisovat ({e.strerror or e})") from e
        try:
            free = shutil.disk_usage(dest.parent).free
        except OSError:
            free = size + KEEP_FREE
        if free < size + KEEP_FREE:
            raise BackupError(507, "Na PC dochází místo na disku")
        part = dest.with_name(f".{dest.name}.{secrets.token_hex(4)}.part")
        got = 0
        try:
            with open(part, "wb") as f:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    got += len(chunk)
                    if got > size:
                        raise BackupError(400, "Soubor je delší, než telefon ohlásil")
                    f.write(chunk)
            if got != size:
                raise BackupError(400, "Přenos se přerušil")
            final = dest
            i = 2
            while final.exists():                      # a different file with the same name: keep both
                final = dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
                i += 1
            os.replace(part, final)
        except BaseException:
            try:
                part.unlink()
            except OSError:
                pass
            raise
        if taken_ms > 0:
            try:
                os.utime(final, (taken_ms / 1000, taken_ms / 1000))
            except (OSError, OverflowError, ValueError):
                pass
        self.stats["count"] = int(self.stats.get("count", 0)) + 1
        self.stats["bytes"] = int(self.stats.get("bytes", 0)) + size
        self.stats["session"] = int(self.stats.get("session", 0)) + 1
        self.stats["last"] = time.time()
        self.stats["last_name"] = final.name
        self._save()
        return {"ok": True, "saved": final.name}

    def done(self, sent: int) -> dict:
        """The phone finished a round: one quiet notification for the whole batch, not one per photo."""
        n = int(self.stats.get("session", 0))
        self.stats["session"] = 0
        self._save()
        if n > 0:
            word = "soubor" if n == 1 else "soubory" if 2 <= n <= 4 else "souborů"
            self.rt.notify("Záloha fotek z telefonu", f"Uloženo {n} {word} do {self.folder()}", speak=False)
        return self.status()

    def status(self) -> dict:
        return {"folder": str(self.folder()), "count": int(self.stats.get("count", 0)), "bytes": int(self.stats.get("bytes", 0)),
                "last": float(self.stats.get("last", 0) or 0), "last_name": str(self.stats.get("last_name", ""))}

    def open_folder(self) -> bool:
        p = self.folder()
        try:
            p.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(p))  # type: ignore[attr-defined]  # noqa: S606 – our own folder in Explorer
                return True
        except OSError as e:
            log.debug("open folder: %s", e)
        return False

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self.stats), "utf-8")
        except OSError as e:
            log.debug("photo backup stats: %s", e)
