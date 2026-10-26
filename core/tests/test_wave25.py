"""OMEGA wave 25 (game development studio): seeded world, dialogue and quests, economy, loot odds, spawn fairness,
level generator, save validation, animation state machine, server capacity, telemetry, colour blindness, balance."""
import json
import math

from PIL import Image

from jarvis import gamedev, tools

tools.load_builtin()


async def test_world_is_seeded(rt):
    a = await tools.call("game_world", {"seed": 42, "size": 96}, rt)
    b = await tools.call("game_world", {"seed": 42, "size": 96}, rt)
    c = await tools.call("game_world", {"seed": 43, "size": 96}, rt)
    assert a.data["biomes"] == b.data["biomes"] and a.data["biomes"] != c.data["biomes"]
    assert abs(sum(a.data["biomes"].values()) - 100) < 0.5 and Image.open(a.data["path"]).size == (384, 384)
    x, y = a.data["spawn"]
    h = gamedev.fractal(42, 96, 96)
    assert h[y, x] >= 0.45                                              # the spawn is on land
    dry = await tools.call("game_world", {"seed": 1, "size": 64, "sea_level": 0}, rt)
    assert dry.data["land_pct"] == 100 and "voda" not in dry.data["biomes"]


TREE = {"start": "uvod", "nodes": {
    "uvod": {"text": "Ahoj {jmeno}, potřebuješ klíč?", "choices": [{"text": "Ano", "next": "klic", "set": "ma_klic"}, {"text": "Ne", "next": "konec"}]},
    "klic": {"text": "Tady máš.", "choices": [{"text": "Díky", "next": "konec"}, {"text": "Otevři dveře", "next": "dvere", "if": "ma_klic"}]},
    "dvere": {"text": "Dveře se otevřely.", "end": True},
    "konec": {"text": "Sbohem.", "end": True}}}


async def test_dialogue(rt, tmp_path):
    r = await tools.call("dialogue_check", {"tree": TREE, "variables": ["jmeno"], "play": [0, 1]}, rt)
    assert r.data["ok"] and [x["node"] for x in r.data["play"]["log"]] == ["uvod", "klic", "dvere"] and r.data["play"]["ended"]
    bad = json.loads(json.dumps(TREE))
    bad["nodes"]["klic"]["choices"].append({"text": "Tajné", "next": "nikde", "if": "zlodej"})
    bad["nodes"]["sirotek"] = {"text": "Nikdo sem nepřijde", "end": True}
    bad["nodes"]["smycka"] = {"text": "{hrac}", "choices": [{"text": "znovu", "next": "smycka2"}]}
    bad["nodes"]["smycka2"] = {"text": "a znovu", "choices": [{"text": "zpět", "next": "smycka"}]}
    bad["nodes"]["uvod"]["choices"].append({"text": "Hm", "next": "smycka"})
    bad["nodes"]["slepa"] = {"text": "…"}
    bad["nodes"]["konec"]["choices"] = [{"text": "?", "next": "slepa"}]
    (tmp_path / "hra").mkdir()
    (tmp_path / "hra" / "d.json").write_text(json.dumps(bad), encoding="utf-8")
    r = await tools.call("dialogue_check", {"file": str(tmp_path / "hra" / "d.json"), "variables": ["jmeno"]}, rt)
    d = r.data
    assert d["unreachable"] == ["sirotek"] and d["dead_ends"] == ["slepa"] and d["traps"] == ["smycka", "smycka2"]
    assert d["flags_never_set"] == ["zlodej"] and d["unknown_vars"] == ["hrac"] and any("nikde" in i for i in d["issues"])
    no = gamedev.dialogue_play(TREE, [1])
    assert no["log"][-1]["node"] == "konec" and no["ended"]
    assert gamedev.dialogue_play({"start": "uvod", "nodes": {"uvod": TREE["nodes"]["uvod"], "konec": TREE["nodes"]["konec"]}}, [0])["error"]


async def test_quests(rt):
    qs = [{"id": "q1", "level": 1, "xp": 100, "gold": 10, "gives": ["mapa"]},
          {"id": "q2", "requires": ["q1"], "level": 2, "xp": 150, "gold": 20, "needs": ["mapa"]},
          {"id": "q3", "level": 6, "xp": 50},
          {"id": "q4", "needs": ["drak_vejce"]},
          {"id": "q5", "requires": ["q6"]}, {"id": "q6", "requires": ["q5"]}]
    r = await tools.call("quest_check", {"quests": qs}, rt)
    assert [o["id"] for o in r.data["order"]] == ["q1", "q2"] and r.data["final_level"] == 3 and r.data["gold"] == 30
    why = {b["id"]: " ".join(b["why"]) for b in r.data["blocked"]}
    assert "úroveň 6" in why["q3"] and "drak_vejce nikdo nedá" in why["q4"] and "q6" in why["q5"]


