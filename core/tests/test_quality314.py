"""3.14 návrhy 12, 13, 16, 17, 20: tool health per version, regressions → rollback, beta channel, bug report link."""
import asyncio
import json

import httpx

from conftest import FakeRouter
from jarvis import quality, tools, updater

tools.load_builtin()


def test_tool_stats_and_versions(rt, monkeypatch):
    for _ in range(4):
        quality.record_tool(rt, "web_search", True, 120)
    for _ in range(3):
        quality.record_tool(rt, "ui_click", False, 900)
    quality.record_tool(rt, "ui_click", True, 300)
    h = quality.health(rt)
    assert h["failing"][0]["tool"] == "ui_click" and h["failing"][0]["rate"] == 0.75
    assert {t["tool"] for t in h["tools"]} == {"web_search", "ui_click"}
    assert h["versions"][0]["calls"] == 8
    monkeypatch.setattr(quality, "_version", lambda: "3.10.999")
    for _ in range(25):
        quality.record_tool(rt, "web_search", True, 50)
    vers = quality.by_version(rt)
    assert vers[0]["version"] == "3.10.999"


async def test_agent_counts_tools(rt):
    rt.router = FakeRouter([[("get_time", {})], "Je poledne."])
    await rt.agent.handle("kolik je hodin")
    assert any(t["tool"] == "get_time" for t in quality.tool_health(rt, min_calls=1))


def test_regressions():
    before = [{"key": "notch", "ok": True}, {"key": "tts", "ok": True}, {"key": "internet", "ok": True}, {"key": "mic", "ok": False}]
    now = [{"key": "notch", "ok": False, "name": "Notch"}, {"key": "tts", "ok": True}, {"key": "internet", "ok": False},
           {"key": "mic", "ok": False}]
    regs = quality.regressions(before, now)
    assert [r["key"] for r in regs] == ["notch"]           # internet is not JARVIS's fault, mic was broken before
    assert quality.should_roll_back(regs)
    assert not quality.should_roll_back([{"key": "tts"}])
    assert quality.should_roll_back([{"key": "tts"}, {"key": "wake"}])


async def test_after_update_rolls_back(rt, monkeypatch):
    from jarvis import selfcheck, upkeep

    upkeep._set(rt, "selfcheck_last", json.dumps([{"key": "notch", "ok": True, "name": "Notch"}]))
    upkeep._set(rt, "updated_from", "3.10.5")

    async def fake_run(rt_, tester):
        return [{"key": "notch", "ok": False, "name": "Notch", "detail": "okno nenaběhlo"}]
    monkeypatch.setattr(selfcheck, "run", fake_run)
    calls = []

    class Up:
        async def rollback(self, to, bad=""):
            calls.append((to, bad))
            return True
    rt.updater = Up()
    rt.notified = []
    monkeypatch.setattr(rt, "notify", lambda t, b, **k: rt.notified.append((t, b)))
    await upkeep.after_update(rt, delay=0)
    assert calls and calls[0][0] == "3.10.5"
    assert "Vracím" in rt.notified[0][0]


def _rel(tag, pre=False, asset=True):
    return {"tag_name": f"v{tag}", "prerelease": pre, "draft": False, "body": "",
            "assets": [{"name": updater.ASSET, "browser_download_url": f"https://x/{tag}.exe"}] if asset else []}


def test_pick_channel():
    lst = [_rel("3.10.7", pre=True), _rel("3.10.6"), _rel("3.10.8", asset=False)]
    assert updater.Updater.pick(lst, "stable")["tag_name"] == "v3.10.6"
    assert updater.Updater.pick(lst, "beta")["tag_name"] == "v3.10.7"
    assert updater.Updater.pick(_rel("3.10.6"), "stable")["tag_name"] == "v3.10.6"


async def test_beta_channel_asks_the_list(rt):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        data = [_rel("3.10.50", pre=True)] if "releases?" in str(req.url) else _rel("3.10.40")
        return httpx.Response(200, json=data)
    u = updater.Updater(rt, transport=httpx.MockTransport(handler), current="3.10.30")
    rt.cfg.general.update_channel = "beta"
    r = await u.check()
    assert r["version"] == "3.10.50" and "per_page" in seen[0]
    rt.cfg.general.update_channel = "stable"
    r = await u.check()
    assert r["version"] == "3.10.40" and seen[-1].endswith("/releases/latest")


def test_issue_url(rt):
    assert quality.repo_of("https://api.github.com/repos/adamekk778/JARViS2/releases/latest") == "adamekk778/JARViS2"
    url = quality.issue_url(rt, "Notch nejde", "klíč sk-abcdefghijklmnopqrstuvwx1234 se nesmí ukázat")
    assert url.startswith("https://github.com/adamekk778/JARViS2/issues/new?")
    assert "sk-abcdefghijklmnopqrstuvwx1234" not in url and len(url) < 16000


def test_power_meter():
    pm = quality.PowerMeter()
    assert pm.report() == {"samples": 0}
    pm.sample()
    pm.sample()
    rep = pm.report()
    assert rep["samples"] >= 1 and 0 <= rep["cpu_share"] <= 100


async def test_ws_quality_and_bug_report(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({"type": "quality_get"})
        got = {}
        for _ in range(40):
            msg = ws.receive_json()
            if msg["type"] in ("quality",):
                got = msg
                break
        assert "failing" in got and got["channel"] == "stable"
        ws.send_json({"type": "bug_report", "title": "test", "text": "nejde hlas"})
        for _ in range(40):
            msg = ws.receive_json()
            if msg["type"] == "bug_report_url":
                assert "issues/new" in msg["url"]
                break
        else:
            raise AssertionError("no bug_report_url")
    await asyncio.sleep(0)
