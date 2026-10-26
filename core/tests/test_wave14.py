"""OMEGA wave 14 (testing lab): load, fuzzing, the network-fault proxy, memory leaks, corrupted data, translation
overflow and pseudo-localisation, and the browser tests (keyboard, devices, offline, user flows) against a real local
server and a real headless browser."""
import http.server
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from jarvis import testlab, tools

tools.load_builtin()

CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
needs_browser = pytest.mark.skipif(not (sys.platform == "win32" or Path(CHROMIUM).exists()), reason="žádný prohlížeč")

SHOP = """<!doctype html><html><head><meta name=viewport content="width=device-width"><style>
button:focus { outline: 2px solid blue } .wide { width: 900px; height: 20px; background: #eee }
#card:focus { outline: none }</style></head><body>
<h1>Obchod</h1>
<label>Hledat <input id="q"></label>
<button id="buy" onclick="document.getElementById('out').textContent='KOUPENO ' + document.getElementById('q').value">Koupit</button>
<a href="/kosik">Košík</a>
<div id="fake" onclick="alert(1)">Falešné tlačítko</div>
<div id="card" tabindex="0">Karta</div>
<p id="out"></p>
<div class="wide">široký pruh</div>
</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            return self._send(200, SHOP)
        if u.path == "/kosik":
            return self._send(200, "<h1>Košík</h1><p>Prázdný</p>")
        if u.path == "/api/item":
            v = q.get("id", ["1"])[0]
            try:
                return self._send(200, json.dumps({"id": int(v)}), "application/json")
            except ValueError:
                return self._send(500, "Internal Server Error")
        if u.path == "/search":
            return self._send(200, f"<p>Hledáš: {q.get('q', [''])[0]}</p>")
        if u.path == "/slow":
            time.sleep(0.02)
            return self._send(200, "ok", "text/plain")
        return self._send(404, "nic")


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture
def real_http(rt):
    rt.transport = None
    return rt


@pytest.fixture
def browser_env(monkeypatch):
    if sys.platform != "win32":
        monkeypatch.setenv("JARVIS_CHROMIUM", CHROMIUM)


def test_local_only_blocks_the_internet():
    assert testlab.local_only("http://127.0.0.1:8000/x")
    assert testlab.local_only("http://192.168.1.10/")
    with pytest.raises(ValueError, match="není tvůj počítač"):
        testlab.local_only("http://8.8.8.8/")
    with pytest.raises(ValueError):
        testlab.local_only("ftp://127.0.0.1/")


async def test_load_test(real_http, server):
    rt = real_http
    r = await tools.call("load_test", {"url": server + "/slow", "users": 5, "seconds": 2}, rt)
    assert r.ok and r.data["requests"] > 20 and r.data["error_pct"] == 0 and r.data["status"] == {"200": r.data["requests"]}
    assert r.data["p50_ms"] >= 15 and r.data["p95_ms"] >= r.data["p50_ms"]
    assert not (await tools.call("load_test", {"url": "http://1.1.1.1/", "users": 5, "seconds": 2}, rt)).ok
    assert tools.REGISTRY["load_test"].danger


async def test_fuzz_finds_crash_and_xss(real_http, server):
    r = await tools.call("fuzz_inputs", {"url": server + "/api/item?id=1", "params": ["id"]}, real_http)
    probs = {(f["input"], f["problem"]) for f in r.data["findings"]}
    assert ("SQL", "server spadl (500)") in probs and ("mezera", "server spadl (500)") in probs
    assert not any(i == "nula" for i, _ in probs)            # 0 is a valid id
    r = await tools.call("fuzz_inputs", {"url": server + "/search", "params": ["q"]}, real_http)
    assert any(f["problem"].endswith("(XSS)") for f in r.data["findings"])


async def test_network_fault_proxy(real_http, server):
    port = urlparse(server).port
    r = await tools.call("network_fault_start", {"target": f"127.0.0.1:{port}", "latency_ms": 300}, real_http)
    p = r.data["port"]
    async with httpx.AsyncClient() as c:
        t0 = time.perf_counter()
        resp = await c.get(f"http://127.0.0.1:{p}/kosik", timeout=10)
        slow = time.perf_counter() - t0
    assert resp.status_code == 200 and "Košík" in resp.text and slow >= 0.3
    await tools.call("network_fault_stop", {"port": p}, real_http)
    r = await tools.call("network_fault_start", {"target": f"127.0.0.1:{port}", "down": True}, real_http)
    async with httpx.AsyncClient() as c:
        with pytest.raises(httpx.TransportError):
            await c.get(f"http://127.0.0.1:{r.data['port']}/", timeout=5)
    stop = await tools.call("network_fault_stop", {}, real_http)
    assert stop.data[r.data["port"]]["dropped"] >= 1
    assert not (await tools.call("network_fault_stop", {}, real_http)).ok


def test_leak_verdict():
    leak = testlab.leak_verdict([(i * 10, 100 + i * 2) for i in range(10)])
    assert leak["verdict"] == "podezření na únik paměti" and leak["mb_per_min"] == 12.0 and leak["r2"] == 1.0
    flat = testlab.leak_verdict([(i * 10, 100 + (i % 2)) for i in range(10)])
    assert flat["verdict"] == "stabilní"


async def test_memory_leak_check_real_process(rt, tmp_path):
    script = tmp_path / "leak.py"
    script.write_text("import time\nx = []\nwhile True:\n    x.append(b'x' * 4_000_000)\n    time.sleep(0.25)\n", encoding="utf-8")
    p = subprocess.Popen([sys.executable, str(script)])
    try:
        time.sleep(0.5)
        r = await tools.call("memory_leak_check", {"process": str(p.pid), "seconds": 10, "interval": 1}, rt)
        assert r.ok and r.data["end_mb"] - r.data["start_mb"] > 50 and r.data["verdict"] == "podezření na únik paměti"
    finally:
        p.kill()
    assert not (await tools.call("memory_leak_check", {"process": "neexistujici-proces-xyz"}, rt)).ok


async def test_corruption_test(rt, tmp_path):
    data = tmp_path / "config.json"
    data.write_text(json.dumps({"name": "Adam", "items": list(range(50))}), encoding="utf-8")
    careful = tmp_path / "careful.py"
    careful.write_text("import json, sys\ntry:\n    d = json.load(open(sys.argv[1], encoding='utf-8'))\n    assert isinstance(d, dict) and 'name' in d\n"
                       "except Exception as e:\n    print('chybný soubor:', type(e).__name__)\n    sys.exit(2)\n", encoding="utf-8")
    sloppy = tmp_path / "sloppy.py"
    sloppy.write_text("import json, sys\nd = json.load(open(sys.argv[1], encoding='utf-8'))\nprint(d['name'])\n", encoding="utf-8")
    r = await tools.call("corruption_test", {"file": str(data), "command": f'"{sys.executable}" "{careful}" {{file}}'}, rt)
    outcomes = {x["variant"]: x["outcome"] for x in r.data["results"]}
    assert outcomes["prazdny"] == "odmítl" and outcomes["pulka"] == "odmítl" and not r.data["bad"]
    r = await tools.call("corruption_test", {"file": str(data), "command": f'"{sys.executable}" "{sloppy}" {{file}}'}, rt)
    assert {x["variant"] for x in r.data["bad"]} >= {"prazdny", "pulka", "nahodne-bajty"} and "PROBLÉM" in r.summary
    assert data.read_text(encoding="utf-8").startswith('{"name"')
    assert not (await tools.call("corruption_test", {"file": str(data), "command": "type"}, rt)).ok
    r = await tools.call("corrupt_test_data", {"file": str(data)}, rt)
    assert len(list((tmp_path / "poskozene").iterdir())) == 8 and (tmp_path / "poskozene" / "config.prazdny.json").stat().st_size == 0


async def test_translation_overflow_and_pseudo(rt, tmp_path):
    en = tmp_path / "en.json"
    cs = tmp_path / "cs.json"
    en.write_text(json.dumps({"save": "Save", "cancel": "Cancel", "title": "Settings", "greet": "Hello {name}"}), encoding="utf-8")
    cs.write_text(json.dumps({"save": "Uložit všechny změny", "cancel": "Zrušit", "title": "Nastavení", "greet": "Ahoj {name}"}), encoding="utf-8")
    r = await tools.call("translation_overflow", {"source": str(en), "translated": str(cs), "limits": '{"title": 8}'}, rt)
    keys = [x["key"] for x in r.data]
    assert keys[0] == "save" and "title" in keys and "cancel" not in keys
    r = await tools.call("pseudo_localize", {"source": str(en)}, rt)
    out = json.loads((tmp_path / "en.pseudo.json").read_text(encoding="utf-8"))
    assert r.ok and out["save"].startswith("[!! Šávé") and out["greet"].count("{name}") == 1 and len(out["title"]) > len("Settings") * 1.4
    assert not (await tools.call("pseudo_localize", {"source": str(en)}, rt)).ok   # never overwrites


@needs_browser
async def test_keyboard_test(rt, server, browser_env):
    r = await tools.call("keyboard_test", {"url": server + "/"}, rt)
    assert r.ok, r.summary
    labels = [o["label"] for o in r.data["order"]]
    assert labels == ["Hledat", "Koupit", "Košík", "Karta"]
    assert "Falešné tlačítko" in [u["label"] for u in r.data["unreachable"]]
    assert "Karta" in r.data["no_focus_ring"] and not r.data["trap"]


@needs_browser
async def test_device_matrix(rt, server, browser_env):
    r = await tools.call("device_test", {"url": server + "/"}, rt)
    assert r.ok, r.summary
    by = {d["device"]: d for d in r.data["devices"]}
    assert by["telefon"]["scroll_x"] and not by["monitor"]["scroll_x"]
    assert all(Path(d["screenshot"]).stat().st_size > 1000 for d in r.data["devices"])


@needs_browser
async def test_offline(rt, server, browser_env):
    r = await tools.call("offline_test", {"url": server + "/"}, rt)
    assert r.ok and not r.data["works_offline"] and not r.data["service_worker"] and "NEFUNGUJE" in r.summary


@needs_browser
async def test_user_flow(rt, server, browser_env):
    ok = await tools.call("user_flow_test", {"url": server + "/", "steps": ["vyplň Hledat = mléko", "klikni na Koupit",
                                                                          "očekávej KOUPENO mléko", "klikni na Košík", "očekávej Prázdný"]}, rt)
    assert ok.ok and ok.data["ok"] and len(ok.data["steps"]) == 5, ok.summary
    assert all(Path(s["screenshot"]).is_file() for s in ok.data["steps"])
    bad = await tools.call("user_flow_test", {"url": server + "/", "steps": ["klikni na Koupit", "očekávej ZAPLACENO", "klikni na Košík"]}, rt)
    assert not bad.data["ok"] and len(bad.data["steps"]) == 2 and "kroku 2/3" in bad.summary
    assert not (await tools.call("user_flow_test", {"url": server + "/", "steps": ["udělej kotrmelec"]}, rt)).ok
