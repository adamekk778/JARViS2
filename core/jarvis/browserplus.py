"""OMEGA §41 super browser: sort the JARVIS browser's tabs, save / restore a browsing session, record a workflow on a
website and replay it, compare a page's structure over time, find the click route to a page, refuse cookies on a
consent banner, a privacy report (trackers, cookies before consent, third parties), logins about to expire, verify a
download's source, and an overview of subscriptions from e-mailed receipts."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from . import paths
from .comms import fold

# ============================================================================================== 527 tabs
TAB_RULES = [("práce", r"docs\.google|sheets\.google|office\.com|sharepoint|github|gitlab|jira|atlassian|notion|trello|slack|teams\.microsoft|figma|outlook"),
             ("nákupy", r"alza|mall\.cz|czc|amazon|ebay|aliexpress|temu|heureka|datart|ikea|rohlik|kosik|notino|zalando"),
             ("video a hudba", r"youtube|youtu\.be|netflix|twitch|spotify|hbomax|disney|voyo|ivysilani|stream\.cz"),
             ("zprávy", r"idnes|novinky|seznamzpravy|irozhlas|ct24|aktualne|denik|bbc|cnn|reuters|blesk|lidovky|e15"),
             ("sociální sítě", r"facebook|instagram|x\.com|twitter|linkedin|reddit|tiktok|threads"),
             ("hledání", r"google\.[a-z.]+/search|bing\.com/search|seznam\.cz/\?q|duckduckgo"),
             ("banka a úřady", r"banka|bank|airbank|csob|kb\.cz|moneta|fio\.cz|gov\.cz|mojedatovaschranka|identitaobcana|portal\.gov")]


def classify_url(url: str) -> str:
    u = url.lower()
    return next((name for name, rx in TAB_RULES if re.search(rx, u)), "ostatní")


def sort_tabs(tabs: list[dict]) -> dict:
    groups: dict[str, list[dict]] = {}
    seen: Counter = Counter()
    dups = []
    for t in tabs:
        key = t["url"].split("#")[0].rstrip("/")
        seen[key] += 1
        if seen[key] > 1:
            dups.append(t)
        groups.setdefault(classify_url(t["url"]), []).append(t)
    return {"groups": groups, "duplicates": dups, "count": len(tabs)}


# ============================================================================================== 528 / 540 sessions
def _sessions_dir() -> Path:
    d = paths.data_dir() / "browser-sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_session(name: str, tabs: list[dict], note: str = "") -> Path:
    slug = re.sub(r"[^\w-]+", "-", fold(name)).strip("-")[:40] or "relace"
    f = _sessions_dir() / f"{slug}.json"
    f.write_text(json.dumps({"name": name, "saved": time.time(), "note": note, "tabs": [{"url": t["url"], "title": t.get("title", "")} for t in tabs
                                                                                      if t["url"].startswith(("http://", "https://", "file:"))]},
                            ensure_ascii=False, indent=1), encoding="utf-8")
    return f


def load_session(name: str) -> dict:
    slug = re.sub(r"[^\w-]+", "-", fold(name)).strip("-")[:40]
    f = _sessions_dir() / f"{slug}.json"
    if not f.is_file():
        have = [p.stem for p in _sessions_dir().glob("*.json")]
        raise ValueError(f"Relace „{name}“ neexistuje." + (f" Uložené: {', '.join(have)}." if have else ""))
    return json.loads(f.read_text(encoding="utf-8"))


def list_sessions() -> list[dict]:
    out = []
    for f in sorted(_sessions_dir().glob("*.json"), key=lambda p: -p.stat().st_mtime):
        d = json.loads(f.read_text(encoding="utf-8"))
        out.append({"name": d["name"], "tabs": len(d["tabs"]), "saved": d["saved"], "note": d.get("note", "")})
    return out


# ============================================================================================== 529 recording
RECORDER_JS = r"""
(() => {
  if (window.__jarvisRec) return;
  const store = () => { try { return JSON.parse(sessionStorage.getItem('__jarvisRec') || '[]'); } catch (e) { return []; } };
  const push = (ev) => { const a = store(); a.push(ev); sessionStorage.setItem('__jarvisRec', JSON.stringify(a)); };
  window.__jarvisRec = { events: store };
  const label = (e) => {
    if (!e) return '';
    if (e.labels && e.labels[0]) return e.labels[0].innerText.trim();
    return (e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.innerText || e.value || e.name || e.id || '').trim().slice(0, 60);
  };
  push({t: 'nav', url: location.href, ts: Date.now()});
  document.addEventListener('click', (ev) => {
    const e = ev.target.closest('a, button, [role=button], input[type=submit], input[type=button], label, [onclick]');
    if (e && !e.matches('input[type=text], input[type=email], input[type=password], textarea')) push({t: 'click', label: label(e), ts: Date.now()});
  }, true);
  document.addEventListener('change', (ev) => {
    const e = ev.target;
    if (!e.matches('input, textarea, select')) return;
    const secret = e.type === 'password' || /pass|heslo|card|cvv|iban|pin/i.test(e.name + ' ' + e.id + ' ' + e.autocomplete);
    push({t: 'fill', label: label(e), value: secret ? null : (e.type === 'checkbox' ? String(e.checked) : e.value), secret, ts: Date.now()});
  }, true);
})();
"""


def events_to_steps(events: list[dict], start_url: str = "") -> list[str]:
    """Recorded events → the plain steps user_flow understands; secrets become {heslo} and are never stored."""
    steps: list[str] = []
    last_url = start_url
    for e in sorted(events, key=lambda x: x.get("ts", 0)):
        if e["t"] == "nav":
            url = e["url"]
            if url != last_url and not (steps and steps[-1].startswith("klikni")):   # a navigation caused by a click is implied
                steps.append(f"jdi na {url}")
            last_url = url
        elif e["t"] == "click" and e.get("label"):
            steps.append(f"klikni na {e['label']}")
        elif e["t"] == "fill" and e.get("label"):
            val = "{heslo}" if e.get("secret") else (e.get("value") or "")
            if steps and steps[-1].startswith(f"vyplň {e['label']} ="):
                steps[-1] = f"vyplň {e['label']} = {val}"
            else:
                steps.append(f"vyplň {e['label']} = {val}")
    return steps


def _wf_dir() -> Path:
    d = paths.data_dir() / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_workflow(name: str, start_url: str, steps: list[str]) -> Path:
    slug = re.sub(r"[^\w-]+", "-", fold(name)).strip("-")[:40] or "postup"
    f = _wf_dir() / f"{slug}.json"
    f.write_text(json.dumps({"name": name, "url": start_url, "steps": steps, "saved": time.time()}, ensure_ascii=False, indent=1), encoding="utf-8")
    return f


def load_workflow(name: str) -> dict:
    slug = re.sub(r"[^\w-]+", "-", fold(name)).strip("-")[:40]
    f = _wf_dir() / f"{slug}.json"
    if not f.is_file():
        raise ValueError(f"Postup „{name}“ neexistuje.")
    return json.loads(f.read_text(encoding="utf-8"))


# ============================================================================================== 532 structure
STRUCTURE_JS = r"""() => {
  const txt = (e) => (e.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 80);
  const h = [...document.querySelectorAll('h1, h2, h3')].map(e => e.tagName.toLowerCase() + ': ' + txt(e)).filter(x => x.length > 4);
  const land = [...document.querySelectorAll('header, nav, main, aside, footer, [role=navigation], [role=main], [role=search]')]
      .map(e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : ''));
  const forms = [...document.querySelectorAll('form')].map(f => ({action: f.getAttribute('action') || '',
      fields: [...f.querySelectorAll('input, select, textarea')].filter(i => i.type !== 'hidden').map(i => i.name || i.id || i.type)}));
  const buttons = [...document.querySelectorAll('button, [role=button], input[type=submit]')].map(txt).filter(Boolean).slice(0, 60);
  const links = document.querySelectorAll('a[href]').length;
  return {title: document.title, headings: h, landmarks: land, forms, buttons, links};
}"""


def structure_diff(a: dict, b: dict) -> dict:
    def sd(x, y):
        return {"added": [v for v in y if v not in x], "removed": [v for v in x if v not in y]}
    fa = [f"{f['action']}({','.join(f['fields'])})" for f in a.get("forms", [])]
    fb = [f"{f['action']}({','.join(f['fields'])})" for f in b.get("forms", [])]
    out = {"title": [a.get("title"), b.get("title")] if a.get("title") != b.get("title") else None, "headings": sd(a["headings"], b["headings"]),
           "landmarks": sd(a["landmarks"], b["landmarks"]), "forms": sd(fa, fb), "buttons": sd(a["buttons"], b["buttons"]),
           "links": [a["links"], b["links"]] if abs(a["links"] - b["links"]) > max(3, a["links"] * 0.1) else None}
    out["same"] = not (out["title"] or out["links"] or any(v["added"] or v["removed"] for k, v in out.items() if isinstance(v, dict)))
    return out


def _struct_file(url: str) -> Path:
    d = paths.data_dir() / "structure"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".json")


# ============================================================================================== 533 route
_A = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)


async def find_route(client, start: str, target: str, max_pages: int = 60) -> dict:
    """Breadth-first over the site's own links: the shortest click path to a page whose text contains `target`."""
    if not start.startswith(("http://", "https://")):
        start = "https://" + start
    host = urlparse(start).netloc
    goal = fold(target)
    queue = deque([(start, [])])
    seen = {start}
    visited = 0
    while queue and visited < max_pages:
        url, path = queue.popleft()
        try:
            r = await client.get(url, timeout=15)
        except Exception:  # noqa: BLE001 – an unreachable page is skipped
            continue
        visited += 1
        if "html" not in r.headers.get("content-type", "html"):
            continue
        html = r.text
        text = fold(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)))
        if goal in text and path:
            return {"found": True, "url": url, "clicks": path, "visited": visited}
        for href, inner in _A.findall(html):
            nxt = urljoin(url, href.strip())
            label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()[:60] or nxt
            if urlparse(nxt).netloc == host and nxt not in seen and nxt.startswith(("http://", "https://")):
                seen.add(nxt)
                if goal in fold(label):
                    return {"found": True, "url": nxt, "clicks": path + [label], "visited": visited}
                queue.append((nxt, path + [label]))
    return {"found": False, "visited": visited, "clicks": []}


