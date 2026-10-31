"""OMEGA §32 security utilities: is this link a phishing trap (397), is this downloaded file safe (398), are there
leaked keys in my code (401), was this password in a known leak (396), is my copy identical (700)."""
from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from .pcreport import run_quiet

SUSPICIOUS_TLDS = {"zip", "mov", "top", "xyz", "click", "loan", "work", "gq", "tk", "ml", "cf", "ga", "rest", "cam", "country"}
BRANDS = {"paypal", "apple", "microsoft", "google", "facebook", "instagram", "seznam", "csob", "kb", "fio", "airbank", "moneta",
          "rb", "raiffeisen", "ceskasporitelna", "george", "alza", "mall", "zasilkovna", "ppl", "dpd", "postaonline", "ceskaposta",
          "netflix", "amazon", "ebay", "binance", "revolut", "o2", "vodafone", "tmobile", "steam", "discord", "whatsapp"}
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "cutt.ly", "rb.gy", "shorturl.at"}


def check_link(url: str) -> dict:
    """Offline heuristics (nothing is opened): IP host, punycode, look-alike brand, many subdomains, shorteners…"""
    u = url.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I):
        u = "http://" + u
    p = urlparse(u)
    host = (p.hostname or "").lower()
    reasons, score = [], 0
    if p.scheme == "http":
        reasons.append("nešifrované spojení (http)")
        score += 1
    try:
        ipaddress.ip_address(host)
        reasons.append("místo názvu webu je jen IP adresa")
        score += 3
    except ValueError:
        pass
    if "xn--" in host:
        reasons.append("název obsahuje zakódované znaky (punycode) – může napodobovat jiný web")
        score += 3
    if "@" in (p.netloc or ""):
        reasons.append("adresa obsahuje @ – skutečný cíl je až za ním")
        score += 3
    parts = host.split(".")
    tld = parts[-1] if parts else ""
    if tld in SUSPICIOUS_TLDS:
        reasons.append(f"neobvyklá koncovka .{tld}")
        score += 1
    if len(parts) > 4:
        reasons.append("hodně poddomén")
        score += 1
    reg = ".".join(parts[-2:]) if len(parts) >= 2 else host
    if host in SHORTENERS or reg in SHORTENERS:
        reasons.append("zkracovač odkazů – skutečný cíl není vidět")
        score += 1
    flat = re.sub(r"[^a-z0-9]", "", host)
    for b in BRANDS:
        if b in flat and not (reg.startswith(b + ".") or reg.replace("-", "").startswith(b)):
            reasons.append(f"obsahuje „{b}“, ale hlavní doména je {reg}")
            score += 3
            break
    if re.search(r"(login|signin|verify|ověř|overeni|update|secure|account|ucet|platba|payment)", (p.path + p.query).lower()) and score:
        reasons.append("vede na přihlášení/ověření účtu")
        score += 1
    level = "ok" if score == 0 else "warn" if score < 3 else "bad"
    return {"url": url, "host": host, "domain": reg, "score": score, "level": level, "reasons": reasons}


MAGIC = {b"MZ": "program pro Windows (.exe/.dll)", b"%PDF": "PDF", b"PK\x03\x04": "ZIP (i .docx/.xlsx)", b"\x89PNG": "obrázek PNG",
         b"\xff\xd8\xff": "obrázek JPEG", b"Rar!": "RAR", b"7z\xbc\xaf": "7-Zip", b"{\\rtf": "RTF", b"\xd0\xcf\x11\xe0": "starý dokument Office"}
RISKY_EXT = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jse", ".scr", ".com", ".pif", ".hta", ".lnk", ".iso", ".img", ".dll", ".jar"}


