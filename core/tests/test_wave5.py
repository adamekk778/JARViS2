"""OMEGA wave 5: specialist agents (own tools, same safety path, evidence, no recursion, handover), deep research with
checked citations, alternatives, several models compared, goal → tracked plan, and the specialists' real checks."""
import json
import sqlite3

import httpx
import pytest
from conftest import FakeRouter

from jarvis import agents, devcheck, thinking, tools

tools.load_builtin()


# ---------------------------------------------------------------------------------------------- agents
async def test_delegate_runs_the_specialist_with_its_own_tools(rt, tmp_path):
    (tmp_path / "README.md").write_text("Projekt pekárna", encoding="utf-8")
    rt.router = FakeRouter([
        [("list_folder", {"path": str(tmp_path)})],                       # the specialist looks around
        [("run_shell", {"command": "del *"})],                            # not its tool → refused
        "Projekt má jen README; chybí testy.",
    ])
    tid = rt.tasks.begin("posouzení", rt.memory.current_conversation)
    r = await tools.call("delegate_to_agent", {"agent": "architekt", "task": "Posuď projekt v " + str(tmp_path)}, rt)
    assert r.ok and "Architekt" in r.summary and "chybí testy" in r.summary and "list_folder" in r.summary
    sys_prompt = rt.router.calls[0]["messages"][0]["content"]
    offered = {t["function"]["name"] for t in rt.router.calls[0]["tools"]}
    assert "Architekt" in sys_prompt and "list_folder" in offered and "run_shell" not in offered and "delegate_to_agent" not in offered
    tool_msg = rt.router.calls[2]["messages"][-1]
    assert "tahle role nemá" in tool_msg["content"]
    ev = rt.tasks.get(tid)["evidence"]
    assert [e["claim"] for e in ev if e["source"] == "agent Architekt"] == ["zadání", "výsledek"]
    acts = [a["tool"] for a in rt.tasks.get(tid)["actions"]]
    assert "list_folder" in acts and "run_shell" not in acts


async def test_specialist_dangerous_step_still_needs_approval(rt, tmp_path):
    target = tmp_path / "docs.md"
    rt.router = FakeRouter([[("write_text_file", {"path": str(target), "content": "x"})], "hotovo"])
    target.write_text("původní", encoding="utf-8")
    rt.tasks.begin("dok", rt.memory.current_conversation)
    task = __import__("asyncio").create_task(agents.run(rt, "dokumentace", "přepiš docs"))
    for _ in range(50):
        await __import__("asyncio").sleep(0.01)
        if rt.agent.pending_confirm():
            break
    cid = rt.agent.pending_confirm()
    assert cid
    rt.agent.confirm(cid, False)
    r = await task
    assert target.read_text(encoding="utf-8") == "původní" and r["tools"][0]["ok"] is False


async def test_team_hands_over_the_result(rt):
    rt.router = FakeRouter(["Návrh: tři moduly.", "Otestováno: moduly fungují."])
    rt.tasks.begin("tým", rt.memory.current_conversation)
    r = await tools.call("agent_team", {"steps": [{"agent": "architekt", "task": "navrhni"}, {"agent": "tester", "task": "ověř návrh"}]}, rt)
    assert r.ok and "Architekt" in r.summary and "Tester" in r.summary
    second_user = rt.router.calls[1]["messages"][1]["content"]
    assert "Návrh: tři moduly." in second_user                      # handover


async def test_unknown_agent(rt):
    r = await tools.call("delegate_to_agent", {"agent": "kuchař", "task": "x"}, rt)
    assert not r.ok and "architekt" in r.summary


