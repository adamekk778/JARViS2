"""3.13 round 3: the game coach (what you play, tips in the notch, playing time, results, the graphics card back to
the game), "dej mi vědět, až najde zápas", the morning company card, buttons of notices from the phone, the try-out."""
import asyncio
import time

from conftest import FakeRouter, drain
from fastapi.testclient import TestClient

from jarvis import gamecoach, tools
from jarvis.gamecoach import GameCoach, describe_stats, name_for
from jarvis.server.app import create_app

REMOTE = ("192.168.1.50", 5000)
VALO = {"exe": "VALORANT-Win64-Shipping.exe", "title": "VALORANT  "}


def test_the_game_is_recognised_by_its_program():
    assert name_for(VALO) == "Valorant"
    assert name_for({"exe": "cs2.exe", "title": "Counter-Strike 2"}) == "Counter-Strike 2"
    assert name_for({"exe": "javaw.exe", "title": "Minecraft 1.21.4"}) == "Minecraft"
    assert name_for({"exe": "SomeIndie.exe", "title": "Hollow Knight - Steam"}) == "Hollow Knight"


def test_a_session_starts_tips_come_and_the_time_is_kept(rt, monkeypatch):
    coach = GameCoach(rt)
    unloaded = []

    class Local:
        async def unload(self):
            unloaded.append(1)
    rt.local = Local()
    q = rt.bus.subscribe()
    hooked = []
    rt.on_game_tip = lambda: hooked.append(1)
    t0 = 1_000_000.0
    coach.tick(VALO, True, now=t0)
    ev = drain(q)
    assert coach.game == "Valorant" and any(e["type"] == "game_state" and e["on"] for e in ev)
    coach.tick(VALO, True, now=t0 + 60)                       # the first tip a minute and a half in, not at once
    assert not [e for e in drain(q) if e["type"] == "game_tip"]
    coach.tick(VALO, True, now=t0 + 100)
    tips = [e for e in drain(q) if e["type"] == "game_tip"]
    assert tips and tips[0]["game"] == "Valorant" and tips[0]["tip"] in gamecoach.TIPS["Valorant"] and hooked
    coach.tick(VALO, True, now=t0 + 160)                      # not again so soon
    assert not [e for e in drain(q) if e["type"] == "game_tip"]
    coach.tick(None, False, now=t0 + 30 * 60)                 # gone for a while: the session is over
    assert coach.game == "" and any(e["type"] == "game_state" and not e["on"] for e in drain(q))
    s = coach.stats(7, now=t0 + 31 * 60)
    assert s["games"][0]["game"] == "Valorant" and s["games"][0]["minutes"] == 3 and s["games"][0]["sessions"] == 1


def test_a_short_alt_tab_is_not_the_end_of_the_game(rt):
    coach = GameCoach(rt)
    coach.tick(VALO, True, now=100.0)
    coach.tick(None, False, now=130.0)
    assert coach.game == "Valorant"
    coach.tick(VALO, True, now=140.0)
    assert coach.game == "Valorant" and coach.since == 100.0


def test_results_and_stats_in_words(rt):
    coach = GameCoach(rt)
    coach.tick(VALO, True, now=time.time() - 1800)
    coach.log_result("výhra", "13:7")
    coach.log_result("prohra", "9:13")
    s = coach.stats(7)
    v = next(g for g in s["games"] if g["game"] == "Valorant")
    assert (v["wins"], v["losses"]) == (1, 1) and "Valorant" in describe_stats(s) and "1 výher / 1 proher" in describe_stats(s)
    try:
        coach.log_result("možná")
        raise AssertionError("bad result accepted")
    except ValueError:
        pass


def test_tips_for_an_unknown_game_are_written_by_the_ai_once(rt, monkeypatch, tmp_path):
    coach = GameCoach(rt)
    monkeypatch.setattr(coach, "_cache_file", lambda: tmp_path / "game_tips.json")
    rt.router = FakeRouter(['["Tip jedna", "Tip dva"]'])

    async def run():
        coach._ask_ai("Hollow Knight")
        await asyncio.sleep(0.05)
    asyncio.run(run())
    assert coach.tips_for("Hollow Knight") == ["Tip jedna", "Tip dva"]
    fresh = GameCoach(rt)
    monkeypatch.setattr(fresh, "_cache_file", lambda: tmp_path / "game_tips.json")
    assert fresh.tips_for("Hollow Knight") == ["Tip jedna", "Tip dva"]     # cached, no second question


def test_tips_can_be_switched_off(rt):
    rt.cfg.games.tips = False
    coach = GameCoach(rt)
    q = rt.bus.subscribe()
    coach.tick(VALO, True, now=0.0)
    coach.tick(VALO, True, now=3600.0)
    assert not [e for e in drain(q) if e["type"] == "game_tip"]


