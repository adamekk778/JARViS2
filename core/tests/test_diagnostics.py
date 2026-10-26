import sys

import time
import zipfile

import httpx
import pytest

from jarvis import diagnostics, paths, tools
from jarvis.tools.system import system_snapshot

tools.load_builtin()


def test_snapshot_shape(rt):
    s = diagnostics.snapshot(rt)
    assert isinstance(s["cpu_pct"], float) and s["ram_mb"] > 0 and s["threads"] >= 1
    assert isinstance(s["children"], list) and isinstance(s["ttft"], dict) and isinstance(s["log_tail"], list)
    assert "voice" in s and "loop_lag_ms" in s


def test_export_zip_has_no_secrets(rt):
    rt.update_config({"phone": {"token": "SECRET_TOKEN_123456"}})
    log = paths.sub("logs") / "jarvis.log"
    log.write_text("klíč sk-abcdefghijklmnop1234 ws?token=SECRET_TOKEN_123456\n", encoding="utf-8")
    path = diagnostics.export_zip(rt)
    with zipfile.ZipFile(path) as z:
        blob = b"".join(z.read(n) for n in z.namelist())
    assert z.namelist() and b"sk-abcdefghijklmnop1234" not in blob and b"SECRET_TOKEN_123456" not in blob


def test_log_tail_redacted(rt):
    (paths.sub("logs") / "jarvis.log").write_text("token=ABCDEF0123456789abcdef\n", encoding="utf-8")
    assert all("ABCDEF0123456789abcdef" not in line for line in diagnostics.snapshot(rt)["log_tail"])


def test_bench_runs():
    t0 = time.monotonic()
    out = diagnostics.bench(2)
    assert time.monotonic() - t0 < 20
    assert set(out) >= {"startup_s", "cpu_pct", "ram_mb", "seconds", "targets"}
    assert out["targets"] == {"cpu_pct": 2.0, "ram_mb": 400}


def test_bench_gate():
    assert diagnostics.gate({"cpu_pct": 3.9, "ram_mb": 799}) is True
    assert diagnostics.gate({"cpu_pct": 4.1, "ram_mb": 100}) is False
    assert diagnostics.gate({"cpu_pct": 1.0, "ram_mb": 801}) is False


def test_system_snapshot_net_and_disks():
    system_snapshot()
    s = system_snapshot()
    assert isinstance(s["net_down_kbps"], float) and s["net_down_kbps"] >= 0
    assert s["disks"] and {"mount", "used_pct", "free_gb"} <= set(s["disks"][0])
    assert "gpu" in s


async def test_performance_report_read_only(ctx):
    before = list(ctx.platform.calls)
    res = await tools.call("performance_report", {}, ctx)
    assert res.ok and res.summary.strip() and ctx.platform.calls == before
    assert {"top_cpu", "top_ram", "ram_percent", "startup_items"} <= set(res.data)


def test_performance_rules():
    from jarvis.tools.system import recommendations

    tips = recommendations({"ram_percent": 91, "top_ram": [{"name": "chrome.exe", "ram_mb": 3000}],
                            "startup_items": 14, "disks": [{"mount": "C:\\", "used_pct": 95, "free_gb": 4.0}],
                            "top_cpu": [], "uptime_h": 300})
    text = " ".join(tips)
    assert "chrome.exe" in text and "po spuštění" in text and "C:" in text and "restart" in text.lower()


async def test_ttft_recorded(rt):
    from jarvis.llm.router import Router

    def h(req):
        return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"ahoj"}}]}\n\ndata: [DONE]\n\n',
                              headers={"content-type": "text/event-stream"})

    r = Router(rt.cfg.brain, lambda pid: "", httpx.MockTransport(h))
    out = [c async for c in r.stream([{"role": "user", "content": "hi"}], None)]
    assert out and sum(len(v) for v in r.ttft.values()) == 1


def test_main_bench_prints_json(capsys):
    import json

    from jarvis.__main__ import main

    assert main(["--bench", "1"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["seconds"] == 1 and "cpu_pct" in out


def test_ws_diagnostics(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "diagnostics_get"})
        m = ws.receive_json()
        while m["type"] != "diagnostics":
            m = ws.receive_json()
        assert "ram_mb" in m
        ws.send_json({"type": "diagnostics_export"})
        m = ws.receive_json()
        while m["type"] != "diagnostics_file":
            m = ws.receive_json()
        assert m["attachment"]["name"].endswith(".zip")
        ws.send_json({"type": "system_get", "gpu": True})
        m = ws.receive_json()
        while m["type"] != "system":
            m = ws.receive_json()
        assert "disks" in m and "gpu" in m


@pytest.mark.skipif(sys.platform == "win32", reason="the GIL-holding freeze is simulated with libc via PyDLL")
def test_hang_dump_when_the_whole_interpreter_freezes(tmp_path, monkeypatch):
    """A thread that holds the GIL inside a blocking native call freezes every Python thread (the stall watch too);
    the C watchdog must still write all thread stacks to hang-dump.txt."""
    import asyncio
    import ctypes
    import faulthandler
    import threading
    import time as _t

    monkeypatch.setenv("JARVIS_HANG_DUMP", "1")
    loop = asyncio.new_event_loop()
    th = threading.Thread(target=loop.run_forever, daemon=True)
    th.start()
    try:
        diagnostics.start_stall_watch(None, loop, limit_s=1, dump_after=2)
        _t.sleep(0.5)
        libc = ctypes.PyDLL(None)                 # PyDLL: the GIL stays held during the call
        libc.sleep(4)                             # freeze everything for 4 s
        _t.sleep(0.5)
        dump = (paths.data_dir() / "logs" / "hang-dump.txt").read_text(encoding="utf-8")
        assert "Thread 0x" in dump and "test_hang_dump_when_the_whole_interpreter_freezes" in dump
    finally:
        faulthandler.cancel_dump_traceback_later()
        loop.call_soon_threadsafe(loop.stop)
        th.join(2)
        loop.close()


def test_one_shared_tls_context(rt):
    """All HTTP clients reuse the TLS context made once at start-up (see tlsctx: a first-time OpenSSL init racing other
    native start-up work froze the whole process on Windows)."""
    from jarvis import tlsctx

    tlsctx.warm_up()
    rt.transport = None
    a, b = rt.http(), rt.http()
    assert a._transport._pool._ssl_context is tlsctx.context() is b._transport._pool._ssl_context
