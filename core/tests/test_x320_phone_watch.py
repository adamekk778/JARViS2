"""3.20 Telefon + Hodinky (nápady 121–160)."""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from pathlib import Path

import pytest

from jarvis import phonex, tools


def _watch_on(rt):
    w = phonex.watch(rt)
    w.last_poll = time.time()
    return w


# ------------------------------------------------------------------ (141) vibrační kódy
def test_vibe_codes_and_notice_to_wrist(rt):
    assert phonex.vibe_for("⏲ Čaj", "čas vypršel", urgent=True) == "urgent"
    assert phonex.vibe_for("Časovač", "minutka doběhla", urgent=True) == "timer"
    assert phonex.vibe_for("Kalendář", "Schůzka za 10 min") == "meeting"
    assert phonex.vibe_for("Pitný režim", "je čas na sklenici vody") == "sit"
    assert phonex.vibe_for("WhatsApp", "Petr: ahoj") == "message"
    w = _watch_on(rt)
    assert phonex.on_notice(rt, "Pošta", "nový e-mail") is False          # at the PC and not urgent → not to the wrist
    assert phonex.on_notice(rt, "Budík", "vstávej", urgent=True) is True
    ev = w.queue[-1]
    assert ev["pattern"] == phonex.VIBES["urgent"] and "Budík" in ev["text"]
    rt.cfg.mobx.watch_vibes = False
    assert phonex.on_notice(rt, "Budík", "vstávej", urgent=True) is False
    rt.cfg.mobx.watch_vibes = True
    w.last_poll = 0
    assert phonex.on_notice(rt, "Budík", "vstávej", urgent=True) is False   # the watch is not connected


async def test_watch_long_poll_gets_events(rt):
    w = phonex.watch(rt)
    task = asyncio.create_task(w.poll(5))
    await asyncio.sleep(0.05)
    w.push("find", "Tady jsem!", "find")
    events = await asyncio.wait_for(task, 2)
    assert events[0]["kind"] == "find" and events[0]["pattern"] == phonex.VIBES["find"] and w.alive()


# ------------------------------------------------------------------ (127) zapomenutý telefon
def test_forgotten_phone(rt):
    assert phonex.net_of("192.168.1.20") == "home" and phonex.net_of("100.101.2.3") == "away"
    assert phonex.net_of("85.10.1.1") == "away" and phonex.net_of("127.0.0.1") == "home" and phonex.net_of("x") == "unknown"
    _watch_on(rt)
    now = time.time()
    phonex.seen(rt, "phone", "192.168.1.40", now)
    phonex.seen(rt, "watch", "85.10.1.1", now)
    assert "Telefon zůstal doma" in phonex.forgotten_check(rt, now)
    assert phonex.watch(rt).queue[-1]["pattern"] == phonex.VIBES["phone"]
    assert phonex.forgotten_check(rt, now + 60) == ""                    # once per two hours
    phonex.seen(rt, "phone", "85.10.1.2", now + 3 * 3600)
    phonex.seen(rt, "watch", "85.10.1.1", now + 3 * 3600)
    assert phonex.forgotten_check(rt, now + 3 * 3600) == ""              # both outside → you have it


# ------------------------------------------------------------------ (134) roaming, (128) data
def test_roaming_and_data(rt):
    assert "Roaming jako doma (EU)" in phonex.roaming_text("de")
    t = phonex.roaming_text("us")
    assert "mimo EU" in t and "911" in t and "adaptér" in t and "$" in t
    assert phonex.roaming_text("cz") == ""
    assert phonex.on_country(rt, "cz") == ""                              # the first look at home says nothing
    assert "Chorvatsko" in phonex.on_country(rt, "hr")
    assert phonex.on_country(rt, "hr") == ""                              # once per country change
    assert "zpátky doma" in phonex.on_country(rt, "cz")
    rt.cfg.mobx.data_limit_gb = 10
    day = dt.date(2026, 11, 25)
    assert phonex.on_data(rt, 5000, day) == ""
    assert "80 %" not in phonex.on_data(rt, 8500, day) and "Zbývá" in phonex.on_data(rt, 8600, dt.date(2026, 12, 1))
    assert phonex.on_data(rt, 8700, dt.date(2026, 12, 2)) == ""          # 80 % said once this month
    assert "Wi-Fi" in phonex.on_data(rt, 10300, dt.date(2026, 12, 20))
    assert phonex.on_data(rt, 10400, dt.date(2026, 12, 21)) == ""


