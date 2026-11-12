"""OMEGA wave 45 (original list): automatic backups (P10.04), finished downloads and installs (P10.03), screenshots and
clips (P12.08), Bluetooth devices (P13.04), mood from the tone of voice (P3.12), sharing the screen to the phone (P9.08),
several PCs (P9.09), music in the notch (P12.02) and a personal knowledge graph (P15.07)."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import io
import json
import logging
import math
import os
import re
import time
from pathlib import Path


import numpy as np

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- P10.03 downloads and installs
PARTIAL = (".crdownload", ".part", ".partial", ".download", ".opdownload", ".tmp")


def _snapshot(folder: Path) -> dict[str, int]:
    """Names and sizes in a folder. os.scandir: on Windows the sizes come with the listing itself (no extra call per
    file), which matters for a Downloads folder with thousands of files looked at every few seconds."""
    out = {}
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if e.is_file():
                        out[e.name] = e.stat().st_size
                except OSError:
                    continue
    except OSError:
        pass
    return out


def installer_procs() -> list[dict]:
    """[{pid, name, cmdline}] for installer-looking processes only. Reading every process's command line every few
    seconds was the costly part on Windows; only msiexec needs it (to tell an install from the idle service)."""
    import psutil

    out = []
    for p in psutil.process_iter(["pid", "name"]):
        name = p.info.get("name") or ""
        if INSTALLER.search(name) or name.lower() == "msiexec.exe":
            try:
                cmd = p.cmdline() if name.lower() == "msiexec.exe" else []
            except (psutil.Error, OSError):
                cmd = []
            out.append({"pid": p.info["pid"], "name": name, "cmdline": cmd})
    return out


class DownloadWatch:
    """A download is finished when its partial file (.crdownload, .part…) disappears and the final file exists with a
    stable size. Only downloads seen in progress are reported – no noise about files copied in."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.partial: dict[str, float] = {}           # final name → since
        self.pending: dict[str, int] = {}             # final name → last size (waiting for it to settle)
        self.sizes: dict[str, tuple[float, int]] = {}  # partial file → (when, bytes) for the speed (OMEGA 075)

    def progress(self, snap: dict[str, int], now: float) -> list[dict]:
        """Files being downloaded right now: real size so far and speed since the last look."""
        out = []
        for name, size in snap.items():
            f = self.final_name(name)
            if not f:
                continue
            prev = self.sizes.get(name)
            speed = (size - prev[1]) / (now - prev[0]) if prev and now > prev[0] and size >= prev[1] else 0.0
            self.sizes[name] = (now, size)
            out.append({"file": f, "bytes": size, "speed": round(speed)})
        self.sizes = {k: v for k, v in self.sizes.items() if k in snap}
        return sorted(out, key=lambda x: -x["speed"])

    @staticmethod
    def final_name(name: str) -> str | None:
        low = name.lower()
        for ext in PARTIAL:
            if low.endswith(ext):
                base = name[: -len(ext)]
                return re.sub(r"\.[0-9a-f-]{6,}$", "", base) if ext in (".tmp", ".part") else base
        return None

    def step(self, snap: dict[str, int] | None = None, now: float | None = None) -> list[dict]:
        snap = _snapshot(self.folder) if snap is None else snap
        now = time.time() if now is None else now
        done = []
        for name in snap:
            f = self.final_name(name)
            if f and f not in self.partial:
                self.partial[f] = now
        for f in list(self.partial):
            if not any(self.final_name(n) == f for n in snap):
                if f in snap:
                    if self.pending.get(f) == snap[f]:
                        done.append({"file": f, "bytes": snap[f], "seconds": round(now - self.partial.pop(f))})
                        self.pending.pop(f, None)
                    else:
                        self.pending[f] = snap[f]
                elif now - self.partial[f] > 30:
                    self.partial.pop(f)                   # cancelled download
                    self.pending.pop(f, None)
        return done


