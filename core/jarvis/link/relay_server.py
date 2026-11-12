#!/usr/bin/env python3
"""JARVIS Relay – your own meeting point on the internet for JARVIS Link (needs only Python 3.8+, no packages).

Run it on any small server with a public address (a free VPS is enough):

    python3 jarvis_relay.py --port 8443 --key-file /etc/jarvis-relay.key

How it works: the PC keeps a few connections open here ("pc"); when the phone comes ("phone"), the relay pairs it
with one of them and from then on only copies bytes both ways. Everything inside is TLS between the phone and the
PC (the phone checks the PC's certificate fingerprint), so the relay can neither read nor change anything. Without
the access key nobody can use the relay at all.

Handshake (one text line each way):  ->  "JRL1 <key> pc|phone <room>\\n"   <-  "OK\\n" | "ERR <why>\\n"
An idle "pc" connection gets "P\\n" every 30 s (keeps routers from dropping it) and "GO\\n" when a phone is paired.
Wake (3.12):  ->  "JRL1 <key> wake <room> <mac>\\n"  – the PC is off: the relay sends a Wake-on-LAN packet to the
home's public address it last saw the PC come from (the home router forwards UDP 9 to the PC).
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import hmac
import logging
import os
import re
import socket
import sys
import time

log = logging.getLogger("jarvis-relay")
ROOM_RE = re.compile(r"^[0-9a-f]{16,64}$")
MAC_RE = re.compile(r"^[0-9a-f]{12}$")
WAKE_PORTS = (9, 7)
WAKE_GAP_S = 3
PING_S = 30
HANDSHAKE_S = 10
WAIT_PC_S = 8
POOL_PER_ROOM = 4
MAX_ROOMS = 32
MAX_PIPES = 64
MAX_CONNS = 256
CHUNK = 65536


class Relay:
    def __init__(self, key: str):
        if len(key) < 16:
            raise ValueError("the access key must have at least 16 characters")
        self.key = key
        self.pools: "dict[str, collections.deque]" = {}
        self.pipes = 0
        self.conns = 0
        self.homes: "dict[str, str]" = {}           # room → the public address the PC last came from (for Wake-on-LAN)
        self.woke: "dict[str, float]" = {}

    # ---------- the connections ----------
    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.conns += 1
        try:
            if self.conns > MAX_CONNS:
                return
            try:
                line = await asyncio.wait_for(reader.readline(), HANDSHAKE_S)
            except (asyncio.TimeoutError, ValueError, ConnectionError):
                return
            parts = line.decode("ascii", "replace").split()
            wake = len(parts) == 5 and parts[2:3] == ["wake"] and bool(MAC_RE.match(parts[4]))
            if (len(parts) != (5 if wake else 4) or parts[0] != "JRL1" or not hmac.compare_digest(parts[1].encode(), self.key.encode())
                    or parts[2] not in ("pc", "phone", "wake") or not ROOM_RE.match(parts[3])):
                await self._say(writer, b"ERR auth\n")
                await asyncio.sleep(1)               # slows down guessing
                return
            room = parts[3]
            if wake:
                await self._say(writer, self.wake(room, parts[4]))
                return
            if parts[2] == "pc":
                peer = writer.get_extra_info("peername")
                if peer and (room in self.homes or len(self.homes) < MAX_ROOMS * 4):
                    self.homes[room] = peer[0]
                await self._pc(room, reader, writer)
            else:
                await self._phone(room, reader, writer)
        except Exception as e:  # noqa: BLE001 – one bad connection must never stop the relay
            log.debug("connection: %s", e)
        finally:
            self.conns -= 1
            _close(writer)

    def wake(self, room: str, mac: str) -> bytes:
        """A Wake-on-LAN "magic packet" for this PC to its home's public address (harmless: it only wakes that MAC)."""
        home = self.homes.get(room)
        if not home:
            return b"ERR nohome\n"
        now = time.monotonic()
        if now - self.woke.get(room, 0.0) < WAKE_GAP_S:
            return b"OK\n"
        self.woke[room] = now
        packet = b"\xff" * 6 + bytes.fromhex(mac) * 16
        try:
            fam = socket.AF_INET6 if ":" in home else socket.AF_INET
            with socket.socket(fam, socket.SOCK_DGRAM) as s:
                for port in WAKE_PORTS:
                    s.sendto(packet, (home, port))
        except OSError as e:
            log.debug("wake: %s", e)
            return b"ERR send\n"
        return b"OK\n"

    async def _say(self, writer: asyncio.StreamWriter, data: bytes) -> bool:
        try:
            writer.write(data)
            await writer.drain()
            return True
        except (ConnectionError, OSError):
            return False

    async def _pc(self, room: str, reader, writer) -> None:
        pool = self.pools.get(room)
        if pool is None:
            if len(self.pools) >= MAX_ROOMS:
                await self._say(writer, b"ERR full\n")
                return
            pool = self.pools[room] = collections.deque()
        slot = {"reader": reader, "writer": writer, "taken": asyncio.Event(), "done": asyncio.Event()}
        pool.append(slot)
        while len(pool) > POOL_PER_ROOM:            # the oldest idle one goes (the PC opens a fresh one)
            old = pool.popleft()
            _close(old["writer"])
            old["done"].set()
        if not await self._say(writer, b"OK\n"):
            self._drop(room, slot)
            return
        eof = slot["eof"] = asyncio.ensure_future(reader.read(1))   # the PC never speaks while idle: anything = gone
        try:
            while not slot["taken"].is_set():
                taken = asyncio.ensure_future(slot["taken"].wait())
                done, _ = await asyncio.wait({eof, taken}, timeout=PING_S, return_when=asyncio.FIRST_COMPLETED)
                if slot["taken"].is_set():           # a phone took it (and stopped the idle watch itself)
                    taken.cancel()
                    break
                if eof in done:
                    taken.cancel()
                    self._drop(room, slot)
                    return
                if taken not in done:
                    taken.cancel()
                    if not await self._say(writer, b"P\n"):
                        self._drop(room, slot)
                        return
        finally:
            eof.cancel()
        await slot["done"].wait()                    # the phone side runs the pipe; this keeps the writer open

    def _drop(self, room: str, slot: dict) -> None:
        pool = self.pools.get(room)
        if pool is not None:
            try:
                pool.remove(slot)
            except ValueError:
                pass
            if not pool:
                self.pools.pop(room, None)
        slot["done"].set()

    async def _phone(self, room: str, reader, writer) -> None:
        slot = None
        for _ in range(int(WAIT_PC_S / 0.25)):
            pool = self.pools.get(room)
            while pool:
                cand = pool.popleft()
                if not cand["writer"].is_closing():
                    slot = cand
                    break
                cand["done"].set()
            if pool is not None and not pool:
                self.pools.pop(room, None)
            if slot:
                break
            await asyncio.sleep(0.25)
        if slot is None:
            await self._say(writer, b"ERR nopc\n")
            return
        if self.pipes >= MAX_PIPES:
            slot["done"].set()
            await self._say(writer, b"ERR busy\n")
            return
        slot["taken"].set()
        eof = slot.get("eof")
        if eof is not None:                          # stop watching the idle PC side before the pipe reads from it
            eof.cancel()
            try:
                await eof
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        try:
            if not await self._say(slot["writer"], b"GO\n") or not await self._say(writer, b"OK\n"):
                return
            self.pipes += 1
            try:
                await asyncio.gather(_pipe(reader, slot["writer"]), _pipe(slot["reader"], writer))
            finally:
                self.pipes -= 1
        finally:
            _close(slot["writer"])
            slot["done"].set()


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await src.read(CHUNK)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionError, OSError, asyncio.IncompleteReadError):
        pass
    finally:
        _close(dst)


