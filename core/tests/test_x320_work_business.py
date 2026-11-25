"""3.20 Práce+ (261–280) a Firma+ (281–300)."""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pytest

from jarvis import bizx, tools, workx


# ================================================================== Práce+
def test_hosts_block_and_unblock():
    cur = "127.0.0.1 localhost\n"
    blocked = workx.hosts_with_block(cur, ["youtube.com", "reddit.com"])
    assert "0.0.0.0 youtube.com # JARVIS focus" in blocked and blocked.startswith("127.0.0.1 localhost")
    assert workx.hosts_with_block(blocked, ["x.com"]).count(workx.HOSTS_MARK) == 1       # replaced, not piled up
    assert workx.hosts_without_block(blocked) == cur


def test_focus_pomodoro_topic(rt, monkeypatch, tmp_path):
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1 localhost\n", encoding="utf-8")
    monkeypatch.setattr(workx, "hosts_path", lambda: hosts)
    r = workx.deep_focus(rt, 50)
    assert r["blocked"] and "youtube.com" in hosts.read_text(encoding="utf-8")
    workx.focus_end(rt)
    assert "youtube" not in hosts.read_text(encoding="utf-8") and workx.focus_stats(rt)["focus"]["sessions"] == 1
    p = workx.Pomodoro(25, 5, 2)
    st = p.start(0)
    assert st["phase"] == "work" and st["until"] == 1500 and p.tick(100) is None
    assert p.tick(1500)["phase"] == "rest" and p.tick(1800)["phase"] == "work" and p.n == 2
    assert p.tick(1800 + 1500)["phase"] == "rest" and p.tick(1800 + 1500 + 300) == {"phase": "done", "n": 2}
    assert workx.focus_topic_holds("faktury", "Discord", "Petr: ahoj") and not workx.focus_topic_holds("faktury", "Fakturoid", "nová faktura")
    rt.focus_topic = "faktury"
    assert rt.notify("Discord", "Petr: ahoj") == 0 and rt.focus_held
    rt.notify("Fakturoid", "nová faktura zaplacena")
    assert rt.notices[0]["title"] == "Fakturoid"
    rt.focus_topic = ""


def test_autoreply_bodies():
    g = workx.gmail_vacation_body(True, "Jsem pryč", dt.date(2026, 12, 20), dt.date(2027, 1, 2))
    assert g["enableAutoReply"] and g["endTime"] > g["startTime"] and g["responseBodyPlainText"] == "Jsem pryč"
    o = workx.outlook_vacation_body(True, "Jsem pryč", dt.date(2026, 12, 20), dt.date(2027, 1, 2))
    assert o["automaticRepliesSetting"]["status"] == "scheduled" and o["automaticRepliesSetting"]["scheduledEndDateTime"]["dateTime"].startswith("2027-01-03")
    assert "Do 02. 01. 2027" in workx.vacation_text(dt.date(2027, 1, 2), "Adam", "Jana")


def test_notes_attachments_morning(rt):
    assert workx.note_category("Zavolat Petrovi kvůli smlouvě") == "úkol"
    assert workx.note_category("Nápad: co kdyby notch uměl…") == "nápad"
    assert workx.note_category("Jen tak") == "poznámka"
    r = workx.quick_note(rt, "Nezapomeň poslat fakturu Alfě")
    assert r["category"] == "úkol" and workx.db(rt).one("SELECT title FROM wk_board")["title"].startswith("Nezapomeň")
    assert workx.mentions_attachment("Dobrý den, v příloze posílám nabídku.") and not workx.mentions_attachment("Díky za info.")
    assert workx.morning_slot(dt.datetime(2026, 11, 25, 14, 0)) is None
    assert workx.morning_slot(dt.datetime(2026, 11, 25, 22, 30)) == dt.datetime(2026, 11, 26, 8, 0)
    assert workx.morning_slot(dt.datetime(2026, 11, 27, 21, 0)) == dt.datetime(2026, 11, 30, 8, 0)      # Friday night → Monday
    assert workx.morning_slot(dt.datetime(2026, 11, 26, 6, 30)) == dt.datetime(2026, 11, 26, 8, 0)
    assert workx.morning_slot(dt.datetime(2026, 12, 23, 21, 0)) == dt.datetime(2026, 12, 28, 8, 0)      # over Christmas


