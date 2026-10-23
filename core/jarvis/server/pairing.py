"""Phone pairing: QR with LAN + Tailscale addresses and the token."""
from __future__ import annotations

import ipaddress
import io
import socket
import urllib.parse

import psutil

TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def local_ips() -> tuple[list[str], list[str]]:
    lan, ts = [], []
    for name, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family != socket.AF_INET:
                continue
            ip = ipaddress.ip_address(a.address)
            if ip.is_loopback or ip.is_link_local:
                continue
            if ip in TAILSCALE_NET or "tailscale" in name.lower():
                ts.append(a.address)
            elif ip.is_private:
                lan.append(a.address)
    lan.sort(key=lambda s: (not s.startswith("192.168."), s))
    return lan, ts


def pairing_info(token: str, port: int) -> dict:
    lan, ts = local_ips()
    hosts = lan + ts
    first = hosts[0] if hosts else "127.0.0.1"
    frag = urllib.parse.urlencode({"token": token, "hosts": ",".join(hosts), "port": port})
    url = f"http://{first}:{port}/mobile#{frag}"
    return {"url": url, "hosts": hosts, "lan": lan, "tailscale": ts, "port": port, "token": token,
            "qr_svg": qr_svg(url)}


def qr_svg(data: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()
