"""3.20 Propojení+ (421–440): the clients and parsers with real-shaped answers (no internet)."""
from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest

from jarvis import connectors, linkx, tools

KEYS = {("bakalari", "url"): "https://skola.cz/bakaweb", ("bakalari", "username"): "rodic", ("bakalari", "password"): "x",
        ("mapycz", "api_key"): "k", ("isds", "username"): "abc123", ("isds", "password"): "p", ("jellyfin", "url"): "http://nas:8096",
        ("jellyfin", "api_key"): "jk", ("plex", "url"): "http://nas:32400", ("plex", "token"): "pt", ("synology", "url"): "https://nas:5001",
        ("synology", "username"): "u", ("synology", "password"): "p", ("nextcloud", "url"): "https://cloud.cz", ("nextcloud", "username"): "eva",
        ("nextcloud", "app_password"): "a", ("strava", "client_id"): "1", ("strava", "client_secret"): "s", ("strava", "refresh_token"): "r"}


@pytest.fixture
def keys(monkeypatch):
    def value(cid, field):
        return KEYS.get((cid, field), "")

    monkeypatch.setattr(linkx, "value", value)
    monkeypatch.setattr(connectors, "value", value)
    monkeypatch.setattr(linkx, "need", lambda cid: None)
    linkx._BAKA.update(token="", until=0)
    linkx._STRAVA.update(token="", until=0)
    yield


def mock(handler):
    return httpx.MockTransport(handler)


def test_safe_xml():
    with pytest.raises(ValueError):
        linkx.parse_xml('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')
    assert linkx.parse_xml("<a><b>1</b></a>").find("b").text == "1"


async def test_bakalari(keys):
    seen = []

    def h(req: httpx.Request):
        seen.append(req.url.path)
        if req.url.path.endswith("/api/login"):
            assert b"username=rodic" in req.content and b"client_id=ANDR" in req.content
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        assert req.headers["Authorization"] == "Bearer T"
        return httpx.Response(200, json={"Subjects": [{"Subject": {"Name": "Matematika"}, "AverageText": "1,5", "Marks": [
            {"MarkDate": "2026-11-20T00:00:00+01:00", "MarkText": "1", "Caption": "Zlomky", "Weight": 5, "IsNew": True},
            {"MarkDate": "2026-09-01T00:00:00+02:00", "MarkText": "3", "Caption": "Stará"}]}]})

    data = await linkx.bakalari("marks", transport=mock(h))
    marks = linkx.parse_marks(data, dt.date(2026, 11, 1))
    assert marks == [{"subject": "Matematika", "mark": "1", "weight": 5, "what": "Zlomky", "date": "2026-11-20", "new": True, "average": "1,5"}]
    await linkx.bakalari("marks", transport=mock(h))
    assert seen.count("/bakaweb/api/login") == 1                               # the token is reused
    hw = linkx.parse_homework({"Homeworks": [{"Subject": {"Name": "Čeština"}, "Content": "<p>Cvičení 4</p>", "DateEnd": "2026-11-27", "Done": False},
                                              {"Subject": {"Name": "X"}, "Content": "hotovo", "DateEnd": "2026-11-27", "Done": True}]}, dt.date(2026, 11, 25))
    assert hw == [{"subject": "Čeština", "task": "Cvičení 4", "due": "2026-11-27"}]
    kom = linkx.parse_komens({"Messages": [{"Title": "Výlet", "Text": "Sraz v <b>8:00</b>", "SentDate": "2026-11-24T10:00", "Sender": {"Name": "Třídní"}}]})
    assert kom[0]["text"] == "Sraz v 8:00" and not kom[0]["read"]


