"""3.12 Zapnout PC z telefonu: this PC's network card for the phone + the relay's wake packet to the home address."""
import asyncio
import socket
from types import SimpleNamespace

from jarvis.link import relay_server

KEY = "k" * 24
ROOM = "ab" * 16
MAC = "a0b1c2d3e4f5"


def test_relay_wakes_the_home_it_last_saw(monkeypatch):
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    udp.settimeout(3)
    monkeypatch.setattr(relay_server, "WAKE_PORTS", (udp.getsockname()[1],))

    async def main():
        relay, server = await relay_server.serve(KEY, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        async def line(text):
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(text.encode())
            await w.drain()
            got = await asyncio.wait_for(r.readline(), 5)
            w.close()
            return got

        assert await line(f"JRL1 {KEY} wake {ROOM} {MAC}\n") == b"ERR nohome\n"     # the PC never came: nowhere to send
        r, w = await asyncio.open_connection("127.0.0.1", port)                  # the PC's idle connection from home
        w.write(f"JRL1 {KEY} pc {ROOM}\n".encode())
        await w.drain()
        assert await asyncio.wait_for(r.readline(), 5) == b"OK\n"
        w.close()
        assert await line(f"JRL1 {KEY} wake {ROOM} {MAC}\n") == b"OK\n"
        assert await line(f"JRL1 wrongwrongwrongwrong wake {ROOM} {MAC}\n") == b"ERR auth\n"
        assert await line(f"JRL1 {KEY} wake {ROOM} not-a-mac\n") == b"ERR auth\n"
        server.close()
        return relay

    relay = asyncio.run(main())
    data, _ = udp.recvfrom(200)
    assert data == b"\xff" * 6 + bytes.fromhex(MAC) * 16          # exactly one MAC: it can only wake that card
    from jarvis import network
    assert data == network.magic_packet("A0:B1:C2:D3:E4:F5")
    assert relay.homes[ROOM] == "127.0.0.1"
    udp.close()


def test_the_pcs_card_prefers_the_home_network(monkeypatch):
    import psutil

    from jarvis import wol

    A = lambda fam, addr, mask=None: SimpleNamespace(family=fam, address=addr, netmask=mask)  # noqa: E731
    link = getattr(psutil, "AF_LINK", 17)
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: {
        "Tailscale": [A(2, "100.70.1.2", "255.192.0.0"), A(link, "11-22-33-44-55-66")],
        "Wi-Fi": [A(2, "192.168.1.30", "255.255.255.0"), A(link, "AA-BB-CC-DD-EE-01")],
        "Ethernet": [A(2, "192.168.1.20", "255.255.255.0"), A(link, "A0-B1-C2-D3-E4-F5")],
    })
    monkeypatch.setattr(psutil, "net_if_stats", lambda: {})
    card = wol.nic()
    assert card == {"name": "Ethernet", "mac": MAC, "ip": "192.168.1.20", "broadcast": "192.168.1.255", "wifi": False}
    assert wol.nic("192.168.1.30")["wifi"] is True                # the one JARVIS is reachable on wins
    tips = wol.tips({"mac": MAC, "wifi": True, "armed": False, "away": False})
    assert any("Wi-Fi" in t for t in tips) and any("Správce zařízení" in t for t in tips) and any("relay" in t for t in tips)


def test_phone_gets_the_wake_info(rt, monkeypatch):
    from starlette.testclient import TestClient

    from jarvis import wol
    from jarvis.server.app import create_app

    monkeypatch.setattr(wol, "nic", lambda lan="": {"name": "Ethernet", "mac": MAC, "ip": "192.168.1.20", "broadcast": "192.168.1.255", "wifi": False})
    monkeypatch.setattr(wol, "armed", lambda: True)
    rt.link.router = {"state": "ok", "public_ip": "85.160.10.7", "wake": True}
    c = TestClient(create_app(rt, manage_runtime=False), client=("100.70.1.2", 5000))
    assert c.get("/api/phone/wake").status_code == 401
    r = c.get("/api/phone/wake", headers={"Authorization": f"Bearer {rt.cfg.phone.token}"}).json()
    assert r["mac"] == MAC and r["broadcast"] == "192.168.1.255" and r["away"] and r["public"] == "85.160.10.7"
