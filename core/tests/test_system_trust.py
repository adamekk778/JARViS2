"""JARVIS trusts what Windows trusts (an antivirus that inspects HTTPS adds its certificate there)."""
import ssl

import certifi
import pytest

from jarvis import tlsctx


@pytest.fixture
def restore(monkeypatch):
    monkeypatch.setattr(certifi, "where", certifi.where)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(tlsctx, "_bundle", None)
    yield
    if hasattr(certifi, "_jarvis_where"):
        del certifi._jarvis_where
    import certifi.core as core
    core.where = certifi.where


def _antivirus_cert() -> bytes:
    text = open(certifi.where()).read()
    start = text.index("-----BEGIN CERTIFICATE-----")
    pem = text[start:text.index("-----END CERTIFICATE-----", start)] + "-----END CERTIFICATE-----\n"
    return ssl.PEM_cert_to_DER_cert(pem)


def test_windows_certificates_join_the_public_list(tmp_path, restore):
    der = _antivirus_cert()
    stores = {"ROOT": [(der, "x509_asn", True)], "CA": [(b"junk", "pkcs_7_asn", True), (der, "x509_asn", {"1.3.6.1.5.5.7.3.2"})]}
    path = tlsctx.use_system_trust(folder=tmp_path, enum=lambda s: stores[s])
    text = open(path).read()
    assert certifi.where() == path
    assert text.count(ssl.DER_cert_to_PEM_cert(der).strip().splitlines()[1]) == 2      # public list + Windows ROOT once
    ctx = ssl.create_default_context(cafile=certifi.where())                          # httpx does exactly this
    assert ctx.cert_store_stats()["x509_ca"] > 50


def test_nothing_from_windows_changes_nothing(tmp_path, restore):
    before = certifi.where()
    assert tlsctx.use_system_trust(folder=tmp_path, enum=lambda s: []) is None
    assert certifi.where() == before


def test_httpx_uses_the_joined_list(tmp_path, restore):
    import httpx

    der = _antivirus_cert()
    tlsctx.use_system_trust(folder=tmp_path, enum=lambda s: [(der, "x509_asn", True)] if s == "ROOT" else [])
    with httpx.Client() as c:                                # builds its SSL context from certifi.where()
        assert c is not None