# ------------------------------------------------------------------ (137) 80 %
async def test_charge_limit(rt):
    assert await phonex.on_battery(rt, 60, True) == ""
    t = await phonex.on_battery(rt, 81, True)
    assert "81 %" in t and "Odpoj" in t
    assert await phonex.on_battery(rt, 85, True) == ""                    # once per charge
    await phonex.on_battery(rt, 84, False)
    assert await phonex.on_battery(rt, 80, True) != ""                    # a new charge, a new reminder


# ------------------------------------------------------------------ (121) NFC
async def test_nfc_tags(rt):
    from conftest import FakeRouter

    r = phonex.nfc_bind(rt, "Kuchyň", "zhasni v kuchyni")
    assert r["tag"] == "kuchyn" and r["uri"] == "jarvis://tag/kuchyn"
    assert phonex.nfc_list(rt)[0]["command"] == "zhasni v kuchyni"
    with pytest.raises(ValueError):
        phonex.nfc_bind(rt, "!!!", "x")
    assert "zatím nic nedělá" in await phonex.on_nfc(rt, "auto")
    assert await phonex.on_nfc(rt, "../etc") == "Neznámý štítek."
    rt.router = FakeRouter(["Zhasnuto."])
    assert await phonex.on_nfc(rt, "kuchyn") == "Zhasnuto."
    assert "zhasni v kuchyni" in rt.router.calls[0]["messages"][-1]["content"]
    assert phonex.nfc_remove(rt, "kuchyn") and not phonex.nfc_list(rt)


# ------------------------------------------------------------------ (122, 133, 142, 155) PC z telefonu a hodinek
async def test_pc_actions(rt):
    rt.platform.volume = 50
    assert await phonex.pc_action(rt, "mute") == (True, "Ztlumeno.")
    assert await phonex.pc_action(rt, "vol_up") == (True, "Hlasitost 60 %.")
    assert (await phonex.pc_action(rt, "lock"))[0] and ("power", "lock") in rt.platform.calls
    assert (await phonex.pc_action(rt, "next_slide"))[0] and ("hotkey", ("right",)) in rt.platform.calls
    assert (await phonex.pc_action(rt, "play_pause"))[0] and ("media_key", "play_pause") in rt.platform.calls
    assert await phonex.pc_action(rt, "format_disk") == (False, "Neznámá akce.")
    assert (await phonex.pc_action(rt, "open_payment")) == (False, "Žádná platba nečeká.")


# ------------------------------------------------------------------ (123) auto
def test_driving_mode(rt):
    from jarvis import brainx

    assert phonex.is_car(rt, "Škoda Octavia") and phonex.is_car(rt, "MY CAR") and not phonex.is_car(rt, "AirPods Pro")
    assert phonex.on_bt(rt, "AirPods Pro", True) is None
    assert phonex.on_bt(rt, "Skoda Kodiaq", True) is True and rt.driving
    assert phonex.DRIVE_RULE in brainx.prompt_lines(rt, "co je nového")
    assert phonex.on_bt(rt, "Skoda Kodiaq", False) is False
    assert phonex.DRIVE_RULE not in brainx.prompt_lines(rt, "co je nového")
    rt.cfg.mobx.car_names = ["Octavka"]
    assert phonex.is_car(rt, "Octavka 2") and not phonex.is_car(rt, "Skoda Kodiaq")


