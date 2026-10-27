"""Wave 45: automatic backup, downloads / installs, screenshots, Bluetooth, voice tone, screen share, other PCs, music bars,
knowledge graph."""
import datetime as dt
import json
import os
import time

import httpx
import numpy as np
import pytest

from jarvis import sysplus, tools

tools.load_builtin()


def test_download_watch():
    w = sysplus.DownloadWatch(None)
    assert w.final_name("film.mp4.crdownload") == "film.mp4" and w.final_name("x.zip.part") == "x.zip" and w.final_name("a.pdf") is None
    assert w.step({"film.mp4.crdownload": 100, "stary.pdf": 5}, 0) == []
    assert w.step({"film.mp4.crdownload": 900, "stary.pdf": 5}, 5) == []
    assert w.step({"film.mp4": 1000, "stary.pdf": 5}, 10) == []                    # first sight of the final file → wait for it to settle
    done = w.step({"film.mp4": 1000, "stary.pdf": 5}, 15)
    assert done == [{"file": "film.mp4", "bytes": 1000, "seconds": 15}]
    assert w.step({"kopie.pdf": 10}, 20) == []                                     # files that just appear are not reported
    w.step({"zrus.zip.part": 1}, 30)
    assert w.step({}, 70) == [] and "zrus.zip" not in w.partial                    # cancelled


def test_installers():
    procs = [{"pid": 1, "name": "chrome.exe", "cmdline": []}, {"pid": 2, "name": "SteamSetup.exe", "cmdline": []},
             {"pid": 3, "name": "msiexec.exe", "cmdline": ["msiexec.exe", "/V"]}, {"pid": 4, "name": "msiexec.exe", "cmdline": ["msiexec", "/i", "x.msi"]},
             {"pid": 5, "name": "winget.exe", "cmdline": []}]
    assert sysplus.installers(procs) == {2: "SteamSetup.exe", 4: "msiexec.exe", 5: "winget.exe"}
    w = sysplus.InstallWatch()
    w.step({2: "SteamSetup.exe", 9: "x_setup.exe"}, 0)
    w.step({2: "SteamSetup.exe"}, 3)                                               # 9 flashed for 3 s → ignored
    assert w.step({}, 95) == [{"installer": "SteamSetup.exe", "seconds": 95}]


async def test_run_backup_and_tool(rt, tmp_path):
    src = tmp_path / "Dokumenty"
    src.mkdir()
    (src / "a.txt").write_text("ahoj")
    dst = tmp_path / "zaloha"
    r = await sysplus.run_backup(rt, {"source": str(src), "destination": str(dst)})
    assert r["ok"] and r["copied"] == 1 and (dst / "Dokumenty" / "a.txt").read_text() == "ahoj"
    assert json.loads(rt.db.one("SELECT v FROM kv WHERE k=?", (f"auto_backup:{src}",))["v"])["ok"]
    miss = await sysplus.run_backup(rt, {"source": str(tmp_path / "nic"), "destination": str(dst)})
    assert not miss["ok"] and miss["reason"] == "source"
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    t = await tools.call("auto_backup", {"source": str(src), "destination": str(dst), "time_of_day": "21:15"}, rt)
    assert t.ok and "21:15" in t.summary
    assert tools.is_dangerous(tools.REGISTRY["auto_backup"], {"action": "set"}, ctx=rt)
    lst = await tools.call("auto_backup", {"action": "list"}, rt)
    assert lst.ok and "Dokumenty" in lst.summary and "naposledy" in lst.summary
    job = [j for j in rt.scheduler.list() if j["kind"] == "backup"][0]
    (src / "b.txt").write_text("nove")
    await rt.scheduler._run(job)
    assert (dst / "Dokumenty" / "b.txt").exists()
    assert (await tools.call("auto_backup", {"action": "cancel"}, rt)).ok and not [j for j in rt.scheduler.list() if j["kind"] == "backup"]


