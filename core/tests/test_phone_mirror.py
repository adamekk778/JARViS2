"""3.12 Telefon na monitoru PC: the phone's pictures come in, the PC's clicks go back in the answer; only this PC sees it."""
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 500


def client(rt, host="100.70.1.2"):
    from starlette.testclient import TestClient

    from jarvis.server.app import create_app

    rt.phone_push = lambda kind, **d: rt.__dict__.setdefault("_pushed", []).append(kind) or True
    return TestClient(create_app(rt, manage_runtime=False), client=(host, 5000))


def frame(c, rt, body=JPEG, control="1"):
    return c.post("/api/phone/mirror/frame", content=body, headers={"Authorization": f"Bearer {rt.cfg.phone.token}",
                                                                    "X-W": "720", "X-H": "1560", "X-Control": control})


def test_pictures_in_clicks_back(rt):
    c = client(rt)
    m = rt.phone_mirror
    assert not m.input({"kind": "tap", "x": 0.5, "y": 0.5})            # nothing is mirrored: clicks go nowhere
    assert frame(c, rt).json() == {"inputs": [], "stop": False}
    assert m.active and m.size == (720, 1560) and m.control
    assert m.input({"kind": "tap", "x": 1.7, "y": -3})                  # clamped onto the screen
    assert m.input({"kind": "swipe", "x1": 0.5, "y1": 0.8, "x2": 0.5, "y2": 0.2, "ms": 99999})
    assert m.input({"kind": "text", "text": "ahoj"}) and m.input({"kind": "back"})
    assert not m.input({"kind": "shell", "cmd": "rm -rf /"})            # only the known kinds
    assert not m.input({"kind": "text", "text": ""})
    got = frame(c, rt, body=b"").json()["inputs"]                       # an empty "anything for me?" also collects
    assert got == [{"kind": "tap", "x": 1.0, "y": 0.0}, {"kind": "swipe", "x1": 0.5, "y1": 0.8, "x2": 0.5, "y2": 0.2, "ms": 1500},
                   {"kind": "text", "text": "ahoj"}, {"kind": "back"}]
    assert frame(c, rt).json()["inputs"] == []                          # each click goes once


def test_stop_from_the_pc_and_bad_pictures(rt):
    c = client(rt)
    assert frame(c, rt, body=b"<html>").status_code == 400              # not a picture
    assert frame(c, rt).status_code == 200
    rt.phone_mirror.stop()
    assert "mirror_stop" in rt._pushed
    assert frame(c, rt).json()["stop"] is True and not rt.phone_mirror.active
    assert c.post("/api/phone/mirror/frame", content=JPEG).status_code == 401   # only the paired phone


def test_only_this_pc_sees_the_phone(rt):
    phone = client(rt)
    frame(phone, rt)
    assert phone.get("/api/phone/mirror/latest", headers={"Authorization": f"Bearer {rt.cfg.phone.token}"}).status_code == 403
    pc = client(rt, "127.0.0.1")
    r = pc.get("/api/phone/mirror/latest?after=0")
    assert r.status_code == 200 and r.content == JPEG and float(r.headers["X-Ts"]) > 0
    assert pc.get(f"/api/phone/mirror/latest?after={r.headers['X-Ts']}").status_code == 204   # nothing newer: waits, then 204


def test_asking_the_phone_to_start(rt):
    from jarvis.phonemirror import PhoneMirror

    sent = []
    rt.phone_push = lambda kind, **d: sent.append(kind) or True
    assert PhoneMirror(rt).request() and sent == ["mirror_ask"]
