"""3.4 e-mail + calendar against a fake IMAP mailbox and a fake SMTP server."""
import asyncio
import datetime as dt
import email.utils
import re
from email.message import EmailMessage

import pytest
from conftest import FakeRouter, drain

from jarvis import config, mail, tools
from jarvis.calendar_ import parse_ics


def make_mail(uid, frm, subject, body, unsub=False, html=False):
    m = EmailMessage()
    m["From"] = frm
    m["To"] = "adam@seznam.cz"
    m["Subject"] = subject
    m["Date"] = email.utils.format_datetime(dt.datetime(2026, 10, 25, 9, uid % 60, tzinfo=dt.timezone.utc))
    m["Message-ID"] = f"<m{uid}@example.cz>"
    if unsub:
        m["List-Unsubscribe"] = "<mailto:unsub@shop.cz>"
    if html:
        m.set_content(body)
        m.add_alternative(f"<html><body><p>{body}</p></body></html>", subtype="html")
    else:
        m.set_content(body + "\n\nDne 24.10. napsal Adam:\n> stará zpráva")
    return m.as_bytes()


class FakeIMAP:
    """Just the IMAP commands JARVIS uses."""

    def __init__(self):
        self.msgs = {}      # uid → [bytes, flags set]
        self.folders = {"INBOX": None, "Odeslané": "\\Sent", "Koš": "\\Trash"}
        self.literal = None
        self.appended = []
        self.copied = []

    def add(self, raw, seen=False):
        uid = max(self.msgs, default=100) + 1
        self.msgs[uid] = [raw, {"\\Seen"} if seen else set()]
        return uid

    def noop(self):
        return "OK", [b""]

    def select(self, name, readonly=False):
        return "OK", [str(len(self.msgs)).encode()]

    def list(self):
        return "OK", [f'({f or ""}) "/" "{n}"'.encode() for n, f in self.folders.items()]

    def logout(self):
        pass

    def expunge(self):
        for uid in [u for u, (_, f) in self.msgs.items() if "\\Deleted" in f]:
            del self.msgs[uid]

    def append(self, folder, flags, date, raw):
        self.appended.append((folder, raw))

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            lit = (self.literal or b"").decode().lower()
            self.literal = None
            res = []
            for uid, (raw, flags) in sorted(self.msgs.items()):
                if "UNSEEN" in args and "\\Seen" in flags:
                    continue
                text = raw.decode("utf-8", "replace").lower()
                if "FROM" in args:
                    frm = re.search(r"^from: (.*)$", text, re.M).group(1)
                    if lit not in frm:
                        continue
                elif "TEXT" in args and lit not in text:
                    continue
                res.append(str(uid))
            return "OK", [" ".join(res).encode()]
        if cmd == "FETCH":
            uids = [int(u) for u in args[0].decode().split(",")] if isinstance(args[0], bytes) else [int(args[0])]
            out = []
            for uid in uids:
                raw, flags = self.msgs[uid]
                if "BODY[]" in args[1] and "PEEK" not in args[1]:
                    flags.add("\\Seen")
                part = raw if "HEADER.FIELDS" not in args[1] else raw.split(b"\n\n", 1)[0] + b"\n\n"
                out.append((f"{uid} (UID {uid} FLAGS ({' '.join(flags)}) RFC822.SIZE {len(raw)}".encode(), part))
                out.append(b")")
            return "OK", out
        if cmd == "STORE":
            uid, op, flag = int(args[0]), args[1], args[2].strip("()")
            (self.msgs[uid][1].add if op == "+FLAGS" else self.msgs[uid][1].discard)(flag)
            return "OK", [b""]
        if cmd == "COPY":
            self.copied.append((int(args[0]), args[1]))
            return "OK", [b""]
        raise AssertionError(cmd)


class FakeSMTP:
    sent = []

    def __init__(self, host, port, **k):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def login(self, user, pw):
        assert pw == "app-heslo"

    def starttls(self, **k):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture
def box(rt, monkeypatch):
    acc = config.MailAccount(id="a1", address="adam@seznam.cz", name="Adam Bartók", provider="seznam",
                             imap_host="imap.seznam.cz", smtp_host="smtp.seznam.cz")
    rt.cfg = config.apply_patch(rt.cfg, {"mail": {"accounts": [acc.model_dump()]}})
    rt.mail.sync()
    fake = FakeIMAP()
    a = rt.mail.accounts["a1"]
    a.conn = fake
    a._password = lambda: "app-heslo"
    FakeSMTP.sent = []
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    fake.add(make_mail(1, "Petr Novák <petr@firma.cz>", "Schůzka zítra", "Ahoj Adame, můžeme se sejít ve 3?"))
    fake.add(make_mail(2, "Shop <news@shop.cz>", "Sleva 50 %", "Jen dnes!", unsub=True))
    fake.add(make_mail(3, "Máma <mama@seznam.cz>", "Oběd", "Přijdeš v neděli?", html=True), seen=True)
    return fake


