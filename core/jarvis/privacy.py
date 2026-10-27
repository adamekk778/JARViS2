"""OMEGA §51 Privacy Fortress: what JARVIS keeps (677), how long (684), where the microphone was on (679), the full
export (793), an encrypted backup (685) and the complete local reset (794). Everything stays on this PC."""
from __future__ import annotations

import datetime as dt
import io
import os
import shutil
import time
import zipfile
from pathlib import Path

from . import paths

MIC_SQL = "CREATE TABLE IF NOT EXISTS mic_log (start REAL, end REAL, source TEXT);"
# table → what it is, in Czech (the data inventory shows these)
TABLES = {
    "conversations": "konverzace", "messages": "zprávy v chatu", "facts": "zapamatovaná fakta", "tasks": "mise a úkoly",
    "task_actions": "záznam akcí (audit)", "task_artifacts": "soubory z misí", "task_evidence": "důkazy misí",
    "task_steps": "kroky misí", "jobs": "naplánované rutiny", "dictations": "diktování", "notes": "poznámky a nahrávky",
    "app_usage": "čas v aplikacích", "cal_events": "události kalendáře", "llm_usage": "spotřeba AI", "lists": "seznamy",
    "skill_versions": "verze dovedností", "mic_log": "kdy byl zapnutý mikrofon", "attachments": "přílohy",
    "projects": "projekty", "fact_conflicts": "rozpory v paměti", "search_idx": "vyhledávací rejstřík",
    "search_emb": "rejstřík podle významu", "perf_history": "historie výkonu", "perf_bench": "testy výkonu",
    "cards": "kartičky na učení", "card_reviews": "opakování kartiček", "quiz_answers": "odpovědi v testech", "exams": "plány zkoušek",
    "app_hours": "aplikace podle hodin (rutiny)", "price_history": "historie cen", "workspaces": "pracovní prostředí (rozložení oken)",
    "db_snapshots": "záznamy o velikosti databází", "experiments": "deník experimentů",
    "doc_files": "zaindexované dokumenty", "doc_idx": "rejstřík dokumentů",
    "site_checks": "kontroly dostupnosti webů", "creative_assets": "evidence souborů a licencí", "tutor_progress": "postup v procvičování", "voice_bookmarks": "záložky v hovorech a konverzacích", "quotes": "evidence cenových nabídek", "customer_requests": "požadavky zákazníků", "competitor_snapshots": "uložené stránky konkurence", "sfx_index": "rejstřík zvukových efektů", "render_jobs": "fronta renderů", "pins": "připnuté úkoly v notchi",
}
# (table, time column) pruned by the retention rule
RETAIN = [("messages", "created"), ("tasks", "created"), ("task_actions", "ts"), ("task_evidence", "ts"),
          ("task_artifacts", "ts"), ("dictations", "ts"), ("app_usage", None), ("app_hours", None), ("llm_usage", None), ("mic_log", "start")]


def _tables(rt) -> set[str]:
    return {r["name"] for r in rt.db.all("SELECT name FROM sqlite_master WHERE type='table'")}


def _dir_size(p: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------------------------- inventory
def inventory(rt) -> dict:
    """OMEGA 677: every kind of personal data JARVIS holds, how much, and where. Secrets are listed by name only."""
    have = _tables(rt)
    rows = []
    for t, label in TABLES.items():
        if t in have:
            n = rt.db.one(f"SELECT COUNT(*) n FROM {t}")["n"]
            rows.append({"what": label, "table": t, "count": n})
    base = paths.data_dir()
    folders = []
    for name in sorted(p.name for p in base.iterdir() if p.is_dir()):
        folders.append({"folder": name, "bytes": _dir_size(base / name)})
    from . import secrets

    names = ["api klíče poskytovatelů AI", "hesla e-mailových účtů", "token Home Assistantu", "token Twilio"]
    return {"base": str(base), "database": rows, "folders": folders, "secrets": names,
            "secrets_where": "trezor Windows (Správce pověření)" if secrets._keyring() else "soubor secrets.json v datové složce",
            "private_mode": rt.memory.private, "keep_days": rt.cfg.privacy.keep_days}


# ---------------------------------------------------------------------------------------------- retention
def prune(rt, keep_days: int | None = None, now: float | None = None) -> dict:
    """OMEGA 684: delete everything older than `keep_days` (0 = keep all). Facts, settings and skills stay."""
    keep_days = rt.cfg.privacy.keep_days if keep_days is None else keep_days
    if not keep_days:
        return {}
    cutoff = (now or time.time()) - keep_days * 86400
    day_cut = dt.date.fromtimestamp(cutoff).isoformat()
    have, out = _tables(rt), {}
    for table, col in RETAIN:
        if table not in have:
            continue
        if col:
            n = rt.db.exec(f"DELETE FROM {table} WHERE {col} < ?", (cutoff,)).rowcount
        else:
            n = rt.db.exec(f"DELETE FROM {table} WHERE day < ?", (day_cut,)).rowcount
        if n:
            out[table] = n
    rt.db.exec("DELETE FROM task_steps WHERE task_id NOT IN (SELECT id FROM tasks)")
    rt.db.exec("DELETE FROM conversations WHERE id NOT IN (SELECT DISTINCT conv_id FROM messages) AND updated < ?", (cutoff,))
    if out:
        drop_search_index(rt)
    return out


def drop_search_index(rt) -> None:
    """The search index is rebuilt from what is left (so deleted things cannot be found any more)."""
    for t in ("search_idx", "search_emb"):
        if t in _tables(rt):
            rt.db.exec(f"DELETE FROM {t}")
    rt.db.exec("DELETE FROM kv WHERE k LIKE 'idx_%'")


# ---------------------------------------------------------------------------------------------- microphone
class MicLog:
    """OMEGA 679: when the microphone was listening (from the real state events), kept 30 days."""

    def __init__(self, rt):
        self.rt = rt
        rt.db.conn.executescript(MIC_SQL)
        self._since: float | None = None

    def on_event(self, m: dict) -> None:
        if m.get("type") != "state":
            return
        listening, now = m.get("state") == "listening", time.time()
        if listening and self._since is None:
            self._since = now
        elif not listening and self._since is not None:
            self.rt.db.exec("INSERT INTO mic_log VALUES (?,?,?)", (self._since, now, "hlas"))
            self._since = None

    def recent(self, days: int = 7) -> dict:
        since = time.time() - days * 86400
        rows = self.rt.db.all("SELECT start, end, source FROM mic_log WHERE start>=? ORDER BY start DESC LIMIT 200", (since,))
        return {"sessions": rows, "seconds": round(sum(r["end"] - r["start"] for r in rows)), "now": self._since is not None,
                "camera": "JARVIS kameru nepoužívá"}


# ---------------------------------------------------------------------------------------------- export / backup / reset
def _zip_data(include_files: bool = True) -> bytes:
    base = paths.data_dir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(base):
            rel_root = Path(root).relative_to(base)
            dirs[:] = [d for d in dirs if d not in ("webview", "models", "logs", "Audit") and (include_files or d != "files")]
            for f in files:
                if f.endswith((".tmp", "-journal", "-wal", "-shm")) or f == "secrets.json":
                    continue
                p = Path(root) / f
                try:
                    z.write(p, str(rel_root / f))
                except OSError:
                    pass
    return buf.getvalue()


def export_all(folder: Path | None = None) -> Path:
    """OMEGA 793: all my data in one ZIP (database, settings, files) – without passwords and API keys."""
    folder = folder or (Path.home() / "Documents" if (Path.home() / "Documents").is_dir() else Path.home())
    p = folder / f"JARVIS-data_{dt.datetime.now():%Y-%m-%d_%H-%M}.zip"
    p.write_bytes(_zip_data())
    return p


def _key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000).derive(password.encode())


