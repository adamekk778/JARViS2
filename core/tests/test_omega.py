"""OMEGA slice 1: missions with criteria, artifacts and evidence; restart recovery; read-only PC report; Skill Forge."""
import asyncio

from jarvis import pcreport, skillforge, tools
from jarvis.config import ProtocolStep
from jarvis.tasks import TaskManager, sha256_file


async def test_pc_report_mission_end_to_end(rt):
    q = rt.bus.subscribe()
    await rt.agent.run_steps("Zjisti stav počítače, připrav report a ulož ho", [ProtocolStep(tool="pc_health_report")], source="mission")
    t = rt.tasks.get(rt.tasks.list(limit=1)[0]["id"])
    assert t["status"] == "done", t["summary"]
    assert t["criteria"] == pcreport.CRITERIA
    assert [s["status"] for s in t["steps"]] == ["done"] * 4
    art = t["artifacts"][0]
    from pathlib import Path

    p = Path(art["path"])
    assert p.is_file() and sha256_file(p) == art["sha256"] and art["bytes"] == p.stat().st_size
    checks = [e for e in t["evidence"] if e["source"] == "ověření souboru"]
    assert len(checks) == 5 and all(e["ok"] for e in checks)
    assert len([e for e in t["evidence"] if e["source"] != "ověření souboru"]) == len(pcreport.SECTIONS)
    assert any(e["type"] == "task_update" and e["task"]["status"] == "verifying" for e in _drain(q))


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_report_verification_catches_a_changed_file(tmp_path):
    data = pcreport.collect(win={"error": "test"})
    p = pcreport.write_report(data, tmp_path)
    sha = sha256_file(p)
    assert all(ok for _, ok, _ in pcreport.verify(p, sha))
    p.write_text(p.read_text(encoding="utf-8").replace('id="disks"', 'id="x"'), encoding="utf-8")
    res = dict((c, ok) for c, ok, _ in pcreport.verify(p, sha))
    assert not res[pcreport.CRITERIA[1]] and not res[pcreport.CRITERIA[3]]
    # the parts that need Windows say why they are missing instead of inventing data
    unk = [s for s in data["sections"] if s["ok"] is None and not s["rows"]]
    assert unk and all(s["note"] for s in unk)


def test_windows_probe_is_read_only():
    assert pcreport.cmdlets_used() <= pcreport.ALLOWED_CMDLETS
    assert not any(c.startswith(("Set-", "Remove-", "Stop-", "Clear-", "New-", "Invoke-")) for c in pcreport.cmdlets_used())


def test_windows_probe_output_parsed():
    win = {"os": {"Caption": "Microsoft Windows 11 Pro", "Version": "10.0.26100", "BuildNumber": "26100", "LastBoot": "2026-10-25T08:00:00"},
           "cpu": {"Name": "AMD Ryzen 7 7800X3D", "NumberOfCores": 8}, "gpu": [{"Name": "RTX 4070", "DriverVersion": "32.0", "Status": "OK"}],
           "physical": [{"FriendlyName": "Samsung 990", "MediaType": "SSD", "Health": "Healthy", "Status": "OK", "Size": 1}],
           "events": [{"Name": "Disk", "Count": 3}], "shutdowns": 4, "hotfix": {"HotFixID": "KB5044284", "Date": "2026-10-10"},
           "startup": [{"Name": "Discord", "Location": "HKU"}], "problems": {"Name": "USB Mass Storage", "ConfigManagerErrorCode": 43}}
    data = pcreport.collect(win=win)
    s = {x["id"]: x for x in data["sections"]}
    assert ["Model", "AMD Ryzen 7 7800X3D"] in s["cpu"]["rows"]
    assert s["events"]["ok"] is False and ["Neočekávaná vypnutí (30 dní)", "4"] in s["events"]["rows"]
    assert s["devices"]["ok"] is False and ["· USB Mass Storage", "kód 43"] in s["devices"]["rows"]
    assert any(f["section"] == "devices" for f in data["findings"])


def test_restart_marks_unfinished_missions_interrupted(rt):
    tid = rt.tasks.begin("Dlouhá mise", "c1")
    rt.tasks._id = None                       # the process died here
    TaskManager(rt)                           # next start
    t = rt.tasks.get(tid)
    assert t["status"] == "interrupted" and "Zopakovat" in t["summary"]


async def test_skill_forge_from_mission_versions_and_rollback(rt):
    await rt.agent.run_steps("Kino", [ProtocolStep(tool="volume", args={"action": "set", "level": 20}),
                                      ProtocolStep(tool="set_dark_mode", args={"dark": True})])
    spec = tools.REGISTRY["save_mission_as_skill"]
    assert tools.is_dangerous(spec, {"name": "Kino"}, [], [], rt)
    assert tools.details_for(spec, {"name": "Kino"}, rt) == ["Název: Kino", "1. Hlasitost: 20 %", "2. Tmavý režim: zapnout"]
    r = await tools.call("save_mission_as_skill", {"name": "Kino"}, rt)
    assert r.ok and "verze 1" in r.summary
    proto = next(p for p in rt.cfg.stark.protocols if p.id == "kino")
    assert [s.tool for s in proto.steps] == ["volume", "set_dark_mode"]
    # a later edit = version 2, rollback = version 3 with the content of version 1
    items = [p.model_dump(mode="json") for p in rt.cfg.stark.protocols]
    next(p for p in items if p["id"] == "kino")["steps"][0]["args"]["level"] = 60
    rt.update_config({"stark": {"protocols": items}})
    assert [h["version"] for h in skillforge.history(rt, "kino")] == [2, 1]
    skillforge.rollback(rt, "kino", 1)
    h = skillforge.history(rt, "kino")
    assert h[0]["version"] == 3 and h[0]["note"] == "návrat na verzi 1"
    assert next(p for p in rt.cfg.stark.protocols if p.id == "kino").steps[0].args["level"] == 20


def test_manifest_lists_permissions_and_problems(rt):
    m = skillforge.manifest(rt, {"id": "x", "name": "X", "steps": [{"tool": "volume", "args": {}}, {"tool": "neexistuje"},
                                                                    {"ask": "shrň e-maily"}]})
    assert m["tools"] == ["volume", "neexistuje"] and m["ai_steps"] == 1
    assert "Nástroj neexistuje neexistuje." in m["problems"] and m["permissions"]
    rt.update_config({"permissions": {"apps": False}})
    assert any("vypnuté" in p for p in skillforge.manifest(rt, {"id": "y", "steps": [{"tool": "volume", "args": {}}]})["problems"])


async def test_mood_celebrates_a_verified_mission(rt):
    rt.mood.on_event({"type": "task_update", "task": {"id": "a", "status": "done", "artifacts": [{"path": "x"}],
                                                     "evidence": [{"ok": 1}]}})
    assert "joy" in rt.mood.until
    rt.mood.on_event({"type": "task_update", "task": {"id": "b", "status": "failed", "summary": "chyba"}})
    assert "error" in rt.mood.until
    await asyncio.sleep(0)
