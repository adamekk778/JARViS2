"""OMEGA wave 2: PC rescue probes + analyzers (fed with recorded Windows output), the diagnose mission with a verified
report, performance (sample, bottlenecks, benchmark, history), network and security checks, the never-run commands."""
import base64
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jarvis import netdiag, perf, rescue, secutils, tools
from jarvis.tools.rescue_tools import _areas
from jarvis.tools.shell import never_reason


def fake_runner(outputs: dict):
    """Answers each probe by the first key of its decoded script: {probe_key: json_dict}."""
    calls = []

    def run(cmd, timeout):
        calls.append(cmd)
        if "-EncodedCommand" in cmd:
            script = base64.b64decode(cmd[cmd.index("-EncodedCommand") + 1]).decode("utf-16-le")
            for name, p in rescue.PROBES.items():
                if p["script"] in script:
                    out = outputs.get(name)
                    if out is None:
                        return None, "", ""
                    return 0, json.dumps(out), ""
        return 1, "", "neznámý příkaz"
    run.calls = calls
    return run


def levels(fs):
    return [f["level"] for f in fs]


# ---------------------------------------------------------------------------------------------- probes
def test_every_probe_is_read_only_and_has_an_analyzer():
    for name, p in rescue.PROBES.items():
        used = rescue.cmdlets(p["script"])
        assert used, name
        assert used <= rescue.ALLOWED, (name, used - rescue.ALLOWED)
        assert not any(c.split("-")[0] in ("Set", "Remove", "New", "Stop", "Start", "Restart", "Clear", "Format", "Invoke")
                       for c in used), name
        assert callable(getattr(rescue, f"_an_{name}")), name
    assert "Kernel-PnP" not in rescue.cmdlets(rescue.PROBES["usb"]["script"])


def test_run_probe_handles_timeout_garbage_and_success():
    assert rescue.run_probe("network", lambda c, t: (None, "", ""))["error"].startswith("neodpovědělo")
    assert "nečitelný" in rescue.run_probe("network", lambda c, t: (0, "{oops", ""))["error"]
    assert rescue.run_probe("network", lambda c, t: (1, "", "Access is denied"))["error"] == "Access is denied"
    r = rescue.run_probe("network", lambda c, t: (0, 'WARNING x\n{"adapters": []}', ""))
    assert r["ok"] and r["data"] == {"adapters": []}


# ---------------------------------------------------------------------------------------------- analyzers
def test_drivers_codes_unsigned_and_old():
    fs = rescue.analyze("drivers", {"problems": [{"Name": "USB Mass Storage", "ConfigManagerErrorCode": 43},
                                                 {"Name": "Vypnuté", "ConfigManagerErrorCode": 22}],
                                    "drivers": [{"DeviceName": "Divná síťovka", "IsSigned": False, "Manufacturer": "X"},
                                                {"DeviceName": "Stará grafika", "DeviceClass": "DISPLAY", "Date": "2012-03-01", "IsSigned": True}]})
    assert levels(fs) == ["bad", "warn", "info"]
    assert "kód 43" in fs[0]["text"] and "Vypnuté" not in " ".join(f["text"] for f in fs)
    assert rescue.analyze("drivers", {"problems": [], "drivers": [{"DeviceName": "a", "IsSigned": True}]})[0]["level"] == "ok"


def test_crashes_explain_stop_codes_and_power_loss():
    fs = rescue.analyze("crashes", {
        "bugchecks": [{"Time": "2026-10-20T10:00:00", "Message": "The computer has rebooted from a bugcheck.  The bugcheck was: 0x0000009f (0x3, ...)"},
                      {"Time": "2026-10-22T10:00:00", "Message": "The bugcheck was: 0x0000009f (0x3)"},
                      {"Time": "2026-10-23T10:00:00", "Message": "The bugcheck was: 0x00000124 (0x0)"}],
        "kernel_power": [{"Time": "x"}] * 4, "unexpected": [], "dumps": [{"Name": "a.dmp", "Time": "2026-10-23T10:00:00"}]})
    text = " ".join(f["text"] for f in fs)
    assert "DRIVER_POWER_STATE_FAILURE – 2×" in text and "WHEA_UNCORRECTABLE_ERROR" in text
    assert "4× vypnul nečekaně" in text and levels(fs).count("bad") == 3
    assert rescue.explain_bugcheck("0x116")[0] == "VIDEO_TDR_FAILURE"
    assert rescue.analyze("crashes", {"bugchecks": [], "kernel_power": [], "unexpected": [], "dumps": []})[0]["level"] == "ok"


