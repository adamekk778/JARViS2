"""3.3 everyday powers: selected text anywhere, clipboard history, screen time, break reminders, website watching,
disk clean-up and the internet speed test.

The activity sampler runs every few seconds and only looks at which window is in front and whether the clipboard
changed. Nothing leaves the PC; the clipboard history lives in memory only.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import html
import logging
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

USAGE_SQL = """
CREATE TABLE IF NOT EXISTS app_usage (day TEXT, app TEXT, seconds REAL, PRIMARY KEY (day, app));
"""
SAMPLE_S = 3.0
IDLE_AWAY_S = 120          # no input this long = not at the PC (no screen time, a break)
BREAK_RESET_S = 300        # away this long = the break happened


def looks_secret(text: str) -> bool:
    """Passwords and keys are not kept in the clipboard history: one token, mixed character classes."""
    t = text.strip()
    if not 8 <= len(t) <= 128 or any(c.isspace() for c in t):
        return False
    if re.match(r"^(https?://|www\.)", t) or re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.]+", t):
        return False
    classes = sum(bool(re.search(p, t)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w]"))
    return classes >= 3 or bool(re.fullmatch(r"(sk|pk|ghp|gho|xox[bp]|AKIA)[\w-]{10,}", t))


class Activity:
    """The last window outside JARVIS, screen time, the clipboard history and the break reminder."""

    def __init__(self, rt):
        self.rt = rt
        self.last_external: dict = {}
        self.clips: deque[dict] = deque(maxlen=30)
        self._clip_seq = None
        self._active_since: float | None = None
        self._break_said = False
        self._task: asyncio.Task | None = None
        rt.db.conn.executescript(USAGE_SQL)

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.sample)
            except Exception as e:
                log.debug("activity: %s", e)
            await asyncio.sleep(SAMPLE_S)

    # ---------- one sample ----------
    def sample(self, now: float | None = None, dt_s: float = SAMPLE_S) -> None:
        now = time.time() if now is None else now
        p, cfg = self.rt.platform, self.rt.cfg.powers
        fg = p.foreground_info() or {}
        if fg.get("hwnd") and fg.get("pid") != os.getpid():
            self.last_external = {**fg, "ts": now}
        idle = p.idle_seconds()
        present = idle < IDLE_AWAY_S
        if cfg.screen_time and present and fg.get("app") and fg.get("pid") != os.getpid():
            day = dt.date.fromtimestamp(now).isoformat()
            self.rt.db.exec("INSERT INTO app_usage VALUES (?,?,?) ON CONFLICT(day, app) DO UPDATE SET seconds=seconds+excluded.seconds",
                            (day, fg["app"], dt_s))
        if cfg.clipboard_history:
            self._clipboard(now)
        self._breaks(now, idle, cfg.break_minutes)

    def _clipboard(self, now: float) -> None:
        p = self.rt.platform
        seq = p.clipboard_seq()
        if seq == self._clip_seq:
            return
        first = self._clip_seq is None
        self._clip_seq = seq
        if first:
            return                         # what was there before JARVIS started is not "history"
        try:
            text = p.clipboard_get() or ""
        except Exception:
            return
        text = text.strip()
        if not text or len(text) > 20000 or looks_secret(text):
            return
        if self.clips and self.clips[0]["text"] == text:
            return
        self.clips.appendleft({"text": text, "ts": now, "app": self.last_external.get("app", "")})

    def _breaks(self, now: float, idle: float, minutes: int) -> None:
        if idle >= BREAK_RESET_S or minutes <= 0:
            self._active_since, self._break_said = None, False
            return
        if self._active_since is None:
            self._active_since = now - idle
        if not self._break_said and now - self._active_since >= minutes * 60:
            self._break_said = True
            a = self.rt.cfg.general.address_as or "pane"
            self.rt.call_soon(lambda: self.rt.notify(
                "Přestávka", f"{a.capitalize()}, sedíte u počítače už {round((now - self._active_since) / 60)} minut v kuse. "
                             "Doporučuji krátkou pauzu – protáhnout se a napít.", speak=self.rt.cfg.voice.speak_mode != "never"))

    # ---------- queries ----------
    def screen_time(self, days: int = 1, today: dt.date | None = None) -> list[dict]:
        today = today or dt.date.today()
        start = (today - dt.timedelta(days=days - 1)).isoformat()
        rows = self.rt.db.all("SELECT app, SUM(seconds) s FROM app_usage WHERE day>=? GROUP BY app ORDER BY s DESC", (start,))
        return [{"app": r["app"], "minutes": round(r["s"] / 60)} for r in rows if r["s"] >= 30]

    def prune(self, keep_days: int = 30) -> None:
        self.rt.db.exec("DELETE FROM app_usage WHERE day<?", ((dt.date.today() - dt.timedelta(days=keep_days)).isoformat(),))


# ---------------------------------------------------------------------------------------------- selected text
def grab_selection(rt) -> tuple[str, dict]:
    """The text selected in the app in front (or in the last app before JARVIS took focus). Copies it with Ctrl+C
    and puts the old clipboard back. Returns (text, window)."""
    p = rt.platform
    p.wait_keys_released()
    act = getattr(rt, "activity", None)
    fg = p.foreground_info() or {}
    target = fg
    if fg.get("pid") == os.getpid() and act and act.last_external.get("hwnd"):
        target = act.last_external
        p.focus_window(target["hwnd"])
        time.sleep(0.25)
    try:
        old = p.clipboard_get()
    except Exception:
        old = None
    marker = f"⁣jarvis-{time.time_ns()}"
    p.clipboard_set(marker)
    p.hotkey(["ctrl", "c"])
    text = ""
    for _ in range(12):                      # some apps take a moment to fill the clipboard
        time.sleep(0.05)
        try:
            text = p.clipboard_get() or ""
        except Exception:
            text = ""
        if text != marker:
            break
    if text == marker:
        text = ""
    if old is not None:
        p.clipboard_set(old)
    return text, target


def replace_selection(rt, text: str, window: dict | None = None) -> bool:
    """Types `text` over the selection: back to that window, paste, clipboard restored."""
    p = rt.platform
    win = window or getattr(getattr(rt, "activity", None), "last_external", {}) or {}
    fg = p.foreground_info() or {}
    if win.get("hwnd") and fg.get("hwnd") != win["hwnd"]:
        if not p.focus_window(win["hwnd"]):
            return False
        time.sleep(0.25)
    try:
        old = p.clipboard_get()
    except Exception:
        old = None
    p.clipboard_set(text)
    time.sleep(0.05)
    p.hotkey(["ctrl", "v"])
    time.sleep(0.35)
    if old is not None:
        p.clipboard_set(old)
    return True


SELECTION_ACTIONS: dict[str, tuple[str, str, bool]] = {
    # key: (button label, instruction for the AI, replace the selection with the result?)
    "fix": ("Opravit pravopis", "Oprav pravopis, gramatiku a interpunkci. Zachovej jazyk, význam, styl a formátování. "
                                "Vrať jen opravený text.", True),
    "translate": ("Přeložit", "Přelož text: češtinu do angličtiny, cokoli jiného do češtiny. Vrať jen překlad.", True),
    "formal": ("Formálněji", "Přepiš text zdvořile a formálně (jako e-mail úřadu nebo šéfovi). Vrať jen nový text.", True),
    "shorter": ("Zkrátit", "Zkrať text na polovinu, zachovej to důležité. Vrať jen nový text.", True),
    "explain": ("Vysvětlit", "Vysvětli jednoduše česky, co ten text znamená (2–4 věty).", False),
    "summary": ("Shrnout", "Shrň text česky do 3 bodů.", False),
}


async def selection_action(rt, action: str, text: str, window: dict | None = None) -> dict:
    label, instr, replace = SELECTION_ACTIONS[action]
    out = await rt.router.complete([
        {"role": "system", "content": "Jsi JARVIS. Pracuješ s textem, který si uživatel označil v jiné aplikaci. " + instr},
        {"role": "user", "content": text[:12000]}])
    out = (out or "").strip()
    if replace and out:
        ok = await asyncio.to_thread(replace_selection, rt, out, window)
        return {"action": action, "label": label, "text": out, "replaced": ok}
    return {"action": action, "label": label, "text": out, "replaced": False}


# ---------------------------------------------------------------------------------------------- website watching
def page_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


async def check_watch(rt, payload: dict) -> tuple[bool, str, dict]:
    """(fire?, message, new payload). Mode "text": fires once the text appears; "change": whenever the page changes."""
    async with rt.http() as c:
        r = await c.get(payload["url"], timeout=20, headers={"User-Agent": "Mozilla/5.0 JARVIS"})
    text = page_text(r.text)
    want = (payload.get("text") or "").strip()
    if want:
        hit = want.lower() in text.lower()
        if hit:
            i = text.lower().index(want.lower())
            around = text[max(0, i - 80): i + len(want) + 80]
            return True, f"Na stránce se objevilo „{want}“: …{around}…", payload
        return False, "", payload
    digest = hashlib.sha256(text.encode()).hexdigest()
    old = payload.get("hash")
    new = {**payload, "hash": digest}
    if old is None or old == digest:
        return False, "", new
    return True, f"Stránka {payload['url']} se změnila.", new


# ---------------------------------------------------------------------------------------------- disk
def folder_size(path: Path, deadline: float) -> int:
    total = 0
    stack = [path]
    while stack and time.monotonic() < deadline:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def storage_report(home: Path | None = None, budget_s: float = 20.0) -> dict:
    import shutil

    home = home or Path.home()
    deadline = time.monotonic() + budget_s
    names = ["Downloads", "Desktop", "Documents", "Videos", "Pictures", "Music", "OneDrive", "AppData/Local/Temp"]
    folders = []
    for n in names:
        p = home / n
        if p.is_dir():
            folders.append({"name": n.replace("AppData/Local/Temp", "Dočasné soubory"), "path": str(p), "bytes": folder_size(p, deadline)})
    folders.sort(key=lambda f: -f["bytes"])
    big: list[tuple[int, str]] = []
    dl = home / "Downloads"
    if dl.is_dir():
        for root, _dirs, files in os.walk(dl):
            if time.monotonic() > deadline:
                break
            for f in files:
                try:
                    s = os.path.getsize(os.path.join(root, f))
                except OSError:
                    continue
                if s > 100 * 2**20:
                    big.append((s, os.path.join(root, f)))
    big.sort(reverse=True)
    du = shutil.disk_usage(home.anchor or "/")
    return {"folders": folders, "big_downloads": [{"path": p, "bytes": s} for s, p in big[:8]],
            "disk_free": du.free, "disk_total": du.total, "complete": time.monotonic() < deadline}


def temp_dirs() -> list[Path]:
    out = []
    for p in {os.environ.get("TEMP"), os.environ.get("TMP")}:
        if p and Path(p).is_dir():
            out.append(Path(p))
    return out


def clean_temp(dirs: list[Path], older_than_s: float = 86400) -> tuple[int, int]:
    """Deletes files in the temp folders older than a day (running apps keep using the fresh ones).
    Returns (files, bytes). Files in use are simply skipped."""
    cutoff = time.time() - older_than_s
    n = freed = 0
    for d in dirs:
        for root, _dirs, files in os.walk(d, topdown=False):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    st = os.lstat(fp)
                    if st.st_mtime < cutoff:
                        os.remove(fp)
                        n += 1
                        freed += st.st_size
                except OSError:
                    continue
            if root != str(d):
                try:
                    os.rmdir(root)            # only removes empty folders
                except OSError:
                    pass
    return n, freed


def fmt_bytes(n: float) -> str:
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "kB") else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return str(n)


# ---------------------------------------------------------------------------------------------- speed test
async def speed_test(rt, seconds: float = 8.0) -> dict:
    """Ping, download and upload against Cloudflare's public speed test endpoints."""
    import socket

    def ping() -> float | None:
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            try:
                with socket.create_connection(("speed.cloudflare.com", 443), timeout=3):
                    times.append((time.perf_counter() - t0) * 1000)
            except OSError:
                pass
        return round(min(times)) if times else None

    out: dict[str, Any] = {"ping_ms": await asyncio.to_thread(ping)}
    async with rt.http() as c:
        got, t0 = 0, time.perf_counter()
        try:
            async with c.stream("GET", "https://speed.cloudflare.com/__down?bytes=100000000", timeout=seconds + 5) as r:
                async for chunk in r.aiter_bytes():
                    got += len(chunk)
                    if time.perf_counter() - t0 > seconds:
                        break
        except Exception as e:
            log.debug("speed down: %s", e)
        el = max(0.001, time.perf_counter() - t0)
        out["down_mbps"] = round(got * 8 / el / 1e6, 1) if got else None
        try:
            body = os.urandom(8 * 2**20)
            t0 = time.perf_counter()
            await c.post("https://speed.cloudflare.com/__up", content=body, timeout=seconds + 10)
            out["up_mbps"] = round(len(body) * 8 / (time.perf_counter() - t0) / 1e6, 1)
        except Exception as e:
            log.debug("speed up: %s", e)
            out["up_mbps"] = None
    return out