async def test_mapy(keys, rt):
    def h(req: httpx.Request):
        assert req.url.params["apikey"] == "k"
        if req.url.path.endswith("/geocode"):
            q = req.url.params["query"]
            pos = {"lon": 16.6, "lat": 49.2} if "Brno" in q else {"lon": 15.59, "lat": 49.4}
            return httpx.Response(200, json={"items": [{"name": q, "location": "Česko", "position": pos}]})
        assert req.url.params["routeType"] == "bike_road"
        return httpx.Response(200, json={"length": 88300, "duration": 16200})

    t = mock(h)
    a = await linkx.mapy_geocode("Brno", t)
    b = await linkx.mapy_geocode("Jihlava", t)
    r = await linkx.mapy_route(a, b, linkx.route_type("na kole"), t)
    assert r == {"km": 88.3, "minutes": 270, "link": "https://mapy.cz/fnc/v1/route?start=16.6,49.2&end=15.59,49.4&routeType=bike_road"}
    linkx.places_set(rt, "Babička", "Jihlava, Masarykovo náměstí 1")
    assert linkx.resolve_place(rt, "babička") == "Jihlava, Masarykovo náměstí 1" and linkx.resolve_place(rt, "Praha") == "Praha"


ISDS_OK = """<?xml version="1.0" encoding="UTF-8"?><SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/"><SOAP-ENV:Body>
<p:GetListOfReceivedMessagesResponse xmlns:p="http://isds.czechpoint.cz/v20"><p:dmRecords><p:dmRecord><p:dmID>123456</p:dmID>
<p:dmSender>Finanční úřad pro Jihomoravský kraj</p:dmSender><p:dmAnnotation>Výzva</p:dmAnnotation><p:dmMessageStatus>4</p:dmMessageStatus>
<p:dmDeliveryTime>2026-11-24T09:12:00</p:dmDeliveryTime></p:dmRecord></p:dmRecords><p:dmStatus><p:dmStatusCode>0000</p:dmStatusCode>
<p:dmStatusMessage>Provedeno úspěšně.</p:dmStatusMessage></p:dmStatus></p:GetListOfReceivedMessagesResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"""


async def test_databox(keys):
    def h(req: httpx.Request):
        assert req.headers["Authorization"].startswith("Basic ") and b"GetListOfReceivedMessages" in req.content
        return httpx.Response(200, text=ISDS_OK)

    msgs = await linkx.isds_received(30, mock(h))
    assert msgs == [{"id": "123456", "from": "Finanční úřad pro Jihomoravský kraj", "subject": "Výzva", "delivered": "2026-11-24T09:12:00",
                     "status": "dodána"}]
    with pytest.raises(ValueError, match="Chybné"):
        linkx.parse_isds_list(ISDS_OK.replace("0000", "1110").replace("Provedeno úspěšně.", "Chybné jméno"))
    assert "doručení" in " ".join(connectors.CONNECTORS["isds"]["help"])                 # the warning about delivery is shown


async def test_strava_and_files(keys, monkeypatch):
    saved = {}
    from jarvis import secrets

    monkeypatch.setattr(secrets, "set", lambda k, v: saved.__setitem__(k, v))

    def h(req: httpx.Request):
        if req.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "A", "expires_at": 9_999_999_999, "refresh_token": "r2"})
        assert req.headers["Authorization"] == "Bearer A"
        return httpx.Response(200, json=[{"id": 1, "name": "Ranní běh", "sport_type": "Run", "distance": 10230, "moving_time": 3010,
                                          "start_date_local": "2026-11-24T07:00:00Z", "average_heartrate": 151}])

    acts = await linkx.strava_activities(14, mock(h))
    assert acts[0]["kind"] == "run" and acts[0]["km"] == 10.23 and acts[0]["minutes"] == 50.2 and saved == {"conn.strava.refresh_token": "r2"}
    gpx = ('<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
           '<trkpt lat="49.0" lon="16.0"><ele>200</ele><time>2026-11-24T07:00:00Z</time></trkpt>'
           '<trkpt lat="49.01" lon="16.0"><ele>230</ele><time>2026-11-24T07:06:00Z</time></trkpt>'
           '<trkpt lat="49.02" lon="16.0"><ele>220</ele><time>2026-11-24T07:12:00Z</time></trkpt></trkseg></trk></gpx>')
    g = linkx.parse_gpx(gpx)
    assert g["km"] == pytest.approx(2.22, abs=0.01) and g["minutes"] == 12 and g["gain_m"] == 30
    rows = linkx.parse_garmin_csv("Activity Type,Date,Title,Distance,Time,Avg HR\nRunning,2026-11-20 07:00:00,Běh,8.50,00:45:30,148\n")
    assert rows == [{"kind": "run", "name": "Běh", "start": "2026-11-20 07:00:00", "km": 8.5, "minutes": 45.5, "hr": 148.0}]


