"""3.12 shared clipboard with pictures: a screenshot on the PC → the phone's clipboard; a copied photo → the PC's."""
import asyncio
import io
import time

from fastapi.testclient import TestClient
from PIL import Image

from jarvis.server.app import create_app

HOME = ("192.168.1.50", 5000)


def png(color="red"):
    b = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(b, "PNG")
    return b.getvalue()


def test_a_screenshot_on_the_pc_goes_to_the_phone_once(rt, monkeypatch):
    rt.phone.last_poll = time.time()
    rt.cfg.phone_link.clip_sync = True
    act = rt.activity
    seq, pic = [1], [None]
    monkeypatch.setattr(rt.platform, "clipboard_seq", lambda: seq[0], raising=False)
    monkeypatch.setattr(rt.platform, "clipboard_get", lambda: "", raising=False)
    monkeypatch.setattr(rt.platform, "clipboard_image_get", lambda: pic[0], raising=False)
    later = []
    monkeypatch.setattr(rt, "call_soon", lambda fn, *a: later.append(fn))
    act._clipboard(time.time())                               # first look only remembers
    seq[0], pic[0] = 2, png()
    act._clipboard(time.time())
    seq[0] = 3                                                # the same picture again (seq changed, content not)
    act._clipboard(time.time())
    assert len(later) == 1

    async def run():
        later[0]()
        await asyncio.sleep(0.2)
    asyncio.run(run())
    cmds = [c for c in rt.phone.queue if c["kind"] == "clip_image"]
    assert len(cmds) == 1 and rt.store.get(cmds[0]["aid"]).mime == "image/png"


def test_off_means_no_pictures_leave_the_pc(rt, monkeypatch):
    rt.cfg.phone_link.clip_sync = False
    later = []
    monkeypatch.setattr(rt, "call_soon", lambda fn, *a: later.append(fn))
    monkeypatch.setattr(rt.platform, "clipboard_image_get", lambda: png(), raising=False)
    rt.activity._clip_image(time.time())
    assert later == []


def test_a_photo_copied_on_the_phone_lands_in_the_pcs_clipboard(rt):
    rt.cfg.phone_link.clip_sync = True
    app = create_app(rt, manage_runtime=False)
    c = TestClient(app, client=HOME)
    h = {"Authorization": f"Bearer {rt.cfg.phone.token}"}
    att = c.post("/api/upload", files={"file": ("schranka.png", png("blue"), "image/png")}, headers=h).json()
    with c.websocket_connect(f"/ws?token={rt.cfg.phone.token}&client=mobile") as ws:
        ws.receive_json()
        ws.send_json({"type": "clip_from_phone", "attachment_id": att["id"]})
        ws.send_json({"type": "ping"})
        for _ in range(40):
            if ws.receive_json()["type"] == "pong":
                break
        for _ in range(50):                                    # the picture is checked first (a moment)
            if getattr(rt.platform, "clipboard_image", None):
                break
            time.sleep(0.05)
    assert rt.platform.clipboard_image == png("blue")
    later = []                                                 # …and it is not sent straight back to the phone
    rt.call_soon = lambda fn, *a: later.append(fn)
    rt.activity._clip_image(time.time())
    assert later == []