def test_apps_groups_crashes_and_names_the_module():
    errs = [{"App": "game.exe", "Module": "nvwgf2umx.dll", "Time": f"2026-10-2{i}"} for i in range(6)]
    fs = rescue.analyze("apps", {"app_errors": errs + [{"App": "word.exe", "Module": "word.exe", "Time": "2026-10-20"}],
                                 "hangs": [{"App": "explorer.exe"}]})
    assert fs[0]["level"] == "bad" and "game.exe spadl 6×" in fs[0]["text"] and "grafický ovladač" in fs[0]["text"]
    assert "chyba je v samotné aplikaci" in fs[1]["text"] and fs[-1]["level"] == "info"


def test_boot_slow_start_and_culprits():
    fs = rescue.analyze("boot", {"boots": [{"BootMs": 95000}, {"BootMs": 60000}],
                                 "slow": [{"Name": "OneDrive", "DegradationMs": 7400}, {"Name": "mini", "DegradationMs": 200}],
                                 "startup": [{"Name": str(i)} for i in range(14)], "fast_startup": 0})
    t = " ".join(f["text"] for f in fs)
    assert fs[0]["level"] == "bad" and "95 s" in t and "OneDrive o 7.4 s" in t and "14 programů" in t and "Rychlé spuštění" in t
    adm = rescue.analyze("boot", {"boots": {"error": "Attempted to perform an unauthorized operation."}})
    assert "správce" in adm[0]["text"]


def test_usb_raw_disk_is_never_formatted():
    fs = rescue.analyze("usb", {"usb_problems": [{"FriendlyName": "USB Hub", "Status": "Error"}],
                                "pnp_events": [{"Id": 219, "Text": "The driver failed to load"}],
                                "disks": [{"Number": 2, "FriendlyName": "JMicron Generic", "Bus": "USB", "Style": "RAW", "Status": "Online"}]})
    t = " ".join(f["text"] + " " + f["fix"] for f in fs)
    assert "NEFORMÁTUJ" in t and "RAW" in t and "USB rámečku" in t and fs[0]["level"] == "bad"


def test_disks_wear_errors_and_log_events():
    fs = rescue.analyze("disks", {"physical": [{"DeviceId": "0", "FriendlyName": "Samsung SSD", "Health": "Healthy"}],
                                  "reliability": [{"DeviceId": "0", "Wear": 96, "Temperature": 65, "ReadErrors": 3}],
                                  "volumes": [{"Letter": "C", "Size": 100 * 2**30, "SizeRemaining": 5 * 2**30, "Health": "Healthy"}],
                                  "io_events": [{"Id": 7, "ProviderName": "disk"}, {"Id": 129, "ProviderName": "storahci"}]})
    t = " ".join(f["text"] for f in fs)
    assert "opotřebení 96 %" in t and "65 °C" in t and "3 chyb čtení" in t and "volné jen 5.0 GB" in t
    assert "vadné sektory 1×" in t and fs[-1]["level"] == "bad"


def test_security_flags_real_risks():
    fs = rescue.analyze("security", {
        "defender": {"AntivirusEnabled": True, "RealTimeProtectionEnabled": False, "AntivirusSignatureAge": 12, "QuickScanAge": 1},
        "cfa": 0, "threats": [], "firewall": [{"Name": "Public", "Enabled": False}],
        "listening": [{"Address": "0.0.0.0", "Port": 3389, "Process": "svchost"}, {"Address": "127.0.0.1", "Port": 8765, "Process": "jarvis"}],
        "startup": [{"Name": "Updater", "Exe": r"C:\Users\a\AppData\Roaming\x\upd.exe", "Signature": "NotSigned"}],
        "tasks": [{"TaskName": "Sync", "Action": "powershell -w hidden -enc AAAA"}], "uac": 1, "rdp": 0,
        "hotfix": {"HotFixID": "KB1", "Date": "2020-01-01"}})
    t = " ".join(f["text"] for f in fs)
    for s in ("v reálném čase", "12 dní", "ransomwaru", "Firewall je vypnutý", "svchost:3389", "Podezřelá položka po spuštění",
              "Podezřelá naplánovaná úloha", "Vzdálená plocha", "Poslední aktualizace Windows"):
        assert s in t, s
    assert "jarvis" not in t


