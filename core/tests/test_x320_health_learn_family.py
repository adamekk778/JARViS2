"""3.20 Zdraví+ (241–260), Učení+ (361–380) a Rodina+ (381–400)."""
from __future__ import annotations

import datetime as dt
import json
import time

import pytest

from jarvis import familyx, healthx, learnx, tools


# ================================================================== Zdraví+
def test_meds_and_stock(rt):
    healthx.med_set(rt, "Euthyrox", ["7:00"], "1 tableta", stock=8, per_dose=1)
    with pytest.raises(ValueError):
        healthx.med_set(rt, "X", ["ráno"])
    due = healthx.meds_due(rt, dt.datetime(2026, 11, 25, 7, 0))
    assert any(d["kind"] == "dose" and "Euthyrox" in d["text"] for d in due)
    assert healthx.meds_due(rt, dt.datetime(2026, 11, 25, 7, 0)) == []           # once that minute
    r = healthx.med_taken(rt, "Euthyrox")
    assert r == {"stock": 7.0, "days_left": 7}
    due = healthx.meds_due(rt, dt.datetime(2026, 11, 26, 9, 0))
    assert any(d["kind"] == "stock" for d in due)
    assert healthx.adherence(rt, "Euthyrox")["taken"] == 1
    with pytest.raises(ValueError):
        healthx.med_taken(rt, "Neni")


def test_breathing_exercises_noise_light_gamma():
    b = healthx.breathing("4-7-8", 2)
    assert b["rounds"] == 6 and b["steps"][1] == {"say": "zadrž", "s": 7}
    assert len(healthx.exercise_set(3, seed=1)) == 3
    assert healthx.noise_db([0.5, -0.5] * 100, 90) == pytest.approx(84.0, abs=0.1)
    w = healthx.NoiseWatch(70, 10)
    assert w.feed(75, 0) == "" and w.feed(75, 300) == "" and "hluk přes 70 dB" in w.feed(76, 601) and w.feed(76, 700) == ""
    assert w.feed(50, 800) == ""
    assert healthx.light_advice(healthx.luminance((20, 25, 30))) and healthx.light_advice(healthx.luminance((150, 150, 150))) == ""
    ramp = healthx.gamma_ramp(3400)
    assert len(ramp) == 3 and ramp[0][255] > ramp[2][255] and ramp[0][0] == 0
    assert healthx.evening_kelvin(dt.datetime(2026, 11, 25, 20, 0)) == 6500
    assert healthx.evening_kelvin(dt.datetime(2026, 11, 25, 21, 30)) == 5000
    assert healthx.evening_kelvin(dt.datetime(2026, 11, 26, 2, 0)) == 3400


def test_diary_doctor_prevent_pharmacy(rt):
    now = time.time()
    healthx.symptom_add(rt, "Bolest hlavy", 4, ts=now - 10 * 86400)
    healthx.symptom_add(rt, "bolest hlavy", 7, "hlavně ráno", ts=now - 86400)
    healthx.med_set(rt, "Ibalgin", ["20:00"], "400 mg")
    b = healthx.doctor_brief(rt, questions=["Mám jít na vyšetření?"])
    assert "Bolest hlavy: 2×" in b and "zhoršuje se" in b and "hlavně ráno" in b and "Ibalgin 400 mg" in b and "1) Mám jít" in b
    healthx.prevent_set(rt, "Adam", "zubar", "2026-05-20")
    out = healthx.prevent_due(rt, dt.date(2026, 11, 10))
    assert out and "Zubař" in out[0] and "za 8 dní" in out[0]                 # 6 months ≈ 182 days
    healthx.pharmacy_set(rt, "Paralen", "2026-11-01")
    healthx.pharmacy_set(rt, "Ibuprofen 400", "2026-12-10")
    r = healthx.pharmacy_check(rt, dt.date(2026, 11, 25))
    assert r["expired"] == ["Paralen"] and r["soon"] == ["Ibuprofen 400"] and "paracetamol" in r["missing"] and "ibuprofen" not in r["missing"]