# ============================================================================================== 534 cookie banners
REJECT_SELECTORS = ["#onetrust-reject-all-handler", "#CybotCookiebotDialogBodyButtonDecline", "#didomi-notice-disagree-button",
                    "[data-testid=uc-deny-all-button]", "#cmpwelcomebtnno", ".cc-deny", "button[data-cookiefirst-action=reject]",
                    "#tarteaucitronAllDenied2", ".fc-cta-do-not-consent", "[aria-label='Odmítnout vše']"]
REJECT_TEXTS = ["Odmítnout vše", "Odmítnout všechny", "Odmítnout", "Pouze nezbytné", "Jen nezbytné", "Pouze nutné", "Nesouhlasím", "Zamítnout vše",
                "Reject all", "Reject", "Decline", "Only necessary", "Necessary only", "Deny"]


async def reject_cookies(page) -> dict:
    for sel in REJECT_SELECTORS:
        loc = page.locator(sel).first
        try:
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=3000)
                return {"clicked": True, "how": sel}
        except Exception:  # noqa: BLE001
            continue
    for frame in [page.main_frame, *page.frames]:
        for t in REJECT_TEXTS:
            loc = frame.get_by_role("button", name=re.compile(rf"^\s*{re.escape(t)}\s*$", re.I)).first
            try:
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=3000)
                    return {"clicked": True, "how": t}
            except Exception:  # noqa: BLE001
                continue
    return {"clicked": False, "how": ""}