def test_network_and_restore():
    fs = rescue.analyze("network", {"adapters": [{"Name": "Wi-Fi", "Status": "Up"}],
                                    "ipconfig": [{"InterfaceAlias": "Wi-Fi", "IPv4": "169.254.3.3", "Gateway": ""}]})
    assert levels(fs) == ["warn", "bad"]
    assert rescue.analyze("restore", {"points": []})[0]["level"] == "warn"
    adm = rescue.analyze("restore", {"points": {"error": "Access is denied"}, "memtest": [{"Id": 1101, "Text": "Hardware errors were detected"}]})
    assert "správce" in adm[0]["text"] and adm[1]["level"] == "bad"


def test_smart_from_smartctl_json():
    scan = {"devices": [{"name": "/dev/sda"}]}
    info = {"model_name": "WD Blue", "smart_status": {"passed": True}, "temperature": {"current": 41},
            "ata_smart_attributes": {"table": [{"name": "Reallocated_Sector_Ct", "raw": {"value": 8}},
                                               {"name": "Current_Pending_Sector", "raw": {"value": 0}}]}}

    def run(cmd, t):
        return 0, json.dumps(scan if "--scan" in cmd else info), ""
    s = rescue.smart_data(run, exe="smartctl")
    assert s["available"] and s["disks"][0]["reallocated"] == 8
    fs = rescue.analyze_smart(s)
    assert fs[0]["level"] == "bad" and "8 přemapovaných" in fs[0]["text"]


# ---------------------------------------------------------------------------------------------- mission
def test_area_aliases():
    assert _areas("all") == _areas("") and len(_areas("all")) == 10
    assert _areas("modrá obrazovka, usb, nesmysl, crashes") == ["crashes", "usb"]


def test_diagnose_report_is_verified(tmp_path):
    run = fake_runner({"crashes": {"bugchecks": [{"Time": "2026-10-20", "Message": "The bugcheck was: 0x0000001a"}]},
                       "usb": None})
    data = rescue.diagnose(["crashes", "usb"], run, smart=False)
    assert data["results"][0]["ok"] and "MEMORY_MANAGEMENT" in data["top"][0]["text"]
    assert not data["results"][1]["ok"] and "neodpovědělo" in data["results"][1]["findings"][0]["text"]
    path = rescue.write_report(data, tmp_path)
    from jarvis.tasks import sha256_file

    checks = rescue.verify_report(path, sha256_file(path))
    assert all(ok for _c, ok, _v in checks), checks
    html = path.read_text(encoding="utf-8")
    assert "MEMORY_MANAGEMENT" in html and "Nejdůležitější" in html
    sha = sha256_file(path)
    path.write_text(html.replace("MEMORY_MANAGEMENT", "X"), encoding="utf-8")
    assert not rescue.verify_report(path, sha)[2][1]                  # changed after saving → the fingerprint says so


async def test_pc_diagnose_mission_records_evidence(rt, monkeypatch):
    real = rescue.diagnose
    monkeypatch.setattr(rescue, "diagnose", lambda areas: real(areas, fake_runner({"services": {"stopped_auto": [
        {"Name": "Spooler", "DisplayName": "Zařazování tisku", "State": "Stopped", "ExitCode": 1067}], "scm_events": []}}), smart=False))
    tid = rt.tasks.begin("diagnostika", "c1")
    r = await tools.call("pc_diagnose", {"area": "služby"}, rt)
    t = rt.tasks.get(tid)
    assert r.ok and "Zařazování tisku" in r.summary
    assert t["artifacts"] and len(t["evidence"]) == 5 and all(e["ok"] for e in t["evidence"])
    bad = await tools.call("pc_diagnose", {"area": "kytky"}, rt)
    assert not bad.ok and "Neznámá oblast" in bad.summary


async def test_explain_crash_code_tool(rt):
    r = await tools.call("explain_crash_code", {"code": "0x9F"}, rt)
    assert r.ok and "DRIVER_POWER_STATE_FAILURE" in r.summary
    r = await tools.call("explain_crash_code", {"code": "video_tdr_failure"}, rt)
    assert r.ok and "grafick" in r.summary
    assert not (await tools.call("explain_crash_code", {"code": "ahoj"}, rt)).ok


