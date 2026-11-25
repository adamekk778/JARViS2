"""3.17 Chytřejší (návrhy 10–14): a part from any description, finger gestures, checks from your own commands, what
JARVIS learnt (and forgetting it), and pattern reflexes ("pusť {x} na YouTube")."""
from __future__ import annotations

import json

import numpy as np
import pytest
from conftest import FakeRouter

from jarvis import cad, handmodel, toolmind, tools


def _all() -> set[str]:
    tools.load_builtin()
    return set(tools.REGISTRY)


class _C:
    """A fake websocket client for the handlers."""

    def __init__(self, rt):
        self.rt = rt
        self.sent: list[tuple[str, dict]] = []

    async def send(self, t, **d):
        self.sent.append((t, d))


# ------------------------------------------------------------------------------------------ 14 pattern reflexes
def test_a_pattern_becomes_a_reflex_after_two_different_values(rt):
    allowed = _all()
    toolmind.learn(rt, "pusť lo-fi na YouTube", [("youtube_play", {"query": "lo-fi"}, True)], "Pouštím lo-fi.")
    assert toolmind.reflex(rt, "pusť Hans Zimmer na YouTube", allowed) is None           # one value is not a pattern yet
    toolmind.learn(rt, "Pusť jazz na YouTube", [("youtube_play", {"query": "jazz"}, True)], "Pouštím jazz.")
    rx = toolmind.reflex(rt, "Jarvisi, pusť Hans Zimmer na YouTube, prosím", allowed)
    assert rx == ("youtube_play", {"query": "Hans Zimmer"}, "Pouštím Hans Zimmer.")    # accents and case as you said it
    assert toolmind.reflex(rt, "pusť Hans Zimmer na Spotify", allowed) is None           # other words = no match
    assert toolmind.reflex(rt, "pusť Hans Zimmer na YouTube", allowed - {"youtube_play"}) is None   # switched off
    toolmind.punish(rt, "pusť Hans Zimmer na YouTube")                                   # "ne, to ne"
    assert toolmind.reflex(rt, "pusť Beethoven na YouTube", allowed) is None


def test_the_same_value_twice_or_a_risky_tool_is_not_a_pattern(rt):
    allowed = _all()
    for _ in range(3):
        toolmind.learn(rt, "pusť lo-fi na YouTube", [("youtube_play", {"query": "lo-fi"}, True)], "Pouštím lo-fi.")
    assert toolmind.reflex(rt, "pusť jazz na YouTube", allowed) is None
    for v in ("kontakty", "fotky"):                                                     # deleting asks first, always
        toolmind.learn(rt, f"smaž složku {v}", [("delete_file", {"path": v}, True)], f"Smazáno {v}.")
    assert toolmind.reflex(rt, "smaž složku dokumenty", allowed) is None
    toolmind.learn(rt, "pusť 1", [("youtube_play", {"query": "x"}, True)], "Pouštím.")   # the value must be in the words
    assert rt.db.one("SELECT COUNT(*) AS n FROM tool_patterns WHERE pattern LIKE 'pust 1%'")["n"] == 0


def test_match_pattern_keeps_your_words():
    assert toolmind._match_pattern("pust {x} na youtube", "pusť Žluťoučký kůň na YouTube!") == "Žluťoučký kůň"
    assert toolmind._match_pattern("pust {x} na youtube", "pusť na YouTube") is None
    assert toolmind._match_pattern("zapni {x}", "zapni světlo v kuchyni") == "světlo v kuchyni"
    assert toolmind._match_pattern("zapni {x}", "vypni světlo") is None