# ------------------------------------------------------------------ (130) tichá hodina, (132) zamčená obrazovka
def test_quiet_hours_and_lock_status(rt):
    rt.cfg.mobx.quiet_sleep = "23:00-07:00"
    assert phonex._window("23:00-07:00", dt.datetime(2026, 11, 25, 23, 30))
    assert phonex._window("23:00-07:00", dt.datetime(2026, 11, 26, 6, 59))
    assert not phonex._window("23:00-07:00", dt.datetime(2026, 11, 26, 7, 0))
    assert phonex._window("13:00-14:00", dt.datetime(2026, 11, 26, 13, 30))
    assert phonex.dnd_tick(rt, dt.datetime(2026, 11, 25, 12, 0)) is None     # nothing to turn off at the start
    assert phonex.dnd_tick(rt, dt.datetime(2026, 11, 25, 23, 5)) == "spánek"
    assert phonex.dnd_tick(rt, dt.datetime(2026, 11, 25, 23, 30)) is None    # no change
    assert phonex.dnd_tick(rt, dt.datetime(2026, 11, 26, 7, 1)) == "off"
    assert phonex.status_line(rt) == "JARVIS je připravený"
    assert phonex.lock_tick(rt) is None                                     # off unless you switch it on
    rt.cfg.mobx.lock_status = True
    assert phonex.lock_tick(rt) == "JARVIS je připravený" and phonex.lock_tick(rt) is None


# ------------------------------------------------------------------ (138) dovolená
def test_vacation(rt):
    assert "Dovolená do 2027-01-05" in phonex.vacation(rt, True, "2027-01-05")
    assert phonex.vacation_on(rt, dt.date(2027, 1, 5)) and not phonex.vacation_on(rt, dt.date(2027, 1, 6))
    assert phonex.status_line(rt).startswith("Dovolená") or not phonex.vacation_on(rt)
    assert "skončila" in phonex.vacation(rt, False) and not phonex.vacation_on(rt)


# ------------------------------------------------------------------ (139) poloha na čas
def test_location_share(rt):
    r = phonex.share_start(rt, 30, "Adam")
    tok, now = r["token"], time.time()
    assert len(tok) >= 20 and r["minutes"] == 30 and r["url"].endswith(tok)
    assert "nedorazila" in phonex.share_page(rt, tok, now)
    assert phonex.share_update(rt, tok, 50.08, 14.42, 12, now)
    page = phonex.share_page(rt, tok, now + 60)
    assert "50.08000, 14.42000" in page and "±12 m" in page and "openstreetmap.org" in page
    assert not phonex.share_update(rt, tok, 95, 14, None, now)                # nonsense position
    assert phonex.share_page(rt, tok, now + 31 * 60) is None                  # it expired
    assert not phonex.share_update(rt, "nope", 50, 14)
    r2 = phonex.share_start(rt, 10, "<script>")
    assert "<script>" not in phonex.share_page(rt, r2["token"]) and phonex.share_stop(rt) == 2
    assert phonex.share_page(rt, r2["token"]) is None


# ------------------------------------------------------------------ (140) poznámka po hovoru
async def test_call_note(rt):
    phonex.save_call_note(rt, "Petr", "domluvit sraz v pátek")
    assert phonex.call_notes(rt, "petr")[0]["text"] == "domluvit sraz v pátek"
    ok, msg = await rt.notice_action("call_note", {"who": "Jana", "text": "poslat fakturu"})
    assert ok and "uložil" in msg and phonex.call_notes(rt, "jana")
    ok, _ = await rt.notice_action("call_note", {"who": "Jana", "text": " "})
    assert not ok


# ------------------------------------------------------------------ (135) sken do PDF
def test_scan_pdf(tmp_path: Path):
    from PIL import Image

    pages = []
    for i, color in enumerate(((240, 240, 230), (200, 210, 220))):
        p = tmp_path / f"p{i}.jpg"
        Image.new("RGB", (600, 800), color).save(p)
        pages.append(p)
    out = phonex.scan_pdf(pages, tmp_path / "out" / "sken.pdf")
    data = out.read_bytes()
    assert data.startswith(b"%PDF") and data.count(b"/Type /Page\n") + data.count(b"/Type /Page\r") + data.count(b"/Type /Page ") >= 1
    assert phonex.scan_pdf(pages[:1], tmp_path / "bw.pdf", "bw").exists()
    with pytest.raises(ValueError):
        phonex.scan_pdf([], tmp_path / "x.pdf")


# ------------------------------------------------------------------ (136) webkamera
def test_cam_feed(rt):
    f = phonex.camfeed(rt)
    with pytest.raises(ValueError):
        f.put(b"not a jpeg")
    f.put(b"\xff\xd8\xff\xe0jpegdata")
    assert f.fresh() and phonex.camfeed(rt) is f


