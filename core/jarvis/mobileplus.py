"""Wave 34 – phone and other devices.

* clean_text (OMEGA 726): links lose their tracking parameters, secrets are masked before text goes to another device
* command links / QR (731): a printed QR runs a sentence – always shown and confirmed on the phone first
* shared folders (415): the phone browses only the PC folders you chose, read-only, nothing outside them
* guests (727 / 419): a temporary pairing for someone else that expires, with only the music and volume controls
* device permissions (419): which permission areas a paired phone may use at all
"""
from __future__ import annotations

import contextvars
import hashlib
import os
import secrets
import time
import urllib.parse
from pathlib import Path

from . import paths
from .redact import redact

# ---------------------------------------------------------------- 726 clean text for another device
TRACKING = {"fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "yclid", "igshid", "igsh", "mc_cid", "mc_eid",
            "_hsenc", "_hsmi", "ref_src", "ref_url", "si", "spm", "scm", "s_cid", "trk", "trkCampaign", "vero_id",
            "oly_anon_id", "oly_enc_id", "rb_clickid", "__s", "_ga", "_gl", "share_id"}


def clean_url(url: str) -> tuple[str, list[str]]:
    """A link without the parts that only say who shared it where (utm_*, fbclid, si …)."""
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return url, []
    if p.scheme not in ("http", "https") or not p.query:
        return url, []
    keep, gone = [], []
    for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True):
        if k.lower().startswith("utm_") or k in TRACKING:
            gone.append(k)
        else:
            keep.append((k, v))
    if not gone:
        return url, []
    return urllib.parse.urlunsplit(p._replace(query=urllib.parse.urlencode(keep))), gone


def clean_text(text: str) -> dict:
    """Text ready to go to another device: links cleaned, passwords / keys / tokens masked."""
    import re

    removed: list[str] = []

    def fix(m: re.Match) -> str:
        url, gone = clean_url(m.group(0))
        removed.extend(gone)
        return url

    out = re.sub(r"https?://[^\s<>\"']+", fix, text or "")
    masked = redact(out)
    return {"text": masked, "removed": sorted(set(removed)), "masked": masked != out}


# ---------------------------------------------------------------- 731 command links and QR codes
SCHEME = "jarvis://cmd"
MAX_CMD = 300


def command_link(text: str) -> str:
    text = " ".join(str(text).split())[:MAX_CMD]
    if not text:
        raise ValueError("Napiš, co má QR kód spustit.")
    return f"{SCHEME}?{urllib.parse.urlencode({'text': text})}"


def parse_command_link(url: str) -> str | None:
    """The sentence inside a JARVIS command link, or None (anything else is not ours)."""
    if not str(url).startswith(SCHEME + "?"):
        return None
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    text = " ".join((q.get("text") or [""])[0].split())[:MAX_CMD]
    return text or None


def command_qr(text: str, name: str = "") -> Path:
    import qrcode

    link = command_link(text)
    out = paths.sub("qr")
    slug = "".join(c if c.isalnum() else "-" for c in (name or text).lower())[:40].strip("-") or "prikaz"
    path = out / f"{slug}-{int(time.time())}.png"
    img = qrcode.make(link, box_size=12, border=3)
    img.save(path)
    return path


# ---------------------------------------------------------------- 415 PC folders the phone may browse
def shared_roots(rt) -> list[dict]:
    out = []
    for i, p in enumerate(rt.cfg.phone.shared_folders):
        path = Path(os.path.expandvars(os.path.expanduser(p)))
        out.append({"id": str(i), "name": path.name or str(path), "path": str(path), "ok": path.is_dir()})
    return out


def _resolve(rt, root: str, rel: str = "") -> tuple[Path, Path]:
    roots = shared_roots(rt)
    r = next((x for x in roots if x["id"] == str(root)), None)
    if not r or not r["ok"]:
        raise PermissionError("Tahle složka není sdílená s telefonem.")
    base = Path(r["path"]).resolve()
    target = (base / (rel or "").lstrip("/\\")).resolve()
    if target != base and base not in target.parents:
        raise PermissionError("Mimo sdílenou složku nesmím.")
    if any(part.startswith(".") for part in target.relative_to(base).parts):
        raise PermissionError("Skryté soubory telefonu neukazuji.")
    return base, target


