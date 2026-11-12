"""3.12 JARVIS Link – our own Tailscale: the phone reaches the PC over mobile data, directly or through your relay,
always TLS end to end with the PC's certificate pinned."""
import asyncio
import hashlib
import json
import socket
import ssl
import shutil
import subprocess
import sys


from jarvis import secrets
from jarvis.link import relay_server, upnp
from jarvis.link.manager import RELAY_KEY, Gate
from jarvis.server.app import create_app

KEY = "k" * 24


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


async def tls_get(reader, writer, path, token=None, fp=None):
    """The phone: TLS over an already open stream, the certificate checked by its fingerprint only."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    await writer.start_tls(ctx, server_hostname="jarvis.link")
    der = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
    if fp is not None:
        assert hashlib.sha256(der).hexdigest() == fp          # pinned: anyone else's certificate is refused
    auth = f"Authorization: Bearer {token}\r\n" if token else ""
    writer.write(f"GET {path} HTTP/1.1\r\nHost: jarvis.link\r\n{auth}Connection: close\r\n\r\n".encode())
    await writer.drain()
    raw = await asyncio.wait_for(reader.read(), 10)
    writer.close()
    head, _, body = raw.partition(b"\r\n\r\n")
    return int(head.split()[1]), body


def setup_link(rt, tmp_path, relay_port=None):
    app = create_app(rt, manage_runtime=False)
    rt.asgi_app = app
    rt.cfg.link.enabled = True
    rt.cfg.link.upnp = False
    rt.cfg.link.port = free_port()
    if relay_port:
        secrets.set(RELAY_KEY, KEY)
        rt.cfg.link.relay_host = "127.0.0.1"
        rt.cfg.link.relay_port = relay_port
    return app


def test_phone_over_mobile_data_through_own_relay(rt, tmp_path):
    async def main():
        rport = free_port()
        relay, server = await relay_server.serve(KEY, "127.0.0.1", rport)
        setup_link(rt, tmp_path, rport)
        await rt.link.start()
        try:
            assert rt.link.listening and len(rt.link.fp) == 64
            for _ in range(100):
                if rt.link.agent and rt.link.agent.ready >= 1:
                    break
                await asyncio.sleep(0.05)
            assert rt.link.agent.ready >= 1                       # the PC waits at the relay

            info = rt.link.info()
            assert info["enabled"] and info["fp"] == rt.link.fp
            assert info["relay"] == {"host": "127.0.0.1", "port": rport, "key": KEY, "room": rt.cfg.link.room}

            async def via_relay(path, token=None):
                r, w = await asyncio.open_connection("127.0.0.1", rport)
                w.write(f"JRL1 {KEY} phone {rt.cfg.link.room}\n".encode())
                await w.drain()
                assert (await r.readline()).strip() == b"OK"
                return await tls_get(r, w, path, token, rt.link.fp)

            token = rt.cfg.phone.token
            for _ in range(8):                                     # again and again, every time
                assert (await via_relay("/api/health"))[0] == 200
            code, body = await via_relay("/api/link/info", token)
            assert code == 200 and json.loads(body)["fp"] == rt.link.fp
            code, _ = await via_relay("/api/link/info")             # no token, no answer
            assert code == 401
            # the relay agent connects from 127.0.0.1 – that must never count as "this PC"
            code, _ = await via_relay("/api/pairing", token)
            assert code == 403
            code, body = await via_relay("/api/health")
            assert code == 200 and json.loads(body)["name"] == "JARVIS"

            # a stranger without the relay's access key gets nothing
            r, w = await asyncio.open_connection("127.0.0.1", rport)
            w.write(f"JRL1 {'x' * 24} phone {rt.cfg.link.room}\n".encode())
            await w.drain()
            assert (await r.readline()).startswith(b"ERR auth")
            w.close()
            assert rt.link.status()["reachable"]
        finally:
            await rt.link.stop()
            server.close()
        assert not rt.link.listening

    asyncio.run(main())


def test_direct_port_is_never_local_and_needs_the_token(rt, tmp_path):
    async def main():
        setup_link(rt, tmp_path)
        await rt.link.start()
        try:
            port = rt.cfg.link.port
            r, w = await asyncio.open_connection("127.0.0.1", port)
            code, _ = await tls_get(r, w, "/api/pairing", rt.cfg.phone.token, rt.link.fp)
            assert code == 403                                       # pairing (the token!) only from the PC itself
            r, w = await asyncio.open_connection("127.0.0.1", port)
            code, body = await tls_get(r, w, "/api/phone/island", rt.cfg.phone.token)
            assert code == 200 and "kind" in json.loads(body)
            r, w = await asyncio.open_connection("127.0.0.1", port)
            code, _ = await tls_get(r, w, "/", None)
            assert code == 401                                       # not even the web page without the token
            # plain http on the link port goes nowhere
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(b"GET /api/health HTTP/1.1\r\nHost: x\r\n\r\n")
            await w.drain()
            assert not (await asyncio.wait_for(r.read(), 5)).startswith(b"HTTP/1.1 200")
            w.close()
        finally:
            await rt.link.stop()

    asyncio.run(main())


def test_gate_blocks_guessing():
    calls = []

    async def app(scope, receive, send):
        calls.append(scope["client"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    class RT:
        class cfg:
            class phone:
                token = "t" * 40
                devices = []
                guests = []

    g = Gate(RT, app)
    sent = []

    async def send(m):
        sent.append(m)

    async def run(tok):
        sent.clear()
        hdr = [(b"authorization", f"Bearer {tok}".encode())]
        await g({"type": "http", "path": "/api/x", "client": ("203.0.113.9", 1), "headers": hdr, "query_string": b""}, None, send)
        return sent[0]["status"]

    async def main():
        assert await run("t" * 40) == 200 and calls[-1] == ("link", 0)
        for _ in range(20):
            assert await run("wrong") == 401
        assert await run("t" * 40) == 429                         # 20 wrong tries → that address waits

    asyncio.run(main())


def test_ws_over_link_is_not_nearby(rt):
    """Approvals limited to the home network must not accept a phone that comes in over JARVIS Link."""
    from starlette.testclient import TestClient

    rt.cfg.phone.approve_nearby_only = True
    app = Gate(rt, create_app(rt, manage_runtime=False))
    c = TestClient(app, client=("192.168.1.20", 5000))           # even if the socket looked like home
    r = c.post("/api/phone/confirm", json={"id": "x", "approved": True},
               headers={"Authorization": f"Bearer {rt.cfg.phone.token}"})
    assert r.status_code == 403


DESC = b"""<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device>
<deviceType>urn:schemas-upnp-org:device:InternetGatewayDevice:1</deviceType><deviceList><device><deviceList><device>
<serviceList><service><serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>
<controlURL>/ctl/IPConn</controlURL></service></serviceList></device></deviceList></device></deviceList></device></root>"""


def soap_ok(action, **vals):
    inner = "".join(f"<{k}>{v}</{k}>" for k, v in vals.items())
    return (f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            f'<u:{action}Response xmlns:u="urn:x">{inner}</u:{action}Response></s:Body></s:Envelope>').encode()


def test_upnp_maps_the_port_and_spots_cgnat(rt, monkeypatch):
    assert upnp.control_url("http://192.168.1.1:5000/desc.xml", DESC) == (
        "http://192.168.1.1:5000/ctl/IPConn", "urn:schemas-upnp-org:service:WANIPConnection:1")
    calls = []
    ext = {"ip": "85.160.10.7"}

    def fake_http(method, url, body=None, headers=None, timeout=4.0):
        action = (headers or {}).get("SOAPAction", "").split("#")[-1].strip('"')
        calls.append((action, body))
        if action == "GetExternalIPAddress":
            return soap_ok(action, NewExternalIPAddress=ext["ip"])
        if action == "AddPortMapping" and b"<NewLeaseDuration>3600" in body:
            raise upnp.UpnpError("UPnP 725")                         # a router that only knows permanent mappings
        return soap_ok(action)

    monkeypatch.setattr(upnp, "_http", fake_http)
    gw = upnp.Gateway("http://192.168.1.1:5000/ctl/IPConn", "urn:schemas-upnp-org:service:WANIPConnection:1", "192.168.1.50")
    monkeypatch.setattr(upnp.Gateway, "find", classmethod(lambda cls, timeout=2.5: gw))
    rt.cfg.link.port = 8766

    st = asyncio.run(rt.link.map_router())
    assert st["state"] == "ok" and st["public_ip"] == "85.160.10.7" and st["public_port"] == 8766
    adds = [b for a, b in calls if a == "AddPortMapping"]
    assert len(adds) == 2 and b"<NewInternalClient>192.168.1.50<" in adds[1] and b"<NewLeaseDuration>0<" in adds[1]

    calls.clear()
    ext["ip"] = "100.72.4.1"                                          # the provider's shared address
    st = asyncio.run(rt.link.map_router())
    assert st["state"] == "cgnat" and not [a for a, _ in calls if a == "AddPortMapping"]
    assert upnp.classify("10.0.0.2") == "private" and upnp.classify("8.8.8.8") == "public"


def test_relay_install_script(rt, tmp_path):
    rt.cfg.link.relay_port = 8443
    script = rt.link.install_script()
    key = secrets.get(RELAY_KEY)
    assert len(key) >= 24 and f"'{key}'" in script and "--port 8443" in script
    assert "class Relay" in script and "systemctl enable --now jarvis-relay" in script
    f = tmp_path / "install.sh"
    f.write_bytes(script.encode("utf-8"))
    if sys.platform != "win32" and shutil.which("bash"):          # syntax check of the installer (Linux like the VPS)
        assert subprocess.run(["bash", "-n", str(f)]).returncode == 0
    assert rt.link.install_script().count(key) == 1                # the same key the next time
    st = rt.link.status()
    assert st["relay_key_set"] and key not in json.dumps(st)        # Settings never see the key itself


def test_relay_rejects_bad_handshakes():
    async def main():
        port = free_port()
        _, server = await relay_server.serve(KEY, "127.0.0.1", port)
        try:
            for line in (b"HELLO\n", f"JRL1 {KEY} admin abcdefabcdefabcd\n".encode(), f"JRL1 {KEY} pc ../etc\n".encode()):
                r, w = await asyncio.open_connection("127.0.0.1", port)
                w.write(line)
                await w.drain()
                assert (await r.readline()).startswith(b"ERR")
                w.close()
            r, w = await asyncio.open_connection("127.0.0.1", port)       # a phone and no PC waiting
            w.write(f"JRL1 {KEY} phone abcdefabcdefabcd\n".encode())
            await w.drain()
            assert (await asyncio.wait_for(r.readline(), 12)).startswith(b"ERR nopc")
        finally:
            server.close()

    asyncio.run(main())


def test_link_off_by_default(rt):
    assert rt.cfg.link.enabled is False
    asyncio.run(rt.link.start())
    assert not rt.link.listening and rt.link.info() == {"enabled": False}
    from jarvis import config

    assert "room" not in config.public_dump(rt.cfg)["link"]
