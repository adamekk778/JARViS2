"""3.20 Bezpečnost+ (nápady 181–200 ze stránky „Nápady pro JARVISe“).

- měsíční audit oprávnění (181), návnadové soubory (182), soubory sdílené odkazem pro kohokoli (183)
- účty bez dvoufázového ověření (184), šifrovaná záloha klíčů na flashku (185), podvodné SMS a hovory – i pro rodiče
  (186, 188), cizí člověk u PC zamkne obrazovku (187), druhý model kontroluje nebezpečné kroky (189)
- kdo zapnul kameru nebo mikrofon (190), tresor dokumentů (191), kontrola stažených souborů (192)
- časový zámek akcí (193), neměnný záznam schválení (194), heslo odkazem, který zmizí (195), YubiKey (196)
- vymazání stop (197), kontrola routeru (198), rozšíření prohlížeče (199), bezpečnostní test jedním klikem (200)
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets as pysecrets
import socket
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sx_audit (n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, who TEXT, action TEXT, approved INT, prev TEXT, h TEXT);
CREATE TABLE IF NOT EXISTS sx_canary (token TEXT PRIMARY KEY, path TEXT, kind TEXT, ts REAL, hits INT DEFAULT 0, last_hit REAL);
CREATE TABLE IF NOT EXISTS sx_vault (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, tags TEXT, words TEXT, file TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS sx_oneshot (token TEXT PRIMARY KEY, blob TEXT, until REAL, ts REAL);
CREATE TABLE IF NOT EXISTS sx_2fa (service TEXT PRIMARY KEY, on2fa INT, ts REAL);
"""


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def db(rt: Any):
    if not getattr(rt, "_secx_ready", False):
        with rt.db.lock:
            rt.db.conn.executescript(SCHEMA)
            rt.db.conn.commit()
        rt._secx_ready = True
    return rt.db


def _cfg(rt: Any) -> Any:
    return getattr(rt.cfg, "secx", None)


def _get(rt: Any, name: str, default: Any = None) -> Any:
    c = _cfg(rt)
    return getattr(c, name, default) if c is not None else default


def _fernet(key_name: str):
    from cryptography.fernet import Fernet

    from . import secrets

    k = secrets.get(key_name)
    if not k:
        k = Fernet.generate_key().decode()
        secrets.set(key_name, k)
    return Fernet(k.encode())


# ------------------------------------------------------------------ (181) audit oprávnění
def permission_audit(rt: Any, days: int = 30, now: float | None = None) -> dict:
    """What JARVIS may do and what it really used in the last `days` – with what could be switched off."""
    from . import tools
    from .permissions import PERMS, perm_of

    now = now or time.time()
    used: set[str] = set()
    try:
        used = {r["tool"] for r in rt.db.all("SELECT DISTINCT tool FROM tool_uses WHERE ts >= ?", (now - days * 86400,))}
    except Exception:  # noqa: BLE001 – no history yet
        pass
    per: dict[str, int] = {p: 0 for p in PERMS}
    for name in used:
        spec = tools.REGISTRY.get(name)
        if spec is not None:
            p = perm_of(spec)
            if p in per:
                per[p] += 1
    perms = rt.cfg.permissions
    rows = [{"perm": p, "label": label, "on": bool(getattr(perms, p, True)), "used_tools": per[p]} for p, label in PERMS.items()]
    tips = [f"„{r['label']}“ – za {days} dní nepoužito, můžeš vypnout (Nastavení → Oprávnění)." for r in rows if r["on"] and not r["used_tools"]]
    old_devices = [d.name for d in getattr(rt.cfg.phone, "devices", []) or [] if getattr(d, "last_seen", 0) and now - d.last_seen > 60 * 86400]
    tips += [f"Zařízení „{n}“ se 60 dní neozvalo – odvolej ho (Nastavení → Telefon)." for n in old_devices]
    if getattr(rt.cfg.phone_link, "remote_desktop", False):
        tips.append("Vzdálená plocha z telefonu je zapnutá – vypni ji, když ji nepoužíváš.")
    return {"rows": rows, "tips": tips, "days": days}


def audit_text(a: dict) -> str:
    on = [r["label"] for r in a["rows"] if r["on"]]
    lines = [f"JARVIS teď smí: {', '.join(on) or 'nic'}."]
    lines += a["tips"] or ["Všechno zapnuté se opravdu používá – není co omezit."]
    return "\n".join(lines)


# ------------------------------------------------------------------ (182) návnadové soubory
CANARY_NAMES = {"html": "Hesla a PINy.html", "url": "Internetové bankovnictví – přihlášení.url"}


def canary_create(rt: Any, folder: Path, base_url: str) -> list[dict]:
    """Bait files: opening one loads a picture / opens a link on this PC's JARVIS, which tells you at once."""
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for kind, name in CANARY_NAMES.items():
        token = pysecrets.token_urlsafe(12)
        url = f"{base_url.rstrip('/')}/canary/{token}"
        p = folder / name
        if kind == "html":
            p.write_text(f"<!doctype html><meta charset=utf-8><title>Hesla</title><img src=\"{url}.png\" width=1 height=1 alt=\"\">"
                         "<h1>Hesla a PINy</h1><p>Načítání…</p>", encoding="utf-8")
        else:
            p.write_text(f"[InternetShortcut]\r\nURL={url}\r\n", encoding="utf-8")
        db(rt).exec("INSERT INTO sx_canary (token, path, kind, ts) VALUES (?,?,?,?)", (token, str(p), kind, time.time()))
        out.append({"token": token, "path": str(p)})
    return out