def check_file(path: str) -> dict:
    """OMEGA 398: where it came from (Zone.Identifier), what it really is (magic bytes vs extension), signature, SHA-256."""
    p = Path(path).expanduser()
    if not p.is_file():
        return {"error": f"Soubor neexistuje: {p}"}
    head = p.read_bytes()[:8]
    kind = next((v for k, v in MAGIC.items() if head.startswith(k)), "")
    ext = p.suffix.lower()
    reasons = []
    if p.name.count(".") >= 2 and ext in RISKY_EXT:
        reasons.append(f"dvojitá přípona ({p.name}) – typický trik")
    if kind.startswith("program") and ext not in (".exe", ".dll", ".msi", ".scr", ".com", ".sys"):
        reasons.append(f"tváří se jako {ext}, ale je to {kind}")
    if ext in RISKY_EXT:
        reasons.append(f"spustitelný typ souboru ({ext})")
    origin = ""
    try:
        with open(str(p) + ":Zone.Identifier", encoding="utf-8", errors="ignore") as f:
            z = f.read()
        m = re.search(r"HostUrl=(.+)", z)
        origin = m.group(1).strip() if m else "z internetu"
    except OSError:
        pass
    sig = ""
    if sys.platform == "win32" and ext in (".exe", ".dll", ".msi", ".ps1", ".sys", ".scr"):
        lit = str(p).replace("'", "''")
        _c, out, _e = run_quiet(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                                 f"(Get-AuthenticodeSignature -LiteralPath '{lit}') | ForEach-Object {{ \"$($_.Status)|$($_.SignerCertificate.Subject)\" }}"], 20)
        sig = out.strip()
        if sig and not sig.startswith("Valid"):
            reasons.append("program nemá platný digitální podpis")
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    level = "bad" if any("tváří" in r or "dvojitá" in r for r in reasons) else "warn" if reasons else "ok"
    return {"path": str(p), "bytes": p.stat().st_size, "type": kind or "neznámý", "origin": origin, "signature": sig,
            "sha256": h.hexdigest(), "reasons": reasons, "level": level}


def defender_scan(path: str) -> dict:
    """A read-only Microsoft Defender scan of one file or folder (MpCmdRun -Scan -ScanType 3)."""
    if sys.platform != "win32":
        return {"error": "jen na Windows"}
    exe = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Defender" / "MpCmdRun.exe"
    if not exe.is_file():
        return {"error": "Microsoft Defender není k dispozici"}
    code, out, err = run_quiet([str(exe), "-Scan", "-ScanType", "3", "-File", str(Path(path)), "-DisableRemediation"], 600)
    if code is None:
        return {"error": "kontrola trvala moc dlouho"}
    found = re.findall(r"Threat\s*:\s*(.+)", out)
    return {"clean": code == 0 and not found, "threats": found, "exit": code, "output": out[-600:]}


