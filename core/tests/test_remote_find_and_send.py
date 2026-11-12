"""The user's scenario: away from home, on the phone: "najdi mi na PC fakturu a pošli mi ji do telefonu"."""
from conftest import FakeRouter
from fastapi.testclient import TestClient

from jarvis.server.app import create_app

AWAY = ("100.70.1.2", 5000)          # the phone over Tailscale (not at home)


def test_find_a_file_on_the_pc_and_get_it_on_the_phone(rt, tmp_path):
    f = tmp_path / "Faktura-2026-11.pdf"
    f.write_bytes(b"%PDF-1.4 faktura")
    rt.router = FakeRouter([[("find_file", {"query": "faktura", "folder": str(tmp_path)})],
                            [("send_file", {"path": str(f)})],
                            "Našel jsem Faktura-2026-11.pdf a posílám ti ji."])
    app = create_app(rt, manage_runtime=False)
    c = TestClient(app, client=AWAY)
    token = rt.cfg.phone.token
    with c.websocket_connect(f"/ws?token={token}&client=mobile") as ws:
        assert ws.receive_json()["type"] == "welcome"
        ws.send_json({"type": "user_text", "text": "najdi mi na PC fakturu a pošli mi ji do telefonu"})
        done = None
        for _ in range(200):
            m = ws.receive_json()
            if m["type"] == "assistant_done":
                done = m
                break
    assert done and done["attachments"] and done["attachments"][0]["name"] == "Faktura-2026-11.pdf"
    r = c.get(done["attachments"][0]["url"], headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.content == b"%PDF-1.4 faktura"          # the phone downloads it
    assert c.get(done["attachments"][0]["url"]).status_code in (401, 403)     # nobody else can
