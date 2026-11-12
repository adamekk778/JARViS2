"""The PC's own TLS certificate for JARVIS Link (self-signed; the phone pins its fingerprint).

The private key is stored encrypted; its password lives in the system keyring (Windows Credential Manager)."""
from __future__ import annotations

import datetime
import hashlib
import logging
import secrets as _rand
from pathlib import Path

from .. import paths, secrets

log = logging.getLogger(__name__)
PASS_NAME = "link_tls_pass"


def folder() -> Path:
    d = paths.data_dir() / "link"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fingerprint(cert_pem: bytes) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    der = x509.load_pem_x509_certificate(cert_pem).public_bytes(Encoding.DER)
    return hashlib.sha256(der).hexdigest()


def _make(cert_p: Path, key_p: Path, password: str) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "JARVIS Link")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("jarvis.link")]), critical=False)
            .sign(key, hashes.SHA256()))
    key_p.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.BestAvailableEncryption(password.encode())))
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _key_opens(key_p: Path, password: str) -> bool:
    from cryptography.hazmat.primitives import serialization

    try:
        serialization.load_pem_private_key(key_p.read_bytes(), password.encode())
        return True
    except Exception:  # noqa: BLE001 – wrong password / damaged file
        return False


def ensure() -> dict:
    """{cert, key, password, fp} – made once; made again only if the key can no longer be opened."""
    d = folder()
    cert_p, key_p = d / "link-cert.pem", d / "link-key.pem"
    password = secrets.get(PASS_NAME)
    if not (password and cert_p.exists() and key_p.exists() and _key_opens(key_p, password)):
        password = _rand.token_urlsafe(32)
        secrets.set(PASS_NAME, password)
        _make(cert_p, key_p, password)
        log.info("JARVIS Link: new certificate")
    return {"cert": str(cert_p), "key": str(key_p), "password": password, "fp": fingerprint(cert_p.read_bytes())}
