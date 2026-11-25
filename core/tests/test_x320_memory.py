"""3.20 Paměť+ (nápady 41–60)."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import time

import pytest
from conftest import FakeRouter

from jarvis import memx, tools


def _fact(rt, text, created=None, source=""):
    memx.db(rt)
    cur = rt.db.exec("INSERT INTO facts(text, created, source) VALUES (?,?,?)", (text, created or time.time(), source))
    return cur.lastrowid


# ------------------------------------------------------------------ (41) wiki, (45) původ
async def test_wiki_and_origin(rt):
    fid = _fact(rt, "Uživatel má rád kávu bez cukru.")
    rt.db.exec("INSERT INTO messages(id, conv_id, role, content, attachments, source, created, meta) VALUES (?,?,?,?,?,?,?,?)",
               ("m1", "c1", "user", "zapamatuj si, že piju kávu bez cukru", "[]", "chat", time.time() - 5, "{}"))
    r = await tools.call("memory_kit", {"action": "wiki"}, rt)
    html = open(r.data["path"], encoding="utf-8").read()
    assert r.ok and "kávu bez cukru" in html and "prefers-color-scheme:dark" in html
    o = memx.origin(rt, "kávu")
    assert o[0]["id"] == fid and o[0]["said"] == "zapamatuj si, že piju kávu bez cukru"
    assert memx.edit_fact(rt, fid, "Uživatel pije kávu s mlékem.")
    assert "s mlékem" in memx.wiki_html(rt)


# ------------------------------------------------------------------ (42) zapomeň i ze záloh
async def test_forget_everywhere_and_after_a_restore(rt, tmp_path):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    dest = tmp_path / "zaloha"
    (dest / "JARVIS").mkdir(parents=True)
    copy = dest / "JARVIS" / "jarvis.db"
    con = sqlite3.connect(str(copy))
    con.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, text TEXT, created REAL)")
    con.execute("INSERT INTO facts(text, created) VALUES ('Heslo k Wi-Fi je Kocka123', 1)")
    con.commit()
    con.close()
    rt.scheduler.add({"type": "daily", "time": "02:00"}, "backup", {"source": str(tmp_path), "destination": str(dest)})
    _fact(rt, "Heslo k Wi-Fi je Kocka123")
    r = await tools.call("memory_kit", {"action": "forget_all", "text": "heslo k wi-fi"}, rt)
    assert r.ok and r.data["in_backups"] == 1
    assert not sqlite3.connect(str(copy)).execute("SELECT * FROM facts").fetchall()
    _fact(rt, "Heslo k Wi-Fi je Kocka123")                  # an older backup was restored
    assert memx.apply_tombstones(rt) == 1 and not rt.db.all("SELECT * FROM facts WHERE text LIKE '%Kocka%'")


# ------------------------------------------------------------------ (43) přání, (47) kam jsem to dal, (48) doporučení
async def test_quick_memory_commands_without_the_ai(rt):
    rt.router = FakeRouter([])
    assert (await rt.agent.handle("Jana by chtěla nová bezdrátová sluchátka")).startswith("Zapsáno jako tip na dárek pro Jana")
    assert memx.wishes(rt, "Jana")[0]["item"] == "nová bezdrátová sluchátka"
    assert (await rt.agent.handle("klíče od sklepa jsou v šuplíku u dveří")).startswith("Zapamatováno")
    out = await rt.agent.handle("kde jsou klíče od sklepa?")
    assert "v šuplíku u dveří" in out
    assert "Nevím, kde je" in await rt.agent.handle("kde je deštník?")
    assert (await rt.agent.handle("Petr mi doporučil film Interstellar")).startswith("Zapsáno: film „Interstellar“")
    assert memx.recs(rt, "film")[0]["by"] == "Petr"
    assert not rt.router.calls


def test_wish_and_place_are_not_everything():
    assert memx.detect_wish("Petr chce jít na pivo") == ("Petr", "jít na pivo")       # quick() filters verbs out
    assert memx.detect_wish("To by chtělo opravit") is None


# ------------------------------------------------------------------ (44) časová osa, (52) rok v kostce, (53) deník
async def test_timeline_year_and_diary(rt):
    _fact(rt, "Svatba byla 12. 6. 2015.")
    memx.diary_add(rt, "Výlet na Sněžku, krásný výhled.", dt.date(2026, 7, 4))
    tl = memx.timeline(rt)
    assert [e["kind"] for e in tl] == ["fakt", "deník"] and tl[0]["date"] == "2015-06-12"
    assert memx.diary(rt, "Sněžk")[0]["day"] == "2026-07-04"
    rt.router = FakeRouter(["Rok 2026 byl ve znamení hor."])
    assert await memx.year_story(rt, 2026) == "Rok 2026 byl ve znamení hor."
    assert "nemám skoro žádné záznamy" in await memx.year_story(rt, 1999)


async def test_diary_answer_after_the_evening_question(rt):
    rt.router = FakeRouter([])
    rt.memx_diary_asked = time.time()
    out = await rt.agent.handle("Dneska v práci dobrý, večer jsme byli v kině")
    assert out == "Zapsáno do deníku." and "v kině" in memx.diary(rt)[0]["text"] and not rt.router.calls


# ------------------------------------------------------------------ (46) výročí, (71) narozeniny s dárkem
def test_dates_and_gift_tip(rt):
    _fact(rt, "Jana má narozeniny 3. 12.")
    _fact(rt, "Výročí svatby je 12. 6. 2015.")
    assert memx.dates_from_facts(rt) == 2 and memx.dates_from_facts(rt) == 0
    memx.add_wish(rt, "Jana", "nová sluchátka")
    up = memx.upcoming_dates(rt, 10, dt.date(2026, 11, 26))
    assert up[0]["in_days"] == 7 and up[0]["kind"] == "narozeniny"
    assert memx.date_line(up[0], rt) == "Za 7 dní: Jana má narozeniny. Tip na dárek – Jana chtěl(a): nová sluchátka."
    june = memx.upcoming_dates(rt, 3, dt.date(2027, 6, 11))
    assert june[0]["years"] == 12


# ------------------------------------------------------------------ (49) vzpomínka s fotkou
async def test_photo_memory(rt):
    att = await rt.store.save("vylet.jpg", b"\xff\xd8\xff" + b"0" * 200, "image/jpeg")
    rt.router = FakeRouter([])
    rt.phone_location = {"place": "Sněžka"}
    out = await rt.agent.handle("pamatuj si tohle: výhled ze Sněžky", [att.id])
    assert out == "Zapamatováno i s fotkou." and not rt.router.calls
    row = rt.db.one("SELECT text, source FROM facts ORDER BY id DESC")
    assert row["text"] == "výhled ze Sněžky (místo: Sněžka)" and row["source"] == f"fotka:{att.id}"


# ------------------------------------------------------------------ (50) starší než rok
async def test_stale_facts_ask_and_buttons(rt):
    old = _fact(rt, "Pracuji ve firmě Alfa.", created=time.time() - 400 * 86400)
    _fact(rt, "Mám psa.")
    st = memx.stale_facts(rt)
    assert [f["id"] for f in st] == [old]
    ok, msg = await rt.notice_action("fact_confirm", {"id": old})
    assert ok and not memx.stale_facts(rt)
    ok, msg = await rt.notice_action("fact_drop", {"id": old})
    assert ok and not rt.db.one("SELECT id FROM facts WHERE id=?", (old,))


# ------------------------------------------------------------------ (51) rodina, (59) PIN
def test_family_sees_only_shared_and_locked_stays_locked(rt):
    _fact(rt, "Kód od branky je 4711.")
    _fact(rt, "Uživatel má rád kávu.")
    secret = _fact(rt, "Výsledky krve jsou v pořádku.")
    assert memx.share_fact(rt, "branky") == 1
    all_facts = [r["text"] for r in rt.db.all("SELECT text FROM facts")]
    assert memx.facts_for_speaker(rt, all_facts, True) == ["Kód od branky je 4711."]
    with pytest.raises(ValueError, match="PIN"):
        memx.lock_fact(rt, "krve")
    memx.set_pin(rt, "2468")
    assert memx.lock_fact(rt, f"#{secret}") == 1
    assert "Výsledky krve jsou v pořádku." not in memx.facts_for_speaker(rt, all_facts, False)
    assert "Výsledky krve" not in memx.wiki_html(rt)
    assert not memx.unlock(rt, "1111") and memx.unlock(rt, "2468")
    assert "Výsledky krve jsou v pořádku." in memx.facts_for_speaker(rt, all_facts, False)


# ------------------------------------------------------------------ (54) fotky s pamětí
async def test_photos_by_place_and_month(rt, tmp_path):
    from PIL import Image

    pics = tmp_path / "Fotky" / "Dovolená"
    pics.mkdir(parents=True)
    im = Image.new("RGB", (8, 8))
    ex = im.getexif()
    ex[0x9003] = "2026:07:04 10:00:00"
    ex[0x0132] = "2026:07:04 10:00:00"
    gps = {1: "N", 2: (50.0, 44.0, 9.0), 3: "E", 4: (15.0, 44.0, 23.0)}
    ex[0x8825] = gps
    im.save(pics / "snezka.jpg", exif=ex)
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES (?,?)", ("geo_50.74_15.74", "Pec pod Sněžkou"))
    r = await memx.index_photos(rt, tmp_path / "Fotky")
    assert r == {"seen": 1, "new": 1}
    assert len(memx.search_photos(rt, "fotky z Pece v červenci 2026")) == 1
    assert memx.search_photos(rt, "fotky z Brna") == []


# ------------------------------------------------------------------ (55) oblíbené odpovědi
def test_favorites(rt):
    rt.db.exec("INSERT INTO messages(id, conv_id, role, content, attachments, source, created, meta) VALUES (?,?,?,?,?,?,?,?)",
               ("a1", "c1", "assistant", "Recept na svíčkovou: …", "[]", "chat", time.time(), "{}"))
    assert memx.star(rt, "a1")
    assert memx.favorites(rt, "svíčkov")[0]["msg_id"] == "a1"
    assert json.loads(rt.db.one("SELECT meta FROM messages WHERE id='a1'")["meta"])["starred"] is True
    assert memx.star(rt, "a1", False) and memx.favorites(rt) == []


# ------------------------------------------------------------------ (56) dočasné vzpomínky
async def test_remember_until(rt):
    rt.router = FakeRouter([])
    out = await rt.agent.handle("pamatuj si do pátku, že parkuju v garáži B")
    assert out.startswith("Zapamatováno do") and not rt.router.calls
    row = rt.db.one("SELECT text, expires FROM facts ORDER BY id DESC")
    assert row["text"] == "parkuju v garáži B" and row["expires"] > time.time()
    assert dt.datetime.fromtimestamp(row["expires"]).hour == 23


# ------------------------------------------------------------------ (57) citlivé údaje
def test_sensitive_scan(rt):
    _fact(rt, "Moje karta 4111 1111 1111 1111 platí do 2028.")
    _fact(rt, "Heslo do banky je Tajne123")
    _fact(rt, "Číslo objednávky 1234 5678 9012 3456")              # not a card (fails the Luhn check)
    hits = memx.sensitive_scan(rt)
    assert [h["kind"] for h in hits] == ["karta", "heslo"]
    assert "1111 1111" not in hits[0]["text"] and "•••• 1111" in hits[0]["text"] and "Tajne123" not in hits[1]["text"]


# ------------------------------------------------------------------ (60) paměť přes víc PC
def test_sync_blob_needs_the_key(rt, tmp_path, monkeypatch):
    _fact(rt, "Uživatel má rád kávu.")
    blob = memx.export_facts(rt, "klic-A")
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "druhe-pc"))        # the other PC has its own database
    from jarvis.runtime import Runtime
    from jarvis.tools.platform.null import NullPlatform

    other = Runtime(platform=NullPlatform(), persist_config=False)
    with pytest.raises(ValueError, match="rozšifrovat"):
        memx.import_facts(other, blob, "jiny-klic")
    r = memx.import_facts(other, blob, "klic-A")
    assert r["added"] == 1 and other.db.one("SELECT source FROM facts")["source"] == "jiný počítač"
    assert memx.import_facts(other, blob, "klic-A")["added"] == 0


async def test_sync_handler_round_trip(rt):
    from jarvis.server.handlers import memxh

    _fact(rt, "Na tomhle PC: rád jezdím na kole.")
    sent = []

    class C:
        def __init__(self, r):
            self.rt = r

        async def send(self, t, **kw):
            sent.append((t, kw))
    other_blob = memx.export_facts(rt, rt.cfg.phone.token)
    await memxh.mem_sync(C(rt), {"blob": other_blob})
    assert sent[0][0] == "mem_sync_done" and "blob" in sent[0][1]
    await memxh.mem_sync(C(rt), {"blob": memx.export_facts(rt, "spatny")})
    assert sent[1][1]["error"].startswith("Data nejdou")