# ============================================================================================== 539 privacy
TRACKERS = {"google-analytics.com": "Google Analytics", "googletagmanager.com": "Google Tag Manager", "doubleclick.net": "Google reklamy",
            "googlesyndication.com": "Google reklamy", "googleadservices.com": "Google reklamy", "facebook.net": "Facebook pixel",
            "facebook.com/tr": "Facebook pixel", "connect.facebook": "Facebook", "hotjar.com": "Hotjar (nahrávání pohybu myši)",
            "clarity.ms": "Microsoft Clarity (nahrávání relací)", "analytics.tiktok.com": "TikTok pixel", "snap.licdn.com": "LinkedIn Insight",
            "criteo": "Criteo reklamy", "adform.net": "Adform reklamy", "gemius": "Gemius měření", "smartlook": "Smartlook (nahrávání relací)",
            "mouseflow": "Mouseflow", "yandex": "Yandex Metrica", "bat.bing.com": "Microsoft Ads", "c.seznam.cz": "Seznam měření",
            "ssp.seznam.cz": "Seznam reklamy", "tiktok.com/i18n/pixel": "TikTok pixel", "segment.io": "Segment", "mixpanel": "Mixpanel",
            "amplitude.com": "Amplitude", "newrelic": "New Relic", "sentry.io": "Sentry (chyby)"}