async def test_tools_tip_result_and_stats(rt):
    rt.gamecoach.tick(VALO, True, now=time.time() - 600)
    q = rt.bus.subscribe()
    r = await tools.call("game_tip", {}, rt)
    assert r.ok and any(e["type"] == "game_tip" for e in drain(q))
    r = await tools.call("game_result", {"result": "výhra", "score": "13:5"}, rt)
    assert r.ok and "Výhra v Valorant 13:5" in r.summary
    r = await tools.call("game_stats", {"days": 7}, rt)
    assert r.ok and "Valorant" in r.summary


async def test_screen_watch_tells_when_it_is_there(rt):
    rt.router = FakeRouter(["ne", "ano, výběr agenta je vidět"])
    pushed = []
    rt.phone_push = lambda kind, **d: pushed.append(d) or True
    from jarvis.tools import game_tools

    game_tools.WATCH_EVERY_S = 0.01
    q = rt.bus.subscribe()
    r = await tools.call("screen_wait_for", {"what": "nalezený zápas", "minutes": 1}, rt)
    assert r.ok
    for _ in range(50):
        await asyncio.sleep(0.02)
        if pushed:
            break
    ev = [e for e in drain(q) if e["type"] == "notify"]
    assert pushed and ev and ev[-1]["title"] == "Je to tady"


def test_the_morning_company_card_once_a_day(rt, monkeypatch):
    from jarvis import bizcompany

    monkeypatch.setattr(bizcompany, "_agents", lambda rt_: [{"name": "E-mailový asistent"}])
    monkeypatch.setattr(bizcompany, "brief", lambda rt_: "Nic nečeká na schválení. Dnes agenti pracovali 3×. Cíl tržby 40 %.")
    import datetime as dt

    eight = dt.datetime(2026, 11, 20, 8, 5).timestamp()
    assert bizcompany.morning_card(rt, now=eight, idle=500) is None          # not at the PC
    c = bizcompany.morning_card(rt, now=eight, idle=5)
    assert c and c["title"] == "Firma dnes" and "schválení" in c["body"]
    assert bizcompany.morning_card(rt, now=eight + 60, idle=5) is None       # once a day
    assert bizcompany.morning_card(rt, now=dt.datetime(2026, 11, 21, 15, 0).timestamp(), idle=5) is None   # afternoon


def test_a_button_tapped_on_the_phone(rt):
    c = TestClient(create_app(rt, manage_runtime=False), client=REMOTE)
    hdr = {"Authorization": f"Bearer {rt.cfg.phone.token}"}
    r = c.post("/api/phone/notice_action", json={"action": "timer_more", "args": {"label": "Pizza", "minutes": 5}}, headers=hdr)
    assert r.json()["ok"] and any(t["label"] == "Pizza" for t in rt.timers.list())
    assert c.post("/api/phone/notice_action", json={"action": "report_bug"}, headers=hdr).status_code == 400


def test_away_notices_carry_their_buttons_to_the_phone(rt, monkeypatch):
    pushed = []
    rt.phone_push = lambda kind, **d: pushed.append((kind, d)) or True
    monkeypatch.setattr(rt, "user_away", lambda: True)
    rt._timer_fired("Pizza")
    assert pushed and [a["label"] for a in pushed[0][1]["actions"]] == ["+5 min", "Ok"]


def test_the_try_out_runs_each_new_thing(rt):
    spoken = []
    rt.speak = lambda text, lang="cs", reply_to="", announce="": spoken.append(text)
    c = TestClient(create_app(rt, manage_runtime=False))
    with c.websocket_connect(f"/ws?token={rt.cfg.phone.token}") as ws:
        ws.receive_json()
        q = rt.bus.subscribe()
        for item in ("notice", "game_tip", "voice", "barge"):
            ws.send_json({"type": "trial_run", "item": item})
        ws.send_json({"type": "ping"})
        time.sleep(0.3)
    ev = drain(q)
    assert any(e["type"] == "notify" and e["title"] == "Zkouška upozornění" for e in ev)
    assert any(e["type"] == "game_tip" for e in ev) and len(spoken) == 2


async def test_later_loops_start_a_little_later(rt):
    ran = []

    async def job():
        ran.append(1)
    t = rt._later(job(), 0.05)
    await asyncio.sleep(0.01)
    assert not ran
    await asyncio.sleep(0.1)
    assert ran and t.done()
    t2 = rt._later(job(), 10)
    t2.cancel()
    await asyncio.sleep(0)
