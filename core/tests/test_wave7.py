"""OMEGA wave 7 (learning): SM-2 flashcards, cards/tests from documents, grading + mistakes, weak spots, exam plan,
study stats, a math step checker that computes, mind maps, oral exam."""
import datetime as dt
import json
import time

import pytest
from conftest import FakeRouter

from jarvis import learning, tools

tools.load_builtin()


def test_sm2_schedule(rt):
    lr = rt.learning
    c = lr.add_card("Dějepis", "Kdy byla bitva na Bílé hoře?", "1620")
    with pytest.raises(ValueError):
        lr.add_card("Dějepis", "Kdy byla bitva na Bílé hoře?", "1620")
    now = time.time()
    c = lr.review(c["id"], 4, now)
    assert c["interval"] == 1 and abs(c["due"] - (now + 86400)) < 2
    c = lr.review(c["id"], 5, now)
    assert c["interval"] == 6
    c = lr.review(c["id"], 4, now)
    assert c["interval"] == round(6 * c["ease"], 1) or c["interval"] > 6
    c = lr.review(c["id"], 1, now)
    assert c["reps"] == 0 and c["lapses"] == 1 and c["due"] - now == pytest.approx(600, abs=2) and c["ease"] >= 1.3
    assert lr.decks()[0]["deck"] == "Dějepis"


async def test_review_flow_by_tool(rt):
    rt.learning.add_card("Angličtina", "pes", "dog")
    q = await tools.call("flashcards_review", {}, rt)
    assert q.ok and "pes" in q.summary and "dog" not in q.summary          # the answer is not given away
    r = await tools.call("flashcards_review", {"card_id": q.data["id"], "grade": 5}, rt)
    assert "dog" in r.summary
    assert "Teď není co opakovat" in (await tools.call("flashcards_review", {}, rt)).summary


async def test_cards_and_quiz_from_a_document(rt, tmp_path):
    p = tmp_path / "zapis.md"
    p.write_text("Fotosyntéza probíhá v chloroplastech. Vzniká při ní kyslík.", encoding="utf-8")
    rt.router = FakeRouter([json.dumps({"cards": [{"front": "Kde probíhá fotosyntéza?", "back": "V chloroplastech", "topic": "Biologie"},
                                                  {"front": "Co vzniká?", "back": "Kyslík"}]})])
    r = await tools.call("flashcards_from", {"source": str(p), "deck": "Bio"}, rt)
    assert r.ok and "2 kartiček" in r.summary and rt.learning.decks()[0]["cards"] == 2
    assert "chloroplastech" in rt.router.calls[0]["messages"][1]["content"]
    rt.router = FakeRouter([json.dumps({"questions": [{"q": "Kde?", "options": ["v jádře", "v mitochondriích"], "answer": "v chloroplastech"}]})])
    q = await tools.call("quiz_from", {"source": str(p)}, rt)
    assert q.ok and "v chloroplastech" in q.data[0]["options"]


async def test_grading_records_mistakes_and_weak_spots(rt):
    rt.router = FakeRouter([json.dumps({"score": 40, "feedback": "Půl správně.", "missing": ["kyslík"], "mistake": "neúplná odpověď"}),
                            json.dumps({"score": 20, "feedback": "Špatně.", "mistake": "chybějící znalost"})])
    r = await tools.call("check_answer", {"question": "Co vzniká při fotosyntéze?", "answer": "cukr", "expected": "cukr a kyslík", "topic": "Fotosyntéza"}, rt)
    assert r.ok and r.summary.startswith("40 / 100") and "kyslík" in r.summary
    await tools.call("check_answer", {"question": "Kdo napsal Babičku?", "answer": "Mácha", "expected": "Božena Němcová", "topic": "Literatura"}, rt)
    exact = await tools.call("check_answer", {"question": "2+2", "answer": "4", "expected": "4", "topic": "Matika"}, rt)
    assert exact.summary.startswith("100")
    w = await tools.call("learning_weak_spots", {}, rt)
    assert w.data["topics"][0]["topic"] == "Literatura" and "chybějící znalost" in w.summary


def test_exam_plan(rt):
    today = dt.date(2026, 11, 2)
    p = rt.learning.plan_exam("Biologie", dt.date(2026, 11, 12), ["Buňka", "Fotosyntéza", "Genetika"], today)
    days = list(p["plan"])
    assert p["days"] == 10 and days[0] == "2026-11-02" and p["plan"]["2026-11-11"][-1].startswith("Celkové opakování")
    flat = [x for v in p["plan"].values() for x in v]
    for t in ("Buňka", "Fotosyntéza", "Genetika"):
        assert f"Naučit: {t}" in flat and f"Zopakovat: {t}" in flat
    assert all(d < "2026-11-12" for d in days)
    with pytest.raises(ValueError):
        rt.learning.plan_exam("X", today, ["a"], today)