# ------------------------------------------------------------------------------------------ 13 what JARVIS learnt
async def test_learnt_list_block_and_forget(rt):
    from jarvis.server.handlers.toolmem import toolmem_forget, toolmem_get

    allowed = _all()
    for _ in range(2):
        toolmind.learn(rt, "ztlum to", [("volume", {"action": "down"}, True)], "Ztlumeno.")
    toolmind.learn(rt, "pusť lo-fi na YouTube", [("youtube_play", {"query": "lo-fi"}, True)], "Pouštím lo-fi.")
    toolmind.learn(rt, "pusť jazz na YouTube", [("youtube_play", {"query": "jazz"}, True)], "Pouštím jazz.")
    items = toolmind.memory_list(rt)
    phrase = next(i for i in items if i["kind"] == "phrase" and i["tool"] == "volume")
    pattern = next(i for i in items if i["kind"] == "pattern")
    assert phrase["reflex"] and phrase["phrase"] == "ztlum to"
    assert pattern["reflex"] and pattern["phrase"] == "pust … na youtube" and set(pattern["values"]) == {"lo fi", "jazz"}

    c = _C(rt)
    await toolmem_get(c, {})
    assert c.sent[-1][0] == "toolmem" and len(c.sent[-1][1]["items"]) == len(items)
    await toolmem_forget(c, {"phrase": "ztlum to", "tool": "volume", "block": True})        # "Ne reflex": kept, never a reflex
    assert c.sent[-1][1]["changed"] == 1 and toolmind.reflex(rt, "ztlum to", allowed) is None
    toolmind.learn(rt, "ztlum to", [("volume", {"action": "down"}, True)], "Ztlumeno.")
    assert toolmind.reflex(rt, "ztlum to", allowed) is None                              # a block stays
    await toolmem_forget(c, {"phrase": pattern["pattern"], "tool": "youtube_play"})        # the trash can
    assert toolmind.reflex(rt, "pusť Hans Zimmer na YouTube", allowed) is None
    await toolmem_forget(c, {"all": True})
    assert toolmind.memory_list(rt) == [] and c.sent[-1][1]["items"] == []


def test_forget_is_local_only():
    from jarvis.server import handlers

    handlers.load()
    assert "toolmem_forget" in handlers.LOCAL_ONLY and "toolmem_get" not in handlers.LOCAL_ONLY
    assert "mine_check" in handlers.SLOW


# ------------------------------------------------------------------------------------------ 12 checks from your commands
def test_your_commands_are_checked_again(rt, monkeypatch):
    from jarvis.evals import mine

    _all()
    rt.db.conn.executescript(toolmind.SQL)
    now = 1.0
    for phrase, tool in (("pust dalsi pisnicku", "media_control"), ("jake bude pocasi zitra", "weather"),
                         ("udelej neco s tim starym nastrojem", "gone_tool")):
        rt.db.exec("INSERT INTO tool_memory (phrase, tool, args, answer, ok, bad, last) VALUES (?,?,?,?,3,0,?)",
                   (phrase, tool, "{}", "", now))
    rt.db.exec("INSERT INTO tool_memory (phrase, tool, args, answer, ok, bad, last) VALUES (?,?,?,?,0,2,?)",
               ("zrus to", "media_control", "{}", "", now))                                   # failed = not a check
    res = mine.check(rt)
    assert res["checked"] == 3 and res["ok"] == 2
    assert res["failed"] == [{"phrase": "udelej neco s tim starym nastrojem", "tool": "gone_tool", "got": "nástroj už neexistuje"}]
    assert json.loads(rt.db.one("SELECT v FROM kv WHERE k='mine_check'")["v"])["checked"] == 3

    notes: list[tuple] = []
    monkeypatch.setattr(rt, "notify", lambda *a, **k: notes.append(a))
    assert mine.after_update(rt)["checked"] == 3 and len(notes) == 1                       # once per version…
    assert mine.after_update(rt) is None and len(notes) == 1                               # …not again


async def test_mine_check_handler(rt):
    from jarvis.server.handlers.toolmem import mine_check

    c = _C(rt)
    await mine_check(c, {})
    assert c.sent == [("mine_check", {"checked": 0, "ok": 0, "failed": []})]


# ------------------------------------------------------------------------------------------ 10 a part from any description
VASE = {"name": "Váza", "tree": {"difference": [
    {"cylinder": {"r": 30, "h": 80, "r2": 20}},
    {"cylinder": {"r": 27, "h": 80, "r2": 17}, "at": [0, 0, 2]}]}}