def test_presets_and_provider_guess():
    assert mail.guess_provider("x@email.cz") == "seznam" and mail.guess_provider("x@gmail.com") == "gmail"
    assert mail.PRESETS["seznam"]["imap_host"] == "imap.seznam.cz" and mail.guess_provider("x@firma.cz") == "custom"


async def test_inbox_unread_and_newsletter_flag(rt, box):
    r = await tools.call("email_inbox", {"unread_only": True}, rt)
    assert r.ok and [m["subject"] for m in r.data] == ["Sleva 50 %", "Schůzka zítra"]
    assert r.data[0]["newsletter"] and not r.data[1]["newsletter"] and r.data[1]["from_name"] == "Petr Novák"
    assert "a1:101" in r.summary


async def test_read_marks_seen_and_strips_quotes_and_html(rt, box):
    r = await tools.call("email_read", {"id": "a1:101"}, rt)
    assert r.ok and "můžeme se sejít ve 3?" in r.summary and "stará zpráva" not in r.summary
    assert "\\Seen" in box.msgs[101][1]
    r3 = await tools.call("email_read", {"id": "a1:103"}, rt)
    assert "Přijdeš v neděli?" in r3.summary


async def test_search(rt, box):
    r = await tools.call("email_search", {"query": "neděli"}, rt)
    assert [m["subject"] for m in r.data] == ["Oběd"]


async def test_send_needs_confirmation_and_resolves_names(rt, box):
    spec = tools.REGISTRY["email_send"]
    assert tools.is_dangerous(spec, {}, [], [], rt)
    lines = tools.details_for(spec, {"to": "Petr", "subject": "Re", "body": "Ahoj,\nv pořádku."}, rt)
    assert lines[:2] == ["Komu: Petr", "Předmět: Re"] and "v pořádku." in lines
    r = await tools.call("email_send", {"to": "Petr", "subject": "Zítra", "body": "Ahoj Petře,\nve 3 mi to sedí.\nAdam"}, rt)
    assert r.ok and FakeSMTP.sent[0]["To"] == "petr@firma.cz" and FakeSMTP.sent[0]["From"] == "Adam Bartók <adam@seznam.cz>"
    assert box.appended and box.appended[0][0] == '"Odeslané"'          # a copy in Sent (not Gmail)
    unknown = await tools.call("email_send", {"to": "Pepa Zdepa", "subject": "x", "body": "x"}, rt)
    assert not unknown.ok and "Zeptej se" in unknown.summary


async def test_reply_threads_the_conversation(rt, box):
    r = await tools.call("email_reply", {"id": "a1:101", "body": "Jasně, ve 3 u vás."}, rt)
    msg = FakeSMTP.sent[-1]
    assert r.ok and msg["Subject"] == "Re: Schůzka zítra" and msg["In-Reply-To"] == "<m1@example.cz>" and msg["To"] == "petr@firma.cz"
    assert "\\Answered" in box.msgs[101][1]


async def test_delete_moves_to_trash(rt, box):
    assert tools.is_dangerous(tools.REGISTRY["email_delete"], {}, [], [], rt)
    r = await tools.call("email_delete", {"id": "a1:102"}, rt)
    assert r.ok and box.copied == [(102, '"Koš"')] and 102 not in box.msgs


async def test_agent_send_goes_through_the_confirmation(rt, box):
    rt.router = FakeRouter([[("email_send", {"to": "petr@firma.cz", "subject": "Zítra", "body": "Ahoj, nepřijdu."})], "Neposláno."])
    task = asyncio.create_task(rt.agent.handle("napiš Petrovi, že nepřijdu"))
    q = rt.bus.subscribe()
    for _ in range(100):
        await asyncio.sleep(0.02)
        if rt.agent.pending_confirm():
            break
    req = next(e for e in drain(q) if e["type"] == "confirm_request")
    assert "Komu: petr@firma.cz" in req["details"] and "Ahoj, nepřijdu." in req["details"]
    rt.agent.confirm(rt.agent.pending_confirm(), False)
    await task
    assert FakeSMTP.sent == []


async def test_new_mail_watcher_announces_and_skips_newsletters(rt, box, monkeypatch):
    said = []
    monkeypatch.setattr(rt, "notify", lambda title, body, **k: said.append((title, body)))
    rt.cfg = config.apply_patch(rt.cfg, {"mail": {"vip": ["máma"]}})
    assert await rt.mail.check() == []                        # first look: just remembers where we are
    box.add(make_mail(4, "Shop <news@shop.cz>", "Další sleva", "x", unsub=True))
    box.add(make_mail(5, "Máma <mama@seznam.cz>", "Zavolej mi", "Prosím zavolej."))
    q = rt.bus.subscribe()
    fresh = await rt.mail.check()
    assert [m["subject"] for m in fresh] == ["Zavolej mi", "Další sleva"]
    assert said == [("Důležitý e-mail", "Píše vám Máma: Zavolej mi")]
    assert [e["subject"] for e in drain(q) if e["type"] == "mail_new"] == ["Zavolej mi"]


