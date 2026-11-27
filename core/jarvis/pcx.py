"""3.20 Ovládání PC+ (nápady 81–100 ze stránky „Nápady pro JARVISe“).

- úklid s náhledem: nic se nemaže hned – soubory jdou do „karantény“ JARVISe, vše jde vrátit, po 30 dnech pryč (81)
- rozložení oken hlasem: „prohlížeč doleva a Discord doprava“ (82)
- přesun programu na jiný disk: složka se přesune a na starém místě zůstane odkaz (junction), program nic nepozná (83)
- ovladače grafiky: oficiální aplikace výrobce přes winget (84), licence programů (85)
- RGB přes OpenRGB (86), bod obnovy před velkou změnou samo (87), křivka ventilátorů přes FanControl (89)
- písma: co je za písmo na obrázku, instalace písma (90), vypnutí za … s odpočtem v notchi (91)
- výchozí aplikace (92), proč netiskne tiskárna (93), režim prezentace (94), uložená Wi-Fi hesla (95)
- přenos na nové PC: seznam programů + nastavení JARVISe (96), virtuální plochy (97), profily monitorů (98)
- snímek s šipkou a poznámkou (99), jazyk klávesnice podle aplikace (100)
Everything Windows-only runs through a runner the tests replace; on other systems it says so instead of failing.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)
WIN = sys.platform == "win32"
Runner = Callable[[list[str], int], subprocess.CompletedProcess]


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def ps(script: str, runner: Runner | None = None, timeout: int = 60) -> str:
    out = (runner or run)(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)
    return (out.stdout or "").strip()


def ps_json(script: str, runner: Runner | None = None, timeout: int = 60) -> Any:
    txt = ps(script + " | ConvertTo-Json -Depth 4 -Compress", runner, timeout)
    try:
        v = json.loads(txt) if txt else None
    except ValueError:
        return None
    return [v] if isinstance(v, dict) else v


# ------------------------------------------------------------------ (81) úklid s náhledem a vrácením
def quarantine_dir() -> Path:
    from .paths import data_dir

    p = data_dir() / "karantena"
    p.mkdir(parents=True, exist_ok=True)
    return p


TEMP_GLOBS = ("*.tmp", "*.temp", "*.log", "*.dmp", "~*", "*.old", "*.bak")


def clean_candidates(roots: list[Path], older_days: int = 7, now: float | None = None) -> list[dict]:
    """Temporary files older than a week (what would go) – nothing is touched here."""
    now = now or time.time()
    out = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            try:
                if not p.is_file() or now - p.stat().st_mtime < older_days * 86400:
                    continue
                if root.name.lower() not in ("temp", "tmp") and not any(p.match(g) for g in TEMP_GLOBS):
                    continue
                out.append({"path": str(p), "size": p.stat().st_size})
            except OSError:
                continue
            if len(out) >= 5000:
                return out
    return out


def human(n: float) -> str:
    for u in ("B", "kB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u in ("B", "kB") else f"{n:.1f} {u}".replace(".", ",")
        n /= 1024
    return f"{n:.1f} PB"


def clean_apply(items: list[dict]) -> dict:
    """Move them to the quarantine (a batch with a manifest) – "vrať úklid" puts everything back."""
    batch = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bdir = quarantine_dir() / batch
    bdir.mkdir(parents=True, exist_ok=True)
    moved, size = [], 0
    for i, it in enumerate(items):
        src = Path(it["path"])
        if not src.is_file():
            continue
        dst = bdir / f"{i:05d}_{src.name}"
        try:
            shutil.move(str(src), str(dst))
        except OSError as e:
            log.debug("quarantine %s: %s", src, e)
            continue
        moved.append({"from": str(src), "to": str(dst)})
        size += it.get("size", 0)
    (bdir / "manifest.json").write_text(json.dumps({"ts": time.time(), "items": moved}, ensure_ascii=False), encoding="utf-8")
    return {"batch": batch, "moved": len(moved), "size": size}


def clean_undo(batch: str = "") -> dict:
    q = quarantine_dir()
    batches = sorted([p for p in q.iterdir() if (p / "manifest.json").is_file()], reverse=True)
    target = next((b for b in batches if b.name == batch), batches[0] if batches and not batch else None)
    if target is None:
        raise ValueError("Žádný úklid k vrácení nemám.")
    man = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    back = 0
    for it in man["items"]:
        src, dst = Path(it["to"]), Path(it["from"])
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            back += 1
    shutil.rmtree(target, ignore_errors=True)
    return {"batch": target.name, "restored": back}


def purge_quarantine(days: int = 30, now: float | None = None) -> int:
    now = now or time.time()
    n = 0
    for b in quarantine_dir().iterdir():
        man = b / "manifest.json"
        try:
            ts = json.loads(man.read_text(encoding="utf-8"))["ts"] if man.is_file() else b.stat().st_mtime
        except (OSError, ValueError, KeyError):
            continue
        if now - ts > days * 86400:
            shutil.rmtree(b, ignore_errors=True)
            n += 1
    return n


# ------------------------------------------------------------------ (82) rozložení oken hlasem
SIDES = {"doleva": "left", "vlevo": "left", "nalevo": "left", "doprava": "right", "vpravo": "right", "napravo": "right",
         "nahoru": "top", "nahore": "top", "dolu": "bottom", "dole": "bottom", "na celou": "full", "pres celou": "full",
         "doprostred": "center", "do stredu": "center", "na stred": "center"}
APP_WORDS = {"prohlizec": ("chrome", "edge", "firefox", "opera", "brave"), "browser": ("chrome", "edge", "firefox", "opera", "brave"),
             "hudba": ("spotify",), "poznamky": ("notepad", "obsidian", "onenote"), "posta": ("outlook", "thunderbird", "mail")}


def parse_layout(text: str) -> list[tuple[str, str]]:
    """"dej prohlížeč doleva a Discord doprava" → [("prohlížeč", "left"), ("Discord", "right")]."""
    t = fold(text)
    t = re.sub(r"^(dej|prehod|presun|posun|umisti|hod)\s+", "", t)
    out = []
    for part in re.split(r"\s+(?:a|,)\s+|,\s*", t):
        for k, side in sorted(SIDES.items(), key=lambda kv: -len(kv[0])):
            m = re.search(rf"^(?:okno\s+)?(.+?)\s+{k}\b", part)
            if m:
                out.append((m.group(1).strip(), side))
                break
    return out


def rect_for(side: str, mon: dict) -> tuple[int, int, int, int]:
    x, y, w, h = mon["left"], mon["top"], mon["width"], mon["height"]
    return {"left": (x, y, w // 2, h), "right": (x + w // 2, y, w - w // 2, h), "top": (x, y, w, h // 2),
            "bottom": (x, y + h // 2, w, h - h // 2), "center": (x + w // 6, y + h // 8, w * 2 // 3, h * 3 // 4)}.get(side, (x, y, w, h))


def find_window(windows: list[dict], name: str) -> dict | None:
    n = fold(name)
    alts = APP_WORDS.get(n.split()[0] if n else "", ())
    for w in windows:
        hay = fold(f"{w.get('app', '')} {w.get('exe', '')} {w.get('title', '')}")
        if n and (n in hay or any(a in hay for a in alts)):
            return w
    return None


# ------------------------------------------------------------------ (83) přesun programu
def move_program(src: Path, dest_root: Path, runner: Runner | None = None, running: Callable[[Path], bool] | None = None) -> dict:
    """The program's folder goes to the other disk; a junction at the old place keeps every shortcut and update
    working. Refused while the program runs."""
    src = src.resolve()
    if not src.is_dir():
        raise ValueError(f"Složku {src} nenacházím.")
    if running and running(src):
        raise ValueError("Program teď běží – zavři ho a zkus to znovu.")
    dst = dest_root / src.name
    if dst.exists():
        raise ValueError(f"V cíli už {dst} existuje.")
    need = sum(p.stat().st_size for p in src.rglob("*") if p.is_file())
    free = shutil.disk_usage(dest_root if dest_root.exists() else dest_root.anchor or ".").free
    if need * 1.1 > free:
        raise ValueError(f"Na cílovém disku není místo ({human(need)} potřeba, volno {human(free)}).")
    dest_root.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    if WIN or runner is not None:
        out = (runner or run)(["cmd", "/c", "mklink", "/J", str(src), str(dst)], 30)
        if out.returncode != 0:
            shutil.move(str(dst), str(src))           # could not link: everything back as it was
            raise RuntimeError(f"Odkaz se nevytvořil, vrátil jsem program zpět: {(out.stdout or out.stderr or '').strip()[:200]}")
    else:
        os.symlink(dst, src, target_is_directory=True)
    return {"from": str(src), "to": str(dst), "size": need}


# ------------------------------------------------------------------ (84) ovladače grafiky
VENDOR_APPS = {"nvidia": "NVIDIA App", "amd": "AMD Software Adrenalin", "intel": "Intel Driver & Support Assistant"}


def gpu_vendor(name: str) -> str:
    n = fold(name)
    return "nvidia" if "nvidia" in n or "geforce" in n or "rtx" in n else "amd" if "amd" in n or "radeon" in n else \
        "intel" if "intel" in n or "arc" in n else ""


def winget_candidates(text: str) -> list[dict]:
    """`winget search` output → [{name, id}] (the table after the dashes line)."""
    out, started = [], False
    for ln in (text or "").splitlines():
        if re.match(r"^-{5,}", ln.strip()):
            started = True
            continue
        if not started or not ln.strip():
            continue
        parts = re.split(r"\s{2,}", ln.strip())
        if len(parts) >= 2:
            out.append({"name": parts[0], "id": parts[1]})
    return out


# ------------------------------------------------------------------ (85) licence programů
def windows_key(runner: Runner | None = None) -> str:
    k = ps("(Get-CimInstance -ClassName SoftwareLicensingService).OA3xOriginalProductKey", runner)
    return k if re.fullmatch(r"[A-Z0-9]{5}(-[A-Z0-9]{5}){4}", k or "") else ""


def _vault_key() -> bytes:
    import base64
    import hashlib

    from . import secrets

    k = secrets.get("license_vault")
    if not k:
        from cryptography.fernet import Fernet

        k = Fernet.generate_key().decode()
        secrets.set("license_vault", k)
    return base64.urlsafe_b64encode(hashlib.sha256(k.encode()).digest())


def license_add(rt: Any, product: str, key: str, note: str = "") -> int:
    from cryptography.fernet import Fernet

    rt.db.exec("CREATE TABLE IF NOT EXISTS pc_licenses (id INTEGER PRIMARY KEY AUTOINCREMENT, product TEXT, secret TEXT, note TEXT, ts REAL)")
    enc = Fernet(_vault_key()).encrypt(key.strip().encode()).decode()
    return int(rt.db.exec("INSERT INTO pc_licenses(product, secret, note, ts) VALUES (?,?,?,?)",
                          (product.strip(), enc, note, time.time())).lastrowid)


def licenses(rt: Any, reveal: bool = False) -> list[dict]:
    from cryptography.fernet import Fernet, InvalidToken

    rt.db.exec("CREATE TABLE IF NOT EXISTS pc_licenses (id INTEGER PRIMARY KEY AUTOINCREMENT, product TEXT, secret TEXT, note TEXT, ts REAL)")
    f = Fernet(_vault_key())
    out = []
    for r in rt.db.all("SELECT * FROM pc_licenses ORDER BY product"):
        try:
            k = f.decrypt(r["secret"].encode()).decode()
        except InvalidToken:
            k = "?"
        out.append({"id": r["id"], "product": r["product"], "key": k if reveal else (k[:4] + "…" + k[-4:] if len(k) > 10 else "••••"),
                    "note": r["note"]})
    return out


# ------------------------------------------------------------------ (86) RGB, (89) ventilátory
def find_exe(names: tuple[str, ...], extra: tuple[str, ...] = ()) -> str:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", "")):
        for sub in extra:
            p = Path(base) / sub
            if base and p.is_file():
                return str(p)
    return ""


MOOD_COLORS = {"klid": "0050FF", "soustredeni": "FFFFFF", "hra": "FF0000", "party": "", "noc": "FF6A00", "vypnout": "000000",
               "zelena": "00FF40", "modra": "0050FF", "cervena": "FF0000", "bila": "FFFFFF", "fialova": "8A2BE2", "oranzova": "FF6A00"}


def rgb_command(what: str, exe: str) -> list[str]:
    w = fold(what)
    if w in ("party", "duha", "rainbow"):
        return [exe, "--mode", "rainbow"]
    if re.fullmatch(r"#?[0-9a-f]{6}", w):
        return [exe, "--mode", "static", "--color", w.lstrip("#").upper()]
    col = next((v for k, v in MOOD_COLORS.items() if w.startswith(k[:5])), "")
    if col == "":
        return [exe, "--profile", what]
    return [exe, "--mode", "static", "--color", col]


def fan_configs(folder: Path) -> list[str]:
    return sorted(p.stem for p in folder.glob("*.json")) if folder.is_dir() else []


# ------------------------------------------------------------------ (87) bod obnovy před změnou
SYSTEM_CHANGES = {"app_install", "app_uninstall", "service_start_type", "driver_rollback_check", "windows_updates", "registry_set",
                  "power_plan_set", "startup_app_set", "pc_migrate"}


def auto_restore_point(rt: Any, tool: str, runner: Callable | None = None, now: float | None = None) -> str:
    """Before a big change of the system: a restore point (at most one a day – Windows' own limit)."""
    if tool not in SYSTEM_CHANGES or not getattr(getattr(rt.cfg, "pc", None), "auto_restore", True):
        return ""
    now = now or time.time()
    row = rt.db.one("SELECT v FROM kv WHERE k='pcx_restore_ts'")
    if row and now - float(row["v"]) < 23 * 3600:
        return ""
    from . import rescue

    ok, msg = rescue.create_restore_point(f"JARVIS před {tool}", **({"runner": runner} if runner else {}))
    if ok:
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('pcx_restore_ts', ?)", (str(now),))
        return "Vytvořil jsem bod obnovy."
    return ""


# ------------------------------------------------------------------ (90) písma
FONT_PROMPT = ("Na obrázku je text. Jaké je to písmo (font)? Odpověz JSON {\"font\": \"nejpravděpodobnější název\", "
               "\"similar_free\": [\"až 3 podobná písma zdarma z Google Fonts\"]}. Když nevíš, font prázdný.")


def install_font(src: Path) -> Path:
    """Copy a .ttf / .otf for this user (no admin) and register it (Windows: HKCU Fonts)."""
    if src.suffix.lower() not in (".ttf", ".otf"):
        raise ValueError("Písmo musí být soubor .ttf nebo .otf.")
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / ("Microsoft/Windows/Fonts" if WIN else "fonts")
    base.mkdir(parents=True, exist_ok=True)
    dst = base / src.name
    shutil.copy2(src, dst)
    if WIN:                                                     # pragma: no cover – Windows
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Fonts", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, f"{src.stem} (TrueType)", 0, winreg.REG_SZ, str(dst))
    return dst


# ------------------------------------------------------------------ (91) vypnutí za …
def shutdown_in(minutes: int, runner: Runner | None = None) -> float:
    secs = max(60, min(int(minutes), 24 * 60) * 60)
    (runner or run)(["shutdown", "/s", "/t", str(secs)], 15)
    return time.time() + secs


def shutdown_cancel(runner: Runner | None = None) -> None:
    (runner or run)(["shutdown", "/a"], 15)


# ------------------------------------------------------------------ (92) výchozí aplikace
EXT_WORDS = {"pdf": ".pdf", "obrazky": ".jpg", "fotky": ".jpg", "video": ".mp4", "videa": ".mp4", "hudba": ".mp3", "hudbu": ".mp3",
             "odkazy": "http", "web": "http", "prohlizec": "http", "maily": "mailto", "e-maily": "mailto", "texty": ".txt", "zip": ".zip"}


def default_app_target(text: str) -> str:
    t = fold(text)
    m = re.search(r"\.(\w{2,5})\b", t)
    if m:
        return "." + m.group(1)
    return next((v for k, v in EXT_WORDS.items() if re.search(rf"\b{k}\b", t)), "")


# ------------------------------------------------------------------ (93) tiskárna
JOB_ERR = re.compile(r"error|chyb|offline|paper|papir|jam|zasek|blocked|user intervention|deleting", re.I)


def printer_diagnose(printers: list[dict], jobs: list[dict]) -> list[str]:
    """What is wrong, in words: offline, a stuck job, paper, no default printer."""
    out = []
    if not printers:
        return ["Windows nevidí žádnou tiskárnu – je zapnutá a připojená? Ovladač nainstaluješ v Nastavení → Tiskárny."]
    default = [p for p in printers if p.get("Default") or p.get("IsDefault")]
    if not default:
        out.append("Není nastavená výchozí tiskárna.")
    for p in printers:
        st = str(p.get("PrinterStatus", "")).lower()
        if st in ("offline", "7", "error", "1") or p.get("WorkOffline"):
            out.append(f"„{p.get('Name')}“ je offline – zkontroluj zapnutí a Wi-Fi/USB, případně vypni „Používat offline“.")
    stuck = [j for j in jobs if JOB_ERR.search(str(j.get("JobStatus", "")))]
    if stuck:
        out.append(f"Zaseknutá fronta: {len(stuck)} úloh ({stuck[0].get('DocumentName', '')}) – vyčistím frontu a restartuji tiskovou službu.")
    return out or ["Tiskárna i fronta vypadají v pořádku – zkus vytisknout zkušební stránku."]


# ------------------------------------------------------------------ (95) Wi-Fi hesla
def wifi_profiles(text: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"(?:All User Profile|Profil všech uživatelů|Profil vsech uzivatelu)\s*:\s*(.+)", text)]


