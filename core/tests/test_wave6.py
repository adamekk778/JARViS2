"""OMEGA wave 6: communication (ranking, unified inbox, actions, contact card, follow-ups, digest) and meetings
(clashes, travel buffer, free slots, preparation, minutes) – with a fake mailbox and calendar."""
import datetime as dt
import json
import threading
import time

from conftest import FakeRouter

from jarvis import comms, tools

tools.load_builtin()
NOW = time.time()


class FakeAcc:
    def __init__(self, inbox, sent=(), bodies=None):
        self.inbox, self.sent, self.bodies = list(inbox), list(sent), bodies or {}
        self.cfg = type("C", (), {"address": "ja@example.cz", "id": "a1"})()
        self.lock = threading.RLock()

    def list(self, limit=10, query="", folder="INBOX", unread=False):
        src = self.sent if folder == "Sent" else self.inbox
        q = comms.fold(query)
        return [m for m in src if not q or q in comms.fold(m["subject"] + m["from_name"] + m["from"])][:limit]

    def folder(self, flag, fallbacks):
        return "Sent"

    def read(self, uid, mark_seen=True):
        m = next(m for m in self.inbox if m["uid"] == uid)
        return {**m, "text": self.bodies.get(uid, ""), "attachments": m.get("attachments", []), "to": "ja@example.cz"}


def mail(uid, frm, subject, hours_ago=1, unread=True, newsletter=False, name=""):
    return {"id": f"a1:{uid}", "uid": uid, "from": frm, "from_name": name or frm.split("@")[0], "subject": subject,
            "date": NOW - hours_ago * 3600, "unread": unread, "newsletter": newsletter, "account": "ja@example.cz"}


def install(rt, acc):
    rt.mail.accounts = {"a1": acc}
    rt.mail.sync = lambda: None
    rt.mail.account = lambda which="": acc
    rt.mail.by_id = lambda mid: (acc, int(mid.split(":")[1]))


def test_rank_reasons():
    s, why = comms.rank({"subject": "Faktura – splatnost zítra", "text": "Prosím zaplaťte do pátku?", "unread": True}, vip=True)
    assert s >= 90 and {"důležitý kontakt", "termín / naléhavé", "chce po tobě něco", "peníze", "otázka"} <= set(why)
    low, why2 = comms.rank({"subject": "Týdenní novinky", "newsletter": True, "date": NOW - 5 * 86400})
    assert low < 20 and "newsletter" in why2


async def test_unified_inbox_merges_email_and_phone(rt):
    install(rt, FakeAcc([mail(1, "news@shop.cz", "Slevy týdne", newsletter=True), mail(2, "sef@firma.cz", "Prosím pošli report do pátku", name="Šéf")]))
    rt.update_config({"mail": {"vip": ["sef@firma.cz"]}})
    rt.phone.notifications.appendleft({"app": "WhatsApp", "package": "com.whatsapp", "title": "Máma", "text": "Zavolej mi prosím",
                                       "ts": NOW - 60, "messaging": True, "call": False})
    r = await tools.call("inbox_overview", {}, rt)
    order = [i["from"] for i in r.data]
    assert r.ok and order[0] == "Šéf" and order[-1] == "news" and "Máma" in order
    assert r.summary.startswith("[Zprávy od třetích osob")


def test_extract_actions_and_due_dates():
    today = dt.date(2026, 10, 26)                                     # a Monday
    acts = comms.extract_actions("Ahoj. Prosím pošli mi fakturu do pátku. Díky! Můžeš zavolat zítra?\nNezapomeň na klíče.", "Jana", today)
    assert [a["task"] for a in acts] == ["Prosím pošli mi fakturu do pátku.", "Můžeš zavolat zítra?", "Nezapomeň na klíče."]
    assert [a["due"] for a in acts] == ["2026-10-30", "2026-10-27", ""]
    assert comms.due_date("odevzdat do 3. 11.", today) == "2026-11-03"


async def test_message_actions_to_list(rt):
    install(rt, FakeAcc([mail(5, "jana@x.cz", "Smlouva")], bodies={5: "Dobrý den, prosím podepište smlouvu do 30. 10. 2026."}))
    r = await tools.call("message_actions", {"add_to_list": "úkoly"}, rt)
    from jarvis.tools.list_tools import items_of

    assert r.ok and r.data[0]["due"] == "2026-10-30" and "podepište smlouvu" in items_of(rt, "úkoly")[0]["item"]


async def test_contact_card(rt):
    install(rt, FakeAcc([mail(1, "petr@firma.cz", "Nabídka", name="Petr Novák"), mail(2, "x@y.cz", "Jiné")]))
    rt.knowledge.add_fact("Petr Novák je náš účetní", "test")
    rt.calendar.add("Schůzka s Petr Novák", dt.datetime.now() + dt.timedelta(days=1))
    r = await tools.call("contact_card", {"who": "Petr Novák"}, rt)
    assert r.ok and "1 zpráv" in r.summary and "účetní" in r.summary and "petr@firma.cz" in r.summary and "Schůzka" in r.summary


