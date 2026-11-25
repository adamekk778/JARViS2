"""3.17 Bambu Lab napřímo (návrh 17): a fake printer on this PC – MQTT over real TLS, the camera, the certificate pin."""
from __future__ import annotations

import asyncio
import datetime
import json
import ssl
from pathlib import Path

import pytest

from jarvis import bambu, minimqtt, printer3d, secrets, tools

JPEG = b"\xff\xd8" + b"\x00" * 300 + b"\xff\xd9"
REPORT = {"print": {"gcode_state": "RUNNING", "mc_percent": 42, "mc_remaining_time": 75, "subtask_name": "Držák",
                    "nozzle_temper": 219.6, "nozzle_target_temper": 220, "bed_temper": 55, "bed_target_temper": 55,
                    "layer_num": 30, "total_layer_num": 120}}


def _cert(tmp: Path, name: str) -> ssl.SSLContext:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30)).sign(key, hashes.SHA256()))
    (tmp / f"{name}.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp / f"{name}.key").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                        serialization.NoEncryption()))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp / f"{name}.pem", tmp / f"{name}.key")
    ctx.der = cert.public_bytes(serialization.Encoding.DER)  # type: ignore[attr-defined]
    return ctx


class FakePrinter:
    """MQTT broker + camera of a Bambu printer, serial 01P00A000000001, access code 12345678."""

    def __init__(self, ctx: ssl.SSLContext):
        self.ctx = ctx
        self.requests: list[dict] = []
        self.logins: list[tuple[str, str]] = []
        self.cam_auth: list[bytes] = []
        self.servers: list[asyncio.base_events.Server] = []
        self.ports: dict[int, int] = {}

    async def start(self):
        for real, handler in ((bambu.PORT_MQTT, self._mqtt), (bambu.PORT_CAM, self._cam)):
            srv = await asyncio.start_server(handler, "127.0.0.1", 0, ssl=self.ctx)
            self.servers.append(srv)
            self.ports[real] = srv.sockets[0].getsockname()[1]
        return self

    def opener(self, host, port, ssl=None):
        return asyncio.open_connection("127.0.0.1", self.ports[port], ssl=ssl)

    async def _mqtt(self, reader, writer):
        try:
            kind, _f, body = await minimqtt.read_packet(reader)
            assert kind == minimqtt.CONNECT
            n = int.from_bytes(body[10:12], "big")
            rest = body[12 + n:]
            u = rest[2:2 + int.from_bytes(rest[:2], "big")].decode()
            rest = rest[2 + len(u.encode()):]
            pw = rest[2:2 + int.from_bytes(rest[:2], "big")].decode()
            self.logins.append((u, pw))
            ok = (u, pw) == ("bblp", "12345678")
            writer.write(bytes([0x20, 2, 0, 0 if ok else 4]))
            await writer.drain()
            if not ok:
                return
            while True:
                kind, flags, body = await minimqtt.read_packet(reader)
                if kind == minimqtt.SUBSCRIBE:
                    writer.write(bytes([0x90, 3]) + body[:2] + b"\x00")
                elif kind == minimqtt.PUBLISH:
                    topic, payload = minimqtt.parse_publish(flags, body)
                    msg = json.loads(payload)
                    self.requests.append(msg)
                    if msg.get("pushing", {}).get("command") == "pushall":
                        writer.write(minimqtt.publish_packet("device/01P00A000000001/report", json.dumps({"info": {}}).encode()))
                        writer.write(minimqtt.publish_packet("device/01P00A000000001/report", json.dumps(REPORT).encode()))
                elif kind == minimqtt.DISCONNECT:
                    return
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError):
            pass
        finally:
            writer.close()

    async def _cam(self, reader, writer):
        try:
            self.cam_auth.append(await reader.readexactly(80))
            writer.write(len(JPEG).to_bytes(4, "little") + b"\x00" * 12 + JPEG)
            await writer.drain()
            await asyncio.sleep(0.05)
        finally:
            writer.close()

    async def stop(self):
        for s in self.servers:
            s.close()
            await s.wait_closed()


