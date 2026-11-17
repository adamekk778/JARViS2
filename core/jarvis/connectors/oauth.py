"""3.12 Sign-in in the browser (OAuth 2 with PKCE) for the services that have no plain key: Microsoft 365, Dropbox.

You create your own free app at the service (2 minutes, the steps are in Propojení) and paste its ID; JARVIS opens the
service's own sign-in page and keeps only the refresh token, in the OS secure storage. No password ever goes through
JARVIS, and no client secret is needed (PKCE, a "public client").

Also the "client credentials" sign-in of accounting services (Fakturoid, iDoklad): an ID and a secret give a token for
two hours; it is kept in memory only.
"""
from __future__ import annotations

import base64
import hashlib
import secrets as pysecrets
import time
from typing import Any
from urllib.parse import urlencode

from .. import secrets
from . import ServiceError, http, need, skey, value


class Pkce:
    def __init__(self, cid: str, auth_url: str, token_url: str, scopes: str, *, client_field: str = "client_id",
                 extra: dict | None = None, scope_on_token: bool = False, name: str = ""):
        self.cid, self.auth_url, self.token_url, self.scopes = cid, auth_url, token_url, scopes
        self.client_field, self.extra, self.scope_on_token, self.name = client_field, extra or {}, scope_on_token, name or cid
        self.pending: dict[str, dict] = {}
        self.access: dict[str, Any] = {"token": "", "until": 0.0}

    def start(self, redirect: str) -> str:
        cid = value(self.cid, self.client_field)
        if not cid:
            raise ValueError("Nejdřív vlož ID aplikace a ulož.")
        verifier = pysecrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = pysecrets.token_urlsafe(24)
        for k in [k for k, v in self.pending.items() if time.time() - v["at"] > 900]:
            self.pending.pop(k, None)
        self.pending[state] = {"verifier": verifier, "redirect": redirect, "at": time.time()}
        q = {"client_id": cid, "response_type": "code", "redirect_uri": redirect, "code_challenge": challenge,
             "code_challenge_method": "S256", "state": state, **self.extra}
        if self.scopes:
            q["scope"] = self.scopes
        return self.auth_url + "?" + urlencode(q)

    async def _token(self, data: dict, transport=None) -> dict:
        data = {"client_id": value(self.cid, self.client_field), **data}
        if self.scope_on_token and self.scopes:
            data["scope"] = self.scopes
        async with http(transport=transport) as c:
            r = await c.post(self.token_url, data=data, headers={"Accept": "application/json"})
        if r.status_code >= 400:
            try:
                d = r.json()
                why = d.get("error_description") or d.get("error") or r.text[:200]
            except Exception:  # noqa: BLE001
                why = r.text[:200]
            raise ServiceError(f"{self.name} přihlášení odmítl: {str(why)[:300]}")
        tok = r.json()
        if tok.get("refresh_token"):
            secrets.set(skey(self.cid, "refresh_token"), tok["refresh_token"])       # some services give a new one each time
        self.access.update(token=tok.get("access_token", ""), until=time.time() + int(tok.get("expires_in", 3600)) - 60)
        return tok

    async def finish(self, code: str, state: str, transport=None) -> str:
        p = self.pending.pop(state, None)
        if not p:
            raise ValueError("Přihlášení vypršelo nebo nepatří k JARVISu – klikni na přihlášení znovu.")
        tok = await self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": p["redirect"],
                                 "code_verifier": p["verifier"]}, transport)
        if not tok.get("refresh_token"):
            raise ServiceError(f"{self.name} nevrátil dlouhodobé přihlášení (refresh token) – zkontroluj nastavení aplikace podle kroků.")
        return f"{self.name} je propojený."

    async def headers(self, transport=None) -> dict:
        need(self.cid)
        if not self.access["token"] or time.time() > self.access["until"]:
            await self._token({"grant_type": "refresh_token", "refresh_token": value(self.cid, "refresh_token")}, transport)
        return {"Authorization": f"Bearer {self.access['token']}"}


class ClientCredentials:
    """ID + secret → a short token (accounting APIs). Kept in memory; asked again when it runs out."""

    def __init__(self, cid: str, token_url: str, *, basic: bool = False, json_body: bool = False, extra: dict | None = None,
                 headers: Any = None, name: str = ""):
        self.cid, self.token_url, self.basic, self.json_body = cid, token_url, basic, json_body
        self.extra, self.headers_fn, self.name = extra or {}, headers, name or cid
        self.access: dict[str, Any] = {"token": "", "until": 0.0, "for": ""}

    async def token(self, transport=None) -> str:
        need(self.cid)
        cid, secret = value(self.cid, "client_id"), value(self.cid, "client_secret")
        if self.access["token"] and time.time() < self.access["until"] and self.access["for"] == cid:
            return self.access["token"]
        body = {"grant_type": "client_credentials", **self.extra}
        hdrs = {"Accept": "application/json", **(self.headers_fn() if self.headers_fn else {})}
        kw: dict[str, Any] = {"headers": hdrs}
        if self.basic:
            kw["auth"] = (cid, secret)
        else:
            body.update(client_id=cid, client_secret=secret)
        kw["json" if self.json_body else "data"] = body
        async with http(transport=transport) as c:
            r = await c.post(self.token_url, **kw)
        if r.status_code >= 400:
            try:
                d = r.json()
                why = d.get("error_description") or d.get("error") or r.text[:200]
            except Exception:  # noqa: BLE001
                why = r.text[:200]
            raise ServiceError(f"{self.name} nepřijal Client ID / Client secret ({r.status_code}: {str(why)[:200]}) – zkontroluj je.")
        tok = r.json()
        self.access.update(token=tok.get("access_token", ""), until=time.time() + int(tok.get("expires_in", 3600)) - 120, **{"for": cid})
        return self.access["token"]

    def forget(self) -> None:
        self.access.update(token="", until=0.0, **{"for": ""})