def _site(host: str) -> str:
    parts = host.split(":")[0].split(".")
    return ".".join(parts[-3:]) if len(parts) > 2 and parts[-2] in ("co", "com", "org", "gov") else ".".join(parts[-2:])


def privacy_summary(page_url: str, requests: list[str], cookies: list[dict], storage_kb: float) -> dict:
    host = urlparse(page_url).netloc
    own = _site(host)
    third = Counter(_site(urlparse(u).netloc) for u in requests if urlparse(u).netloc and _site(urlparse(u).netloc) != own)
    trackers = sorted({name for u in requests for k, name in TRACKERS.items() if k in u})
    first_c = [c for c in cookies if _site(c.get("domain", "").lstrip(".")) == own]
    third_c = [c for c in cookies if c not in first_c]
    long_lived = [c["name"] for c in cookies if c.get("expires", -1) > time.time() + 365 * 86400]
    score = max(0, 100 - 8 * len(trackers) - 2 * len(third) - 3 * len(third_c) - 2 * len(long_lived))
    return {"third_parties": dict(third.most_common(20)), "trackers": trackers, "cookies_first": [c["name"] for c in first_c],
            "cookies_third": [f"{c['name']} ({c.get('domain', '')})" for c in third_c], "long_lived": long_lived, "storage_kb": round(storage_kb, 1),
            "score": score, "grade": "dobré" if score >= 80 else "průměrné" if score >= 50 else "špatné"}


# ============================================================================================== 537 sessions
LOGIN_COOKIE = re.compile(r"sess|auth|token|login|sid\b|_sid|jwt|remember|logged|user", re.I)


def expiring_logins(cookies: list[dict], within_h: float = 48, now: float | None = None) -> dict:
    now = now or time.time()
    sites: dict[str, dict] = {}
    for c in cookies:
        if not LOGIN_COOKIE.search(c.get("name", "")):
            continue
        site = _site(c.get("domain", "").lstrip("."))
        exp = c.get("expires", -1)
        s = sites.setdefault(site, {"site": site, "cookies": 0, "expires": None, "session_only": False})
        s["cookies"] += 1
        if exp is None or exp < 0:
            s["session_only"] = True
        elif s["expires"] is None or exp < s["expires"]:
            s["expires"] = exp
    out = []
    for s in sites.values():
        left = (s["expires"] - now) / 3600 if s["expires"] else None
        state = "vypršelo" if left is not None and left <= 0 else f"vyprší za {left:.0f} h" if left is not None and left <= within_h else \
                "jen do zavření prohlížeče" if s["session_only"] and left is None else \
                f"platné do {dt.datetime.fromtimestamp(s['expires']):%d. %m.}" if s["expires"] else "?"
        out.append({**s, "hours_left": round(left, 1) if left is not None else None, "state": state,
                    "soon": left is not None and left <= within_h})
    return {"sites": sorted(out, key=lambda x: (x["hours_left"] is None, x["hours_left"] or 0)), "soon": [x["site"] for x in out if x["soon"]]}