# ---------------------------------------------------------------------------------------------- performance
def test_bottlenecks_from_a_sample():
    s = {"cpu": 92.0, "max_core": 100, "freq_mhz": 1200, "freq_max_mhz": 3600, "ram_pct": 95, "disks": {"C": {"busy_pct": 99, "read_mb_s": 80, "write_mb_s": 3}},
         "top_cpu": [{"name": "game.exe", "cpu": 70}], "top_ram": [{"name": "chrome.exe", "ram_mb": 4000}],
         "gpu": {"gpu": 40, "vram_mb": 7900, "vram_total_mb": 8192}}
    t = " ".join(f["text"] for f in perf.bottlenecks(s))
    for k in ("Brzdí procesor", "škrcený", "Dochází paměť", "Disk C", "Grafická paměť"):
        assert k in t, k
    calm = perf.bottlenecks({"cpu": 5, "max_core": 20, "ram_pct": 40, "disks": {}, "top_cpu": [], "top_ram": [], "gpu": {}})
    assert calm[0]["level"] == "ok"


def test_sample_and_latency_measure_for_real():
    s = perf.sample(0.3, gpu=False)
    assert 0 <= s["cpu"] <= 100 and s["per_core"] and "ram_pct" in s
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(20)
    lat = perf.tcp_latency("127.0.0.1", srv.getsockname()[1], n=3)
    srv.close()
    assert lat["loss_pct"] == 0 and lat["avg_ms"] is not None
    dead = perf.tcp_latency("127.0.0.1", 1, n=2, timeout=0.2)
    assert dead["loss_pct"] == 100


async def test_benchmark_and_history(rt, monkeypatch):
    seq = iter([{"ts": 1.0, "label": "před", "cpu_score": 100.0, "ram_gb_s": 5.0, "disk_write_mb_s": 200.0, "disk_read_mb_s": 900.0},
                {"ts": 2.0, "label": "po", "cpu_score": 120.0, "ram_gb_s": 5.0, "disk_write_mb_s": 100.0, "disk_read_mb_s": 900.0}])
    monkeypatch.setattr(perf, "benchmark", lambda label: next(seq))
    await tools.call("perf_benchmark", {"label": "před"}, rt)
    r = await tools.call("perf_benchmark", {"label": "po"}, rt)
    assert "procesor: 100 → 120 (+20 %)" in r.summary and "zápis na disk: 200 → 100 (-50 %)" in r.summary
    assert not (await tools.call("perf_history", {}, rt)).ok
    rt.perf.record(30.0, 50.0)
    rt.perf.record(70.0, 60.0, net_ms=20.0)
    h = await tools.call("perf_history", {"hours": 1}, rt)
    assert h.ok and "procesor průměr 50.0 %, max 70.0" in h.summary and "odezva sítě" in h.summary


def test_real_benchmark_is_short():
    b = perf.benchmark("x")
    assert b["cpu_score"] > 0 and b["disk_write_mb_s"] > 0 and b["ram_gb_s"] > 0


async def test_guardian_records_history(rt):
    rt.guardian.last_snap = {"cpu_percent": 12.0, "ram_percent": 34.0}
    row = await rt.guardian.record_perf()
    assert row["cpu"] == 12.0 and rt.perf.series(1)[0]["ram"] == 34.0


async def test_hardware_watch_says_what_changed(rt, monkeypatch):
    state = {"present": [{"Class": "Mouse", "FriendlyName": "Logitech"}]}
    monkeypatch.setattr(rescue, "run_probe", lambda name, runner=None: {"ok": True, "data": state, "error": "", "ms": 1})
    seen = []
    rt.notify = lambda title, body, **k: seen.append(body)
    assert await rt.guardian.check_hardware() == ([], [])         # first look only remembers
    state["present"] = [{"Class": "DiskDrive", "FriendlyName": "SanDisk USB"}]
    added, removed = await rt.guardian.check_hardware()
    assert added == ["DiskDrive: SanDisk USB"] and removed == ["Mouse: Logitech"]
    assert "Připojeno: SanDisk USB" in seen[-1] and "Odpojeno: Logitech" in seen[-1]
    r = await tools.call("hardware_changes", {}, rt)
    assert r.ok and "Žádná změna" in r.summary


# ---------------------------------------------------------------------------------------------- network
class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/" else 503)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


async def test_http_check_up_and_down(rt):
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        up = await netdiag.http_check(rt, base + "/")
        down = await netdiag.http_check(rt, base + "/x")
    finally:
        srv.shutdown()
    assert up["up"] and up["status"] == 200 and not down["up"] and down["status"] == 503
    dead = await netdiag.http_check(rt, "http://127.0.0.1:1/")
    assert not dead["up"] and dead["error"]


