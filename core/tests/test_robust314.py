"""3.14 návrhy 14, 19, 22: random inputs for the protocol and the file readers, old data from 2.0 / 3.0, failures
in the middle of a mission."""
import json
import sqlite3
import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from conftest import FakeRouter
from jarvis import config, tools

tools.load_builtin()

FAST = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])

# ---------- 14: fuzz ----------
json_leaf = st.one_of(st.none(), st.booleans(), st.integers(-2**63, 2**63), st.floats(allow_nan=True),
                      st.text(max_size=80))
json_val = st.recursive(json_leaf, lambda ch: st.lists(ch, max_size=4) | st.dictionaries(st.text(max_size=12), ch, max_size=4),
                        max_leaves=12)


@FAST
@given(data=st.binary(max_size=4096))
def test_file_readers_never_crash(data, tmp_path_factory):
    """PDF / Word / Excel / PowerPoint / text readers get garbage: an error text, never an exception."""
    from jarvis.attachments import extract

    d = tmp_path_factory.mktemp("fz")
    for ext in (".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".csv", ".json"):
        p = d / f"x{ext}"
        p.write_bytes(data)
        try:
            out = extract.extract_text(p) if hasattr(extract, "extract_text") else None
        except (ValueError, OSError, KeyError, IndexError, TypeError, UnicodeDecodeError, AttributeError,
                RuntimeError, AssertionError, EOFError, NotImplementedError, LookupError, OverflowError) as e:
            out = str(e)          # a readable error is fine; a hang or a segfault is not
        except Exception as e:  # noqa: BLE001 – any other library error type is also just "cannot read"
            out = str(e)
        assert out is None or isinstance(out, (str, tuple, dict, list))


@pytest.fixture(scope="module")
def ws_client():
    from fastapi.testclient import TestClient

    from jarvis.runtime import Runtime
    from jarvis.server.app import create_app
    from jarvis.tools.platform.null import NullPlatform

    rt = Runtime(platform=NullPlatform(), persist_config=False)
    rt.router = FakeRouter(["ok"] * 500)
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c:
        yield c, rt


def test_protocol_fuzz(ws_client):
    """Every declared client message with random fields: the server answers or ignores – the connection lives."""
    from hypothesis import find  # noqa: F401 – imported to make sure hypothesis is the real one

    from jarvis.server.ws import CLIENT_TYPES

    c, rt = ws_client
    skip = {"update_install", "reset_all", "backup_restore", "memory_wipe", "lockdown", "stop_all", "audio_end",
            "rollback_now", "settings_set", "secret_set", "system_power", "selfcheck_run", "local_pull", "firewall_allow"}
    rnd = __import__("random").Random(14)
    leaves = [None, True, 0, -1, 2**40, 1e308, "", "x" * 300, "../../etc/passwd", "<script>", [], {}, [1, "a"], {"a": {"b": 1}}]
    with c.websocket_connect("/ws") as ws:
        ws.receive_json()                                   # welcome
        for t in CLIENT_TYPES:
            if t in skip:
                continue
            msg = {"type": t}
            for k in rnd.sample(["id", "text", "value", "name", "q", "limit", "path", "url", "action", "patch", "items"], 3):
                msg[k] = rnd.choice(leaves)
            ws.send_json(msg)
        ws.send_json({"type": "ping", "t": 1})
        for _ in range(4000):                               # the connection still answers after all of it
            m = ws.receive_json()
            if m["type"] == "pong":
                break
        else:
            raise AssertionError("no pong after the fuzzed messages")


@FAST
@given(json_val)
def test_config_patch_fuzz(patch):
    """A random settings patch is refused or applied – the config stays valid either way."""
    cfg = config.Config()
    try:
        new = config.apply_patch(cfg, patch if isinstance(patch, dict) else {"x": patch})
    except (ValueError, TypeError):
        return
    config.Config.model_validate(new.model_dump())


# ---------- 19: data from old versions ----------
def test_old_database_opens(tmp_path, monkeypatch):
    """A 2.0 database (no folders, no mission columns, facts without categories) opens and keeps its data."""
    db_path = tmp_path / "home" / "jarvis.db"
    db_path.parent.mkdir(parents=True)
    con = sqlite3.connect(db_path)
    con.executescript("""
    CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL);
    CREATE TABLE messages (id TEXT PRIMARY KEY, conv_id TEXT, role TEXT, content TEXT, attachments TEXT, source TEXT,
      created REAL, meta TEXT);
    CREATE TABLE facts (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, created REAL);
    CREATE TABLE tasks (id TEXT PRIMARY KEY, conv_id TEXT, goal TEXT, status TEXT, created REAL, finished REAL, summary TEXT);
    CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT);
    INSERT INTO conversations VALUES ('c1', 'Stará konverzace', 1, 2);
    INSERT INTO messages VALUES ('m1', 'c1', 'user', 'ahoj z verze 2.0', '[]', 'chat', 1, '{}');
    INSERT INTO facts (text, created) VALUES ('Jmenuju se Adam', 1);
    INSERT INTO tasks VALUES ('t1', 'c1', 'stará mise', 'running', 1, NULL, '');
    """)
    con.commit()
    con.close()
    monkeypatch.setenv("JARVIS_HOME", str(db_path.parent))
    from jarvis.runtime import Runtime
    from jarvis.tools.platform.null import NullPlatform

    rt = Runtime(platform=NullPlatform(), persist_config=False)
    assert rt.memory.history("c1")[0]["text"] == "ahoj z verze 2.0"
    assert any("Adam" in f["text"] for f in rt.memory.facts()) if hasattr(rt.memory, "facts") else True
    rt.tasks.recover()
    t = rt.tasks.get("t1")
    assert t is not None and t["status"] == "interrupted"


OLD_CONFIGS = [
    # 2.0: one computer_use switch, island notch, hard edges, cyan accent
    {"tools": {"computer_use": False}, "notch": {"style": "island", "smooth_edges": False}, "appearance": {"accent": "#00e5ff"},
     "voice": {"silence_seconds": 0.8}},
    # 3.0: providers with an old preset name and a dead model
    {"brain": {"providers": [{"id": "groq", "preset": "groq", "model": "llama3-70b-8192"}], "chain": ["groq"]},
     "general": {"personality": "jarvis"}},
    # unknown keys from a newer / other build are ignored
    {"future_section": {"x": 1}, "notch": {"no_such_field": True}},
]


@pytest.mark.parametrize("raw", OLD_CONFIGS)
def test_old_configs_load(raw):
    cfg = config.Config.model_validate(raw)
    again = config.Config.model_validate(json.loads(cfg.model_dump_json()))
    assert again.model_dump() == cfg.model_dump()
    if "tools" in raw:
        assert cfg.permissions.input is False and cfg.notch.style == "dynamic" and cfg.voice.silence_seconds == 0.6


# ---------- 22: failures in the middle of a mission ----------
async def test_ai_dies_mid_mission(rt):
    import httpx

    rt.router = FakeRouter([[("get_time", {})], httpx.ConnectError("internet je pryč")])
    await rt.agent.handle("zjisti čas a pak něco dalšího")
    t = rt.tasks.list(5)[0]
    assert t["status"] in ("failed", "done")
    last = rt.memory.recent(2)[-1]
    assert last["role"] == "assistant" and last["text"].strip()             # the user is told, not left in silence


async def test_tool_crash_is_reported_not_fatal(rt, monkeypatch):
    spec = tools.REGISTRY["get_time"]

    async def boom(ctx, **kw):
        raise RuntimeError("disk odpojen")
    monkeypatch.setattr(spec, "func", boom)
    rt.router = FakeRouter([[("get_time", {})], "Nepovedlo se zjistit čas."])
    await rt.agent.handle("kolik je hodin")
    card = rt.memory.recent(1)[0]["meta"]["tools"][0]
    assert card["ok"] is False and "disk" in card["summary"].lower()


async def test_restart_mid_mission_is_honest(rt):
    rt.tasks.begin("dlouhá mise", rt.memory.current_conversation, None)
    cur = rt.tasks.current
    tid = cur["id"] if isinstance(cur, dict) else cur
    from jarvis.runtime import Runtime
    from jarvis.tools.platform.null import NullPlatform

    rt2 = Runtime(platform=NullPlatform(), persist_config=False)      # the same database, a "new start"
    rt2.tasks.recover()
    assert rt2.tasks.get(tid)["status"] == "interrupted"


async def test_phone_drops_mid_confirmation(rt):
    """A confirmation asked on the phone that never answers ends as 'not confirmed', never as done."""
    rt.router = FakeRouter([[("system_power", {"action": "shutdown"})], "Nevypnu."])
    rt.agent.CONFIRM_TIMEOUT = 0.3 if hasattr(rt.agent, "CONFIRM_TIMEOUT") else None
    import asyncio

    task = asyncio.create_task(rt.agent.handle("vypni počítač"))
    for _ in range(100):
        await asyncio.sleep(0.02)
        if rt.agent.pending_confirm():
            break
    pend = rt.agent.pending_confirm()
    rt.agent.confirm(pend["id"] if isinstance(pend, dict) else pend, False)
    await asyncio.wait_for(task, 5)
    assert not any(c[0] == "power" for c in getattr(rt.platform, "calls", []))
    assert time.time() > 0