def canary_hit(rt: Any, token: str, ip: str = "", agent: str = "") -> bool:
    row = db(rt).one("SELECT path FROM sx_canary WHERE token=?", (token,))
    if not row:
        return False
    db(rt).exec("UPDATE sx_canary SET hits=hits+1, last_hit=? WHERE token=?", (time.time(), token))
    text = f"Někdo otevřel návnadu „{Path(row['path']).name}“" + (f" (z {ip})" if ip else "") + " – někdo se ti hrabe v souborech."
    rt.notify("Návnada spuštěna", text, speak=True, urgent=True)
    rt.phone_push("notify", title="Návnada spuštěna", body=text)
    log_event(rt, ip or "?", f"návnada: {text}", True)
    return True


# ------------------------------------------------------------------ (183) veřejně sdílené soubory
async def public_drive_files(rt: Any, client: Any = None) -> dict:
    """Google Drive: files shared "anyone with the link"; OneDrive: items with an anonymous link (Microsoft Graph)."""
    from . import secrets

    out: dict = {"google": None, "onedrive": None}
    own = client is None
    c = client or rt.http()
    try:
        tok = secrets.get("google_drive_token") or secrets.get("google_token")
        if tok:
            r = await c.get("https://www.googleapis.com/drive/v3/files", headers={"Authorization": f"Bearer {tok}"},
                            params={"q": "visibility = 'anyoneWithLink' or visibility = 'anyoneCanFind'", "pageSize": 200,
                                    "fields": "files(id,name,webViewLink,modifiedTime)"}, timeout=20)
            out["google"] = [{"name": f["name"], "link": f.get("webViewLink", "")} for f in r.json().get("files", [])] if r.status_code == 200 else f"chyba {r.status_code}"
        tok = secrets.get("onedrive_token") or secrets.get("microsoft_token")
        if tok:
            h = {"Authorization": f"Bearer {tok}"}
            r = await c.get("https://graph.microsoft.com/v1.0/me/drive/root/search(q='')", headers=h,
                            params={"$top": 200, "$select": "id,name,webUrl"}, timeout=20)
            items = r.json().get("value", []) if r.status_code == 200 else []
            shared = []
            for it in items[:200]:
                p = await c.get(f"https://graph.microsoft.com/v1.0/me/drive/items/{it['id']}/permissions", headers=h, timeout=15)
                perms = p.json().get("value", []) if p.status_code == 200 else []
                if any((x.get("link") or {}).get("scope") == "anonymous" for x in perms):
                    shared.append({"name": it.get("name", ""), "link": it.get("webUrl", "")})
            out["onedrive"] = shared
    finally:
        if own:
            await c.aclose()
    return out


# ------------------------------------------------------------------ (184) účty bez 2FA
IMPORTANT = {"google": "Google (Gmail, Disk)", "microsoft": "Microsoft (Outlook, OneDrive)", "apple": "Apple ID", "facebook": "Facebook",
             "instagram": "Instagram", "seznam": "Seznam.cz", "github": "GitHub", "paypal": "PayPal", "amazon": "Amazon",
             "steam": "Steam", "discord": "Discord", "revolut": "Revolut", "dropbox": "Dropbox", "x": "X (Twitter)"}
HOWTO = {"google": "myaccount.google.com → Zabezpečení → Dvoufázové ověření", "microsoft": "account.microsoft.com/security → Další možnosti",
         "apple": "Nastavení → tvé jméno → Heslo a zabezpečení", "facebook": "Nastavení → Zabezpečení a přihlášení",
         "instagram": "Nastavení → Centrum účtů → Heslo a zabezpečení", "seznam": "Nastavení účtu → Bezpečnost → Dvoufázové ověření",
         "github": "Settings → Password and authentication", "paypal": "Nastavení → Zabezpečení → Dvoufázové ověření",
         "amazon": "Účet → Přihlášení a zabezpečení → Dvoufázové ověření", "steam": "Steam Guard v mobilní aplikaci",
         "discord": "Uživatelská nastavení → Můj účet → Povolit 2FA", "revolut": "Profil → Zabezpečení",
         "dropbox": "Nastavení → Zabezpečení → Dvoustupňové ověření", "x": "Nastavení → Zabezpečení → Dvoufázové ověření"}


def twofa_mark(rt: Any, service: str, on: bool) -> str:
    key = next((k for k, v in IMPORTANT.items() if fold(service) in (k, fold(v))), fold(service)[:30])
    db(rt).exec("INSERT OR REPLACE INTO sx_2fa VALUES (?,?,?)", (key, 1 if on else 0, time.time()))
    return key


def twofa_report(rt: Any, used: list[str] | None = None) -> dict:
    marks = {r["service"]: bool(r["on2fa"]) for r in db(rt).all("SELECT * FROM sx_2fa")}
    services = used or list(IMPORTANT)
    missing = [s for s in services if not marks.get(s)]
    return {"done": [IMPORTANT.get(s, s) for s in services if marks.get(s)],
            "missing": [{"service": IMPORTANT.get(s, s), "how": HOWTO.get(s, "v nastavení účtu → Zabezpečení")} for s in missing]}