async def test_economy(rt):
    r = await tools.call("economy_sim", {"sources": [{"name": "questy", "per_player_day": 100}], "sinks": [{"name": "opravy", "per_player_day": 40}], "days": 10}, rt)
    assert r.data["verdict"].startswith("inflace") and r.data["end"] == 600 and r.data["sink_to_balance"] == 60
    r = await tools.call("economy_sim", {"sources": [{"name": "questy", "per_player_day": 100}], "sinks": [{"name": "daň", "pct_of_wallet": 10}], "days": 400}, rt)
    assert r.data["steady_wallet"] == 1000 and abs(r.data["end"] - 900) < 1 and r.data["verdict"].startswith("stabilní")


async def test_loot(rt):
    r = await tools.call("loot_odds", {"table": [{"item": "meč", "weight": 1}, {"item": "nic", "weight": 99}], "tries": 100}, rt)
    m = r.data["items"][0]
    assert m["chance"] == 1 and m["expected_rolls"] == 100 and m["within"] == 63.4 and m["for_50"] == 69 and m["for_90"] == 230
    p = gamedev.loot([{"item": "meč", "weight": 1}, {"item": "nic", "weight": 99}], 10, pity=50)["items"][0]
    assert p["expected_rolls"] == round((1 - 0.99 ** 50) / 0.01, 2) and p["for_90"] == 50
    assert not (await tools.call("loot_odds", {"table": [{"item": "x", "weight": 0}]}, rt)).ok


async def test_spawns(rt):
    r = await tools.call("spawn_balance", {"spawns": [{"team": "A", "x": 0, "y": 0}, {"team": "B", "x": 100, "y": 0}],
                                           "objectives": [{"name": "střed", "x": 50, "y": 0}, {"name": "věž", "x": 30, "y": 0}],
                                           "min_enemy_distance": 150}, rt)
    assert r.data["distances"] == {"A": {"střed": 50, "věž": 30}, "B": {"střed": 50, "věž": 70}}
    assert [u["objective"] for u in r.data["unfair"]] == ["věž"] and r.data["unfair"][0]["advantage_pct"] == 57.1 and len(r.data["too_close"]) == 1


async def test_level_generator(rt):
    r = await tools.call("level_generator", {"seed": 7, "width": 60, "height": 40, "rooms": 9}, rt)
    d = r.data
    assert d["connected"] and d["rooms"] >= 5 and Image.open(d["path"]).size == (480, 320)
    rows = d["ascii"].split("\n")
    assert rows[d["start"][1]][d["start"][0]] == "S" and rows[d["exit"][1]][d["exit"][0]] == "E" and d["path_length"] >= abs(d["start"][0] - d["exit"][0])
    assert gamedev.dungeon(7, 60, 40, 9)["ascii"] == d["ascii"]                # same seed, same level


async def test_save_validate(rt, tmp_path):
    (tmp_path / "save").mkdir()
    old = {"player": {"level": 12, "gold": 500, "hp": 80}, "inventory": [{"id": "meč", "count": 1}, {"id": "lektvar", "count": 3}]}
    new = {"player": {"level": 120, "gold": 99999, "hp": -5}, "inventory": [{"id": "meč", "count": 1}, {"id": "meč", "count": "2"}]}
    (tmp_path / "save" / "a.json").write_text(json.dumps(old), encoding="utf-8")
    (tmp_path / "save" / "b.json").write_text(json.dumps(new), encoding="utf-8")
    rules = {"player.level": {"type": "int", "min": 1, "max": 99}, "player.hp": {"type": "number", "min": 0}, "player.name": {"type": "str"},
             "inventory[].id": {"type": "str", "unique": True}, "inventory[].count": {"type": "int", "min": 0}}
    r = await tools.call("save_validate", {"file": str(tmp_path / "save" / "b.json"), "rules": rules, "previous_file": str(tmp_path / "save" / "a.json")}, rt)
    e = " | ".join(r.data["errors"])
    assert "player.level: 120 je nad maximem 99" in e and "player.hp: -5 je pod minimem 0" in e and "player.name: chybí" in e
    assert "inventory[1].count: má být int, je str" in e and "'meč' je tam 2×" in e
    assert {j["path"] for j in r.data["suspicious"]} == {"player.gold", "player.hp"}
    ok = await tools.call("save_validate", {"file": str(tmp_path / "save" / "a.json"), "rules": {k: v for k, v in rules.items() if k != "player.name"}}, rt)
    assert ok.data["ok"]


