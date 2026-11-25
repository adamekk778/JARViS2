"""3.20 Mozek+ (nápady 21–40)."""
from __future__ import annotations

import datetime as dt
import json
import time

from conftest import FakeRouter

from jarvis import brainx, tools


# ------------------------------------------------------------------ (21, 22, 40) hloubka, důkladně, kreativně
def test_risk_deep_creative_words():
    assert brainx.risky_action("zaplať tu fakturu") and brainx.risky_action("smaž ty staré zálohy")
    assert not brainx.risky_action("jaké je počasí")
    assert brainx.deep_request("promysli to důkladně") and brainx.deep_request("rozeber to krok za krokem")
    assert brainx.creative_request("vymysli šílené nápady na oslavu") and not brainx.creative_request("šílené počasí")


async def test_routing_thinks_deeper_and_bolder(rt):
    rt.router = FakeRouter(["Rozumím.", "Tady jsou nápady."])
    await rt.agent.handle("pošli Petrovi e-mail, že smlouvu podepíšu zítra")
    assert rt.router.calls[0]["effort"] == "high"
    await rt.agent.handle("vymysli šílené nápady na firemní večírek")
    assert rt.router.calls[1]["temperature"] == 1.0
    assert brainx.CREATIVE_RULE in rt.router.calls[1]["messages"][0]["content"]


# ------------------------------------------------------------------ (23) jistota
def test_confidence_from_sources():
    assert brainx.confidence([]) == (0, "")
    one = brainx.confidence([{"url": "https://blog.example.com/a"}])
    assert one[0] == 60 and "jen jeden zdroj" in one[1]
    three = brainx.confidence(["https://www.ct24.cz/x", "https://irozhlas.cz/y", "https://seznamzpravy.cz/z"])
    assert three[0] == 90 and "ct24.cz" in three[1]
    assert brainx.confidence(["https://a.cz", "https://b.cz"], verified=False)[0] == 55
    assert brainx.confidence_line("Odpověď.", [{"url": "https://a.cz"}]).startswith("\n\nJistota: 60 %")
    assert brainx.confidence_line("Odpověď. Jistota: 80 %", [{"url": "https://a.cz"}]) == ""


# ------------------------------------------------------------------ (24) styl psaní
def test_writing_style_profile(rt):
    texts = ["Dobrý den,\nposílám vám podklady. Můžete je prosím zkontrolovat?\nS pozdravem Adam",
             "Dobrý den,\ndíky za odpověď. Budete mít čas ve čtvrtek?\nS pozdravem Adam",
             "Ahoj, jasně, dorazím.\nDíky"]
    p = brainx.style_profile(texts)
    assert p["greeting"] == "dobry den" and p["sign_off"] == "s pozdravem" and p["address"] == "vykání" and p["samples"] == 3
    brainx._kv_set(rt, "writing_style", p)
    lines = brainx.prompt_lines(rt, "napiš e-mail Petrovi, že přijdu později")
    assert any(ln.startswith("Když píšeš e-mail") and "vykání" in ln for ln in lines)
    assert not any(ln.startswith("Když píšeš e-mail") for ln in brainx.prompt_lines(rt, "jaké je počasí"))


# ------------------------------------------------------------------ (25) slovník zkratek
async def test_glossary(rt):
    r = await tools.call("brain_kit", {"action": "glossary_add", "term": "PRJ", "meaning": "projekt Rekonstrukce Jih"}, rt)
    assert r.ok
    assert "PRJ = projekt Rekonstrukce Jih" in brainx.glossary_prompt(rt, "jak je na tom PRJ?")
    assert brainx.unknown_abbreviations(rt, "pošli PDF do PRJ a KZR") == ["KZR"]
    assert "PRJ" in brainx.learned_week(rt)["glossary"]
    assert (await tools.call("brain_kit", {"action": "glossary_remove", "term": "prj"}, rt)).ok
    assert brainx.glossary(rt) == {}


