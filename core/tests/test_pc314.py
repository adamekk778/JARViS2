"""3.14 ovládání PC (návrhy 81–83, 86–90)."""
import json
import subprocess

import pytest

from jarvis import pcplus, tools

tools.load_builtin()


def done(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


def test_folder_sizes_and_treemap(tmp_path):
    (tmp_path / "big").mkdir()
    (tmp_path / "big" / "a.bin").write_bytes(b"x" * 50_000)
    (tmp_path / "big" / "sub").mkdir()
    (tmp_path / "big" / "sub" / "b.bin").write_bytes(b"x" * 30_000)
    (tmp_path / "small.txt").write_bytes(b"x" * 1000)
    items = pcplus.folder_sizes(tmp_path)
    assert items[0]["name"] == "big" and items[0]["bytes"] == 80_000
    rects = pcplus.squarify([6, 6, 4, 3, 2, 2, 1], 0, 0, 600, 400)
    area = sum(w * h for _x, _y, w, h in rects)
    assert len(rects) == 7 and abs(area - 600 * 400) < 1
    assert all(x >= -0.01 and y >= -0.01 and x + w <= 600.01 and y + h <= 400.01 for x, y, w, h in rects)
    svg = pcplus.treemap_svg(items, "test")
    assert svg.startswith("<svg") and "big" in svg


async def test_treemap_tool(rt, tmp_path):
    (tmp_path / "f.bin").write_bytes(b"x" * 5000)
    r = await tools.call("disk_treemap", {"path": str(tmp_path)}, rt)
    assert r.ok and r.attachments and "f.bin" in r.summary


WINGET = """Name               Id                     Version  Match         Source
-------------------------------------------------------------------------------
VLC media player   VideoLAN.VLC           3.0.21   Tag: vlc      winget
VLC UWP            XPDM1ZW6815MQM         Unknown                msstore
"""


def test_winget_parse_and_ledger(rt):
    rows = pcplus.parse_winget_search(WINGET)
    assert rows[0] == {"name": "VLC media player", "id": "VideoLAN.VLC", "version": "3.0.21", "source": "winget"}
    calls = []

    def runner(cmd, timeout):
        calls.append(cmd)
        return done("ok")
    assert pcplus.install(rt, "VideoLAN.VLC", runner)["ok"]
    assert [x["id"] for x in pcplus.ledger(rt)] == ["VideoLAN.VLC"]
    assert "--exact" in calls[0] and "--silent" in calls[0]
    assert pcplus.uninstall(rt, "VideoLAN.VLC", runner)["ok"] and pcplus.ledger(rt) == []
    assert tools.is_dangerous(tools.REGISTRY["app_install"], {"package_id": "x"}, [], [], rt)


def test_services_remember_the_original(rt):
    state = {"StartType": "Automatic"}
    cmds = []

    def runner(cmd, timeout):
        cmds.append(cmd[-1])
        if "Get-Service" in cmd[-1]:
            return done(json.dumps({"Name": "XblGameSave", "DisplayName": "Xbox", "Status": "Running", **state}))
        if "Set-Service" in cmd[-1]:
            state["StartType"] = cmd[-1].rsplit(" ", 1)[-1]
        return done("")
    assert pcplus.set_service(rt, "XblGameSave", "Manual", runner) == {"name": "XblGameSave", "was": "Automatic", "now": "Manual"}
    pcplus.set_service(rt, "XblGameSave", "Disabled", runner)
    r = pcplus.revert_service(rt, "xblgamesave", runner)
    assert state["StartType"] == "Automatic" and r["name"] == "XblGameSave"       # back to the ORIGINAL
    with pytest.raises(ValueError):
        pcplus.set_service(rt, "WinDefend", "Disabled", runner)
    with pytest.raises(ValueError):
        pcplus.revert_service(rt, "XblGameSave", runner)


def test_baseline_compare(rt):
    s = pcplus.save_baseline(rt, "před úklidem")
    rt.db.exec("UPDATE kv SET v=? WHERE k='pc_baseline'", (json.dumps({**s, "processes": s["processes"] + 50}),))
    c = pcplus.compare(rt)
    proc = next(r for r in c["rows"] if r["what"] == "processes")
    assert proc["better"] and c["label"] == "před úklidem"


def test_gpu_drivers_age():
    def runner(cmd, timeout):
        return done(json.dumps([{"Name": "NVIDIA GeForce RTX 4070", "DriverVersion": "32.0.15.6094", "DriverDate": "2025-01-10"},
                                {"Name": "Microsoft Basic Display Adapter", "DriverVersion": "1", "DriverDate": "2006-06-21"}]))
    rows = pcplus.gpu_drivers(runner, now=1.79e9)
    assert len(rows) == 1 and rows[0]["old"] and "nvidia.com" in rows[0]["page"]


def test_conflicts():
    def runner(cmd, timeout):
        return done(json.dumps({"bad": [{"Name": "USB Audio", "DeviceID": "USB\\A", "ConfigManagerErrorCode": 12}],
                                "alloc": [{"dev": "USB\\A", "res": "Win32_IRQResource:16"}, {"dev": "PCI\\B", "res": "Win32_IRQResource:16"},
                                          {"dev": "PCI\\C", "res": "Win32_IRQResource:17"}]}))
    c = pcplus.conflicts(runner)
    assert c["problems"][0]["meaning"].startswith("nemá dost") and c["shared"][0]["devices"] == ["PCI\\B", "USB\\A"]


def test_fps_from_presentmon():
    rows = ["Application,ProcessID,MsBetweenPresents"] + ["game.exe,1,16.6"] * 10 + ["game.exe,1,bad"]
    assert pcplus.fps_from_presentmon(rows) == pytest.approx(60.2, abs=0.2)
    assert pcplus.fps_from_presentmon(["x,y", "1,2"]) is None


def test_project_restores_its_layout(rt, monkeypatch):
    from jarvis import workspace

    monkeypatch.setattr(workspace, "list_all", lambda rt_: [{"name": "Kancelář", "project": "Eshop"}])
    called = []
    monkeypatch.setattr(rt, "submit", lambda coro: (called.append(coro), coro.close()))
    rt.knowledge.create_project("Eshop")
    rt.knowledge.switch("Eshop")
    assert called
