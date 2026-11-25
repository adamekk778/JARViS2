"""3.20 Propojení+ (ideas 421–440): Czech and home services that the connectors did not have yet.

Each service is a small client with a parser that the tests feed with real-shaped answers. Keys and passwords live in
the keyring (Nastavení → Propojení), never in the settings file. Services without an API (EduPage, Rohlík, ČSFD,
Databáze knih, the electricity distributors' portals) are honest about it: JARVIS opens the page, or imports the file
you download there."""
from __future__ import annotations

import csv
import datetime as dt
import html
import io
import json
import math
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote_plus

from .connectors import call, need, register, value


def fold(s: str) -> str:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_xml(text: str | bytes) -> ET.Element:
    """XML from a service: no DOCTYPE or ENTITY allowed (no entity expansion, nothing fetched from elsewhere)."""
    raw = text.encode("utf-8") if isinstance(text, str) else text
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)", raw, re.I):
        raise ValueError("Odpověď služby obsahuje nepovolené části XML – nečtu ji.")
    return ET.fromstring(raw)  # noqa: S314 – checked above


def strip_html(s: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


# ------------------------------------------------------------------ (422) Bakaláři
register("bakalari", "Bakaláři (škola)", "graduation-cap", [
    {"key": "url", "label": "Adresa školy", "secret": False, "hint": "https://bakalari.skola.cz/bakaweb"},
    {"key": "username", "label": "Uživatel", "secret": False, "hint": "přihlašovací jméno rodiče nebo žáka"},
    {"key": "password", "label": "Heslo", "secret": True, "hint": ""},
], [
    "Adresu najdeš v aplikaci Bakaláři nebo na webu školy (končí třeba /bakaweb).",
    "Použij účet rodiče – JARVIS jen čte známky, úkoly a zprávy (Komens).",
], url="https://www.bakalari.cz", what="Nové známky, domácí úkoly a zprávy ze školy dětí – jen čtení.", group="tasks")

_BAKA: dict[str, Any] = {"token": "", "until": 0.0}


async def bakalari_token(transport=None) -> str:
    need("bakalari")
    if _BAKA["token"] and _BAKA["until"] > time.time() + 30:
        return str(_BAKA["token"])
    base = value("bakalari", "url").rstrip("/")
    r = await call("POST", f"{base}/api/login", transport=transport, headers={"Content-Type": "application/x-www-form-urlencoded"},
                   content=f"client_id=ANDR&grant_type=password&username={quote_plus(value('bakalari', 'username'))}"
                           f"&password={quote_plus(value('bakalari', 'password'))}")
    _BAKA.update(token=r.get("access_token", ""), until=time.time() + float(r.get("expires_in", 3000)))
    return str(_BAKA["token"])


async def bakalari(path: str, method: str = "GET", transport=None, **params) -> Any:
    tok = await bakalari_token(transport)
    base = value("bakalari", "url").rstrip("/")
    return await call(method, f"{base}/api/3/{path}", transport=transport, params=params or None, headers={"Authorization": f"Bearer {tok}"})


def parse_marks(data: dict, since: dt.date | None = None) -> list[dict]:
    out = []
    for subj in data.get("Subjects", []) or []:
        name = (subj.get("Subject") or {}).get("Name", "")
        for m in subj.get("Marks", []) or []:
            day = str(m.get("MarkDate") or m.get("EditDate") or "")[:10]
            if since and day and day < since.isoformat():
                continue
            out.append({"subject": name, "mark": str(m.get("MarkText") or ""), "weight": m.get("Weight"), "what": m.get("Caption") or m.get("Theme") or "",
                        "date": day, "new": bool(m.get("IsNew")), "average": subj.get("AverageText", "")})
    return sorted(out, key=lambda x: x["date"], reverse=True)


def parse_homework(data: dict, today: dt.date) -> list[dict]:
    out = []
    for h in data.get("Homeworks", []) or []:
        due = str(h.get("DateEnd") or "")[:10]
        if h.get("Done") or (due and due < today.isoformat()):
            continue
        out.append({"subject": (h.get("Subject") or {}).get("Name", ""), "task": strip_html(h.get("Content", ""))[:300], "due": due})
    return sorted(out, key=lambda x: x["due"])


def parse_komens(data: dict) -> list[dict]:
    return [{"title": m.get("Title", ""), "from": (m.get("Sender") or {}).get("Name", ""), "date": str(m.get("SentDate", ""))[:10],
             "text": strip_html(m.get("Text", ""))[:500], "read": bool(m.get("Read"))} for m in data.get("Messages", []) or []]


EDUPAGE = ("EduPage nemá veřejné rozhraní pro jiné aplikace – známky a úkoly z něj JARVIS neumí číst. Pomůže, když ti EduPage posílá "
           "upozornění e-mailem: ty JARVIS přečte a shrne.")


# ------------------------------------------------------------------ (426) Mapy.cz
register("mapycz", "Mapy.cz", "map", [
    {"key": "api_key", "label": "API klíč", "secret": True, "hint": "z developer.mapy.com"},
], [
    "Na developer.mapy.com se přihlas Seznam účtem a vytvoř projekt.",
    "Zkopíruj API klíč sem (základní objem dotazů je zdarma).",
], url="https://developer.mapy.com", what="Trasy, vzdálenosti a tvoje oblíbená místa z Mapy.cz.", group="travel")

ROUTE_TYPES = {"horsk": "bike_mountain", "turist": "foot_hiking", "auto": "car_fast", "car": "car_fast", "pesky": "foot_fast", "pesi": "foot_fast",
               "pesk": "foot_fast", "kolo": "bike_road", "kole": "bike_road", "cykl": "bike_road", "bike": "bike_road"}


async def mapy_geocode(query: str, transport=None) -> dict | None:
    need("mapycz")
    r = await call("GET", "https://api.mapy.cz/v1/geocode", transport=transport,
                   params={"query": query, "lang": "cs", "limit": 1, "apikey": value("mapycz", "api_key")})
    items = r.get("items") or []
    if not items:
        return None
    it = items[0]
    return {"name": it.get("name", query), "where": it.get("location", ""), "lon": it["position"]["lon"], "lat": it["position"]["lat"]}


def route_type(text: str) -> str:
    t = fold(text)
    return next((v for k, v in ROUTE_TYPES.items() if k in t), "car_fast")


async def mapy_route(a: dict, b: dict, kind: str = "car_fast", transport=None) -> dict:
    need("mapycz")
    r = await call("GET", "https://api.mapy.cz/v1/routing/route", transport=transport,
                   params={"start": f"{a['lon']},{a['lat']}", "end": f"{b['lon']},{b['lat']}", "routeType": kind, "lang": "cs",
                           "apikey": value("mapycz", "api_key")})
    km = float(r.get("length", 0)) / 1000
    mins = float(r.get("duration", 0)) / 60
    link = f"https://mapy.cz/fnc/v1/route?start={a['lon']},{a['lat']}&end={b['lon']},{b['lat']}&routeType={kind}"
    return {"km": round(km, 1), "minutes": round(mins), "link": link}


def _places(rt: Any) -> dict[str, list[str]]:
    row = rt.db.one("SELECT v FROM kv WHERE k='lx_places'")
    return json.loads(row["v"]) if row else {}


def places_get(rt: Any) -> dict[str, str]:
    """Your favourite places: the name as you said it → the address."""
    return {name: where for name, where in _places(rt).values()}


def places_set(rt: Any, name: str, where: str) -> None:
    p = _places(rt)
    p[fold(name)] = [name.strip(), where.strip()]
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('lx_places', ?)", (json.dumps(p, ensure_ascii=False),))


def resolve_place(rt: Any, text: str) -> str:
    hit = _places(rt).get(fold(text))
    return hit[1] if hit else text


# ------------------------------------------------------------------ (431) Datová schránka (jen čtení)
register("isds", "Datová schránka", "inbox", [
    {"key": "username", "label": "Uživatelské jméno", "secret": False, "hint": "6–12 znaků"},
    {"key": "password", "label": "Heslo", "secret": True, "hint": ""},
], [
    "DŮLEŽITÉ: přihlášení osoby, která smí číst zprávy, se počítá jako doručení všech dodaných zpráv (běží lhůty).",
    "Proto v datové schránce zřiď pověřenou osobu jen s právem zobrazit seznamy zpráv a dodejky – ne číst obsah.",
    "Její jméno a heslo dej sem. JARVIS jen hlídá, že přišla nová zpráva, a řekne od koho; otevřeš ji sám.",
], url="https://www.mojedatovaschranka.cz", what="Upozornění na novou zprávu v datové schránce – jen seznam, nic neotevírá.", group="work")

ISDS_URL = "https://ws1.mojedatovaschranka.cz/DS/dx"
ISDS_BODY = ('<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
             'xmlns:v20="http://isds.czechpoint.cz/v20"><soapenv:Body><v20:GetListOfReceivedMessages><v20:dmFromTime>{a}</v20:dmFromTime>'
             '<v20:dmToTime>{b}</v20:dmToTime><v20:dmRecipientOrgUnitNum/><v20:dmStatusFilter>-1</v20:dmStatusFilter>'
             '<v20:dmOffset>1</v20:dmOffset><v20:dmLimit>50</v20:dmLimit></v20:GetListOfReceivedMessages></soapenv:Body></soapenv:Envelope>')
ISDS_STATUS = {"1": "podána", "2": "dostala razítko", "3": "neprošla antivirem", "4": "dodána", "5": "doručena fikcí", "6": "doručena",
               "7": "přečtena", "8": "nedoručitelná", "9": "smazána", "10": "v trezoru"}


def parse_isds_list(xml: str) -> list[dict]:
    root = parse_xml(xml)
    out = []
    for rec in root.iter():
        if local(rec.tag) != "dmRecord":
            continue
        f = {local(ch.tag): (ch.text or "").strip() for ch in rec}
        out.append({"id": f.get("dmID", ""), "from": f.get("dmSender", ""), "subject": f.get("dmAnnotation", ""),
                    "delivered": f.get("dmDeliveryTime", ""), "status": ISDS_STATUS.get(f.get("dmMessageStatus", ""), f.get("dmMessageStatus", ""))})
    status = next((e.text for e in root.iter() if local(e.tag) == "dmStatusCode"), "0000")
    if status not in ("0000", None):
        msg = next((e.text for e in root.iter() if local(e.tag) == "dmStatusMessage"), "")
        raise ValueError(f"Datová schránka odpověděla: {msg or status}")
    return out


async def isds_received(days: int = 30, transport=None) -> list[dict]:
    need("isds")
    import httpx

    from .connectors import http

    now = dt.datetime.now(dt.timezone.utc)
    body = ISDS_BODY.format(a=(now - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), b=now.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    async with http(transport=transport, timeout=30) as c:
        r = await c.post(ISDS_URL, content=body.encode(), auth=httpx.BasicAuth(value("isds", "username"), value("isds", "password")),
                         headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""})
        if r.status_code == 401:
            raise ValueError("Datová schránka nepřijala jméno nebo heslo.")
        r.raise_for_status()
        return parse_isds_list(r.text)


# ------------------------------------------------------------------ (433) Strava, Garmin files
register("strava", "Strava", "activity", [
    {"key": "client_id", "label": "Client ID", "secret": False, "hint": "číslo z strava.com/settings/api"},
    {"key": "client_secret", "label": "Client Secret", "secret": True, "hint": ""},
    {"key": "refresh_token", "label": "Refresh token", "secret": True, "hint": "s oprávněním activity:read"},
], [
    "Na strava.com/settings/api si vytvoř aplikaci (Authorization Callback Domain: localhost).",
    "Zkopíruj Client ID a Client Secret.",
    "Refresh token s oprávněním activity:read získáš podle návodu Stravy (Getting Started → OAuth) a vložíš sem.",
], url="https://www.strava.com/settings/api", what="Tvoje aktivity ze Stravy (běh, kolo, chůze) do přehledu zdraví a tréninku.", group="travel")

_STRAVA: dict[str, Any] = {"token": "", "until": 0.0}
STRAVA_KIND = {"Run": "run", "TrailRun": "run", "Ride": "bike", "VirtualRide": "bike", "EBikeRide": "bike", "Walk": "walk", "Hike": "walk",
               "Swim": "swim", "WeightTraining": "gym", "Workout": "gym", "Yoga": "yoga", "NordicSki": "ski", "AlpineSki": "ski"}


async def strava_token(transport=None) -> str:
    need("strava")
    if _STRAVA["token"] and _STRAVA["until"] > time.time() + 60:
        return str(_STRAVA["token"])
    r = await call("POST", "https://www.strava.com/oauth/token", transport=transport,
                   data={"client_id": value("strava", "client_id"), "client_secret": value("strava", "client_secret"),
                         "grant_type": "refresh_token", "refresh_token": value("strava", "refresh_token")})
    _STRAVA.update(token=r.get("access_token", ""), until=float(r.get("expires_at", time.time() + 3600)))
    if r.get("refresh_token") and r["refresh_token"] != value("strava", "refresh_token"):
        from . import secrets as _s

        _s.set("conn.strava.refresh_token", r["refresh_token"])            # Strava may rotate it
    return str(_STRAVA["token"])


def parse_strava(items: list[dict]) -> list[dict]:
    out = []
    for a in items or []:
        out.append({"id": a.get("id"), "kind": STRAVA_KIND.get(a.get("sport_type") or a.get("type") or "", "other"), "name": a.get("name", ""),
                    "km": round(float(a.get("distance", 0)) / 1000, 2), "minutes": round(float(a.get("moving_time", 0)) / 60, 1),
                    "start": a.get("start_date_local", ""), "hr": a.get("average_heartrate"), "kcal": a.get("kilojoules")})
    return out


async def strava_activities(days: int = 14, transport=None) -> list[dict]:
    tok = await strava_token(transport)
    after = int(time.time() - days * 86400)
    r = await call("GET", "https://www.strava.com/api/v3/athlete/activities", transport=transport, params={"after": after, "per_page": 60},
                   headers={"Authorization": f"Bearer {tok}"})
    return parse_strava(r if isinstance(r, list) else [])


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def parse_gpx(text: str) -> dict:
    """A GPX track (Garmin, Strava, any watch): distance, time, elevation gain."""
    root = parse_xml(text)
    pts = []
    for p in root.iter():
        if local(p.tag) == "trkpt":
            ele = next((c.text for c in p if local(c.tag) == "ele"), None)
            tm = next((c.text for c in p if local(c.tag) == "time"), None)
            pts.append((float(p.get("lat", 0)), float(p.get("lon", 0)), float(ele) if ele else None, tm))
    if len(pts) < 2:
        raise ValueError("V GPX není trasa.")
    km = sum(haversine(pts[i][:2], pts[i + 1][:2]) for i in range(len(pts) - 1))
    gain = sum(max(0.0, (pts[i + 1][2] or 0) - (pts[i][2] or 0)) for i in range(len(pts) - 1) if pts[i][2] is not None and pts[i + 1][2] is not None)
    minutes = 0.0
    if pts[0][3] and pts[-1][3]:
        a = dt.datetime.fromisoformat(pts[0][3].replace("Z", "+00:00"))
        b = dt.datetime.fromisoformat(pts[-1][3].replace("Z", "+00:00"))
        minutes = (b - a).total_seconds() / 60
    return {"km": round(km, 2), "minutes": round(minutes, 1), "gain_m": round(gain), "start": pts[0][3] or ""}


def parse_garmin_csv(text: str) -> list[dict]:
    """Garmin Connect → Activities → Export CSV."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    out = []
    for r in rows:
        kind = fold(r.get("Activity Type") or r.get("Typ aktivity") or "")
        t = r.get("Time") or r.get("Čas") or "0:00:00"
        parts = [float(x) for x in re.findall(r"[\d.]+", t)]
        while len(parts) < 3:
            parts.insert(0, 0.0)
        out.append({"kind": "run" if "run" in kind or "beh" in kind else "bike" if "cycl" in kind or "cykl" in kind else "walk" if "walk" in kind or "chuz" in kind else "other",
                    "name": r.get("Title") or r.get("Název") or "", "start": r.get("Date") or r.get("Datum") or "",
                    "km": float((r.get("Distance") or r.get("Vzdálenost") or "0").replace(",", ".") or 0),
                    "minutes": round(parts[-3] * 60 + parts[-2] + parts[-1] / 60, 1),
                    "hr": float(r.get("Avg HR") or r.get("Prům. TF") or 0) or None})
    return out


# ------------------------------------------------------------------ (436) Plex, Jellyfin
register("plex", "Plex", "film", [
    {"key": "url", "label": "Adresa serveru", "secret": False, "hint": "http://192.168.1.10:32400"},
    {"key": "token", "label": "X-Plex-Token", "secret": True, "hint": "support.plex.tv → Finding an authentication token"},
], ["Token najdeš podle návodu Plexu „Finding an authentication token“ (z webového přehrávače).", "Adresu serveru i token vlož sem."],
    url="https://support.plex.tv/articles/204059436", what="Co se právě přehrává na tvém Plexu a ovládání přehrávání.", group="music")
register("jellyfin", "Jellyfin", "film", [
    {"key": "url", "label": "Adresa serveru", "secret": False, "hint": "http://192.168.1.10:8096"},
    {"key": "api_key", "label": "API klíč", "secret": True, "hint": "Ovládací panel → API klíče"},
], ["V Jellyfinu: Ovládací panel → API klíče → +, název JARVIS.", "Adresu serveru a klíč vlož sem."],
    url="https://jellyfin.org/docs/", what="Co se přehrává na Jellyfinu, pauza, další, stop.", group="music")


def parse_plex_sessions(xml: str) -> list[dict]:
    root = parse_xml(xml)
    out = []
    for v in root:
        if local(v.tag) not in ("Video", "Track", "Episode"):
            continue
        player = next((c for c in v if local(c.tag) == "Player"), None)
        user = next((c for c in v if local(c.tag) == "User"), None)
        title = v.get("title", "")
        if v.get("grandparentTitle"):
            title = f"{v.get('grandparentTitle')} – {title}"
        out.append({"title": title, "user": user.get("title", "") if user is not None else "", "device": player.get("title", "") if player is not None else "",
                    "state": player.get("state", "") if player is not None else "", "client": player.get("machineIdentifier", "") if player is not None else "",
                    "progress": round(100 * float(v.get("viewOffset", 0)) / float(v.get("duration", 1) or 1))})
    return out


def parse_jellyfin_sessions(items: list[dict]) -> list[dict]:
    out = []
    for s in items or []:
        it = s.get("NowPlayingItem")
        if not it:
            continue
        title = it.get("Name", "")
        if it.get("SeriesName"):
            title = f"{it['SeriesName']} – {title}"
        out.append({"id": s.get("Id", ""), "title": title, "user": s.get("UserName", ""), "device": s.get("DeviceName", ""),
                    "state": "paused" if (s.get("PlayState") or {}).get("IsPaused") else "playing"})
    return out


JF_CMD = {"pauz": "Pause", "pause": "Pause", "pokrac": "Unpause", "play": "Unpause", "pust": "Unpause", "stop": "Stop", "zastav": "Stop",
          "dalsi": "NextTrack", "next": "NextTrack", "predchoz": "PreviousTrack"}


async def plex_sessions(transport=None) -> list[dict]:
    need("plex")
    from .connectors import http

    async with http(transport=transport) as c:
        r = await c.get(value("plex", "url").rstrip("/") + "/status/sessions", headers={"X-Plex-Token": value("plex", "token"), "Accept": "application/xml"})
        r.raise_for_status()
        return parse_plex_sessions(r.text)


async def jellyfin(path: str, method: str = "GET", transport=None) -> Any:
    need("jellyfin")
    return await call(method, value("jellyfin", "url").rstrip("/") + path, transport=transport,
                      headers={"Authorization": f'MediaBrowser Token="{value("jellyfin", "api_key")}"'})


# ------------------------------------------------------------------ (437) Nextcloud
register("nextcloud", "Nextcloud", "cloud", [
    {"key": "url", "label": "Adresa", "secret": False, "hint": "https://cloud.example.cz"},
    {"key": "username", "label": "Uživatel", "secret": False, "hint": ""},
    {"key": "app_password", "label": "Heslo aplikace", "secret": True, "hint": "Nastavení → Zabezpečení → Vytvořit heslo aplikace"},
], ["V Nextcloudu: Osobní nastavení → Zabezpečení → Zařízení a sezení → Vytvořit nové heslo aplikace (JARVIS).", "Adresu, jméno a heslo aplikace vlož sem."],
    url="https://docs.nextcloud.com", what="Hledání souborů a nadcházející události ve tvém Nextcloudu.", group="work")

NC_SEARCH = ('<?xml version="1.0"?><d:searchrequest xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns"><d:basicsearch><d:select><d:prop>'
             '<d:displayname/><d:getcontentlength/><d:getlastmodified/></d:prop></d:select><d:from><d:scope><d:href>/files/{user}</d:href>'
             '<d:depth>infinity</d:depth></d:scope></d:from><d:where><d:like><d:prop><d:displayname/></d:prop><d:literal>%{q}%</d:literal>'
             '</d:like></d:where><d:orderby/><d:limit><d:nresults>20</d:nresults></d:limit></d:basicsearch></d:searchrequest>')
NC_REPORT = ('<?xml version="1.0"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><c:calendar-data/></d:prop>'
             '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"><c:time-range start="{a}" end="{b}"/></c:comp-filter>'
             '</c:comp-filter></c:filter></c:calendar-query>')


def parse_dav_files(xml: str, user: str) -> list[dict]:
    root = parse_xml(xml)
    out = []
    for resp in root:
        if local(resp.tag) != "response":
            continue
        href = next((e.text for e in resp.iter() if local(e.tag) == "href"), "") or ""
        name = next((e.text for e in resp.iter() if local(e.tag) == "displayname"), "") or href.rsplit("/", 1)[-1]
        size = next((e.text for e in resp.iter() if local(e.tag) == "getcontentlength"), None)
        path = re.sub(rf"^.*/files/{re.escape(user)}", "", href)
        out.append({"name": name, "path": path, "size": int(size) if size and size.isdigit() else None})
    return out


def parse_caldav_events(xml: str) -> list[dict]:
    from icalendar import Calendar

    root = parse_xml(xml)
    out = []
    for e in root.iter():
        if local(e.tag) == "calendar-data" and e.text:
            cal = Calendar.from_ical(e.text)
            for ev in cal.walk("VEVENT"):
                start = ev.get("DTSTART").dt if ev.get("DTSTART") else None
                out.append({"title": str(ev.get("SUMMARY", "")), "start": start.isoformat() if start else "", "where": str(ev.get("LOCATION", "") or "")})
    return sorted(out, key=lambda x: x["start"])


async def nextcloud(method: str, path: str, body: str, depth: str = "1", transport=None) -> str:
    need("nextcloud")
    import httpx

    from .connectors import http

    async with http(transport=transport) as c:
        r = await c.request(method, value("nextcloud", "url").rstrip("/") + "/remote.php/dav" + path, content=body.encode(),
                            auth=httpx.BasicAuth(value("nextcloud", "username"), value("nextcloud", "app_password")),
                            headers={"Content-Type": "text/xml; charset=utf-8", "Depth": depth})
        if r.status_code not in (200, 207):
            r.raise_for_status()
        return r.text


# ------------------------------------------------------------------ (438) Synology
register("synology", "Synology NAS", "hard-drive", [
    {"key": "url", "label": "Adresa", "secret": False, "hint": "https://nas.local:5001"},
    {"key": "username", "label": "Uživatel", "secret": False, "hint": "ideálně zvláštní účet jen pro čtení"},
    {"key": "password", "label": "Heslo", "secret": True, "hint": ""},
], ["V DSM si vytvoř uživatele JARVIS (stačí běžný uživatel bez práv měnit nastavení).", "Adresu, jméno a heslo vlož sem."],
    url="https://kb.synology.com", what="Stav disků a svazků, volné místo a výsledek posledních záloh na NAS.", group="work")


def parse_syno_storage(data: dict) -> dict:
    d = data.get("data", data)
    vols = []
    for v in d.get("volumes", []) or []:
        size = v.get("size") or {}
        tot, used = float(size.get("total", 0) or 0), float(size.get("used", 0) or 0)
        vols.append({"id": v.get("id") or v.get("vol_path", ""), "status": v.get("status", ""), "used_pct": round(100 * used / tot) if tot else 0,
                     "free_gb": round((tot - used) / 1e9)})
    disks = [{"name": x.get("name") or x.get("id", ""), "status": x.get("status", ""), "smart": x.get("smart_status", ""), "temp": x.get("temp")}
             for x in d.get("disks", []) or []]
    problems = [f"svazek {v['id']}: {v['status']}" for v in vols if v["status"] not in ("normal", "")] + \
               [f"svazek {v['id']} plný na {v['used_pct']} %" for v in vols if v["used_pct"] >= 90] + \
               [f"disk {x['name']}: {x['status']}/{x['smart']}" for x in disks if x["status"] not in ("normal", "") or x["smart"] not in ("normal", "", None)] + \
               [f"disk {x['name']} má {x['temp']} °C" for x in disks if (x["temp"] or 0) >= 55]
    return {"volumes": vols, "disks": disks, "problems": problems}


def parse_syno_backups(data: dict, now: float) -> list[dict]:
    out = []
    for t in (data.get("data", data).get("task_list") or data.get("data", data).get("tasks") or []):
        last = t.get("last_bkp_time") or ""
        res = t.get("last_bkp_result") or t.get("status") or ""
        age = None
        try:
            age = (now - dt.datetime.strptime(last[:16], "%Y/%m/%d %H:%M").timestamp()) / 86400 if last else None
        except ValueError:
            age = None
        out.append({"name": t.get("name", ""), "result": res, "last": last, "days": round(age, 1) if age is not None else None,
                    "bad": res not in ("done", "success", "backingup") or (age is not None and age > 8)})
    return out


async def synology(api: str, method: str, version: int = 1, transport=None, **params) -> dict:
    need("synology")
    from .connectors import http

    base = value("synology", "url").rstrip("/") + "/webapi/entry.cgi"
    async with http(transport=transport) as c:
        r = await c.get(base, params={"api": "SYNO.API.Auth", "version": 6, "method": "login", "account": value("synology", "username"),
                                      "passwd": value("synology", "password"), "session": "JARVIS", "format": "sid"})
        sid = (r.json().get("data") or {}).get("sid")
        if not sid:
            raise ValueError("NAS nepřijal jméno nebo heslo (nebo vyžaduje dvoufázové ověření – pro JARVISe použij účet bez něj).")
        try:
            r = await c.get(base, params={"api": api, "version": version, "method": method, "_sid": sid, **params})
            return dict(r.json())
        finally:
            await c.get(base, params={"api": "SYNO.API.Auth", "version": 6, "method": "logout", "session": "JARVIS", "_sid": sid})


# ------------------------------------------------------------------ (439) ČHMÚ warnings (CAP, no key)
CHMU_CAP = "https://vystrahy-cr.chmi.cz/data/XOCZ50_OKPR.xml"
SEVERITY = {"Minor": "nízký", "Moderate": "zvýšený", "Severe": "vysoký", "Extreme": "extrémní"}


def parse_cap(xml: str, region: str = "") -> list[dict]:
    """The ČHMÚ warning document (CAP 1.2): Czech warnings for areas whose name contains `region` (kraj, okres or ORP)."""
    root = parse_xml(xml)
    want = fold(region)
    out, seen = [], set()
    for info in root.iter():
        if local(info.tag) != "info":
            continue
        f = {local(c.tag): (c.text or "").strip() for c in info}
        lang = f.get("language", "cs")
        if not lang.startswith("cs"):
            continue
        areas = [next((c.text or "" for c in a if local(c.tag) == "areaDesc"), "") for a in info if local(a.tag) == "area"]
        if want and not any(want in fold(a) for a in areas):
            continue
        key = (f.get("event"), f.get("onset"), f.get("expires"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"event": f.get("event", ""), "severity": SEVERITY.get(f.get("severity", ""), f.get("severity", "")), "onset": f.get("onset", ""),
                    "expires": f.get("expires", ""), "text": f.get("description", "")[:400], "advice": f.get("instruction", "")[:300],
                    "areas": [a for a in areas if not want or want in fold(a)][:5]})
    return out


# ------------------------------------------------------------------ (434) RSS digest, (435) YouTube channels
def youtube_feed_url(channel: str) -> str:
    c = channel.strip()
    if c.startswith("UC") and len(c) >= 20:
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={c}"
    if "playlist?list=" in c:
        return f"https://www.youtube.com/feeds/videos.xml?playlist_id={c.split('list=')[1].split('&')[0]}"
    return ""


def channel_id_from_page(page: str) -> str:
    m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{20,})"', page) or re.search(r'channel_id=(UC[\w-]{20,})', page)
    return m.group(1) if m else ""


def parse_youtube_feed(xml: str) -> list[dict]:
    root = parse_xml(xml)
    out = []
    author = next((e.text for e in root.iter() if local(e.tag) == "name"), "") or ""
    for e in root:
        if local(e.tag) != "entry":
            continue
        f = {local(c.tag): c for c in e}
        vid = (f["videoId"].text if "videoId" in f else "") or ""
        out.append({"id": vid, "title": (f["title"].text if "title" in f else "") or "", "published": (f["published"].text if "published" in f else "") or "",
                    "url": f"https://www.youtube.com/watch?v={vid}", "channel": author})
    return out


def seen_filter(rt: Any, key: str, items: list[dict], id_key: str = "id", keep: int = 400) -> list[dict]:
    """Items not seen before under `key` (the first look only remembers)."""
    row = rt.db.one("SELECT v FROM kv WHERE k=?", (key,))
    seen = json.loads(row["v"]) if row else []
    new = [x for x in items if x.get(id_key) and x[id_key] not in seen]
    seen = (seen + [x[id_key] for x in new if x.get(id_key)])[-keep:]
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(seen)))
    return new if row else []


DIGEST_PROMPT = ("Udělej z těchto článků krátký český přehled: nejvýš 8 odrážek, ke každé jedna věta proč je to zajímavé a zdroj v "
                 "závorce. Podobné zprávy slouč. Žádný úvod.\n\n{items}")


# ------------------------------------------------------------------ (440) electricity from the distributor's portal (file import)
def parse_meter_csv(text: str, nt_hours: tuple[int, int] = (22, 6)) -> dict:
    """The export from the distributor's portal (ČEZ Distribuce PND, EG.D, PREdistribuce): rows with a date/time and kWh.
    Recognises ';' or ',' separators, Czech decimal commas, one column with date and time or two."""
    sample = text.lstrip("﻿")
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(sample), delimiter=delim))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("Soubor je prázdný.")
    head = [fold(c) for c in rows[0]]
    start = 1 if not re.match(r"\d", rows[0][0].strip()) else 0
    kwh_col = next((i for i, h in enumerate(head) if "kwh" in h or "spotreb" in h or "hodnota" in h or "odber" in h), len(rows[0]) - 1) if start else len(rows[0]) - 1
    out: list[tuple[dt.datetime, float]] = []
    for r in rows[start:]:
        try:
            raw = r[0].strip() + (" " + r[1].strip() if len(r) > 2 and re.match(r"^\d{1,2}:\d{2}", r[1].strip()) else "")
            stamp = None
            for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y", "%Y-%m-%d"):
                try:
                    stamp = dt.datetime.strptime(raw[:19].strip(), fmt)
                    break
                except ValueError:
                    continue
            v = float(r[kwh_col].strip().replace(" ", "").replace(",", ".") or 0)
        except (ValueError, IndexError):
            continue
        if stamp is not None:
            out.append((stamp, v))
    if not out:
        raise ValueError("V souboru jsem nenašel datum a spotřebu v kWh.")
    days: dict[str, float] = {}
    night = 0.0
    a, b = nt_hours
    for stamp, v in out:
        days[stamp.date().isoformat()] = days.get(stamp.date().isoformat(), 0) + v
        h = stamp.hour
        if (a > b and (h >= a or h < b)) or (a < b and a <= h < b):
            night += v
    total = sum(days.values())
    peak = max(out, key=lambda x: x[1])
    return {"total": round(total, 2), "days": {k: round(v, 2) for k, v in sorted(days.items())}, "avg_day": round(total / max(1, len(days)), 2),
            "night_pct": round(100 * night / total) if total else 0, "peak": {"at": peak[0].isoformat(timespec="minutes"), "kwh": peak[1]},
            "from": min(days), "to": max(days)}


# ------------------------------------------------------------------ (427) Rohlík, (429) ČSFD, (430) Databáze knih – no API
def rohlik_links(items: list[str]) -> list[str]:
    return [f"https://www.rohlik.cz/hledat?q={quote_plus(i.strip())}" for i in items if i.strip()][:15]


def csfd_link(title: str) -> str:
    return f"https://www.csfd.cz/hledat/?q={quote_plus(title)}"


def dbknih_link(title: str) -> str:
    return f"https://www.databazeknih.cz/search?q={quote_plus(title)}"


BOOKS_PROMPT = ("Přečetl jsem tyto knihy (s hodnocením, kde je): {books}. Doporuč 5 knih, které by se mi mohly líbit, nejlépe dostupných "
                "česky; ke každé jednu větu proč. Nevymýšlej neexistující knihy.")


# ------------------------------------------------------------------ the watch: ČHMÚ every hour, the data box twice a day
async def tick(rt: Any, now: dt.datetime | None = None) -> list[str]:
    from .config import LinkXCfg
    from .connectors import configured, http

    c = getattr(rt.cfg, "linkx", None) or LinkXCfg()
    now = now or dt.datetime.now()
    said: list[str] = []
    if c.region and now.timestamp() - getattr(rt, "_linkx_chmu_at", 0.0) >= 3600:
        rt._linkx_chmu_at = now.timestamp()
        try:
            async with http() as cl:
                r = await cl.get(c.chmu_url or CHMU_CAP)
            for w in seen_filter(rt, "lx_chmu", [x | {"id": f"{x['event']}|{x['onset']}"} for x in parse_cap(r.text, c.region)]):
                t = f"{w['event']} ({w['severity']} stupeň) od {w['onset'][11:16]} {w['onset'][8:10]}.{w['onset'][5:7]}. {w['advice']}".strip()
                rt.notify("Výstraha ČHMÚ", t, speak=w["severity"] in ("vysoký", "extrémní"))
                said.append(t)
        except Exception:  # noqa: BLE001
            pass
    from .proactiveplus import due_today

    slot = "lx_isds_pm" if now.hour >= 14 else "lx_isds_am"
    if c.watch_isds and configured("isds") and due_today(rt, slot, "14:00" if slot == "lx_isds_pm" else "08:00", now):
        rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", (slot, now.date().isoformat()))
        try:
            for m in seen_filter(rt, "lx_isds", await isds_received(10)):
                t = f"Nová zpráva v datové schránce od {m['from']}: {m['subject']}"
                rt.notify("Datová schránka", t, url="https://www.mojedatovaschranka.cz", speak=True)
                said.append(t)
        except Exception:  # noqa: BLE001
            pass
    return said