# ---------------------------------------------------------------------------------------------- research
def test_extract_json_and_citation_check():
    assert thinking.extract_json('Tady:\n```json\n{"a": [1, {"b": "}"}]}\n```') == {"a": [1, {"b": "}"}]}
    assert thinking.extract_json('ok {"x": 1} a dál') == {"x": 1}
    with pytest.raises(ValueError):
        thinking.extract_json("bez json")
    c = thinking.verify_citations("Tvrzení A [1]. Tvrzení B [3].\n\n" + "Dlouhý odstavec bez citace " * 5, 2)
    assert c["invalid"] == [3] and c["unused"] == [2] and c["uncited_paragraphs"] == 1 and not c["ok"]


async def test_deep_research_reads_sources_and_checks_citations(rt, monkeypatch):
    from jarvis.tools import web

    pages = {"https://a.cz/1": "Praha má 1,3 milionu obyvatel. " * 20, "https://b.org/2": "Brno je druhé největší město. " * 20,
             "https://c.com/3": "krátké"}
    monkeypatch.setattr(web, "_ddg", lambda q, n, news: [{"title": u, "href": u, "body": ""} for u in pages])

    def handler(req):
        return httpx.Response(200, text=f"<html><body><p>{pages[str(req.url)]}</p></body></html>")
    rt.transport = httpx.MockTransport(handler)
    rt.router = FakeRouter(['{"queries": ["obyvatelé Praha", "největší města ČR"]}',
                            "## Shrnutí\nPraha má 1,3 milionu obyvatel [1], Brno je druhé [2]."])
    rt.tasks.begin("výzkum", rt.memory.current_conversation)
    r = await tools.call("deep_research", {"question": "Největší města ČR"}, rt)
    assert r.ok and r.data["check"]["ok"] and len(r.data["sources"]) == 2           # the too-short page is skipped
    text = open(r.data["path"], encoding="utf-8").read()
    assert "## Zdroje" in text and "https://a.cz/1" in text and "neexistující čísla zdrojů: žádná" in text
    t = rt.tasks.get(rt.tasks.list(limit=1)[0]["id"])
    assert t["artifacts"] and any(e["source"] == "web_read" for e in t["evidence"])


# ---------------------------------------------------------------------------------------------- thinking
async def test_compare_options(rt):
    rt.router = FakeRouter([json.dumps({"options": [
        {"name": "Notebook", "pros": ["přenosný"], "cons": ["dražší"], "risk": 2, "risk_why": "baterie"},
        {"name": "Stolní PC", "pros": ["výkon"], "cons": ["nepřenosný"], "risk": 1, "risk_why": "nic"},
        {"name": "Počkat", "pros": ["levnější"], "cons": ["čekání"], "risk": 3, "risk_why": "ceny"}],
        "ranking": ["Stolní PC", "Neexistuje", "Notebook"], "why_best": "výkon za cenu", "confidence": 140, "missing_info": ["rozpočet"]})])
    r = await tools.call("compare_options", {"goal": "Jaký počítač na hry?"}, rt)
    assert r.ok and "Doporučuji: Stolní PC" in r.summary and "Jistota 100 %" in r.summary and "rozpočet" in r.summary
    assert r.data["ranking"] == ["Stolní PC", "Notebook"]


async def test_ask_models_needs_two_and_compares(rt):
    rt.router = FakeRouter(["Odpověď A. Jistota: 80 %"])
    rt.router.providers = lambda: [type("P", (), {"id": "groq"})()]
    r = await tools.call("ask_models", {"question": "Kolik je 2+2?"}, rt)
    assert "aspoň dva" in r.summary
    rt.router = FakeRouter(["Čtyři.", "4", json.dumps({"agree": ["výsledek 4"], "disagree": [], "consensus": "2+2=4", "agreement": 95})])
    rt.router.providers = lambda: [type("P", (), {"id": "groq"})(), type("P", (), {"id": "gemini"})()]
    r = await tools.call("ask_models", {"question": "Kolik je 2+2?"}, rt)
    assert r.ok and "Shoda modelů 95 %" in r.summary and "vysoká" in r.summary
    assert [c["only"] for c in rt.router.calls[:2]] == ["groq", "gemini"]


