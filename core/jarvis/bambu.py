"""3.17 Bambu Lab napřímo (návrh 17): the printer on your home network without Home Assistant or the cloud.

The printer in "LAN režim" (or with "LAN only liveview" + developer mode) speaks:
- MQTT over TLS on port 8883 (user "bblp", password = the access code from the printer's screen): the state
  (device/<serial>/report) and the commands pause / resume / stop and "print this file" (device/<serial>/request),
- FTPS on port 990 (the same login): a .3mf from Bambu Studio / Orca, or a .gcode, goes onto the printer's card,
- the camera on port 6000 (P1 and A1 series): one JPEG picture for the failed-print watch. The X1's RTSP camera is
  not used directly (it would send the access code without a checked certificate) – use the camera URL in Settings.

The printer has its own self-signed certificate, so JARVIS remembers its SHA-256 fingerprint at the first connection
and from then on refuses any other one (a different device on the network never gets the access code). The access
code is in the keyring ("printer"), never in the settings.
"""
from __future__ import annotations

import asyncio
import ftplib
import hashlib
import hmac
import json
import logging
import re
import ssl
import struct
import time
from pathlib import Path
from typing import Any, Callable

from . import secrets
from .minimqtt import Client, MQTTError

log = logging.getLogger("jarvis.bambu")

PORT_MQTT, PORT_FTPS, PORT_CAM = 8883, 990, 6000
USER = "bblp"
STATE = {"RUNNING": "printing", "PREPARE": "printing", "SLICING": "printing", "PAUSE": "paused", "FINISH": "done",
         "FAILED": "error", "IDLE": "idle"}
ACTIONS = {"pause": "pause", "resume": "resume", "cancel": "stop"}
MAX_JPEG = 5 * 1024 * 1024
Opener = Callable[..., Any]


def cfg(rt: Any) -> Any:
    return rt.cfg.workshop


def host(rt: Any) -> str:
    """"192.168.1.50", "http://p1s.local", "p1s.local:8883" → the host only."""
    h = re.sub(r"^[a-z]+://", "", (cfg(rt).printer_url or "").strip(), flags=re.I)
    return re.split(r"[:/]", h, maxsplit=1)[0]