async def selection_menu(rt) -> dict:
    """Ctrl+Alt+E: copy the selected text and offer what to do with it (in the notch)."""
    text, win = await asyncio.to_thread(grab_selection, rt)
    rt.selection = {"text": text, "window": win, "ts": time.time()}
    if not text.strip():
        rt.bus.publish("selection", text="", app=win.get("app", ""), actions=[])
        rt.notify("Označený text", "Nejdřív si označ text myší, pak zmáčkni Ctrl+Alt+E.", speak=False)
        return rt.selection
    rt.bus.publish("selection", text=text[:400], length=len(text), app=win.get("app", ""),
                   actions=[{"key": k, "label": v[0], "replace": v[2]} for k, v in SELECTION_ACTIONS.items()])
    return rt.selection


async def run_selection_action(rt, action: str) -> dict:
    sel = getattr(rt, "selection", None) or {}
    if action not in SELECTION_ACTIONS or not sel.get("text"):
        rt.bus.publish("selection_result", action=action, ok=False, text="Označený text už nemám, zkus Ctrl+Alt+E znovu.")
        return {}
    rt.bus.publish("state", state="thinking")
    try:
        res = await selection_action(rt, action, sel["text"], sel.get("window"))
        rt.bus.publish("selection_result", ok=True, **res)
        if not res["replaced"] and rt.cfg.voice.speak_mode == "always":
            rt.speak(res["text"])
        return res
    except Exception as e:
        log.warning("selection action: %s", e)
        rt.bus.publish("selection_result", action=action, ok=False, text=f"Nepovedlo se: {e}")
        return {}
    finally:
        rt.bus.publish("state", state="idle")


