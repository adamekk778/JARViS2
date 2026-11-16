"""3.12 Propojení: keys only in the secure storage, reads free, writes ask first, Google sign-in, each service's API."""
import asyncio
import json
from types import SimpleNamespace as NS
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from jarvis import connectors, secrets, tools
from jarvis.connectors import google, spaceship, supabase

tools.load_builtin()


@pytest.fixture
def vault(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(secrets, "get", lambda k: store.get(k, ""))
    monkeypatch.setattr(secrets, "set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(connectors, "TRANSPORT", None)
    connectors.LAST.clear()
    google._ACCESS.update(token="", until=0.0)
    return store


def fake(monkeypatch, handler):
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(handler))


def run(name, **args):
    return asyncio.run(tools.call(name, args, NS()))


def test_every_service_is_there_and_status_never_shows_a_key(vault):
    ids = [c["id"] for c in connectors.status()]
    assert {"google", "supabase", "spaceship", "github", "notion", "slack"} <= set(ids)
    connectors.save("supabase", {"token": "sbp_secret_value"})
    st = json.dumps(connectors.status())
    assert "sbp_secret_value" not in st and vault["conn.supabase.token"] == "sbp_secret_value"
    assert next(c for c in connectors.status() if c["id"] == "supabase")["connected"]
    connectors.remove("supabase")
    assert not connectors.configured("supabase")


def test_a_tool_of_a_service_not_connected_says_where_to_connect(vault):
    r = run("supabase_projects")
    assert not r.ok and "Propojení" in r.summary


def test_supabase_reads_run_writes_ask():
    assert supabase.is_read("select * from orders limit 5")
    assert supabase.is_read("with t as (select 1) select * from t")
    for q in ("delete from orders", "select 1; drop table x", "with d as (delete from x returning *) select * from d",
              "update users set a=1", "insert into a values (1)", "alter table a add b int", "create table x (a int)"):
        assert not supabase.is_read(q), q
    spec = tools.REGISTRY["supabase_sql"]
    assert not tools.is_dangerous(spec, {"project_ref": "p", "query": "select 1"}, [], [], None)
    assert tools.is_dangerous(spec, {"project_ref": "p", "query": "delete from orders"}, [], [], None)


def test_writes_everywhere_are_dangerous():
    for name in ("google_gmail_send", "google_calendar_create", "google_sheets_append", "spaceship_dns_set",
                 "github_issue_create", "notion_append", "slack_post"):
        assert tools.REGISTRY[name].danger, name
    for name in ("google_gmail_search", "google_gmail_read", "google_gmail_draft", "google_drive_search", "spaceship_domains",
                 "github_repos", "notion_search", "slack_read"):
        assert not tools.REGISTRY[name].danger, name


def test_supabase_sql_goes_to_the_management_api(vault, monkeypatch):
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, req.headers.get("authorization"), req.content))
        return httpx.Response(200, json=[{"n": 42}])

    connectors.save("supabase", {"token": "sbp_x"})
    fake(monkeypatch, handler)
    r = run("supabase_sql", project_ref="abc", query="select count(*) as n from orders")
    assert r.ok and r.data == [{"n": 42}]
    assert seen[0][1] == "/v1/projects/abc/database/query" and seen[0][2] == "Bearer sbp_x"


def test_spaceship_records_and_headers(vault, monkeypatch):
    assert spaceship.record("A", "@", "1.2.3.4")["address"] == "1.2.3.4"
    assert spaceship.record("CNAME", "www", "x.example")["cname"] == "x.example"
    assert spaceship.record("MX", "@", "mx.example", priority=5) == {"type": "MX", "name": "@", "ttl": 3600, "exchange": "mx.example", "preference": 5}
    seen = {}

    def handler(req: httpx.Request):
        seen.update(key=req.headers.get("x-api-key"), secret=req.headers.get("x-api-secret"), path=req.url.path)
        return httpx.Response(200, json={"items": [{"name": "firma.cz", "expirationDate": "2027-01-01", "autoRenew": True}], "total": 1})

    connectors.save("spaceship", {"key": "K", "secret": "S"})
    fake(monkeypatch, handler)
    r = run("spaceship_domains")
    assert r.ok and r.data[0]["name"] == "firma.cz" and seen == {"key": "K", "secret": "S", "path": "/api/v1/domains"}


def test_google_sign_in_and_gmail(vault, monkeypatch):
    connectors.save("google", {"client_id": "cid.apps.googleusercontent.com", "client_secret": "GOCSPX-x"})
    assert not connectors.configured("google")                       # not signed in yet
    url = google.start("http://127.0.0.1:8765/api/oauth/google")
    q = parse_qs(urlparse(url).query)
    assert q["code_challenge_method"] == ["S256"] and "gmail.modify" in q["scope"][0] and q["access_type"] == ["offline"]

    def handler(req: httpx.Request):
        if req.url.host == "oauth2.googleapis.com":
            form = parse_qs(req.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                assert form["code_verifier"] and form["redirect_uri"] == ["http://127.0.0.1:8765/api/oauth/google"]
                return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 3600})
            return httpx.Response(200, json={"access_token": "AT2", "expires_in": 3600})
        assert req.headers["authorization"].startswith("Bearer AT")
        if req.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        return httpx.Response(200, json={"id": "m1", "threadId": "t1", "snippet": "Ahoj, posíláme fakturu", "labelIds": ["UNREAD"],
                                         "payload": {"headers": [{"name": "From", "value": "Firma <a@b.cz>"},
                                                                 {"name": "Subject", "value": "Faktura"}]}})

    fake(monkeypatch, handler)
    with pytest.raises(ValueError):
        asyncio.run(google.finish("code", "wrong-state"))
    assert asyncio.run(google.finish("code", q["state"][0])) == "Google je propojený."
    assert vault["conn.google.refresh_token"] == "RT" and connectors.configured("google")
    r = run("google_gmail_search", query="is:unread")
    assert r.ok and r.data[0]["subject"] == "Faktura" and r.data[0]["unread"]


def test_gmail_body_from_html_only():
    import base64

    html = base64.urlsafe_b64encode(b"<p>Dobr&yacute; den,<br>platba <b>OK</b></p>").decode()
    assert "platba" in google._body({"mimeType": "text/html", "body": {"data": html}})


def test_mail_send_asks_with_the_mail_shown():
    lines = tools.details_for(tools.REGISTRY["google_gmail_send"], {"to": "jan@firma.cz", "subject": "Nabídka", "body": "Dobrý den"}, None)
    assert "Komu: jan@firma.cz" in lines and "Dobrý den" in lines