async def test_email_send_blocks_missing_attachment(rt):
    r = await tools.call("email_send", {"to": "a@b.cz", "subject": "Nabídka", "body": "V příloze posílám nabídku."}, rt)
    assert not r.ok and "příloze" in r.summary


def test_timesheet_and_triage(rt):
    rules = {"Alfa": ["alfa", "figma"], "Interní": ["jira"]}
    assert workx.project_of("Figma", "Návrh – Beta", rules) == "Alfa" and workx.project_of("Spotify", "", rules) == ""
    day = dt.date(2026, 11, 25)
    for _ in range(90):
        workx.track_minute(rt, {"app": "Figma", "title": "x"}, rules, day)
    workx.track_minute(rt, {"app": "Chrome", "title": "JIRA board"}, rules, day, 30)
    assert workx.timesheet(rt, day, day) == [{"project": "Alfa", "hours": 1.5}, {"project": "Interní", "hours": 0.5}]
    assert workx.triage({"from": "newsletter@shop.cz", "subject": "Sleva"}) == "archive"
    assert workx.triage({"from": "petr@firma.cz", "subject": "Smlouva", "snippet": "Můžeš to prosím zkontrolovat?"}) == "reply"
    assert workx.triage({"from": "petr@firma.cz", "subject": "Zápis z porady", "snippet": "Posílám zápis."}) == "read"


def test_docx_translate_pptx_sign(tmp_path):
    from docx import Document

    src = tmp_path / "a.docx"
    d = Document()
    d.add_heading("Nabídka", 1)
    d.add_paragraph("Dobrý den, posíláme nabídku.")
    t = d.add_table(rows=1, cols=1)
    t.rows[0].cells[0].text = "Cena"
    d.save(str(src))
    n = workx.translate_docx(src, tmp_path / "b.docx", lambda s: s.upper())
    out = Document(str(tmp_path / "b.docx"))
    assert n == 3 and out.paragraphs[0].text == "NABÍDKA" and out.paragraphs[0].style.name.startswith("Heading")
    assert out.tables[0].rows[0].cells[0].text == "CENA"
    outline = workx.parse_outline("# Úvod\n- proč\n- co\nVýsledky:\n- 20 % rychleji\nZávěr")
    assert outline == [{"title": "Úvod", "bullets": ["proč", "co"]}, {"title": "Výsledky", "bullets": ["20 % rychleji", "Závěr"]}]
    pp = workx.outline_to_pptx(outline, tmp_path / "s.pptx", "Projekt")
    from pptx import Presentation

    assert len(Presentation(str(pp)).slides) == 3
    from PIL import Image
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "doc.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(100, 700, "Smlouva")
    c.save()
    sig = tmp_path / "sig.png"
    Image.new("RGBA", (300, 100), (0, 0, 255, 255)).save(sig)
    signed = workx.sign_pdf(pdf, sig, tmp_path / "signed.pdf")
    from pypdf import PdfReader

    assert "Podepsano" in PdfReader(str(signed)).pages[0].extract_text()


def test_merge_slots_board_faq_eod(rt):
    row = {"Jméno": "Petr", "Firma": "Alfa"}
    assert workx.merge("Dobrý den {jméno}, děkujeme firmě {firma}. {telefon}", row) == "Dobrý den Petr, děkujeme firmě Alfa. [chybí: telefon]"
    assert workx.merge_rows("jméno;email\nPetr;p@a.cz\n") == [{"jméno": "Petr", "email": "p@a.cz"}]
    day = dt.date(2026, 11, 26)
    busy = [(dt.datetime(2026, 11, 26, 9, 0), dt.datetime(2026, 11, 26, 11, 0)), (dt.datetime(2026, 11, 26, 12, 0), dt.datetime(2026, 11, 26, 16, 30))]
    slots = workx.free_slots(busy, day, 60)
    assert [s.strftime("%H:%M") for s in slots] == ["11:00"]
    fb = {"calendars": {"a@b.cz": {"busy": [{"start": "2026-11-26T08:00:00Z", "end": "2026-11-26T09:00:00Z"}]}}}
    assert len(workx.parse_freebusy(fb)) == 1
    bid = workx.board_add(rt, "Nabídka pro Alfu")
    assert workx.board_move(rt, bid, "doing") and not workx.board_move(rt, bid, "nesmysl")
    assert "Nabídka pro Alfu" in workx.board_html(rt)
    workx.faq_add(rt, "Jak se připojím na VPN?", "Otevři FortiClient a přihlas se firemním účtem.")
    hit = workx.faq_find(rt, "jak se pripojit na vpn z domu")
    assert hit and "FortiClient" in hit["answer"] and workx.faq_find(rt, "kolik stojí oběd") is None
    items = workx.open_items(rt)
    assert any("Nabídka pro Alfu" in i for i in items) and workx.move_to_tomorrow(rt) == 1
    assert "localStorage" in workx.write_page(800) and "cíl 800" in workx.write_page(800)


