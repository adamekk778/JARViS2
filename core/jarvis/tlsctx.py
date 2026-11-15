"""One TLS context for the whole process, created once at start-up.

Creating an SSL context the first time initialises OpenSSL and reads the Windows certificate store inside native code
that holds the GIL. On the CI Windows machine that ran at the same moment as the first keyring import (DLL loads) and
pywebview creating its window, and the whole process froze (hang-dump.txt, run 3.10.59). So the one-off native set-up
happens here, serially, before any other thread starts – and every HTTP client reuses the same context afterwards
(which is also faster: no certificate store per request)."""
from __future__ import annotations

import logging
import os
import ssl
import sys
import threading

log = logging.getLogger(__name__)
_lock = threading.Lock()
_ctx: ssl.SSLContext | None = None


def context() -> ssl.SSLContext:
    global _ctx
    with _lock:
        if _ctx is None:
            _ctx = ssl.create_default_context()
        return _ctx


SERVER_AUTH = "1.3.6.1.5.5.7.3.1"
_bundle: str | None = None


def windows_pems(enum=None) -> list[str]:
    """Every certificate Windows trusts for web sites (its ROOT and CA stores), as PEM text. An antivirus that checks
    encrypted connections (Bitdefender, Avast, ESET, Kaspersky…) puts its own certificate here – browsers trust it
    through Windows, and now JARVIS does the same."""
    enum = enum or getattr(ssl, "enum_certificates", None)
    if enum is None:
        return []
    out: list[str] = []
    for store in ("ROOT", "CA"):
        try:
            items = enum(store)
        except Exception as e:  # noqa: BLE001
            log.debug("certificate store %s: %s", store, e)
            continue
        for der, encoding, trust in items:
            if encoding == "x509_asn" and (trust is True or SERVER_AUTH in (trust or ())):
                out.append(ssl.DER_cert_to_PEM_cert(der))
    return out


def use_system_trust(folder=None, enum=None) -> str | None:
    """One certificate list for every library JARVIS uses to reach the internet (httpx, the voice, updates…): the
    usual public list plus everything Windows trusts. Without it an antivirus that inspects HTTPS made JARVIS's
    connections fail while the browser worked. Nothing is switched off – certificates are still checked, just
    against what Windows itself trusts. Returns the path of the list (None when not on Windows / nothing to add)."""
    global _bundle
    if enum is None and sys.platform != "win32":
        return None
    try:
        import certifi
    except ImportError:
        return None
    extra = windows_pems(enum)
    if not extra:
        return None
    from .paths import data_dir

    base = folder or data_dir()
    base.mkdir(parents=True, exist_ok=True)
    path = base / "certificates.pem"
    original = getattr(certifi, "_jarvis_where", None) or certifi.where
    text = open(original(), encoding="ascii", errors="ignore").read().rstrip() + "\n" + "".join(extra)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="ascii", errors="ignore")
    os.replace(tmp, path)
    where = str(path)
    certifi._jarvis_where = original          # type: ignore[attr-defined]
    certifi.where = lambda: where             # httpx, aiohttp (voice) and others ask certifi for the list
    try:
        import certifi.core as core

        core.where = certifi.where
    except Exception:  # noqa: BLE001
        pass
    os.environ.setdefault("SSL_CERT_FILE", where)
    _bundle = where
    log.info("certificates: %d from Windows added to the public list", len(extra))
    return where


def warm_up() -> None:
    """Called from main() before the server, the UI and the background threads start."""
    try:
        use_system_trust()
    except Exception as e:  # noqa: BLE001 – the public list alone still works on most PCs
        log.warning("Windows certificates: %s", e)
    context()
    try:
        from . import secrets

        secrets._keyring()          # the keyring backend detection imports win32 DLLs the first time
    except Exception as e:  # noqa: BLE001 – a missing keyring falls back to the file store later anyway
        log.debug("keyring warm-up: %s", e)
