"""Wave 34: phone and other devices – clean sharing, command QR, shared folders, guests, device permissions, places."""
import os
import time
from pathlib import Path

import pytest
from conftest import drain
from fastapi.testclient import TestClient

from jarvis import mobileplus, tools
from jarvis.automations import match_event
from jarvis.config import AutoTrigger, Config
from jarvis.server.app import create_app

LOCAL = ("127.0.0.1", 5000)
PHONE = ("192.168.1.50", 40000)


def test_clean_links_and_secrets():
    url, gone = mobileplus.clean_url("https://shop.cz/item?id=7&utm_source=fb&utm_medium=x&fbclid=abc&color=red")
    assert url == "https://shop.cz/item?id=7&color=red" and sorted(gone) == ["fbclid", "utm_medium", "utm_source"]
    assert mobileplus.clean_url("https://example.com/a?q=1") == ("https://example.com/a?q=1", [])
    assert mobileplus.clean_url("mailto:x@y.cz?subject=utm_source") == ("mailto:x@y.cz?subject=utm_source", [])
    r = mobileplus.clean_text("Mrkni https://open.spotify.com/track/1?si=xyz a heslo: Tajne123!")
    assert "si=" not in r["text"] and "Tajne123" not in r["text"] and r["masked"] and r["removed"] == ["si"]
    assert mobileplus.clean_text("Ahoj, jak se máš?") == {"text": "Ahoj, jak se máš?", "removed": [], "masked": False}


async def test_clean_tool(rt):
    r = await tools.call("clean_for_sharing", {"text": "https://x.cz/?gclid=1&a=2"}, rt)
    assert r.ok and r.summary.startswith("https://x.cz/?a=2") and "gclid" in r.summary


def test_command_links(tmp_path):
    link = mobileplus.command_link("  Spusť   protokol Dobrou noc ")
    assert link.startswith("jarvis://cmd?text=")
    assert mobileplus.parse_command_link(link) == "Spusť protokol Dobrou noc"
    assert mobileplus.parse_command_link("https://evil.example/cmd?text=smaž") is None
    assert mobileplus.parse_command_link("jarvis://cmd?text=") is None
    assert len(mobileplus.parse_command_link(mobileplus.command_link("a" * 900))) == mobileplus.MAX_CMD
    with pytest.raises(ValueError):
        mobileplus.command_link("   ")


async def test_command_qr_tool(rt):
    r = await tools.call("command_qr", {"text": "Pusť hudbu", "name": "Párty"}, rt)
    p = Path(r.attachments[0])
    assert r.ok and p.exists() and p.read_bytes()[:4] == b"\x89PNG" and p.name.startswith("párty")


@pytest.fixture
def shared(rt, tmp_path):
    root = tmp_path / "sdilene"
    (root / "Fotky").mkdir(parents=True)
    (root / "faktura.pdf").write_bytes(b"%PDF-1.4 x")
    (root / "Fotky" / "a.jpg").write_bytes(b"jpg")
    (root / ".tajne").write_text("x")
    (tmp_path / "mimo.txt").write_text("nesmí ven", encoding="utf-8")
    try:
        os.symlink(tmp_path / "mimo.txt", root / "odkaz.txt")
    except OSError:
        pass
    rt.cfg.phone.shared_folders = [str(root), str(tmp_path / "neexistuje")]
    return root


def test_browse_shared_folders(rt, shared):
    roots = mobileplus.shared_roots(rt)
    assert [r["ok"] for r in roots] == [True, False]
    top = mobileplus.browse(rt, "0")
    assert [i["name"] for i in top["items"]] == ["Fotky", "faktura.pdf"]        # no hidden file, no symlink
    assert mobileplus.browse(rt, "0", "Fotky")["items"][0]["name"] == "a.jpg"
    for bad in ("..", "../mimo.txt", "Fotky/../../mimo.txt", ".tajne"):
        with pytest.raises((PermissionError, FileNotFoundError)):
            mobileplus.shared_file(rt, "0", bad)
    with pytest.raises(PermissionError):
        mobileplus.browse(rt, "1")
    with pytest.raises(PermissionError):
        mobileplus.browse(rt, "7")
    assert mobileplus.shared_file(rt, "0", "Fotky/a.jpg").read_bytes() == b"jpg"