async def test_send_later_job(rt):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    sent = []

    class Acc:
        def send(self, to, subject, body):
            sent.append((to, subject, body))

    class Mail:
        def account(self, which=""):
            return Acc()

    import jarvis.tools.mail_tools as mt

    orig = mt._mail
    mt._mail = lambda ctx: Mail()
    try:
        job = rt.scheduler.add_once(dt.datetime.now() + dt.timedelta(seconds=1), "send_mail", {"to": "a@b.cz", "subject": "Ahoj", "body": "Text"},
                                    title="E-mail")
        await rt.scheduler._run(job) if hasattr(rt.scheduler, "_run") else await rt.scheduler.run_job(job)
    finally:
        mt._mail = orig
    assert sent == [("a@b.cz", "Ahoj", "Text")]


# ================================================================== Firma+
def test_ico_ares_vat_isir():
    assert bizx.ico_ok("27082440") and bizx.ico_ok("25596641") and not bizx.ico_ok("27082441") and not bizx.ico_ok("123")
    a = bizx.parse_ares({"ico": "27082440", "obchodniJmeno": "Alza.cz a.s.", "dic": "CZ27082440",
                         "sidlo": {"textovaAdresa": "Jankovcova 1522/53, Praha 7"}, "datumVzniku": "2003-08-26"})
    assert a["name"] == "Alza.cz a.s." and a["address"].startswith("Jankovcova") and a["ended"] == ""
    xml = ('<soapenv:Envelope><soapenv:Body><StatusNespolehlivyPlatceResponse><statusPlatceDPH dic="27082440" nespolehlivyPlatce="NE">'
           '<zverejneneUcty><ucet><standardniUcet cislo="1234567" kodBanky="0300"/></ucet></zverejneneUcty></statusPlatceDPH>'
           "</StatusNespolehlivyPlatceResponse></soapenv:Body></soapenv:Envelope>")
    assert bizx.parse_vat(xml) == {"known": True, "unreliable": False, "accounts": ["1234567/0300"]}
    assert bizx.parse_vat(xml.replace('"NE"', '"ANO"'))["unreliable"]
    assert bizx.parse_isir("<html><td>Nebyl nalezen žádný záznam</td></html>") == {"found": False}
    assert bizx.parse_isir("<td>INS 12345/2025</td><td>KSPH</td>")["cases"] == ["INS 12345/2025"]


async def test_ares_client():
    class R:
        status_code = 200

        def json(self):
            return {"ico": "27082440", "obchodniJmeno": "Alza.cz a.s."}

        def raise_for_status(self):
            pass

    class C:
        async def get(self, url, timeout):
            assert url.endswith("/27082440")
            return R()

        async def aclose(self):
            pass

    assert (await bizx.ares(None, "27082440", C()))["name"] == "Alza.cz a.s."
    with pytest.raises(ValueError):
        await bizx.ares(None, "12345678", C())


