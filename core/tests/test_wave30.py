"""OMEGA wave 30 (looking after the PC): service dependencies, drivers before / after crashes and rollback, power plan
parsing and advice, recovery checklist, frame pacing, launch timing with a scripted platform, priority profiles on real
processes, the window layout over a restart and repeated crashes. On Windows the real probes run too."""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time

import psutil
import pytest

from jarvis import pccare, tools, workspace

tools.load_builtin()

SERVICES = {"services": [
    {"Name": "RpcSs", "Display": "Vzdálené volání procedur", "Status": "Running", "Start": "Automatic", "Requires": []},
    {"Name": "Dnscache", "Display": "Klient DNS", "Status": "Stopped", "Start": "Automatic", "Requires": ["RpcSs"]},
    {"Name": "WinHttp", "Display": "WinHTTP", "Status": "Running", "Start": "Manual", "Requires": ["Dnscache"]},
    {"Name": "Spooler", "Display": "Zařazování tisku", "Status": "Running", "Start": "Automatic", "Requires": ["RpcSs", "http"]},
    {"Name": "http", "Display": "HTTP", "Status": "Running", "Start": "Manual", "Requires": []},
    {"Name": "MyAgent", "Display": "Aktualizace", "Status": "Running", "Start": "Automatic", "Requires": "Dnscache"}]}


def test_services_graph(monkeypatch):
    r = pccare.services_graph(SERVICES, "tisk")
    assert r["focus"]["service"] == "Spooler" and r["focus"]["needs"] == ["RpcSs", "http"] and r["focus"]["needs_not_running"] == []
    stopped = r["stopped_automatic"][0]
    assert stopped["service"] == "Dnscache" and stopped["breaks"] == ["MyAgent"]       # WinHttp is manual: not "broken"
    assert r["most_needed"][0]["service"] == "RpcSs" and r["most_needed"][0]["dependents"] == 4
    rpc = pccare.services_graph(SERVICES, "RpcSs")["focus"]
    assert rpc["all_dependents"] == ["Dnscache", "MyAgent", "Spooler", "WinHttp"]
    with pytest.raises(ValueError):
        pccare.services_graph(SERVICES, "neexistuje")


async def test_service_tool(rt, monkeypatch):
    monkeypatch.setattr(pccare, "probe", lambda name, runner=None: SERVICES)
    r = await tools.call("service_dependencies", {}, rt)
    assert "Klient DNS → MyAgent" in r.summary
    r = await tools.call("service_dependencies", {"service": "winhttp"}, rt)
    assert "NEBĚŽÍ: Dnscache" in r.summary


STORE = """Microsoft PnP Utility

Published Name:     oem12.inf
Original Name:      nvlddmkm.inf
Provider Name:      NVIDIA
Class Name:         Display adapters
Class GUID:         {4d36e968-e325-11ce-bfc1-08002be10318}
Driver Version:     09/15/2026 32.0.15.6100
Signer Name:        Microsoft Windows Hardware Compatibility Publisher

Publikovaný název:  oem7.inf
Původní název:      nvlddmkm.inf
Název zprostředkovatele: NVIDIA
Název třídy:        Grafické adaptéry
Identifikátor GUID třídy: {4d36e968-e325-11ce-bfc1-08002be10318}
Verze ovladače:     05/02/2026 31.0.15.5222
Jméno podepisujícího: Microsoft Windows Hardware Compatibility Publisher

Published Name:     oem3.inf
Original Name:      rt640x64.inf
Provider Name:      Realtek
Class Name:         Net
Class GUID:         {4d36e972-e325-11ce-bfc1-08002be10318}
Driver Version:     01/10/2025 10.68.0.0
Signer Name:        Microsoft
"""


def _drivers(now):
    t = (now - dt.timedelta(days=20)).replace(microsecond=0)
    crash = [{"Time": (t + dt.timedelta(days=d)).isoformat(), "Id": 41, "Provider": "Kernel-Power"} for d in (1, 3, 4, 9)]
    crash += [{"Time": (t - dt.timedelta(days=25)).isoformat(), "Id": 1001, "Provider": "BugCheck"}]
    return {"installed": [{"Time": t.isoformat(), "Id": 20001, "Text": "Driver Management concluded the process to install driver oem12.inf for Device Instance ID PCI\\VEN_10DE&DEV_2504 with status 0x0."},
                          {"Time": (now - dt.timedelta(days=60)).isoformat(), "Id": 20001, "Text": "… install driver oem3.inf for Device Instance ID PCI\\VEN_10EC …"}],
            "signed": [{"Device": "NVIDIA GeForce RTX 3060", "Class": "DISPLAY", "Version": "32.0.15.6100", "Inf": "oem12.inf", "Id": "PCI\\VEN_10DE&DEV_2504"},
                       {"Device": "Realtek PCIe GbE", "Class": "NET", "Version": "10.68.0.0", "Inf": "oem3.inf", "Id": "PCI\\VEN_10EC"}],
            "crashes": crash, "store": STORE}


