"""Omega Brain: dynamic priorities (009), error prediction (008), several solutions compared (004)."""
import json
import time

from conftest import FakeRouter
from jarvis import omega, tools

tools.load_builtin()
NOW = 1_800_000_000.0


def test_priority_moves_with_deadline_importance_and_waiting():
    q = [{"id": "a", "goal": "uklidit plochu", "created": NOW - 60},
         {"id": "b", "goal": "poslat fakturu", "created": NOW - 60, "deadline": NOW + 1800},
         {"id": "c", "goal": "zálohovat fotky", "created": NOW - 10 * 3600},
         {"id": "d", "goal": "nic", "created": NOW, "not_before": NOW + 3600}]
    r = omega.rank(q, NOW)
    assert [x["id"] for x in r][:3] == ["b", "c", "a"] and r[-1]["id"] == "d" and r[-1]["score"] < 0
    assert "termín za 30 min" in r[0]["why"] and any("čeká" in w for w in r[1]["why"])
    urgent = omega.priority_score({"goal": "urgentní: zavolat bance", "created": NOW}, NOW)
    assert urgent[0] > omega.priority_score({"goal": "zavolat bance", "created": NOW}, NOW)[0]
    focus = omega.priority_score({"goal": "dodělat web pro klienta", "created": NOW}, NOW, focus="pracuju na webu pro klienta")
    assert "souvisí s tím, na čem právě děláš" in focus[1]


async def test_queue_uses_dynamic_priority(rt):
    t1 = rt.tasks.enqueue("uklidit stažené soubory")
    t2 = rt.tasks.enqueue("odeslat nabídku", deadline=time.time() + 900)
    assert [q["id"] for q in rt.tasks.queue()] == [t2, t1]
    assert rt.tasks.next_queued()["id"] == t2
    t3 = rt.tasks.enqueue("vyfotit doklady", priority="vysoká")
    assert rt.tasks.queue()[1]["id"] == t3


def test_predict_errors(rt, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    steps = [{"tool": "read_text_file", "args": {"path": str(tmp_path / "a.txt")}},
             {"tool": "read_text_file", "args": {"path": str(tmp_path / "chybi.txt")}},
             {"tool": "neexistuje", "args": {}},
             "pošli e-mail Petrovi",
             "stáhni ceník z webu"]
    f = omega.predict_errors(rt, steps, online=False)
    by = {(x["step"], x["level"]) for x in f}
    assert (1, "blok") in by and (2, "blok") in by and (3, "blok") in by and (4, "riziko") in by
    assert not any(x["step"] == 0 and x["level"] == "blok" for x in f)
    assert "e-mailový účet" in omega.summarize(f)


def test_predict_errors_learns_from_failures(rt):
    rt.tasks.begin("test", rt.memory.current_conversation)
    for ok in (0, 0, 1, 0):
        rt.tasks.log_action("speed_test", {}, bool(ok), "server nedostupný", 10)
    f = omega.predict_errors(rt, [{"tool": "speed_test", "args": {}}], online=True)
    assert any("nepovedl 3× z 4" in x["text"] for x in f)


async def test_plan_gets_risks(rt):
    rt.tasks.begin("poslat zprávu", rt.memory.current_conversation)
    rt.tasks.set_plan(["napiš e-mail šéfovi", "hotovo"])
    assert any("e-mailový účet" in r["text"] for r in rt.tasks.current["risks"])


async def test_solve_plans_picks_the_feasible_one(rt):
    rt.router = FakeRouter([
        json.dumps([{"name": "E-mailem", "idea": "pošli to mailem", "steps": ["pošli e-mail účetní"]},
                    {"name": "Ručně", "idea": "vytiskni a odnes", "steps": ["vytiskni fakturu", "odnes ji"]}]),
        json.dumps({"feasibility": 8, "risk": 2, "effort": 2, "why": "rychlé"}),
        json.dumps({"feasibility": 7, "risk": 2, "effort": 6, "why": "pracné"}),
    ])
    r = await omega.solve_plans(rt, "dostat fakturu účetní", 2)
    assert r["best"]["name"] == "Ručně"                      # mail is not set up → its step is blocked
    assert any(f["level"] == "blok" for f in r["candidates"][1]["findings"])


async def test_solve_code_tries_each_approach_in_a_copy(rt, tmp_path):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    calls = []

    def runner(work, cmd):
        text = (work / "calc.py").read_text(encoding="utf-8")
        calls.append(text)
        return ("a + b" in text, "FAILED" if "a + b" not in text else "ok")

    rt.router = FakeRouter([
        json.dumps([{"name": "Přepsat výraz", "idea": "oprav znaménko"}, {"name": "Nic", "idea": "nech být"}]),
        json.dumps({"calc.py": "def add(a, b):\n    return a + b\n"}),
        "nevím", "nevím", "nevím",
    ])
    r = await omega.solve_code(rt, "add odčítá", tmp_path, "pytest", ["calc.py"], 2, runner=runner)
    assert r["solved"] and r["best"]["name"] == "Přepsat výraz" and "+    return a + b" in r["best"]["diff"]
    assert (tmp_path / "calc.py").read_text(encoding="utf-8").endswith("a - b\n")        # the project is untouched


async def test_tools_registered(rt):
    assert tools.REGISTRY["apply_solution"].danger and "predict_errors" in tools.REGISTRY
    r = await tools.call("predict_errors", {"goal": "zavolej mámě"}, rt)
    assert r.ok and "telefon" in r.summary
