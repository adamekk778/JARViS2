"""Wave F4: firewall rules (393), CPU temperature (022 / 297), the home-network speed test (717), a container for the
project (342), coverage measuring (334) and a personal routine composed from habits (504)."""
import json

from jarvis import devlab, perf, proactive, rescue, tools
from jarvis.tools import devlab_tools

tools.load_builtin()


def test_firewall_rules_review():
    f = rescue.firewall_findings([{"Name": "x", "Program": r"C:\Users\a\Downloads\tool.exe", "Profile": "Private", "Port": "Any"}])
    assert f[0]["level"] == "bad" and "Downloads" in f[0]["text"]
    f = rescue.firewall_findings([{"Name": "open", "Program": "Any", "Profile": "Public", "Port": "Any"}])
    assert f[0]["level"] == "warn"
    f = rescue.firewall_findings([{"Name": "Steam", "Program": r"C:\Program Files\Steam\steam.exe", "Profile": "Private", "Port": "27036"}])
    assert f[0]["level"] == "info" and "Steam" in f[0]["text"]
    assert rescue.firewall_findings([]) == []
    assert rescue.cmdlets(rescue.PROBES["security"]["script"]) <= rescue.ALLOWED


def test_cpu_temperature_sources():
    lhm = {"sensors": [{"name": "CPU Package", "value": 71.5, "source": "root\\LibreHardwareMonitor"},
                       {"name": "CPU Core #1", "value": 69.0, "source": "root\\LibreHardwareMonitor"},
                       {"name": "GPU Core", "value": 55.0, "source": "root\\LibreHardwareMonitor"}]}
    t = perf.parse_temps(lhm)
    assert t["cpu_c"] == 71.5 and t["exact"] and t["source"] == "LibreHardwareMonitor"
    t = perf.parse_temps({"sensors": {"name": "ACPI TZ00", "value": 48.0, "source": "acpi"}})
    assert t["cpu_c"] == 48.0 and not t["exact"]
    t = perf.parse_temps({})
    assert t["cpu_c"] is None and "LibreHardwareMonitor" in t["hint"]
    hot = {"cpu": 50, "max_core": 60, "per_core": [50], "freq_mhz": None, "freq_max_mhz": None, "ram_pct": 30, "disks": {},
           "top_cpu": [], "top_ram": [], "temp": {"cpu_c": 93, "source": "LibreHardwareMonitor"}}
    assert any("přehřátý" in x["text"] for x in perf.bottlenecks(hot))


def test_lan_speedtest_endpoints(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    with TestClient(create_app(rt, manage_runtime=False), client=("192.168.1.50", 5000)) as c:
        assert c.get("/api/speedtest?mb=1").status_code == 401           # from the network only with the pairing token
        tok = rt.cfg.phone.token
        r = c.get(f"/api/speedtest?mb=2&token={tok}")
        assert r.status_code == 200 and len(r.content) == 2 << 20
        up = c.post(f"/api/speedtest?token={tok}", content=b"x" * 300_000)
        assert up.json()["bytes"] == 300_000


def test_container_files(tmp_path):
    (tmp_path / "requirements.txt").write_text("flask\n")
    (tmp_path / "app.py").write_text("print(1)\n")
    r = devlab.container_files(tmp_path, {"python": "3.11.9", "tools": {}})
    d = r["files"]["Dockerfile"]
    assert r["kind"] == "python" and d.startswith("FROM python:3.11-slim") and "pip install --no-cache-dir -r requirements.txt" in d
    assert 'CMD ["python", "app.py"]' in d and ".env" in r["files"][".dockerignore"]
    assert json.loads(r["files"][".devcontainer/devcontainer.json"])["image"].endswith("python:3.11")
    n = tmp_path / "web"
    n.mkdir()
    (n / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js"}}))
    (n / "package-lock.json").write_text("{}")
    r = devlab.container_files(n, {"python": "3.12.1", "tools": {"node": "v22.3.0"}})
    assert r["kind"] == "node" and "FROM node:22-slim" in r["files"]["Dockerfile"] and "RUN npm ci" in r["files"]["Dockerfile"]
    assert 'CMD ["npm", "start"]' in r["files"]["Dockerfile"]
    e = tmp_path / "empty"
    e.mkdir()
    try:
        devlab.container_files(e, {})
        raise AssertionError
    except ValueError:
        pass


def test_coverage_plan(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    cmds, rep = devlab_tools.coverage_plan(tmp_path, tmp_path / "out")
    assert cmds[0].startswith("python -m coverage run -m pytest") and rep.name == "coverage.json"
    j = tmp_path / "js"
    j.mkdir()
    (j / "package.json").write_text("{}")
    cmds, rep = devlab_tools.coverage_plan(j, tmp_path / "o2")
    assert "c8" in cmds[0] and rep.name == "lcov.info"
    assert devlab_tools.coverage_plan(tmp_path / "nic", tmp_path) is None
    spec = tools.REGISTRY["measure_coverage"]
    assert spec.danger and tools.REGISTRY["container_setup"].danger_if({"write": True}) and not tools.REGISTRY["container_setup"].danger_if({})


async def test_compose_routine(rt):
    found = [{"when": "všední den", "hour": 8, "app": "Outlook", "days": 15}, {"when": "všední den", "hour": 8, "app": "Teams", "days": 12},
             {"when": "všední den", "hour": 9, "app": "Excel", "days": 10}, {"when": "všední den", "hour": 14, "app": "Spotify", "days": 9},
             {"when": "víkend", "hour": 10, "app": "Steam", "days": 6}]
    r = proactive.compose_routine(found)
    assert r["apps"] == ["Outlook", "Teams", "Excel"] and r["trigger"]["value"] == "08:00" and r["trigger"]["days"] == [0, 1, 2, 3, 4]
    assert r["name"].startswith("Ranní") and [s["args"]["name"] for s in r["steps"][1:]] == ["Outlook", "Teams", "Excel"]
    w = proactive.compose_routine(found, "víkend")
    assert w["apps"] == ["Steam"] and w["trigger"]["days"] == [5, 6]
    assert proactive.compose_routine(found, "všední den", 20) is None
    assert proactive.compose_routine([], "víkend") is None
    res = await tools.REGISTRY["compose_routine"].func(rt)
    assert not res.ok                                                  # no usage data in a fresh profile
