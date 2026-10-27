"""Wave 42: recurring meetings, meeting folders, programming exercises, project-based learning, client portal."""
import datetime as dt
import json
import os
import time

from jarvis import tools, workplus

tools.load_builtin()

T0 = dt.datetime(2026, 9, 7, 9, 0).timestamp()      # a Monday


def weekly(title, n, minutes=60, day=0):
    t = T0 + day * 86400
    return [{"id": f"e{i}", "title": f"{title} #{i + 1}", "start": t + i * 7 * 86400, "end": t + i * 7 * 86400 + minutes * 60, "location": ""}
            for i in range(n)]


def note(at, todos=(), points=(), seconds=3600, transcript=""):
    return {"created": at + 120, "seconds": seconds, "todos": json.dumps(list(todos)), "points": json.dumps(list(points)), "transcript": transcript, "title": "Hovor"}


def test_series_key():
    assert workplus.series_key("Porada týmu #12 (říjen)") == workplus.series_key("Porada týmu – 3. 11.") == "porada tymu"


def test_meeting_series_verdicts():
    now = T0 + 70 * 86400
    useless = weekly("Status meeting", 8)
    useful = weekly("Plánování sprintu", 8, 90, day=1)
    notes = [note(e["start"], points=["a"], seconds=1500) for e in useless[:6]]
    notes += [note(e["start"], todos=["úkol"], points=["a", "b", "c"], seconds=6000,
                   transcript="Já: dobře tak to uděláme\nPetr: souhlas\nJá: ještě jedna věc k tomu") for e in useful[:6]]
    s = {x["title"].split(" #")[0]: x for x in workplus.meeting_series(useless + useful + weekly("Jednou", 2), notes, now)}
    assert set(s) == {"Status meeting", "Plánování sprintu"}
    st, pl = s["Status meeting"], s["Plánování sprintu"]
    assert st["verdict"] == "zrušit nebo nahradit e-mailem" and st["useful"] == 0 and st["recorded"] == 6
    assert pl["verdict"] == "nechat" and pl["avg_overrun_min"] == 10.0 and pl["talk_share"] == {"Já": 90, "Petr": 10}
    assert round(pl["per_month"]) == 5 and pl["hours_month"] > st["hours_month"]


def test_meeting_trend_and_shorten():
    now = T0 + 70 * 86400
    evs = weekly("Retro", 8)
    notes = [note(e["start"], todos=["x", "y", "z"] if i < 3 else (["x"] if i < 5 else []), points=["a"], seconds=3600) for i, e in enumerate(evs[:7])]
    r = workplus.meeting_series(evs, notes, now)[0]
    assert r["trend"] == "méně výstupů" and r["verdict"].startswith("zředit")
    notes2 = [note(e["start"], todos=["x"], seconds=1800) for e in evs[:7]]
    assert workplus.meeting_series(evs, notes2, now)[0]["verdict"] == "zkrátit"


def test_meeting_folder(tmp_path):
    src = tmp_path / "docs"
    src.mkdir()
    agenda = src / "agenda.docx"
    agenda.write_bytes(b"agenda")
    old = src / "stary.txt"
    old.write_text("x")
    os.utime(old, (T0 - 10 * 86400, T0 - 10 * 86400))
    os.utime(agenda, (T0 - 1800, T0 - 1800))
    files = workplus.files_around([src], T0, T0 + 3600)
    assert files == [agenda]
    r = workplus.meeting_folder("Porada: rozpočet/2027", T0, note(T0, todos=["poslat čísla"], points=["schválen rozpočet"], transcript="Já: ahoj"),
                                files, tmp_path / "out")
    d = tmp_path / "out" / "2026-09-07 Porada rozpočet2027"
    md = (d / "schuzka.md").read_text(encoding="utf-8")
    assert r["copied"] == ["agenda.docx"] and "- [ ] poslat čísla" in md and "schválen rozpočet" in md and (d / "prepis.txt").exists()


async def test_meeting_tools(rt):
    for e in weekly("Status", 4):
        rt.calendar.add(e["title"], dt.datetime.fromtimestamp(time.time() - 30 * 86400 + int(e["title"][-1]) * 7 * 86400))
    r = await tools.call("meeting_relevance", {}, rt)
    assert r.ok and "Status" in r.summary and r.data[0]["verdict"] == "nevím"
    r = await tools.call("meeting_review", {"name": "status"}, rt)
    assert r.ok and "4×" in r.summary
    r = await tools.call("meeting_folder", {"meeting": "Status", "include_files": False}, rt)
    assert r.ok and r.attachments[0].endswith("schuzka.md")


