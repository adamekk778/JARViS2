"""Spec 2026-11-20 §5.5: JARVIS learns from the pages you read – only when you switch it on. Every 10 minutes it reads
the new visits from the history of Chrome, Edge, Brave, Opera, Vivaldi and Firefox (a copy, read-only) and fetches the
pages itself, without cookies – so nothing behind a login and nothing from a private window (those never reach the
history). Banks, e-mail, payments, sign-in pages, local addresses and the sites in "Nikdy se neučit z" are skipped; a
search results page keeps only what you searched for."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import sources
from .store import Doc, domain

log = logging.getLogger("jarvis.webknow")
CHROMIUM_EPOCH = 11644473600          # seconds between 1601-01-01 and 1970-01-01
FIRST_LOOK_S = 24 * 3600              # the first time: the last day only
PER_FILE = 200
TICK_S = 600
START_DELAY_S = 120
# review: a parameter whose name only CONTAINS one of these (reset_token, X-Amz-Signature, pwd…) is secret too
SECRET_PARTS = ("token", "sig", "secret", "pwd", "pass", "key", "auth", "session", "sid", "otp", "code", "nonce", "ticket")
# one-time links: opening them again would unsubscribe you, confirm, reset, log you out or use up a magic link
ONE_TIME = re.compile(r"unsubscribe|odhlas|reset|verif|confirm|potvr|activat|aktivac|logout|log-out|signout|sign-out|magic|"
                      r"password|passwd|heslo|invite|pozvan|oauth|callback|/otp|2fa", re.I)
LAN_SUFFIX = (".local", ".lan", ".internal", ".intranet", ".home", ".box", ".router", ".localdomain", ".corp")
SIGN_IN = ("accounts.", "login.", "auth.", "signin.", "sso.", "checkout.")
SEARCH_HOSTS = {"google.": ("/search", "q"), "bing.com": ("/search", "q"), "duckduckgo.com": ("", "q"),
                "search.seznam.cz": ("", "q"), "search.yahoo.com": ("/search", "p")}
OFFER_TITLE = "Nové: JARVIS se může učit z prohlížeče"
OFFER_TEXT = ("Bude si pamatovat stránky, které čteš (ne bankovnictví, e-mail ani anonymní okna). Zapneš v Nastavení → "
              "Internet a znalosti.")


def history_files(local: Path | None = None, roaming: Path | None = None) -> list[tuple[str, str, Path]]:
    """(browser, "chromium" | "firefox", path) of every profile's history on this PC."""
    local = local or (Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else None)
    roaming = roaming or (Path(os.environ["APPDATA"]) if os.environ.get("APPDATA") else None)
    out: list[tuple[str, str, Path]] = []
    if local and local.exists():
        for name, root in (("Chrome", "Google/Chrome/User Data"), ("Edge", "Microsoft/Edge/User Data"),
                           ("Brave", "BraveSoftware/Brave-Browser/User Data"), ("Vivaldi", "Vivaldi/User Data")):
            out += [(name, "chromium", p) for p in sorted((local / root).glob("*/History")) if p.is_file()]
    if roaming and roaming.exists():
        for name, root in (("Opera", "Opera Software/Opera Stable"), ("Opera GX", "Opera Software/Opera GX Stable")):
            p = roaming / root / "History"
            if p.is_file():
                out.append((name, "chromium", p))
        out += [("Firefox", "firefox", p) for p in sorted((roaming / "Mozilla/Firefox/Profiles").glob("*/places.sqlite")) if p.is_file()]
    return out


def read_history(path: Path, flavor: str, since: float) -> list[tuple[str, str, float]]:
    """(url, title, unix time) of the visits after `since`, oldest first. Missing, locked or broken → []."""
    try:
        with tempfile.TemporaryDirectory(prefix="jarvis-hist-") as tmp:
            copy = Path(tmp) / path.name
            shutil.copyfile(path, copy)
            for ext in ("-wal", "-journal"):
                side = path.with_name(path.name + ext)
                if side.is_file():
                    shutil.copyfile(side, copy.with_name(copy.name + ext))
            con = sqlite3.connect(f"file:{copy.as_posix()}?mode=ro", uri=True)
            try:
                if flavor == "firefox":
                    rows = con.execute("SELECT p.url, p.title, h.visit_date FROM moz_historyvisits h JOIN moz_places p ON p.id = h.place_id "
                                       "WHERE h.visit_date > ? ORDER BY h.visit_date LIMIT ?", (int(since * 1e6), PER_FILE)).fetchall()
                    return [(u, t or "", v / 1e6) for u, t, v in rows if u]
                rows = con.execute("SELECT u.url, u.title, v.visit_time FROM visits v JOIN urls u ON u.id = v.url "
                                   "WHERE v.visit_time > ? ORDER BY v.visit_time LIMIT ?",
                                   (int((since + CHROMIUM_EPOCH) * 1e6), PER_FILE)).fetchall()
                return [(u, t or "", v / 1e6 - CHROMIUM_EPOCH) for u, t, v in rows if u]
            finally:
                con.close()
    except Exception as e:  # noqa: BLE001 – a browser not installed / a file in use / a broken file
        log.debug("history %s: %s", path, e)
        return []