async def test_animation_fsm(rt):
    r = await tools.call("animation_fsm", {"states": ["idle", "walk", "run", "jump", "dead", "swim"], "entry": "idle", "params": ["speed", "grounded"],
                                           "terminal": ["dead"],
                                           "transitions": [{"from": "idle", "to": "walk", "when": "speed > 0.1"}, {"from": "walk", "to": "run", "when": "speed > 3"},
                                                           {"from": "walk", "to": "idle", "when": "speed < 0.1"}, {"from": "run", "to": "walk", "when": "speed < 3"},
                                                           {"from": "walk", "to": "jump", "when": "speed > 3"}, {"from": "idle", "to": "jump", "when": "jump_pressed"},
                                                           {"from": "*", "to": "dead", "when": "hp <= 0"}]}, rt)
    d = r.data
    assert d["unreachable"] == ["swim"] and d["stuck"] == ["jump", "swim"] and d["conflicts"] == ["walk při „speed > 3“"]
    assert d["unknown_params"] == ["hp", "jump_pressed"] and "[*] --> idle" in d["mermaid"] and "dead --> [*]" in d["mermaid"]


async def test_server_capacity(rt):
    r = await tools.call("server_capacity", {"players": 100, "tick_rate": 30, "cpu_ms_per_player": 0.2, "bytes_per_entity": 40, "cores": 2}, rt)
    d = r.data
    assert d["cpu_ms_per_tick"] == 11 and d["uplink_mbps"] == 95.04 and d["max_players_network"] == 102 and d["bottleneck"] == "síť (upload)"
    near = gamedev.server_capacity(1000, 30, 0.02, 40, 1, 100, interest_radius_players=50)
    assert near["uplink_mbps"] == 1000 * 50 * 40 * 30 * 8 / 1e6 and near["max_players_cpu"] == 1616


async def test_telemetry(rt, tmp_path):
    (tmp_path / "t").mkdir()
    rows = ["player,event,level,time,x,y"]
    for p in range(10):
        rows += [f"p{p},start,L1,0,,", f"p{p},complete,L1,60,,"]
        if p < 6:
            rows += [f"p{p},start,L2,100,,", f"p{p},death,L2,130,{41 + p % 3},{12}"]
            if p < 3:
                rows += [f"p{p},complete,L2,200,,"]
            else:
                rows += [f"p{p},quit,L2,140,,"]
    (tmp_path / "t" / "tel.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    r = await tools.call("game_telemetry", {"file": str(tmp_path / "t" / "tel.csv")}, rt)
    lv = {x["level"]: x for x in r.data["levels"]}
    assert lv["L1"]["completion_pct"] == 100 and lv["L1"]["avg_time"] == 60 and lv["L2"]["completion_pct"] == 50 and lv["L2"]["quits"] == 3
    assert r.data["funnel"] == [{"level": "L1", "players": 10, "pct": 100.0}, {"level": "L2", "players": 6, "pct": 60.0}]
    assert r.data["hardest"] == "L2" and r.data["death_spots"][0] == {"x": 40, "y": 10, "deaths": 6}


async def test_colorblind(rt, tmp_path):
    r = await tools.call("colorblind_check", {"color_a": "#ff0000", "color_b": "#008000"}, rt)
    assert r.data["normal"] > 100 and r.data["protanopie"] < 15 and "protanopie" in r.summary
    (tmp_path / "ui").mkdir()
    im = Image.new("RGB", (200, 100), (255, 0, 0))
    im.paste((0, 128, 0), (100, 0, 200, 100))
    im.save(tmp_path / "ui" / "hud.png")
    r = await tools.call("colorblind_check", {"image": str(tmp_path / "ui" / "hud.png")}, rt)
    assert not r.data["ok"] and r.data["confusions"]["protanopie"] and not r.data["confusions"]["tritanopie"]
    assert len(r.attachments) == 3 and Image.open(r.data["images"]["deuteranopie"]).size == (200, 100)
    grey = gamedev.simulate_cvd(gamedev.np.array([[128, 128, 128]]), "deuteranopie")[0]
    assert all(abs(v - 128) <= 1 for v in grey)                       # greys stay grey


async def test_balance(rt):
    same = {"hp": 100, "damage": 10, "attack_speed": 1, "accuracy": 0.8}
    r = await tools.call("balance_sim", {"units": [{"name": "A", **same}, {"name": "B", **same}], "fights": 2000}, rt)
    assert abs(r.data["win_rate"]["A"] - r.data["win_rate"]["B"]) < 6                # mirror match ≈ even
    u = [{"name": "rytíř", "hp": 120, "damage": 12, "attack_speed": 1, "armor": 4},
         {"name": "lučištník", "hp": 70, "damage": 9, "attack_speed": 1.6, "accuracy": 0.85},
         {"name": "obr", "hp": 300, "damage": 30, "attack_speed": 0.5, "armor": 8}]
    r = await tools.call("balance_sim", {"units": u, "fights": 200}, rt)
    assert r.data["dominant"] == ["obr"] and r.data["weak"] == ["lučištník"] and math.isclose(r.data["dps"]["lučištník"], 12.24)
    assert r.data == (await tools.call("balance_sim", {"units": u, "fights": 200}, rt)).data      # seeded