# ------------------------------------------------------------------ (26) vlastní malý model
def test_reflex_modelfile(rt):
    from jarvis import toolmind

    rt.db.conn.executescript(toolmind.SQL)
    for i, (ph, tool, args) in enumerate([("zhasni v kuchyni", "home_control", {"room": "kuchyně", "on": False}),
                                          ("pusť lofi", "youtube_play", {"query": "lofi"}), ("ztlum", "volume", {"action": "mute"}),
                                          ("co mám koupit", "list_show", {}), ("brífink", "briefing", {}),
                                          ("jen jednou", "weather", {})]):
        rt.db.exec("INSERT INTO tool_memory VALUES (?,?,?,?,?,?,?)", (ph, tool, json.dumps(args), "", 1 if i == 5 else 3, 0, time.time()))
    ex = brainx.reflex_examples(rt)
    assert len(ex) == 5 and {"phrase": "ztlum", "tool": "volume", "args": {"action": "mute"}} in ex
    mf = brainx.modelfile("qwen3:1.7b", ex)
    assert mf.startswith("FROM qwen3:1.7b") and 'MESSAGE user """ztlum"""' in mf and '"tool": "volume"' in mf
    path, n = brainx.write_modelfile(rt, "qwen3:1.7b")
    assert n == 5 and path.read_text(encoding="utf-8") == mf


# ------------------------------------------------------------------ (27) kontrola po dokončení
async def test_after_check(rt):
    rt.router = FakeRouter(['{"ok": false, "why": "Chybí příloha s fakturou."}'])
    cards = [{"tool": "find_file", "ok": True, "summary": "faktura.pdf"}, {"tool": "compose_email", "ok": True, "summary": "koncept"},
             {"tool": "email_send", "ok": True, "summary": "odesláno"}]
    r = await brainx.after_check(rt, "pošli fakturu účetní", cards, "Odesláno.")
    assert r == {"ok": False, "why": "Chybí příloha s fakturou."}
    assert await brainx.after_check(rt, "x", cards[:2], "y") is None          # short tasks: no second look


# ------------------------------------------------------------------ (28) přepočítání čísel
def test_numbers_are_recomputed():
    assert brainx.check_numbers("Celkem 1 250 + 380 = 1 630 Kč.") == []
    fixes = brainx.check_numbers("To je 12 × 15 = 170 a 20 % z 350 je 80.")
    assert fixes == ["12 × 15 = 180 (ne 170)", "20 % z 350 je 70 (ne 80)"]
    assert brainx.numbers_line("Hotovo.") == ""


async def test_wrong_sum_in_an_answer_is_corrected(rt):
    rt.router = FakeRouter(["Za tři noci: 3 × 1 450 = 4 150 Kč."])
    out = await rt.agent.handle("kolik zaplatím za tři noci po 1450 korunách?")
    assert "Oprava výpočtu" in out and "4 350" in out


# ------------------------------------------------------------------ (29) plán ke schválení
async def test_plan_first_waits_for_approval(rt):
    rt.update_config({"agent": {"plan_first": True}})
    text = ("projdi všechny faktury za listopad a pak je přejmenuj podle dodavatele, potom je zařaď do složek "
            "a nakonec připrav souhrn pro účetní a pošli mi ho do mobilu")
    assert brainx.needs_plan(rt, text)
    rt.router = FakeRouter(["1. Najdu faktury.\n2. Přejmenuji je.\n3. Zařadím do složek.\n4. Pošlu souhrn."])

    async def deny_later():
        import asyncio

        for _ in range(100):
            cid = rt.agent.pending_confirm()
            if cid:
                assert rt.agent.confirm_info[cid]["description"].startswith("Schválit plán: 1) Najdu faktury.")
                rt.agent.confirm(cid, False)
                return
            await asyncio.sleep(0.02)
    import asyncio

    task = asyncio.get_running_loop().create_task(deny_later())
    out = await rt.agent.handle(text)
    await task
    assert out.startswith("Dobře, podle toho plánu nic nedělám") and len(rt.router.calls) == 1


# ------------------------------------------------------------------ (30, 36, 37) styl, učitel, nevím
async def test_answer_style_and_teacher(rt):
    rt.router = FakeRouter([])
    out = await rt.agent.handle("odpovídej podrobně")
    assert out == "Odpovídám podrobně." and rt.cfg.general.answer_style == "detailed" and not rt.router.calls
    assert brainx.STYLES["detailed"] in brainx.prompt_lines(rt, "co je fotosyntéza")
    assert brainx.HONEST_RULE in brainx.prompt_lines(rt, "co je fotosyntéza")
    assert brainx.teach_request("nauč mě, jak to udělám sám") and not brainx.teach_request("nauč se tohle")


async def test_teacher_mode_offers_only_reading_tools(rt):
    from jarvis import permissions

    rt.router = FakeRouter(["Otevři Nastavení → Bluetooth…"])
    await rt.agent.handle("ukaž mi, jak sám zapnu bluetooth ve Windows")
    names = [sc.get("function", sc)["name"] for sc in rt.router.calls[0]["tools"] or []]
    assert names and all(n == "find_tools" or permissions.is_reading(tools.REGISTRY[n]) for n in names)
    assert brainx.TEACH_RULE in rt.router.calls[0]["messages"][0]["content"]


