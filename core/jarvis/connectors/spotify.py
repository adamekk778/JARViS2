"""3.12 Spotify: the exact place in the song (to the tenth of a second, also for a song that was already playing) and
the right cover, straight from your Spotify account – the lyrics in the notch follow it exactly. Read-only: JARVIS only
asks what is playing. You sign in once (PKCE, your own free Spotify app's Client ID; no secret is stored)."""
from __future__ import annotations

import base64
import hashlib
import secrets as pysecrets
import time
from typing import Any

from .. import secrets
from . import http, need, register, skey, value

AUTH = "https://accounts.spotify.com/authorize"
TOKEN = "https://accounts.spotify.com/api/token"
SCOPES = "user-read-currently-playing user-read-playback-state"
_PENDING: dict[str, dict] = {}
_ACCESS: dict[str, Any] = {"token": "", "until": 0.0}


async def _test(rt: Any) -> str:
    now = await current()
    if not now:
        return "Přihlášeno. Teď nic nehraje."
    return f"Přihlášeno – hraje {now['title']} ({now['artist']})."


register("spotify", "Spotify (přesné texty písní)", "spotify-logo", [
    {"key": "client_id", "label": "Client ID", "secret": False, "hint": "32 znaků z developer.spotify.com"},
], [
    "Otevři developer.spotify.com/dashboard a přihlas se svým Spotify účtem.",
    "Create app: název JARVIS, popis cokoli, Redirect URI přesně: http://127.0.0.1:8765/api/oauth/spotify, zaškrtni Web API.",
    "Otevři aplikaci → Settings a zkopíruj Client ID sem, ulož.",
    "Klikni „Přihlásit se Spotify“ a povol přístup (jen čtení, co právě hraje).",
], url="https://developer.spotify.com/dashboard", oauth=True,
    what="Přesné místo v písničce a obal přímo ze Spotify – texty v notchi jdou na desetinu sekundy.", test=_test, group="music", login="Přihlásit se Spotify",
    probe={"method": "GET", "url": "https://api.spotify.com/v1/me/player/currently-playing", "headers": {"Authorization": "Bearer FAKE"}})


def start(redirect: str) -> str:
    cid = value("spotify", "client_id")
    if not cid:
        raise ValueError("Nejdřív vlož Client ID.")
    verifier = pysecrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = pysecrets.token_urlsafe(24)
    _PENDING[state] = {"verifier": verifier, "redirect": redirect, "at": time.time()}
    from urllib.parse import urlencode

    return AUTH + "?" + urlencode({"client_id": cid, "response_type": "code", "redirect_uri": redirect, "scope": SCOPES,
                                   "code_challenge_method": "S256", "code_challenge": challenge, "state": state})


async def finish(code: str, state: str, transport=None) -> str:
    p = _PENDING.pop(state, None)
    if not p:
        raise ValueError("Přihlášení vypršelo nebo nepatří k JARVISu – zkus „Přihlásit se Spotify“ znovu.")
    async with http(transport=transport) as c:
        r = await c.post(TOKEN, data={"grant_type": "authorization_code", "code": code, "redirect_uri": p["redirect"],
                                      "client_id": value("spotify", "client_id"), "code_verifier": p["verifier"]})
        r.raise_for_status()
        tok = r.json()
    secrets.set(skey("spotify", "refresh_token"), tok.get("refresh_token", ""))
    _ACCESS.update(token=tok.get("access_token", ""), until=time.time() + int(tok.get("expires_in", 3600)) - 60)
    return "Spotify je propojený."


async def _auth(transport=None) -> dict:
    need("spotify")
    if not _ACCESS["token"] or time.time() > _ACCESS["until"]:
        async with http(transport=transport) as c:
            r = await c.post(TOKEN, data={"grant_type": "refresh_token", "refresh_token": value("spotify", "refresh_token"),
                                          "client_id": value("spotify", "client_id")})
            r.raise_for_status()
            tok = r.json()
        if tok.get("refresh_token"):
            secrets.set(skey("spotify", "refresh_token"), tok["refresh_token"])     # PKCE: a new one each time
        _ACCESS.update(token=tok["access_token"], until=time.time() + int(tok.get("expires_in", 3600)) - 60)
    return {"Authorization": f"Bearer {_ACCESS['token']}"}


async def current(transport=None) -> dict | None:
    """What plays on your Spotify now: title, artists, position (s), length (s), playing, the cover's address."""
    async with http(transport=transport, timeout=6) as c:
        r = await c.get("https://api.spotify.com/v1/me/player/currently-playing", headers=await _auth(transport))
    if r.status_code == 204 or not r.content:
        return None
    r.raise_for_status()
    d = r.json()
    item = d.get("item") or {}
    if not item:
        return None
    images = sorted((item.get("album") or {}).get("images") or [], key=lambda x: -(x.get("width") or 0))
    return {"title": item.get("name", ""), "artist": ", ".join(a.get("name", "") for a in item.get("artists") or []),
            "main_artist": ((item.get("artists") or [{}])[0]).get("name", ""), "position": (d.get("progress_ms") or 0) / 1000,
            "duration": (item.get("duration_ms") or 0) / 1000, "playing": bool(d.get("is_playing")),
            "cover": images[0]["url"] if images else "", "at": time.time()}
