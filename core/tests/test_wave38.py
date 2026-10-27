"""Wave 38: games – test scenes, concepts, logs, assets, Godot runs, mods, FPS by settings, exploits, voxels, settings."""
import json
import re
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from jarvis import gamedev, gameplus, tools


def test_godot_scene_is_consistent():
    lvl = gamedev.dungeon(3, 30, 20, 5)
    tscn = gameplus.godot_scene(lvl, 32, 2, 1)
    walls = len(re.findall(r'\[node name="Wall\d+" type="StaticBody2D"', tscn))
    subs = re.findall(r'\[sub_resource type="RectangleShape2D" id="(S\d+)"\]', tscn)
    refs = re.findall(r'shape = SubResource\("(S\d+)"\)', tscn)
    assert walls == len(subs) == len(refs) and set(subs) == set(refs)
    assert tscn.startswith(f"[gd_scene load_steps={len(subs) + 1} format=3]")
    assert tscn.count('type="Marker2D"') == 3 and '[node name="Exit" type="Area2D"' in tscn
    first_node = tscn.index("[node ")
    assert all(tscn.index(f'id="{s}"') < first_node for s in subs)          # sub-resources before nodes


def test_concept_board(tmp_path):
    r = gameplus.concept_board("poušť", tmp_path / "c.png", 5)
    assert Image.open(tmp_path / "c.png").size == (1024, 640) and len(r["palette"]) == 6 and "duny" in r["prompt"]
    with pytest.raises(ValueError):
        gameplus.concept_board("bažina", tmp_path / "x.png")


UNITY_LOG = """Initialize engine version: 2022.3.10f1 (Unity)
NullReferenceException: Object reference not set to an instance of an object
  at Player.Update () [0x00012] in Player.cs:42
NullReferenceException: Object reference not set to an instance of an object
Warning: shader fallback
Hitch detected: frame took 312.4ms
Failed to load texture 'Assets/tex/rock.png'
"""


def test_game_log():
    r = gameplus.game_log(UNITY_LOG)
    assert r["engine"] == "Unity" and r["counts"]["chyba"] == 2 and r["counts"]["zásek"] == 1
    assert r["top"][0]["kind"] == "chyba" and r["top"][0]["count"] == 2 and r["top"][0]["first_line"] == 2
    assert any(g["kind"] == "chybějící soubor" for g in r["top"])
    assert gameplus.game_log("Godot Engine v4.2\nSCRIPT ERROR: Invalid call")["engine"] == "Godot"


