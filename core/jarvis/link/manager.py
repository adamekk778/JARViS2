"""JARVIS Link on the PC: the encrypted port, the router mapping and the relay agent – started, watched and described
for the phone (/api/link/info) and for Settings (status)."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import secrets as _rand
import socket
import time
from typing import Any

from .. import secrets
from . import upnp
from .relay_agent import RelayAgent

log = logging.getLogger(__name__)

RELAY_KEY = "link_relay_key"
UPNP_RENEW_S = 30 * 60
WAKE_PORT = 9                     # 3.12 Wake-on-LAN from outside: the router forwards UDP 9 to this PC
FAIL_LIMIT = 20               # wrong tokens from one address in FAIL_WINDOW_S → that address waits FAIL_WINDOW_S
FAIL_WINDOW_S = 600


def relay_key(create: bool = False) -> str:
    k = secrets.get(RELAY_KEY)
    if not k and create:
        k = _rand.token_urlsafe(24)
        secrets.set(RELAY_KEY, k)
    return k


def global_v6() -> list[str]:
    """This PC's public IPv6 addresses – many homes have them, and mobile data usually speaks IPv6 too."""
    try:
        import psutil
    except ImportError:
        return []
    out = []
    for addrs in psutil.net_if_addrs().values():
        for a in addrs:
            if a.family != socket.AF_INET6:
                continue
            try:
                ip = ipaddress.ip_address(a.address.split("%")[0])
            except ValueError:
                continue
            if ip.is_global and ip not in ipaddress.ip_network("2001::/32"):   # not Teredo
                out.append(str(ip))
    return out[:3]


class Gate:
    """Wraps the app for the link port: everything that comes here is from outside (never "this PC", even when it
    arrives through the relay agent on 127.0.0.1), and nothing but /api/health answers without a paired token."""

    def __init__(self, rt: Any, app: Any, watch: Any = None):
        self.rt, self.app, self.watch = rt, app, watch
        self.fails: dict[str, list[float]] = {}

    def _blocked(self, peer: str) -> bool:
        now = time.monotonic()
        hits = [t for t in self.fails.get(peer, []) if now - t < FAIL_WINDOW_S]
        if hits:
            self.fails[peer] = hits
        else:
            self.fails.pop(peer, None)
        return len(hits) >= FAIL_LIMIT

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        peer = (scope.get("client") or ("?", 0))[0]
        scope = dict(scope)
        scope["client"] = ("link", 0)                 # not local, not "home network" – whatever the socket says
        scope["jarvis_link"] = True
        path = scope.get("path", "")
        if scope["type"] == "websocket":              # the app itself checks the token and answers 4401
            if self._blocked(peer):
                await send({"type": "websocket.close", "code": 4429})
                return
            if self.watch is not None:
                from ..server.app import _token_ok

                tok = _query_token(scope)
                if _token_ok(self.rt, tok):
                    self.watch.seen(peer, tok)
                else:
                    self.watch.failed(peer)
            return await self.app(scope, receive, send)
        if path == "/api/health":
            return await self.app(scope, receive, send)
        from ..server.app import _token_ok

        token = None
        for k, v in scope.get("headers") or []:
            if k == b"authorization" and v[:7].lower() == b"bearer ":
                token = v[7:].decode("latin-1")
        if token is None:
            token = _query_token(scope)
        if self._blocked(peer):
            return await _plain(send, 429, "Příliš mnoho pokusů – zkus to za pár minut.")
        if not _token_ok(self.rt, token):
            self.fails.setdefault(peer, []).append(time.monotonic())
            if self.watch is not None:
                self.watch.failed(peer)
            return await _plain(send, 401, "Chybí nebo je špatný token – spáruj telefon znovu.")
        if self.watch is not None:
            self.watch.seen(peer, token)
        return await self.app(scope, receive, send)


def _query_token(scope) -> str | None:
    from urllib.parse import parse_qs

    return (parse_qs((scope.get("query_string") or b"").decode("latin-1")).get("token") or [None])[0]


def route_of(peer: str) -> str:
    """How a connection came: through the relay agent (127.0.0.1), from the home network, or straight from outside."""
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return "internet"
    if ip.is_loopback:
        return "relay"
    if ip.is_private or ip.is_link_local:
        return "home"
    return "internet"


ROUTE_LABEL = {"relay": "přes tvůj relay", "home": "z domácí sítě", "internet": "přímo z internetu"}