def test_driver_suspects():
    assert [s["original"] for s in pccare.parse_store(STORE)] == ["nvlddmkm.inf", "nvlddmkm.inf", "rt640x64.inf"]
    now = dt.datetime.now()
    r = pccare.driver_suspects(_drivers(now), now=now)
    s = r["suspects"][0]
    assert s["device"] == "NVIDIA GeForce RTX 3060" and s["crashes_before"] == 1 and s["crashes_after"] == 4 and s["can_roll_back"]
    assert s["older_in_store"] == ["31.0.15.5222 (2026-05-02)"]
    net = next(d for d in r["drivers"] if d["device"] == "Realtek PCIe GbE")
    assert not net["suspect"] and not net["can_roll_back"]


async def test_driver_tool(rt, monkeypatch):
    now = dt.datetime.now()
    monkeypatch.setattr(pccare, "probe", lambda name, runner=None: _drivers(now))
    r = await tools.call("driver_rollback_check", {}, rt)
    assert "Podezřelý: NVIDIA GeForce RTX 3060" in r.summary and "Vrátit změny ovladače" not in r.summary.split("jde vrátit:")[0]
    assert "Správce zařízení" in r.summary


LIST = """Existing Power Schemes (* Active)
-----------------------------------
Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (Vysoký výkon) *
Power Scheme GUID: a1841308-3541-4fab-bc81-f71556f20b4a  (Power saver)
"""


def _query(cur_ac, cur_dc):
    return ("Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (Vysoký výkon)\n  Subgroup GUID: 54533251-82be-4824-96c1-47b60b740d00  (Processor)\n"
            "    Minimum Possible Setting: 0x00000000\n    Maximum Possible Setting: 0x00000064\n    Possible Settings increment: 0x00000001\n"
            f"    Current AC Power Setting Index: 0x{cur_ac:08x}\n    Current DC Power Setting Index: 0x{cur_dc:08x}\n")