MAGIC = b"JARVISVAULT1"


def backup_encrypted(password: str, folder: Path | None = None) -> Path:
    """OMEGA 685: the same data, encrypted with AES-256-GCM and a key from the password (PBKDF2, 390 000 rounds)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(password) < 8:
        raise ValueError("Heslo zálohy musí mít aspoň 8 znaků.")
    salt, nonce = os.urandom(16), os.urandom(12)
    data = AESGCM(_key(password, salt)).encrypt(nonce, _zip_data(), MAGIC)
    folder = folder or (Path.home() / "Documents" if (Path.home() / "Documents").is_dir() else Path.home())
    p = folder / f"JARVIS-zaloha_{dt.datetime.now():%Y-%m-%d_%H-%M}.jarvisvault"
    p.write_bytes(MAGIC + salt + nonce + data)
    return p


def restore_encrypted(path: Path, password: str, target: Path | None = None) -> list[str]:
    """Decrypts a backup into `target` (default: a new folder next to it, never over the live data). → file names"""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw = Path(path).read_bytes()
    if not raw.startswith(MAGIC):
        raise ValueError("Tohle není záloha JARVISe.")
    salt, nonce, data = raw[len(MAGIC):len(MAGIC) + 16], raw[len(MAGIC) + 16:len(MAGIC) + 28], raw[len(MAGIC) + 28:]
    try:
        plain = AESGCM(_key(password, salt)).decrypt(nonce, data, MAGIC)
    except InvalidTag:
        raise ValueError("Špatné heslo nebo poškozená záloha.") from None
    target = target or Path(path).with_suffix("")
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(plain)) as z:
        for name in z.namelist():
            if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                raise ValueError("Záloha obsahuje podezřelou cestu.")
        z.extractall(target)
        return z.namelist()


def reset_all(rt) -> dict:
    """OMEGA 794: wipes JARVIS's local data (history, memory, missions, logs, files, usage). Settings and secrets stay
    unless asked; the phone pairing gets a new token so paired devices are disconnected."""
    import secrets as pysecrets

    have, out = _tables(rt), {}
    for t in TABLES:
        if t in have:
            out[t] = rt.db.exec(f"DELETE FROM {t}").rowcount
    rt.db.exec("DELETE FROM kv WHERE k NOT IN ('whats_new_seen')")
    files = paths.data_dir() / "files"
    if files.is_dir():
        shutil.rmtree(files, ignore_errors=True)
    rt.memory.new_conversation()
    rt.update_config({"phone": {"token": pysecrets.token_urlsafe(32)}})
    return out



async def watch(rt) -> None:
    """Background: the microphone log follows the real listening state; old data is pruned once a day."""
    import asyncio

    q = rt.bus.subscribe()
    last_prune = 0.0
    try:
        while True:
            try:
                m = await asyncio.wait_for(q.get(), timeout=60)
                rt.miclog.on_event(m)
            except asyncio.TimeoutError:
                pass
            if time.time() - last_prune > 86400:
                last_prune = time.time()
                try:
                    prune(rt)
                except Exception:
                    pass
    finally:
        rt.bus.unsubscribe(q)
