"""OMEGA wave 22 (hardware incidents + site operations): USB tree and power problems, disk error log with heat map, the
read-only copy plan, the service report, hosting health, outage timeline, log explorer, deployment diff, backups.
On Windows the real probes run too."""
import json
import os
import sys
import time

import httpx
import pytest

from jarvis import hwops, tools

tools.load_builtin()

USB = {"controllers": [{"FriendlyName": "Intel USB 3.1 eXtensible Host Controller", "InstanceId": "PCI\\CTRL"}],
       "devices": [{"Name": "USB Root Hub (USB 3.0)", "Class": "USB", "Status": "OK", "Id": "USB\\ROOT", "Parent": "PCI\\CTRL", "Problem": 0},
                   {"Name": "Generic USB Hub", "Class": "USB", "Status": "OK", "Id": "USB\\HUB", "Parent": "USB\\ROOT", "Problem": 0},
                   {"Name": "Externí disk WD", "Class": "DiskDrive", "Status": "Error", "Id": "USB\\WD", "Parent": "USB\\HUB", "Problem": 43},
                   {"Name": "Myš", "Class": "HIDClass", "Status": "OK", "Id": "USB\\MOUSE", "Parent": "USB\\ROOT", "Problem": 0}],
       "events": [{"Id": 1, "ProviderName": "USBHUB3", "Time": "2026-10-25T10:00:00", "Text": "Port reset failed – power surge on the hub port"}]}

STORAGE = {"disks": [{"DeviceId": 0, "Name": "Samsung 980 PRO", "Bus": "NVMe", "Health": "Healthy", "Size": 1_000_204_886_016, "Temperature": 41,
                      "Wear": 3, "ReadUncorrected": 0, "PowerOnHours": 2100, "Firmware": "5B2QGXA7", "Serial": "S5GX"},
                     {"DeviceId": 1, "Name": "WDC WD10EZEX", "Bus": "SATA", "Health": "Warning", "Size": 1_000_204_886_016, "Temperature": 52,
                      "Wear": None, "ReadUncorrected": 14, "PowerOnHours": 41000, "Firmware": "01.01A01", "Serial": "WD-1"}],
           "events": [{"Id": 7, "ProviderName": "disk", "Time": "2026-10-20T08:00:00", "Text": "The device, \\Device\\Harddisk1\\DR1, has a bad block."},
                      *[{"Id": 153, "ProviderName": "disk", "Time": f"2026-10-2{i}T09:00:00",
                         "Text": f"The IO operation at logical block address 0x{lba:x} for Disk 1 (PDO name: \\Device\\000) was retried."}
                        for i, lba in enumerate([1_900_000_000, 1_900_100_000, 1_901_000_000])],
                      {"Id": 129, "ProviderName": "storahci", "Time": "2026-10-24T09:00:00", "Text": "Reset to device, \\Device\\RaidPort0, was issued."}],
           "system": {"Maker": "Dell Inc.", "Model": "OptiPlex 7080", "Serial": "ABC123", "Bios": "1.21.0", "Os": "Windows 11 Pro 10.0.22631", "RamGB": 16}}


@pytest.fixture
def fake_probe(monkeypatch):
    monkeypatch.setattr(hwops, "probe", lambda name, runner=None: {"usb_tree": USB, "storage": STORAGE}[name])


async def test_usb(rt, fake_probe):
    r = await tools.call("usb_check", {}, rt)
    assert r.data["problems"] == [{"device": "Externí disk WD", "code": 43, "meaning": hwops.PROBLEM_CODES[43], "power_suspect": True}]
    assert r.data["tree"][:3] == ["Intel USB 3.1 eXtensible Host Controller", "  USB Root Hub (USB 3.0)", "    Generic USB Hub"]
    assert "rozbočovač s vlastním napájením" in r.summary and len(r.data["power_events"]) == 1


