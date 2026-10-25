"""OMEGA §53 + 021/387: network diagnostics – Wi-Fi signal, DNS, route to a host, TLS certificates, DNS as seen by
public resolvers, HTTP availability. All read-only, standard tools (socket, ssl, tracert / traceroute, netsh)."""
from __future__ import annotations

import datetime as dt
import re
import socket
import ssl
import sys
import time

from .pcreport import run_quiet


def wifi() -> dict:
    """Signal, SSID, channel, speed (Windows: netsh wlan show interfaces)."""
    if sys.platform != "win32":
        return {"error": "jen na Windows"}
    code, out, _ = run_quiet(["netsh", "wlan", "show", "interfaces"], 10)
    info: dict = {}
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        kl = k.lower()
        if kl == "ssid":
            info["ssid"] = v
        elif kl in ("signal", "signál"):
            info["signal_pct"] = int(re.sub(r"\D", "", v) or 0)
        elif kl in ("channel", "kanál"):
            info["channel"] = v
        elif "receive rate" in kl or "rychlost příjmu" in kl:
            info["rx_mbps"] = v
        elif kl in ("radio type", "typ rádia"):
            info["radio"] = v
        elif kl in ("state", "stav"):
            info["state"] = v
    return info or {"error": "Wi-Fi není připojená"}


def dns_timing(domains: tuple[str, ...] = ("google.com", "seznam.cz", "cloudflare.com")) -> list[dict]:
    out = []
    for d in domains:
        t0 = time.perf_counter()
        try:
            ip = socket.getaddrinfo(d, 443)[0][4][0]
            out.append({"domain": d, "ip": ip, "ms": round((time.perf_counter() - t0) * 1000, 1)})
        except OSError as e:
            out.append({"domain": d, "error": str(e)[:100]})
    return out


def trace(host: str, max_hops: int = 20) -> list[dict]:
    """OMEGA 706: the hops to a host (Windows tracert -d, elsewhere traceroute -n)."""
    host = re.sub(r"[^\w.\-:]", "", host)[:255]
    if not host:
        return []
    cmd = ["tracert", "-d", "-h", str(max_hops), "-w", "800", host] if sys.platform == "win32" else ["traceroute", "-n", "-m", str(max_hops), "-w", "1", host]
    _code, out, _ = run_quiet(cmd, 90)
    hops = []
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*)", line)
        if not m:
            continue
        rest = m.group(2)
        ms = [int(x) for x in re.findall(r"(\d+)\s*ms", rest)] or [int(x) for x in re.findall(r"<1", rest) and [1]]
        ip = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", rest)
        hops.append({"hop": int(m.group(1)), "ip": ip[-1] if ip else "*", "ms": round(sum(ms) / len(ms), 1) if ms else None})
    return hops


def tls_check(domain: str, port: int = 443) -> dict:
    """OMEGA 708 / 387: certificate issuer, expiry, protocol; flags expiring soon or invalid."""
    domain = domain.strip().removeprefix("https://").removeprefix("http://").split("/")[0]
    ctx = ssl.create_default_context()
    t0 = time.perf_counter()
    try:
        with socket.create_connection((domain, port), timeout=6) as raw, ctx.wrap_socket(raw, server_hostname=domain) as s:
            cert = s.getpeercert()
            proto = s.version()
    except ssl.SSLCertVerificationError as e:
        return {"domain": domain, "valid": False, "error": f"neplatný certifikát: {e.verify_message}"}
    except OSError as e:
        return {"domain": domain, "valid": False, "error": str(e)[:200]}
    exp = dt.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
    days = (exp - dt.datetime.utcnow()).days
    issuer = dict(x[0] for x in cert.get("issuer", []))
    return {"domain": domain, "valid": True, "expires": exp.date().isoformat(), "days_left": days, "protocol": proto,
            "issuer": issuer.get("organizationName", "") or issuer.get("commonName", ""), "ms": round((time.perf_counter() - t0) * 1000)}


async def dns_public(rt, domain: str, rtype: str = "A") -> dict:
    """OMEGA 707: what Google and Cloudflare resolvers answer (DNS over HTTPS JSON) – to see if a change propagated."""
    res = {}
    async with rt.http() as c:
        for name, url in (("Google", "https://dns.google/resolve"), ("Cloudflare", "https://cloudflare-dns.com/dns-query")):
            try:
                r = await c.get(url, params={"name": domain, "type": rtype}, headers={"accept": "application/dns-json"}, timeout=6)
                ans = r.json().get("Answer") or []
                res[name] = sorted({a.get("data", "") for a in ans})
            except Exception as e:
                res[name] = [f"chyba: {type(e).__name__}"]
    try:
        res["Tento PC"] = sorted({a[4][0] for a in socket.getaddrinfo(domain, None)})
    except OSError as e:
        res["Tento PC"] = [f"chyba: {e}"]
    return res


async def http_check(rt, url: str) -> dict:
    """OMEGA 709: is a web / API up, how fast, which status."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    t0 = time.perf_counter()
    try:
        async with rt.http() as c:
            r = await c.get(url, timeout=10, follow_redirects=True)
        return {"url": url, "up": r.status_code < 500, "status": r.status_code, "ms": round((time.perf_counter() - t0) * 1000)}
    except Exception as e:
        return {"url": url, "up": False, "status": None, "error": f"{type(e).__name__}: {e}"[:200]}