def test_screenshots(tmp_path):
    shots = tmp_path / "Pictures" / "Screenshots"
    shots.mkdir(parents=True)
    desk = tmp_path / "Desktop"
    desk.mkdir()
    (shots / "Screenshot 2026-10-01.png").write_bytes(b"A" * 100)
    (shots / "kopie.png").write_bytes(b"A" * 100)
    (desk / "Snímek obrazovky 2026-05-01.png").write_bytes(b"B" * 50)
    (desk / "dovolena.jpg").write_bytes(b"C")
    (desk / "Screen Recording 1.mp4").write_bytes(b"D" * 10)
    old = time.time() - 200 * 86400
    os.utime(desk / "Snímek obrazovky 2026-05-01.png", (old, old))
    r = sysplus.find_screenshots(sysplus.screenshot_folders(tmp_path))
    assert r["count"] == 4 and r["clips"] == 1 and r["old"] == 1 and len(r["duplicates"]) == 1
    assert "dovolena.jpg" not in [i["name"] for i in r["items"]]
    plan = sysplus.organize_plan(r["items"], tmp_path / "Sorted")
    month = dt.datetime.fromtimestamp(old).strftime("%Y-%m")
    tos = [p["to"].replace("\\", "/") for p in plan]
    assert any(t.endswith(f"{month}/Snímek obrazovky 2026-05-01.png") for t in tos)
    assert any("/Klipy/Screen Recording 1.mp4" in t for t in tos)


def test_bluetooth_parse():
    rows = [{"Name": "WH-1000XM4", "Status": "OK", "Battery": 15}, {"Name": "Microsoft Bluetooth Enumerator", "Status": "OK"},
            {"Name": "MX Master 3", "Status": "Unknown", "Battery": 80}, {"Name": "Xbox Wireless Controller", "Status": "OK", "Battery": None},
            {"Name": "WH-1000XM4", "Status": "OK"}]
    d = sysplus.parse_bluetooth(rows)
    assert [x["name"] for x in d] == ["WH-1000XM4", "Xbox Wireless Controller", "MX Master 3"]
    assert d[0] == {"name": "WH-1000XM4", "connected": True, "battery": 15, "kind": "sluchátka"} and d[2]["kind"] == "myš" and not d[2]["connected"]


def tone(f0: float, seconds: float = 3.0, sr: int = 16000, amp: float = 0.3, syll: float = 3.0, vib: float = 0.0) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    freq = f0 * (1 + vib * np.sin(2 * np.pi * 1.5 * t))
    phase = 2 * np.pi * np.cumsum(freq) / sr
    env = 0.5 + 0.5 * np.sin(2 * np.pi * syll * t) ** 2
    return (amp * env * np.sin(phase)).astype(np.float32)


def test_voice_features_and_mood():
    f = sysplus.voice_features(tone(150), 16000)
    assert 140 < f["pitch_hz"] < 160 and f["speech_share"] > 0.5 and f["seconds"] == 3.0
    base = {"pitch_hz": 150, "pitch_spread": 0.08, "loudness_db": -16, "rate": 6.0}
    tense = sysplus.voice_mood({**f, "pitch_hz": 190, "rate": 9.0, "loudness_db": -10, "pitch_spread": 0.05}, base)
    tired = sysplus.voice_mood({**f, "pitch_hz": 125, "rate": 3.0, "loudness_db": -24, "pitch_spread": 0.03}, base)
    lively = sysplus.voice_mood({**f, "pitch_hz": 175, "rate": 6.0, "loudness_db": -16, "pitch_spread": 0.2}, base)
    assert tense["mood"] == "napětí / spěch" and tired["mood"] == "únava" and lively["mood"] == "nadšení"
    assert sysplus.voice_mood({**f, "seconds": 0.5}, base)["mood"] == "nevím"


def test_voice_mood_baseline_and_prompt(rt):
    for _ in range(6):
        sysplus.update_voice_mood(rt, (tone(150) * 32767).astype(np.int16), 16000)
    b = json.loads(rt.db.one("SELECT v FROM kv WHERE k='voice_baseline'")["v"])
    assert b["n"] == 6 and 140 < b["pitch_hz"] < 160


async def test_voice_mood_reaches_prompt(rt):
    rt.voice_mood = {"mood": "únava", "why": "x", "confidence": 0.6, "ts": time.time()}
    msgs, _ = await rt.agent._build_messages("ahoj", [], True, "")
    assert "zní: únava" in msgs[0]["content"]
    msgs, _ = await rt.agent._build_messages("ahoj", [], False, "")
    assert "zní:" not in msgs[0]["content"]                                   # typed text: no voice hint
    rt.voice_mood["ts"] = time.time() - 600
    msgs, _ = await rt.agent._build_messages("ahoj", [], True, "")
    assert "zní:" not in msgs[0]["content"]