def browse(rt, root: str, rel: str = "", limit: int = 300) -> dict:
    base, target = _resolve(rt, root, rel)
    if not target.is_dir():
        raise FileNotFoundError("Složka neexistuje.")
    items = []
    for e in os.scandir(target):
        if e.name.startswith(".") or e.is_symlink():
            continue
        try:
            st = e.stat()
        except OSError:
            continue
        items.append({"name": e.name, "dir": e.is_dir(), "size": 0 if e.is_dir() else st.st_size, "mtime": st.st_mtime})
    items.sort(key=lambda x: (not x["dir"], -x["mtime"] if not x["dir"] else 0, x["name"].lower()))
    rel_path = target.relative_to(base).as_posix()
    return {"root": str(root), "path": "" if rel_path == "." else rel_path, "items": items[:limit], "more": len(items) > limit}


def shared_file(rt, root: str, rel: str) -> Path:
    _, target = _resolve(rt, root, rel)
    if not target.is_file() or target.is_symlink():
        raise FileNotFoundError("Soubor neexistuje.")
    return target


# ---------------------------------------------------------------- 727 / 419 guests and device permissions
GUEST_TYPES = {"hello", "ping", "quick_action", "guest_info"}
GUEST_QUICK = {"media_control", "volume", "youtube_play"}
_DEVICE_PERMS: contextvars.ContextVar[set[str] | None] = contextvars.ContextVar("device_perms", default=None)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def add_guest(rt, name: str = "Host", hours: float = 3) -> dict:
    """A temporary pairing: its own token (only the hash is kept) that stops working by itself."""
    from .config import Guest

    hours = max(0.25, min(72.0, float(hours)))
    token = "g_" + secrets.token_urlsafe(24)
    g = Guest(id=secrets.token_hex(4), name=(name or "Host").strip()[:40], token_hash=_hash(token), expires=time.time() + hours * 3600)
    guests = [x for x in rt.cfg.phone.guests if x.expires > time.time()] + [g]
    rt.update_config({"phone": {"guests": [x.model_dump() for x in guests]}})
    from .secplus import record_consent

    record_consent(rt, "Dočasný přístup hosta (hudba a hlasitost)", g.name, True, "telefon", g.expires)
    return {**g.model_dump(exclude={"token_hash"}), "token": token}


def guest_for(rt, token: str | None) -> dict | None:
    if not token or not token.startswith("g_"):
        return None
    h = _hash(token)
    now = time.time()
    for g in rt.cfg.phone.guests:
        if secrets.compare_digest(g.token_hash, h) and g.expires > now:
            return g.model_dump(exclude={"token_hash"})
    return None


def revoke_guest(rt, gid: str) -> bool:
    keep = [x for x in rt.cfg.phone.guests if x.id != gid]
    if len(keep) == len(rt.cfg.phone.guests):
        return False
    rt.update_config({"phone": {"guests": [x.model_dump() for x in keep]}})
    return True


def list_guests(rt) -> list[dict]:
    now = time.time()
    return [{**g.model_dump(exclude={"token_hash"}), "left_min": round((g.expires - now) / 60)} for g in rt.cfg.phone.guests if g.expires > now]


def guest_perms() -> set[str]:
    """Exactly the permission areas the guest's few quick actions need – nothing more."""
    from . import tools
    from .permissions import required

    return {p for n in GUEST_QUICK if (spec := tools.REGISTRY.get(n)) for p in required(spec)}


def set_device_perms(perms: set[str] | None) -> contextvars.Token:
    """For the request that is about to start: the permission areas this device may use (None = no extra limit)."""
    return _DEVICE_PERMS.set(perms)


def device_blocks(required: list[str]) -> str | None:
    allowed = _DEVICE_PERMS.get()
    if allowed is None:
        return None
    return next((p for p in required if p not in allowed), None)
