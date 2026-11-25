"""3.14 Roboti (návrhy 12, 57, 58): the robot vacuum and the lawn mower through Home Assistant, and a DJI Tello drone.

Vysavač / sekačka: any vacuum (Roborock, Dreame, Ecovacs, iRobot…) or lawn mower (Husqvarna, Worx, Gardena…) in Home
Assistant. "Ukliď kuchyň" cleans only that room when you map the room to its segment numbers (Roborock / Xiaomi app
segments – Nastavení → Domov → Vysavač), otherwise the whole flat. Starting the mower always asks first.

Dron (DJI Tello / Tello EDU, the PC on the drone's Wi-Fi): voice commands with hard limits – indoors only, at most
1,5 m high, at most 1 m per move, at most 2 minutes in the air (then it lands by itself), take-off only above 25 %
battery and always after your yes. Any error → it lands. "Nouzově vypni" stops the motors at once (it falls!).
"""
from __future__ import annotations

import asyncio
import logging
import re
import socket
import threading
import time
from typing import Any, Callable

log = logging.getLogger("jarvis.robots")

# ---------------------------------------------------------------------------------------------- vacuum + mower (HA)
VACUUM_STATE = {"cleaning": "uklízí", "docked": "stojí v doku", "returning": "vrací se do doku", "idle": "stojí",
                "paused": "pozastavený", "error": "hlásí chybu", "unavailable": "není dostupný"}
MOWER_STATE = {"mowing": "seče", "docked": "stojí v doku", "paused": "pozastavená", "returning": "vrací se do doku",
               "error": "hlásí chybu", "unavailable": "není dostupná"}


def _fold(s: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower()) if not unicodedata.combining(c)).strip()


async def devices(rt: Any) -> dict[str, list[dict]]:
    states = await rt.home.states(fresh=True)
    return {"vacuum": [e for e in states if e["domain"] == "vacuum"], "mower": [e for e in states if e["domain"] == "lawn_mower"]}


async def status(rt: Any) -> tuple[str, dict]:
    d = await devices(rt)
    bits = []
    for e in d["vacuum"]:
        bat = f", baterie {int(e['battery'])} %" if e.get("battery") is not None else ""
        bits.append(f"{e['name']} {VACUUM_STATE.get(e['state'], e['state'])}{bat}")
    for e in d["mower"]:
        bits.append(f"{e['name']} {MOWER_STATE.get(e['state'], e['state'])}")
    if not bits:
        return "V Home Assistantu nevidím žádný vysavač ani sekačku.", d
    return "; ".join(bits) + ".", d


def rooms_for(rt: Any, room: str) -> list[int]:
    """Segment numbers of a room (Nastavení → Domov → Vysavač: místnost → čísla segmentů)."""
    want = _fold(room)
    for name, segs in (getattr(rt.cfg.home, "vacuum_rooms", None) or {}).items():
        if _fold(name) == want or (want and want[:4] == _fold(name)[:4]):
            return [int(s) for s in segs]
    return []


async def vacuum(rt: Any, action: str, room: str = "") -> str:
    d = (await devices(rt))["vacuum"]
    if not d:
        raise LookupError("V Home Assistantu nevidím žádný robotický vysavač.")
    eid = d[0]["id"]
    if action == "clean":
        segs = rooms_for(rt, room) if room else []
        if segs:
            await rt.home.service("vacuum", "send_command", {"entity_id": eid, "command": "app_segment_clean", "params": segs})
            return f"Vysavač jede uklidit {room}."
        await rt.home.service("vacuum", "start", {"entity_id": eid})
        return "Vysavač uklízí celý byt." + (f" (Místnost „{room}“ nemám přiřazenou – nastav ji v Nastavení → Domov → Vysavač.)"
                                             if room else "")
    service = {"dock": "return_to_base", "pause": "pause", "stop": "stop", "locate": "locate"}.get(action)
    if not service:
        raise ValueError("Vysavač umí: uklidit, pauza, stop, domů, najít.")
    await rt.home.service("vacuum", service, {"entity_id": eid})
    return {"dock": "Vysavač se vrací do doku.", "pause": "Vysavač pozastaven.", "stop": "Vysavač zastaven.",
            "locate": "Vysavač se ozve, ať ho najdeš."}[action]