async def test_disk_errors_and_heatmap(rt, fake_probe):
    r = await tools.call("disk_errors", {}, rt)
    wd = r.data["disks"][1]
    assert "14 neopravitelných chyb čtení" in wd["issues"] and any("operace se musela opakovat 3×" in i for i in wd["issues"])
    assert wd["heatmap"].count("·") == 39 and len(wd["heatmap"].rstrip("·")) >= 38 and r.data["disks"][0]["issues"] == []
    assert r.data["events_by_disk"]["1"]["vadný blok"] == 1


def test_heatmap():
    assert hwops.heatmap([0, 1, 2, 999], 1000, 10) == "█········░"


async def test_copy_plan_and_report(rt, fake_probe, tmp_path, monkeypatch):
    from jarvis import secutils

    monkeypatch.setattr(secutils, "rescue_plan", lambda rt: [{"folder": "C:\\Users\\a\\Documents", "bytes": 1e9, "files": 100, "newest": time.time()},
                                                             {"folder": "C:\\Users\\a\\Videos", "bytes": 500e9, "files": 10, "newest": 1}])
    r = await tools.call("disk_copy_plan", {"source_gb": 1000, "destination": str(tmp_path), "health": "Warning"}, rt)
    assert r.data["first_folders"] == ["C:\\Users\\a\\Documents"] or r.data["dest_free_gb"] > 520
    assert "robocopy" in r.summary and "/R:0" in r.summary and "chkdsk" in r.summary
    r = await tools.call("hardware_report", {"problem": "disk cvaká a PC zamrzá"}, rt)
    text = open(r.data["path"], encoding="utf-8").read()
    assert "OptiPlex 7080" in text and "ABC123" in text and "WDC WD10EZEX" in text and "disk cvaká" in text and "Externí disk WD" in text


@pytest.mark.skipif(sys.platform != "win32", reason="skutečné sondy jen na Windows")
async def test_real_windows_probes(rt):
    u = await tools.call("usb_check", {}, rt)
    d = await tools.call("disk_errors", {}, rt)
    # a virtual machine (CI) may have no USB controller at all; every device must still be listed exactly once
    assert u.ok and len(u.data["tree"]) == u.data["devices"] + (1 if u.data["unplaced"] else 0), u.data
    assert d.ok and d.data["disks"] and d.data["system"].get("Model") is not None


def fake_site(req):
    u = str(req.url)
    if "dns.google" in u:
        name, t = req.url.params["name"], req.url.params["type"]
        ans = {("good.cz", "A"): ["1.2.3.4"], ("good.cz", "MX"): ["10 mail.good.cz."], ("good.cz", "TXT"): ['"v=spf1 mx -all"'],
               ("_dmarc.good.cz", "TXT"): ['"v=DMARC1; p=none"'], ("bad.cz", "A"): ["5.6.7.8"], ("bad.cz", "MX"): ["10 mx.bad.cz."]}.get((name, t), [])
        return httpx.Response(200, json={"Answer": [{"data": a} for a in ans]})
    if req.url.host == "good.cz":
        if req.url.scheme == "http":
            return httpx.Response(301, headers={"location": "https://good.cz/"})
        return httpx.Response(200, text="ok", headers={k: "x" for k in hwops.SEC_HEADERS})
    if req.url.host == "bad.cz":
        return httpx.Response(503, text="down")
    return httpx.Response(404)


async def test_hosting_health_and_timeline(rt, monkeypatch):
    from jarvis import netdiag

    monkeypatch.setattr(netdiag, "tls_check", lambda d: {"valid": True, "days_left": 60} if d == "good.cz" else {"valid": True, "days_left": 5})
    rt.transport = httpx.MockTransport(fake_site)
    r = await tools.call("hosting_health", {"domain": "https://good.cz/"}, rt)
    assert r.data["up"] and not r.data["issues"] and "SPF a DMARC v pořádku" in r.summary
    r = await tools.call("hosting_health", {"domain": "bad.cz"}, rt)
    iss = " | ".join(r.data["issues"])
    assert not r.data["up"] and "chybí SPF" in iss and "chybí DMARC" in iss and "vyprší za 5 dní" in iss and "nepřesměruje" in iss
    rt.db.exec("UPDATE site_checks SET ts = ts - 3600 WHERE site='bad.cz'")
    from jarvis import hwops as h

    h.record_check(rt, "bad.cz", True, 200, 100)
    t = await tools.call("outage_timeline", {"domain": "bad.cz"}, rt)
    assert t.data["uptime_pct"] == 50.0 and t.data["outages"][0]["minutes"] >= 59 and not t.data["outages"][0]["ongoing"]