async def test_screen_share(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    client = TestClient(create_app(rt, manage_runtime=False))
    hdr = {"Authorization": f"Bearer {rt.cfg.phone.token}", "host": "192.168.1.5:8765"}
    assert client.get("/api/screen/stream", headers=hdr).status_code == 403
    assert tools.is_dangerous(tools.REGISTRY["screen_share"], {"action": "start"}, ctx=rt)
    r = await tools.call("screen_share", {"minutes": 1}, rt)
    assert r.ok and rt.screen_share.active
    jpg = rt.screen_share.frame()
    assert jpg[:2] == b"\xff\xd8"
    agen = rt.screen_share.stream(fps=50)
    chunk = await agen.__anext__()
    assert chunk.startswith(b"--frame\r\nContent-Type: image/jpeg") and rt.screen_share.viewers == 1
    await agen.aclose()
    assert (await tools.call("screen_share", {"action": "stop"}, rt)).ok and not rt.screen_share.active
    assert client.get("/api/screen/stream", headers={"host": "192.168.1.5:8765"}).status_code == 401


async def test_peer_command_and_endpoint(rt, monkeypatch):
    from jarvis.server.app import create_app

    async def fake_handle(text, attachments=None, source="chat", **kw):
        assert source == "remote_pc" and "notebook" in kw["extra_system"]
        return f"hotovo: {text}"
    monkeypatch.setattr(rt.agent, "handle", fake_handle)
    app = create_app(rt, manage_runtime=False)
    transport = httpx.ASGITransport(app=app, client=("192.168.1.9", 5000))
    r = await sysplus.peer_command({"url": "http://192.168.1.5:8765", "me": "notebook"}, rt.cfg.phone.token, "pusť hudbu", transport)
    assert r == {"ok": True, "answer": "hotovo: pusť hudbu"}
    with pytest.raises(PermissionError):
        await sysplus.peer_command({"url": "http://192.168.1.5:8765"}, "spatny", "x", transport)
    st = await sysplus.peer_status({"url": "http://192.168.1.5:8765"}, transport)
    assert st["online"]


async def test_pc_link_tools(rt, monkeypatch):
    from jarvis import secrets

    vault = {}
    monkeypatch.setattr(secrets, "get", lambda n: vault.get(n, ""))
    monkeypatch.setattr(secrets, "set", lambda n, v: vault.__setitem__(n, v) if v else vault.pop(n, None))

    async def offline(peer, transport=None):
        return {"online": False}
    monkeypatch.setattr(sysplus, "peer_status", offline)
    r = await tools.call("pc_link", {"name": "Notebook", "url": "http://10.0.0.2:8765", "key": "k" * 20}, rt)
    assert r.ok and vault["peer:Notebook"] == "k" * 20 and "k" * 20 not in json.dumps(rt.cfg.model_dump())

    async def cmd(peer, token, text, transport=None):
        assert token == "k" * 20
        return {"ok": True, "answer": "Hudba hraje."}
    monkeypatch.setattr(sysplus, "peer_command", cmd)
    s = await tools.call("pc_send", {"pc": "notebook", "request": "pusť hudbu"}, rt)
    assert s.ok and "Hudba hraje." in s.summary
    assert (await tools.call("pc_link", {"action": "remove", "name": "Notebook"}, rt)).ok and "peer:Notebook" not in vault


def test_music_bars():
    b = sysplus.bars([0.1, 0.5, 0.9], 7, 1.0)
    assert len(b) == 7 and all(0.04 <= x <= 1 for x in b) and b[3] >= sorted(b)[3]
    assert sysplus.bars([], 5) == [0.0] * 5
    assert max(sysplus.bars([0.0, 0.0], 7)) <= 0.05


async def test_knowledge_graph(rt):
    from jarvis import intelplus

    items = [{"source": "kalendář", "ref": "1", "label": "x", "text": "Schůzka Jan Novák a Petr Malý k projektu Atlas"},
             {"source": "paměť", "ref": "2", "label": "y", "text": "Jan Novák jan@firma.cz projekt Atlas"},
             {"source": "chat", "ref": "3", "label": "z", "text": "Eva Zelená"}]
    rt.knowledge.create_project("Atlas", "")
    intelplus.build_index(rt, items)
    g = sysplus.knowledge_graph(rt)
    ids = [n["id"] for n in g["nodes"]]
    assert ids[0] in ("jan novak", "atlas") and "eva zelena" in ids
    e = {(x["a"], x["b"]): x["weight"] for x in g["edges"]}
    assert e[("atlas", "jan novak")] == 2
    focus = sysplus.knowledge_graph(rt, "eva")
    assert [n["id"] for n in focus["nodes"]] == ["eva zelena"] and not focus["edges"]
    assert sysplus.graph_svg(g).count("<circle") == len(g["nodes"])
    r = await tools.call("knowledge_graph", {}, rt)
    assert r.ok and r.attachments[0].endswith(".svg")