# ============================================================================================== 538 downloads
MAGIC = [(b"MZ", "program Windows (exe/dll)"), (b"%PDF", "PDF"), (b"PK\x03\x04", "ZIP (i docx/xlsx/apk/jar)"), (b"\x89PNG", "PNG"),
         (b"\xff\xd8\xff", "JPEG"), (b"Rar!", "RAR"), (b"7z\xbc\xaf", "7-Zip"), (b"\x1f\x8b", "GZIP"), (b"GIF8", "GIF"),
         (b"\xd0\xcf\x11\xe0", "starý Office / MSI"), (b"ID3", "MP3"), (b"OggS", "OGG"), (b"\x00\x00\x00", "MP4 / ISO"), (b"<!DOCTYPE", "HTML stránka"),
         (b"<html", "HTML stránka")]
EXT_KIND = {".exe": "program Windows", ".msi": "starý Office / MSI", ".dll": "program Windows", ".pdf": "PDF", ".zip": "ZIP", ".docx": "ZIP",
            ".xlsx": "ZIP", ".apk": "ZIP", ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".rar": "RAR", ".7z": "7-Zip", ".gz": "GZIP", ".mp3": "MP3"}


def sniff(head: bytes) -> str:
    h = head.lstrip()[:16]
    return next((name for sig, name in MAGIC if h.startswith(sig) or head.startswith(sig)), "neznámý")


async def verify_download(client, url: str, expected_sha256: str = "", max_mb: int = 2048) -> dict:
    import hashlib as _h

    if not url.startswith("https://") and not url.startswith("http://"):
        raise ValueError("Zadej celou adresu souboru (https://…).")
    hops = []
    cur = url
    for _ in range(10):
        r = await client.head(cur, follow_redirects=False, timeout=20)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            nxt = urljoin(cur, r.headers["location"])
            hops.append(nxt)
            cur = nxt
            continue
        break
    final = cur
    issues = []
    if not final.startswith("https://"):
        issues.append("stahuje se bez šifrování (http) – obsah může někdo cestou podvrhnout")
    if urlparse(final).netloc and _site(urlparse(final).netloc) != _site(urlparse(url).netloc):
        issues.append(f"přesměrováno na jinou doménu: {urlparse(final).netloc}")
    sha = _h.sha256()
    size, head = 0, b""
    async with client.stream("GET", final, timeout=120) as r:
        if r.status_code >= 400:
            raise ValueError(f"Soubor nejde stáhnout (HTTP {r.status_code}).")
        ctype = r.headers.get("content-type", "")
        name = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', r.headers.get("content-disposition", ""))
        fname = name.group(1) if name else Path(urlparse(final).path).name
        async for chunk in r.aiter_bytes():
            if not head:
                head = chunk[:64]
            sha.update(chunk)
            size += len(chunk)
            if size > max_mb * 2 ** 20:
                raise ValueError(f"Soubor je větší než {max_mb} MB.")
    kind = sniff(head)
    ext = Path(fname).suffix.lower()
    if ext in EXT_KIND and EXT_KIND[ext].split(" ")[0] not in kind:
        issues.append(f"přípona {ext} neodpovídá obsahu ({kind}) – soubor se tváří jako něco jiného")
    if kind.startswith("HTML") and ext not in (".html", ".htm"):
        issues.append("místo souboru přišla webová stránka (přihlášení / chyba / podvod?)")
    digest = sha.hexdigest()
    match = None
    if expected_sha256:
        match = digest.lower() == expected_sha256.strip().lower()
        if not match:
            issues.append("kontrolní součet NESEDÍ – soubor není ten, který vydavatel zveřejnil")
    return {"url": url, "final_url": final, "redirects": hops, "file": fname, "bytes": size, "type": kind, "content_type": ctype,
            "sha256": digest, "checksum_ok": match, "issues": issues, "ok": not issues}


async def domain_age(client, host: str) -> dict:
    """Registration date from RDAP (the modern WHOIS). Very new domains are a classic sign of scams."""
    dom = _site(host)
    try:
        r = await client.get(f"https://rdap.org/domain/{dom}", timeout=15, follow_redirects=True)
        if r.status_code != 200:
            return {"domain": dom, "known": False}
        ev = {e.get("eventAction"): e.get("eventDate") for e in r.json().get("events", [])}
        reg = ev.get("registration")
        if not reg:
            return {"domain": dom, "known": False}
        days = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(reg.replace("Z", "+00:00"))).days
        return {"domain": dom, "known": True, "registered": reg[:10], "days": days}
    except Exception:  # noqa: BLE001 – RDAP unreachable: just unknown
        return {"domain": dom, "known": False}