def test_child_fever_doses(rt):
    t0 = 1_000_000.0
    healthx.fever_log(rt, "Ema", 38.9, "paracetamol", 250, ts=t0)
    r = healthx.next_dose(rt, "Ema", "Paracetamol", 18, now=t0 + 3600)
    assert not r["now_ok"] and r["next_ts"] == t0 + 6 * 3600 and r["dose_mg"] == 270 and "příbalovým letákem" in r["note"]
    for k in range(1, 4):
        healthx.fever_log(rt, "Ema", 38.5, "paracetamol", 250, ts=t0 + k * 6 * 3600)
    r = healthx.next_dose(rt, "Ema", "paracetamol", now=t0 + 19 * 3600)
    assert r["doses_24h"] == 4 and r["next_ts"] == t0 + 24 * 3600          # the 4th dose in a day: wait for the first to age out
    with pytest.raises(ValueError):
        healthx.fever_log(rt, "Ema", 50)
    with pytest.raises(ValueError):
        healthx.next_dose(rt, "Ema", "aspirin")


def test_coffee_water_pollen_crisis_ice_cycle(rt):
    ts = dt.datetime(2026, 11, 25, 16, 0).timestamp()
    r = healthx.coffee(rt, "espresso", ts)
    assert r["mg"] == 65 and "po 15:00" in r["warn"]
    for _ in range(6):
        healthx.coffee(rt, "káva", ts)
    assert "nad doporučených 400 mg" in healthx.coffee(rt, "káva", ts)["warn"]
    assert healthx.water_add(rt, dt.date(2026, 11, 25)) == 1 and healthx.water_add(rt, dt.date(2026, 11, 25), 2) == 3
    assert healthx.water_week(rt, dt.date(2026, 11, 25))[-1] == ("25. 11.", 3)
    t = healthx.pollen_alert({"birch_pollen": [10, 80, 30], "grass_pollen": [5, 6]}, ["bříza", "trávy"])
    assert t.startswith("Vysoký pyl: bříza 80 zrn/m³") and "trávy" not in t
    assert healthx.crisis_signal("už nechci žít") and not healthx.crisis_signal("nechci jít do práce")
    from jarvis import brainx

    assert healthx.CRISIS_RULE in brainx.prompt_lines(rt, "nemá to cenu žít") and "116 123" in healthx.CRISIS_RULE
    rt.cfg.healthx.blood_type, rt.cfg.healthx.allergies, rt.cfg.healthx.ice_contact = "A+", ["penicilin"], "Jana +420 777 000 111"
    assert healthx.ice_card(rt).startswith("Krevní skupina A+ · Alergie: penicilin") and "Jana" in healthx.ice_card(rt)
    bed = dt.datetime(2026, 11, 25, 23, 0)
    at = healthx.cycle_alarm(bed, dt.datetime(2026, 11, 26, 6, 30), dt.datetime(2026, 11, 26, 7, 0))
    assert at == dt.datetime(2026, 11, 26, 6, 45)                              # 23:15 + 5 × 90 min
    assert healthx.cycle_alarm(bed, dt.datetime(2026, 11, 26, 6, 50), dt.datetime(2026, 11, 26, 7, 0)) == dt.datetime(2026, 11, 26, 7, 0)
    assert healthx.detox_block("TikTok", dt.datetime(2026, 11, 25, 22, 30), ["tiktok"], "22:00")
    assert not healthx.detox_block("TikTok", dt.datetime(2026, 11, 25, 20, 0), ["tiktok"], "22:00")


async def test_health_tick_202020(rt):
    rt.platform.idle_seconds = lambda: 5
    s = healthx.state(rt)
    t = dt.datetime(2026, 11, 25, 14, 0)
    for k in range(25):
        said = await healthx.tick(rt, t + dt.timedelta(minutes=k))
    assert "202020" in said or s.work < 20 * 60