async def test_media_servers(keys, rt):
    plex_xml = ('<MediaContainer size="1"><Video title="Pilot" grandparentTitle="Seriál" viewOffset="600000" duration="2400000">'
                '<User title="eva"/><Player title="Obývák TV" state="playing" machineIdentifier="m1"/></Video></MediaContainer>')
    calls = []

    def h(req: httpx.Request):
        calls.append((req.method, req.url.path))
        if req.url.host == "nas" and req.url.port == 32400:
            assert req.headers["X-Plex-Token"] == "pt"
            return httpx.Response(200, text=plex_xml)
        assert 'Token="jk"' in req.headers["Authorization"]
        if req.method == "POST":
            return httpx.Response(204)
        return httpx.Response(200, json=[{"Id": "s1", "UserName": "Tom", "DeviceName": "Ložnice", "PlayState": {"IsPaused": False},
                                          "NowPlayingItem": {"Name": "Film"}}, {"Id": "s2", "DeviceName": "Nic"}])

    connectors.TRANSPORT = mock(h)
    try:
        assert linkx.parse_plex_sessions(plex_xml)[0] == {"title": "Seriál – Pilot", "user": "eva", "device": "Obývák TV", "state": "playing",
                                                         "client": "m1", "progress": 25}
        r = await tools.call("link_kit", {"action": "media"}, rt)
        assert r.ok and "Seriál – Pilot" in r.summary and "Film – Ložnice" in r.summary
        r = await tools.call("link_kit", {"action": "media_cmd", "text": "dej pauzu"}, rt)
        assert r.ok and ("POST", "/Sessions/s1/Playing/Pause") in calls
    finally:
        connectors.TRANSPORT = None
    assert tools.REGISTRY["link_kit"].danger_if({"action": "media_cmd"}) and not tools.REGISTRY["link_kit"].danger_if({"action": "media"})


def test_nextcloud_and_synology_parsers():
    files = ('<d:multistatus xmlns:d="DAV:"><d:response><d:href>/remote.php/dav/files/eva/Dokumenty/Smlouva.pdf</d:href><d:propstat><d:prop>'
             '<d:displayname>Smlouva.pdf</d:displayname><d:getcontentlength>2048</d:getcontentlength></d:prop></d:propstat></d:response></d:multistatus>')
    assert linkx.parse_dav_files(files, "eva") == [{"name": "Smlouva.pdf", "path": "/Dokumenty/Smlouva.pdf", "size": 2048}]
    cal = ('<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav"><d:response><d:propstat><d:prop><cal:calendar-data>'
           "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:1\nDTSTART:20261126T090000Z\nSUMMARY:Zubař\nLOCATION:Brno\nEND:VEVENT\nEND:VCALENDAR\n"
           "</cal:calendar-data></d:prop></d:propstat></d:response></d:multistatus>")
    ev = linkx.parse_caldav_events(cal)
    assert ev[0]["title"] == "Zubař" and ev[0]["start"].startswith("2026-11-26T09:00") and ev[0]["where"] == "Brno"
    st = linkx.parse_syno_storage({"data": {"volumes": [{"id": "volume_1", "status": "normal", "size": {"total": "4000000000000", "used": "3800000000000"}}],
                                            "disks": [{"name": "Disk 1", "status": "normal", "smart_status": "normal", "temp": 41},
                                                      {"name": "Disk 2", "status": "crashed", "smart_status": "failing", "temp": 58}]}})
    assert st["volumes"][0]["used_pct"] == 95 and len(st["problems"]) == 3
    now = dt.datetime(2026, 11, 25, 12).timestamp()
    bk = linkx.parse_syno_backups({"data": {"task_list": [{"name": "Fotky", "last_bkp_result": "done", "last_bkp_time": "2026/11/24 03:00"},
                                                           {"name": "Dokumenty", "last_bkp_result": "failed", "last_bkp_time": "2026/11/10 03:00"}]}}, now)
    assert [b["bad"] for b in bk] == [False, True] and bk[0]["days"] == 1.4