HOLDER = {"name": "Držák na kolo", "tree": {"difference": [
    {"union": [{"box": [60, 20, 5]}, {"box": [10, 20, 40], "at": [25, 0, 5]}]},
    {"cylinder": {"r": 2.2, "h": 7}, "at": [10, 10, -1]},
    {"cylinder": {"r": 2.2, "h": 7}, "at": [50, 10, -1]}]}}


def test_check_tree_says_what_is_wrong():
    assert cad.check_tree(VASE["tree"]) == "" and cad.check_tree(HOLDER["tree"]) == ""
    assert "box" in cad.check_tree({"box": [10, -1, 5]})
    assert "at" in cad.check_tree({"box": [1, 1, 1], "at": [0, 0]})
    assert "neznámý" in cad.check_tree({"torus": {"r": 5}})
    assert "složitý" in cad.check_tree({"union": [{"box": [1, 1, 1]}] * 300})
    deep: dict = {"box": [1, 1, 1]}
    for _ in range(20):
        deep = {"union": [deep]}
    assert "složitý" in cad.check_tree(deep)
    assert cad.check_tree({"box": [1, 1, float("inf")]}) != ""
    assert cad.check_tree({"box": [1, 1, 5000]}) != ""


def test_free_tree_volume_and_files(rt):
    tree = {"difference": [{"box": [20, 20, 10]}, {"cylinder": {"r": 3, "h": 12}, "at": [10, 10, -1]}]}
    lo, hi = cad.tree_bounds(tree)
    assert np.allclose(lo, [0, 0, 0]) and np.allclose(hi, [20, 20, 10])
    pts = np.array([[10, 10, 5], [2, 2, 5], [10, 10, 15]], dtype=np.float32)
    d = cad.tree_sdf(tree, pts)
    assert d[0] > 0 and d[1] < 0 and d[2] > 0                                            # the hole, the wall, above it
    scad = cad.tree_scad(tree)
    assert scad.startswith("difference() {") and "cube([20,20,10]);" in scad and "translate([10,10,-1])" in scad
    files = cad.free_files({"name": "Kostka s dírou", "version": 1, "params": {"tree": tree}})
    expected = (20 * 20 * 10 - np.pi * 9 * 10) / 1000
    assert files["closed"] and abs(files["volume_cm3"] - expected) < 0.25
    assert files["size_mm"] == [20.0, 20.0, 10.0]
    assert open(files["scad"], encoding="utf-8").read().count("difference()") == 1


def test_rotated_part_bounds():
    lo, hi = cad.tree_bounds({"box": [10, 2, 2], "rotate": [0, 0, 90]})
    assert np.allclose(hi - lo, [2, 10, 2], atol=1e-4)


async def test_cad_part_designs_and_edits_a_free_part(rt):
    _all()
    taller = json.loads(json.dumps(HOLDER))
    taller["tree"]["difference"][0]["union"][1]["box"][2] = 60
    rt.router = FakeRouter(["To nevím.", json.dumps(HOLDER), json.dumps(taller)])         # 1st answer is no JSON: one retry
    r = await tools.call("cad_part", {"action": "create", "description": "držák na kolo na zeď se dvěma šrouby"}, rt)
    assert r.ok and "Držák na kolo" in r.summary
    assert len(rt.router.calls) == 2 and "Tohle nejde" in rt.router.calls[1]["messages"][-1]["content"]
    part = cad.latest(rt)
    assert part["template"] == "free" and part["version"] == 1
    r = await tools.call("cad_part", {"action": "edit", "description": "o 20 mm vyšší"}, rt)
    assert r.ok and cad.latest(rt)["version"] == 2
    sent = rt.router.calls[-1]["messages"]
    assert "Pokyn: o 20 mm vyšší" in sent[-1]["content"] and '"box": [10, 20, 40]' in sent[-1]["content"]
    assert cad.latest(rt)["params"]["tree"]["difference"][0]["union"][1]["box"][2] == 60
    r = await tools.call("cad_part", {"action": "undo"}, rt)
    assert r.ok and cad.latest(rt)["params"]["tree"]["difference"][0]["union"][1]["box"][2] == 40


