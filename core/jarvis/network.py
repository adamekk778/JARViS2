"""3.5 home network: who is on the Wi-Fi ("kdo je připojený"), names for devices, Wake-on-LAN, a new-device alert."""
from __future__ import annotations

import asyncio
import json
import re
import socket
import subprocess
import sys

from .stark import _fold

MAC_RE = re.compile(r"([0-9a-f]{2}[:-]){5}[0-9a-f]{2}", re.I)
IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def norm_mac(mac: str) -> str:
    return mac.lower().replace("-", ":")


def parse_neighbors(text: str) -> list[dict]:
    """`arp -a` (Windows) or `ip neigh` (Linux) → [{ip, mac}], without broadcast / multicast entries."""
    out, seen = [], set()
    for line in text.splitlines():
        ip, mac = IP_RE.search(line), MAC_RE.search(line)
        if not ip or not mac:
            continue
        m = norm_mac(mac.group(0))
        first = int(ip.group(1).split(".")[0])
        last = ip.group(1).split(".")[-1]
        if m in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00") or m.startswith("01:00:5e") or 224 <= first <= 239 or last == "255":
            continue
        if m not in seen:
            seen.add(m)
            out.append({"ip": ip.group(1), "mac": m})
    return out


def read_neighbors() -> list[dict]:
    flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    cmd = ["arp", "-a"] if sys.platform == "win32" else ["ip", "neigh"]
    try:
        text = subprocess.run(cmd, capture_output=True, text=True, timeout=8, **flags).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_neighbors(text)


def _hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0].split(".")[0]
    except (OSError, UnicodeError):
        return ""


def names(rt) -> dict[str, str]:
    row = rt.db.one("SELECT v FROM kv WHERE k='net_names'")
    return json.loads(row["v"]) if row else {}


def set_name(rt, mac: str, name: str) -> None:
    n = names(rt)
    if name:
        n[norm_mac(mac)] = name
    else:
        n.pop(norm_mac(mac), None)
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('net_names', ?)", (json.dumps(n, ensure_ascii=False),))


def known(rt) -> set[str]:
    row = rt.db.one("SELECT v FROM kv WHERE k='net_seen'")
    return set(json.loads(row["v"])) if row else set()


def remember(rt, macs: set[str]) -> None:
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('net_seen', ?)", (json.dumps(sorted(macs)),))


async def devices(rt) -> list[dict]:
    """The devices the PC has seen on the network lately, with names (yours, or the one they announce)."""
    found = await asyncio.to_thread(read_neighbors)
    hosts = await asyncio.gather(*[asyncio.to_thread(_hostname, d["ip"]) for d in found])
    nick, seen = names(rt), known(rt)
    for d, host in zip(found, hosts):
        d["host"] = host
        d["name"] = nick.get(d["mac"]) or host or ""
        d["new"] = bool(seen) and d["mac"] not in seen
    return found


def find(items: list[dict], rt, who: str) -> dict | None:
    w = _fold(who)
    if MAC_RE.fullmatch(who.strip()):
        return {"mac": norm_mac(who.strip()), "name": who}
    nick = names(rt)
    for mac, n in nick.items():
        if _fold(n) == w or (w and w in _fold(n)):
            return {"mac": mac, "name": n}
    return next((d for d in items if w and (w == d["ip"] or w in _fold(d.get("name", "")))), None)


def magic_packet(mac: str) -> bytes:
    raw = bytes.fromhex(norm_mac(mac).replace(":", ""))
    if len(raw) != 6:
        raise ValueError("Neplatná MAC adresa.")
    return b"\xff" * 6 + raw * 16


def wake(mac: str) -> None:
    pkt = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            s.sendto(pkt, ("255.255.255.255", port))