# ------------------------------------------------------------------ (185) šifrovaná záloha klíčů
KEY_NAMES = ("anthropic", "openai", "groq", "gemini", "elevenlabs", "home_assistant", "twilio", "google_token", "google_drive_token",
             "onedrive_token", "license_vault", "doc_vault", "github_token", "liteapi", "yubico_api")


def _kdf(password: str, salt: bytes) -> bytes:
    return base64.urlsafe_b64encode(hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32))


def keys_backup(target: Path, password: str, values: dict[str, str]) -> Path:
    from cryptography.fernet import Fernet

    if len(password) < 10:
        raise ValueError("Heslo zálohy musí mít aspoň 10 znaků.")
    salt = os.urandom(16)
    blob = Fernet(_kdf(password, salt)).encrypt(json.dumps(values).encode())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"v": 1, "salt": base64.b64encode(salt).decode(), "data": blob.decode(),
                                  "made": dt.date.today().isoformat(), "count": len(values)}), encoding="utf-8")
    return target


def keys_restore(source: Path, password: str) -> dict[str, str]:
    from cryptography.fernet import Fernet, InvalidToken

    d = json.loads(source.read_text(encoding="utf-8"))
    try:
        return json.loads(Fernet(_kdf(password, base64.b64decode(d["salt"]))).decrypt(d["data"].encode()))
    except InvalidToken:
        raise ValueError("Špatné heslo zálohy.") from None


def collect_keys() -> dict[str, str]:
    from . import secrets

    return {k: secrets.get(k) for k in KEY_NAMES if secrets.has(k)}


# ------------------------------------------------------------------ (186, 188) podvodné SMS a hovory
SCAM_RULES: list[tuple[str, int, str]] = [
    (r"doplat|doplatek|clo\b|celni|poplatek za doruc", 3, "doplatek / clo za zásilku"),
    (r"balik|zasilk|doruc|ppl|dpd|zasilkovn|ceska posta|dhl|gls", 1, "zásilka"),
    (r"ucet (byl )?(zablokov|pozastav|omezen)|zablokovan|overte (svuj )?ucet|aktualizujte udaje", 3, "zablokovaný účet"),
    (r"vyhral|vyhra|odmena|darek zdarma|gratulujeme", 2, "výhra"),
    (r"mami|tati|ztratil jsem telefon|nove cislo|tohle je moje nove", 3, "„mami, mám nové číslo“"),
    (r"posli mi (penize|kod)|posles mi|potrebuju zaplatit|pujcis mi", 2, "žádost o peníze"),
    (r"bezpecnostni oddeleni|bankovni specialist|presunte penize|bezpecny ucet|policie vas", 4, "falešný bankéř / policie"),
    (r"kryptomen|bitcoin|investic|zhodnoceni", 2, "investice / krypto"),
    (r"(ihned|okamzite|do 24 hodin|dnes do)", 1, "naléhavost"),
    (r"https?://[^\s]*(bit\.ly|tinyurl|t\.co|is\.gd|cutt\.ly|rb\.gy|[a-z0-9-]+\.(top|xyz|click|info|shop|online|live|icu|cfd))", 3, "podezřelý odkaz"),
    (r"https?://\S+", 1, "odkaz"),
    (r"sms kod|overovaci kod|nikomu nesdelujte|zadejte kod", 1, "kód z SMS"),
]


def scam_score(text: str, sender: str = "") -> dict:
    t = fold(text)
    hits, score = [], 0
    for pat, w, label in SCAM_RULES:
        if re.search(pat, t):
            score += w
            hits.append(label)
    s = re.sub(r"[\s-]", "", sender or "")
    if s.startswith("+") and not s.startswith("+420"):
        score += 1
        hits.append("zahraniční číslo")
    if re.fullmatch(r"\+?(?:00)?(?:882|883|870|881)\d+", s):
        score += 2
        hits.append("satelitní / zvláštní číslo")
    level = "high" if score >= 5 else "medium" if score >= 3 else "low"
    return {"score": score, "level": level, "why": hits}


def on_message(rt: Any, item: dict) -> dict | None:
    """A message mirrored from a phone: a likely scam → a warning on that phone (and on the PC for family phones)."""
    if not _get(rt, "scam_check", True) or not item.get("messaging"):
        return None
    r = scam_score(str(item.get("text") or ""), str(item.get("title") or ""))
    if r["level"] != "high":
        return None
    why = ", ".join(dict.fromkeys(r["why"]))[:160]
    body = f"Tahle zpráva vypadá jako podvod ({why}). Na odkaz neklikej, nic neplať a kód nikomu nesděluj. Když si nejsi jistý, zavolej rovnou do banky nebo dopravci."
    rt.phone_push("notify", title="Pozor – podvodná zpráva?", body=body)
    family = _get(rt, "family_devices", []) or []
    dev = str(item.get("device") or "")
    if dev and dev in family:
        rt.notify("Rodina: podvodná zpráva", f"{dev} dostal(a) podezřelou zprávu ({why}). Možná zavolej, ať na nic neklikne.", speak=False)
    return r


# ------------------------------------------------------------------ (187) cizí u PC
def stranger_check(people: list[dict], owners: list[str]) -> str:
    """'' = fine; a reason to lock when someone unknown sits at the PC without you."""
    if not people:
        return ""
    names = {fold(p.get("name", "")) for p in people}
    own = {fold(o) for o in owners}
    if names & own:
        return ""
    return "U počítače je někdo, koho neznám."