def test_study_stats_streak(rt):
    c = rt.learning.add_card("A", "q", "a")
    now = time.time()
    rt.learning.review(c["id"], 4, now)
    rt.learning.review(c["id"], 2, now - 86400)
    s = rt.learning.stats()
    assert s["reviews"] == 2 and s["accuracy"] == 50 and s["streak"] == 2


# ---------------------------------------------------------------------------------------------- math
def test_safe_eval_is_safe_and_czech_friendly():
    assert learning.safe_eval("2x^2 + 3,5", {"x": 2}) == 11.5
    assert learning.safe_eval("3(x+1)", {"x": 1}) == 6
    assert learning.safe_eval("sqrt(16) + pi - pi", {}) == 4
    for bad in ("__import__('os').system('x')", "open('f')", "x.__class__", "[1,2]"):
        with pytest.raises((ValueError, SyntaxError)):
            learning.safe_eval(bad, {"x": 1})


def test_check_expression_steps():
    r = learning.check_steps(["(x+1)^2", "x^2 + 2x + 1", "x^2 + 2x + 2"])
    assert not r["ok"] and r["first_error"]["step"] == 3
    assert learning.check_steps(["2(a+b) - a", "a + 2b"])["ok"]


def test_check_equation_steps():
    good = learning.check_steps(["2x + 3 = 7", "2x = 4", "x = 2"])
    assert good["ok"], good
    bad = learning.check_steps(["2x + 3 = 7", "2x = 10", "x = 5"])
    assert not bad["ok"] and bad["first_error"]["step"] == 2
    quad = learning.check_steps(["x^2 - 5x + 6 = 0", "(x-2)(x-3) = 0"])
    assert quad["ok"]


async def test_check_math_tool(rt):
    r = await tools.call("check_math_steps", {"steps": "3x - 2 = 10\n3x = 12\nx = 3"}, rt)
    assert "Chyba je v kroku 3" in r.summary
    assert "Všech 3 kroků" in (await tools.call("check_math_steps", {"steps": "3x - 2 = 10; 3x = 12; x = 4"}, rt)).summary


# ---------------------------------------------------------------------------------------------- maps & oral exam
async def test_mind_map_saved(rt):
    rt.router = FakeRouter([json.dumps({"root": "Buňka", "children": [{"name": "Jádro", "children": [{"name": "DNA"}]}, {"name": "Membrána"}],
                                        "links": [{"a": "DNA", "b": "Membrána", "why": "nic"}]})])
    rt.tasks.begin("mapa", rt.memory.current_conversation)
    r = await tools.call("mind_map", {"source": "Buňka"}, rt)
    assert r.ok and "# Buňka" in r.summary and "  - DNA" in r.summary
    text = open(r.summary.split("Uloženo: ")[1].strip(), encoding="utf-8").read()
    assert "mindmap" in text and "root((Buňka))" in text


async def test_oral_exam_avoids_repeats(rt):
    rt.learning.record_answer("", "Fotosyntéza", "Kde probíhá?", 50, "neúplná odpověď")
    rt.router = FakeRouter([json.dumps({"question": "Jaké látky fotosyntéza potřebuje?", "expected": "CO2, voda, světlo"})])
    r = await tools.call("oral_exam", {"topic": "Fotosyntéza"}, rt)
    assert r.ok and r.summary == "Jaké látky fotosyntéza potřebuje?"
    assert "Kde probíhá?" in rt.router.calls[0]["messages"][1]["content"]


def test_learn_page(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c, c.websocket_connect("/ws") as ws:
        def recv(t):
            return next(x for x in iter(ws.receive_json, None) if x["type"] == t)
        ws.send_json({"type": "learn_add", "deck": "Země", "front": "Hlavní město Francie?", "back": "Paříž"})
        assert recv("learn")["decks"][0]["deck"] == "Země"
        ws.send_json({"type": "learn_next", "deck": "Země"})
        card = recv("learn_card")["card"]
        assert card["front"] == "Hlavní město Francie?"
        ws.send_json({"type": "learn_grade", "id": card["id"], "grade": 5, "deck": "Země"})
        assert recv("learn_card")["card"] is None
        ws.send_json({"type": "learn_tool", "tool": "check_math_steps", "args": {"steps": "2x = 4\nx = 3"}})
        assert "Chyba je v kroku 2" in recv("learn_result")["summary"]
        ws.send_json({"type": "learn_tool", "tool": "run_shell", "args": {}})
        assert "nejde" in recv("error")["message"]