async def test_explore_logs(rt, tmp_path):
    (tmp_path / "app.log").write_text(
        "2026-10-25 10:00:01 INFO start\n2026-10-25 10:00:02 ERROR Connection to 10.0.0.5 failed after 3 tries\n"
        "2026-10-25 10:05:02 ERROR Connection to 10.0.0.7 failed after 5 tries\n2026-10-25 11:00:00 WARNING disk 91% full\n"
        "2026-10-26 09:00:00 ERROR Connection to 10.0.0.5 failed after 1 tries\n", encoding="utf-8")
    (tmp_path / "worker.log").write_text("2026-10-26 08:00:00 CRITICAL job 'import' crashed\nTraceback (most recent call last):\n", encoding="utf-8")
    r = await tools.call("explore_logs", {"path": str(tmp_path)}, rt)
    g = r.data["groups"]
    assert g[0]["level"] == "CRITICAL" and any(x["count"] == 3 and x["first"] == "2026-10-25 10:00:02" and x["last"] == "2026-10-26 09:00:00" for x in g)
    r = await tools.call("explore_logs", {"path": str(tmp_path), "level": "error", "since": "2026-10-26"}, rt)
    assert r.data["matched"] == 3


async def test_deploy_diff(rt, tmp_path):
    a, b = tmp_path / "v1", tmp_path / "v2"
    for d in (a, b):
        (d / "static").mkdir(parents=True)
    (a / "app.py").write_text("print(1)", encoding="utf-8")
    (b / "app.py").write_text("print(2)", encoding="utf-8")
    (a / "static" / "old.css").write_text("x", encoding="utf-8")
    (b / "static" / "new.css").write_text("y", encoding="utf-8")
    (a / ".env").write_text("DEBUG=true\nDB_PASSWORD=stare\nWORKERS=2\n", encoding="utf-8")
    (b / ".env").write_text("DEBUG=false\nDB_PASSWORD=nove\nWORKERS=2\n", encoding="utf-8")
    (a / "settings.json").write_text(json.dumps({"api": {"url": "http://a", "timeout": 5}}), encoding="utf-8")
    (b / "settings.json").write_text(json.dumps({"api": {"url": "http://b", "timeout": 5}}), encoding="utf-8")
    r = await tools.call("deploy_diff", {"before": str(a), "after": str(b)}, rt)
    assert r.data["added"] == ["static/new.css"] and r.data["removed"] == ["static/old.css"] and set(r.data["changed"]) == {"app.py", ".env", "settings.json"}
    assert r.data["config"][".env"] == {"DEBUG": ["true", "false"], "DB_PASSWORD": ["•••", "•••"]}
    assert r.data["config"]["settings.json"] == {"api.url": ['"http://a"', '"http://b"']} and "stare" not in r.summary


async def test_check_backups(rt, tmp_path):
    tmp_path = tmp_path / "zalohy"                                   # tmp_path itself also holds JARVIS_HOME
    tmp_path.mkdir()
    now = time.time()
    ages_h = [8 * 24, 7 * 24, 4 * 24, 3 * 24, 2 * 24 + 6, 30]          # a 3-day gap, and the newest is 30 h old
    for i, (size, age_h) in enumerate(zip([5000, 5100, 5050, 0, 5200, 1000], ages_h)):
        f = tmp_path / f"zaloha-{i}.zip"
        f.write_bytes(b"x" * size)
        os.utime(f, (now - age_h * 3600, now - age_h * 3600))
    r = await tools.call("check_backups", {"folder": str(tmp_path)}, rt)
    iss = " | ".join(r.data["issues"])
    assert "prázdné zálohy: zaloha-3.zip" in iss and "menší než obvykle" in iss and "vynechaná" in iss and "stará 30 h" in iss