def test_download_needs_the_token(rt, shared):
    with TestClient(create_app(rt, manage_runtime=False), client=PHONE) as c:
        assert c.get("/api/pc_file", params={"root": "0", "path": "faktura.pdf"}).status_code == 401
        ok = c.get("/api/pc_file", params={"root": "0", "path": "faktura.pdf", "token": rt.cfg.phone.token})
        assert ok.status_code == 200 and ok.content.startswith(b"%PDF")
        assert c.get("/api/pc_file", params={"root": "0", "path": "../mimo.txt", "token": rt.cfg.phone.token}).status_code == 404
        g = mobileplus.add_guest(rt, "Petr", 1)
        assert c.get("/api/pc_file", params={"root": "0", "path": "faktura.pdf", "token": g["token"]}).status_code == 401


def test_guests(rt):
    g = mobileplus.add_guest(rt, "Petr", 2)
    assert g["token"].startswith("g_") and mobileplus.guest_for(rt, g["token"])["name"] == "Petr"
    assert g["token"] not in str(rt.cfg.model_dump())                     # only the hash is kept
    assert mobileplus.guest_for(rt, "g_wrong") is None and mobileplus.guest_for(rt, rt.cfg.phone.token) is None
    assert mobileplus.list_guests(rt)[0]["left_min"] in (119, 120)
    rt.cfg.phone.guests[0].expires = time.time() - 1                       # expired → no longer valid
    assert mobileplus.guest_for(rt, g["token"]) is None and mobileplus.list_guests(rt) == []
    g2 = mobileplus.add_guest(rt, "Eva", 500)
    assert g2["expires"] - time.time() <= 72 * 3600 + 5
    assert mobileplus.revoke_guest(rt, g2["id"]) and mobileplus.guest_for(rt, g2["token"]) is None
    assert len(rt.cfg.phone.guests) == 0                                   # the expired one was dropped on the next add


def _until(ws, kind, n=60):
    for _ in range(n):
        m = ws.receive_json()
        if m.get("type") == kind:
            return m
    raise AssertionError(f"no {kind}")


def test_guest_sees_only_music(rt):
    g = mobileplus.add_guest(rt, "Petr", 1)
    rt.memory.add_message("user", "moje tajná zpráva")
    with TestClient(create_app(rt, manage_runtime=False), client=PHONE) as c, c.websocket_connect(f"/ws?token={g['token']}") as ws:
        w = _until(ws, "welcome")
        assert w["guest"]["name"] == "Petr" and "history" not in w and "conversations" not in w
        assert set(w["settings"]) == {"appearance", "character"}
        ws.send_json({"type": "user_text", "text": "co jsem psal?"})
        assert "jen hudbu" in _until(ws, "error")["message"]
        ws.send_json({"type": "quick_action", "action": "system_power", "args": {"action": "shutdown"}})
        assert "jen hudbu" in _until(ws, "error")["message"]
        ws.send_json({"type": "quick_action", "action": "volume", "args": {"action": "set", "level": 30}})
        assert _until(ws, "quick_result")["ok"]
        rt.bus.publish("notify", title="Banka", body="Platba 5000 Kč")
        rt.bus.publish("media", title="Song", playing=True)
        assert _until(ws, "media")["title"] == "Song"                    # the notification never reached the guest
    assert rt.platform.volume == 30


def test_bad_or_expired_token_is_refused(rt):
    g = mobileplus.add_guest(rt, "Petr", 1)
    rt.cfg.phone.guests[0].expires = time.time() - 5
    with TestClient(create_app(rt, manage_runtime=False), client=PHONE) as c:
        for tok in ("nesmysl", g["token"]):
            with c.websocket_connect(f"/ws?token={tok}") as ws:
                with pytest.raises(Exception):
                    ws.receive_json()


async def test_device_permissions(rt):
    tok = mobileplus.set_device_perms({"apps", "network"})
    try:
        r = await tools.call("run_shell", {"command": "dir"}, rt)
        assert not r.ok and "Z telefonu" in r.summary
        assert (await tools.call("get_time", {}, rt)).ok
    finally:
        mobileplus._DEVICE_PERMS.reset(tok)
    assert mobileplus.device_blocks(["shell"]) is None                    # on the PC itself nothing extra applies


