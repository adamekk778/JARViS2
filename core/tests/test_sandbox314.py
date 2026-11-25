"""3.14 návrh 10: run_python in a fenced process."""
import sys

import pytest

from jarvis import tools

tools.load_builtin()


async def run(rt, code):
    return await tools.call("run_python", {"code": code, "timeout": 30}, rt)


async def test_normal_work_and_own_files(rt):
    r = await run(rt, "import json, math\nprint(math.sqrt(16))\nopen('out.txt','w').write('ahoj')\nprint(json.dumps({'a': 1}))")
    assert r.ok, r.data
    assert "4.0" in r.data["stdout"] and r.data["files"] == 1


async def test_writes_outside_are_refused(rt, tmp_path):
    target = tmp_path / "evil.txt"
    r = await run(rt, f"open({str(target)!r}, 'w').write('x')")
    assert not r.ok and "Omezené prostředí" in r.data["stderr"] and not target.exists()


async def test_no_programs_no_network(rt):
    r = await run(rt, "import subprocess\nsubprocess.run(['echo', 'hi'])")
    assert not r.ok and "Omezené prostředí" in r.data["stderr"]
    r = await run(rt, "import os\nos.system('echo hi')")
    assert not r.ok and "Omezené prostředí" in r.data["stderr"]
    r = await run(rt, "import socket\nsocket.create_connection(('1.1.1.1', 80), timeout=2)")
    assert not r.ok and "síť je vypnutá" in r.data["stderr"]


async def test_delete_outside_refused(rt, tmp_path):
    victim = tmp_path / "keep.txt"
    victim.write_text("data")
    r = await run(rt, f"import os\nos.remove({str(victim)!r})")
    assert not r.ok and victim.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX memory limit")
async def test_memory_limit(rt):
    r = await run(rt, "x = bytearray(3 * 1024 ** 3)\nprint(len(x))")
    assert not r.ok


async def test_sandbox_can_be_switched_off(rt, tmp_path):
    rt.cfg.tools.sandbox_code = False
    target = tmp_path / "ok.txt"
    r = await run(rt, f"open({str(target)!r}, 'w').write('x')")
    assert r.ok and target.exists()


async def test_loopback_is_not_the_network(rt):
    # asyncio's self-pipe on Windows connects to 127.0.0.1 – it must not count as network access
    r = await run(rt, "import socket\ntry:\n    socket.create_connection(('127.0.0.1', 9), timeout=1)\nexcept PermissionError:\n"
                      "    raise\nexcept OSError:\n    pass\nimport asyncio\nasyncio.run(asyncio.sleep(0))\nprint('ok')")
    assert r.ok and "ok" in r.data["stdout"], r.data


SKILL_NO_SHELL = '''import subprocess
from jarvis.tools.base import ToolResult, tool

SKILL = {"name": "tichy", "permissions": [], "timeout": 20}


@tool("tichy_echo", "Spustí echo.")
async def tichy_echo(ctx, what: str = "ahoj") -> ToolResult:
    if what == "net":
        import socket
        socket.create_connection(("1.1.1.1", 80), timeout=2)
    if what == "write":
        open("/etc/jarvis-test-zakazano.txt", "w").write("x")
    if what == "own":
        import tempfile, os
        with open(os.path.join(tempfile.gettempdir(), "jarvis-skill-ok.txt"), "w") as f:
            f.write("ok")
        return ToolResult(True, "zapsáno")
    out = subprocess.run(["echo", what], capture_output=True, text=True)
    return ToolResult(True, out.stdout.strip())
'''


async def test_skill_manifest_is_enforced(rt):
    res = await tools.call("create_skill", {"name": "tichy", "code": SKILL_NO_SHELL}, rt)
    assert res.ok, res.summary
    r = await tools.call("tichy_echo", {"what": "ahoj"}, rt)
    assert not r.ok and "spouštět programy" in r.summary
    r = await tools.call("tichy_echo", {"what": "net"}, rt)
    assert not r.ok and "síť je vypnutá" in r.summary
    r = await tools.call("tichy_echo", {"what": "write"}, rt)
    assert not r.ok and "zapisovat smím jen" in r.summary
    r = await tools.call("tichy_echo", {"what": "own"}, rt)
    assert r.ok, r.summary
    allowed = SKILL_NO_SHELL.replace('"permissions": []', '"permissions": ["shell"]')
    await tools.call("create_skill", {"name": "tichy", "code": allowed}, rt)
    r = await tools.call("tichy_echo", {"what": "ahoj"}, rt)
    assert r.ok and r.summary == "ahoj", r.summary
    await tools.call("delete_skill", {"name": "tichy"}, rt)