def wifi_key(text: str) -> str:
    m = re.search(r"(?:Key Content|Obsah klíče|Obsah klice)\s*:\s*(.+)", text)
    return m.group(1).strip() if m else ""


# ------------------------------------------------------------------ (96) přenos na nové PC
def migration_pack(rt: Any, folder: Path, runner: Runner | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    apps = folder / "programy-winget.json"
    (runner or run)(["winget", "export", "-o", str(apps), "--accept-source-agreements"], 300)
    from . import config

    (folder / "nastaveni-jarvis.json").write_text(json.dumps(config.public_dump(rt.cfg, local=True), ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
    (folder / "README.txt").write_text("Na novém PC: nainstaluj JARVIS a řekni mu „nainstaluj programy ze starého PC“ – vybere tuhle složku.\n",
                                       encoding="utf-8")
    return folder


def migration_apps(folder: Path) -> list[str]:
    f = folder / "programy-winget.json"
    if not f.is_file():
        return []
    d = json.loads(f.read_text(encoding="utf-8"))
    return [p["PackageIdentifier"] for s in d.get("Sources", []) for p in s.get("Packages", [])]


# ------------------------------------------------------------------ (97) virtuální plochy
def desktop_index(ids_blob: bytes, current: bytes) -> tuple[int, int]:
    """(current 1-based, count) from the registry's VirtualDesktopIDs (16 bytes each) and CurrentVirtualDesktop."""
    ids = [ids_blob[i:i + 16] for i in range(0, len(ids_blob), 16)]
    return (ids.index(current) + 1 if current in ids else 1), max(1, len(ids))


def desktop_keys(cur: int, want: int) -> list[str]:
    if want == cur:
        return []
    return ["win+ctrl+right" if want > cur else "win+ctrl+left"] * abs(want - cur)


# ------------------------------------------------------------------ (98) profily monitorů
def monitor_of(mons: list[dict], x: int, y: int) -> int | None:
    """The 0-based index (in the order Windows lists the screens) of the monitor under a point."""
    for i, m in enumerate(mons):
        if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
            return i
    return None


def monitor_signature(mons: list[dict]) -> str:
    return "|".join(sorted(f"{m.get('width')}x{m.get('height')}" for m in mons))


# ------------------------------------------------------------------ (99) snímek s poznámkou
def annotate(png: bytes, text: str = "", arrow: tuple[int, int, int, int] | None = None, crop: tuple[int, int, int, int] | None = None,
             color: str = "#ff3b30") -> bytes:
    """A cut-out of the screen with an arrow and a caption (Pillow)."""
    import io
    import math

    from PIL import Image, ImageDraw, ImageFont

    im = Image.open(io.BytesIO(png)).convert("RGB")
    if crop:
        x, y, w, h = crop
        im = im.crop((x, y, x + w, y + h))
    d = ImageDraw.Draw(im)
    if arrow:
        x1, y1, x2, y2 = arrow
        d.line((x1, y1, x2, y2), fill=color, width=max(3, im.width // 200))
        ang = math.atan2(y2 - y1, x2 - x1)
        L = max(14, im.width // 40)
        for s in (-0.5, 0.5):
            d.line((x2, y2, x2 - L * math.cos(ang + s), y2 - L * math.sin(ang + s)), fill=color, width=max(3, im.width // 200))
    if text:
        try:
            font = ImageFont.truetype("arial.ttf", max(14, im.width // 40))
        except OSError:
            font = ImageFont.load_default()
        pad = 8
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.rectangle((pad, im.height - th - 3 * pad, pad * 3 + tw, im.height - pad), fill=(20, 20, 24))
        d.text((pad * 2, im.height - th - 2 * pad), text, fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# ------------------------------------------------------------------ (100) jazyk klávesnice podle aplikace
LAYOUTS = {"cs": "00000405", "en": "00000409", "sk": "0000041B", "de": "00000407", "pl": "00000415", "uk": "00000422"}


def layout_for(app: str, mapping: dict[str, str]) -> str:
    a = fold(app)
    for k, v in mapping.items():
        if fold(k) and fold(k) in a:
            return LAYOUTS.get(v.lower()[:2], v)
    return ""


def switch_layout(klid: str) -> bool:                    # pragma: no cover – Windows
    if not WIN or not klid:
        return False
    import ctypes

    u = ctypes.windll.user32
    hkl = u.LoadKeyboardLayoutW(klid, 1)
    hwnd = u.GetForegroundWindow()
    u.PostMessageW(hwnd, 0x0050, 0, hkl)                 # WM_INPUTLANGCHANGEREQUEST
    return bool(hkl)


async def desktop_loop(rt: Any) -> None:                 # pragma: no cover – Windows
    """(100) the keyboard language per app, (98) the monitor layout per set of monitors, (118) a ring around the
    cursor while you share your screen, (113) music bars above the taskbar."""
    import asyncio

    from . import lookx, overlayfx

    last, sig, n = "", "", 0
    while True:
        await asyncio.sleep(1.0)
        n += 1
        pc = getattr(rt.cfg, "pc", None)
        app_cfg = rt.cfg.appearance
        mapping = getattr(pc, "keyboard_by_app", {}) or {}
        info: dict = {}
        if mapping:     # only when a keyboard per app is set – and off the event loop (a process lookup can stall)
            try:
                info = await asyncio.to_thread(rt.platform.foreground_info) or {}
            except Exception:  # noqa: BLE001
                info = {}
        app = info.get("app", "")
        if mapping and app and app != last:
            last = app
            klid = layout_for(app, mapping)
            if klid:
                await asyncio.to_thread(switch_layout, klid)
        if n % 10 == 0 and getattr(pc, "monitor_profiles", None):
            try:
                cur = monitor_signature(await asyncio.to_thread(rt.platform.monitors))
            except Exception:  # noqa: BLE001
                cur = sig
            if cur != sig:
                sig = cur
                prof = pc.monitor_profiles.get(cur)
                exe = find_exe(("MultiMonitorTool", "MultiMonitorTool.exe"), ("MultiMonitorTool/MultiMonitorTool.exe",))
                if prof and exe:
                    from .paths import data_dir

                    await asyncio.to_thread(run, [exe, "/LoadConfig", str(data_dir() / "monitory" / f"{prof}.cfg")], 30)
        if getattr(app_cfg, "share_ring", True) and n % 2 == 0:
            try:
                titles = await asyncio.to_thread(rt.platform.list_windows)
            except Exception:  # noqa: BLE001
                titles = []
            if lookx.sharing_screen(titles):
                x, y = rt.platform.cursor_pos()
                overlayfx.emit(rt, "ring", x=x, y=y)
        if getattr(rt.cfg.notch, "all_monitors", False) and n % 2 == 0:   # (110) the notch goes where you work
            try:
                from .desktop import platforms as _pl

                x, y = rt.platform.cursor_pos()
                mons = [{"left": r[0].x, "top": r[0].y, "width": r[0].w, "height": r[0].h}      # the host's own order
                        for r in await asyncio.to_thread(_pl.monitors)]
            except Exception:  # noqa: BLE001
                mons = []
            idx = monitor_of(mons, x, y) if mons else None
            prev = getattr(rt, "_cursor_mon", None)
            rt._cursor_mon = idx
            if idx is not None and idx == prev and idx != getattr(rt, "notch_monitor_follow", None):
                hook = getattr(rt, "on_notch_monitor", None)
                if hook is not None:
                    hook(idx)
                rt.bus.publish("notch_active", monitor=idx + 1)
        bars = getattr(rt, "music_bars", None)
        if getattr(app_cfg, "taskbar_eq", False) and bars and time.time() - getattr(rt, "music_bars_at", 0) < 2 and n % 2 == 0:
            overlayfx.emit(rt, "eq", bars=list(bars))
