"""3.14 Balíčky dovedností s podpisem (návrhy 104, 105).

A skill package (.jarvisskill) is a ZIP with the skill's Python file, a manifest (name, version, what it does, the
permission areas it uses, the author, its public key, the SHA-256 of the code) and an Ed25519 signature over both.

- your own skills are signed with this PC's key (made once, kept in the OS keyring) – share the file with anyone
- installing checks the signature and the code hash: a changed file is refused; a valid signature from an author
  you have not trusted yet is shown as "neznámý autor" with its fingerprint
- the code then goes through the same review and approval as a skill JARVIS writes itself (you see every line)
- a catalog is just a JSON list on any web address (e.g. a GitHub repository): {"skills": [{"name", "url", …}]}
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any

KEY = "skill_sign_key"
MAX_BYTES = 512 * 1024


def _keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from . import secrets

    raw = secrets.get(KEY)
    if raw:
        priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(raw))
    else:
        priv = Ed25519PrivateKey.generate()
        secrets.set(KEY, base64.b64encode(priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                                             serialization.NoEncryption())).decode())
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return priv, pub


def fingerprint(pub: bytes) -> str:
    h = hashlib.sha256(pub).hexdigest()[:16]
    return ":".join(h[i:i + 4] for i in range(0, 16, 4))


def my_fingerprint() -> str:
    return fingerprint(_keypair()[1])


def _signed_bytes(manifest: dict, code: bytes) -> bytes:
    return json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode() + b"\n" + code


def pack(path: str | Path, author: str = "") -> bytes:
    """A skill file → a signed .jarvisskill package."""
    from .tools.skills import read_manifest

    p = Path(path)
    code = p.read_bytes()
    if len(code) > MAX_BYTES:
        raise ValueError("dovednost je moc velká")
    m = read_manifest(p) or {}
    priv, pub = _keypair()
    manifest: dict[str, Any] = {"format": 1, "name": str(m.get("name") or p.stem), "version": str(m.get("version", "1.0")),
                "description": str(m.get("description", ""))[:300], "permissions": list(m.get("permissions", [])),
                "author": author[:60], "pubkey": base64.b64encode(pub).decode(), "file": f"{p.stem}.py",
                "sha256": hashlib.sha256(code).hexdigest(), "created": int(time.time())}
    sig = priv.sign(_signed_bytes(manifest, code))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        z.writestr(str(manifest["file"]), code)
        z.writestr("signature", base64.b64encode(sig).decode())
    return buf.getvalue()


def inspect(data: bytes, trusted: list[str] | None = None) -> dict:
    """Verify a package: the code matches its hash, the signature matches its key. Never runs anything."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if len(data) > 4 * MAX_BYTES:
        raise ValueError("balíček je moc velký")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        fname = str(manifest.get("file", ""))
        if not re.fullmatch(r"[a-z0-9_]{1,40}\.py", fname):
            raise ValueError("neplatný název souboru v balíčku")
        code = z.read(fname)
        sig = base64.b64decode(z.read("signature"))
    except (KeyError, zipfile.BadZipFile, ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"tohle není balíček dovednosti JARVISe ({e})") from e
    problems = []
    if hashlib.sha256(code).hexdigest() != manifest.get("sha256"):
        problems.append("kód nesedí s otiskem v manifestu (soubor byl změněn)")
    valid = False
    try:
        pub = base64.b64decode(manifest.get("pubkey", ""))
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, _signed_bytes(manifest, code))
        valid = not problems
    except (InvalidSignature, ValueError):
        problems.append("podpis nesedí")
        pub = b""
    fp = fingerprint(pub) if pub else ""
    return {"valid": valid, "problems": problems, "manifest": manifest, "fingerprint": fp, "code": code.decode("utf-8", "replace"),
            "trusted": bool(fp) and fp in (trusted or []), "mine": bool(fp) and fp == my_fingerprint()}


def catalog_entries(data: Any) -> list[dict]:
    items = data.get("skills", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    out = []
    for it in items:
        if isinstance(it, dict) and it.get("url") and it.get("name"):
            out.append({"name": str(it["name"])[:60], "url": str(it["url"]), "description": str(it.get("description", ""))[:200],
                        "author": str(it.get("author", ""))[:60], "version": str(it.get("version", ""))[:20]})
    return out[:200]
