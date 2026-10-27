"""Wave 39: security, privacy, cloud."""
import subprocess
import time
from pathlib import Path

import pytest

from jarvis import mobileplus, secplus, tools

FT = lambda ts: int(ts * 1e7 + 116444736000000000)  # noqa: E731  unix → Windows FILETIME


def test_ps_probes_only_read():
    with pytest.raises(ValueError):
        secplus.run_ps("T 'x' { Remove-Item C:\\ -Recurse }", runner=lambda c, t: (0, "{}", ""))
    out = secplus.run_ps("T 'x' { Get-Date }", runner=lambda c, t: (0, '{"x": "2026"}', ""))
    assert out == {"x": "2026"}
    assert "error" in secplus.run_ps("T 'x' { Get-Date }", runner=lambda c, t: (None, "", ""))


def test_consent_store():
    now = time.time()
    rows = [{"Cap": "webcam", "App": "C:#Program Files#Zoom#bin#Zoom.exe", "Value": "Allow", "Start": FT(now - 60), "Stop": 0},
            {"Cap": "microphone", "App": "Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe", "Value": "Allow", "Start": FT(now - 86400), "Stop": FT(now - 86000)},
            {"Cap": "location", "App": "Weather_abc", "Value": "Deny", "Start": 0, "Stop": 0},
            {"Cap": "webcam", "App": "NonPackaged", "Value": "Allow"}]
    r = secplus.parse_consent(rows, now)
    cam = r["capabilities"]["kamera"]
    assert cam[0]["app"] == "Zoom.exe" and cam[0]["in_use"] and len(cam) == 1
    mic = r["capabilities"]["mikrofon"][0]
    assert mic["app"] == "WindowsSoundRecorder_8wekyb3d8bbwe" or mic["app"].startswith("WindowsSoundRecorder")
    assert not mic["in_use"] and mic["recent"]
    assert r["capabilities"]["poloha"][0]["allowed"] is False
    assert "Zoom.exe teď používá kamera" in r["flags"][0]


def test_incident_timeline():
    data = {"defender": [{"Id": 5001, "Time": "2026-10-20T10:00:00", "Text": "Real-time protection disabled"},
                         {"Id": 1116, "Time": "2026-10-21T09:00:00", "Text": "Trojan:Win32/X"}],
            "system": [{"Id": 7045, "Time": "2026-10-21T09:05:00", "Text": "A service was installed: Evil"}],
            "security": [{"Id": 4625, "Time": f"2026-10-22T03:{m:02d}:00", "Text": "An account failed to log on"} for m in range(12)],
            "tasks": {"error": "x"}}
    r = secplus.incident_timeline(data)
    assert r["serious"] == 2 and r["verdict"] == "vyžaduje pozornost"
    assert r["failed_logon_bursts"] == ["2026-10-22T03:00"]
    assert r["events"][0]["time"] == "2026-10-22T03:11:00" and r["events"][-1]["what"] == "Ochrana v reálném čase VYPNUTA"
    assert secplus.incident_timeline({"security": {"error": "Access denied"}})["notes"]


def test_ransomware_plan():
    sec = {"defender": {"AntivirusEnabled": True, "RealTimeProtectionEnabled": True, "IsTamperProtected": False}, "cfa": 0}
    r = secplus.ransomware_plan(sec, {"points": []}, [{"folder": "/home/x/Documents", "files": 10, "bytes": 2e9}],
                                {"last_backup": time.time() - 86400, "offline": False})
    assert r["score"] == 33 and "Řízený přístup ke složkám (ochrana dokumentů před ransomwarem)" in r["missing"]
    assert any("Documents" in s for s in r["steps"]) and r["data_gb"] == 2.0


def test_consents_and_guest(rt):
    cid = secplus.record_consent(rt, "Dočasné oprávnění: Shell", "30 min", True, "nastavení", time.time() + 1800)
    old = secplus.record_consent(rt, "Staré", "", True, "", time.time() - 10)
    assert [c["id"] for c in secplus.consents(rt)] == [cid]
    assert {c["id"] for c in secplus.consents(rt, True)} == {cid, old}
    assert secplus.revoke_consent(rt, cid) and not secplus.revoke_consent(rt, cid)
    g = mobileplus.add_guest(rt, "Petr", 1)
    rec = secplus.consents(rt)[0]
    assert rec["what"].startswith("Dočasný přístup hosta") and rec["scope"] == "Petr"
    assert mobileplus.guest_for(rt, g["token"])


async def test_revoking_guest_consent_removes_access(rt):
    g = mobileplus.add_guest(rt, "Eva", 2)
    cid = secplus.consents(rt)[0]["id"]
    r = await tools.call("consents", {"revoke": cid}, rt)
    assert r.ok and mobileplus.guest_for(rt, g["token"]) is None


