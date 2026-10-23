"""Regression tests for the findings of the 2.1 whole-branch review (C1, I1–I12)."""
import asyncio
import shutil
import subprocess
import time

import pytest
from conftest import FakeRouter, drain

from jarvis import config, lang, tools
from jarvis.redact import looks_secret, redact

tools.load_builtin()


async def _wait(q, pred, timeout=2.0):
    end = asyncio.get_running_loop().time() + timeout
    seen = []
    while asyncio.get_running_loop().time() < end:
        while not q.empty():
            e = q.get_nowait()
            seen.append(e)
            if pred(e):
                return e, seen
        await asyncio.sleep(0.01)
    raise AssertionError([e["type"] for e in seen])


# ---------- C1: refs must not bypass the risky-click confirmation ----------
def test_c1_risky_ref_needs_confirmation(ctx):
    spec = tools.REGISTRY["ui_click"]
    ref = ctx.platform.ui_find(window="Kalkulačka", name="Odeslat")["ref"]
    assert tools.is_dangerous(spec, {"target": ref}, ctx=ctx)
    safe = ctx.platform.ui_find(window="Kalkulačka", name="Sedm")["ref"]
    assert not tools.is_dangerous(spec, {"target": safe}, ctx=ctx)


async def test_c1_agent_asks_before_clicking_risky_ref(rt):
    ref = rt.platform.ui_find(window="Kalkulačka", name="Odeslat")["ref"]
    rt.router = FakeRouter([[("ui_click", {"target": ref, "window": "Kalkulačka"})], "Hotovo."])
    q = rt.bus.subscribe()
    task = asyncio.create_task(rt.agent.handle("odešli to"))
    ev, _ = await _wait(q, lambda e: e["type"] == "confirm_request")
    rt.agent.confirm(ev["id"], False)
    await task
    assert not any(c[0] == "ui_act" for c in rt.platform.calls)


# ---------- I1: Zrušit / Esc resolves an open confirmation ----------
async def test_i1_stop_resolves_confirmation(rt):
    rt.router = FakeRouter([[("system_power", {"action": "shutdown"})], "x"])
    q = rt.bus.subscribe()
    task = asyncio.create_task(rt.agent.handle("vypni"))
    ev, _ = await _wait(q, lambda e: e["type"] == "confirm_request")
    rt.agent.stop()
    await asyncio.wait_for(task, 1)
    res, _ = await _wait(q, lambda e: e["type"] == "confirm_resolved")
    assert res["id"] == ev["id"] and res["approved"] is False


# ---------- I2: messages while paused / queued work after STOP ----------
class SlowRouter(FakeRouter):
    async def stream(self, messages, tools, need_vision=False, fast=False):
        await asyncio.sleep(0.15)
        async for ch in super().stream(messages, tools, need_vision, fast):
            yield ch


async def test_i2_message_while_paused_is_answered(rt):
    rt.router = SlowRouter([[("get_time", {})], [("get_time", {})], "Hotovo."])
    q = rt.bus.subscribe()
    first = asyncio.create_task(rt.agent.handle("dva kroky"))
    await _wait(q, lambda e: e["type"] == "tool_end")
    rt.tasks.pause()
    out = await asyncio.wait_for(rt.agent.handle("smaž ty soubory"), 1)
    assert "pozastaven" in out.lower()
    ev = drain(q)
    assert any(e["type"] == "error" and "pozastaven" in e["message"].lower() for e in ev)
    rt.stop_all()
    await asyncio.wait_for(first, 1)


async def test_i2_stop_all_drops_queued_requests(rt):
    rt.router = SlowRouter([[("get_time", {})], "první hotovo", "druhé by nemělo běžet"])
    q = rt.bus.subscribe()
    first = asyncio.create_task(rt.agent.handle("první"))
    await _wait(q, lambda e: e["type"] == "tool_start")
    second = asyncio.create_task(rt.agent.handle("druhé"))
    await asyncio.sleep(0.05)
    rt.stop_all()
    await asyncio.wait_for(asyncio.gather(first, second), 2)
    assert not any(m["text"] == "druhé" for m in rt.memory.recent())
    assert len(rt.router.calls) <= 2


# ---------- I3: unexpected exception ends the task ----------
async def test_i3_unexpected_error_fails_task(rt):
    rt.router = FakeRouter([[("get_time", {})], RuntimeError("bug")])
    await rt.agent.handle("první")
    assert rt.tasks.list()[0]["status"] == "failed" and rt.tasks.current is None
    rt.router = FakeRouter([[("get_time", {})], "ok"])
    await rt.agent.handle("druhý úkol")
    goals = {t["goal"]: t["status"] for t in rt.tasks.list()}
    assert goals == {"první": "failed", "druhý úkol": "done"}


# ---------- I4: Czech without diacritics stays Czech ----------
@pytest.mark.parametrize("text", ["pust to na youtube", "dej to do me slozky", "napis mi to do poznamek", "a co to je",
                                  "otevri mi spotify a pust hudbu"])
def test_i4_czech_without_diacritics(text):
    assert lang.detect(text) == "cs"


@pytest.mark.parametrize("text", ["What is the weather like today", "Please open the calculator for me"])
def test_i4_english_still_english(text):
    assert lang.detect(text) == "en"


# ---------- I5: redaction gaps ----------
@pytest.mark.parametrize("secret", ["gsk_abcdefghijklmnopqrstuvwxyz123456", "hf_abcdefghijklmnopqrstuvwxyz12",
                                    "github_pat_11ABCDEFG0123456789_abcdefghijklmnop"])