# ------------------------------------------------------------------ (143, 152) tep
def test_heart_rate_gaming_and_stress(rt):
    now = time.time()
    rt.game_active = True
    outs = [phonex.add_hr(rt, 140, ts=now - (14 - k) * 60) for k in range(15)]
    assert all(o["ctx"] == "game" for o in outs) and sum(1 for o in outs if o.get("warned")) == 1   # once per half hour
    rt.game_active = False
    with pytest.raises(ValueError):
        phonex.add_hr(rt, 400)
    day = dt.date.today()
    base = dt.datetime.combine(day, dt.time(3)).timestamp()
    for k in range(20):
        phonex.add_hr(rt, 58, ts=base - 86400 + k * 60)
    for k in range(10):
        phonex.add_hr(rt, 85, ts=base + 7 * 3600 + k * 60)
    s = phonex.stress(rt, day)
    assert s["resting"] == 58 and any(h["hour"] == 10 and h["level"] and h["level"] > 50 for h in s["hours"])
    assert "není to lékařské" in s["note"]


# ------------------------------------------------------------------ (153) BLE pás
def test_ble_heart_rate_parser():
    assert phonex.parse_hr_measurement(bytes([0x00, 72])) == (72, [])
    assert phonex.parse_hr_measurement(bytes([0x01, 0x2C, 0x01])) == (300, [])         # 16-bit
    bpm, rr = phonex.parse_hr_measurement(bytes([0x10, 60, 0x00, 0x04, 0x00, 0x04]))    # RR 1024/1024 s = 1000 ms
    assert bpm == 60 and rr == [1000, 1000]
    assert phonex.parse_hr_measurement(bytes([0x18, 70, 0x10, 0x00, 0x00, 0x02]))[1] == [500]   # energy skipped


# ------------------------------------------------------------------ (144) jméno
def test_name_mentions(rt):
    rt.cfg.general.user_name = "Adam Novák"
    rt.cfg.mobx.my_names = ["Áďo"]
    assert phonex.mentions_name(rt, "Adame, přijdeš?") and phonex.mentions_name(rt, "zeptej se ado")
    assert not phonex.mentions_name(rt, "Adamantium je kov")              # only the name with a Czech ending
    assert not phonex.mentions_name(rt, "Petr přijde")
    _watch_on(rt)
    assert phonex.on_message(rt, {"messaging": True, "title": "Rodina", "app": "WhatsApp", "text": "Adame, kde jsi?"})
    assert phonex.watch(rt).queue[-1]["pattern"] == phonex.VIBES["name"]
    assert not phonex.on_message(rt, {"messaging": False, "text": "Adame"})


# ------------------------------------------------------------------ (145) minutka, (154) tichý budík, (157) najdi
async def test_timer_alarm_find(rt):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    w = _watch_on(rt)
    r = await tools.call("set_timer", {"seconds": 300, "label": "Čaj"}, rt)
    assert r.ok and w.queue[-1]["kind"] == "timer" and w.queue[-1]["label"] == "Čaj"
    job = phonex.schedule_silent_alarm(rt, "6:30", dt.datetime(2026, 11, 25, 22, 0))
    assert job["kind"] == "watch_alarm" and "6:30" in job["title"].replace("06:30", "6:30")
    assert phonex.run_watch_alarm(rt) == "watch" and w.queue[-1]["kind"] == "alarm" and w.queue[-1]["repeat"]
    w.last_poll = 0
    assert phonex.run_watch_alarm(rt) == "phone"
    assert phonex.find_watch(rt)[0] is False
    w.last_poll = time.time()
    assert phonex.find_watch(rt)[0] and w.queue[-1]["kind"] == "find"