LUX_PS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
  $null = [Windows.Devices.Sensors.LightSensor, Windows.Devices.Sensors, ContentType = WindowsRuntime]
  $s = [Windows.Devices.Sensors.LightSensor]::GetDefault()
  if ($s) { $r = $s.GetCurrentReading(); "{""lux"": $([math]::Round($r.IlluminanceInLux, 1))}" } else { '{"lux": null}' }
} catch { '{"lux": null}' }
"""


def ambient_lux() -> float | None:
    """OMEGA 741: the ambient light sensor (laptops / tablets that have one) through the Windows sensor API; None = no sensor."""
    import base64
    import json as _json
    import sys as _sys

    if _sys.platform != "win32":
        return None
    from .pcreport import run_quiet

    enc = base64.b64encode(LUX_PS.encode("utf-16-le")).decode()
    _c, out, _e = run_quiet(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], 20)
    try:
        v = _json.loads(out[out.find("{"):]).get("lux") if "{" in out else None
    except ValueError:
        return None
    return float(v) if isinstance(v, (int, float)) else None


def glow_for_lux(lux: float | None) -> float:
    """How bright the notch glow should be (0.35–1): dim in a dark room, full in daylight; no sensor → full."""
    if lux is None:
        return 1.0
    import math

    return round(max(0.35, min(1.0, 0.35 + 0.65 * math.log10(1 + lux) / math.log10(1 + 500))), 2)


EXPLORER_COPY = re.compile(r"(\d{1,3})\s*%\s*(dokončeno|complete|hotovo)", re.I)


def explorer_copy(titles: list[str]) -> int | None:
    """OMEGA 074: a copy / move running in File Explorer – its progress dialog's title ("45 % dokončeno") → the percent."""
    for t in titles:
        m = EXPLORER_COPY.search(t or "")
        if m:
            return int(m.group(1))
    return None


INSTALLER = re.compile(r"(setup|install|installer|uninstall|update)[\w.-]*\.exe$|^(winget|choco|scoop)\.exe$", re.I)


def installers(procs: list[dict]) -> dict[int, str]:
    """psutil-like [{pid, name, cmdline}] → {pid: name} of what is installing right now."""
    out = {}
    for p in procs:
        name = (p.get("name") or "")
        cmd = " ".join(p.get("cmdline") or [])
        if INSTALLER.search(name) or (name.lower() == "msiexec.exe" and re.search(r"(?i)\s/(i|package|x)\b", cmd)):
            out[p["pid"]] = name
    return out


class InstallWatch:
    def __init__(self):
        self.seen: dict[int, tuple[str, float]] = {}

    def step(self, current: dict[int, str], now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        for pid, name in current.items():
            self.seen.setdefault(pid, (name, now))
        done = []
        for pid in list(self.seen):
            if pid not in current:
                name, since = self.seen.pop(pid)
                if now - since >= 10:                    # ignore helpers that flash for a moment
                    done.append({"installer": name, "seconds": round(now - since)})
        return done


# ---------------------------------------------------------------- P10.04 automatic backups
def backup_due_message(r: dict, source: str) -> tuple[str, bool]:
    ok = not r["failed"] and not r["verify_failed"]
    msg = (f"Záloha {Path(source).name}: {r['copied']} nových / změněných souborů, {r['unchanged']} beze změny"
           + (", vše ověřeno." if ok else f", {len(r['failed'])} chyb, {len(r['verify_failed'])} nesedí otisk."))
    return msg, ok


async def run_backup(rt, payload: dict) -> dict:
    from . import fileuniverse as fu

    src, dst = Path(payload["source"]), Path(payload["destination"])
    if not src.is_dir():
        rt.notify("Automatická záloha", f"Složka {src} neexistuje – záloha neproběhla.", speak=False)
        return {"ok": False, "reason": "source"}
    if not dst.anchor or not Path(dst.anchor).exists() or not (dst.exists() or dst.parent.exists()):
        rt.notify("Automatická záloha", f"Cíl {dst} není dostupný (připoj disk) – zkusím to příště.", speak=False)
        return {"ok": False, "reason": "target"}
    dst.mkdir(parents=True, exist_ok=True)
    r = await asyncio.to_thread(fu.backup, src, dst)
    msg, ok = backup_due_message(r, str(src))
    rt.db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (f"auto_backup:{src}", json.dumps({"ts": time.time(), "ok": ok, "msg": msg}, ensure_ascii=False)))
    if r["copied"] or not ok:
        rt.notify("Automatická záloha", msg, speak=False)
    return {"ok": ok, **r}


# ---------------------------------------------------------------- P12.08 screenshots and clips
SHOT = re.compile(r"(?i)(snímek obrazovky|snimek obrazovky|screenshot|screen shot|výstřižek|vystrizek|screen recording|záznam obrazovky|capture)")