async def test_goal_plan_sets_mission_criteria_and_steps(rt):
    rt.router = FakeRouter([json.dumps({"phases": [{"name": "Příprava", "steps": [{"text": "Zjistit rozpočet", "who": "uživatel"}]},
                                                   {"name": "Nákup", "steps": [{"text": "Porovnat ceny", "who": "JARVIS"}]}],
                                        "criteria": ["Kolo koupeno do 15 000 Kč"], "risks": ["vyprodáno"], "first_step": "Zjistit rozpočet"})])
    tid = rt.tasks.begin("kolo", rt.memory.current_conversation)
    r = await tools.call("goal_plan", {"goal": "Koupit kolo"}, rt)
    t = rt.tasks.get(tid)
    assert r.ok and t["criteria"] == ["Kolo koupeno do 15 000 Kč"] and [s["title"] for s in t["steps"]] == ["Příprava: Zjistit rozpočet", "Nákup: Porovnat ceny"]


async def test_bad_json_twice_is_a_clear_error(rt):
    rt.router = FakeRouter(["nevím", "pořád nevím"])
    r = await tools.call("check_assumptions", {"plan": "x"}, rt)
    assert not r.ok and "strukturovanou" in r.summary


# ---------------------------------------------------------------------------------------------- the specialists' checks
def test_sql_is_read_only(tmp_path):
    db = tmp_path / "shop.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE zbozi (id INTEGER, nazev TEXT)")
    con.execute("INSERT INTO zbozi VALUES (1, 'chleba')")
    con.commit()
    con.close()
    assert devcheck.sql_query(db, "SELECT nazev FROM zbozi")["rows"] == [["chleba"]]
    assert devcheck.sql_schema(db)[0]["name"] == "zbozi"
    for bad in ("DELETE FROM zbozi", "SELECT 1; DROP TABLE zbozi", "WITH x AS (SELECT 1) DELETE FROM zbozi"):
        with pytest.raises(ValueError):
            devcheck.sql_query(db, bad)
    with pytest.raises(sqlite3.OperationalError):                      # even a sneaky write fails: the file is opened read-only
        devcheck.sql_query(db, "PRAGMA user_version = 5")
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM zbozi").fetchone()[0] == 1


def test_a11y_audit_finds_real_problems():
    html = """<html><head></head><body><h2>Menu</h2>
<img src="logo.png"><input type="text" name="email"><button></button>
<a href="/x">klikni zde</a><p style="color:#999999;background:#ffffff">šedý text</p>
<div onclick="go()">Pokračovat</div><h4>Skok</h4></body></html>"""
    d = devcheck.a11y_audit(html)
    rules = {i["rule"] for i in d["issues"]}
    assert {"1.1.1", "1.3.1", "4.1.2", "2.4.4", "1.4.3", "2.1.1", "3.1.1", "2.4.2"} <= rules and d["score"] < 40
    good = devcheck.a11y_audit('<html lang="cs"><head><title>T</title></head><body><h1>A</h1><img src="a" alt="logo">'
                               '<label for="e">E-mail</label><input id="e"><button>Odeslat</button><a href="/">Domů</a></body></html>')
    assert good["issues"] == [] and good["score"] == 100
    assert devcheck.contrast("#000000", "#ffffff") == 21.0


async def test_check_translation(rt, tmp_path):
    (tmp_path / "en.json").write_text(json.dumps({"hi": "Hello {name}", "menu": {"save": "Save", "quit": "Quit %s"}}), encoding="utf-8")
    (tmp_path / "cs.json").write_text(json.dumps({"hi": "Ahoj {jmeno}", "menu": {"save": "Save"}}), encoding="utf-8")
    r = await tools.call("check_translation", {"source": str(tmp_path / "en.json"), "translated": str(tmp_path / "cs.json")}, rt)
    assert not r.ok and r.data["missing"] == ["menu.quit"] and r.data["placeholders"] == ["hi"] and r.data["untranslated"] == ["menu.save"]