async def test_project_isolation(rt, tmp_path):
    proj = tmp_path / "klient"
    proj.mkdir()
    (proj / "a.txt").write_text("uvnitř")
    (tmp_path / "tajne.txt").write_text("venku")
    rt.knowledge.create_project("Klient", str(proj))
    rt.knowledge.switch("Klient")
    r = await tools.call("read_text_file", {"path": str(tmp_path / "tajne.txt")}, rt)
    assert r.ok                                                    # isolation is off by default
    rt.cfg.limits.project_isolation = True
    r = await tools.call("read_text_file", {"path": str(tmp_path / "tajne.txt")}, rt)
    assert not r.ok and "oddělený" in r.summary
    assert (await tools.call("read_text_file", {"path": str(proj / "a.txt")}, rt)).ok
    rt.cfg.limits.project_perms = {"Klient": ["apps"]}
    r = await tools.call("read_text_file", {"path": str(proj / "a.txt")}, rt)
    assert not r.ok and "vypnuté" in r.summary
    rt.knowledge.switch("")
    assert (await tools.call("read_text_file", {"path": str(tmp_path / "tajne.txt")}, rt)).ok


def test_cloud_inventory_and_costs():
    def runner(args, **kw):
        if "describe-instances" in args:
            return subprocess.CompletedProcess(args, 0, stdout='[{"id": "i-1", "type": "t3.micro", "state": "running"}]', stderr="")
        return subprocess.CompletedProcess(args, 255, stdout="", stderr="Unable to locate credentials")
    r = secplus.cloud_inventory("aws", runner=runner)
    assert r["items"] == [{"kind": "ec2 describe-instances", "id": "i-1", "type": "t3.micro", "state": "running"}]
    assert r["errors"] == ["Unable to locate credentials"]
    with pytest.raises(ValueError):
        secplus.cloud_inventory("oracle")
    csv_text = "Date,Service,Cost\n" + "".join(f"2026-10-{d:02d},EC2,{10 + (d % 2)}\n2026-10-{d:02d},S3,1\n" for d in range(1, 20))
    csv_text += "2026-10-20,EC2,95\n2026-10-20,S3,1\n"
    c = secplus.cost_anomalies(csv_text)
    assert c["anomalies"][0]["service"] == "EC2" and c["anomalies"][0]["date"] == "2026-10-20" and len(c["anomalies"]) == 1
    assert list(c["totals"])[0] == "EC2"


def test_rollback_rehearsal(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (repo / "v.txt").write_text("1")
    g("add", ".")
    g("commit", "-qm", "one")
    g("tag", "v1")
    (repo / "v.txt").write_text("2")
    g("commit", "-qam", "two")
    g("tag", "v2")
    r = secplus.rollback_rehearsal(repo, "grep -q 1 v.txt")
    assert r["ok"] and r["to"] == "v1" and r["from"] == "v2"
    assert (repo / "v.txt").read_text() == "2"                  # the working copy is untouched
    bad = secplus.rollback_rehearsal(repo, "grep -q 2 v.txt", to="v1")
    assert not bad["ok"]
    assert len(subprocess.run(["git", "-C", str(repo), "worktree", "list"], capture_output=True, text=True).stdout.splitlines()) == 1


def test_search_query():
    r = secplus.optimize_query("Windows chyba 0x80070005 při aktualizaci")
    assert r["variants"][0].startswith('"0x80070005"')
    r2 = secplus.optimize_query("návod na výměnu baterie notebook pdf")
    assert any("filetype:pdf" in v for v in r2["variants"]) and any("OR" in v for v in r2["variants"])
    assert any("site:gov.cz" in v for v in secplus.optimize_query("dotace na tepelné čerpadlo")["variants"])


def test_untrusted_mcp_is_always_confirmed(rt):
    from jarvis.config import McpServer
    from jarvis.integrations.mcp_client import McpManager

    rt.cfg.integrations.mcp = [McpServer(name="cizi", command="x")]
    m = McpManager(rt)

    class T:
        name = "get_weather"
        description = "Počasí"
        annotations = type("A", (), {"readOnlyHint": True})()
        inputSchema = {"type": "object", "properties": {}}
    m._register("cizi", "mcp:cizi", None, T())
    assert tools.REGISTRY["mcp__cizi__get_weather"].danger
    rt.cfg.integrations.mcp = [McpServer(name="cizi", command="x", trusted=True)]
    m._register("cizi", "mcp:cizi", None, T())
    assert not tools.REGISTRY["mcp__cizi__get_weather"].danger
    tools.REGISTRY.pop("mcp__cizi__get_weather", None)


def test_nearby_only_flag_default():
    from jarvis.config import Config

    assert Config().phone.approve_nearby_only is False and Config().limits.project_isolation is False
    assert Path  # keep import
