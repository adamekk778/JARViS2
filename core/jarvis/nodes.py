"""3.14 Víc počítačů jako jeden JARVIS (návrhy 2, 25): the notebook, the gaming PC and an always-on home server, each
running JARVIS, act as one: "pošli to na notebook", "zeptej se herního PC, kolik má volného místa", "vypni herní PC",
"zapni herní PC" (Wake-on-LAN).

A node is another JARVIS reachable on the home network (or through JARVIS Link): its address and its pairing key
(Nastavení → Telefon on that PC). The request goes there as if typed into its chat; when that JARVIS wants a
confirmation (deleting, shutting down…), the question comes HERE and your answer goes back – nothing risky happens there
without you saying yes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from typing import Any
from urllib.parse import quote, urlsplit

log = logging.getLogger(__name__)
TIMEOUT_S = 120


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(c)).strip()


def nodes(rt: Any) -> list[dict]:
    return [n for n in (getattr(rt.cfg.home, "nodes", []) or []) if isinstance(n, dict) and n.get("name") and n.get("url")]


def find(rt: Any, name: str) -> dict | None:
    want = _fold(name)
    items = nodes(rt)
    return next((n for n in items if _fold(n["name"]) == want), None) or \
        next((n for n in items if want and (want in _fold(n["name"]) or _fold(n["name"]) in want)), None)


def token_for(node: dict) -> str:
    """The node's pairing key – kept in the OS keyring, not in the settings (the phone sees the settings)."""
    if node.get("token"):
        return str(node["token"])
    from . import secrets

    try:
        return secrets.get(f"node:{_fold(node['name'])}") or ""
    except Exception:  # noqa: BLE001
        return ""


def add(rt: Any, name: str, url: str, token: str = "", mac: str = "") -> dict:
    from . import secrets

    name, url = name.strip()[:40], url.strip()[:200]
    if not name or not url:
        raise ValueError("jméno a adresa jsou povinné")
    if mac and not mac_ok(mac):
        raise ValueError("MAC adresa má tvar AA:BB:CC:DD:EE:FF")
    if token:
        secrets.set(f"node:{_fold(name)}", token.strip())
    items = [n for n in nodes(rt) if _fold(n["name"]) != _fold(name)]
    items.append({"name": name, "url": url, "mac": mac.strip()})
    rt.update_config({"home": {"nodes": items}})
    return {"name": name, "url": url, "mac": mac}


def remove(rt: Any, name: str) -> bool:
    items = nodes(rt)
    keep = [n for n in items if _fold(n["name"]) != _fold(name)]
    rt.update_config({"home": {"nodes": keep}})
    return len(keep) != len(items)


def ws_url(node: dict) -> str:
    u = urlsplit(node["url"] if "://" in node["url"] else "http://" + node["url"])
    scheme = "wss" if u.scheme == "https" else "ws"
    port = f":{u.port}" if u.port else ""
    return f"{scheme}://{u.hostname}{port}/ws?token={quote(token_for(node), safe='')}"


async def ask(rt: Any, node: dict, text: str, connect=None, timeout: float = TIMEOUT_S) -> dict:
    """Send a request to another JARVIS; relay its confirmations to you; return its answer."""
    from .llm.base import ToolCall

    if connect is None:
        from websockets.asyncio.client import connect as ws_connect

        conn = ws_connect(ws_url(node), open_timeout=8, max_size=2**22)
    else:
        conn = connect(ws_url(node))
    answer, cards = "", []
    try:
        async with conn as ws:
            await ws.send(json.dumps({"type": "hello", "client": "node", "name": "JARVIS"}))
            await ws.send(json.dumps({"type": "user_text", "text": text, "attachments": []}))
            loop = asyncio.get_running_loop()
            end = loop.time() + timeout
            while True:
                left = end - loop.time()
                if left <= 0:
                    return {"ok": False, "answer": f"{node['name']} neodpověděl včas.", "node": node["name"]}
                msg = json.loads(await asyncio.wait_for(ws.recv(), left))
                t = msg.get("type")
                if t == "confirm_request":         # the other PC wants a yes – you decide here
                    call = ToolCall(id=f"node-{msg.get('id', '')}", name=str(msg.get("tool", "")) or "node",
                                    arguments=msg.get("args") or {})
                    ok = await rt.agent._ask_confirm(call)
                    await ws.send(json.dumps({"type": "confirm_response", "id": msg.get("id", ""), "approved": bool(ok)}))
                elif t == "tool_end":
                    cards.append(str(msg.get("summary", ""))[:200])
                elif t == "assistant_done":
                    answer = str(msg.get("text", "")).strip()
                    break
                elif t == "error" and msg.get("message"):
                    return {"ok": False, "answer": str(msg["message"]), "node": node["name"]}
    except (OSError, asyncio.TimeoutError) as e:
        return {"ok": False, "answer": f"{node['name']} není dostupný ({type(e).__name__}) – běží tam JARVIS a je ve stejné síti?",
                "node": node["name"]}
    return {"ok": True, "answer": answer or "Hotovo.", "node": node["name"], "steps": cards}


def mac_ok(mac: str) -> bool:
    return bool(re.fullmatch(r"([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", mac or ""))


def wake(node: dict) -> bool:
    """Wake-on-LAN magic packet to the node's network card."""
    import socket

    mac = str(node.get("mac", ""))
    if not mac_ok(mac):
        return False
    raw = bytes.fromhex(re.sub(r"[:-]", "", mac))
    packet = b"\xff" * 6 + raw * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, ("255.255.255.255", 9))
    return True