async def test_vip_mail_rings_the_phone_when_enabled(rt, box, monkeypatch):
    rings = []

    class Phone:
        async def ring(self, text, reason=""):
            rings.append(text)

    rt.phone = Phone()
    monkeypatch.setattr(rt, "notify", lambda *a, **k: None)
    rt.cfg = config.apply_patch(rt.cfg, {"mail": {"vip": ["petr@firma.cz"], "call_vip": True}})
    await rt.mail.check()
    box.add(make_mail(6, "Petr Novák <petr@firma.cz>", "Hoří to", "Ozvi se hned."))
    await rt.mail.check()
    assert rings and "Petr Novák" in rings[0]


def test_add_account_via_ws_tests_login_and_keeps_password_out_of_config(rt, monkeypatch):
    from fastapi.testclient import TestClient
    from jarvis.server.app import create_app

    stored = {}
    monkeypatch.setattr(mail, "test_login", lambda acc, pw: None if pw == "dobre" else (_ for _ in ()).throw(ValueError("Přihlášení nevyšlo")))
    monkeypatch.setattr("jarvis.secrets.set", lambda k, v: stored.__setitem__(k, v))
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)).websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "mail_account_add", "address": "adam@seznam.cz", "password": "spatne"})
        while (m := ws.receive_json())["type"] != "mail_status":
            pass
        assert "Přihlášení nevyšlo" in m["error"] and not rt.cfg.mail.accounts
        ws.send_json({"type": "mail_account_add", "address": "adam@seznam.cz", "password": "dobre", "name": "Adam"})
        while (m := ws.receive_json())["type"] != "mail_status":
            pass
        acc = rt.cfg.mail.accounts[0]
        assert m["added"] == "adam@seznam.cz" and acc.imap_host == "imap.seznam.cz" and stored == {f"mail:{acc.id}": "dobre"}
        assert "dobre" not in rt.cfg.model_dump_json()


# ---------- calendar ----------
ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:zubar
DTSTART:20261026T090000Z
DTEND:20261026T093000Z
SUMMARY:Zubař
LOCATION:Praha 2
END:VEVENT
BEGIN:VEVENT
UID:fotbal
DTSTART;TZID=Europe/Prague:20261020T180000
DTEND;TZID=Europe/Prague:20261020T193000
RRULE:FREQ=WEEKLY;BYDAY=TU
SUMMARY:Fotbal
END:VEVENT
END:VCALENDAR
""".replace("\n", "\r\n").encode("utf-8")


def test_parse_ics_with_recurrence():
    evs = parse_ics(ICS, dt.datetime(2026, 10, 26), dt.datetime(2026, 10, 28))
    assert [e["title"] for e in evs] == ["Zubař", "Fotbal"]
    from zoneinfo import ZoneInfo

    assert evs[1]["start"] == dt.datetime(2026, 10, 27, 18, 0, tzinfo=ZoneInfo("Europe/Prague")).timestamp()   # 18:00 Prague
    assert evs[0]["location"] == "Praha 2"


async def test_calendar_add_list_remind(rt, monkeypatch):
    said = []
    monkeypatch.setattr(rt, "notify", lambda title, body, **k: said.append(body))
    start = (dt.datetime.now() + dt.timedelta(minutes=10)).replace(second=0, microsecond=0)
    r = await tools.call("calendar_add", {"title": "Schůzka s Petrem", "start": start.strftime("%Y-%m-%dT%H:%M"), "location": "kavárna"}, rt)
    assert r.ok and "připomenu 15 min předem" in r.summary
    lst = await tools.call("calendar_list", {"day": "dnes"}, rt)
    if start.date() == dt.date.today():
        assert "Schůzka s Petrem (kavárna)" in lst.summary
    at = start - dt.timedelta(minutes=10)
    await rt.calendar.remind_due(at)
    await rt.calendar.remind_due(at + dt.timedelta(seconds=30))     # said only once
    assert said == ["Za 10 min: Schůzka s Petrem (kavárna)."]
    assert (await tools.call("calendar_delete", {"id": r.data["id"]}, rt)).ok


async def test_calendar_feed_and_briefing(rt, monkeypatch):
    import httpx

    rt.transport = httpx.MockTransport(lambda req: httpx.Response(200, content=ICS))
    rt.cfg = config.apply_patch(rt.cfg, {"calendar": {"ics_urls": ["webcal://calendar.google.com/x/basic.ics"]}})
    evs = await rt.calendar.day(dt.date(2026, 10, 26))
    assert [e["title"] for e in evs] == ["Zubař"] and evs[0]["readonly"]

    async def no_weather(*a, **k):
        raise OSError

    monkeypatch.setattr("jarvis.tools.weather.fetch_weather", no_weather)
    from jarvis import stark

    b = await stark.briefing(rt, dt.datetime(2026, 10, 26, 7, 0), news=False)
    assert "V kalendáři: " in b["text"] and "Zubař (Praha 2)" in b["text"]