# ============================================================================================== 535 subscriptions
AMOUNT = re.compile(r"(\d{1,3}(?:[  .]\d{3})*(?:[,.]\d{2})?|\d+(?:[,.]\d{2})?)\s*(Kč|CZK|€|EUR|\$|USD)|(€|\$)\s?(\d+(?:[.,]\d{2})?)", re.I)
SUB_WORDS = re.compile(r"předplatn|subscription|membership|členstv|obnoven|renew|měsíční|monthly|roční|annual|faktur|invoice|receipt|účtenk|platba|payment", re.I)
RATE = {"Kč": 1.0, "CZK": 1.0, "€": 25.0, "EUR": 25.0, "$": 23.0, "USD": 23.0}


def _amount(text: str) -> tuple[float, str] | None:
    m = AMOUNT.search(text)
    if not m:
        return None
    if m.group(1):
        num, cur = m.group(1), m.group(2)
    else:
        cur, num = m.group(3), m.group(4)
    v = float(re.sub(r"[  ]", "", num).replace(".", "").replace(",", ".")) if re.search(r"\d[ . ]\d{3}", num) else float(num.replace(",", "."))
    return v, cur.upper() if cur.upper() in ("CZK", "EUR", "USD") else cur


def subscriptions(messages: list[dict], today: dt.date | None = None) -> dict:
    """Receipts from the same sender with a similar amount at a regular interval → a subscription, its monthly cost and
    the next expected charge."""
    today = today or dt.date.today()
    by: dict[str, list] = {}
    for m in messages:
        text = f"{m.get('subject', '')}\n{m.get('body', '')}"
        if not SUB_WORDS.search(text):
            continue
        a = _amount(text)
        if not a:
            continue
        sender = (m.get("from_name") or m.get("from") or "?").split("<")[0].strip()
        d = dt.date.fromtimestamp(float(m["date"])) if isinstance(m.get("date"), (int, float)) else dt.date.fromisoformat(str(m["date"])[:10])
        by.setdefault(fold(sender), []).append({"sender": sender, "date": d, "amount": a[0], "cur": a[1], "subject": m.get("subject", "")})
    subs = []
    for items in by.values():
        items.sort(key=lambda x: x["date"])
        if len(items) < 2:
            continue
        gaps = [(b["date"] - a["date"]).days for a, b in zip(items, items[1:])]
        g = sorted(gaps)[len(gaps) // 2]
        period = "měsíčně" if 25 <= g <= 35 else "ročně" if 350 <= g <= 380 else "týdně" if 6 <= g <= 8 else "čtvrtletně" if 85 <= g <= 95 else None
        if not period:
            continue
        last = items[-1]
        per_month = last["amount"] * RATE.get(last["cur"], 1.0) * {"měsíčně": 1, "ročně": 1 / 12, "týdně": 4.345, "čtvrtletně": 1 / 3}[period]
        nxt = last["date"] + dt.timedelta(days=g)
        price_up = len(items) >= 2 and items[-1]["amount"] > items[-2]["amount"] * 1.02
        subs.append({"service": last["sender"], "period": period, "amount": last["amount"], "currency": last["cur"], "per_month_czk": round(per_month),
                     "last": last["date"].isoformat(), "next": nxt.isoformat(), "charges": len(items), "price_up": price_up,
                     "stale": (today - last["date"]).days > g * 1.5})
    subs.sort(key=lambda s: -s["per_month_czk"])
    active = [s for s in subs if not s["stale"]]
    return {"subscriptions": subs, "monthly_czk": sum(s["per_month_czk"] for s in active), "yearly_czk": 12 * sum(s["per_month_czk"] for s in active)}


def page_info(p: Any) -> dict:
    return {"url": p.url, "title": ""}