def serial(rt: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", cfg(rt).bambu_serial or "").upper()


def problem(rt: Any) -> str:
    """'' when everything needed is set, else what is missing."""
    if not host(rt):
        return "chybí adresa tiskárny (IP z obrazovky tiskárny)"
    if not serial(rt):
        return "chybí sériové číslo tiskárny"
    if not secrets.get("printer"):
        return "chybí přístupový kód (Nastavení → Dílna → Přístupový kód)"
    return ""


def context() -> ssl.SSLContext:
    """The printer's certificate is self-signed: no CA check, but the fingerprint is pinned (pin_verdict)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def pin_verdict(pinned: str, der: bytes | None) -> tuple[bool, str, str]:
    """(ok, fingerprint, why). An empty pin = the first connection: this certificate becomes the printer's."""
    if not der:
        return False, "", "tiskárna neposlala certifikát"
    fp = hashlib.sha256(der).hexdigest()
    if not pinned or hmac.compare_digest(pinned.lower(), fp):
        return True, fp, ""
    return False, fp, ("certifikát tiskárny se změnil – jestli jsi tiskárnu měnil nebo resetoval, smaž v Nastavení → Dílna "
                       "otisk certifikátu; jinak se na síti vydává za tiskárnu jiné zařízení")


def _remember_pin(rt: Any, fp: str) -> None:
    if fp and not cfg(rt).bambu_pin:
        rt.update_config({"workshop": {"bambu_pin": fp}})


async def _open(rt: Any, port: int, opener: Opener | None = None) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.wait_for((opener or asyncio.open_connection)(host(rt), port, ssl=context()), 8)
    so = writer.get_extra_info("ssl_object")
    ok, fp, why = pin_verdict(cfg(rt).bambu_pin, so.getpeercert(binary_form=True) if so else None)
    if not ok:
        writer.close()
        raise MQTTError(why)
    _remember_pin(rt, fp)
    return reader, writer


async def _mqtt(rt: Any, opener: Opener | None = None) -> Client:
    reader, writer = await _open(rt, PORT_MQTT, opener)
    return await Client.connect(reader, writer, f"jarvis-{int(time.time())}", USER, secrets.get("printer") or "")


def from_report(p: dict) -> dict:
    """The printer's "print" report → the same state the other printers give (printer3d.status)."""
    def num(k: str) -> float:
        try:
            return float(p.get(k) or 0)
        except (TypeError, ValueError):
            return 0.0
    st = STATE.get(str(p.get("gcode_state") or "").upper(), "idle")
    out = {"state": st, "file": str(p.get("subtask_name") or p.get("gcode_file") or ""), "progress": num("mc_percent"),
           "left_s": int(num("mc_remaining_time") * 60), "elapsed_s": 0,
           "nozzle": [round(num("nozzle_temper"), 1), round(num("nozzle_target_temper"), 1)],
           "bed": [round(num("bed_temper"), 1), round(num("bed_target_temper"), 1)]}
    if p.get("total_layer_num"):
        out["layer"] = [int(num("layer_num")), int(num("total_layer_num"))]
    if p.get("print_error") and st == "error":
        out["why"] = f"chyba tiskárny {p['print_error']}"
    return out


def _request(cmd: str, **extra: Any) -> dict:
    return {"print": {"sequence_id": str(int(time.time()) % 100000), "command": cmd, **extra}}


async def status(rt: Any, opener: Opener | None = None, wait_s: float = 8.0) -> dict:
    why = problem(rt)
    if why:
        return {"state": "offline", "why": why}
    cl = await _mqtt(rt, opener)
    try:
        sn = serial(rt)
        await cl.subscribe(f"device/{sn}/report")
        await cl.publish(f"device/{sn}/request", {"pushing": {"sequence_id": "0", "command": "pushall"}})
        loop = asyncio.get_running_loop()
        end = loop.time() + wait_s
        while (left := end - loop.time()) > 0:
            msg = await cl.next_message(left)
            if msg is None:
                break
            try:
                p = (json.loads(msg[1]) or {}).get("print") or {}
            except ValueError:
                continue
            if "gcode_state" in p:
                return from_report(p)
        return {"state": "offline", "why": "tiskárna neposlala stav"}
    finally:
        await cl.close()


async def command(rt: Any, action: str, opener: Opener | None = None) -> str:
    """pause / resume / cancel → '' on success, else the reason."""
    if action not in ACTIONS:
        return "neznámý příkaz"
    why = problem(rt)
    if why:
        return why
    cl = await _mqtt(rt, opener)
    try:
        await cl.publish(f"device/{serial(rt)}/request", _request(ACTIONS[action], param=""))
        return ""
    finally:
        await cl.close()


# ------------------------------------------------------------------------------------------ a file onto the printer
class ImplicitFTPS(ftplib.FTP_TLS):
    """FTPS with TLS from the first byte (port 990) and the data connection reusing the TLS session (the printer
    insists on that)."""

    def __init__(self, *a: Any, **kw: Any):
        self._sock: Any = None
        super().__init__(*a, **kw)

    @property  # type: ignore[override]
    def sock(self) -> Any:
        return self._sock

    @sock.setter
    def sock(self, value: Any) -> None:
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value

    def ntransfercmd(self, cmd: str, rest: Any = None) -> tuple[Any, int | None]:
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:  # type: ignore[attr-defined]
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


def safe_name(name: str) -> str:
    stem, dot, ext = Path(name).name.rpartition(".")
    stem = re.sub(r"[^\w.-]+", "_", stem or ext)[:60].strip("._") or "jarvis"
    return f"{stem}.{ext.lower()}" if dot else stem


def project_payload(name: str, use_ams: bool = False, plate: int = 1) -> dict:
    return _request("project_file", param=f"Metadata/plate_{plate}.gcode", project_id="0", profile_id="0", task_id="0",
                    subtask_id="0", subtask_name=Path(name).stem, url=f"file:///sdcard/{name}", md5="", timelapse=False,
                    bed_type="auto", bed_leveling=True, flow_cali=False, vibration_cali=False, layer_inspect=False,
                    use_ams=bool(use_ams), ams_mapping=[])


def _put(host_: str, code: str, pinned: str, path: Path, name: str, factory: Callable[..., Any] | None) -> tuple[str, str]:
    """In a thread: (why, fingerprint) – why '' = uploaded."""
    ftp = (factory or ImplicitFTPS)(context=context(), timeout=30)
    try:
        ftp.connect(host_, PORT_FTPS)
        ok, fp, why = pin_verdict(pinned, ftp.sock.getpeercert(binary_form=True))
        if not ok:
            return why, fp
        ftp.login(USER, code)
        ftp.prot_p()
        with open(path, "rb") as f:
            ftp.storbinary(f"STOR {name}", f)
        try:
            ftp.quit()
        except Exception:  # noqa: BLE001
            pass
        return "", fp
    except (OSError, ftplib.Error) as e:
        return f"nahrání se nepovedlo: {e}"[:160], ""
    finally:
        try:
            ftp.close()
        except Exception:  # noqa: BLE001
            pass


async def upload_and_print(rt: Any, path: Path, start: bool = True, opener: Opener | None = None,
                           ftp_factory: Callable[..., Any] | None = None) -> str:
    why = problem(rt)
    if why:
        return why
    ext = path.suffix.lower()
    if ext not in (".3mf", ".gcode"):
        return "Bambu tiskne .3mf (uložený z Bambu Studia nebo Orcy jako „vyslicovaný“) nebo .gcode"
    name = safe_name(path.name)
    why, fp = await asyncio.to_thread(_put, host(rt), secrets.get("printer") or "", cfg(rt).bambu_pin, path, name, ftp_factory)
    if why:
        return why
    _remember_pin(rt, fp)
    if not start:
        return ""
    payload = project_payload(name, cfg(rt).bambu_ams) if ext == ".3mf" else _request("gcode_file", param=f"/sdcard/{name}")
    cl = await _mqtt(rt, opener)
    try:
        await cl.publish(f"device/{serial(rt)}/request", payload)
    finally:
        await cl.close()
    return ""


# ------------------------------------------------------------------------------------------ the camera (P1 / A1)
def camera_auth(code: str) -> bytes:
    return struct.pack("<IIII", 0x40, 0x3000, 0, 0) + USER.encode().ljust(32, b"\0") + code.encode()[:32].ljust(32, b"\0")


async def snapshot(rt: Any, opener: Opener | None = None) -> bytes | None:
    """One JPEG from the P1 / A1 camera (port 6000), or None."""
    if problem(rt) or cfg(rt).bambu_model == "x1":
        return None
    try:
        reader, writer = await _open(rt, PORT_CAM, opener)
    except Exception as e:  # noqa: BLE001
        log.debug("bambu camera: %s", e)
        return None
    try:
        writer.write(camera_auth(secrets.get("printer") or ""))
        await writer.drain()
        head = await asyncio.wait_for(reader.readexactly(16), 8)
        size = int.from_bytes(head[:4], "little")
        if not 100 < size <= MAX_JPEG:
            return None
        jpg = await asyncio.wait_for(reader.readexactly(size), 8)
        return jpg if jpg[:2] == b"\xff\xd8" and jpg[-2:] == b"\xff\xd9" else None
    except Exception as e:  # noqa: BLE001
        log.debug("bambu camera: %s", e)
        return None
    finally:
        writer.close()
