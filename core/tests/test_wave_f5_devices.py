"""Wave F5a: each phone its own key (184 / 402), revoke one (185 / 403 / 420), emergency lockdown (405)."""
from jarvis import mobileplus, tools

tools.load_builtin()


def _client(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    return TestClient(create_app(rt, manage_runtime=False), client=("192.168.1.77", 5000))


def _recv(ws, t):
    return next(x for x in iter(ws.receive_json, None) if x["type"] == t)


def test_phone_gets_own_key_and_can_be_revoked_alone(rt):
    master = rt.cfg.phone.token
    with _client(rt) as c:
        with c.websocket_connect(f"/ws?token={master}") as ws:
            ws.send_json({"type": "hello", "client": "mobile", "name": "Pixel", "caps": ["device_token"]})
            m = _recv(ws, "device_token")
        tok, did = m["token"], m["id"]
        assert tok.startswith("d_") and mobileplus.device_for(rt, tok)["name"] == "Pixel"
        assert all(d.token_hash != tok for d in rt.cfg.phone.devices)              # only the hash is stored
        assert c.get(f"/api/speedtest?mb=1&token={tok}").status_code == 200
        with c.websocket_connect(f"/ws?token={master}") as ws:                     # an old app (no caps) → no key piling up
            ws.send_json({"type": "hello", "client": "mobile", "name": "Old"})
            ws.send_json({"type": "ping", "t": 1})
            _recv(ws, "pong")
        assert len(rt.cfg.phone.devices) == 1
        tok2, d2 = mobileplus.issue_device(rt, "iPad")
        assert mobileplus.revoke_device(rt, did)
        assert mobileplus.device_for(rt, tok) is None and mobileplus.device_for(rt, tok2)["id"] == d2["id"]
        assert c.get(f"/api/speedtest?mb=1&token={tok}").status_code == 401
        assert c.get(f"/api/speedtest?mb=1&token={tok2}").status_code == 200
        assert c.get(f"/api/speedtest?mb=1&token={master}").status_code == 200    # the pairing code keeps working


def test_lockdown_revokes_everything(rt):
    tok, _ = mobileplus.issue_device(rt, "Telefon")
    old = rt.cfg.phone.token
    r = mobileplus.lockdown(rt)
    assert r["revoked"] == 1 and rt.cfg.phone.devices == [] and rt.cfg.phone.token != old and rt.cfg.limits.read_only
    assert mobileplus.device_for(rt, tok) is None
    rt.update_config({"limits": {"read_only": False}})


async def test_device_tools(rt):
    mobileplus.issue_device(rt, "Samsung Petr")
    r = await tools.REGISTRY["paired_devices"].func(rt)
    assert r.ok and "Samsung Petr" in r.summary
    spec = tools.REGISTRY["paired_devices"]
    assert spec.danger_if({"remove": "x"}) and not spec.danger_if({})
    r = await tools.REGISTRY["paired_devices"].func(rt, remove="samsung")
    assert r.ok and rt.cfg.phone.devices == []
    r = await tools.REGISTRY["paired_devices"].func(rt, remove="nic")
    assert not r.ok


def test_no_tool_name_is_defined_twice():
    """A second @tool with the same name silently replaces the first one – never let that happen."""
    import re
    from collections import Counter
    from pathlib import Path

    names = Counter(m for f in Path(tools.__file__).parent.glob("*.py")
                    for m in re.findall(r'@tool\("([a-z_0-9]+)"', f.read_text(encoding="utf-8")))
    assert [n for n, c in names.items() if c > 1] == []