class Watch:
    """3.12 who connects over JARVIS Link: every paired device and the way it came, kept for Settings; a new device or
    a new way – and anyone trying wrong keys – is told to you at once."""

    KEEP = 40
    FAIL_ALERT = 5               # wrong keys from one address before you are told
    ALERT_EVERY_S = 3600

    def __init__(self, rt: Any):
        self.rt = rt
        self.recent: dict[tuple[str, str, str], dict] = {}
        self.fail_counts: dict[str, list[float]] = {}
        self.alerted: dict[str, float] = {}
        self.alerts: list[dict] = []
        self._known = self._load()

    def _file(self):
        from .cert import folder

        return folder() / "seen.json"

    def _load(self) -> set[str]:
        import json

        try:
            return set(json.loads(self._file().read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return set()

    def _save(self) -> None:
        import json

        try:
            self._file().write_text(json.dumps(sorted(self._known)), encoding="utf-8")
        except OSError as e:
            log.debug("link seen: %s", e)

    def _who(self, token: str | None) -> tuple[str, str]:
        from .. import mobileplus

        d = mobileplus.device_for(self.rt, token)
        if d:
            return d["id"], d.get("name") or "Telefon"
        g = mobileplus.guest_for(self.rt, token)
        if g:
            return f"guest:{g.get('id', '')}", f"Host – {g.get('name') or 'host'}"
        return "pairing", "Telefon (párovací kód)"

    def seen(self, peer: str, token: str | None) -> None:
        dev_id, name = self._who(token)
        route = route_of(peer)
        ip = "" if route == "relay" else peer
        now = time.time()
        key = (dev_id, route, ip)
        e = self.recent.get(key)
        if e:
            e["last"], e["count"] = now, e["count"] + 1
            return
        self.recent[key] = {"device": dev_id, "name": name, "route": route, "label": ROUTE_LABEL[route], "ip": ip,
                            "first": now, "last": now, "count": 1}
        if len(self.recent) > self.KEEP:
            oldest = min(self.recent, key=lambda k: self.recent[k]["last"])
            self.recent.pop(oldest, None)
        known = f"{dev_id}|{route}"
        if known not in self._known:
            self._known.add(known)
            self._save()
            self._alert("new", f"{name} se poprvé připojil {ROUTE_LABEL[route]}" + (f" ({ip})" if ip else "") + ".",
                        "Nebyl jsi to ty? V Nastavení → Telefon → JARVIS Link ho jedním klikem odpojíš.")

    def failed(self, peer: str) -> None:
        now = time.time()
        hits = [t for t in self.fail_counts.get(peer, []) if now - t < 600] + [now]
        self.fail_counts[peer] = hits
        if len(hits) >= self.FAIL_ALERT and now - self.alerted.get(peer, 0) > self.ALERT_EVERY_S:
            self.alerted[peer] = now
            where = "přes tvůj relay" if route_of(peer) == "relay" else f"z adresy {peer}"
            self._alert("bad_key", f"Někdo zkouší neplatný klíč {where} ({len(hits)}× za 10 min).",
                        f"Po {FAIL_LIMIT} pokusech se ta adresa na 10 minut zablokuje. Bez spárovaného klíče se nic nedostane dovnitř.")

    def _alert(self, kind: str, text: str, hint: str) -> None:
        self.alerts = ([{"kind": kind, "text": text, "hint": hint, "at": time.time()}] + self.alerts)[:10]
        try:
            self.rt.notify("JARVIS Link", f"{text} {hint}", speak=False)
        except Exception as e:  # noqa: BLE001
            log.debug("link alert: %s", e)
        try:
            self.rt.bus.publish("link_status", **self.rt.link.status())
        except Exception:  # noqa: BLE001
            pass

    def list(self) -> list[dict]:
        return sorted(self.recent.values(), key=lambda e: -e["last"])


async def _plain(send, code: int, text: str) -> None:
    body = text.encode()
    await send({"type": "http.response.start", "status": code,
                "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def _sockets(port: int) -> list[socket.socket]:
    out = []
    s4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s4.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s4.bind(("0.0.0.0", port))
        s4.listen(128)
        s4.setblocking(False)
        out.append(s4)
    except OSError:
        s4.close()
        raise
    try:
        s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        if not hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s6.bind(("::", port))
        s6.listen(128)
        s6.setblocking(False)
        out.append(s6)
    except (OSError, AttributeError):
        try:
            s6.close()
        except Exception:  # noqa: BLE001
            pass
    return out


class Link:
    def __init__(self, rt: Any):
        self.rt = rt
        self.fp = ""
        self.server = None
        self.agent: RelayAgent | None = None
        self.listening = False
        self.error = ""
        self.router: dict = {"state": "off"}
        self._tasks: list[asyncio.Task] = []
        self._gw: upnp.Gateway | None = None
        self._mapped = 0
        self.watch = Watch(rt)

    @property
    def cfg(self):
        return self.rt.cfg.link

    # ---------- start / stop ----------
    async def start(self) -> None:
        if not self.cfg.enabled:
            return
        app = getattr(self.rt, "asgi_app", None)
        if app is None:
            self.error = "server ještě neběží"
            return
        try:
            await self._start_tls(app)
        except Exception as e:  # noqa: BLE001
            self.error = f"port {self.cfg.port} nejde otevřít: {e}"[:200]
            log.warning("JARVIS Link: %s", self.error)
            return
        loop = asyncio.get_running_loop()
        if self.cfg.upnp:
            self._tasks.append(loop.create_task(self._router_loop()))
        else:
            self.router = {"state": "off"}
        self._start_relay()

    async def _start_tls(self, app: Any) -> None:
        import uvicorn

        from .cert import ensure

        c = await asyncio.to_thread(ensure)
        self.fp = c["fp"]
        conf = uvicorn.Config(Gate(self.rt, app, self.watch), lifespan="off", ssl_certfile=c["cert"], ssl_keyfile=c["key"],
                              ssl_keyfile_password=c["password"], proxy_headers=False, server_header=False,
                              log_level="warning", log_config=None, ws_max_size=32 * 2**20, timeout_keep_alive=30)
        socks = _sockets(self.cfg.port)
        self.server = uvicorn.Server(conf)
        self.server.install_signal_handlers = lambda: None   # older uvicorn; newer ones only do it on the main thread

        server = self.server

        async def run():
            try:   # _serve: without uvicorn's Ctrl+C handling (that belongs to the main server)
                await server._serve(socks) if hasattr(server, "_serve") else await server.serve(socks)
            except BaseException as e:  # noqa: BLE001
                if not isinstance(e, asyncio.CancelledError):
                    self.error = f"šifrovaný port: {e}"[:200]
            finally:
                for s in socks:
                    s.close()
                if self.server is server or self.server is None:
                    self.listening = False

        self._serve_task = asyncio.get_running_loop().create_task(run())
        for _ in range(100):
            if self.server.started:
                break
            await asyncio.sleep(0.05)
        self.listening = bool(self.server.started)
        self.error = "" if self.listening else "šifrovaný port nenaběhl"

    def _start_relay(self) -> None:
        if self.agent:
            self.agent.stop()
            self.agent = None
        key = relay_key()
        if self.cfg.relay_host and key and self.listening:
            self.agent = RelayAgent(self.cfg.relay_host.strip(), self.cfg.relay_port, key, self.cfg.room, self.cfg.port)
            self.agent.start()

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        if self.agent:
            self.agent.stop()
            self.agent = None
        if self._gw and self._mapped:
            gw, port = self._gw, self._mapped
            self._mapped = 0
            try:
                await asyncio.to_thread(gw.remove, port)
            except Exception as e:  # noqa: BLE001
                log.debug("upnp remove: %s", e)
        if self.server:
            self.server.should_exit = True
            task = getattr(self, "_serve_task", None)
            if task:
                try:
                    await asyncio.wait_for(asyncio.shield(task), 5)
                except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                    task.cancel()
            self.server = None
        self._tasks = []
        self.listening = False
        self.router = {"state": "off"}

    async def apply(self) -> dict:
        """After a change in Settings: start again with the new values."""
        await self.stop()
        self.error = ""
        await self.start()
        return self.status()

    # ---------- the router ----------
    @property
    def public_port(self) -> int:
        return self.cfg.public_port or self.cfg.port

    async def map_router(self) -> dict:
        try:
            gw = await asyncio.to_thread(upnp.Gateway.find)
            if gw is None:
                self.router = {"state": "none"}
                return self.router
            self._gw = gw
            ext = await asyncio.to_thread(gw.external_ip)
            kind = upnp.classify(ext)
            if kind != "public":
                self.router = {"state": kind, "public_ip": ext, "lan_ip": gw.lan_ip}
                return self.router
            await asyncio.to_thread(gw.add, self.public_port, self.cfg.port)
            self._mapped = self.public_port
            wake = False
            try:                                        # 3.12 Zapnout PC z telefonu: the relay's wake packet → this PC
                await asyncio.to_thread(gw.add, WAKE_PORT, WAKE_PORT, 0, "UDP")
                wake = True
            except Exception as e:  # noqa: BLE001 – waking from outside is a bonus, never a reason to fail
                log.debug("upnp wake mapping: %s", e)
            self.router = {"state": "ok", "public_ip": ext, "public_port": self.public_port, "lan_ip": gw.lan_ip,
                           "wake": wake, "at": time.time()}
        except Exception as e:  # noqa: BLE001
            self.router = {"state": "failed", "error": str(e)[:160]}
        return self.router

    async def _router_loop(self) -> None:
        while True:
            await self.map_router()
            await asyncio.sleep(UPNP_RENEW_S if self.router.get("state") == "ok" else 5 * 60)

    # ---------- what the phone and Settings get ----------
    def info(self) -> dict:
        """For the paired phone: how to reach this PC from outside, and the fingerprint to check."""
        if not (self.cfg.enabled and self.listening and self.fp):
            return {"enabled": False}
        from ..server.pairing import local_ips

        lan, _ = local_ips()
        direct = [{"host": ip, "port": self.cfg.port, "kind": "lan"} for ip in lan[:3]]
        if self.router.get("state") == "ok":
            direct.append({"host": self.router["public_ip"], "port": self.public_port, "kind": "router"})
        if self.cfg.public_host.strip():
            direct.append({"host": self.cfg.public_host.strip(), "port": self.public_port, "kind": "manual"})
        direct += [{"host": ip, "port": self.cfg.port, "kind": "ipv6"} for ip in global_v6()]
        relay = None
        key = relay_key()
        if self.cfg.relay_host.strip() and key:
            relay = {"host": self.cfg.relay_host.strip(), "port": self.cfg.relay_port, "key": key, "room": self.cfg.room}
        return {"enabled": True, "v": 1, "fp": self.fp, "direct": direct, "relay": relay, "at": int(time.time())}

    def status(self) -> dict:
        """For Settings on this PC (never the keys)."""
        ag = self.agent.status() if self.agent else None
        return {"enabled": self.cfg.enabled, "listening": self.listening, "port": self.cfg.port, "error": self.error,
                "fp": self.fp, "upnp": self.cfg.upnp, "router": self.router, "ipv6": global_v6() if self.cfg.enabled else [],
                "public_host": self.cfg.public_host, "relay_host": self.cfg.relay_host, "relay_port": self.cfg.relay_port,
                "relay_key_set": bool(relay_key()), "relay": ag,
                "connections": self.watch.list()[:15], "alerts": self.watch.alerts[:5],
                "reachable": bool(self.listening and (self.router.get("state") == "ok" or (ag and ag["connected"])
                                                      or self.cfg.public_host.strip()))}

    def install_script(self) -> str:
        """A one-paste installer for your relay server (Ubuntu/Debian with systemd); carries a fresh access key."""
        from pathlib import Path

        key = relay_key(create=True)
        code = (Path(__file__).with_name("relay_server.py")).read_text(encoding="utf-8")
        port = int(self.cfg.relay_port)
        return INSTALL.replace("@KEY@", key).replace("@PORT@", str(port)).replace("@CODE@", code)


INSTALL = """#!/bin/bash
# JARVIS Relay – instalace na tvůj server (Ubuntu / Debian). Vlož celé do terminálu serveru (SSH) jako root.
set -e
command -v python3 >/dev/null || (apt-get update -y && apt-get install -y python3)
install -d -m 755 /opt/jarvis-relay
cat > /opt/jarvis-relay/jarvis_relay.py <<'JARVIS_RELAY_CODE'
@CODE@JARVIS_RELAY_CODE
umask 077
printf '%s' '@KEY@' > /etc/jarvis-relay.key
cat > /etc/systemd/system/jarvis-relay.service <<'JARVIS_RELAY_UNIT'
[Unit]
Description=JARVIS Relay
After=network-online.target
Wants=network-online.target

[Service]
DynamicUser=yes
LoadCredential=key:/etc/jarvis-relay.key
ExecStart=/usr/bin/python3 /opt/jarvis-relay/jarvis_relay.py --port @PORT@ --key-file ${CREDENTIALS_DIRECTORY}/key
Restart=always
RestartSec=3
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
JARVIS_RELAY_UNIT
systemctl daemon-reload
systemctl enable --now jarvis-relay
systemctl restart jarvis-relay
if command -v ufw >/dev/null && ufw status | grep -q active; then ufw allow @PORT@/tcp; fi
if command -v iptables >/dev/null && iptables -S INPUT 2>/dev/null | grep -q -- '-j REJECT'; then
  iptables -I INPUT -p tcp --dport @PORT@ -j ACCEPT
  (command -v netfilter-persistent >/dev/null && netfilter-persistent save) || true
fi
echo
echo "Hotovo: JARVIS Relay běží na portu @PORT@. Teď v JARVISovi na PC zadej adresu tohoto serveru."
"""