async def test_synology_logs_in_and_out(keys):
    seen = []

    def h(req: httpx.Request):
        api, method = req.url.params["api"], req.url.params["method"]
        seen.append(method)
        if method == "login":
            return httpx.Response(200, json={"data": {"sid": "S"}, "success": True})
        if method == "logout":
            return httpx.Response(200, json={"success": True})
        assert req.url.params["_sid"] == "S" and api == "SYNO.Storage.CGI.Storage"
        return httpx.Response(200, json={"data": {"volumes": [], "disks": []}, "success": True})

    out = await linkx.synology("SYNO.Storage.CGI.Storage", "load_info", transport=mock(h))
    assert out["success"] and seen == ["login", "load_info", "logout"]


CAP = """<?xml version="1.0" encoding="UTF-8"?><alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"><identifier>x</identifier>
<info><language>cs</language><event>Silný vítr</event><severity>Moderate</severity><onset>2026-11-25T18:00:00+01:00</onset>
<expires>2026-11-26T06:00:00+01:00</expires><description>Nárazy 70–90 km/h.</description><instruction>Zabezpečte volné předměty.</instruction>
<area><areaDesc>Jihomoravský kraj – Brno</areaDesc></area><area><areaDesc>Kraj Vysočina – Jihlava</areaDesc></area></info>
<info><language>en</language><event>Strong wind</event><severity>Moderate</severity><area><areaDesc>Brno</areaDesc></area></info>
<info><language>cs</language><event>Ledovka</event><severity>Severe</severity><onset>2026-11-26T03:00:00+01:00</onset><expires>2026-11-26T10:00:00+01:00</expires>
<area><areaDesc>Plzeňský kraj – Klatovy</areaDesc></area></info></alert>"""


def test_chmu_youtube_rss_meter(rt):
    w = linkx.parse_cap(CAP, "Brno")
    assert len(w) == 1 and w[0]["event"] == "Silný vítr" and w[0]["severity"] == "zvýšený" and w[0]["areas"] == ["Jihomoravský kraj – Brno"]
    assert [x["event"] for x in linkx.parse_cap(CAP)] == ["Silný vítr", "Ledovka"]
    assert linkx.youtube_feed_url("UCabcdefghijklmnopqrstuv").endswith("channel_id=UCabcdefghijklmnopqrstuv")
    assert linkx.youtube_feed_url("https://www.youtube.com/playlist?list=PL123&x=1").endswith("playlist_id=PL123")
    assert linkx.channel_id_from_page('...{"externalId":"UCabcdefghijklmnopqrstuv"}...') == "UCabcdefghijklmnopqrstuv"
    feed = ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><author><name>Kanál</name></author>'
            '<entry><yt:videoId>abc</yt:videoId><title>Nové video</title><published>2026-11-24T10:00:00+00:00</published></entry></feed>')
    v = linkx.parse_youtube_feed(feed)
    assert v == [{"id": "abc", "title": "Nové video", "published": "2026-11-24T10:00:00+00:00", "url": "https://www.youtube.com/watch?v=abc",
                  "channel": "Kanál"}]
    assert linkx.seen_filter(rt, "t", v) == [] and linkx.seen_filter(rt, "t", v) == []
    assert linkx.seen_filter(rt, "t", [{"id": "new"}, *v]) == [{"id": "new"}]
    csv_text = ("Datum;Čas od;Spotřeba [kWh]\n24.11.2026;00:00;0,25\n24.11.2026;00:15;0,30\n24.11.2026;18:00;1,20\n"
                "25.11.2026;23:30;0,50\n")
    m = linkx.parse_meter_csv(csv_text)
    assert m["total"] == 2.25 and m["days"] == {"2026-11-24": 1.75, "2026-11-25": 0.5} and m["night_pct"] == 47
    assert m["peak"] == {"at": "2026-11-24T18:00", "kwh": 1.2}
    with pytest.raises(ValueError):
        linkx.parse_meter_csv("nic tu není\n")
    assert linkx.rohlik_links(["mléko", " ", "chléb"]) == ["https://www.rohlik.cz/hledat?q=ml%C3%A9ko", "https://www.rohlik.cz/hledat?q=chl%C3%A9b"]