def screenshot_folders(home: Path | None = None) -> list[Path]:
    h = home or Path.home()
    return [h / "Pictures" / "Screenshots", h / "Obrázky" / "Snímky obrazovky", h / "Videos" / "Captures", h / "Videos" / "Screen Recordings",
            h / "Desktop", h / "Pictures", h / "Downloads"]


def find_screenshots(folders: list[Path], now: float | None = None) -> dict:
    now = now or time.time()
    items, seen = [], set()
    for d in folders:
        if not d.is_dir():
            continue
        in_shot_dir = bool(re.search(r"(?i)screenshot|snímky obrazovky|captures|recording", d.name))
        for p in d.iterdir():
            if not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".mp4", ".webm", ".mkv") or p in seen:
                continue
            if not (in_shot_dir or SHOT.search(p.name)):
                continue
            seen.add(p)
            st = p.stat()
            items.append({"path": str(p), "name": p.name, "bytes": st.st_size, "mtime": st.st_mtime,
                          "kind": "klip" if p.suffix.lower() in (".mp4", ".webm", ".mkv", ".gif") else "snímek"})
    by_hash: dict[str, list] = {}
    for it in items:
        if it["bytes"] < 50 * 2**20:
            h = hashlib.sha256(Path(it["path"]).read_bytes()).hexdigest()
            by_hash.setdefault(h, []).append(it["path"])
    dups = [sorted(v) for v in by_hash.values() if len(v) > 1]
    old = [i for i in items if now - i["mtime"] > 90 * 86400]
    return {"items": sorted(items, key=lambda i: -i["mtime"]), "count": len(items), "bytes": sum(i["bytes"] for i in items),
            "clips": sum(1 for i in items if i["kind"] == "klip"), "duplicates": dups, "old": len(old),
            "old_bytes": sum(i["bytes"] for i in old)}


def organize_plan(items: list[dict], dest_root: Path) -> list[dict]:
    """Move into dest_root/<year>-<month>/ (clips into a 'Klipy' subfolder); names that would clash get a number."""
    plan, taken = [], set()
    for it in items:
        m = dt.datetime.fromtimestamp(it["mtime"])
        d = dest_root / f"{m:%Y-%m}" / ("Klipy" if it["kind"] == "klip" else "")
        t = d / it["name"]
        n = 1
        while str(t) in taken or (t.exists() and str(t) != it["path"]):
            t = d / f"{Path(it['name']).stem} ({n}){Path(it['name']).suffix}"
            n += 1
        taken.add(str(t))
        if str(t) != it["path"]:
            plan.append({"from": it["path"], "to": str(t)})
    return plan


# ---------------------------------------------------------------- P13.04 Bluetooth
BT_PS = r"""
$bt = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -and $_.InstanceId -notmatch 'BTHENUM\\\{0000' }
$out = foreach ($d in $bt) {
  $b = $null
  try { $b = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName '{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2' -ErrorAction Stop).Data } catch {}
  [pscustomobject]@{ Name = $d.FriendlyName; Status = "$($d.Status)"; Id = $d.InstanceId; Battery = $b }
}
@($out) | ConvertTo-Json -Compress
"""
ADAPTER = re.compile(r"(?i)adapter|radio|enumerator|transport|microsoft bluetooth|generic|le enumerator|avrcp|service|rfcomm|attribute")


def parse_bluetooth(rows: list[dict]) -> list[dict]:
    out, seen = [], set()
    for r in rows:
        name = (r.get("Name") or "").strip()
        if not name or ADAPTER.search(name) or name in seen:
            continue
        seen.add(name)
        bat = r.get("Battery")
        kind = "sluchátka" if re.search(r"(?i)buds|airpods|headphone|headset|wh-|wf-|jabra|bose|sluch", name) else \
            "myš" if re.search(r"(?i)mouse|myš|mx ", name) else "klávesnice" if re.search(r"(?i)keyboard|klávesnice|keys", name) else \
            "telefon" if re.search(r"(?i)phone|galaxy|pixel|redmi|xiaomi", name) else "ovladač" if re.search(r"(?i)controller|gamepad|xbox|dualsense", name) else "zařízení"
        out.append({"name": name, "connected": r.get("Status") == "OK", "battery": int(bat) if isinstance(bat, (int, float)) else None, "kind": kind})
    return sorted(out, key=lambda d: (not d["connected"], d["name"]))


HEADPHONES = re.compile(r"(?i)headphone|headset|sluch|buds|airpods|wh-|wf-|jabra|bose|beats|earphone|hands-free|sennheiser|hyperx|steelseries|razer|logitech g")