# ================================================================== Učení+
def test_music():
    assert learnx.note_for_freq(440) == {"note": "A", "octave": 4, "cents": 0, "in_tune": True}
    n = learnx.note_for_freq(445)
    assert n["note"] == "A" and n["cents"] == 20 and not n["in_tune"]
    assert learnx.note_for_freq(261.63)["note"] == "C" and learnx.freq_of("A", 4) == 440.0
    assert learnx.chord_notes("Am7") == ["A", "C", "E", "G"] and learnx.chord_notes("Bbmaj7") == ["A#", "D", "F", "A"]
    assert learnx.chord_notes("F#m") == ["F#", "A", "C#"]
    assert learnx.scale_notes("D", "dur") == ["D", "E", "F#", "G", "A", "H", "C#"]
    assert learnx.scale_notes("A", "moll") == ["A", "H", "C", "D", "E", "F", "G"]
    with pytest.raises(ValueError):
        learnx.chord_notes("Xm")
    wav = learnx.chord_wav(["C", "E", "G"], 0.2)
    assert wav[:4] == b"RIFF" and len(wav) > 8000


def test_words_rules_video():
    w = learnx.word_of_day("en", dt.date(2026, 11, 25))
    assert w["word"] and w["cs"] and w["example"]
    assert learnx.word_of_day("en", dt.date(2026, 11, 25)) == w and learnx.word_of_day("en", dt.date(2026, 11, 26)) != w
    assert "anglicky" in learnx.practice_rule("en") and "✎" in learnx.practice_rule("en")
    assert "NEPROZRAZUJ" in learnx.ask_rule("homework") and "NEPŘEPISUJ" in learnx.ask_rule("essay") and learnx.ask_rule("x") == ""
    vtt = ("WEBVTT\nKind: captions\n\n00:00:01.000 --> 00:00:03.000\nAhoj všichni\n\n00:00:03.000 --> 00:00:05.000\nAhoj všichni\n"
           "dnes vaříme\n\n00:01:10.500 --> 00:01:12.000\n<c>polévku</c> &amp; chleba\n")
    lines = learnx.parse_vtt(vtt)
    assert lines == [(1, "Ahoj všichni"), (3, "dnes vaříme"), (70, "polévku & chleba")]
    assert learnx.transcript_text(lines).startswith("[0:01] Ahoj všichni dnes vaříme [1:10] polévku")


def test_typing_rsvp_reading_syllables():
    s = learnx.typing_score("ahoj svete", "ahoj svete", 6)
    assert s["accuracy"] == 100.0 and s["wpm"] == 20.0
    assert learnx.typing_score("ahoj", "ahxj", 6)["accuracy"] < 100
    r = learnx.rsvp_words("Jedna dvě tři čtyři.", 300)
    assert r["words"] == ["Jedna", "dvě", "tři", "čtyři."] and r["ms"] == 200
    chk = learnx.reading_check("Pes běžel po louce za koloběžkou.", "pes běžel po louce za kolo")
    assert chk["hard"] == ["koloběžkou"] and chk["ok"] < 100
    assert learnx.syllables("koloběžka") == "ko-lo-běž-ka" and learnx.syllables("chobotnice") == "cho-bot-ni-ce"


def test_driving_cite_capitals_books_money(rt):
    q = learnx.driving_question(0)
    assert q["answer"] == "50 km/h"
    assert learnx.driving_check(0, "50 km/h")[0] and learnx.driving_check(0, "2")[0] and not learnx.driving_check(0, "1")[0]
    assert "etesty2.mdcr.cz" in learnx.driving_check(3, "žádný")[1]
    assert learnx.iso690("book", ["Karel Čapek"], "R.U.R.", "1920", "Aventinum", "Praha", isbn="978-80-000") == \
        "ČAPEK, Karel. R.U.R. Praha: Aventinum, 1920. ISBN 978-80-000."
    web = learnx.iso690("web", ["Jan Novák"], "Jak na sloh", "2025", "Učíme se", url="https://x.cz", accessed="2026-11-25")
    assert web.startswith("NOVÁK, Jan. Jak na sloh [online].") and "[cit. 2026-11-25]" in web
    country, cap = learnx.capital_question(0)
    assert learnx.capital_check(country, cap)[0] and learnx.capital_check("Slovinsko", "Lublan")[0]
    assert not learnx.capital_check("Austrálie", "Sydney")[0]
    learnx.book_add(rt, "Babička", "Božena Němcová")
    assert learnx.book_note(rt, "babička", "Krásný začátek", quote=True) and learnx.book_done(rt, "Babička", 5)
    b = learnx.book_find(rt, "babi")
    assert b["status"] == "přečteno" and json.loads(b["notes"])[0]["quote"]
    les = learnx.money_lesson(1)
    assert les["n"] == 2 and les["title"] == "Spoření"
    assert "<canvas" not in learnx.tuner_page() and "getUserMedia" in learnx.tuner_page() and "/api/learn/typing" in learnx.typing_page()


