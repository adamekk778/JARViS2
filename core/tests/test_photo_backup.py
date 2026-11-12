"""3.12 Záloha fotek z telefonu: the paired phone streams new photos/videos into Obrázky\\JARVIS Telefon\\YYYY-MM."""
import time
from urllib.parse import quote

import pytest


@pytest.fixture
def client(rt, tmp_path):
    from starlette.testclient import TestClient

    from jarvis.server.app import create_app

    rt.cfg.phone_link.photo_folder = str(tmp_path / "Fotky")
    rt.notify = lambda *a, **k: rt.__dict__.setdefault("_notes", []).append((a, k)) or 1
    return TestClient(create_app(rt, manage_runtime=False), client=("100.70.1.2", 5000))   # not this PC


def up(c, rt, name, data, taken=0, token=None, size=None):
    h = {"Authorization": f"Bearer {token or rt.cfg.phone.token}", "X-Name": quote(name), "X-Size": str(len(data) if size is None else size),
         "X-Taken": str(taken), "Content-Type": "application/octet-stream"}
    return c.post("/api/phone/backup", content=data, headers=h)


def test_photos_land_by_month_and_repeat_is_skipped(client, rt, tmp_path):
    taken = int(time.mktime((2026, 7, 14, 12, 0, 0, 0, 0, -1)) * 1000)
    r = up(client, rt, "IMG_20260714.jpg", b"\xff\xd8photo" * 100, taken)
    assert r.status_code == 200 and r.json()["saved"] == "IMG_20260714.jpg"
    f = tmp_path / "Fotky" / "2026-07" / "IMG_20260714.jpg"
    assert f.read_bytes() == b"\xff\xd8photo" * 100
    assert abs(f.stat().st_mtime - taken / 1000) < 2                     # the photo keeps its date
    assert up(client, rt, "IMG_20260714.jpg", b"\xff\xd8photo" * 100, taken).json()["skipped"]
    # the phone asks first, so it only sends what is missing
    have = client.post("/api/phone/backup/have", headers={"Authorization": f"Bearer {rt.cfg.phone.token}"},
                       json={"items": [{"name": "IMG_20260714.jpg", "size": 700, "taken": taken},
                                       {"name": "IMG_new.jpg", "size": 10, "taken": taken}]}).json()["have"]
    assert have == [True, False]
    # a different photo with the same name is kept too
    r = up(client, rt, "IMG_20260714.jpg", b"other", taken)
    assert r.json()["saved"] == "IMG_20260714 (2).jpg"
    assert rt.photo_backup.status()["count"] == 2
    st = client.post("/api/phone/backup/done", json={"sent": 2}, headers={"Authorization": f"Bearer {rt.cfg.phone.token}"}).json()
    assert st["count"] == 2 and len(rt._notes) == 1 and rt._notes[0][1]["speak"] is False     # one quiet note per batch


def test_only_the_paired_phone_and_only_media(client, rt, tmp_path):
    assert up(client, rt, "a.jpg", b"x", token="wrong").status_code == 401
    assert up(client, rt, "setup.exe", b"MZ").status_code == 415                # not a photo or a video
    assert up(client, rt, "a.jpg", b"xx", size=1).status_code == 400            # longer than announced
    assert up(client, rt, "b.mp4", b"xx", size=5).status_code == 400            # cut off → nothing left behind
    assert not list((tmp_path / "Fotky").rglob("*.part")) and not list((tmp_path / "Fotky").rglob("b.mp4"))


def test_names_cannot_escape_the_folder(client, rt, tmp_path):
    from jarvis.photobackup import safe_name

    assert safe_name("../../Windows/evil.jpg") == "evil.jpg"
    assert safe_name("..\\..\\x.JPG") == "x.jpg"
    assert safe_name("CON.jpg") == "foto_CON.jpg"
    assert safe_name('a<b>:c?.png') == "a_b__c_.png"
    r = up(client, rt, "../../../escape.jpg", b"data")
    assert r.status_code == 200
    assert not (tmp_path / "escape.jpg").exists()
    assert list((tmp_path / "Fotky").rglob("escape.jpg"))


def test_full_disk_is_refused(client, rt, monkeypatch):
    import shutil
    from collections import namedtuple

    U = namedtuple("U", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: U(10, 10, 5))
    r = up(client, rt, "big.jpg", b"x" * 100)
    assert r.status_code == 507 and "místo" in r.json()["detail"]


def test_default_folder_is_pictures(rt):
    rt.cfg.phone_link.photo_folder = ""
    assert rt.photo_backup.folder().parts[-2:] == ("Pictures", "JARVIS Telefon")
    rt.cfg.phone_link.photo_folder = "relative/path"                           # only a full path counts
    assert rt.photo_backup.folder().parts[-1] == "JARVIS Telefon"