SECRET_PATTERNS = [
    ("OpenAI / Anthropic klíč", r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"),
    ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    ("AWS přístupový klíč", r"\bAKIA[0-9A-Z]{16}\b"),
    ("Google API klíč", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("Stripe klíč", r"\b[sr]k_live_[A-Za-z0-9]{20,}"),
    ("soukromý klíč", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ("heslo v kódu", r"(?i)\b(password|passwd|heslo|secret|api_key|apikey|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"),
]
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".idea"}
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".env", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".txt", ".md",
            ".java", ".kt", ".cs", ".go", ".rb", ".php", ".sh", ".ps1", ".bat", ".xml", ".properties", ".conf", ""}


def scan_secrets(folder: str, max_files: int = 5000) -> list[dict]:
    """OMEGA 401: leaked keys/passwords in a project folder. The secret itself is never returned, only its start."""
    root = Path(folder).expanduser()
    hits = []
    n = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            p = Path(dirpath) / name
            if p.suffix.lower() not in TEXT_EXT or n >= max_files:
                continue
            n += 1
            try:
                if p.stat().st_size > 2_000_000:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for kind, rx in SECRET_PATTERNS:
                for m in re.finditer(rx, text):
                    line = text.count("\n", 0, m.start()) + 1
                    hits.append({"file": str(p.relative_to(root)), "line": line, "kind": kind, "preview": m.group(0)[:6] + "…"})
    return hits


async def pwned_count(rt, password: str) -> int:
    """OMEGA 396: Have I Been Pwned "range" API – only the first 5 characters of the SHA-1 leave the PC."""
    sha = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    async with rt.http() as c:
        r = await c.get(f"https://api.pwnedpasswords.com/range/{sha[:5]}", headers={"Add-Padding": "true"}, timeout=10)
    r.raise_for_status()
    for line in r.text.splitlines():
        suf, _, cnt = line.partition(":")
        if suf.strip() == sha[5:]:
            return int(cnt.strip() or 0)
    return 0


def verify_copy(src: str, dst: str, max_files: int = 200000) -> dict:
    """OMEGA 700 / 329: is the copy (or clone, or backup) bit-for-bit the same? SHA-256 of every file."""
    a, b = Path(src).expanduser(), Path(dst).expanduser()

    def digest(p: Path) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    if a.is_file():
        same = b.is_file() and digest(a) == digest(b)
        return {"files": 1, "same": int(same), "different": [] if same else [a.name], "missing": [] if b.exists() else [a.name]}
    missing, diff, same, n = [], [], 0, 0
    for p in a.rglob("*"):
        if not p.is_file():
            continue
        n += 1
        if n > max_files:
            break
        rel = p.relative_to(a)
        q = b / rel
        if not q.is_file():
            missing.append(str(rel))
        elif p.stat().st_size != q.stat().st_size or digest(p) != digest(q):
            diff.append(str(rel))
        else:
            same += 1
    return {"files": n, "same": same, "different": diff[:200], "missing": missing[:200]}


def rescue_plan(rt) -> list[dict]:
    """OMEGA 300 / 699 / 703: when a disk is failing – what to save first (your folders, newest and smallest first)."""
    home = Path.home()
    cands = ["Desktop", "Documents", "Pictures", "Downloads", "Videos", "Music", "OneDrive"]
    out = []
    for c in cands:
        p = home / c
        if not p.is_dir():
            continue
        size, newest, files = 0, 0.0, 0
        for root, dirs, fs in os.walk(p):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in fs:
                try:
                    st = (Path(root) / f).stat()
                except OSError:
                    continue
                size += st.st_size
                files += 1
                newest = max(newest, st.st_mtime)
            if files > 200000:
                break
        out.append({"folder": str(p), "bytes": size, "files": files, "newest": newest})
    # what you worked on lately and is small goes first – the most value per minute of a dying disk
    out.sort(key=lambda x: (-x["newest"], x["bytes"]))
    return out


def recovery_odds(probe: dict) -> list[dict]:
    """OMEGA 703: a rough chance of getting the data off each disk, from what Windows reports (health, read / write
    errors, bad-sector and timeout events, wear). An estimate with the reasons – not a promise."""
    from .rescue import L

    rel = {str(r.get("DeviceId")): r for r in L(probe.get("reliability"))}
    ev = L(probe.get("io_events"))
    bad_sectors = sum(1 for e in ev if int(e.get("Id") or 0) in (7, 51, 153))
    timeouts = sum(1 for e in ev if int(e.get("Id") or 0) in (129, 11))
    out = []
    for p in L(probe.get("physical")):
        r = rel.get(str(p.get("DeviceId"))) or {}
        name = p.get("FriendlyName") or "disk"
        health, status = str(p.get("Health") or ""), str(p.get("Status") or "")
        errs = (r.get("ReadErrors") or 0) + (r.get("WriteErrors") or 0)
        why, lo, hi = [], 95, 100
        if health not in ("", "Healthy", "0"):
            lo, hi = min(lo, 50), min(hi, 85)
            why.append(f"Windows hlásí stav {health}")
        if status and status.lower() not in ("ok", "online", "2"):
            lo, hi = min(lo, 30), min(hi, 60)
            why.append(f"disk je ve stavu {status}")
        if errs:
            lo, hi = (min(lo, 70), min(hi, 90)) if errs < 50 else (min(lo, 40), min(hi, 70))
            why.append(f"{errs} chyb čtení/zápisu")
        if bad_sectors:
            lo, hi = (min(lo, 70), min(hi, 90)) if bad_sectors < 20 else (min(lo, 40), min(hi, 75))
            why.append(f"{bad_sectors}× vadné sektory v logu")
        if (r.get("Wear") or 0) >= 100:
            why.append("SSD je opotřebené na 100 % – často přejde jen do čtení, to je pro záchranu dobře")
        if timeouts and not errs and not bad_sectors:
            why.append(f"{timeouts}× timeout řadiče – často jen kabel nebo napájení")
        level = "vysoká" if lo >= 85 else "střední" if lo >= 50 else "nízká"
        advice = ("Kopíruj hned, nejnovější a nejmenší soubory první." if level == "vysoká" else
                  "Kopíruj jen to nejcennější, disk zbytečně nezatěžuj a nic na něj nezapisuj." if level == "střední" else
                  "Pokud disk cvaká nebo ho systém přestává vidět, vypni ho a obrať se na firmu na záchranu dat – každé další "
                  "zapnutí může šanci snížit.")
        out.append({"disk": name, "level": level, "percent": f"{lo}–{hi} %", "reasons": why or ["žádné známky poškození"],
                    "advice": advice})
    return out