def blocked(url: str, never: list[str]) -> bool:
    p = urlparse(url or "")
    if p.scheme not in ("http", "https"):
        return True
    host = (p.hostname or "").lower()
    if not host or host == "localhost" or "." not in host or host.endswith(LAN_SUFFIX):
        return True
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    except ValueError:
        pass
    for d in never or []:
        d = d.lower().strip().removeprefix("www.")
        if d and (host == d or host.endswith("." + d) or host == "www." + d):
            return True
    if "bank" in host or "paypal." in host or host.startswith(SIGN_IN) or ONE_TIME.search(p.path or ""):
        return True
    return any(part in k.lower() for k in parse_qs(p.query, keep_blank_values=True) for part in SECRET_PARTS)


def search_query(url: str) -> str | None:
    p = urlparse(url or "")
    host = (p.hostname or "").lower().removeprefix("www.")
    for h, (path, key) in SEARCH_HOSTS.items():
        if (host.startswith(h) if h.endswith(".") else host == h) and p.path.startswith(path):
            q = (parse_qs(p.query).get(key) or [""])[0].strip()
            return q or None
    return None


async def _learn(rt, browser_name: str, url: str, title: str, ts: float) -> bool:
    store = rt.webknow
    q = search_query(url)
    if q:
        return store.add(Doc(url=url, title=f"Hledal jsi: {q}", kind="browser", source=browser_name, visited=ts)) is not None
    try:
        from . import youtube

        if youtube.video_id(url):
            return await youtube.learn_video(rt, url) is not None
    except ImportError:
        pass
    from .store import normalize_url

    known = rt.db.one("SELECT id, text FROM web_docs WHERE url=?", (normalize_url(url),))
    if known and known["text"]:                    # read before: only the time of the visit changes
        return store.add(Doc(url=url, title=title, kind="browser", visited=ts)) is not None
    page_title, text = await sources.read_page(rt, url)
    if not text or sources.looks_like_login(page_title, text):
        # a login wall / nothing readable: only what anybody sees – never the title of YOUR signed-in page (review I5)
        return store.add(Doc(url=url, title=page_title or domain(url), kind="browser", source=browser_name, visited=ts)) is not None
    return store.add(Doc(url=url, title=page_title or title or url, kind="browser", text=text[:6000], source=browser_name,
                         visited=ts)) is not None


async def learn_round(rt, now: float | None = None) -> int:
    cfg = rt.cfg.webknow
    now = now or time.time()
    if not cfg.browser or rt.memory.private:
        # what you visit while this is off or in the private mode is never learned later (review I4)
        for _name, _flavor, path in history_files():
            rt.db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (f"webknow_browser_since:{path}", str(now)))
        return 0
    stored = 0
    sem = asyncio.Semaphore(4)
    for name, flavor, path in history_files():
        key = f"webknow_browser_since:{path}"
        row = rt.db.one("SELECT v FROM kv WHERE k=?", (key,))
        since = float(row["v"]) if row else now - FIRST_LOOK_S
        rows = await asyncio.to_thread(read_history, path, flavor, since)
        if not rows:
            continue
        latest: dict[str, tuple[str, float]] = {}
        for url, title, ts in rows:
            if not blocked(url, cfg.never_learn):
                latest[url] = (title, ts)

        async def one(url: str, title: str, ts: float) -> bool:
            async with sem:
                try:
                    return await _learn(rt, name, url, title, ts)
                except Exception as e:  # noqa: BLE001 – one page never stops the rest
                    log.debug("browser %s: %s", url, e)
                    return False

        stored += sum(await asyncio.gather(*(one(u, t, ts) for u, (t, ts) in latest.items())))
        rt.db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (key, str(max(ts for _, _, ts in rows))))
    return stored


def offer(rt) -> None:
    """Once, after the update: tell what learning from the browser is and offer to switch it on with one click."""
    cfg = rt.cfg.webknow
    if cfg.browser or cfg.browser_offered:
        return
    rt.notify(OFFER_TITLE, OFFER_TEXT, speak=False, actions=[{"label": "Zapnout", "action": "webknow_browser_on", "args": {}}])
    rt.update_config({"webknow": {"browser_offered": True}})


async def browser_loop(rt) -> None:
    await asyncio.sleep(START_DELAY_S)
    try:
        offer(rt)
    except Exception as e:  # noqa: BLE001
        log.debug("browser offer: %s", e)
    while True:
        try:
            await learn_round(rt)
        except Exception as e:  # noqa: BLE001 – try again in 10 minutes
            log.warning("učení z prohlížeče: %s", e)
        await asyncio.sleep(TICK_S)