def test_dns_timing_and_tls_errors():
    r = netdiag.dns_timing(("localhost", "neexistuje.invalid"))
    assert "ms" in r[0] and "error" in r[1]
    t = netdiag.tls_check("127.0.0.1:1".split(":")[0], 1)
    assert t["valid"] is False and t["error"]


def test_trace_parses_windows_output(monkeypatch):
    out = ("Tracing route to x [1.1.1.1]\n  1    <1 ms    <1 ms    <1 ms  192.168.1.1\n"
           "  2    12 ms    10 ms    11 ms  10.0.0.1\n  3     *        *        *     Request timed out.\n")
    monkeypatch.setattr(netdiag, "run_quiet", lambda cmd, t: (0, out, ""))
    hops = netdiag.trace("x; rm -rf /")
    assert [h["ip"] for h in hops] == ["192.168.1.1", "10.0.0.1", "*"] and hops[1]["ms"] == 11.0


# ---------------------------------------------------------------------------------------------- security
def test_check_link_heuristics():
    assert secutils.check_link("https://www.seznam.cz/")["level"] == "ok"
    bad = secutils.check_link("http://csob-overeni.secure-login.xyz/login")
    assert bad["level"] == "bad" and any("csob" in r for r in bad["reasons"])
    assert secutils.check_link("http://192.168.1.5/a")["level"] != "ok"
    assert secutils.check_link("https://xn--pypal-4ve.com")["level"] != "ok"


def test_check_file_double_extension_and_fake_type(tmp_path):
    f = tmp_path / "faktura.pdf.exe"
    f.write_bytes(b"MZ\x90\x00" + b"\x00" * 100)
    r = secutils.check_file(str(f))
    assert r["level"] == "bad" and r["type"].startswith("program") and len(r["sha256"]) == 64
    g = tmp_path / "foto.jpg"
    g.write_bytes(b"MZ\x00\x00")
    assert any("tváří se jako .jpg" in x for x in secutils.check_file(str(g))["reasons"])
    ok = tmp_path / "a.pdf"
    ok.write_bytes(b"%PDF-1.7")
    assert secutils.check_file(str(ok))["level"] == "ok"
    assert "error" in secutils.check_file(str(tmp_path / "nic"))


async def test_scan_secrets_never_returns_the_secret(rt, tmp_path):
    (tmp_path / "app").mkdir()
    key = "sk-ant-" + "A" * 40
    (tmp_path / "app" / "config.py").write_text(f'API = "{key}"\npassword = "hunter22hunter"\n')
    (tmp_path / "app" / "node_modules").mkdir()
    (tmp_path / "app" / "node_modules" / "x.js").write_text(f'k="{key}"')
    r = await tools.call("scan_secrets", {"folder": str(tmp_path / "app")}, rt)
    assert r.ok and "2 možných" in r.summary and key not in json.dumps(r.data) and key not in r.summary


async def test_verify_copy_finds_missing_and_changed(rt, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        (d / "sub").mkdir(parents=True)
        (d / "sub" / "x.txt").write_text("stejné")
    (a / "y.txt").write_text("1")
    (b / "y.txt").write_text("2")
    (a / "z.txt").write_text("chybí")
    r = await tools.call("verify_copy", {"source": str(a), "copy": str(b)}, rt)
    assert not r.ok and "1 chybí, 1 se liší" in r.summary
    (b / "z.txt").write_text("chybí")
    (b / "y.txt").write_text("1")
    assert (await tools.call("verify_copy", {"source": str(a), "copy": str(b)}, rt)).ok


async def test_pwned_count_sends_only_the_prefix(rt):
    import hashlib

    import httpx

    sha = hashlib.sha1(b"heslo123").hexdigest().upper()
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, text=f"0000000000000000000000000000000000A:1\n{sha[5:]}:4242\n")
    rt.transport = httpx.MockTransport(handler)
    assert await secutils.pwned_count(rt, "heslo123") == 4242
    assert seen[0].endswith("/range/" + sha[:5]) and "heslo123" not in seen[0] and sha[5:] not in seen[0]


def test_rescue_plan_orders_by_recent_work(tmp_path, monkeypatch):
    monkeypatch.setattr(secutils.Path, "home", lambda: tmp_path)
    for name, age in (("Documents", 10), ("Pictures", 1000)):
        (tmp_path / name).mkdir()
        f = tmp_path / name / "f"
        f.write_text("x")
        os.utime(f, (1e9 - age, 1e9 - age))
    plan = secutils.rescue_plan(None)
    assert [os.path.basename(p["folder"]) for p in plan] == ["Documents", "Pictures"]