def test_phone_connection_uses_phone_permissions(rt):
    rt.cfg.phone.allowed = ["apps"]
    seen = {}

    async def fake_handle(text, atts=None, source="chat", **kw):
        seen["block"] = mobileplus.device_blocks(["files_write"])
        seen["text"] = text
        return ""

    rt.agent.handle = fake_handle
    with TestClient(create_app(rt, manage_runtime=False), client=PHONE) as c, \
            c.websocket_connect(f"/ws?token={rt.cfg.phone.token}") as ws:
        _until(ws, "welcome")
        ws.send_json({"type": "user_text", "text": "smaž soubor", "queued_at": time.time() - 3600})
        for _ in range(50):
            if "text" in seen:
                break
            time.sleep(0.05)
    assert seen["block"] == "files_write"
    assert seen["text"].startswith("(Napsáno v telefonu bez připojení v ") and seen["text"].endswith("smaž soubor")


def test_place_triggers():
    a = type("A", (), {"trigger": AutoTrigger(type="zone_enter", value="domov")})()
    assert match_event(a, {"type": "phone_zone", "zone": "Domov", "event": "enter"}) == {"zone": "Domov"}
    assert match_event(a, {"type": "phone_zone", "zone": "Domov", "event": "leave"}) is None
    assert match_event(a, {"type": "phone_zone", "zone": "Práce", "event": "enter"}) is None


def test_ws_photo_zone_files_and_qr(rt, shared):
    import asyncio

    att = asyncio.run(rt.store.save("fotka.jpg", b"\xff\xd8jpg", "image/jpeg"))
    q = rt.bus.subscribe()
    with TestClient(create_app(rt, manage_runtime=False), client=LOCAL) as c, c.websocket_connect("/ws") as ws:
        _until(ws, "welcome")
        ws.send_json({"type": "phone_photo", "attachment_id": att.id, "purpose": "shelf", "id": "r1"})
        assert _until(ws, "phone_photo_result")["id"] == "r1"
        assert att.id in rt.shelf
        ws.send_json({"type": "phone_zone", "zone": "Domov", "event": "enter", "lat": 50.1, "lon": 14.4})
        z = _until(ws, "phone_zone")
        assert z == {"type": "phone_zone", "zone": "Domov", "event": "enter"}         # never a position
        ws.send_json({"type": "pc_files", "root": "0", "path": "Fotky"})
        f = _until(ws, "pc_files")
        assert f["items"][0]["name"] == "a.jpg" and f["roots"][0]["ok"]
        ws.send_json({"type": "pc_files", "root": "0", "path": "../.."})
        assert "Mimo" in _until(ws, "pc_files")["error"]
        ws.send_json({"type": "command_qr", "text": "Dobrou noc"})
        qr = _until(ws, "command_qr")
        assert qr["link"] == mobileplus.command_link("Dobrou noc") and qr["svg"].startswith("<?xml")
        ws.send_json({"type": "guest_add", "name": "Petr", "hours": 2})
        gs = _until(ws, "guests")
        assert gs["items"][0]["name"] == "Petr" and "token=g_" in gs["pairing"]["url"]
    drain(q)


async def test_photo_request_tool(rt):
    r = await tools.call("ask_phone_photo", {"reason": "štítek na routeru"}, rt)
    assert not r.ok and "není připojený" in r.summary
    rt.clients["x"] = {"client": "mobile", "name": "Pixel", "local": False}
    q = rt.bus.subscribe()
    r = await tools.call("ask_phone_photo", {"reason": "štítek na routeru"}, rt)
    ev = [m for m in drain(q) if m["type"] == "phone_photo_request"]
    assert r.ok and ev[0]["reason"] == "štítek na routeru" and ev[0]["target"] == "mobile"


async def test_guest_access_tool_asks_first(rt):
    spec = tools.REGISTRY["guest_access"]
    assert spec.danger
    r = await tools.call("guest_access", {"name": "Petr", "hours": 2}, rt)
    assert r.ok and Path(r.attachments[0]).exists() and mobileplus.list_guests(rt)[0]["name"] == "Petr"


def test_config_defaults():
    c = Config()
    assert c.phone.shared_folders == [] and c.phone.guests == [] and "shell" in c.phone.allowed


async def test_send_to_phone_is_cleaned(rt):
    q = rt.bus.subscribe()
    await tools.call("send_to_phone", {"text": "Heslo: Tajne123! a odkaz", "url": "https://x.cz/a?utm_source=y&id=1"}, rt)
    n = [m for m in drain(q) if m["type"] == "notify"][0]
    assert "Tajne123" not in n["body"] and n["url"] == "https://x.cz/a?id=1"