def audio_link(before: dict | None, now: dict | None) -> dict | None:
    """What the notch should announce when the sound output changes (None at start-up or when nothing changed)."""
    if not before or not now or before.get("id") == now.get("id") or not now.get("name"):
        return None
    name = now["name"]
    short = re.sub(r"^.*?\((.+)\)\s*$", r"\1", name).strip() or name      # "Sluchátka (AirPods Pro)" → "AirPods Pro"
    kind = "headphones" if HEADPHONES.search(name) else "speakers"
    return {"kind": kind, "name": short[:40], "full": name[:80]}


# ---------------------------------------------------------------- P3.12 mood from the tone of voice
def _f0(frame: np.ndarray, sr: int) -> float:
    frame = frame - frame.mean()
    if np.sqrt((frame ** 2).mean()) < 0.01:
        return 0.0
    ac = np.correlate(frame, frame, "full")[len(frame) - 1:]
    lo, hi = int(sr / 400), int(sr / 70)
    if hi >= len(ac):
        return 0.0
    k = lo + int(np.argmax(ac[lo:hi]))
    return sr / k if ac[k] > 0.3 * ac[0] else 0.0


def voice_features(samples: np.ndarray, sr: int) -> dict:
    """Pitch (median and spread), loudness, how much of the time is speech, and a speaking-rate proxy (energy peaks / s)."""
    x = samples.astype(np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if np.abs(x).max() > 1.5:
        x = x / 32768.0
    n = int(sr * 0.04)
    frames = [x[i:i + n] for i in range(0, len(x) - n, n // 2)]
    rms = np.array([np.sqrt((f ** 2).mean()) for f in frames]) if frames else np.zeros(1)
    voiced = rms > max(0.02, rms.max() * 0.15) if rms.size else np.zeros(1, bool)
    f0 = np.array([_f0(f, sr) for f, v in zip(frames, voiced) if v])
    f0 = f0[f0 > 0]
    env = np.convolve(rms, np.ones(3) / 3, "same")
    peaks = int(((env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) & (env[1:-1] > env.max() * 0.3)).sum()) if env.size > 2 else 0
    dur = len(x) / sr
    return {"pitch_hz": round(float(np.median(f0)), 1) if f0.size else 0.0,
            "pitch_spread": round(float(np.std(f0) / np.median(f0)), 3) if f0.size > 2 else 0.0,
            "loudness_db": round(20 * math.log10(float(rms[voiced].mean()) + 1e-9), 1) if voiced.any() else -90.0,
            "speech_share": round(float(voiced.mean()), 2), "rate": round(peaks / dur, 2) if dur else 0.0, "seconds": round(dur, 1)}


def voice_mood(f: dict, baseline: dict | None = None) -> dict:
    """A cautious read of how the voice sounds (tension, tiredness, liveliness) – from the tone, never from the words.
    Compared with the user's own baseline when there is one."""
    b = baseline or {"pitch_hz": f["pitch_hz"] or 150, "pitch_spread": 0.12, "loudness_db": -22.0, "rate": 3.0}
    if f["seconds"] < 1.5 or f["speech_share"] < 0.2 or not f["pitch_hz"]:
        return {"mood": "nevím", "why": "málo řeči", "confidence": 0.0}
    hi_pitch = f["pitch_hz"] > b["pitch_hz"] * 1.12
    lo_pitch = f["pitch_hz"] < b["pitch_hz"] * 0.92
    lively = f["pitch_spread"] > b["pitch_spread"] * 1.3
    flat = f["pitch_spread"] < b["pitch_spread"] * 0.6
    loud = f["loudness_db"] > b["loudness_db"] + 4
    quiet = f["loudness_db"] < b["loudness_db"] - 5
    fast = f["rate"] > b["rate"] * 1.25
    slow = f["rate"] < b["rate"] * 0.75
    if hi_pitch and fast and (loud or not lively):
        mood, why = "napětí / spěch", "hlas je výš, rychlejší a hlasitější než obvykle"
    elif lively and (hi_pitch or loud):
        mood, why = "nadšení", "živá melodie a energie"
    elif (lo_pitch or flat) and (slow or quiet):
        mood, why = "únava", "hlas je nižší, plošší a pomalejší"
    else:
        mood, why = "klid", "nic neobvyklého"
    signals = sum([hi_pitch, lo_pitch, lively, flat, loud, quiet, fast, slow])
    return {"mood": mood, "why": why, "confidence": round(min(0.8, 0.3 + 0.12 * signals), 2)}


# ---------------------------------------------------------------- P9.08 screen sharing
class ScreenShare:
    """The PC screen to the paired phone as a slow MJPEG stream – only while switched on (visible on the PC), windows that
    look private are blacked out, it stops by itself after `minutes`."""

    def __init__(self, rt):
        self.rt = rt
        self.until = 0.0
        self.viewers = 0
        self.size: tuple[int, int] | None = None      # the real screen size of the last frame (for remote clicks)
        self.fps = 2.0

    @property
    def active(self) -> bool:
        return time.time() < self.until

    def start(self, minutes: float = 15, quiet: bool = False) -> None:
        self.until = time.time() + max(1, min(minutes, 120)) * 60
        self.rt.bus.publish("screen_share", active=True, until=self.until)
        if not quiet:
            self.rt.notify("Sdílím obrazovku", f"Telefon vidí obrazovku PC ({round(minutes)} min). Zastavíš „přestaň sdílet“.", speak=False)

    def stop(self) -> None:
        if self.until:
            self.until = 0.0
            self.rt.bus.publish("screen_share", active=False, until=0)

    def frame(self, width: int = 960, quality: int = 60) -> bytes:
        from PIL import Image

        from .vision import private_screenshot

        png, _ = private_screenshot(self.rt)
        im = Image.open(io.BytesIO(png)).convert("RGB")
        self.size = (im.width, im.height)
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        return buf.getvalue()

    async def stream(self, fps: float | None = None):
        self.viewers += 1
        try:
            while self.active:
                remote = bool(getattr(getattr(self.rt, "remote_desk", None), "on", False))
                # driving with a finger: more frames, a little sharper; same picture otherwise
                jpg = await asyncio.to_thread(self.frame, 1280 if remote else 960, 55 if remote else 60)
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
                await asyncio.sleep(1 / (fps or (5.0 if remote else self.fps)))
        finally:
            self.viewers -= 1


# ---------------------------------------------------------------- P9.09 several PCs
async def peer_command(peer: dict, token: str, text: str, transport=None, timeout: float = 150) -> dict:
    import httpx

    async with httpx.AsyncClient(transport=transport, timeout=timeout) as c:
        r = await c.post(peer["url"].rstrip("/") + "/api/remote/command", json={"text": text, "from": peer.get("me", "")},
                         headers={"Authorization": f"Bearer {token}"})
    if r.status_code == 401:
        raise PermissionError("Druhý počítač odmítl klíč – spáruj ho znovu.")
    r.raise_for_status()
    return r.json()


async def peer_status(peer: dict, transport=None) -> dict:
    import httpx

    try:
        async with httpx.AsyncClient(transport=transport, timeout=5) as c:
            r = await c.get(peer["url"].rstrip("/") + "/api/health")
        return {"online": r.status_code == 200, **(r.json() if r.status_code == 200 else {})}
    except Exception as e:  # noqa: BLE001
        return {"online": False, "error": type(e).__name__}


# ---------------------------------------------------------------- P12.02 music in the notch
def bars(peaks: list[float], n: int = 7, seed: float = 0.0) -> list[float]:
    """A peak-meter history → n bar heights 0–1 for the notch (the newest level drives the middle, the edges echo older
    values, a little per-bar movement so it looks alive without a real spectrum)."""
    if not peaks:
        return [0.0] * n
    recent = peaks[-n:] + [0.0] * max(0, n - len(peaks))
    level = max(0.0, min(1.0, peaks[-1]))
    out = []
    for i in range(n):
        d = abs(i - (n - 1) / 2) / ((n - 1) / 2 or 1)
        echo = recent[-1 - min(int(d * (len(recent) - 1)), len(recent) - 1)]
        wobble = 0.15 * math.sin(seed * 7.3 + i * 1.7)
        out.append(round(max(0.04, min(1.0, (level * (1 - 0.45 * d) + echo * 0.3) * (1 + wobble))), 3))
    return out


def peak_meter():                                             # pragma: no cover – Windows
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation

    dev = AudioUtilities.GetSpeakers()
    iface = dev.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioMeterInformation))


def _volume_publish(rt, state: tuple, last: tuple | None, publish) -> tuple:
    rt.last_audio = {"level": state[0], "muted": bool(state[1])}     # for windows that connect later
    if last is not None and state != last:
        publish("volume", level=state[0], muted=bool(state[1]))
    if state != last and getattr(rt, "volume_feeds_mood", False):  # Mochi's reaction to the volume, from this one reader
        mood = getattr(rt, "mood", None)
        if mood is not None:
            rt.call_soon(lambda: mood.on_audio(state[0], bool(state[1])))
    return state


def volume_pause(since_change: float, idle: float) -> float:
    """How long to wait before reading the volume again: quick right after a change, calm otherwise."""
    return 0.04 if since_change < 1.5 else idle


def _win_volume_thread(rt, interval: float) -> None:                 # pragma: no cover – Windows
    """One thread for the whole life of JARVIS: COM initialised once, the speaker opened once. Opening it on a fresh
    worker thread every poll and letting Python free it later on another thread crashed the process (comtypes
    Release after CoUninitialize)."""
    import comtypes

    comtypes.CoInitialize()
    ep, last, moved = None, None, 0.0
    while True:
        try:
            if ep is None:
                ep = rt.platform._endpoint()
            state = (round(ep.GetMasterVolumeLevelScalar() * 100), bool(ep.GetMute()))
            if last is not None and state != last:
                moved = time.monotonic()
            last = _volume_publish(rt, state, last, rt.bus.publish_threadsafe)
            # while the volume is moving (a key held, the slider dragged) read it ~25× a second so the bar in the
            # notch glides with it; otherwise a calm pace
            time.sleep(volume_pause(time.monotonic() - moved, interval))
        except Exception:                                    # no speaker / device changed: open it again later
            ep = None
            time.sleep(5)


async def volume_loop(rt, interval: float = 0.25, rounds: int | None = None) -> None:
    """The system volume as it changes (keys, the mixer, another app): the notch shows a volume bar for a moment.
    The first reading is only remembered; nothing is published until the volume really changes."""
    import sys
    import threading

    if sys.platform == "win32" and hasattr(rt.platform, "_endpoint") and rounds is None:
        rt.volume_feeds_mood = True          # saving power: the mood's own volume poll (every 1.5 s) steps aside
        threading.Thread(target=_win_volume_thread, args=(rt, interval), daemon=True, name="volume").start()
        return
    last: tuple | None = None
    n = 0
    while rounds is None or n < rounds:
        n += 1
        try:
            state = rt.platform.audio_state()
        except Exception:
            state = (None, None)
        if state[0] is not None:
            last = _volume_publish(rt, state, last, rt.bus.publish)
        await asyncio.sleep(interval if state[0] is not None else 5)


def tempo_bpm(levels: list[float], rate_hz: float, lo: float = 60, hi: float = 180) -> tuple[float | None, float]:
    """OMEGA 244: the beat of the music from the loudness meter alone (no recording): onsets = rises of the level,
    their autocorrelation peaks at the beat period. Answers (bpm, confidence 0–1); None when there is no clear beat."""
    import numpy as np

    x = np.asarray(levels, dtype=float)
    if len(x) < rate_hz * 4:
        return None, 0.0
    on = np.maximum(np.diff(x), 0)
    on = on - on.mean()
    if not on.any() or np.std(on) < 1e-6:
        return None, 0.0
    ac = np.correlate(on, on, mode="full")[len(on) - 1:]
    ac = ac / (ac[0] or 1)
    lmin, lmax = int(rate_hz * 60 / hi), int(rate_hz * 60 / lo) + 1
    if lmax >= len(ac) or lmin < 1:
        return None, 0.0
    k = lmin + int(np.argmax(ac[lmin:lmax]))
    conf = float(max(0.0, ac[k]))
    if 0 < k < len(ac) - 1:                       # parabolic refinement of the peak
        a, b, c = ac[k - 1], ac[k], ac[k + 1]
        d = (a - c) / (2 * (a - 2 * b + c)) if (a - 2 * b + c) else 0.0
        k = k + max(-0.5, min(0.5, d))
    bpm = 60 * rate_hz / k
    while bpm < 80:
        bpm *= 2
    while bpm > 170:
        bpm /= 2
    return (round(float(bpm), 1) if conf >= 0.2 else None), round(conf, 2)


async def music_loop(rt) -> None:                             # pragma: no cover – Windows
    import sys

    if sys.platform != "win32":
        return
    meter = None
    hist: list[float] = []
    beat: list[float] = []                       # OMEGA 244: ~12 s of levels at 20 Hz → the tempo for Mochi's dance
    beat_at = 0.0
    tick = 0
    quiet_since = time.time()
    while True:
        try:
            if not getattr(rt.cfg.notch, "music_viz", True) or not rt.cfg.notch.enabled:
                await asyncio.sleep(2)
                continue
            if meter is None:
                meter = await asyncio.to_thread(peak_meter)
            p = float(meter.GetPeakValue())
            hist = (hist + [p])[-12:]
            if p > 0.01:
                quiet_since = time.time()
                beat = (beat + [p])[-240:]
                tick += 1
                if tick % 2 == 0:                    # the bars stay at 10 Hz, the meter is read at 20 Hz
                    rt.bus.publish("music_level", bars=bars(hist, 7, time.time()))
                if len(beat) >= 160 and time.time() - beat_at > 8:
                    beat_at = time.time()
                    bpm, conf = tempo_bpm(beat, 20.0)
                    if bpm:
                        rt.bus.publish("beat", bpm=bpm, confidence=conf)
                await asyncio.sleep(0.05)
            else:
                beat = []
                if time.time() - quiet_since < 1.5:
                    rt.bus.publish("music_level", bars=[0.0] * 7)
                await asyncio.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            log.debug("music meter: %s", e)
            meter = None
            await asyncio.sleep(10)


# ---------------------------------------------------------------- P15.07 personal knowledge graph
def knowledge_graph(rt, center: str = "", limit: int = 40) -> dict:
    """Entities (people, e-mails, projects…) as nodes; an edge when two appear in the same item, weighted by how often."""
    from .intelplus import LINKS_SQL

    for s in LINKS_SQL:
        rt.db.exec(s)
    rows = rt.db.all("SELECT entity, kind, source, ref FROM sem_links")
    items: dict[tuple, set] = {}
    kinds: dict[str, str] = {}
    for r in rows:
        items.setdefault((r["source"], r["ref"]), set()).add(r["entity"])
        kinds[r["entity"]] = r["kind"]
    weight: dict[tuple, int] = {}
    count: dict[str, int] = {}
    for ents in items.values():
        for e in ents:
            count[e] = count.get(e, 0) + 1
        es = sorted(ents)
        for i, a in enumerate(es):
            for b in es[i + 1:]:
                weight[(a, b)] = weight.get((a, b), 0) + 1
    if center:
        from .comms import fold

        c = fold(center)
        focus = {e for e in count if c in e}
        keep = focus | {b if a in focus else a for (a, b) in weight if a in focus or b in focus}
    else:
        keep = set(sorted(count, key=lambda e: -count[e])[:limit])
    keep = set(sorted(keep, key=lambda e: -count[e])[:limit])
    nodes = [{"id": e, "kind": kinds[e], "mentions": count[e]} for e in sorted(keep, key=lambda e: -count[e])]
    edges = [{"a": a, "b": b, "weight": w} for (a, b), w in weight.items() if a in keep and b in keep]
    return {"nodes": nodes, "edges": sorted(edges, key=lambda e: -e["weight"])}


def graph_svg(g: dict, size: int = 640) -> str:
    import html as h

    n = len(g["nodes"])
    if not n:
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}"/>'
    pos = {}
    c = size / 2
    for i, node in enumerate(g["nodes"]):
        if i == 0:
            pos[node["id"]] = (c, c)
            continue
        ring = 1 + (i - 1) // 12
        k = (i - 1) % 12
        a = 2 * math.pi * k / min(12, n - 1 - (ring - 1) * 12) + ring * 0.4
        r = size * 0.18 * ring
        pos[node["id"]] = (c + r * math.cos(a), c + r * math.sin(a))
    col = {"jméno": "#60a5fa", "email": "#34d399", "projekt": "#f59e0b", "telefon": "#f472b6", "ičo": "#a78bfa"}
    lines = "".join(f'<line x1="{pos[e["a"]][0]:.0f}" y1="{pos[e["a"]][1]:.0f}" x2="{pos[e["b"]][0]:.0f}" y2="{pos[e["b"]][1]:.0f}" '
                    f'stroke="#475569" stroke-width="{min(6, e["weight"])}"/>' for e in g["edges"])
    dots = "".join(f'<circle cx="{pos[x["id"]][0]:.0f}" cy="{pos[x["id"]][1]:.0f}" r="{6 + min(14, x["mentions"] * 2)}" fill="{col.get(x["kind"], "#94a3b8")}"/>'
                   f'<text x="{pos[x["id"]][0]:.0f}" y="{pos[x["id"]][1] + 26:.0f}" fill="#e5e7eb" font-size="12" text-anchor="middle">{h.escape(x["id"][:28])}</text>'
                   for x in g["nodes"])
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}"><rect width="100%" height="100%" fill="#0b0d12"/>{lines}{dots}</svg>'