def test_exercises_are_consistent():
    for k in workplus.EXERCISES:
        ex = workplus.make_exercise(k, seed=3)
        assert ex["tests"] and ex["starter"].startswith("def solve(") and ex["level"] in (1, 2, 3)
    assert workplus.make_exercise("rimska_cisla", seed=1)["tests"][5] == {"args": [1994], "expected": "MCMXCIV"}
    assert all(workplus.make_exercise(level=3, seed=s)["level"] == 3 for s in range(5))


def test_check_solution():
    tests = workplus.make_exercise("palindrom", seed=1)["tests"]
    good = "import re, unicodedata\ndef solve(t):\n    s=''.join(c for c in unicodedata.normalize('NFKD', t.lower()) if not unicodedata.combining(c))\n" \
           "    s=re.sub(r'[^a-z0-9]','',s)\n    return s==s[::-1]\n"
    assert workplus.check_solution(good, tests) == {"ok": True, "passed": 5, "total": 5, "fails": []}
    bad = workplus.check_solution("def solve(t):\n    return t == t[::-1]\n", tests)
    assert not bad["ok"] and bad["passed"] < 5 and bad["fails"][0]["expected"] is True
    assert "SyntaxError" in workplus.check_solution("def solve(:\n", tests)["error"]
    slow = workplus.check_solution("def solve(t):\n    while True: pass\n", tests, timeout=2)
    assert "déle" in slow["error"]


async def test_coding_tools(rt):
    r = await tools.call("coding_exercise", {"topic": "fizzbuzz"}, rt)
    assert r.ok and "FizzBuzz" in r.summary
    code = "def solve(n):\n    return list(range(1, n+1))\n"
    assert tools.is_dangerous(tools.REGISTRY["coding_check"], {"code": code}, ctx=rt)      # not what the user wrote → ask first
    rt.memory.add_message("user", "moje řešení:\n" + code)
    assert not tools.is_dangerous(tools.REGISTRY["coding_check"], {"code": code}, ctx=rt)
    r = await tools.call("coding_check", {"code": code}, rt)
    assert r.ok and "Prošlo 1 z 5" in r.summary


async def test_learning_project(rt):
    r = await tools.call("learning_project", {"goal": "chci se naučit dělat webové stránky"}, rt)
    assert r.ok and r.data["kind"] == "web" and r.data["next"]["n"] == 1 and "HTML" in r.summary
    assert any(d["deck"].startswith("Projekt:") for d in rt.learning.decks())
    r = await tools.call("learning_project", {"done_step": 1}, rt)
    assert r.data["progress"] == 20 and r.data["next"]["n"] == 2
    for n in (2, 3, 4, 5):
        r = await tools.call("learning_project", {"done_step": n}, rt)
    assert r.data["finished"] and "hotový" in r.summary
    assert workplus.pick_project("Arduino a senzory") == "arduino" and workplus.pick_project("něco") == "python"


async def test_client_portal(rt):
    from jarvis import bizops

    rt.db.exec(bizops.QUOTES_SQL)
    rt.db.exec(bizops.REQ_SQL)
    rt.db.exec("INSERT INTO quotes (number, client, created, valid_until, base, total, status) VALUES ('N-001', 'Pekárna Novák', ?, '2026-12-01', 1000, 1210, 'přijatá')", (T0,))
    rt.db.exec("INSERT INTO quotes (number, client, created, total, status) VALUES ('N-002', 'Jiný klient', ?, 5, 'otevřená')", (T0,))
    rt.db.exec("INSERT INTO customer_requests (created, client, text, status, due) VALUES (?, 'Pekárna Novák', '<script>alert(1)</script> nový web', 'otevřený', '2026-11-10')", (T0,))
    r = await tools.call("client_portal", {"client": "novák"}, rt)
    assert r.ok and "/sites/portal-pekarna-novak-" in r.data["url"]
    page = open(r.data["path"], encoding="utf-8").read()
    assert "N-001" in page and "1 210 Kč" in page and "N-002" not in page and "&lt;script&gt;" in page and "<script>" not in page
    again = await tools.call("client_portal", {"client": "Pekárna Novák"}, rt)
    assert again.data["id"] == r.data["id"]                                             # same address after refresh
    assert not (await tools.call("client_portal", {"client": "Nikdo"}, rt)).ok