async def stranger_tick(rt: Any) -> str:
    if not _get(rt, "stranger_lock", False):
        return ""
    try:
        idle = float(rt.platform.idle_seconds())
    except Exception:  # noqa: BLE001
        idle = 1e9
    if idle > 30:                                      # nobody typing → nothing to check
        return ""
    import asyncio

    from . import faces

    if not faces.models_ready():
        return ""
    res = await asyncio.to_thread(faces.who_is_here, rt)
    owners = _get(rt, "owners", []) or [str(getattr(rt.cfg.general, "user_name", "") or "").split(" ")[0]]
    why = stranger_check(res.get("people", []), [o for o in owners if o])
    if why:
        await asyncio.to_thread(rt.platform.power, "lock")
        rt.phone_push("notify", title="PC zamčeno", body=why + " Obrazovku jsem zamkl.")
        log_event(rt, "stranger_lock", why, True)
    return why


# ------------------------------------------------------------------ (189) druhý model
AUDIT_PROMPT = ("Jsi nezávislý bezpečnostní kontrolor. Asistent se chystá provést akci na počítači uživatele. Posuď jen podle "
                "popisu, jestli je bezpečná a odpovídá běžnému přání uživatele. Odpověz jedním řádkem: „OK – důvod“ nebo "
                "„POZOR – důvod“. Buď stručný.")


async def second_opinion(rt: Any, desc: str, ask: Callable[..., Any] | None = None) -> str:
    """Another model's one-line view of a dangerous step ('' when off or it cannot answer)."""
    if not _get(rt, "second_ai", False):
        return ""
    try:
        if ask is None:
            import asyncio

            only = str(_get(rt, "second_ai_provider", "") or "") or None      # another brain than the one that planned it
            out = await asyncio.wait_for(rt.router.complete([{"role": "system", "content": AUDIT_PROMPT},
                                                             {"role": "user", "content": desc}], fast=True, only=only), 20)
        else:
            out = await ask(desc)
    except Exception as e:  # noqa: BLE001
        log.info("second opinion: %s", e)
        return ""
    line = str(out or "").strip().splitlines()[0][:200] if out else ""
    return line


# ------------------------------------------------------------------ (190) kamera a mikrofon právě teď
def in_use(consent: dict) -> set[str]:
    return {f"{cap}:{a['app']}" for cap, apps in (consent.get("capabilities") or {}).items() if cap in ("kamera", "mikrofon")
            for a in apps if a.get("in_use")}


def media_changes(before: set[str], now_: set[str]) -> list[str]:
    out = []
    for item in sorted(now_ - before):
        cap, app = item.split(":", 1)
        out.append(f"{app} teď používá {cap}.")
    return out


# ------------------------------------------------------------------ (191) tresor dokumentů
def vault_dir(rt: Any) -> Path:
    from . import paths

    d = paths.sub("vault")
    d.mkdir(parents=True, exist_ok=True)
    return d


def vault_add(rt: Any, src: Path, name: str = "", tags: str = "", words: str = "") -> int:
    data = src.read_bytes()
    f = _fernet("doc_vault")
    fname = pysecrets.token_hex(8) + ".bin"
    (vault_dir(rt) / fname).write_bytes(f.encrypt(data))
    cur = db(rt).exec("INSERT INTO sx_vault (name, tags, words, file, ts) VALUES (?,?,?,?,?)",
                      ((name or src.name)[:120], tags[:200], fold(words or "")[:4000], fname, time.time()))
    return int(getattr(cur, "lastrowid", 0) or 0)


def vault_search(rt: Any, query: str) -> list[dict]:
    q = fold(query).split()
    rows = [dict(r) for r in db(rt).all("SELECT id, name, tags, words, ts FROM sx_vault ORDER BY ts DESC")]
    if not q:
        return [{k: r[k] for k in ("id", "name", "tags", "ts")} for r in rows]
    hits = [r for r in rows if all(w in fold(r["name"] + " " + r["tags"] + " " + r["words"]) for w in q)]
    return [{k: r[k] for k in ("id", "name", "tags", "ts")} for r in hits]


def vault_get(rt: Any, vid: int, out_dir: Path) -> Path:
    row = db(rt).one("SELECT * FROM sx_vault WHERE id=?", (int(vid),))
    if not row:
        raise ValueError("Takový dokument v tresoru není.")
    data = _fernet("doc_vault").decrypt((vault_dir(rt) / row["file"]).read_bytes())
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / re.sub(r"[\\/:*?\"<>|]+", "_", row["name"])
    p.write_bytes(data)
    return p


# ------------------------------------------------------------------ (192) stažené soubory
def new_downloads(folder: Path, seen: dict[str, float], now: float | None = None) -> list[Path]:
    """Files that appeared in Downloads and have not changed for 10 s (a download that finished)."""
    now = now or time.time()
    out: list[Path] = []
    if not folder.is_dir():
        return out
    for p in folder.iterdir():
        if not p.is_file() or p.suffix.lower() in (".crdownload", ".part", ".tmp", ".partial") or p.name.startswith("~"):
            continue
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        key = str(p)
        if key in seen:
            continue
        if now - m >= 10:
            seen[key] = m
            out.append(p)
    return out