async def test_feeds(rt):
    xml = ("<rss><channel><item><title>Tisk letáků – Praha</title><link>https://x/1</link><description>Zakázka na <b>tisk</b></description></item>"
           "<item><title>Stavba mostu</title><link>https://x/2</link></item></channel></rss>")
    items = bizx.parse_feed(xml)
    assert items[0] == {"title": "Tisk letáků – Praha", "link": "https://x/1", "text": "Zakázka na tisk"}
    assert [i["link"] for i in bizx.feed_hits(items, ["tisk"], "praha")] == ["https://x/1"]

    async def fetch(url):
        return xml

    assert len(await bizx.watch_feeds(rt, ["u"], ["tisk"], fetch=fetch)) == 1
    assert await bizx.watch_feeds(rt, ["u"], ["tisk"], fetch=fetch) == []               # once
    atom = '<feed><entry><title>Nová povinnost pro e-shopy</title><link href="https://y/1"/><summary>DPH</summary></entry></feed>'
    assert bizx.parse_feed(atom)[0]["link"] == "https://y/1"


def test_contract_attendance_cash_shifts(rt):
    text = ("Smlouva se automaticky prodlužuje o další rok. Dodavatel si vyhrazuje právo změnit ceník. V případě prodlení zaplatí "
            "odběratel smluvní pokutu 0,5 % denně. Spory rozhodne rozhodce.")
    risks = [r["risk"] for r in bizx.contract_risks(text)]
    assert {"Smluvní pokuta", "Automatické prodloužení", "Jednostranná změna podmínek", "Rozhodčí doložka"} <= set(risks)
    assert bizx.contract_risks("Kupující zaplatí cenu do 14 dnů.") == []
    t0 = dt.datetime(2026, 11, 3, 8, 0).timestamp()
    bizx.clock_in(rt, "Jana", t0)
    with pytest.raises(ValueError):
        bizx.clock_in(rt, "Jana", t0 + 60)
    assert bizx.clock_out(rt, "Jana", t0 + 8.5 * 3600) == 8.5
    assert bizx.hours(rt, "2026-11") == {"Jana": 8.5}
    rows = bizx.forecast(50000, 80000, 95000, [("2027-01-15", -30000)], 3, dt.date(2026, 11, 1))
    assert [r["balance"] for r in rows] == [35000, 20000, -25000] and rows[2]["low"]
    sh = bizx.plan_shifts(["po", "út"], ["ranní"], {"Jana": ["po-ranní", "út-ranní"], "Petr": ["po-ranní"]})
    assert sh["plan"] == {"po-ranní": ["Jana"], "út-ranní": ["Jana"]} or sh["count"]["Petr"] == 1
    assert sh["gaps"] == []
    sh2 = bizx.plan_shifts(["st"], ["noční"], {"Jana": []})
    assert sh2["gaps"] == ["st-noční"]


def test_claims_gdpr_suppliers_margin_fx(rt):
    cid = bizx.claim_add(rt, "Novák", "Rozbitý kávovar", "2026-11-01")
    due = bizx.claims_due(rt, dt.date(2026, 11, 25))
    assert due and due[0]["left"] == 6
    assert bizx.claim_close(rt, cid, "vyměněno") and bizx.claims_due(rt, dt.date(2026, 11, 25)) == []
    from jarvis import workx as w

    w.quick_note(rt, "Novák chce nabídku na servis")
    g = bizx.gdpr_find(rt, "novák")
    assert "wk_notes" in g["found"] and g["deadline_days"] == 30
    assert bizx.gdpr_delete(rt, "Novák") >= 1 and "wk_notes" not in bizx.gdpr_find(rt, "novák")["found"]
    comp = bizx.compare_suppliers([{"item": "Papír A4", "supplier": "Alfa", "price": 120}, {"item": "papír a4", "supplier": "Beta", "price": 99}])
    assert comp[0]["best"] == "Beta" and comp[0]["others"][0]["more_pct"] == 21.2
    m = bizx.margin(1210, 600, fee_pct=10, shipping=50)
    assert m == {"net_price": 1000.0, "fees": 100.0, "profit": 250.0, "margin_pct": 25.0, "markup_pct": 41.7}
    fx = bizx.fx_difference(1000, 25.0, 24.5)
    assert fx == {"issued_czk": 25000.0, "paid_czk": 24500.0, "difference": -500.0, "kind": "kurzová ztráta"}