# ================================================================== Rodina+
def test_members_calendar_chores(rt):
    assert familyx.member_add(rt, "Ema", kid=True) == familyx.COLORS[0]
    familyx.member_add(rt, "Adam")
    assert familyx.owner_of("Emin kroužek", familyx.members(rt)) is not None or familyx.owner_of("Ema – kroužek", familyx.members(rt))
    familyx.schedule_add(rt, "Ema", 2, "15:30", "Plavání", "Adam")
    page = familyx.week_html(rt, dt.date(2026, 11, 23))
    assert "Plavání" in page and "veze Adam" in page and "středa" in page
    familyx.chore_add(rt, "Ema", "Uklidit pokoj", 10)
    assert familyx.chore_done(rt, "Ema", "pokoj")["points"] == 10
    with pytest.raises(ValueError):
        familyx.chore_done(rt, "Ema", "pokoj")
    assert familyx.weekday_of("Středa") == 2 and familyx.weekday_of("čtvrtek") == 3 and familyx.weekday_of("so") == 5
    with pytest.raises(ValueError):
        familyx.weekday_of("xyz")


def test_menu_recipe_fridge():
    p = familyx.menu_prompt(3, "těstoviny", "houby", ["vejce"])
    assert "3 lidi" in p and "houby" in p and "vejce" in p and "JSON" in p
    m = familyx.parse_menu('Tady: {"days": [{"day": "pondělí", "lunch": "Guláš", "dinner": "Chléb"}], "shopping": ["maso 500 g"]}')
    assert m["days"][0]["lunch"] == "Guláš" and m["shopping"] == ["maso 500 g"]
    with pytest.raises(ValueError):
        familyx.parse_menu("nic")
    steps = familyx.recipe_steps("Postup:\n1. Nakrájej cibuli.\n2. Osmaž ji 5 minut.\n3. Vař 20–25 minut.\n4. Podávej.")
    assert [s["timer"] for s in steps] == [0, 300, 1500, 0]
    r = familyx.Recipe(steps)
    assert r.next()["n"] == 1 and r.next()["timer"] == 300 and r.repeat()["n"] == 2 and r.back()["n"] == 1


def test_fridge_plants_care_waste(rt):
    today = dt.date(2026, 11, 25)
    familyx.fridge_add(rt, "Jogurt", "2026-11-26")
    familyx.fridge_add(rt, "Šunka", "2026-11-20")
    f = familyx.fridge(rt, today)
    assert f["soon"] == ["Jogurt"] and f["expired"] == ["Šunka"] and familyx.fridge_remove(rt, "šunk")
    assert familyx.plant_add(rt, "Monstera v obýváku", "monstera", last="2026-11-17") == 7
    assert familyx.plant_add(rt, "Kaktus", "", last="2026-11-20") == 21
    assert familyx.plants_due(rt, today) == ["Monstera v obýváku"]
    assert familyx.plant_watered(rt, "monstera", today) and familyx.plants_due(rt, today) == []
    cid = familyx.care_add(rt, "Rex", "pet", "Očkování", 365, "2025-11-20")
    familyx.care_add(rt, "Rex", "pet", "Krmení", 1, at="18:00")
    due = familyx.care_due(rt, today, "18:00")
    assert any("Očkování" in d["text"] and "po termínu" in d["text"] for d in due) and any("Krmení" in d["text"] for d in due)
    assert familyx.care_done(rt, cid, today) and not any("Očkování" in d["text"] for d in familyx.care_due(rt, today))
    assert familyx.house_defaults(rt) == len(familyx.HOUSE_TASKS) and familyx.house_defaults(rt) == 0
    familyx.waste_set(rt, "papir", 3, every_weeks=2, parity=dt.date(2026, 11, 26).isocalendar()[1] % 2)
    familyx.waste_set(rt, "smesny", 3)
    assert familyx.waste_tomorrow(rt, today) == ["Papír (modrá)", "Směsný odpad (černá)"]
    assert familyx.waste_tomorrow(rt, today + dt.timedelta(days=7)) == ["Směsný odpad (černá)"]