async def test_cad_part_gives_up_cleanly(rt):
    _all()
    rt.router = FakeRouter(['{"tree": {"torus": 1}}', '{"tree": {"box": [0, 1, 1]}}'])
    r = await tools.call("cad_part", {"action": "design", "description": "něco divného"}, rt)
    assert not r.ok and "nepodařilo navrhnout" in r.summary and cad.latest(rt) is None
    rt.router = FakeRouter([])
    r = await tools.call("cad_part", {"action": "create", "description": "krabička 60 × 40 × 25 mm"}, rt)
    assert r.ok and cad.latest(rt)["template"] == "box" and rt.router.calls == []         # a template needs no AI


# ------------------------------------------------------------------------------------------ 11 finger gestures
def test_hand_model_files_only_when_downloaded_whole():
    assert handmodel.status()["ready"] is False and handmodel.status()["size_mb"] >= 20
    assert handmodel.path_of("hand_landmarker.task") is None                             # not downloaded yet
    for bad in ("../secret.task", "x.task", "hand_landmarker.task/..", "", "HAND.task"):
        assert handmodel.path_of(bad) is None
    p = handmodel.folder() / "vision_wasm_internal.js"
    p.write_bytes(b"x" * 10)                                                            # a broken / partial file
    assert handmodel.path_of("vision_wasm_internal.js") is None
    p.write_bytes(b"x" * handmodel.FILES["vision_wasm_internal.js"][1])
    assert handmodel.path_of("vision_wasm_internal.js") == p
    p.unlink()


async def test_hand_model_download_checks_every_file(rt):
    import httpx

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not the model")
    seen: list[float] = []
    res = await handmodel.download(httpx.MockTransport(handler), progress=seen.append)
    assert res["ok"] is False and "nesedí" in res["error"]
    assert not any(handmodel.folder().glob("*.part")) and not handmodel.ready()


def test_hand_files_are_served_only_on_this_pc(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    app = create_app(rt, manage_runtime=False)
    assert TestClient(app, client=("192.168.1.20", 5000)).get("/api/hands/hand_landmarker.task").status_code == 403
    local = TestClient(app, client=("127.0.0.1", 5000))
    assert local.get("/api/hands/hand_landmarker.task").status_code == 404
    assert local.get("/api/hands/..%2Fjarvis.db").status_code == 404


@pytest.mark.parametrize("g,ok", [("rotate:12", True), ("rotate:-30.5", True), ("zoom:1.15", True), ("zoom:0.8", True),
                                  ("fist", True), ("rotate:", False), ("zoom:1e9", False), ("rotate:12;alert(1)", False),
                                  ("pan:3", False), ("zoom:12345", False)])
async def test_finger_gesture_values(rt, g, ok):
    from jarvis.server.handlers.workshop import hud_gesture

    q = rt.bus.subscribe()
    await hud_gesture(_C(rt), {"g": g})
    got = []
    while not q.empty():
        got.append(q.get_nowait())
    assert any(e["type"] == "hud_cmd" and e.get("gesture") == g for e in got) is ok


async def test_hands_status_handler_and_protocol(rt):
    from jarvis.server import handlers, ws
    from jarvis.server.handlers.workshop import hands_status

    c = _C(rt)
    await hands_status(c, {})
    assert c.sent[0][0] == "hands" and c.sent[0][1]["ready"] is False
    handlers.load()
    assert "hands_download" in handlers.LOCAL_ONLY and "hands_download" in handlers.SLOW
    assert {"hands_status", "hands_download", "toolmem_get", "toolmem_forget", "mine_check"} <= set(ws.CLIENT_TYPES)
    assert {"hands", "toolmem", "mine_check"} <= set(ws.SERVER_TYPES)
