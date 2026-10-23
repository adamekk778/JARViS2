import time
import zipfile

import httpx

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