# ------------------------------------------------------------------ (31) kontext z obrazovky
async def test_screen_goes_along_with_what_is_this(rt):
    assert brainx.wants_screen(rt, "Co to je?", []) and not brainx.wants_screen(rt, "co to je fotosyntéza za proces", [])
    assert not brainx.wants_screen(rt, "co to je?", ["a1"])
    rt.platform.screenshot = lambda: b"\x89PNG\r\n\x1a\n" + b"0" * 100
    rt.router = FakeRouter(["To je chybová hláška."])
    await rt.agent.handle("co to je?")
    assert rt.router.calls[0]["need_vision"] is True
    rt.cfg.permissions.screen = False
    assert not brainx.wants_screen(rt, "co to je?", [])


# ------------------------------------------------------------------ (32) na noc
async def test_night_task(rt):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    at = brainx.night_time(rt, dt.datetime(2026, 11, 24, 22, 0))
    assert at == dt.datetime(2026, 11, 25, 2, 0)
    rt.router = FakeRouter([])
    out = await rt.agent.handle("projdi v noci moje fotky a najdi duplikáty")
    assert out.startswith("Udělám to v noci") and not rt.router.calls
    job = next(j for j in rt.scheduler.list() if j["kind"] == "prompt")
    assert job["payload"] == {"prompt": "projdi moje fotky a najdi duplikáty", "cheap": True}
    rt.cfg.brain.split_easy = "ollama"
    assert brainx.cheap_provider(rt) == "ollama"


# ------------------------------------------------------------------ (33) proč
async def test_why_after_steps(rt):
    rt.router = FakeRouter([[("volume", {"action": "set", "level": 20})], "Ztlumeno."])
    await rt.agent.handle("je tu nějak hlučno, uděláš s tím něco?")
    rows = brainx.why_last(rt)
    assert rows[0]["tool"] == "volume"
    rt.router = FakeRouter([])
    out = await rt.agent.handle("proč jsi to udělal?")
    assert out.startswith("Udělal jsem:") and not rt.router.calls


# ------------------------------------------------------------------ (35) rozpočet podle činnosti
def test_budget_per_activity(rt):
    assert brainx.over_budget(rt, "game") == ""
    rt.cfg.limits.ai_czk_game = 5
    brainx.add_spend(rt, "game", 3.0)
    assert brainx.over_budget(rt, "game") == ""
    brainx.add_spend(rt, "game", 2.5)
    assert brainx.over_budget(rt, "game").startswith("Dnešní rozpočet AI na hraní (5 Kč)")
    assert brainx.over_budget(rt, "work") == ""
    assert brainx.spend_today(rt, "game") == 5.5


# ------------------------------------------------------------------ (38) odhad doby
def test_estimate(rt):
    assert "odhad podle velikosti" in brainx.estimate(rt, "najdi soubor")["text"]
    for i in range(3):
        rt.db.exec("INSERT INTO tasks (id, conv_id, goal, status, created, finished, summary) VALUES (?,?,?,?,?,?,?)",
                   (f"t{i}", "c", "prejmenuj fotky z dovolene podle data", "done", 1000.0, 1000.0 + 120 + i * 60, ""))
    e = brainx.estimate(rt, "přejmenuj fotky z dovolené podle data")
    assert e["seconds"] == 180 and "podle 3 podobných" in e["text"]


# ------------------------------------------------------------------ (39) co se naučil
def test_learned_week(rt):
    rt.db.exec("CREATE TABLE IF NOT EXISTS learned_rules (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, created REAL, source TEXT, "
               "uses INT DEFAULT 0, on_ INT DEFAULT 1)")
    rt.db.exec("INSERT INTO learned_rules (text, created, source) VALUES (?,?,?)", ("Hudbu pouštěj na Spotify.", time.time(), "oprava"))
    d = brainx.learned_week(rt)
    assert d["rules"] == ["Hudbu pouštěj na Spotify."]
    assert brainx.learned_text(d).startswith("Pravidla z tvých oprav: Hudbu pouštěj na Spotify.")
    assert "nic nového" in brainx.learned_text({"rules": [], "reflexes": [], "skills": [], "glossary": []})


def test_week_job_is_created_once(rt):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    brainx.ensure_week_job(rt)
    brainx.ensure_week_job(rt)
    jobs = [j for j in rt.scheduler.list() if j["kind"] == "brain_week"]
    assert len(jobs) == 1 and jobs[0]["spec"] == {"type": "daily", "days": [6], "time": "18:00"}