def _close(writer: asyncio.StreamWriter) -> None:
    try:
        writer.close()
    except Exception:  # noqa: BLE001
        pass


async def serve(key: str, host: str = "0.0.0.0", port: int = 8443):
    relay = Relay(key)
    server = await asyncio.start_server(relay.handle, host, port, reuse_address=True)
    return relay, server


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="JARVIS Relay")
    ap.add_argument("--port", type=int, default=int(os.environ.get("JARVIS_RELAY_PORT", "8443")))
    ap.add_argument("--host", default="::" if _has_v6() else "0.0.0.0")
    ap.add_argument("--key-file", default=os.environ.get("JARVIS_RELAY_KEY_FILE", "/etc/jarvis-relay.key"))
    args = ap.parse_args(argv)
    key = os.environ.get("JARVIS_RELAY_KEY", "")
    if not key:
        try:
            with open(args.key_file, encoding="utf-8") as f:
                key = f.read().strip()
        except OSError as e:
            print(f"Chybí přístupový klíč ({e}).", file=sys.stderr)
            return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    async def run():
        _, server = await serve(key, args.host, args.port)
        log.info("JARVIS Relay běží na portu %s", args.port)
        async with server:
            await server.serve_forever()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    return 0


def _has_v6() -> bool:
    import socket

    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.close()
        return True
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(main())
