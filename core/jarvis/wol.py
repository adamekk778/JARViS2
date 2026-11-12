"""3.12 Zapnout PC z telefonu: what the phone needs to wake this PC (Wake-on-LAN) and whether the PC is ready for it.

The phone keeps this PC's network card address (MAC) and its home network's broadcast address. When the PC is off or
asleep, the phone sends the "magic packet" itself at home, and away from home asks your JARVIS relay to send it to
the home router (which forwards UDP 9 to this PC – JARVIS Link sets that up through UPnP).
"""
from __future__ import annotations

import ipaddress
import logging
import re
import subprocess
import sys
from typing import Any

log = logging.getLogger("jarvis.wol")
_NIC_WORDS = re.compile(r"ethernet|network|net adapter|lan|gbe|gigabit|realtek|intel\(r\)|killer|wi-?fi|wireless|802\.11", re.I)


def _norm_mac(mac: str) -> str:
    raw = re.sub(r"[^0-9a-fA-F]", "", mac or "").lower()
    return raw if len(raw) == 12 and raw != "000000000000" else ""


def nic(lan_ip: str = "") -> dict:
    """The network card that carries the home network: name, MAC, IPv4, broadcast, Wi-Fi or cable."""
    try:
        import psutil
    except ImportError:
        return {}
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    best: dict = {}
    for name, items in addrs.items():
        v4 = next((a for a in items if a.family == 2 and a.address and not a.address.startswith(("127.", "169.254."))), None)
        mac = next((_norm_mac(a.address) for a in items if a.family in (getattr(psutil, "AF_LINK", -1), 17, 18) and _norm_mac(a.address)), "")
        if not v4 or not mac or (name in stats and not stats[name].isup):
            continue
        try:
            ip = ipaddress.ip_address(v4.address)
            if not ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10"):
                continue                                   # VPN / Tailscale / CGNAT interfaces cannot carry the packet
            net = ipaddress.ip_network(f"{v4.address}/{v4.netmask or '255.255.255.0'}", strict=False)
        except ValueError:
            continue
        cand = {"name": name, "mac": mac, "ip": v4.address, "broadcast": str(net.broadcast_address),
                "wifi": bool(re.search(r"wi-?fi|wlan|wireless", name, re.I))}
        if v4.address == lan_ip:
            return cand
        if not best or (best["wifi"] and not cand["wifi"]):   # a cable beats Wi-Fi (Wi-Fi rarely wakes a PC)
            best = cand
    return best


def armed() -> bool | None:
    """Windows: may a network card wake this PC? (powercfg needs no admin rights for this query)."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(["powercfg", "-devicequery", "wake_armed"], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return any(_NIC_WORDS.search(line) for line in out.splitlines())


def info(rt: Any) -> dict:
    from .server.pairing import local_ips

    lan, _ = local_ips()
    card = nic(lan[0] if lan else "")
    router = getattr(getattr(rt, "link", None), "router", {}) or {}
    out = {"mac": card.get("mac", ""), "ip": card.get("ip", ""), "broadcast": card.get("broadcast", ""),
           "wifi": bool(card.get("wifi")), "card": card.get("name", ""), "armed": armed(),
           "away": bool(router.get("wake")), "public": router.get("public_ip", "") if router.get("wake") else ""}
    return out


def tips(i: dict) -> list[str]:
    """What to check on this PC so the phone can wake it – plain words for Settings."""
    t = []
    if not i.get("mac"):
        t.append("JARVIS nenašel síťovou kartu domácí sítě.")
        return t
    if i.get("wifi"):
        t.append("PC je připojené přes Wi-Fi – budit jde spolehlivě jen PC na kabelu. Zkus PC připojit kabelem do routeru.")
    if i.get("armed") is False:
        t.append("Windows zatím nedovolí síťové kartě PC probudit: Správce zařízení → Síťové adaptéry → tvoje karta → "
                 "Řízení spotřeby → zaškrtni „Povolit tomuto zařízení probudit počítač“ i „Jen magic packet“.")
    t.append("Aby šlo zapnout i úplně vypnuté PC: v BIOSu zapni „Wake on LAN“ a ve Windows vypni „Rychlé spuštění“ "
             "(Ovládací panely → Možnosti napájení → Nastavení tlačítek). Uspané PC se budí i bez toho.")
    if not i.get("away"):
        t.append("Mimo domov: zapni JARVIS Link s relay serverem; router musí povolit UPnP.")
    return t
