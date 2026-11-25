"""3.17 A small MQTT 3.1.1 client (QoS 0 only) – enough for the Bambu Lab printers' local MQTT, without a new library.

Only what a printer needs: CONNECT with a user and password, SUBSCRIBE, PUBLISH (QoS 0), PINGREQ and DISCONNECT, over a
stream the caller opens (TLS for the printer, plain streams in the tests).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

CONNECT, CONNACK, PUBLISH, SUBSCRIBE, SUBACK, PINGREQ, PINGRESP, DISCONNECT = 1, 2, 3, 8, 9, 12, 13, 14
MAX_PACKET = 2 * 1024 * 1024           # a printer report is a few kB; anything this big is not a printer
CONNACK_WHY = {1: "nepodporovaná verze MQTT", 2: "odmítnuté ID klienta", 3: "služba nedostupná",
               4: "špatné jméno nebo přístupový kód", 5: "nepovoleno"}


class MQTTError(Exception):
    pass


def varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n % 128, n // 128
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _s(text: str) -> bytes:
    b = text.encode("utf-8")
    return len(b).to_bytes(2, "big") + b


def _packet(kind: int, flags: int, body: bytes) -> bytes:
    return bytes([(kind << 4) | flags]) + varint(len(body)) + body


def connect_packet(client_id: str, username: str = "", password: str = "", keepalive: int = 60) -> bytes:
    flags = 0x02 | (0x80 if username else 0) | (0x40 if password else 0)      # clean session
    body = _s("MQTT") + bytes([4, flags]) + keepalive.to_bytes(2, "big") + _s(client_id)
    if username:
        body += _s(username)
    if password:
        body += _s(password)
    return _packet(CONNECT, 0, body)


def subscribe_packet(pid: int, topic: str) -> bytes:
    return _packet(SUBSCRIBE, 0x02, pid.to_bytes(2, "big") + _s(topic) + b"\x00")


def publish_packet(topic: str, payload: bytes) -> bytes:
    return _packet(PUBLISH, 0, _s(topic) + payload)


def parse_publish(flags: int, body: bytes) -> tuple[str, bytes]:
    n = int.from_bytes(body[:2], "big")
    topic = body[2:2 + n].decode("utf-8", "replace")
    rest = body[2 + n:]
    if (flags >> 1) & 0x03:                    # QoS 1/2 carry a packet id
        rest = rest[2:]
    return topic, rest


async def read_packet(reader: asyncio.StreamReader) -> tuple[int, int, bytes]:
    """(type, flags, body)."""
    head = await reader.readexactly(1)
    mult, size = 1, 0
    for _ in range(4):
        b = (await reader.readexactly(1))[0]
        size += (b & 0x7F) * mult
        if not b & 0x80:
            break
        mult *= 128
    else:
        raise MQTTError("vadná délka zprávy")
    if size > MAX_PACKET:
        raise MQTTError("zpráva je moc velká")
    return head[0] >> 4, head[0] & 0x0F, await reader.readexactly(size) if size else b""


class Client:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer
        self._pid = 0

    @classmethod
    async def connect(cls, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, client_id: str, username: str = "",
                      password: str = "", timeout: float = 8.0) -> "Client":
        c = cls(reader, writer)
        writer.write(connect_packet(client_id, username, password))
        await writer.drain()
        kind, _f, body = await asyncio.wait_for(read_packet(reader), timeout)
        if kind != CONNACK or len(body) < 2:
            await c.close()
            raise MQTTError("tiskárna neodpověděla jako MQTT")
        if body[1]:
            await c.close()
            raise MQTTError(CONNACK_WHY.get(body[1], f"odmítnuto ({body[1]})"))
        return c

    async def subscribe(self, topic: str) -> None:
        self._pid = self._pid % 65535 + 1
        self.writer.write(subscribe_packet(self._pid, topic))
        await self.writer.drain()

    async def publish(self, topic: str, payload: Any) -> None:
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.writer.write(publish_packet(topic, data))
        await self.writer.drain()

    async def ping(self) -> None:
        self.writer.write(bytes([PINGREQ << 4, 0]))
        await self.writer.drain()

    async def next_message(self, timeout: float) -> tuple[str, bytes] | None:
        """The next PUBLISH (other packets are skipped), or None after the timeout."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            left = end - loop.time()
            if left <= 0:
                return None
            try:
                kind, flags, body = await asyncio.wait_for(read_packet(self.reader), left)
            except asyncio.TimeoutError:
                return None
            if kind == PUBLISH:
                return parse_publish(flags, body)

    async def close(self) -> None:
        try:
            self.writer.write(bytes([DISCONNECT << 4, 0]))
            await self.writer.drain()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.writer.close()
            await asyncio.wait_for(self.writer.wait_closed(), 2)
        except Exception:  # noqa: BLE001
            pass