def test_pickups_rules_cleaning_wifi_cards(rt):
    familyx.schedule_add(rt, "Ema", 2, "16:00", "Flétna", "Jana")
    out = familyx.pickups(rt, dt.datetime(2026, 11, 25, 15, 40))
    assert out and out[0]["driver"] == "Jana" and familyx.pickups(rt, dt.datetime(2026, 11, 25, 15, 45)) == []
    rules = {"school_from": "15:00", "bed": "20:30", "daily_min": 90}
    assert "nic nenahrává" in familyx.kid_rules_text(rules)
    assert familyx.kid_allowed(rules, dt.datetime(2026, 11, 25, 14, 0), 0) == (False, "Ve všední dny až od 15:00.")
    assert familyx.kid_allowed(rules, dt.datetime(2026, 11, 25, 21, 0), 0)[0] is False
    assert familyx.kid_allowed(rules, dt.datetime(2026, 11, 25, 16, 0), 95)[0] is False
    assert familyx.kid_allowed(rules, dt.datetime(2026, 11, 28, 10, 0), 30) == (True, "")
    plan = familyx.chores_rotation(["Adam", "Jana"], ["koupelna", "kuchyň", "vysávání"], 1)
    plan2 = familyx.chores_rotation(["Adam", "Jana"], ["koupelna", "kuchyň", "vysávání"], 2)
    assert plan != plan2 and sorted(sum(plan.values(), [])) == ["koupelna", "kuchyň", "vysávání"]
    assert familyx.wifi_qr_text("Doma;5G", "tajne:heslo") == r"WIFI:T:WPA;S:Doma\;5G;P:tajne\:heslo;;"
    assert familyx.wifi_qr_text("Host", "") == "WIFI:T:nopass;S:Host;;"
    card = familyx.babysitter_html([{"name": "Ema", "age": 6, "allergies": "ořechy"}], ["Adam 777"], ["Spát v 19:30"], ["st 16:00 flétna"])
    assert "ořechy" in card and "155" in card
    kron = familyx.chronicle_html("Novákovi", {2025: [{"date": "2025-06-01", "text": "výlet <Šumava>"}]})
    assert "&lt;Šumava&gt;" in kron and "2025" in kron
    assert "Nepoužívej postavy ze známých" in familyx.story_prompt("Ema", 6, "o drakovi")


# ================================================================== tools, routes, hooks
async def test_x7_tools_and_pages(rt):
    for n in ("health_kit", "learn_kit", "family_kit"):
        assert n in tools.REGISTRY
    r = await tools.call("learn_kit", {"action": "chord", "text": "G7"}, rt)
    assert r.ok and r.summary == "G7: G – H – D – F" and r.attachments
    r = await tools.call("health_kit", {"action": "next_dose", "person": "Ema", "text": "ibuprofen", "weight": 20}, rt)
    assert r.ok and "200 mg" in r.summary
    r = await tools.call("family_kit", {"action": "cleaning", "text": "Adam, Jana"}, rt)
    assert r.ok and "Adam:" in r.summary
    r = await tools.call("learn_kit", {"action": "practice", "text": "en"}, rt)
    from jarvis import brainx

    assert r.ok and any("Konverzační trénink" in x for x in brainx.prompt_lines(rt, "hello"))
    await tools.call("learn_kit", {"action": "practice", "text": "stop"}, rt)
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    c = TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000))
    assert "Ladička" in c.get("/learn/tuner").text and "Psaní všemi deseti" in c.get("/learn/typing").text
    assert c.post("/api/learn/typing", json={"wpm": 42, "accuracy": 97}).json()["ok"]
    assert "Rodinný kalendář" in c.get("/family-calendar").text


async def test_water_done_fills_the_glass(rt):
    ok, _ = await rt.notice_action("water_done", {})
    assert ok and healthx.db(rt).one("SELECT n FROM hl_water WHERE day=?", (dt.date.today().isoformat(),))["n"] == 1
