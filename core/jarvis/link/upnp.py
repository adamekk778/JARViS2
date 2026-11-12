"""Ask the home router to open JARVIS Link's port (UPnP IGD) and find the home's public address.

Plain SSDP + SOAP, no extra package. Nothing is opened unless JARVIS Link is switched on, and the mapping is removed
when it is switched off. Behind CGNAT (the router itself has no public address – common with mobile/fixed-wireless
internet) a direct connection is impossible; the relay is then the way.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
import urllib.parse
import xml.etree.ElementTree as ET

log = logging.getLogger(__name__)

SSDP = ("239.255.255.250", 1900)
SEARCH_TARGETS = ("urn:schemas-upnp-org:device:InternetGatewayDevice:1",
                  "urn:schemas-upnp-org:service:WANIPConnection:1",
                  "urn:schemas-upnp-org:device:InternetGatewayDevice:2")
SERVICES = ("urn:schemas-upnp-org:service:WANIPConnection:2", "urn:schemas-upnp-org:service:WANIPConnection:1",
            "urn:schemas-upnp-org:service:WANPPPConnection:1")
CGNAT = ipaddress.ip_network("100.64.0.0/10")
DESCRIPTION = "JARVIS Link"


class UpnpError(Exception):
    pass


def discover(timeout: float = 2.5) -> list[str]:
    """LOCATION urls of the gateways that answer (usually one: the router)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    s.settimeout(timeout)
    found: list[str] = []
    try:
        for st in SEARCH_TARGETS:
            msg = (f"M-SEARCH * HTTP/1.1\r\nHOST: {SSDP[0]}:{SSDP[1]}\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\n"
                   f"ST: {st}\r\n\r\n")
            s.sendto(msg.encode(), SSDP)
        while True:
            try:
                data, _ = s.recvfrom(4096)
            except (socket.timeout, OSError):
                break
            m = re.search(rb"^location:\s*(\S+)", data, re.I | re.M)
            if m:
                loc = m.group(1).decode(errors="replace")
                if loc not in found:
                    found.append(loc)
    finally:
        s.close()
    return found


def _http(method: str, url: str, body: bytes | None = None, headers: dict | None = None, timeout: float = 4.0) -> bytes:
    import httpx

    with httpx.Client(timeout=timeout, trust_env=False) as c:      # the router is on the LAN: never via a proxy
        r = c.request(method, url, content=body, headers=headers or {})
    if r.status_code >= 400:
        err = re.search(rb"<errorCode>(\d+)</errorCode>", r.content)
        raise UpnpError(f"UPnP {err.group(1).decode() if err else r.status_code}")
    return r.content


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def control_url(location: str, xml: bytes) -> tuple[str, str] | None:
    """(control url, service type) of the WAN connection service in a gateway's description."""
    root = ET.fromstring(xml)
    base = location
    for el in root.iter():
        if _local(el.tag) == "URLBase" and (el.text or "").strip():
            base = el.text.strip()
    found: dict[str, str] = {}
    for svc in root.iter():
        if _local(svc.tag) != "service":
            continue
        kids = {_local(k.tag): (k.text or "").strip() for k in svc}
        if kids.get("serviceType") in SERVICES and kids.get("controlURL"):
            found[kids["serviceType"]] = urllib.parse.urljoin(base, kids["controlURL"])
    for st in SERVICES:
        if st in found:
            return found[st], st
    return None


def soap(ctl: str, stype: str, action: str, args: dict | None = None) -> dict:
    inner = "".join(f"<{k}>{v}</{k}>" for k, v in (args or {}).items())
    body = (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:{action} xmlns:u="{stype}">'
            f"{inner}</u:{action}></s:Body></s:Envelope>").encode()
    raw = _http("POST", ctl, body, {"Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{stype}#{action}"'})
    out: dict[str, str] = {}
    for el in ET.fromstring(raw).iter():
        if el.text is not None and not list(el):
            out[_local(el.tag)] = el.text.strip()
    return out


def lan_ip_towards(host: str) -> str:
    """This PC's address on the network the router is on."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 9))
        return s.getsockname()[0]
    finally:
        s.close()


def classify(ip: str) -> str:
    """public / cgnat (the provider shares one address – no direct way in) / private (another router in front)."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return "unknown"
    if a in CGNAT:
        return "cgnat"
    if a.is_private or a.is_loopback or a.is_link_local:
        return "private"
    return "public"


class Gateway:
    def __init__(self, ctl: str, stype: str, lan_ip: str):
        self.ctl, self.stype, self.lan_ip = ctl, stype, lan_ip

    @classmethod
    def find(cls, timeout: float = 2.5) -> Gateway | None:
        for loc in discover(timeout):
            try:
                found = control_url(loc, _http("GET", loc))
            except Exception as e:  # noqa: BLE001
                log.debug("upnp description %s: %s", loc, e)
                continue
            if found:
                host = urllib.parse.urlparse(found[0]).hostname or ""
                return cls(found[0], found[1], lan_ip_towards(host))
        return None

    def external_ip(self) -> str:
        return soap(self.ctl, self.stype, "GetExternalIPAddress").get("NewExternalIPAddress", "")

    def add(self, external_port: int, internal_port: int, lease: int = 3600) -> None:
        args = {"NewRemoteHost": "", "NewExternalPort": external_port, "NewProtocol": "TCP",
                "NewInternalPort": internal_port, "NewInternalClient": self.lan_ip, "NewEnabled": 1,
                "NewPortMappingDescription": DESCRIPTION, "NewLeaseDuration": lease}
        try:
            soap(self.ctl, self.stype, "AddPortMapping", args)
        except UpnpError as e:
            if "725" not in str(e):                    # 725 = this router only knows permanent mappings
                raise
            soap(self.ctl, self.stype, "AddPortMapping", {**args, "NewLeaseDuration": 0})

    def remove(self, external_port: int) -> None:
        soap(self.ctl, self.stype, "DeletePortMapping",
             {"NewRemoteHost": "", "NewExternalPort": external_port, "NewProtocol": "TCP"})