@pytest.fixture
async def printer(tmp_path):
    p = await FakePrinter(_cert(tmp_path, "printer")).start()
    yield p
    await p.stop()


@pytest.fixture
def lan(rt, monkeypatch):
    rt.update_config({"workshop": {"printer": "bambu_lan", "printer_url": "192.168.1.50", "bambu_serial": "01p00a000000001"}})
    store = {"printer": "12345678"}
    monkeypatch.setattr(secrets, "get", lambda name: store.get(name, ""))
    return rt


# ------------------------------------------------------------------------------------------ pure parts
def test_mqtt_packets_round_trip():
    assert minimqtt.varint(0) == b"\x00" and minimqtt.varint(321) == b"\xc1\x02" and minimqtt.varint(16384) == b"\x80\x80\x01"
    pkt = minimqtt.publish_packet("device/X/request", b'{"a":1}')
    assert pkt[0] == 0x30 and minimqtt.parse_publish(0, pkt[2:]) == ("device/X/request", b'{"a":1}')
    c = minimqtt.connect_packet("jarvis", "bblp", "code")
    assert c[0] == 0x10 and b"MQTT" in c and c.endswith(b"\x00\x04code")


def test_report_and_settings_helpers(lan):
    s = bambu.from_report(REPORT["print"])
    assert s["state"] == "printing" and s["progress"] == 42 and s["left_s"] == 4500 and s["layer"] == [30, 120]
    assert "Držák na 42 %" in printer3d.say(s, "Bambu")
    assert bambu.from_report({"gcode_state": "FAILED", "print_error": 50348044})["why"].startswith("chyba tiskárny")
    assert bambu.host(lan) == "192.168.1.50" and bambu.serial(lan) == "01P00A000000001" and bambu.problem(lan) == ""
    lan.update_config({"workshop": {"printer_url": "http://p1s.local:8883/x"}})
    assert bambu.host(lan) == "p1s.local"
    assert bambu.safe_name("../../Držák police v2.3MF") == "Držák_police_v2.3mf"
    assert bambu.safe_name("rm -rf ;.gcode") == "rm_-rf.gcode"
    auth = bambu.camera_auth("12345678")
    assert len(auth) == 80 and auth[16:20] == b"bblp" and auth[48:56] == b"12345678"


def test_pin_rules():
    ok, fp, why = bambu.pin_verdict("", b"cert-a")
    assert ok and len(fp) == 64 and not why                                    # the first time: remembered
    assert bambu.pin_verdict(fp, b"cert-a")[0]
    ok, _fp, why = bambu.pin_verdict(fp, b"cert-b")
    assert not ok and "změnil" in why
    assert not bambu.pin_verdict("", None)[0]


def test_missing_settings_say_what(rt, monkeypatch):
    monkeypatch.setattr(secrets, "get", lambda name: "")
    rt.update_config({"workshop": {"printer": "bambu_lan"}})
    assert "adresa" in bambu.problem(rt)
    rt.update_config({"workshop": {"printer_url": "10.0.0.5"}})
    assert "sériové" in bambu.problem(rt)
    rt.update_config({"workshop": {"bambu_serial": "01P"}})
    assert "přístupový kód" in bambu.problem(rt)


# ------------------------------------------------------------------------------------------ against the fake printer
async def test_status_over_tls_and_the_pin_is_remembered(lan, printer):
    assert lan.cfg.workshop.bambu_pin == ""
    s = await bambu.status(lan, printer.opener, wait_s=3)
    assert s["state"] == "printing" and s["file"] == "Držák" and s["nozzle"] == [219.6, 220.0]
    assert printer.logins == [("bblp", "12345678")]
    assert {"pushing": {"sequence_id": "0", "command": "pushall"}} in printer.requests
    assert len(lan.cfg.workshop.bambu_pin) == 64


async def test_a_different_printer_never_gets_the_code(lan, printer):
    lan.update_config({"workshop": {"bambu_pin": "0" * 64}})                     # paired with another certificate
    with pytest.raises(minimqtt.MQTTError, match="změnil"):
        await bambu.status(lan, printer.opener, wait_s=2)
    await asyncio.sleep(0.05)
    assert printer.logins == []                                                  # the access code was not sent
    assert await bambu.snapshot(lan, printer.opener) is None and printer.cam_auth == []