# ------------------------------------------------------------------ (147) tempo, (149) navigace
def test_pace_and_route_parse():
    assert phonex.parse_pace("5:30") == 330 and phonex.parse_pace("5.5") == 330 and phonex.parse_pace("6 min/km") == 360
    with pytest.raises(ValueError):
        phonex.parse_pace("rychle")
    assert phonex.pace_feedback(330, 360) == "slow" and phonex.pace_feedback(330, 300) == "fast"
    assert phonex.pace_feedback(330, 335) == "ok" and phonex.pace_feedback(0, 300) == "ok"
    data = {"routes": [{"distance": 1200, "duration": 900, "legs": [{"steps": [
        {"maneuver": {"type": "depart", "location": [14.42, 50.08]}, "name": "Národní", "distance": 300},
        {"maneuver": {"type": "turn", "modifier": "left", "location": [14.421, 50.081]}, "name": "Spálená", "distance": 400},
        {"maneuver": {"type": "continue", "modifier": "straight", "location": [14.422, 50.082]}, "name": "Spálená", "distance": 100},
        {"maneuver": {"type": "turn", "modifier": "slight right", "location": [14.423, 50.083]}, "name": "Žitná", "distance": 400},
        {"maneuver": {"type": "arrive", "location": [14.424, 50.084]}, "name": "", "distance": 0}]}]}]}
    steps = phonex.parse_osrm(data)
    assert [s["turn"] for s in steps] == ["start", "left", "right", "arrive"]
    assert steps[1] == {"lat": 50.081, "lon": 14.421, "turn": "left", "street": "Spálená", "dist": 400}


# ------------------------------------------------------------------ (150) pád
async def test_fall_starts_emergency(rt):
    r = await phonex.on_fall(rt, 50.08, 14.42)
    assert r["ok"] and "Nouzový protokol" in r["message"]
    from jarvis import safety

    em = safety.emergency(rt)
    assert "pád" in em.last["reason"] and "openstreetmap" in em.last["where"]
    em.cancel()
    await asyncio.sleep(0)


# ------------------------------------------------------------------ (151) komplikace, (160) tréninky, (156) pití
def test_complication_workouts_water(rt):
    assert phonex.complication(rt) == {"short": "OK", "title": "JARVIS"}
    w = phonex.add_workout(rt, "run", 30, 5)
    assert w["text"] == "Běh 30 min, 5.00 km, tempo 6:00/km"
    with pytest.raises(ValueError):
        phonex.add_workout(rt, "run", 0.5)
    phonex.add_workout(rt, "gym", 45, start=time.time() - 2 * 86400)
    assert phonex.week_summary(rt).startswith("Za 7 dní 2 tréninků") and "běh 1×" in phonex.week_summary(rt)
    assert phonex.activity_factor(rt) == 0.6
    from jarvis.proactx import water_minutes

    assert water_minutes(rt, 90) == 54


# ------------------------------------------------------------------ the tools
async def test_tools(rt):
    for name in ("phone_kit", "watch_kit"):
        assert name in tools.REGISTRY
    r = await tools.call("phone_kit", {"action": "nfc_bind", "name": "auto", "text": "naviguj domů"}, rt)
    assert r.ok and "jarvis://tag/auto" in r.summary
    r = await tools.call("phone_kit", {"action": "roaming", "text": "gb"}, rt)
    assert r.ok and "mimo EU" in r.summary
    r = await tools.call("watch_kit", {"action": "legend"}, rt)
    assert "ťuk-ťuk" in r.summary
    r = await tools.call("watch_kit", {"action": "workout_add", "kind": "walk", "minutes": 40, "km": 3.2}, rt)
    assert r.ok and "Chůze 40 min" in r.summary
    r = await tools.call("phone_kit", {"action": "status"}, rt)
    assert r.ok and "NFC štítků: 1" in r.summary


