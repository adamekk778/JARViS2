"""3.12 Propojení 2: every new service – the right address, the key in the right place (never in a log or the status),
the answer read right, and every write asks first."""
import asyncio
import json
from types import SimpleNamespace as NS
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from jarvis import connectors, secrets, tools

tools.load_builtin()
from jarvis.connectors import fio, microsoft, shopify, stripe  # noqa: E402


@pytest.fixture
def vault(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(secrets, "get", lambda k: store.get(k, ""))
    monkeypatch.setattr(secrets, "set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(connectors, "TRANSPORT", None)
    connectors.LAST.clear()
    for cid in connectors.CONNECTORS:
        connectors.forget(cid)
    return store


def connect(cid, **values):
    connectors.save(cid, values)


def net(monkeypatch, handler):
    seen = []

    def wrap(req: httpx.Request):
        seen.append(req)
        return handler(req)
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(wrap))
    return seen


def run(_tool, **args):
    return asyncio.run(tools.call(_tool, args, NS()))


def body(req):
    return json.loads(req.content or b"{}")


WRITES = ["outlook_mail_send", "outlook_calendar_create", "mstodo_add", "stripe_refund", "stripe_payment_link", "fakturoid_invoice_create",
          "hubspot_contact_create", "hubspot_note", "pipedrive_deal_create", "todoist_add", "todoist_done", "trello_card_create",
          "asana_task_create", "linear_issue_create", "jira_issue_create", "clickup_task_create", "airtable_create", "monday_item_create",
          "toggl_timer", "cloudflare_dns_set", "telegram_send", "discord_send", "webhook_send", "google_tasks_add", "google_calendar_create"]


def test_there_are_many_services_and_every_write_asks():
    ids = set(connectors.CONNECTORS)
    assert {"microsoft", "dropbox", "stripe", "fakturoid", "idoklad", "fio", "shopify", "woocommerce", "hubspot", "pipedrive", "mailchimp",
            "calendly", "todoist", "trello", "asana", "linear", "atlassian", "clickup", "airtable", "monday", "toggl", "vercel", "cloudflare",
            "sentry", "telegram", "discord", "webhook"} <= ids
    assert len(ids) >= 34
    for name in WRITES:
        assert tools.REGISTRY[name].danger, name
    # reading never asks
    for name, spec in tools.REGISTRY.items():
        if spec.category == "propojení" and name not in WRITES and any(name.endswith(w) for w in (
                "_search", "_list", "_issues", "_tasks", "_events", "_balance", "_payments", "_invoices", "_orders", "_products", "_account")):
            assert not spec.danger and not spec.danger_if, name


def test_every_tool_has_an_owner_and_every_service_a_group():
    for name, spec in tools.REGISTRY.items():
        if spec.category == "propojení":
            assert connectors.owner(name), name
    for c in connectors.status():
        assert c["group"] in connectors.GROUPS, c["id"]
        assert c["help"] and c["what"], c["id"]
        if c["oauth"]:
            assert c["login"], c["id"]


def test_status_never_shows_a_key(vault):
    connect("stripe", key="rk_live_TOPSECRET")
    connect("fakturoid", client_id="cid", client_secret="TOPSECRET2", email="a@b.cz")
    st = json.dumps(connectors.status())
    assert "TOPSECRET" not in st
    assert next(c for c in connectors.status() if c["id"] == "stripe")["connected"]


def test_not_connected_says_where(vault):
    for name in ("stripe_balance", "fio_account", "todoist_tasks", "outlook_mail_search", "shopify_orders"):
        r = run(name)
        assert not r.ok and "Propojení" in r.summary, name


# ---------------------------------------------------------------- money
def test_stripe_balance_payments_and_payment_link(vault, monkeypatch):
    connect("stripe", key="rk_test_1")

    def h(req):
        assert req.headers["authorization"] == "Bearer rk_test_1"
        if req.url.path == "/v1/balance":
            return httpx.Response(200, json={"livemode": False, "available": [{"amount": 123456, "currency": "czk"}],
                                             "pending": [{"amount": 500, "currency": "jpy"}]})
        if req.url.path == "/v1/payment_intents":
            return httpx.Response(200, json={"has_more": False, "data": [
                {"id": "pi_1", "amount": 25000, "amount_received": 25000, "currency": "czk", "status": "succeeded", "created": 1,
                 "customer": {"email": "k@firma.cz"}},
                {"id": "pi_2", "amount": 1000, "currency": "czk", "status": "requires_payment_method", "created": 2, "customer": None}]})
        if req.url.path == "/v1/prices":
            f = parse_qs(req.content.decode())
            assert f["unit_amount"] == ["150000"] and f["currency"] == ["czk"] and f["product_data[name]"] == ["Web"]
            return httpx.Response(200, json={"id": "price_1"})
        if req.url.path == "/v1/payment_links":
            assert parse_qs(req.content.decode())["line_items[0][price]"] == ["price_1"]
            return httpx.Response(200, json={"url": "https://buy.stripe.com/x"})
        return httpx.Response(404, json={"error": {"message": "no"}})
    net(monkeypatch, h)
    b = run("stripe_balance")
    assert b.ok and b.data["available"] == {"CZK": 1234.56} and b.data["pending"] == {"JPY": 500.0} and b.data["test_mode"]
    p = run("stripe_payments", days=7)
    assert p.ok and p.data["received"] == {"CZK": 250.0} and p.data["payments"][0]["customer"] == "k@firma.cz"
    link = run("stripe_payment_link", name="Web", amount=1500, currency="czk")
    assert link.ok and link.data["url"] == "https://buy.stripe.com/x"


def test_stripe_error_words_reach_the_user(vault, monkeypatch):
    connect("stripe", key="rk_bad")
    net(monkeypatch, lambda req: httpx.Response(401, json={"error": {"message": "Invalid API Key provided: rk_bad", "type": "x"}}))
    r = run("stripe_balance")
    assert not r.ok and "odmítla přístup" in r.summary and "Invalid API Key" in r.summary


def test_fakturoid_token_account_invoices_and_new_invoice(vault, monkeypatch):
    connect("fakturoid", client_id="CID", client_secret="SEC", email="ja@firma.cz")

    def h(req):
        assert req.headers["user-agent"] == "JARVIS (ja@firma.cz)"
        if req.url.path == "/api/v3/oauth/token":
            assert req.headers["authorization"].startswith("Basic ") and body(req) == {"grant_type": "client_credentials"}
            assert req.headers["accept"] == "application/json"
            return httpx.Response(200, json={"access_token": "TOK", "expires_in": 7200})
        assert req.headers["authorization"] == "Bearer TOK"
        if req.url.path == "/api/v3/user.json":
            return httpx.Response(200, json={"default_account": "mojefirma", "accounts": [{"slug": "mojefirma"}]})
        if req.url.path == "/api/v3/accounts/mojefirma/invoices.json" and req.method == "GET":
            assert req.url.params["status"] == "overdue"
            return httpx.Response(200, json=[{"id": 1, "number": "2026-0001", "client_name": "ACME", "total": "12100.0", "currency": "CZK",
                                              "status": "overdue", "due_on": "2026-11-01"}])
        if req.url.path == "/api/v3/accounts/mojefirma/subjects/search.json":
            return httpx.Response(200, json=[{"id": 77, "name": "ACME s.r.o.", "registration_no": "12345678"}])
        if req.url.path == "/api/v3/accounts/mojefirma/invoices.json" and req.method == "POST":
            b = body(req)
            assert b["subject_id"] == 77 and b["due"] == 14 and b["lines"][0] == {"name": "Web", "quantity": 1, "unit_name": "",
                                                                                   "unit_price": 10000, "vat_rate": 21}
            return httpx.Response(201, json={"id": 2, "number": "2026-0002", "total": "12100.0", "currency": "CZK", "status": "open"})
        return httpx.Response(404)
    seen = net(monkeypatch, h)
    r = run("fakturoid_invoices", status="overdue")
    assert r.ok and r.data[0]["number"] == "2026-0001" and "nezaplaceno" in r.summary
    n = run("fakturoid_invoice_create", client="12345678", lines=[{"name": "Web", "quantity": 1, "unit_price": 10000, "vat_rate": 21}])
    assert n.ok and "2026-0002" in n.summary
    assert sum(1 for q in seen if q.url.path.endswith("/oauth/token")) == 1        # the token is reused


def test_fio_statement_is_read_and_payments_found(vault, monkeypatch):
    connect("fio", token="T" * 64)
    fio._CACHE.clear()
    data = {"accountStatement": {"info": {"accountId": "2000000000", "bankId": "2010", "currency": "CZK", "iban": "CZ00",
                                          "openingBalance": 1000.0, "closingBalance": 13100.0, "dateStart": "2026-11-03+0100",
                                          "dateEnd": "2026-11-17+0100"},
                                 "transactionList": {"transaction": [
                                     {"column22": {"value": 1, "name": "ID pohybu"}, "column0": {"value": "2026-11-10+0100"},
                                      "column1": {"value": 12100.0}, "column14": {"value": "CZK"}, "column10": {"value": "ACME s.r.o."},
                                      "column5": {"value": "20260001"}, "column16": {"value": "faktura"}},
                                     {"column0": {"value": "2026-11-11+0100"}, "column1": {"value": -500.0}, "column14": {"value": "CZK"},
                                      "column25": {"value": "nájem"}, "column2": None}]}}}

    def h(req):
        assert req.url.path.startswith("/v1/rest/periods/" + "T" * 64 + "/")
        return httpx.Response(200, json=data)
    net(monkeypatch, h)
    a = run("fio_account", days=14)
    assert a.ok and a.data["balance"] == 13100.0 and a.data["income"] == 12100.0 and a.data["spent"] == -500.0
    assert a.data["moves"][0]["date"] == "2026-11-10" and a.data["moves"][0]["vs"] == "20260001"
    f = run("fio_find_payment", vs="20260001")
    assert f.ok and len(f.data) == 1 and f.data[0]["account_name"] == "ACME s.r.o."


def test_fio_too_often_and_bad_token_are_explained(vault, monkeypatch):
    connect("fio", token="X")
    fio._CACHE.clear()
    net(monkeypatch, lambda req: httpx.Response(409))
    assert "30 sekund" in run("fio_account").summary
    fio._CACHE.clear()
    net(monkeypatch, lambda req: httpx.Response(500))
    assert "token" in run("fio_account").summary


def test_idoklad_reads_invoices(vault, monkeypatch):
    connect("idoklad", client_id="a", client_secret="b")

    def h(req):
        if req.url.host == "identity.idoklad.cz":
            f = parse_qs(req.content.decode())
            assert f["grant_type"] == ["client_credentials"] and f["scope"] == ["idoklad_api"]
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        assert req.headers["authorization"] == "Bearer T" and req.url.path == "/v3/IssuedInvoices"
        return httpx.Response(200, json={"Data": {"Items": [{"Id": 5, "DocumentNumber": "FV1", "DateOfMaturity": "2026-12-01",
                                                             "Prices": {"TotalWithVat": 1210}, "Big": {"x": 1}}], "TotalItems": 1}})
    net(monkeypatch, h)
    r = run("idoklad_invoices")
    assert r.ok and r.data == [{"Id": 5, "DocumentNumber": "FV1", "DateOfMaturity": "2026-12-01", "Prices_TotalWithVat": 1210}]


# ---------------------------------------------------------------- Microsoft (sign-in in the browser)
def test_microsoft_sign_in_mail_and_send(vault, monkeypatch):
    connect("microsoft", client_id="app-1")
    url = microsoft.start(connectors.redirect_uri("microsoft", 8765))
    q = parse_qs(urlparse(url).query)
    assert q["redirect_uri"] == ["http://localhost:8765/api/oauth/microsoft"] and q["code_challenge_method"] == ["S256"]
    assert "offline_access" in q["scope"][0] and "Mail.Send" in q["scope"][0]

    def h(req):
        if req.url.host == "login.microsoftonline.com":
            f = parse_qs(req.content.decode())
            assert f["client_id"] == ["app-1"] and "client_secret" not in f
            if f["grant_type"] == ["authorization_code"]:
                assert f["code"] == ["C"] and f["code_verifier"]
                return httpx.Response(200, json={"access_token": "A1", "refresh_token": "R1", "expires_in": 3600})
            return httpx.Response(200, json={"access_token": "A2", "refresh_token": "R2", "expires_in": 3600})
        assert req.headers["authorization"] in ("Bearer A1", "Bearer A2")
        if req.url.path == "/v1.0/me/mailFolders/inbox/messages":
            assert req.url.params["$filter"].endswith("isRead eq false") and req.url.params["$orderby"] == "receivedDateTime desc"
            return httpx.Response(200, json={"value": [{"id": "m1", "subject": "Faktura", "from": {"emailAddress": {"name": "Jan", "address": "jan@x.cz"}},
                                                        "receivedDateTime": "2026-11-17T08:00:00Z", "isRead": False, "bodyPreview": "Dobrý den"}]})
        if req.url.path == "/v1.0/me/sendMail":
            b = body(req)
            assert b["message"]["toRecipients"] == [{"emailAddress": {"address": "jan@x.cz"}}] and b["saveToSentItems"] is True
            return httpx.Response(202)
        return httpx.Response(404, json={"error": {"message": "x"}})
    net(monkeypatch, h)
    state = q["state"][0]
    assert asyncio.run(microsoft.finish("C", state)) == "Microsoft je propojený."
    assert vault["conn.microsoft.refresh_token"] == "R1" and connectors.configured("microsoft")
    m = run("outlook_mail_search", unread=True)
    assert m.ok and m.data[0]["from"] == "Jan <jan@x.cz>" and m.data[0]["unread"]
    s = run("outlook_mail_send", to="jan@x.cz", subject="Re: Faktura", body="Děkuji")
    assert s.ok
    microsoft.AUTH.access.update(token="", until=0.0)            # the hour is over → a new token, the new refresh token kept
    run("outlook_mail_search", unread=True)
    assert vault["conn.microsoft.refresh_token"] == "R2"


def test_microsoft_refused_sign_in_says_why(vault, monkeypatch):
    connect("microsoft", client_id="app-1")
    url = microsoft.start("http://localhost:8765/api/oauth/microsoft")
    net(monkeypatch, lambda req: httpx.Response(400, json={"error": "invalid_grant", "error_description": "AADSTS9002313: bad redirect"}))
    with pytest.raises(connectors.ServiceError, match="AADSTS9002313"):
        asyncio.run(microsoft.finish("C", parse_qs(urlparse(url).query)["state"][0]))


def test_docx_text():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Ahoj &amp; čau</w:t></w:r></w:p><w:p><w:r><w:t>2. řádek</w:t></w:r></w:p></w:body></w:document>")
    assert microsoft.docx_text(buf.getvalue()) == "Ahoj & čau\n2. řádek"


def test_redirect_hosts():
    assert connectors.redirect_uri("spotify", 8765) == "http://127.0.0.1:8765/api/oauth/spotify"
    assert connectors.redirect_uri("dropbox", 9000) == "http://localhost:9000/api/oauth/dropbox"
    with pytest.raises(ValueError):
        connectors.oauth_module("stripe")


# ---------------------------------------------------------------- shops, CRM
def test_shopify_version_and_orders(vault, monkeypatch):
    import datetime as dt

    connect("shopify", shop="mujobchod")
    assert not connectors.configured("shopify")            # a shop alone is not enough: a token or Client ID + secret

    assert shopify.version(dt.date(2026, 11, 17)) == "2026-04"
    assert shopify.version(dt.date(2026, 2, 1)) == "2025-07"
    connect("shopify", shop="mujobchod", token="shpat_1")

    def h(req):
        assert req.url.host == "mujobchod.myshopify.com" and req.headers["x-shopify-access-token"] == "shpat_1"
        assert req.url.path == f"/admin/api/{shopify.version()}/graphql.json"
        return httpx.Response(200, json={"data": {"orders": {"nodes": [
            {"name": "#1001", "createdAt": "2026-11-16T10:00:00Z", "displayFinancialStatus": "PAID", "displayFulfillmentStatus": "UNFULFILLED",
             "totalPriceSet": {"shopMoney": {"amount": "990.0", "currencyCode": "CZK"}}, "customer": {"displayName": "Eva"},
             "lineItems": {"nodes": [{"title": "Triko", "quantity": 2}]}}]}}})
    net(monkeypatch, h)
    r = run("shopify_orders", days=1)
    assert r.ok and r.data[0]["items"] == ["2× Triko"] and "990.0" in r.summary


def test_shopify_client_credentials_and_graphql_errors(vault, monkeypatch):
    connect("shopify", shop="https://obchod.myshopify.com/admin", client_id="ci", client_secret="cs")
    shopify._TOKEN.update(v="", until=0.0)

    def h(req):
        if req.url.path == "/admin/oauth/access_token":
            f = parse_qs(req.content.decode())
            assert f["grant_type"] == ["client_credentials"] and f["client_id"] == ["ci"]
            return httpx.Response(200, json={"access_token": "shpat_cc", "expires_in": 86399})
        assert req.headers["x-shopify-access-token"] == "shpat_cc"
        return httpx.Response(200, json={"errors": [{"message": "Access denied for orders field."}]})
    net(monkeypatch, h)
    r = run("shopify_orders")
    assert not r.ok and "Access denied" in r.summary


def test_hubspot_search_and_pipedrive_header(vault, monkeypatch):
    connect("hubspot", token="pat-1")
    connect("pipedrive", token="pd-1")

    def h(req):
        if req.url.host == "api.hubapi.com":
            assert req.headers["authorization"] == "Bearer pat-1" and body(req)["query"] == "acme"
            return httpx.Response(200, json={"total": 1, "results": [{"id": "9", "properties": {"email": "a@acme.cz", "firstname": "Al", "hs_object_id": "9"}}]})
        assert req.headers["x-api-token"] == "pd-1" and "api_token" not in str(req.url)
        return httpx.Response(200, json={"success": True, "data": [{"id": 1, "title": "Web", "value": 50000, "currency": "CZK"}]})
    net(monkeypatch, h)
    c = run("hubspot_contacts", query="acme")
    assert c.ok and c.data == [{"id": "9", "email": "a@acme.cz", "firstname": "Al"}]
    d = run("pipedrive_deals")
    assert d.ok and d.data[0]["title"] == "Web"


# ---------------------------------------------------------------- tasks and projects
def test_todoist_v1_filter_pages_and_dates(vault, monkeypatch):
    connect("todoist", token="td")
    seen = []

    def h(req):
        assert req.headers["authorization"] == "Bearer td" and req.url.path.startswith("/api/v1/")
        if req.url.path == "/api/v1/projects":
            return httpx.Response(200, json={"results": [{"id": "p1", "name": "Práce"}], "next_cursor": None})
        if req.url.path == "/api/v1/tasks/filter":
            if "cursor" not in req.url.params:
                return httpx.Response(200, json={"results": [{"id": "1", "content": "A", "project_id": "p1", "priority": 4}], "next_cursor": "c2"})
            return httpx.Response(200, json={"results": [{"id": "2", "content": "B", "project_id": "p1", "priority": 1}], "next_cursor": None})
        if req.url.path == "/api/v1/tasks":
            seen.append(body(req))
            return httpx.Response(200, json={"id": "3"})
        return httpx.Response(404)
    net(monkeypatch, h)
    t = run("todoist_tasks")
    assert t.ok and [x["task"] for x in t.data] == ["A", "B"] and t.data[0]["priority"] == 1 and t.data[0]["project"] == "Práce"
    run("todoist_add", task="Zavolat", due="2026-11-20")
    run("todoist_add", task="Schůzka", due="2026-11-20 9:30")
    run("todoist_add", task="Něco", due="tomorrow")
    assert seen[0]["due_date"] == "2026-11-20" and seen[1]["due_datetime"] == "2026-11-20T9:30:00" and seen[2]["due_string"] == "tomorrow"


def test_trello_key_goes_in_the_header_not_the_address(vault, monkeypatch):
    connect("trello", key="K", token="T")

    def h(req):
        assert "token=" not in str(req.url) and req.headers["authorization"] == 'OAuth oauth_consumer_key="K", oauth_token="T"'
        if req.url.path == "/1/members/me/boards":
            return httpx.Response(200, json=[{"id": "b1", "name": "Firma", "url": "u"}])
        if req.url.path == "/1/boards/b1/lists":
            return httpx.Response(200, json=[{"id": "l1", "name": "To Do"}])
        return httpx.Response(200, json=[{"name": "Karta", "idList": "l1", "due": None}])
    net(monkeypatch, h)
    r = run("trello_cards", board="firma")
    assert r.ok and r.data["cards"][0]["list"] == "To Do"


def test_linear_and_jira(vault, monkeypatch):
    connect("linear", key="lin_api_1")
    connect("atlassian", site="firma", email="a@b.cz", token="AT")

    def h(req):
        if req.url.host == "api.linear.app":
            assert req.headers["authorization"] == "lin_api_1"
            return httpx.Response(200, json={"data": {"viewer": {"assignedIssues": {"nodes": [
                {"identifier": "ENG-1", "title": "Bug", "url": "u", "priorityLabel": "High", "state": {"name": "Todo"}, "team": {"key": "ENG"}}]}}}})
        assert req.url.host == "firma.atlassian.net" and req.headers["authorization"].startswith("Basic ")
        if req.url.path == "/rest/api/3/search/jql":
            assert "currentUser()" in req.url.params["jql"]
            return httpx.Response(200, json={"issues": [{"key": "WEB-7", "fields": {"summary": "Formulář", "status": {"name": "To Do"}}}]})
        if req.url.path == "/rest/api/3/issue":
            b = body(req)
            if b["fields"]["issuetype"].get("name") == "Task":
                return httpx.Response(400, json={"errors": {"issuetype": "neplatný typ"}})
            assert b["fields"]["issuetype"] == {"id": "10001"} and b["fields"]["description"]["type"] == "doc"
            return httpx.Response(201, json={"key": "WEB-8"})
        if req.url.path == "/rest/api/3/issue/createmeta/WEB/issuetypes":
            return httpx.Response(200, json={"issueTypes": [{"id": "10000", "subtask": True}, {"id": "10001", "subtask": False}]})
        return httpx.Response(404)
    net(monkeypatch, h)
    assert run("linear_issues").data[0]["id"] == "ENG-1"
    j = run("jira_issues")
    assert j.ok and j.data[0]["url"] == "https://firma.atlassian.net/browse/WEB-7"
    c = run("jira_issue_create", project="web", summary="Nový", description="a\nb")
    assert c.ok and "WEB-8" in c.summary


def test_graphql_errors_are_words(vault, monkeypatch):
    connect("monday", token="m")
    net(monkeypatch, lambda req: httpx.Response(200, json={"errors": [{"message": "Not Authenticated"}]}))
    r = run("monday_boards")
    assert not r.ok and r.summary == "monday.com: Not Authenticated"


# ---------------------------------------------------------------- web, messages
def test_cloudflare_dns_updates_an_existing_record(vault, monkeypatch):
    connect("cloudflare", token="cf")
    calls = []

    def h(req):
        calls.append((req.method, req.url.path))
        if req.url.path == "/client/v4/zones":
            return httpx.Response(200, json={"success": True, "result": [{"id": "z1", "name": "firma.cz"}]})
        if req.method == "GET":
            return httpx.Response(200, json={"success": True, "result": [{"id": "r1", "type": "A", "name": "www.firma.cz"}]})
        assert body(req) == {"type": "A", "name": "www.firma.cz", "content": "1.2.3.4", "ttl": 1, "proxied": True}
        return httpx.Response(200, json={"success": True, "result": {}})
    net(monkeypatch, h)
    r = run("cloudflare_dns_set", domain="firma.cz", type="A", name="www", content="1.2.3.4", proxied=True)
    assert r.ok and ("PUT", "/client/v4/zones/z1/dns_records/r1") in calls


def test_telegram_and_discord_and_webhook(vault, monkeypatch):
    connect("telegram", token="123:abc", chat_id="42")
    connect("discord", webhook="https://discord.com/api/webhooks/1/x")
    connect("webhook", url="https://hook.eu1.make.com/abc", name="lead do CRM")
    sent = []

    def h(req):
        sent.append((req.url.host, body(req) if req.content else None))
        if req.url.host == "api.telegram.org":
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        return httpx.Response(204) if req.url.host == "discord.com" else httpx.Response(200, text="Accepted")
    net(monkeypatch, h)
    assert run("telegram_send", text="Ahoj").ok and sent[-1] == ("api.telegram.org", {"chat_id": "42", "text": "Ahoj"})
    assert run("discord_send", text="Hotovo").ok and sent[-1][1]["content"] == "Hotovo"
    w = run("webhook_send", text="Nový lead", data={"email": "x@y.cz"})
    assert w.ok and sent[-1][1] == {"text": "Nový lead", "data": {"email": "x@y.cz"}, "source": "JARVIS"}
    connect("discord", webhook="https://evil.example/hook")
    assert "Discord" in run("discord_send", text="x").summary


def test_probe_counts_wrong_key_as_reachable_and_gone_as_broken(monkeypatch):
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(lambda req: httpx.Response(401, json={"message": "bad key"})))
    assert asyncio.run(connectors.probe("stripe"))["ok"]
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(lambda req: httpx.Response(410, json={"error": "Gone"})))
    assert not asyncio.run(connectors.probe("todoist"))["ok"]
    monkeypatch.setattr(connectors, "TRANSPORT", httpx.MockTransport(lambda req: httpx.Response(500)))
    assert asyncio.run(connectors.probe("fio"))["ok"] and not asyncio.run(connectors.probe("stripe"))["ok"]