async def test_wrong_access_code(lan, printer, monkeypatch):
    monkeypatch.setattr(secrets, "get", lambda name: "00000000")
    with pytest.raises(minimqtt.MQTTError, match="přístupový kód"):
        await bambu.status(lan, printer.opener, wait_s=2)


async def test_commands_and_camera(lan, printer):
    assert await bambu.command(lan, "pause", printer.opener) == ""
    assert await bambu.command(lan, "cancel", printer.opener) == ""
    await asyncio.sleep(0.1)
    cmds = [r["print"]["command"] for r in printer.requests if "print" in r]
    assert cmds == ["pause", "stop"]
    assert await bambu.command(lan, "format_sd", printer.opener) == "neznámý příkaz"
    jpg = await bambu.snapshot(lan, printer.opener)
    assert jpg == JPEG and printer.cam_auth[0][48:56] == b"12345678"
    lan.update_config({"workshop": {"bambu_model": "x1"}})
    assert await bambu.snapshot(lan, printer.opener) is None                    # X1: never the code to an unchecked RTSP


async def test_upload_and_print(lan, printer, tmp_path):
    calls: list = []
    der = printer.ctx.der                                                       # FTPS and MQTT: the same printer certificate

    class FakeFTP:
        def __init__(self, context=None, timeout=None):
            self.sock = self

        def getpeercert(self, binary_form=False):
            return der

        def connect(self, host, port):
            calls.append(("connect", host, port))

        def login(self, u, p):
            calls.append(("login", u, p))

        def prot_p(self):
            calls.append(("prot_p",))

        def storbinary(self, cmd, f):
            calls.append(("stor", cmd, len(f.read())))

        def quit(self):
            pass

        def close(self):
            pass
    model = tmp_path / "Držák police.3mf"
    model.write_bytes(b"PK" + b"0" * 100)
    err = await bambu.upload_and_print(lan, model, True, printer.opener, FakeFTP)
    assert lan.cfg.workshop.bambu_pin == __import__("hashlib").sha256(der).hexdigest()       # paired by the upload
    assert err == "" and ("connect", "192.168.1.50", 990) in calls and ("login", "bblp", "12345678") in calls
    assert ("stor", "STOR Držák_police.3mf", 102) in calls
    await asyncio.sleep(0.1)
    job = [r["print"] for r in printer.requests if r.get("print", {}).get("command") == "project_file"][0]
    assert job["url"] == "file:///sdcard/Držák_police.3mf" and job["use_ams"] is False
    calls.clear()
    lan.update_config({"workshop": {"bambu_pin": "f" * 64}})
    assert "změnil" in await bambu.upload_and_print(lan, model, True, printer.opener, FakeFTP)
    assert not any(c[0] == "login" for c in calls)                              # pin first, login never
    stl = tmp_path / "x.stl"
    stl.write_bytes(b"solid")
    assert ".3mf" in await bambu.upload_and_print(lan, stl, True, printer.opener, FakeFTP)


async def test_printer_tool_goes_through_bambu(lan, monkeypatch, tmp_path):
    tools.load_builtin()
    seen: list = []

    async def status(rt, opener=None, wait_s=8.0):
        return bambu.from_report(REPORT["print"])

    async def upload(rt, path, start=True, opener=None, ftp_factory=None):
        seen.append(path.name)
        return ""
    monkeypatch.setattr(bambu, "status", status)
    monkeypatch.setattr(bambu, "upload_and_print", upload)
    r = await tools.call("printer_control", {"action": "status"}, lan)
    assert r.ok and "42 %" in r.summary
    f = tmp_path / "díl.3mf"
    f.write_bytes(b"PK")
    r = await tools.call("printer_control", {"action": "print", "file": str(f)}, lan)
    assert seen == ["díl.3mf"]                                                   # a sliced .3mf is not sliced again