def download_verdict(check: dict) -> str:
    """secutils.check_file (+ "defender" from secutils.defender_scan) → one line for the notch."""
    name = check.get("name") or Path(str(check.get("path", "soubor"))).name
    d = check.get("defender") or {}
    if isinstance(d, dict) and d.get("threats"):
        return f"⚠ {name}: Defender našel hrozbu ({', '.join(d['threats'][:2])}). Neotvírej ho."
    reasons = check.get("reasons") or []
    if check.get("level") == "bad":
        return f"⚠ {name}: {reasons[0] if reasons else 'podezřelý soubor'}. Neotvírej ho."
    sig = str(check.get("signature") or "")
    signer = re.search(r"CN=([^,]+)", sig)
    bits = [f"{name}: " + ("Defender nic nenašel" if isinstance(d, dict) and d.get("clean") else "zkontrolováno")]
    if sig.startswith("Valid") and signer:
        bits.append(f"podepsal {signer.group(1).strip()}")
    bits += [r for r in reasons if "spustitelný" not in r][:1]
    return ", ".join(bits) + "."


# ------------------------------------------------------------------ (193) časový zámek
def _in(spec_from: str, spec_to: str, clock: dt.datetime) -> bool:
    def mins(s: str) -> int:
        h, m = (int(x) for x in s.replace(".", ":").split(":")[:2])
        return h * 60 + m

    a, b, t = mins(spec_from), mins(spec_to), clock.hour * 60 + clock.minute
    return a <= t < b if a < b else (t >= a or t < b)


def time_blocks(rt: Any, tool: str, args: dict | None = None, clock: dt.datetime | None = None) -> str:
    """Some actions only at some times: payments not at night, the shell not on weekends… (Nastavení → Bezpečnost)."""
    locks = _get(rt, "time_locks", []) or []
    if not locks:
        return ""
    clock = clock or dt.datetime.now()
    from . import tools as tl
    from .permissions import perm_of
    from .trust import is_money

    spec = tl.REGISTRY.get(tool)
    for lk in locks:
        what = str(lk.get("what", ""))
        hit = (what == "money" and is_money(tool, args or {})) or (spec is not None and what == perm_of(spec)) or what == tool
        if not hit:
            continue
        days = lk.get("days")
        if days and clock.weekday() not in days:
            continue
        try:
            inside = _in(str(lk.get("from", "00:00")), str(lk.get("to", "00:00")), clock)
        except ValueError:
            continue
        if inside:
            label = {"money": "Platby", "shell": "Příkazy a kód", "files_write": "Změny souborů", "system": "Systém"}.get(what, what)
            return f"{label} jsou teď zamčené časovým zámkem ({lk.get('from')}–{lk.get('to')}). Změníš to v Nastavení → Bezpečnost."
    return ""


# ------------------------------------------------------------------ (194) neměnný záznam
def _chain(prev: str, ts: float, who: str, action: str, approved: bool) -> str:
    return hashlib.sha256(f"{prev}|{ts:.3f}|{who}|{action}|{int(approved)}".encode()).hexdigest()


def log_event(rt: Any, who: str, action: str, approved: bool, ts: float | None = None) -> str:
    ts = ts or time.time()
    last = db(rt).one("SELECT h FROM sx_audit ORDER BY n DESC LIMIT 1")
    prev = last["h"] if last else "0" * 64
    h = _chain(prev, ts, who[:40], action[:500], approved)
    db(rt).exec("INSERT INTO sx_audit (ts, who, action, approved, prev, h) VALUES (?,?,?,?,?,?)", (ts, who[:40], action[:500], int(approved), prev, h))
    return h


def verify_log(rt: Any) -> dict:
    prev = "0" * 64
    rows = db(rt).all("SELECT * FROM sx_audit ORDER BY n")
    for r in rows:
        if r["prev"] != prev or _chain(prev, float(r["ts"]), r["who"], r["action"], bool(r["approved"])) != r["h"]:
            return {"ok": False, "broken_at": int(r["n"]), "count": len(rows)}
        prev = r["h"]
    return {"ok": True, "count": len(rows), "last": prev}


# ------------------------------------------------------------------ (195) heslo odkazem, který zmizí
def oneshot_create(rt: Any, secret: str, hours: float = 24) -> str:
    if not secret.strip():
        raise ValueError("Co mám poslat?")
    token = pysecrets.token_urlsafe(18)
    blob = _fernet("oneshot_key").encrypt(secret.encode()).decode()
    db(rt).exec("INSERT INTO sx_oneshot VALUES (?,?,?,?)", (token, blob, time.time() + max(0.25, min(hours, 168)) * 3600, time.time()))
    return token


def oneshot_reveal(rt: Any, token: str) -> str | None:
    """Read once: the secret is deleted the moment it is shown (and after its time even unread)."""
    row = db(rt).one("SELECT * FROM sx_oneshot WHERE token=?", (token,))
    db(rt).exec("DELETE FROM sx_oneshot WHERE token=? OR until < ?", (token, time.time()))
    if not row or float(row["until"]) < time.time():
        return None
    return _fernet("oneshot_key").decrypt(row["blob"].encode()).decode()


def oneshot_page(token: str, revealed: str | None = None, gone: bool = False) -> str:
    style = ("<style>body{font:16px system-ui;margin:24px;background:#0b0f14;color:#e8eef5}button{font:inherit;padding:10px 18px;"
             "border-radius:10px;border:0;background:#4fc3ff;color:#001}pre{white-space:pre-wrap;background:#121a23;padding:14px;"
             "border-radius:10px;font-size:18px}</style>")
    head = "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Tajná zpráva</title>"
    if gone:
        return head + style + "<h1>Zpráva už není</h1><p>Byla přečtena, nebo vypršela.</p>"
    if revealed is not None:
        return head + style + f"<h1>Tajná zpráva</h1><pre>{html.escape(revealed)}</pre><p>Právě jsem ji smazal – znovu se nezobrazí.</p>"
    return head + style + (f"<h1>Tajná zpráva</h1><p>Zobrazí se jen jednou a hned se smaže.</p><form method=post action='/s/{html.escape(token)}'>"
                           "<button>Zobrazit</button></form>")


