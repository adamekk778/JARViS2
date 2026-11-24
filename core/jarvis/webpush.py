"""3.18 iPhone bez Macu (návrh 15): the JARVIS web app added to the iPhone's home screen (iOS 16.4+) gets JARVIS's
notices as real notifications – Web Push, the standard way, no App Store, no Mac.

- The phone (Safari, the app from the home screen) subscribes once; the subscription (the push service's address and
  the phone's public keys) stays on this PC.
- A notice is encrypted for that phone (RFC 8291, aes128gcm) and signed with this PC's own key (VAPID, RFC 8292), so
  Apple's push service only carries bytes it cannot read.
- iOS allows this only for a page opened over HTTPS with a valid certificate – e.g. Tailscale Serve or a Cloudflare
  Tunnel in front of JARVIS (docs/IPHONE.md).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger("jarvis.webpush")

VAPID_KEY = "webpush_vapid"
SQL = "CREATE TABLE IF NOT EXISTS webpush (endpoint TEXT PRIMARY KEY, p256dh TEXT, auth TEXT, label TEXT, added REAL)"
PUSH_HOSTS = ("web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com", "notify.windows.com",
              "push.services.mozilla.com")
RECORD = 4096


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ------------------------------------------------------------------------------------------ this PC's signing key (VAPID)
def _private() -> Any:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from . import secrets

    pem = secrets.get(VAPID_KEY)
    if pem:
        return serialization.load_pem_private_key(pem.encode(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    secrets.set(VAPID_KEY, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()).decode())
    return key


def _raw_public(key: Any) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def public_key() -> str:
    """What the page passes to pushManager.subscribe (applicationServerKey)."""
    return b64u(_raw_public(_private()))


def vapid_header(endpoint: str, subject: str = "mailto:jarvis@localhost", key: Any = None) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    key = key or _private()
    u = urlsplit(endpoint)
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": subject},
                           separators=(",", ":")).encode())
    der = key.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"vapid t={head}.{body}.{b64u(sig)}, k={b64u(_raw_public(key))}"


# ------------------------------------------------------------------------------------------ encryption for one phone (RFC 8291)
def _hkdf(salt: bytes, ikm: bytes, info: bytes, n: int) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=n, salt=salt, info=info).derive(ikm)


def encrypt(payload: bytes, p256dh: str, auth: str, salt: bytes | None = None, eph: Any = None) -> bytes:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    ua_pub = unb64u(p256dh)
    secret = unb64u(auth)
    eph = eph or ec.generate_private_key(ec.SECP256R1())
    as_pub = _raw_public(eph)
    shared = eph.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub))
    ikm = _hkdf(secret, shared, b"WebPush: info\x00" + ua_pub + as_pub, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    if len(payload) > RECORD - 17 - 86:
        raise ValueError("zpráva je na push moc dlouhá")
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + RECORD.to_bytes(4, "big") + bytes([len(as_pub)]) + as_pub + body


# ------------------------------------------------------------------------------------------ the subscribed phones
def _db(rt: Any) -> Any:
    rt.db.exec(SQL)
    return rt.db


def endpoint_ok(endpoint: str) -> bool:
    """Only a real push service gets our requests (a paired device cannot make JARVIS call any address)."""
    u = urlsplit(endpoint or "")
    host = (u.hostname or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def subscribe(rt: Any, sub: dict, label: str = "") -> bool:
    endpoint = str(sub.get("endpoint") or "")
    keys = sub.get("keys") or {}
    p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
    try:
        if not endpoint_ok(endpoint) or len(unb64u(p256dh)) != 65 or len(unb64u(auth)) != 16:
            return False
    except (ValueError, TypeError):
        return False
    _db(rt).exec("INSERT OR REPLACE INTO webpush (endpoint, p256dh, auth, label, added) VALUES (?,?,?,?,?)",
                 (endpoint, p256dh, auth, label[:60], time.time()))
    return True


def subscriptions(rt: Any) -> list[dict]:
    return [dict(r) for r in _db(rt).all("SELECT * FROM webpush ORDER BY added")]


def unsubscribe(rt: Any, endpoint: str = "") -> int:
    cur = _db(rt).exec("DELETE FROM webpush" + (" WHERE endpoint=?" if endpoint else ""), (endpoint,) if endpoint else ())
    return int(getattr(cur, "rowcount", 0) or 0)


async def send(rt: Any, title: str, body: str, url: str = "./mobile", transport: Any = None) -> int:
    """To every subscribed phone; a subscription the push service says is gone (404 / 410) is removed."""
    import httpx

    from . import tlsctx

    subs = subscriptions(rt)
    if not subs:
        return 0
    payload = json.dumps({"title": title[:80], "body": body[:400], "url": url}, ensure_ascii=False).encode()
    sent = 0
    async with httpx.AsyncClient(verify=tlsctx.context(), transport=transport, timeout=15) as c:
        for s in subs:
            try:
                data = encrypt(payload, s["p256dh"], s["auth"])
                r = await c.post(s["endpoint"], content=data, headers={
                    "Authorization": vapid_header(s["endpoint"]), "Content-Encoding": "aes128gcm", "TTL": "3600",
                    "Content-Type": "application/octet-stream", "Urgency": "normal"})
                if r.status_code in (404, 410):
                    unsubscribe(rt, s["endpoint"])
                elif r.status_code < 300:
                    sent += 1
                else:
                    log.info("web push %s: %s", urlsplit(s["endpoint"]).hostname, r.status_code)
            except Exception as e:  # noqa: BLE001
                log.debug("web push: %s", e)
    return sent