def test_friendly_never_shows_the_request_address():
    req = httpx.Request("GET", "https://fioapi.fio.cz/v1/rest/periods/SECRETTOKEN/x")
    e = httpx.HTTPStatusError("x", request=req, response=httpx.Response(404, request=req, text="<html>nope</html>"))
    assert "SECRETTOKEN" not in connectors.friendly(e)
    e2 = httpx.ConnectError("fail", request=req)
    assert "SECRETTOKEN" not in connectors.friendly(e2)


def test_slim_keeps_named_fields_or_plain_values():
    assert connectors.slim({"a": 1, "b": {"c": 2}, "d": [1]}, ("a", "b.c")) == {"a": 1, "b_c": 2}
    assert connectors.slim({"x": "y", "z": {"n": 1}}, ("missing",)) == {"x": "y"}


def test_templates_use_only_connected_services(vault, tmp_path, monkeypatch):
    from jarvis import bizagents
    from jarvis.runtime import Runtime

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    rt = Runtime(persist_config=False)
    connect("fio", token="x")
    aid = bizagents.from_template(rt, "finance")
    a = bizagents.get(rt, aid)
    assert a["tools"] == ["fio_account", "fio_find_payment"]
    aid2 = bizagents.from_template(rt, "eshop")              # nothing of it connected → all of it (it says "connect …")
    assert "shopify_orders" in bizagents.get(rt, aid2)["tools"]


def test_stripe_money_units():
    assert stripe.money(1999, "czk") == 19.99 and stripe.money(500, "JPY") == 500
    assert stripe.minor(19.99, "eur") == 1999 and stripe.minor(500, "jpy") == 500