def test_team_templates_cv_onboard_pack(rt, tmp_path):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    tok = bizx.team_create(rt)
    c = TestClient(create_app(rt, manage_runtime=False), client=("85.1.2.3", 5000))
    r = c.post(f"/team/{tok}", content="who=Jana&task=Poslat+nab%C3%ADdku", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and "Poslat nabídku" in r.text
    tid = next(t["id"] for t in bizx.team_tasks(rt, tok) if t["task"] == "Poslat nabídku")
    assert "class=done" in c.post(f"/team/{tok}/done/{tid}").text
    assert c.get("/team/neni").status_code == 404
    doc = bizx.contract_from_template("nda", {"name": "Alfa s.r.o.", "ico": "27082440", "purpose": "vývoj aplikace", "my_name": "Já"})
    assert doc.startswith("Dohoda o mlčenlivosti") and "Alfa s.r.o." in doc and "[address]" in doc and "právníkem" in doc
    with pytest.raises(ValueError):
        bizx.contract_from_template("kupni", {})
    s = bizx.cv_score("Python developer, 5 let praxe, Django, PostgreSQL, Docker", ["python", "django", "react"], ["docker"])
    assert s["has"] == ["python", "django"] and s["missing"] == ["react"] and s["bonus"] == ["docker"] and s["years"] == 5
    assert bizx.onboard_start(rt, "Petr") == len(bizx.ONBOARD)
    r2 = bizx.onboard_tick(rt, "Petr", "bozp")
    assert r2["ticked"] == "Školení BOZP" and len(r2["left"]) == len(bizx.ONBOARD) - 1
    f = tmp_path / "Faktura-2026-11.pdf"
    f.write_bytes(b"%PDF")
    rt.db.exec("INSERT INTO attachments VALUES (?,?,?,?,?,?,?,?,?,?)",
               ("a1", None, "Faktura-2026-11.pdf", "application/pdf", 4, "pdf", str(f), "", None, dt.datetime(2026, 11, 10).timestamp()))
    pack = bizx.accountant_pack(rt, "2026-11", tmp_path / "out.zip")
    import zipfile

    names = zipfile.ZipFile(pack["path"]).namelist()
    assert pack["documents"] == 1 and "doklady/Faktura-2026-11.pdf" in names and "prehled.csv" in names
    page = bizx.travel_order_html("Adam", "2026-11-03 07:00", "2026-11-03 19:00", "Brno", "jednání", "auto", {"text": "152 Kč"}, 400, 5.6)
    assert "Cestovní příkaz" in page and "2 240 Kč" in page
    _ = (json, time, Path)


async def test_x8_tools(rt):
    for n in ("work_kit", "biz_kit"):
        assert n in tools.REGISTRY
    r = await tools.call("biz_kit", {"action": "margin", "amount": 1210, "cost": 600}, rt)
    assert r.ok and "marže" in r.summary
    r = await tools.call("work_kit", {"action": "note", "text": "Zavolat do banky"}, rt)
    assert r.ok and "úkol" in r.summary
    r = await tools.call("work_kit", {"action": "faq", "text": "nic"}, rt)
    assert not r.ok


async def test_travel_order_tool(rt):
    spec = {"name": "Adam", "start": "2026-11-03T07:00", "end": "2026-11-03T19:00", "dest": "Brno", "purpose": "jednání", "km": 400, "rate_km": 5.6}
    r = await tools.call("biz_kit", {"action": "travel_order", "text": json.dumps(spec)}, rt)
    assert r.ok
    page = Path(r.data["path"]).read_text(encoding="utf-8")
    assert "Brno" in page and "CZK" in page and "2 240 Kč" in page


def test_outward_actions_ask_first():
    reg = tools.REGISTRY
    for name, action in (("work_kit", "autoreply"), ("work_kit", "send_later"), ("work_kit", "sign"), ("biz_kit", "gdpr_delete"),
                         ("biz_kit", "team"), ("phone_kit", "share_location")):
        assert reg[name].danger_if({"action": action}), (name, action)
    for name, action in (("work_kit", "note"), ("biz_kit", "margin"), ("phone_kit", "status")):
        assert not reg[name].danger_if({"action": action}), (name, action)