# ------------------------------------------------------------------ (196) YubiKey (Yubico OTP)
def yubico_signature(params: dict[str, str], key_b64: str) -> str:
    msg = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return base64.b64encode(hmac.new(base64.b64decode(key_b64), msg.encode(), hashlib.sha1).digest()).decode()


def otp_public_id(otp: str) -> str:
    otp = (otp or "").strip()
    return otp[:12] if re.fullmatch(r"[cbdefghijklnrtuv]{32,48}", otp) else ""


async def yubikey_verify(rt: Any, otp: str, client: Any = None) -> tuple[bool, str]:
    from . import secrets

    pid = otp_public_id(otp)
    want = str(_get(rt, "yubikey_id", "") or "")
    if not pid:
        return False, "To není kód z YubiKey (dotkni se klíče, napíše ho sám)."
    if want and pid != want:
        return False, "Tenhle YubiKey není ten tvůj."
    api = secrets.get("yubico_api")              # "client_id:base64key" from upgrade.yubico.com/getapikey
    if ":" not in (api or ""):
        return False, "Chybí Yubico API klíč (zdarma na upgrade.yubico.com/getapikey) – ulož ho v Nastavení → Klíče."
    cid, key = api.split(":", 1)
    nonce = pysecrets.token_hex(16)
    params = {"id": cid, "otp": otp.strip(), "nonce": nonce}
    params["h"] = yubico_signature(params, key)
    own = client is None
    c = client or rt.http()
    try:
        r = await c.get("https://api.yubico.com/wsapi/2.0/verify", params=params, timeout=10)
    finally:
        if own:
            await c.aclose()
    fields = dict(line.split("=", 1) for line in r.text.strip().splitlines() if "=" in line)
    if fields.get("nonce") != nonce or fields.get("otp") != otp.strip():
        return False, "Odpověď Yubico nesedí – zkus to znovu."
    sig = fields.pop("h", "")
    if not hmac.compare_digest(sig, yubico_signature(fields, key)):
        return False, "Podpis odpovědi Yubico nesedí."
    status = fields.get("status", "")
    return status == "OK", {"OK": "Ověřeno klíčem.", "REPLAYED_OTP": "Tenhle kód už byl použit."}.get(status, f"Yubico: {status}")


def needs_otp(rt: Any, tool: str) -> bool:
    if not _get(rt, "yubikey_required", False):
        return False
    from . import tools as tl

    spec = tl.REGISTRY.get(tool)
    return bool(spec is not None and getattr(spec, "danger", False))


