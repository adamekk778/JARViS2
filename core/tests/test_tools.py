import json

import httpx

from jarvis import tools
from jarvis.tools import REGISTRY, call, is_dangerous
from jarvis.tools.base import ToolResult, schema_for, tool

tools.load_builtin()


def test_schema_generation():
    from typing import Annotated, Literal

    async def f(ctx, name: Annotated[str, "jméno"], mode: Literal["a", "b"] = "a", n: int | None = None, xs: list[str] = ()):
        pass

    s = schema_for(f)
    assert s["required"] == ["name"]
    assert s["properties"]["name"] == {"type": "string", "description": "jméno"}
    assert s["properties"]["mode"]["enum"] == ["a", "b"]
    assert s["properties"]["n"]["type"] == "integer"
    assert s["properties"]["xs"]["type"] == "array"


def test_builtin_tools_registered():
    for n in ("open_app", "youtube_play", "volume", "media_control", "system_power", "weather", "web_search",
              "screenshot", "set_timer", "run_shell", "remember", "update_setting", "read_attachment", "send_file"):
        assert n in REGISTRY, n


def test_danger_flags():
    sp = REGISTRY["system_power"]
    assert is_dangerous(sp, {"action": "shutdown"})
    assert not is_dangerous(sp, {"action": "lock"})
    assert is_dangerous(REGISTRY["run_shell"], {"command": "dir"})
    assert not is_dangerous(REGISTRY["run_shell"], {"command": "dir"}, trusted=["run_shell"])
    assert is_dangerous(REGISTRY["volume"], {"action": "up"}, always_confirm=["volume"])


async def test_exception_becomes_error(ctx):
    @tool("_boom", "x")
    async def boom(ctx):
        raise RuntimeError("nope")

    r = await call("_boom", {}, ctx)
    assert not r.ok and "nope" in r.summary
    del REGISTRY["_boom"]


async def test_unknown_and_missing_args(ctx):
    assert not (await call("nope", {}, ctx)).ok
    r = await call("open_app", {}, ctx)
    assert not r.ok and "name" in r.summary


async def test_youtube_play(ctx, monkeypatch):
    from jarvis.tools import youtube

    monkeypatch.setattr(youtube, "search_youtube", lambda q, n=1: [{"id": "abc123", "title": "Avengers Trailer", "channel": "", "duration": 1}])
    r = await call("youtube_play", {"query": "avengers trailer"}, ctx)
    assert r.ok and "Avengers" in r.summary
    assert ("open_url", "https://www.youtube.com/watch?v=abc123&autoplay=1") in ctx.platform.calls


async def test_volume(ctx):
    r = await call("volume", {"action": "up", "level": 15}, ctx)
    assert r.data == 65 and ctx.platform.volume == 65
    await call("volume", {"action": "set", "level": 150}, ctx)
    assert ctx.platform.volume == 100


async def test_weather(ctx):
    def handler(req):
        if "geocoding" in req.url.host:
            return httpx.Response(200, json={"results": [{"name": "Praha", "latitude": 50, "longitude": 14}]})
        return httpx.Response(200, json={
            "current": {"temperature_2m": 12.3, "apparent_temperature": 10.1, "relative_humidity_2m": 70,
                        "weather_code": 3, "wind_speed_10m": 5},
            "daily": {"time": ["2026-10-23"], "weather_code": [61], "temperature_2m_max": [14],
                      "temperature_2m_min": [6], "precipitation_probability_max": [60]}})

    ctx.transport = httpx.MockTransport(handler)
    r = await call("weather", {}, ctx)
    assert r.ok and "zataženo" in r.summary and r.data["days"][0]["desc"] == "slabý déšť"


async def test_update_setting(ctx):
    r = await call("update_setting", {"key": "voice.tts_rate", "value": "+20%"}, ctx)
    assert r.ok and ctx.cfg.voice.tts_rate == "+20%"
    r = await call("update_setting", {"key": "phone.token", "value": "x"}, ctx)
    assert not r.ok
    r = await call("update_setting", {"key": "brain.chain", "value": json.dumps(["ollama"])}, ctx)
    assert ctx.cfg.brain.chain == ["ollama"]


async def test_remember_forget(ctx):
    await call("remember", {"fact": "Uživatel má rád pizzu"}, ctx)
    assert ctx.memory.facts()[0]["text"] == "Uživatel má rád pizzu"
    await call("forget", {"fact": "pizzu"}, ctx)
    assert ctx.memory.facts() == []


async def test_screenshot_attaches(ctx):
    r = await call("screenshot", {}, ctx)
    assert r.ok and len(r.attachments) == 1
    assert ctx.store.get(r.attachments[0]).kind == "image"


def test_for_llm_truncates():
    assert len(ToolResult(True, "x", data="a" * 50000).for_llm()) < 13000