def selftest_windows() -> dict:
    """CI on real Windows: Notepad → type → select all → read it like JARVIS → replace it → read again."""
    import ctypes
    import subprocess
    import tempfile
    from ctypes import wintypes

    from .tools.platform.windows import WindowsPlatform

    p = WindowsPlatform()

    class _Rt:   # just what grab/replace need
        platform = p
        activity = None

    out: dict[str, Any] = {"idle_s": round(p.idle_seconds(), 1)}
    seq0 = p.clipboard_seq()
    p.clipboard_set("jarvis-selftest")
    out["clipboard_seq_changes"] = p.clipboard_seq() != seq0
    path = Path(tempfile.mkdtemp()) / "jarvis-selftest.txt"
    path.write_text("", encoding="utf-8")
    proc = subprocess.Popen(["notepad.exe", str(path)])
    try:
        u = ctypes.windll.user32
        found: list[int] = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(h, _):
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == proc.pid and u.IsWindowVisible(h):
                found.append(int(h or 0))
            return True

        for _ in range(40):
            found.clear()
            u.EnumWindows(proto(cb), 0)
            if found:
                break
            time.sleep(0.25)
        if not found:
            return {**out, "skipped": "Notepad window not found"}
        hwnd = found[0]
        out["focus"] = p.focus_window(hwnd)
        time.sleep(0.5)
        fg = p.foreground_info()
        out["foreground"] = {k: fg.get(k) for k in ("app", "exe", "title")}
        p.type_text("dobry den, posilam fakturu")
        time.sleep(0.3)
        p.hotkey(["ctrl", "a"])
        text, _win = grab_selection(_Rt())
        out["grabbed"] = text
        replace_selection(_Rt(), "Dobrý den, posílám fakturu.", {"hwnd": hwnd})
        time.sleep(0.3)
        p.hotkey(["ctrl", "a"])
        out["after"], _ = grab_selection(_Rt())
        out["clipboard_restored"] = p.clipboard_get() == "jarvis-selftest"
        out["ok"] = (out["grabbed"] == "dobry den, posilam fakturu" and out["after"] == "Dobrý den, posílám fakturu."
                     and out["clipboard_restored"])
        return out
    finally:
        proc.kill()