def test_assets(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tex").mkdir()
    (tmp_path / "scripts" / "player.gd").write_text('var t = load("res://tex/hero.png")')
    Image.new("RGB", (64, 64)).save(tmp_path / "tex" / "hero.png")
    Image.new("RGB", (100, 64)).save(tmp_path / "tex" / "unused bg copy.png")
    Image.new("RGB", (64, 64)).save(tmp_path / "tex" / "hero2.png")              # same pixels as hero.png
    r = gameplus.assets_report(tmp_path)
    assert r["kinds"]["textura"] == 3 and r["kinds"]["skript"] == 1
    assert "tex/unused bg copy.png" in r["unused"] and "tex/hero.png" not in r["unused"]
    assert any("unused bg copy.png" in x for x in r["not_power_of_two"])
    assert r["duplicates"] and set(r["duplicates"][0]) == {"tex/hero.png", "tex/hero2.png"}
    assert r["rename_plan"] == [{"from": "tex/unused bg copy.png", "to": "tex/unused_bg.png"}]


def test_godot_check_and_run(tmp_path, monkeypatch):
    out = "Godot Engine v4.2.1\nSCRIPT ERROR: Invalid call. Nonexistent function 'jump'\nERROR: Cannot open file 'res://music/theme.ogg'.\n"
    r = gameplus.godot_check(out, 0)
    assert not r["ok"] and len(r["errors"]) == 2 and r["missing"] == ["res://music/theme.ogg"]
    assert gameplus.godot_check("Godot Engine v4.2.1\n", 0)["ok"]
    (tmp_path / "project.godot").write_text("[application]")
    monkeypatch.setattr(gameplus, "godot_exe", lambda: "/bin/godot")
    seen = {}

    def runner(args, **kw):
        seen["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="Godot Engine v4\n", stderr="")
    assert gameplus.godot_run(tmp_path, 10, runner)["ok"] and "--headless" in seen["args"]
    monkeypatch.setattr(gameplus, "godot_exe", lambda: None)
    with pytest.raises(FileNotFoundError):
        gameplus.godot_run(tmp_path)


def _jar(path: Path, files: dict):
    with zipfile.ZipFile(path, "w") as z:
        for n, t in files.items():
            z.writestr(n, t)


def test_minecraft_mods(tmp_path):
    _jar(tmp_path / "sodium.jar", {"fabric.mod.json": json.dumps({"id": "sodium", "version": "0.5.8", "depends": {"minecraft": "~1.20.4", "fabricloader": ">=0.15"}})})
    _jar(tmp_path / "iris.jar", {"fabric.mod.json": json.dumps({"id": "iris", "version": "1.7", "depends": {"sodium": ">=0.5.8", "minecraft": "1.20.4"}})})
    _jar(tmp_path / "lithium.jar", {"fabric.mod.json": json.dumps({"id": "lithium", "version": "0.12", "depends": {"cloth-config": "*"}})})
    _jar(tmp_path / "sodium-old.jar", {"fabric.mod.json": json.dumps({"id": "sodium", "version": "0.4", "depends": {}})})
    _jar(tmp_path / "jei.jar", {"META-INF/mods.toml": 'modId="jei"\nversion="15.2"\n[[dependencies.jei]]\nmodId="forge"\nmandatory=true\nversionRange="[47,)"\n'})
    (tmp_path / "rozbity.jar").write_bytes(b"neni zip")
    r = gameplus.mods_report(tmp_path, "1.20.1")
    text = " ".join(r["problems"])
    assert r["count"] == 5 and r["unreadable"] == ["rozbity.jar"]
    assert "Míchají se zavaděče" in text and "sodium je tam 2×" in text and "cloth-config" in text
    assert "iris 1.7 chce Minecraft 1.20.4" in text and "sodium 0.5.8 chce Minecraft ~1.20.4" in text
    assert "iris potřebuje sodium" not in text
    assert gameplus._mc_ok(">=1.20", "1.20.1") and not gameplus._mc_ok("1.19.2", "1.20.1") and gameplus._mc_ok("[1.20,1.21)", "1.20.4")


def test_compare_settings():
    smooth = [10.0] * 600
    heavy = [14.0] * 590 + [60.0] * 10
    ultra = [25.0] * 600
    r = gameplus.compare_settings({"nízké": smooth, "vysoké": heavy, "ultra": ultra}, 60)
    assert r["recommended"] == "nízké" and r["runs"][2]["avg_fps"] == 40.0
    r2 = gameplus.compare_settings({"nízké": smooth, "střední": [12.0] * 600}, 60)
    assert r2["recommended"] == "střední"


def test_tampered_saves_and_speed_hacks():
    save = {"player": {"gold": 120, "hp": 80}, "inventory": ["meč", "lektvar"], "level": 3}
    v = gameplus.tampered_saves(save)
    changes = [x["change"] for x in v]
    assert "player.gold → obrovská hodnota" in changes and "inventory → předměty zkopírované 50×" in changes
    hacked = next(x for x in v if x["change"] == "player.hp → záporná hodnota")["data"]
    assert hacked["player"]["hp"] == -999999 and save["player"]["hp"] == 80          # the original is untouched
    rows = [{"player": "a", "t": 0, "x": 0, "y": 0}, {"player": "a", "t": 1, "x": 5, "y": 0}, {"player": "a", "t": 2, "x": 105, "y": 0},
            {"player": "b", "t": 0, "x": 0, "y": 0}, {"player": "b", "t": 1, "x": 3, "y": 4}]
    bad = gameplus.impossible_moves(rows, 10)
    assert len(bad) == 1 and bad[0]["player"] == "a" and bad[0]["speed"] == 100


def test_voxels():
    for kind in ("dům", "věž", "strom", "pyramida"):
        m = gameplus.voxel_model(kind, 9)
        assert len(m) > 50 and all(min(k) >= 0 for k in m)
        vox = gameplus.vox_bytes(m)
        assert vox[:4] == b"VOX " and struct.unpack("<I", vox[4:8])[0] == 150
        size = struct.unpack("<III", vox[20 + 12:20 + 24])
        n = struct.unpack("<I", vox[20 + 24 + 12:20 + 24 + 16])[0]
        assert n == len(m) and all(s >= 1 for s in size)
        assert gameplus.mcfunction(m).count("setblock") == len(m)
    with pytest.raises(ValueError):
        gameplus.voxel_model("hrad")


def test_settings_advice():
    hi = gameplus.settings_advice("NVIDIA GeForce RTX 4080", 16, 32, (2560, 1440), 165, 12)
    lo = gameplus.settings_advice("Intel(R) UHD Graphics 620", 0, 8, (1920, 1080), 60, 4)
    assert hi["tier"] > lo["tier"] and lo["preset"] == "velmi nízké"
    assert any("162" in t for t in hi["tips"]) and any("procesor" in t for t in lo["tips"])


async def test_tools(rt, tmp_path):
    r = await tools.call("godot_test_scene", {"seed": 2, "rooms": 5}, rt)
    assert r.ok and r.attachments[0].endswith(".tscn")
    r = await tools.call("voxel_build", {"kind": "věž", "size": 7}, rt)
    assert r.ok and "kostek" in r.summary and r.attachments[0].endswith(".vox")
    log = tmp_path / "Player.log"
    log.write_text(UNITY_LOG)
    r = await tools.call("game_log_check", {"file": str(log)}, rt)
    assert r.ok and "Unity" in r.summary
    save = tmp_path / "save.json"
    save.write_text(json.dumps({"gold": 10}))
    r = await tools.call("exploit_test", {"save": str(save)}, rt)
    assert r.ok and len(list(Path(r.data["folder"]).glob("*.json"))) == len(r.data["variants"])
    r = await tools.call("game_settings", {"game": "Cyberpunk"}, rt)
    assert r.ok and "Předvolba" in r.summary
    assert tools.REGISTRY["game_autotest"].danger