def update_voice_mood(rt, samples: np.ndarray, sr: int) -> dict:
    """Features of this utterance vs a slowly learnt baseline of the user's voice (kept as numbers only, no audio)."""
    f = voice_features(samples, sr)
    row = rt.db.one("SELECT v FROM kv WHERE k='voice_baseline'")
    base = json.loads(row["v"]) if row else None
    mood = voice_mood(f, base if base and base.get("n", 0) >= 5 else None)
    if f["pitch_hz"] and f["speech_share"] >= 0.2:
        n = (base or {}).get("n", 0)
        a = 1 / (n + 1) if n < 20 else 0.05
        keys = ("pitch_hz", "pitch_spread", "loudness_db", "rate")
        nb = {k: round((base or f)[k] * (1 - a) + f[k] * a, 4) for k in keys} if base else {k: f[k] for k in keys}
        nb["n"] = n + 1
        rt.db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES ('voice_baseline', ?)", (json.dumps(nb),))
    rt.voice_mood = {**mood, "ts": time.time()}
    return {**mood, "features": f}


async def watch_loop(rt, every: float = 5.0) -> None:
    """Background: finished downloads in the Downloads folder and finished installers → a short notice."""
    import psutil

    dl = DownloadWatch(Path.home() / "Downloads")
    inst = InstallWatch()
    lux_at, lux_ok = 0.0, True
    while True:
        await asyncio.sleep(every)
        if lux_ok and time.time() - lux_at > 60:            # OMEGA 741: room light → notch glow (only if a sensor exists)
            lux_at = time.time()
            lux = await asyncio.to_thread(ambient_lux)
            if lux is None:
                lux_ok = False
            else:
                rt.bus.publish("ambient", lux=lux, glow=glow_for_lux(lux))
        try:                                      # OMEGA 240 / 764: battery ↔ charger → the UI can save power
            bat = psutil.sensors_battery()
            on_bat = bool(bat and not bat.power_plugged)
            if on_bat != getattr(rt, "on_battery", False):
                rt.on_battery = on_bat
                rt.bus.publish("power_state", on_battery=on_bat, percent=round(bat.percent) if bat else None)
        except (AttributeError, OSError, RuntimeError):
            pass
        try:                                      # 3.12 headphones / speakers switched → the notch shows it (like an iPhone)
            out = await asyncio.to_thread(rt.platform.default_output)
            link = audio_link(getattr(rt, "_audio_out", None), out)
            if out:
                rt._audio_out = out
            if link:
                rt.bus.publish("device_link", **link)
        except Exception:  # noqa: BLE001
            pass
        att = getattr(rt, "attention", None)
        if att is not None:
            summary = att.flush()                  # OMEGA 753: what waited during the focus / meeting / game
            if summary:
                rt.notify(summary["title"], summary["body"], speak=False, urgent=True)
        if not getattr(rt.cfg.powers, "download_watch", True):
            continue
        try:
            pct = explorer_copy(await asyncio.to_thread(rt.platform.list_windows))
            if pct is not None and time.time() - getattr(rt, "_copy_seen", 0) > 20 and getattr(rt, "mood", None):
                rt._copy_seen = time.time()            # Mochi carries boxes while Explorer copies (once per copy)
                rt.mood.react("copy", {"tool": "explorer", "percent": pct})
            snap = await asyncio.to_thread(_snapshot, dl.folder)
            prog = dl.progress(snap, time.time())
            if prog or getattr(rt, "_dl_shown", False):
                rt.bus.publish("download_progress", items=prog[:3])
                rt._dl_shown = bool(prog)
            for d in dl.step(snap):
                rt.notify("Stahování dokončeno", f"{d['file']} ({d['bytes'] / 2**20:.1f} MB)", speak=False)
            procs = await asyncio.to_thread(installer_procs)
            for d in inst.step(installers(procs)):
                rt.notify("Instalace dokončena", f"{d['installer']} doběhl ({d['seconds'] // 60} min {d['seconds'] % 60} s).", speak=False)
        except Exception as e:  # noqa: BLE001
            log.debug("download watch: %s", e)
