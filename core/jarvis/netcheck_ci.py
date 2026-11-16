"""3.12 "Internet on real Windows" – what the packaged JARVIS.exe reaches, tried on a real Windows machine (the CI build)
before a version is released: the Windows certificates, every AI service (with a made-up key: the answer must be the
service saying "wrong key", never a connection or certificate error), song lyrics and covers, the weather and the
update check. `JARVIS.exe --netcheck` prints one JSON line per check; nothing is stored and no real key is used.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

FAKE = "fake-key-for-the-connection-test-0000000000"
SONGS = [("NIGHTS LIKE THIS", "The Kid LAROI, Ty Dolla $ign"), ("Reflections", "The Neighbourhood")]


def _r(name: str, ok: bool, detail: str, ms: float = 0) -> dict:
    return {"check": name, "ok": ok, "detail": detail[:300], "ms": round(ms)}


def _reached(err: str) -> bool:
    """The service answered (a refused key, a limit) – the connection itself works."""
    e = err.lower()
    return any(w in e for w in ("401", "400", "403", "404", "422", "429", "unauthor", "invalid", "api key", "api_key",
                                "authentication", "permission", "forbidden", "not found", "rate", "quota", "odmítl", "klíč", "nečekaná odpověď"))


async def _ai(pid: str, preset: str) -> dict:
    from .config import Brain, ProviderCfg
    from .llm.presets import PRESETS
    from .llm.router import Router

    pr = PRESETS[preset]
    brain = Brain(providers=[ProviderCfg(id=pid, preset=preset, base_url=pr["base_url"], model=pr.get("model", ""))], chain=[pid])
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(Router(brain, lambda _k: FAKE).complete([{"role": "user", "content": "test"}]), 40)
        return _r(f"ai:{preset}", True, "answered", (time.monotonic() - t0) * 1000)
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        return _r(f"ai:{preset}", _reached(msg), msg, (time.monotonic() - t0) * 1000)


async def run() -> list[dict]:
    from . import nowplaying, tlsctx

    out: list[dict] = []
    t0 = time.monotonic()
    try:
        path = tlsctx.use_system_trust()
        import certifi

        out.append(_r("windows-certificates", True, f"list {path or '(nothing added)'}; certifi.where={certifi.where()}",
                      (time.monotonic() - t0) * 1000))
    except Exception as e:  # noqa: BLE001
        out.append(_r("windows-certificates", False, f"{type(e).__name__}: {e}"))
    try:
        ctx = tlsctx.context()
        out.append(_r("tls-context", True, f"{ctx.cert_store_stats()}"))
    except Exception as e:  # noqa: BLE001
        out.append(_r("tls-context", False, f"{type(e).__name__}: {e}"))

    from .llm.presets import PRESETS

    cloud = [k for k, v in PRESETS.items() if v.get("needs_key") and str(v.get("base_url", "")).startswith("https://")]
    out += await asyncio.gather(*(_ai(k, k) for k in cloud))

    for title, artist in SONGS:
        t0 = time.monotonic()
        try:
            r = await nowplaying.Lyrics().get(title, artist)
            ok = bool(r.get("synced") and r.get("lines")) and not r.get("error")
            out.append(_r(f"lyrics:{title}", ok, r.get("error") or f"{len(r.get('lines', []))} timed lines",
                          (time.monotonic() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            out.append(_r(f"lyrics:{title}", False, f"{type(e).__name__}: {e}"))
        t0 = time.monotonic()
        try:
            nowplaying._COVERS.pop((title, artist), None)
            c = await nowplaying.find_cover(title, artist)
            out.append(_r(f"cover:{title}", bool(c), f"{len(c)} bytes" if c else f"none ({nowplaying.NET.get('cover') or 'no match'})",
                          (time.monotonic() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            out.append(_r(f"cover:{title}", False, f"{type(e).__name__}: {e}"))

    import httpx

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(verify=tlsctx.context(), timeout=15) as c:
            g = (await c.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": "Praha", "count": 1})).json()
        out.append(_r("weather", bool(g.get("results")), "Praha found" if g.get("results") else str(g)[:200], (time.monotonic() - t0) * 1000))
    except Exception as e:  # noqa: BLE001
        out.append(_r("weather", False, f"{type(e).__name__}: {e}"))
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(verify=tlsctx.context(), timeout=15, follow_redirects=True) as c:
            r = await c.get("https://api.github.com/repos/adamekk778/JARViS2/releases/latest",
                            headers={"Accept": "application/vnd.github+json"})
        # 403 = the shared CI address hit GitHub's anonymous limit: the connection itself worked
        out.append(_r("update-check", r.status_code in (200, 403), f"HTTP {r.status_code}", (time.monotonic() - t0) * 1000))
    except Exception as e:  # noqa: BLE001
        out.append(_r("update-check", False, f"{type(e).__name__}: {e}"))
    return out


def main(_args: Any = None) -> int:
    import json
    import os

    async def go() -> int:
        try:
            items = await run()
        except BaseException as e:  # noqa: BLE001
            print(json.dumps({"check": "netcheck", "ok": False, "detail": f"{type(e).__name__}: {e}"}), flush=True)
            return 1
        for it in items:
            print(json.dumps(it), flush=True)
        bad = [i["check"] for i in items if not i["ok"]]
        print(json.dumps({"check": "summary", "ok": not bad, "detail": f"{len(items) - len(bad)}/{len(items)} ok; failed: {bad}"}), flush=True)
        return 1 if bad else 0

    code = asyncio.run(go())
    os._exit(code)