async def test_link_kit_offline_bits(rt, tmp_path):
    from jarvis.tools.list_tools import add_items

    add_items(rt, "nákup", ["mléko", "rohlíky"])
    r = await tools.call("link_kit", {"action": "rohlik"}, rt)
    assert r.ok and sum(1 for c in rt.platform.calls if c[0] == "open_url") == 2
    f = tmp_path / "spotreba.csv"
    f.write_text("Datum;Hodnota (kWh)\n01.11.2026 00:15;0,4\n01.11.2026 12:00;1,6\n", encoding="utf-8")
    r = await tools.call("link_kit", {"action": "meter", "path": str(f)}, rt)
    assert r.ok and "2 kWh" in r.summary
    r = await tools.call("link_kit", {"action": "school", "text": "edupage"}, rt)
    assert not r.ok and "EduPage" in r.summary
    r = await tools.call("link_kit", {"action": "place_add", "name": "práce", "text": "Brno, Kounicova 1"}, rt)
    assert r.ok and "práce" in (await tools.call("link_kit", {"action": "places"}, rt)).summary
    r = await tools.call("link_kit", {"action": "databox"}, rt)
    assert not r.ok and "Datová schránka" in r.summary                          # not connected → a friendly message
    _ = json


class FakeRemote:
    def __init__(self):
        self.items: dict[str, dict] = {}
        self.n = 0

    async def lst(self):
        return list(self.items.values())

    async def add(self, ev):
        self.n += 1
        rid = f"g{self.n}"
        self.items[rid] = {**ev, "id": rid} if isinstance(ev, dict) else {"id": rid, "title": ev}
        return rid

    async def delete(self, rid):
        self.items.pop(rid, None)


async def test_calendar_two_way(rt):
    from jarvis import syncx

    now = dt.datetime(2026, 11, 25, 12).timestamp()
    g = FakeRemote()
    mine = rt.calendar.add("Zubař", dt.datetime(2026, 11, 26, 9), 30)
    g.items["x1"] = {"id": "x1", "title": "Porada", "start": dt.datetime(2026, 11, 27, 10).timestamp(),
                     "end": dt.datetime(2026, 11, 27, 11).timestamp(), "location": "", "jarvis": ""}
    g.items["x2"] = {"id": "x2", "title": "zubař", "start": dt.datetime(2026, 11, 28, 9).timestamp(),       # same name, other day → not a duplicate
                     "end": dt.datetime(2026, 11, 28, 10).timestamp(), "location": "", "jarvis": ""}
    st = await syncx.sync_calendar(rt, g.lst, g.add, g.delete, now=now)
    assert st["pushed"] == 1 and st["pulled"] == 2
    st = await syncx.sync_calendar(rt, g.lst, g.add, g.delete, now=now)
    assert st == {"pushed": 0, "pulled": 0, "paired": 0, "deleted_remote": 0, "deleted_local": 0, "updated_local": 0}    # no duplicates
    g.items["x1"]["start"] += 3600
    g.items["x1"]["end"] += 3600
    rt.calendar.delete(mine["id"])
    st = await syncx.sync_calendar(rt, g.lst, g.add, g.delete, now=now)
    assert st["updated_local"] == 1 and st["deleted_remote"] == 1 and len(g.items) == 2
    del g.items["x2"]
    st = await syncx.sync_calendar(rt, g.lst, g.add, g.delete, now=now)
    assert st["deleted_local"] == 1
    titles = [r["title"] for r in rt.db.all("SELECT title FROM cal_events")]
    assert titles == ["Porada"]
    ev = syncx.google_event({"id": "a", "summary": "S", "start": {"date": "2026-12-01"}, "end": {"date": "2026-12-02"},
                             "extendedProperties": {"private": {"jarvis": "abc"}}})
    assert ev["jarvis"] == "abc" and ev["end"] - ev["start"] == 86400
    body = syncx.google_body({"title": "T", "start": now, "end": now + 600, "jarvis": "id1"})
    assert body["extendedProperties"]["private"]["jarvis"] == "id1" and body["start"]["dateTime"].startswith("2026-11-25T12:00")