def test_power_parsing_and_advice(tmp_path):
    assert pccare.parse_plans(LIST)[1] == {"guid": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", "name": "Vysoký výkon", "active": True}
    vals = {"cpu_max": (80, 50), "cpu_min": (5, 5), "sleep_after": (1800, 0), "display_off": (0, 300), "usb_suspend": (1, 1),
            "hibernate_after": (0, 0), "pcie_aspm": (0, 1)}

    def runner(cmd, timeout):
        if cmd[1] == "/list":
            return 0, LIST, ""
        if cmd[1] == "/query":
            key = next(k for k, (sub, st) in pccare.POWER_SETTINGS.items() if st == cmd[4])
            return 0, _query(*vals[key]), ""
        out = cmd[cmd.index("/output") + 1]
        with open(out, "w", encoding="utf-8") as f:
            f.write("<BatteryReport><Batteries><Battery><DesignCapacity>50000</DesignCapacity><FullChargeCapacity>31000</FullChargeCapacity>"
                    "<CycleCount>612</CycleCount></Battery></Batteries></BatteryReport>")
        return 0, "", ""
    st = pccare.power_state(runner)
    assert st["settings"]["cpu_max"] == {"ac": 80, "dc": 50} and st["battery"] == {"design_mwh": 50000, "full_mwh": 31000, "health_pct": 62.0, "cycles": 612}
    a = pccare.power_advice(st)
    tips = " | ".join(a["tips"])
    assert a["laptop"] and "omezený na 80 %" in tips and "nikdy neuspí" in tips and "obrazovka se nikdy nevypne" in tips and "62 %" in tips
    assert a["minutes"]["sleep_after"] == {"ac": 30, "dc": 0} and a["active"]["name"] == "Vysoký výkon"


def test_recovery_checklist():
    r = pccare.recovery_checklist({"usb": [{"Model": "SanDisk Ultra", "GB": 28.7}, {"Model": "Kingston", "GB": 7.5}],
                                   "recovery_partition": [{"Disk": 0, "GB": 0.75}], "bitlocker": 1, "os": "Windows 11 Pro"})
    items = {i["item"]: i for i in r["items"]}
    assert r["ready"] and "SanDisk Ultra" in items["flash disk aspoň 16 GB"]["note"] and items["obnovovací oddíl Windows (WinRE)"]["ok"]
    assert "48místného klíče" in items["klíč pro obnovení BitLockeru"]["note"]
    none = pccare.recovery_checklist({"usb": [], "recovery_partition": {"error": "Access denied"}, "bitlocker": 0})
    assert not none["ready"] and next(i for i in none["items"] if "WinRE" in i["item"])["ok"] is None


async def test_frame_times(rt, tmp_path):
    d = tmp_path / "hra"
    d.mkdir()
    ms = [16.7] * 600
    for i in (100, 250, 400):
        ms[i] = 70.0                                                   # three hitches
    (d / "presentmon.csv").write_text("Application,ProcessID,MsBetweenPresents,MsBetweenDisplayChange\n" +
                                      "\n".join(f"game.exe,42,{v},{v}" for v in ms) + "\n", encoding="utf-8")
    r = await tools.call("frame_time_report", {"file": str(d / "presentmon.csv")}, rt)
    assert r.data["stutters"] == 3 and r.data["stutter_at_s"][0] == pytest.approx(100 * 16.7 / 1000, abs=0.1)
    assert r.data["low_01pct_fps"] == pytest.approx(1000 / 70, abs=0.1) and r.data["avg_fps"] == pytest.approx(1000 * 600 / sum(ms), abs=0.1)
    assert r.data["verdict"] == "trhané" and r.data["stutters_per_min"] == pytest.approx(18, abs=0.5) and len(r.attachments) == 1
    minute = [16.7] * 3600
    minute[1800] = 80.0
    assert pccare.frame_report(minute)["verdict"] == "občas zasekne"
    smooth = pccare.frame_report([16.6, 16.8] * 100)
    assert smooth["verdict"] == "plynulé" and smooth["stutters"] == 0
    fps = pccare.frame_times(["Time", "FPS"], [[str(i), "50"] for i in range(30)])
    assert fps[0] == 20
    with pytest.raises(ValueError):
        pccare.frame_times(["a", "b"], [["1", "2"]])


def test_launch_timing_with_scripted_windows(monkeypatch):
    """The window shows up 0.3 s (cold) / 0.1 s (warm) after start; what was started gets closed."""
    clock = {"t": 0.0}
    started = []

    class FakeProc:
        pid = 999999

    class Platform:
        def window_layout(self):
            if started and clock["t"] - started[-1] >= (0.3 if len(started) == 1 else 0.1):
                return [{"hwnd": len(started), "exe": "kalk.exe", "path": "C:\\Apps\\kalk.exe"}]
            return [{"hwnd": -1, "exe": "explorer.exe"}]

    def popen(args, **kw):
        started.append(clock["t"])
        return FakeProc()
    monkeypatch.setattr(subprocess, "Popen", popen)

    def sleep(s):
        clock["t"] += s
    r = pccare.measure_launch(Platform(), "C:\\Apps\\kalk.exe", runs=3, sleep=sleep, clock=lambda: clock["t"])
    assert r["cold_s"] == pytest.approx(0.3, abs=0.06) and r["warm_s"] == pytest.approx(0.1, abs=0.06) and len(r["runs"]) == 3


@pytest.mark.skipif(sys.platform == "win32", reason="nice hodnoty Linuxu; na Windows třídy priorit (test níže)")
def test_priority_profile_on_real_processes(tmp_path):
    exe = tmp_path / "jarvistestsync"
    shutil.copy(shutil.which("sleep"), exe)
    procs = [subprocess.Popen([str(exe), "30"]) for _ in range(2)]
    try:
        time.sleep(0.3)
        saved = {}
        r = pccare.apply_profile("vlastní", lower=["jarvistestsync"], saved=saved)
        assert sorted(c["pid"] for c in r["changed"]) == sorted(p.pid for p in procs)
        assert all(psutil.Process(p.pid).nice() == 10 for p in procs)
        back = pccare.restore_profile(saved)
        if os.geteuid() == 0:
            assert len(back["restored"]) == 2 and all(psutil.Process(p.pid).nice() == 0 for p in procs)
        else:                                       # a normal Linux user may lower priority but not raise it back
            assert sorted(back["denied"]) == ["jarvistestsync", "jarvistestsync"] and back["ended"] == 0
        assert saved == {}
    finally:
        for p in procs:
            p.kill()


async def test_performance_profile_tool(rt, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pccare, "apply_profile", lambda name, boost=None, lower=None, saved=None: (calls.append(name), saved.update({"1": {}}),
                                                                                                    {"profile": name, "changed": [{"pid": 1, "name": "OneDrive.exe", "to": "low"}], "denied": [], "saved": saved})[-1])
    monkeypatch.setattr(pccare, "restore_profile", lambda saved: (saved.clear(), {"restored": ["OneDrive.exe"], "ended": 0})[-1])
    r = await tools.call("performance_profile", {"profile": "hra"}, rt)
    assert "OneDrive.exe ↓" in r.summary and calls == ["hra"]
    assert "Vráceno 1" in (await tools.call("performance_profile", {"restore": True}, rt)).summary
    assert not (await tools.call("performance_profile", {"profile": "turbo"}, rt)).ok


def test_layout_over_restart(rt):
    rt.platform.window_layout = lambda: [{"title": "Rozpočet.xlsx", "exe": "EXCEL.EXE", "path": "C:\\Office\\EXCEL.EXE", "app": "Excel", "x": 0, "y": 0, "w": 800, "h": 600},
                                         {"title": "Mail", "exe": "OUTLOOK.EXE", "path": "C:\\Office\\OUTLOOK.EXE", "app": "Outlook", "x": 800, "y": 0, "w": 800, "h": 600}]
    assert pccare.autosave_layout(rt)
    ws = workspace.get(rt, pccare.AUTO)
    assert len(ws["windows"]) == 2
    assert pccare.restore_offer(rt, boot_time=ws["updated"] - 10) is None          # still the same session
    offer = pccare.restore_offer(rt, boot_time=ws["updated"] + 60)
    assert offer["apps"] == ["Excel", "Outlook"]
    assert pccare.restore_offer(rt, boot_time=ws["updated"] + 60) is None          # offered once per boot
    rt.platform.window_layout = lambda: [{"title": "x", "exe": "a.exe", "path": "C:\\a.exe"}]
    assert not pccare.autosave_layout(rt)


def test_repeated_crashes(rt):
    now = time.time()
    t = lambda h: dt.datetime.fromtimestamp(now - h * 3600).isoformat()  # noqa: E731
    errs = [{"App": "photoshop.exe", "Module": "nvoglv64.dll", "Time": t(h)} for h in (1, 3, 5)] + \
           [{"App": "excel.exe", "Module": "excel.exe", "Time": t(2)}, {"App": "photoshop.exe", "Module": "x", "Time": t(30)}]
    hits = pccare.repeated_crashes(errs, now=now)
    assert hits == [{"app": "photoshop.exe", "count": 3, "module": "nvoglv64.dll"}]
    seen = []
    rt.notify = lambda title, text, speak=True: seen.append(text)
    assert len(pccare.offer_crash_help(rt, errs, now=now)) == 1 and "nvoglv64.dll" in seen[0]
    assert pccare.offer_crash_help(rt, errs, now=now) == [] and len(seen) == 1               # once a day
    assert json.loads(rt.db.one("SELECT v FROM kv WHERE k='crash_offers'")["v"])["photoshop.exe"] == dt.date.today().isoformat()


@pytest.mark.skipif(sys.platform != "win32", reason="skutečné sondy jen na Windows")
async def test_real_windows_care(rt):
    s = await tools.call("service_dependencies", {"service": "Dnscache"}, rt)
    assert s.ok and s.data["services"] > 50 and s.data["focus"]["service"].lower() == "dnscache"
    d = await tools.call("driver_rollback_check", {}, rt)
    assert d.ok
    p = await tools.call("power_check", {}, rt)
    assert p.ok and p.data["plans"] and any(x["active"] for x in p.data["plans"])
    r = await tools.call("recovery_media_check", {}, rt)
    assert r.ok and r.data["items"]
    from jarvis.tools.platform.windows import WindowsPlatform

    launch = pccare.measure_launch(WindowsPlatform(), os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "notepad.exe"), runs=2)
    assert 0 < launch["cold_s"] < 30
