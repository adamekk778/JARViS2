"""3.12 Noční údržba PC: once a night, quiet PC: old temp files go, disks and Windows updates are checked."""
import asyncio
import os
import time

from jarvis import nightcare as nc


def _at(hour):
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, hour, 10, 0, 0, 0, -1))


def test_only_at_night_when_nobody_is_there(rt, monkeypatch):
    import psutil

    monkeypatch.setattr(psutil, "sensors_battery", lambda: None)
    idle = {"s": 3600.0}
    monkeypatch.setattr(rt.platform, "idle_seconds", lambda: idle["s"], raising=False)
    care = nc.NightCare(rt)
    assert care.due(_at(3)) and not care.due(_at(15))
    idle["s"] = 30
    assert not care.due(_at(3))                                   # someone is at the PC
    idle["s"] = 3600
    rt.cfg.general.night_care = False
    assert not care.due(_at(3))                                   # switched off
    rt.cfg.general.night_care = True
    care.last = {"day": time.strftime("%Y-%m-%d", time.localtime(_at(3)))}
    assert not care.due(_at(3))                                   # once a night


def test_cleans_only_old_temp_files_and_reports(rt, monkeypatch, tmp_path):
    from jarvis import powers, winupd

    tmp = tmp_path / "Temp"
    (tmp / "sub").mkdir(parents=True)
    old, fresh, keep = tmp / "old.tmp", tmp / "fresh.tmp", tmp_path / "Dokument.docx"
    for f in (old, fresh, keep):
        f.write_bytes(b"x" * 2048)
    week = time.time() - 8 * 86400
    os.utime(old, (week, week))
    os.utime(keep, (week, week))
    monkeypatch.setattr(powers, "temp_dirs", lambda: [tmp])
    monkeypatch.setattr(nc, "disk_health", lambda: [{"name": "Samsung SSD", "health": "Healthy"}, {"name": "Starý HDD", "health": "Warning"}])
    monkeypatch.setattr(winupd, "pending", lambda: {"updates": [{"title": "KB1"}, {"title": "KB2"}], "reboot": True})
    notes = []
    rt.notify = lambda title, body, **k: notes.append(title)
    r = asyncio.run(nc.NightCare(rt).run())
    assert not old.exists() and fresh.exists() and keep.exists()          # only the old temp file; nothing else
    assert r["files"] == 1 and r["freed"] == 2048 and r["disks_bad"] == ["Starý HDD"] and r["updates"] == 2
    assert notes == ["Disk hlásí problém"]
    s = nc.NightCare(rt).summary()                                         # read back from disk
    assert "uvolnila 2,0 kB" in s or "uvolnila 2 kB" in s
    assert "Starý HDD" in s and "2 aktualizací" in s and "restart" in s


def test_disk_list_from_powershell():
    assert nc.parse_disks('{"FriendlyName":"WD","HealthStatus":"Healthy","OperationalStatus":"OK"}') == [{"name": "WD", "health": "Healthy"}]
    assert len(nc.parse_disks('[{"FriendlyName":"A","HealthStatus":"Healthy"},{"FriendlyName":"B","HealthStatus":"Unhealthy"}]')) == 2
    assert nc.parse_disks("nesmysl") == []