async def mower(rt: Any, action: str) -> str:
    d = (await devices(rt))["mower"]
    if not d:
        raise LookupError("V Home Assistantu nevidím žádnou robotickou sekačku.")
    service = {"start": "start_mowing", "pause": "pause", "dock": "dock"}.get(action)
    if not service:
        raise ValueError("Sekačka umí: sekat, pauza, domů.")
    await rt.home.service("lawn_mower", service, {"entity_id": d[0]["id"]})
    return {"start": "Sekačka začíná sekat.", "pause": "Sekačka pozastavena.", "dock": "Sekačka jede domů."}[action]


# ---------------------------------------------------------------------------------------------- the drone (DJI Tello)
TELLO = ("192.168.10.1", 8889)
MAX_HEIGHT_CM, MAX_MOVE_CM, MIN_MOVE_CM = 150, 100, 20
MAX_FLIGHT_S, MIN_BATTERY, KEEPALIVE_S = 120, 25, 8
TAKEOFF_HEIGHT_CM = 80
MOVES = {"up": "nahoru", "down": "dolů", "left": "doleva", "right": "doprava", "forward": "dopředu", "back": "dozadu"}


class DroneError(RuntimeError):
    pass


def udp_sender(addr: tuple[str, int] = TELLO, timeout: float = 7.0) -> Callable[[str], str]:
    """Send one SDK command, wait for the answer ("ok", "error", a number)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 0))
    sock.settimeout(timeout)
    lock = threading.Lock()

    def send(cmd: str) -> str:
        with lock:
            sock.sendto(cmd.encode(), addr)
            try:
                data, _ = sock.recvfrom(1024)
            except socket.timeout as e:
                raise DroneError("dron neodpovídá – je PC připojené k jeho Wi-Fi (TELLO-…)?") from e
            return data.decode("utf-8", "replace").strip()
    return send


class Drone:
    """One Tello with the safety limits. `send` is the SDK link (UDP; a fake in the tests)."""

    def __init__(self, send: Callable[[str], str] | None = None, clock: Callable[[], float] = time.monotonic):
        self._send = send
        self.clock = clock
        self.flying = False
        self.height = 0
        self.took_off_at = 0.0
        self.last_cmd = 0.0
        self._guard: asyncio.Task | None = None

    def link(self) -> Callable[[str], str]:
        if self._send is None:
            self._send = udp_sender()
        return self._send

    async def cmd(self, c: str, expect_ok: bool = True) -> str:
        out = await asyncio.to_thread(self.link(), c)
        self.last_cmd = self.clock()
        if expect_ok and out.lower() != "ok":
            raise DroneError(f"dron odmítl „{c}“: {out}")
        return out

    async def connect(self) -> int:
        await self.cmd("command")
        return await self.battery()

    async def battery(self) -> int:
        out = await self.cmd("battery?", expect_ok=False)
        m = re.search(r"\d+", out)
        if not m:
            raise DroneError(f"nerozumím stavu baterie: {out}")
        return int(m.group(0))

    async def takeoff(self) -> str:
        if self.flying:
            return "Dron už letí."
        bat = await self.connect()
        if bat < MIN_BATTERY:
            raise DroneError(f"baterie má jen {bat} % – pod {MIN_BATTERY} % nevzlétnu")
        await self.cmd("takeoff")
        self.flying, self.height, self.took_off_at = True, TAKEOFF_HEIGHT_CM, self.clock()
        self._start_guard()
        return f"Vzlétl jsem (baterie {bat} %). Nejvýš {MAX_HEIGHT_CM / 100:g} m, za {MAX_FLIGHT_S // 60} minuty přistanu sám."

    async def land(self) -> str:
        if not self.flying:
            return "Dron stojí na zemi."
        try:
            await self.cmd("land")
        finally:
            self.flying, self.height = False, 0
            self._stop_guard()
        return "Přistávám."

    async def emergency(self) -> str:
        """Motors off at once – the drone falls. Only on an explicit "nouzově vypni"."""
        try:
            await self.cmd("emergency", expect_ok=False)
        finally:
            self.flying, self.height = False, 0
            self._stop_guard()
        return "Motory vypnuty."

    async def move(self, direction: str, cm: float) -> str:
        if not self.flying:
            raise DroneError("dron neletí – nejdřív „vzlétni“")
        if direction not in MOVES:
            raise DroneError("směr: nahoru, dolů, doleva, doprava, dopředu, dozadu")
        dist = int(max(MIN_MOVE_CM, min(abs(float(cm or 0)) or 50, MAX_MOVE_CM)))
        if direction == "up":
            dist = min(dist, MAX_HEIGHT_CM - self.height)
            if dist < MIN_MOVE_CM:
                return f"Výš nepoletím – limit je {MAX_HEIGHT_CM / 100:g} m."
        if direction == "down":
            dist = min(dist, max(0, self.height - 30))
            if dist < MIN_MOVE_CM:
                return "Níž už ne – raději přistanu („přistaň“)."
        try:
            await self.cmd(f"{direction} {dist}")
        except Exception:
            await self._safe_land()
            raise
        self.height += dist if direction == "up" else -dist if direction == "down" else 0
        return f"Letím {MOVES[direction]} {dist} cm."

    async def turn(self, degrees: float) -> str:
        if not self.flying:
            raise DroneError("dron neletí")
        deg = int(max(-360, min(360, float(degrees or 90))))
        if abs(deg) < 1:
            return "Otočení o 0° – nic."
        try:
            await self.cmd(f"{'cw' if deg > 0 else 'ccw'} {abs(deg)}")
        except Exception:
            await self._safe_land()
            raise
        return f"Otáčím se o {abs(deg)}° {'doprava' if deg > 0 else 'doleva'}."

    async def room_tour(self, side_cm: float = 100) -> str:
        """A square around the room at a safe height, then land."""
        if not self.flying:
            await self.takeoff()
        side = max(MIN_MOVE_CM, min(float(side_cm or 100), MAX_MOVE_CM))
        for _ in range(4):
            await self.move("forward", side)
            await self.turn(90)
        await self.land()
        return f"Obletěl jsem čtverec {int(side)} × {int(side)} cm a přistál."

    async def photo(self, grab: Callable[[], bytes] | None = None) -> bytes:
        """One picture from the camera (the video stream through OpenCV)."""
        await self.cmd("streamon")
        try:
            return await asyncio.to_thread(grab or _grab_stream)
        finally:
            try:
                await self.cmd("streamoff", expect_ok=False)
            except Exception:  # noqa: BLE001
                pass

    async def _safe_land(self) -> None:
        try:
            await self.cmd("land", expect_ok=False)
        except Exception as e:  # noqa: BLE001
            log.warning("drone safe land: %s", e)
        self.flying, self.height = False, 0
        self._stop_guard()

    # the guard: keeps the link alive (Tello lands by itself after 15 s of silence) and lands after MAX_FLIGHT_S
    def _start_guard(self) -> None:
        self._stop_guard()
        try:
            self._guard = asyncio.get_running_loop().create_task(self._watch())
        except RuntimeError:
            self._guard = None

    def _stop_guard(self) -> None:
        g, self._guard = self._guard, None
        if g is not None and g is not asyncio.current_task():
            g.cancel()

    async def guard_step(self) -> str:
        """One look: land when the time is up, otherwise keep the link alive. Returns what it did."""
        if not self.flying:
            return "idle"
        if self.clock() - self.took_off_at >= MAX_FLIGHT_S:
            await self._safe_land()
            return "landed"
        if self.clock() - self.last_cmd >= KEEPALIVE_S:
            try:
                bat = await self.battery()
                if bat < 15:
                    await self._safe_land()
                    return "landed"
            except Exception:  # noqa: BLE001
                await self._safe_land()
                return "landed"
            return "alive"
        return "wait"

    async def _watch(self) -> None:
        while self.flying:
            await asyncio.sleep(2)
            if await self.guard_step() == "landed":
                break


def _grab_stream() -> bytes:
    import cv2

    cap = cv2.VideoCapture("udp://@0.0.0.0:11111", cv2.CAP_FFMPEG)
    try:
        frame = None
        for _ in range(60):                          # the first frames are grey until a key frame arrives
            ok, f = cap.read()
            if ok and f is not None:
                frame = f
        if frame is None:
            raise DroneError("z kamery dronu nepřišel obraz")
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return bytes(buf) if ok else b""
    finally:
        cap.release()


def drone(rt: Any) -> Drone:
    d = getattr(rt, "_drone", None)
    if d is None:
        d = rt._drone = Drone()
    return d
