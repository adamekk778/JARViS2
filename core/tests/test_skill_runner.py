import time

from jarvis import config, tools
from jarvis.permissions import perm_of
from jarvis.tools import skills

tools.load_builtin()

SLEEPY = '''
import asyncio
from jarvis.tools.base import tool, ToolResult
SKILL = {"name": "sleepy", "description": "spí", "permissions": [], "timeout": 1}

@tool("sleepy_wait", "Čeká 5 s.")
async def sleepy_wait(ctx) -> ToolResult:
    await asyncio.sleep(5)
    return ToolResult(True, "vzhůru")
'''
CRASHY = '''
from jarvis.tools.base import tool, ToolResult

@tool("crashy_go", "Spadne.")
async def crashy_go(ctx) -> ToolResult:
    raise RuntimeError("au, tohle bolí")
'''
HELLO = '''
from jarvis.tools.base import tool, ToolResult
SKILL = {"name": "hello", "description": "pozdrav", "version": "1.0", "permissions": ["network"], "timeout": 20}

@tool("hello_say", "Pozdraví.")
async def hello_say(ctx, name: str = "Adam") -> ToolResult:
    ctx.notify("Ahoj", name)
    return ToolResult(True, "ahoj " + name, data={"x": 1})
'''


def _write(name, code):
    p = skills.skills_dir() / f"{name}.py"
    p.write_text(code, encoding="utf-8")
    return p


def test_manifest_parse_without_exec():
    p = _write("boom", 'SKILL = {"name": "boom", "permissions": ["shell"], "timeout": 999}\nraise SystemExit("ne")\n')
    m = skills.read_manifest(p)
    assert m["permissions"] == ["shell"] and m["timeout"] == 300 and m["name"] == "boom"
    d = skills.read_manifest(_write("plain", "x = 1\n"))
    assert d["permissions"] == [] and d["timeout"] == 30


def test_unapproved_not_registered():
    _write("hello", HELLO)
    skills.load_all_skills(approved=set())
    item = next(i for i in skills.list_skills(approved=set()) if i["name"] == "hello")
    assert item["approved"] is False and item["manifest"]["permissions"] == ["network"] and "hello_say" in item["code"]
    assert "hello_say" not in tools.REGISTRY


async def test_create_skill_auto_approved(ctx):
    res = await tools.call("create_skill", {"name": "pozdrav", "code": HELLO.replace("hello_say", "pozdrav_say")}, ctx)
    assert res.ok and "pozdrav" in ctx.cfg.tools.approved_skills
    tools.REGISTRY.pop("pozdrav_say", None)


async def test_runner_timeout(ctx):
    _write("sleepy", SLEEPY)
    skills.load_all_skills(approved={"sleepy"})
    t0 = time.monotonic()
    res = await tools.call("sleepy_wait", {}, ctx)
    assert not res.ok and "časový limit" in res.summary and time.monotonic() - t0 < 4


async def test_runner_crash(ctx):
    _write("crashy", CRASHY)
    skills.load_all_skills(approved={"crashy"})
    res = await tools.call("crashy_go", {}, ctx)
    assert not res.ok and "Skill spadl" in res.summary and "au, tohle bolí" in res.summary


async def test_runner_result_and_notify(ctx):
    _write("hello", HELLO)
    skills.load_all_skills(approved={"hello"})
    res = await tools.call("hello_say", {"name": "Eva"}, ctx)
    assert res.ok and res.summary == "ahoj Eva" and res.data == {"x": 1}
    assert ctx.notified and ctx.notified[-1][:2] == ("Ahoj", "Eva")


def test_permission_from_manifest():
    _write("hello", HELLO)
    skills.load_all_skills(approved={"hello"})
    spec = tools.REGISTRY["hello_say"]
    assert perm_of(spec) == "network"
    cfg = config.Config.model_validate({"permissions": {"network": False}})
    assert "hello_say" not in {s["function"]["name"] for s in tools.schemas((), cfg)}


def test_existing_skills_approved_once(rt):
    _write("hello", HELLO)
    assert skills.migrate_existing(rt) == ["hello"]
    assert "hello" in rt.cfg.tools.approved_skills
    _write("later", HELLO.replace("hello_say", "later_say"))
    assert skills.migrate_existing(rt) == []  # only the 2.0 → 2.1 upgrade, never again