# ---------------------------------------------------------------------------------------------- never
@pytest.mark.parametrize("cmd", ["format D:", "Format-Volume -DriveLetter E", "diskpart /s x.txt", "Clear-Disk 1",
                                 "vssadmin delete shadows /all", "cipher /w:C:", "dir; format c: /q", "bcdedit /delete {x}"])
async def test_shell_never_runs_destructive_disk_commands(rt, cmd):
    rt.update_config({"permissions": {"shell": True}})
    r = await tools.REGISTRY["run_shell"].func(rt, command=cmd)
    assert not r.ok and "nikdy nespouští" in r.summary
    assert not [c for c in rt.platform.calls if c[0] == "run_shell"]


def test_shell_allows_ordinary_commands():
    for c in ("Get-Disk | Format-Table", "Get-ChildItem", "echo format", "Get-Volume"):
        assert never_reason(c) == "", c


def test_read_only_mode_allows_the_diagnostics():
    from jarvis.permissions import READ_ONLY_OK

    for n in ("pc_diagnose", "perf_check", "network_check", "check_link", "check_download", "verify_copy"):
        assert n in READ_ONLY_OK and n in tools.REGISTRY
    for n in ("create_restore_point", "schedule_memory_test"):
        assert n not in READ_ONLY_OK and tools.REGISTRY[n].danger


# ---------------------------------------------------------------------------------------------- the page (WebSocket)
def _ws(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    return TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000))


def _recv(ws, type_, limit=80):
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == type_:
            return m
    raise AssertionError(type_)


def test_page_runs_diagnostics_and_security_checks(rt, monkeypatch, tmp_path):
    real = rescue.diagnose
    monkeypatch.setattr(rescue, "diagnose", lambda areas: real(areas, fake_runner({"network": {"adapters": []}}), smart=False))
    opened = []
    rt.platform.open_path = lambda p: opened.append(p)
    (tmp_path / "x.py").write_text('token = "abcdefghijkl1234"\n')
    with _ws(rt) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "rescue_run", "area": "network"})
        m = _recv(ws, "rescue")
        assert m["verified"] and "Žádné síťové připojení" in m["top"][0]["text"]
        ws.send_json({"type": "rescue_open", "path": m["path"]})
        ws.send_json({"type": "rescue_open", "path": str(tmp_path / "x.py")})
        assert "nevytvořil" in _recv(ws, "error")["message"]
        ws.send_json({"type": "seccheck", "kind": "link", "value": "http://paypal.com.login-secure.top/"})
        assert _recv(ws, "seccheck")["result"]["level"] == "bad"
        ws.send_json({"type": "seccheck", "kind": "secrets", "value": str(tmp_path)})
        hits = _recv(ws, "seccheck")["result"]["hits"]
        assert hits and "abcdefghijkl1234" not in json.dumps(hits)
        ws.send_json({"type": "seccheck", "kind": "nesmysl"})
        assert _recv(ws, "seccheck")["error"]
    assert opened == [m["path"]]


def test_page_perf_history_and_benchmark(rt, monkeypatch):
    monkeypatch.setattr(perf, "benchmark", lambda label: {"ts": 5.0, "label": label, "cpu_score": 10.0, "ram_gb_s": 1.0,
                                                          "disk_write_mb_s": 1.0, "disk_read_mb_s": 1.0})
    rt.perf.record(20.0, 30.0)
    with _ws(rt) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "perf_bench", "label": "test"})
        m = _recv(ws, "perf")
    assert m["bench"]["label"] == "test" and m["benches"][0]["cpu_score"] == 10.0 and m["history"][0]["cpu"] == 20.0


def test_security_center_is_local_only(rt):
    from jarvis.server.ws import LOCAL_ONLY

    assert {"seccheck", "rescue_open"} <= LOCAL_ONLY


async def test_stall_watch_logs_where_the_loop_is_stuck(caplog):
    import asyncio
    import logging
    import time as _t

    from jarvis import diagnostics

    caplog.set_level(logging.WARNING, logger="jarvis.diagnostics")
    diagnostics.start_stall_watch(None, asyncio.get_running_loop(), limit_s=0.5)
    _t.sleep(3.5)            # a blocking call in the loop – what the watch is for
    await asyncio.sleep(2.5)
    text = caplog.text
    assert "event loop stuck" in text and "test_stall_watch_logs_where_the_loop_is_stuck" in text
    assert "answers again" in text