# ------------------------------------------------------------------ (197) vymazání stop
def trace_targets(home: Path | None = None, env: dict | None = None) -> list[dict]:
    env = env if env is not None else dict(os.environ)
    home = home or Path.home()
    local = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
    roaming = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
    cands = [("Dočasné soubory", Path(env.get("TEMP") or local / "Temp")),
             ("Nedávné soubory", roaming / "Microsoft" / "Windows" / "Recent"),
             ("Mezipaměť Chrome", local / "Google" / "Chrome" / "User Data" / "Default" / "Cache"),
             ("Mezipaměť Edge", local / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache"),
             ("Miniatury", local / "Microsoft" / "Windows" / "Explorer")]
    out = []
    for label, p in cands:
        if p.is_dir():
            size = 0
            n = 0
            for f in p.rglob("*"):
                if f.is_file():
                    n += 1
                    try:
                        size += f.stat().st_size
                    except OSError:
                        pass
                if n > 20000:
                    break
            out.append({"label": label, "path": str(p), "files": n, "bytes": size})
    return out


def wipe(targets: list[dict], only: list[str] | None = None) -> dict:
    """Deletes what is inside those folders (never the folders themselves, never passwords or cookies)."""
    freed, files, skipped = 0, 0, 0
    for t in targets:
        if only and t["label"] not in only:
            continue
        root = Path(t["path"])
        for f in sorted(root.rglob("*"), key=lambda x: -len(x.parts)):
            try:
                if f.is_file() or f.is_symlink():
                    if root.name == "Explorer" and not f.name.startswith(("thumbcache_", "iconcache_")):
                        continue
                    size = f.stat().st_size if f.is_file() else 0
                    f.unlink()
                    freed += size
                    files += 1
                elif f.is_dir():
                    f.rmdir()
            except OSError:
                skipped += 1
    return {"files": files, "bytes": freed, "skipped": skipped}


# ------------------------------------------------------------------ (198) router
RISKY_PORTS = {21: "FTP", 23: "Telnet", 22: "SSH", 80: "web (HTTP)", 443: "web (HTTPS)", 7547: "TR-069 (vzdálená správa operátora)",
               8080: "web 8080", 8443: "web 8443", 1900: "UPnP", 53: "DNS", 445: "SMB (sdílení souborů)"}


def default_gateway() -> str:
    try:
        if os.name == "nt":
            import subprocess

            out = subprocess.run(["route", "print", "0.0.0.0"], capture_output=True, text=True, timeout=10).stdout
            m = re.search(r"0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", out)
            return m.group(1) if m else ""
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            f = line.split()
            if f[1] == "00000000":
                return socket.inet_ntoa(bytes.fromhex(f[2])[::-1])
    except Exception:  # noqa: BLE001
        pass
    return ""


def port_open(host: str, port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def router_report(gw: str, open_ports: list[int], upnp: dict | None = None, page_title: str = "") -> dict:
    tips = []
    if 23 in open_ports:
        tips.append("Router má zapnutý Telnet – starý nešifrovaný přístup. Vypni ho v administraci.")
    if 21 in open_ports:
        tips.append("Router nabízí FTP – pokud nesdílíš disk, vypni ho.")
    if 7547 in open_ports:
        tips.append("Port 7547 (vzdálená správa operátora) je otevřený i do domácí sítě – zeptej se operátora, jestli ho potřebuje.")
    if upnp:
        tips.append(f"UPnP je zapnuté ({upnp.get('model', 'router')}) – programy si samy otevírají porty. Když nehraješ online hry, vypni ho.")
        if upnp.get("firmware"):
            tips.append(f"Firmware {upnp['firmware']} – porovnej s nejnovějším na webu výrobce ({upnp.get('maker', '')}).")
    if 80 in open_ports and 443 not in open_ports:
        tips.append("Administrace jen přes nešifrované HTTP – heslo k routeru jde po síti čitelně.")
    tips.append("Výchozí heslo nezjistím bez přihlášení – pokud jsi heslo k administraci nikdy neměnil, změň ho (bývá na štítku routeru).")
    return {"gateway": gw, "open": [{"port": p, "what": RISKY_PORTS.get(p, str(p))} for p in open_ports], "upnp": upnp or {},
            "title": page_title, "tips": tips}


def parse_upnp(xml: str) -> dict:
    def tag(name: str) -> str:
        m = re.search(rf"<{name}>([^<]*)</{name}>", xml or "")
        return m.group(1).strip() if m else ""

    return {k: v for k, v in {"maker": tag("manufacturer"), "model": tag("modelName") or tag("friendlyName"),
                              "firmware": tag("softwareVersion") or tag("modelNumber")}.items() if v}


def upnp_discover(timeout: float = 2.0) -> str:
    """The router's UPnP description URL (SSDP M-SEARCH on the home network), '' when UPnP is off."""
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 1\r\n"
           "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n").encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(msg, ("239.255.255.250", 1900))
        data, _ = s.recvfrom(4096)
        m = re.search(rb"(?im)^location:\s*(\S+)", data)
        return m.group(1).decode() if m else ""
    except OSError:
        return ""
    finally:
        s.close()


# ------------------------------------------------------------------ (199) rozšíření prohlížeče
DANGER_PERMS = {"<all_urls>": 3, "*://*/*": 3, "http://*/*": 2, "https://*/*": 3, "webRequest": 1, "webRequestBlocking": 2,
                "cookies": 2, "history": 1, "clipboardRead": 2, "nativeMessaging": 2, "debugger": 3, "proxy": 2, "management": 2,
                "declarativeNetRequestWithHostAccess": 1, "scripting": 1, "tabs": 1, "downloads": 1, "privacy": 1}


def browser_ext_dirs(env: dict | None = None) -> list[tuple[str, Path]]:
    env = env if env is not None else dict(os.environ)
    local = Path(env.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    out = []
    for name, base in (("Chrome", local / "Google" / "Chrome" / "User Data"), ("Edge", local / "Microsoft" / "Edge" / "User Data"),
                       ("Brave", local / "BraveSoftware" / "Brave-Browser" / "User Data"),
                       ("Chrome", Path.home() / ".config" / "google-chrome"), ("Chromium", Path.home() / ".config" / "chromium")):
        if base.is_dir():
            for prof in base.iterdir():
                if (prof / "Extensions").is_dir():
                    out.append((f"{name} ({prof.name})", prof / "Extensions"))
    return out


def ext_risk(manifest: dict) -> dict:
    perms = [str(p) for p in (manifest.get("permissions") or []) + (manifest.get("host_permissions") or []) + (manifest.get("optional_permissions") or [])
             if isinstance(p, str)]
    for cs in manifest.get("content_scripts") or []:
        perms += [m for m in cs.get("matches") or [] if isinstance(m, str)]
    score = sum(DANGER_PERMS.get(p, 0) for p in set(perms))
    risky = sorted({p for p in perms if DANGER_PERMS.get(p, 0) >= 2})
    return {"score": score, "risky": risky, "level": "high" if score >= 6 else "medium" if score >= 3 else "low"}


def scan_extensions(dirs: list[tuple[str, Path]]) -> list[dict]:
    out = []
    for browser, root in dirs:
        for ext in root.iterdir():
            if not ext.is_dir() or ext.name == "Temp":
                continue
            vers = sorted((v for v in ext.iterdir() if (v / "manifest.json").is_file()), key=lambda v: v.name)
            if not vers:
                continue
            try:
                man = json.loads((vers[-1] / "manifest.json").read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            name = str(man.get("name") or ext.name)
            if name.startswith("__MSG_"):
                name = ext.name
            r = ext_risk(man)
            out.append({"browser": browser, "id": ext.name, "name": name[:60], "version": vers[-1].name, **r})
    return sorted(out, key=lambda e: -e["score"])


# ------------------------------------------------------------------ (200) test jedním klikem
async def full_check(rt: Any, parts: dict[str, Callable[[], Any]] | None = None) -> dict:
    """Runs every check and gives a score out of 100 with the three most important things to do."""
    import asyncio

    async def run(fn: Callable[[], Any]) -> Any:
        try:
            r = fn()
            if asyncio.iscoroutine(r):
                r = await r
            return r
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:200]}

    parts = parts or default_checks(rt)
    results = {k: await run(fn) for k, fn in parts.items()}
    findings: list[tuple[int, str]] = []
    perm = results.get("permissions") or {}
    findings += [(1, t) for t in perm.get("tips", [])[:3]] if isinstance(perm, dict) else []
    exts = results.get("extensions") or []
    if isinstance(exts, list):
        findings += [(3 if e["level"] == "high" else 2, f"Rozšíření „{e['name']}“ ({e['browser']}) smí: {', '.join(e['risky'][:4])}.")
                     for e in exts if e.get("level") in ("high", "medium")][:5]
    rtr = results.get("router") or {}
    if isinstance(rtr, dict):
        findings += [(2, t) for t in rtr.get("tips", [])[:-1]]
    tfa = results.get("twofa") or {}
    if isinstance(tfa, dict) and tfa.get("missing"):
        findings.append((2, f"Dvoufázové ověření chybí u {len(tfa['missing'])} účtů – začni u {tfa['missing'][0]['service']}."))
    logons = results.get("failed_logons")
    if isinstance(logons, int) and logons >= 5:
        findings.append((3, f"{logons} neúspěšných přihlášení do Windows za týden."))
    log_ok = results.get("audit_log") or {}
    if isinstance(log_ok, dict) and log_ok.get("ok") is False:
        findings.append((3, "Záznam schválení byl změněn – někdo do něj zasahoval."))
    findings.sort(key=lambda f: -f[0])
    score = max(0, 100 - sum(w * 6 for w, _ in findings))
    return {"score": score, "findings": [t for _, t in findings], "results": results,
            "summary": f"Bezpečnost: {score}/100. " + (" ".join(t for _, t in findings[:3]) if findings else "Nic vážného jsem nenašel.")}


def default_checks(rt: Any) -> dict[str, Callable[[], Any]]:
    import asyncio

    def router() -> dict:
        gw = default_gateway()
        if not gw:
            return {"tips": []}
        ports = [p for p in (21, 22, 23, 80, 443, 7547, 8080) if port_open(gw, p)]
        loc = upnp_discover()
        upnp = {}
        if loc:
            try:
                import urllib.request

                with urllib.request.urlopen(loc, timeout=3) as r:  # noqa: S310 – the router's own UPnP address on the LAN
                    upnp = parse_upnp(r.read(65536).decode("utf-8", "replace")) or {"model": "router"}
            except Exception:  # noqa: BLE001
                upnp = {"model": "router"}
        return router_report(gw, ports, upnp or None)

    def logons() -> int:
        from .safety import failed_logons

        return failed_logons(7)

    return {"permissions": lambda: permission_audit(rt), "extensions": lambda: scan_extensions(browser_ext_dirs()),
            "router": lambda: asyncio.to_thread(router), "twofa": lambda: twofa_report(rt), "failed_logons": logons,
            "audit_log": lambda: verify_log(rt)}


# ------------------------------------------------------------------ background: camera / mic, downloads, stranger, monthly audit
async def loop(rt: Any) -> None:
    import asyncio

    from . import secplus, secutils

    await asyncio.sleep(45)
    before: set[str] = set()
    seen: dict[str, float] = {}
    dl = Path(str(_get(rt, "downloads_folder", "") or (Path.home() / "Downloads")))
    if dl.is_dir():
        new_downloads(dl, seen, time.time() + 3600)                # what is already there is not news
    n = 0
    while True:
        n += 1
        try:
            if os.name == "nt" and _get(rt, "media_alert", True):
                data = await asyncio.to_thread(secplus.run_ps, secplus.CONSENT_PS, 30)
                now_ = in_use(secplus.parse_consent(secplus._list(data.get("apps"))))
                for t in media_changes(before, now_):
                    rt.notify("Kamera / mikrofon", t, speak=False)
                before = now_
        except Exception as e:  # noqa: BLE001
            log.debug("media alert: %s", e)
        try:
            if _get(rt, "scan_downloads", True) and n % 2 == 0:
                for p in new_downloads(dl, seen):
                    r = await asyncio.to_thread(secutils.check_file, str(p))
                    if os.name == "nt" and "error" not in r:
                        r["defender"] = await asyncio.to_thread(secutils.defender_scan, r.get("path", str(p)))
                    if "error" not in r:
                        rt.notify("Stažený soubor", download_verdict({**r, "name": p.name}), speak=False)
        except Exception as e:  # noqa: BLE001
            log.debug("downloads: %s", e)
        try:
            if n % 4 == 0:
                await stranger_tick(rt)
        except Exception as e:  # noqa: BLE001
            log.debug("stranger: %s", e)
        try:
            from .proactiveplus import due_today

            today = dt.date.today()
            if today.day == 1 and due_today(rt, "sx_audit_month", "10:00", dt.datetime.now()):
                rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("sx_audit_month", today.isoformat()))
                rt.notify("Audit oprávnění", audit_text(permission_audit(rt)), speak=False)
        except Exception as e:  # noqa: BLE001
            log.debug("monthly audit: %s", e)
        await asyncio.sleep(15)
