"""The PC's side of the relay: keep a few connections open to your relay server; each one the relay hands a phone
to is bridged to this PC's own TLS port (the encryption stays end to end, phone ↔ PC)."""
from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger(__name__)

POOL = 2
IDLE_TIMEOUT_S = 95          # the relay pings every 30 s; silence this long = the connection is dead
CHUNK = 65536


async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await src.read(CHUNK)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            dst.close()
        except Exception:  # noqa: BLE001
            pass


class RelayAgent:
    def __init__(self, host: str, port: int, key: str, room: str, local_port: int):
        self.host, self.port, self.key, self.room, self.local_port = host, port, key, room, local_port
        self.ready = 0               # idle connections waiting at the relay right now
        self.bridges = 0
        self.error = ""
        self.last_ok = 0.0
        self._tasks: list[asyncio.Task] = []
        self._bridging: set[asyncio.Task] = set()   # strong references: a task nobody holds can be garbage-collected

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._slot(i)) for i in range(POOL)]

    def stop(self) -> None:
        for t in self._tasks + list(self._bridging):
            t.cancel()
        self._tasks = []
        self.ready = 0

    def status(self) -> dict:
        return {"connected": self.ready > 0, "ready": self.ready, "active": self.bridges, "error": self.error,
                "last_ok": self.last_ok}

    async def _slot(self, i: int) -> None:
        backoff = 2.0
        while True:
            try:
                await self._once()
                backoff = 2.0
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.error = _why(e)
                log.debug("relay slot %s: %s", i, self.error)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _once(self) -> None:
        r, w = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), 10)
        idle = False
        try:
            w.write(f"JRL1 {self.key} pc {self.room}\n".encode())
            await w.drain()
            line = (await asyncio.wait_for(r.readline(), 10)).strip()
            if line != b"OK":
                raise ConnectionError(line.decode("ascii", "replace") or "relay closed")
            self.error = ""
            self.last_ok = time.time()
            idle = True
            self.ready += 1
            while True:
                line = (await asyncio.wait_for(r.readline(), IDLE_TIMEOUT_S)).strip()
                if line == b"P":
                    self.last_ok = time.time()
                    continue
                if line == b"GO":
                    break
                raise ConnectionError("relay closed")
        except BaseException:
            if idle:
                self.ready -= 1
            w.close()
            raise
        self.ready -= 1
        # a phone is here: bridge it to our own TLS port in the background; this slot reconnects at once
        t = asyncio.get_running_loop().create_task(self._bridge(r, w))
        self._bridging.add(t)
        t.add_done_callback(self._bridging.discard)

    async def _bridge(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        self.bridges += 1
        try:
            lr, lw = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", self.local_port), 5)
        except Exception as e:  # noqa: BLE001
            self.bridges -= 1
            self.error = _why(e)
            w.close()
            return
        try:
            await asyncio.gather(pipe(r, lw), pipe(lr, w))
        finally:
            self.bridges -= 1


def _why(e: BaseException) -> str:
    if isinstance(e, asyncio.TimeoutError):
        return "relay neodpovídá"
    s = str(e) or e.__class__.__name__
    if "ERR auth" in s:
        return "špatný přístupový klíč relay"
    if "ERR full" in s:
        return "relay je plný"
    return s[:160]