def test_follow_ups_and_reply_time():
    inbox = [mail(1, "klient@x.cz", "Poptávka", hours_ago=100), mail(2, "jana@x.cz", "Re: Faktura", hours_ago=20),
             mail(3, "petr@x.cz", "Dotaz", hours_ago=120)]
    sent = [{"subject": "Faktura", "date": NOW - 30 * 3600, "to": "jana@x.cz", "from": "ja"},
            {"subject": "Nabídka", "date": NOW - 6 * 86400, "to": "firma@x.cz", "from": "ja"},
            {"subject": "Re: Poptávka", "date": NOW - 98 * 3600, "to": "klient@x.cz", "from": "ja"}]
    r = comms.follow_ups(sent, inbox, 3)
    assert [w["subject"] for w in r["waiting_for_them"]] == ["Nabídka"]
    assert [w["subject"] for w in r["you_did_not_answer"]] == ["Dotaz"]
    assert r["avg_reply_hours"] == 2.0


async def test_digest(rt):
    install(rt, FakeAcc([mail(1, "sef@firma.cz", "Urgentní: prosím potvrď termín"), mail(2, "n@n.cz", "Novinky", newsletter=True)]))
    r = await tools.call("communication_digest", {"hours": 24}, rt)
    assert r.ok and "2 e-mailů" in r.summary and "Chtějí po tobě" in r.summary


# ---------------------------------------------------------------------------------------------- calendar
def ev(title, h0, h1, loc="", day=None):
    d = day or dt.date.today()
    return {"title": title, "start": dt.datetime.combine(d, dt.time(0)).timestamp() + h0 * 3600,
            "end": dt.datetime.combine(d, dt.time(0)).timestamp() + h1 * 3600, "location": loc}


def test_clashes_travel_and_free_slots():
    e = [ev("Porada", 9, 10, "Kancelář"), ev("Zubař", 9.5, 10.5, "Brno"), ev("Oběd", 10.75, 11.5, "Centrum"), ev("Kino", 20, 22)]
    r = comms.clashes(e, 30)
    assert r["overlaps"][0]["a"] == "Porada" and r["overlaps"][0]["minutes"] == 30
    assert r["travel"][0]["to"] == "Oběd" and r["travel"][0]["gap_min"] == 15
    slots = comms.free_slots(e, dt.date.today(), 8, 18, 30)
    assert slots == [("08:00", "09:00"), ("11:30", "18:00")]
    txt = comms.availability_text([(dt.date(2026, 11, 3), slots)])
    assert txt == "Můžu: út 3. 11. 08:00–09:00, 11:30–18:00."


async def test_free_time_and_calendar_check_tools(rt):
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    rt.calendar.add("A", dt.datetime.combine(tomorrow, dt.time(9)), 120, "Praha")
    rt.calendar.add("B", dt.datetime.combine(tomorrow, dt.time(10)), 60, "Brno")
    c = await tools.call("calendar_check", {"days": 3}, rt)
    assert "Kryje se: „A“ a „B“" in c.summary
    f = await tools.call("free_time", {"days": 3, "weekends": True}, rt)
    assert f.ok and f.summary.startswith("Můžu:")


async def test_meeting_prep_and_minutes(rt):
    rt.calendar.add("Projekt pekárna", dt.datetime.now() + dt.timedelta(hours=3))
    rt.knowledge.add_fact("Projekt pekárna má termín v listopadu", "test")
    rt.router = FakeRouter([json.dumps({"agenda": [{"point": "Termín v listopadu", "why": "z paměti"}]})])
    r = await tools.call("meeting_prep", {"title": "pekárna"}, rt)
    assert r.ok and "Program: 1. Termín v listopadu" in r.summary
    rt.db.exec("INSERT INTO notes (id, created, title, seconds, status, transcript, summary, points, todos, error) VALUES (?,?,?,?,?,?,?,?,?,?)",
               ("n1", NOW, "Porada", 600, "done", json.dumps([{"who": "Já", "text": "Navrhuji spustit web v listopadu."},
                                                              {"who": "Ostatní", "text": "Souhlasím, Petr připraví ceny do pátku."}]),
                "", "[]", "[]", ""))
    rt.router = FakeRouter([json.dumps({"decisions": ["Web se spustí v listopadu"], "actions": [{"task": "Připravit ceny", "owner": "Petr", "due": "2026-10-30"}],
                                        "open_questions": [], "follow_up_email": {"subject": "Shrnutí porady", "body": "…"}})])
    m = await tools.call("meeting_minutes", {"id": "n1", "to_list": "úkoly"}, rt)
    assert m.ok and "Rozhodnuto: Web se spustí v listopadu" in m.summary and "Připravit ceny (Petr, do 2026-10-30)" in m.summary
    assert m.data["speakers"] == {"Ostatní": 55, "Já": 45}
    assert "neodešle" not in m.summary and "až řekneš" in m.summary