# ------------------------------------------------------------------ HTTP: the watch and the phone
async def test_http_routes(rt):
    from fastapi.testclient import TestClient

    from jarvis import watchpair
    from jarvis.server.app import create_app

    app = create_app(rt, manage_runtime=False)
    away = TestClient(app, client=("192.168.1.30", 5000))
    assert away.get("/api/watch/events?wait=0").status_code == 401
    code = watchpair.start(rt)["code"]
    tok = away.post("/api/watch/pair", json={"code": code}).json()["token"]
    auth = {"Authorization": f"Bearer {tok}"}
    phonex.watch(rt).push("notice", "Ahoj", "message")
    ev = away.get("/api/watch/events?wait=0", headers=auth).json()["events"]
    assert ev and ev[0]["text"] == "Ahoj"
    st = away.get("/api/watch/status", headers=auth).json()
    assert st["complication"]["short"] == "OK"
    rt.platform.volume = 30
    assert away.post("/api/watch/action", json={"action": "vol_down"}, headers=auth).json()["message"] == "Hlasitost 20 %."
    assert away.post("/api/watch/hr", json={"samples": [{"bpm": 70}, {"bpm": 999}]}, headers=auth).json()["saved"] == 1
    assert away.post("/api/watch/workout", json={"kind": "run", "minutes": 20, "km": 4}, headers=auth).json()["ok"]
    sh = phonex.share_start(rt, 15)
    assert away.post("/api/phone/loc", json={"token": sh["token"], "lat": 50.1, "lon": 14.4}, headers=auth).json()["ok"]
    page = TestClient(app, client=("85.1.2.3", 5000)).get(f"/share/loc/{sh['token']}")     # the page itself needs no login
    assert page.status_code == 200 and "50.10000" in page.text and page.headers["x-robots-tag"] == "noindex"
    assert TestClient(app, client=("85.1.2.3", 5000)).get("/share/loc/nothing").status_code == 404
    assert away.post("/api/phone/cam", content=b"\xff\xd8jpg", headers=auth).json()["ok"]
    assert away.post("/api/phone/cam", content=b"png", headers=auth).status_code == 400
    r = away.post("/api/phone/event", json={"kind": "nfc", "tag": "neni"}, headers=auth).json()
    assert "zatím nic nedělá" in r["message"]
    away.post("/api/phone/event", json={"kind": "headphones", "on": True, "name": "Skoda Octavia"}, headers=auth)
    assert rt.driving
    away.get("/api/phone/poll?wait=0&battery=50&charging=0&country=at", headers=auth)
    assert phonex._kv(rt, "phx_country") == "at"


# ------------------------------------------------------------------ the phone and watch apps carry the pieces
def test_native_pieces_are_registered():
    root = Path(__file__).resolve().parents[2] / "mobile"
    native = root / "native"
    for f in ("PhoneX.java", "PcControlReceiver.java", "MuteTile.java", "LockTile.java", "NfcActivity.java", "LocShareService.java"):
        assert (native / f).exists(), f
    patch = (root / "patch-android.mjs").read_text(encoding="utf-8")
    for piece in (".MuteTile", ".LockTile", ".PcControlReceiver", ".NfcActivity", ".LocShareService", "NDEF_DISCOVERED",
                  'android:scheme="jarvis" android:host="tag"', "android.intent.action.ASSIST", "ACCESS_NOTIFICATION_POLICY",
                  "FOREGROUND_SERVICE_LOCATION"):
        assert piece in patch, piece
    link = (native / "JarvisLink.java").read_text(encoding="utf-8")
    for case in ('case "dnd"', 'case "lock_status"', 'case "loc_share"', 'case "voice_share"', "PhoneX.extraQuery(c)"):
        assert case in link, case
    wear = root / "wear" / "app" / "src" / "main"
    man = (wear / "AndroidManifest.xml").read_text(encoding="utf-8")
    for piece in (".WatchService", ".StatusComplication", "SHORT_TEXT", ".AlertActivity", "BODY_SENSORS", "android.intent.action.ASSIST"):
        assert piece in man, piece
    gradle = (root / "wear" / "app" / "build.gradle").read_text(encoding="utf-8")
    assert "watchface-complications-data-source" in gradle


def test_pace_rule_same_on_the_watch():
    """Buzz.pace() on the watch and phonex.pace_feedback() on the PC use the same 5 % band (kept in sync by hand)."""
    buzz = (Path(__file__).resolve().parents[2] / "mobile/wear/app/src/main/java/cz/adamekk/jarvis/wear/Buzz.java").read_text(encoding="utf-8")
    assert "targetSecKm * 1.05" in buzz and "targetSecKm * 0.95" in buzz
    assert phonex.pace_feedback(300, 316) == "slow" and phonex.pace_feedback(300, 314) == "ok"
    for name in ("slow", "fast", "left", "right", "arrive"):
        assert name in phonex.VIBES
    assert "{0, 150, 150, 150}" in buzz and "{0, 150, 150, 150, 150, 150}" in buzz           # left / right as on the PC