async def test_list_two_way(rt):
    from jarvis import syncx
    from jarvis.tools.list_tools import add_items, items_of

    t = FakeRemote()

    async def done(rid):
        t.items.pop(rid, None)

    add_items(rt, "nákup", ["mléko", "chleba"])
    t.items["r1"] = {"id": "r1", "title": "Chleba"}
    t.items["r2"] = {"id": "r2", "title": "máslo"}
    st = await syncx.sync_list(rt, "nákup", "todoist", t.lst, t.add, done)
    assert st == {"pushed": 1, "pulled": 1, "paired": 1, "done_remote": 0, "removed_local": 0}
    assert {i["item"] for i in items_of(rt, "nákup")} == {"chleba", "máslo", "mléko"} and len(t.items) == 3
    assert (await syncx.sync_list(rt, "nákup", "todoist", t.lst, t.add, done))["pushed"] == 0
    milk = next(i for i in items_of(rt, "nákup") if i["item"] == "mléko")
    rt.db.exec("DELETE FROM lists WHERE id=?", (milk["id"],))                   # bought → ticked off in Todoist
    t.items.pop("r2")                                                           # done in Todoist → gone from the list
    st = await syncx.sync_list(rt, "nákup", "todoist", t.lst, t.add, done)
    assert st["done_remote"] == 1 and st["removed_local"] == 1
    assert [i["item"] for i in items_of(rt, "nákup")] == ["chleba"] and [x["title"] for x in t.items.values()] == ["Chleba"]


def test_obsidian(tmp_path):
    from jarvis import syncx

    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "skryte.md").write_text("- [ ] tajné", encoding="utf-8")
    (tmp_path / "Projekty").mkdir()
    (tmp_path / "Projekty" / "Dům.md").write_text("# Dům\n- [ ] objednat okna\n- [x] koupit pozemek\nRozpočet 3 mil.\n", encoding="utf-8")
    assert syncx.vault_tasks(tmp_path) == [{"note": "Projekty/Dům", "line": 2, "task": "objednat okna"}]
    assert syncx.vault_search(tmp_path, "rozpočet domu")[0]["note"] == "Projekty/Dům"
    assert syncx.vault_done(tmp_path, "okna") == {"note": "Dům", "task": "objednat okna"}
    assert syncx.vault_tasks(tmp_path) == []
    p = syncx.vault_append(tmp_path, "zavolat elektrikáři", today=dt.date(2026, 11, 25), task=True)
    assert p.name == "2026-11-25.md" and p.read_text(encoding="utf-8") == "- [ ] zavolat elektrikáři\n"
    with pytest.raises(ValueError):
        syncx.vault_append(tmp_path, "x", "../ven")
    assert syncx.best_playlist([{"name": "Ranní káva"}, {"name": "Na běhání"}], "pusť playlist na běhání")["name"] == "Na běhání"


async def test_sync_kit_gating(rt):
    spec = tools.REGISTRY["sync_kit"]
    assert spec.danger_if({"action": "calendar_sync"}) and not spec.danger_if({"action": "notes"})
    r = await tools.call("sync_kit", {"action": "notes", "text": "x"}, rt)
    assert not r.ok and "Obsidian" in r.summary