def test_i5_provider_keys_redacted(secret):
    assert secret not in redact(f"klíč {secret} konec")
    assert looks_secret(f"Můj API klíč je {secret}")


def test_i5_env_style_and_bare_token():
    assert "abcdef0123456789abcdef" not in redact("GROQ_API_KEY=abcdef0123456789abcdef")
    assert "abcdef0123456789abcdef" not in redact("HF_TOKEN=abcdef0123456789abcdef")
    assert "0123456789abcdef0123456789abcdef" not in redact("token 0123456789abcdef0123456789abcdef")
    assert redact("klíč od bytu je pod rohožkou") == "klíč od bytu je pod rohožkou"


# ---------- I6: computer_use needs the screen permission too ----------
async def test_i6_computer_use_needs_screen(ctx):
    cfg = config.Config.model_validate({"permissions": {"screen": False}})
    assert "computer_use" not in {s["function"]["name"] for s in tools.schemas((), cfg)}
    ctx.cfg = cfg
    res = await tools.call("computer_use", {"task": "x"}, ctx)
    assert not res.ok and "Obrazovka" in res.summary


# ---------- I7 / I12: restore with Czech names, preview by project name, copy checkpoints ----------
def _git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def proj(tmp_path, ctx):
    if not shutil.which("git"):
        pytest.skip("git missing")
    root = tmp_path / "Projekty"
    repo = root / "app"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "a.txt").write_text("v1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    ctx.cfg = config.Config.model_validate({"tools": {"allowed_folders": [str(root)]}})
    return repo


async def test_i7_restore_removes_czech_named_file(ctx, proj):
    cp = (await tools.call("checkpoint", {"project": "app"}, ctx)).data["id"]
    (proj / "poznámky.txt").write_text("x", encoding="utf-8")
    (proj / "a.txt").write_text("v2\n", encoding="utf-8")
    details = tools.details_for(tools.REGISTRY["restore_checkpoint"], {"project": "app", "id": cp}, ctx)
    assert any("poznámky.txt" in d for d in details) and any("a.txt" in d for d in details)
    res = await tools.call("restore_checkpoint", {"project": "app", "id": cp}, ctx)
    assert res.ok and not (proj / "poznámky.txt").exists()
    assert (proj / "a.txt").read_text(encoding="utf-8") == "v1\n"


def test_i7_details_outside_allowed_is_empty(ctx, proj, tmp_path):
    other = tmp_path / "jinde"
    other.mkdir()
    assert tools.details_for(tools.REGISTRY["restore_checkpoint"], {"project": str(other), "id": "x"}, ctx) == []


async def test_i12_copy_checkpoints_list_and_restore(ctx, tmp_path):
    root = tmp_path / "Projekty"
    plain = root / "web"
    plain.mkdir(parents=True)
    (plain / "index.html").write_text("v1", encoding="utf-8")
    ctx.cfg = config.Config.model_validate({"tools": {"allowed_folders": [str(root)]}})
    cp = (await tools.call("checkpoint", {"project": "web"}, ctx)).data["id"]
    lst = await tools.call("checkpoints", {"project": "web"}, ctx)
    assert lst.ok and [c["id"] for c in lst.data] == [cp]
    (plain / "index.html").write_text("v2", encoding="utf-8")
    res = await tools.call("restore_checkpoint", {"project": "web", "id": cp}, ctx)
    assert res.ok and (plain / "index.html").read_text(encoding="utf-8") == "v1"


# ---------- I8: no blocking work on the event loop ----------
def test_i8_size_is_capped(tmp_path):
    from jarvis.tools import files

    big = tmp_path / "big"
    big.mkdir()
    for i in range(files.SIZE_SCAN_LIMIT + 50):
        (big / f"{i}.txt").write_bytes(b"x")
    assert files._size(big).startswith(">")


async def test_i8_local_status_does_not_block_loop(rt, monkeypatch):
    import httpx

    from jarvis.llm import local

    def slow_hw(force=False):
        time.sleep(0.4)
        return {"ram_gb": 32, "cores": 8, "gpus": [], "disk_free_gb": 100}

    monkeypatch.setattr(local, "detect_hardware", slow_hw)
    rt.local.transport = httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("x", request=req)))
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    t = asyncio.create_task(ticker())
    await rt.local.status()
    t.cancel()
    assert ticks >= 4


# ---------- I9: migrated 2.0 skills keep working ----------
LEGACY = '''
from jarvis.tools.base import tool, ToolResult

@tool("legacy_apps", "Vypíše aplikace.")
async def legacy_apps(ctx) -> ToolResult:
    return ToolResult(True, ", ".join(ctx.platform.list_apps()))
'''


async def test_i9_migrated_skill_keeps_platform(rt):
    from jarvis.tools import skills

    (skills.skills_dir() / "legacy.py").write_text(LEGACY, encoding="utf-8")
    skills.migrate_existing(rt)
    skills.load_all_skills(rt.cfg.tools.approved_skills, rt.cfg.tools.legacy_skills)
    res = await tools.call("legacy_apps", {}, rt)
    assert res.ok, res.summary
    tools.REGISTRY.pop("legacy_apps", None)


# ---------- I10: a missing local model is remembered and shown ----------
def test_i10_missing_model_in_welcome(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    rt.local.set_missing("qwen2.5:3b", 1.9)
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c, c.websocket_connect("/ws") as ws:
        w = ws.receive_json()
        assert w["type"] == "welcome" and w["local_missing"] == {"name": "qwen2.5:3b", "size_gb": 1.9}
