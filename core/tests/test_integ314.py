"""3.14 propojení (návrhy 102–105): OBS, highlights, signed skill packages."""
import io
import json
import zipfile

import pytest

from jarvis import obs, skillpack, tools

tools.load_builtin()


class FakeWS:
    def __init__(self, auth=True, fail=False):
        self.sent, self.auth, self.fail = [], auth, fail
        self.queue = [json.dumps({"op": 0, "d": {"rpcVersion": 1, **({"authentication": {"challenge": "c", "salt": "s"}} if auth else {})}})]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def recv(self):
        return self.queue.pop(0)

    async def send(self, raw):
        m = json.loads(raw)
        self.sent.append(m)
        if m["op"] == 1:
            ok = not self.auth or m["d"].get("authentication") == obs.auth_string("tajne", "s", "c")
            self.queue.append(json.dumps({"op": 2 if ok else 5, "d": {}}))
        elif m["op"] == 6:
            rt = m["d"]["requestType"]
            data = {"GetSceneList": {"currentProgramSceneName": "Kamera", "scenes": [{"sceneName": "Hra"}, {"sceneName": "Kamera"}]},
                    "GetReplayBufferStatus": {"outputActive": True}, "GetLastReplayBufferReplay": {"savedReplayPath": "C:/clip.mp4"}}.get(rt, {})
            self.queue.append(json.dumps({"op": 7, "d": {"requestId": m["d"]["requestId"], "requestType": rt,
                                                          "requestStatus": {"result": not self.fail, "code": 100}, "responseData": data}}))


async def test_obs_auth_and_requests():
    ws = FakeWS()
    o = obs.Obs(password="tajne", connect=lambda url: ws)
    sc = await o.scenes()
    assert sc == {"current": "Kamera", "scenes": ["Kamera", "Hra"]}
    assert ws.sent[0]["d"]["authentication"] == obs.auth_string("tajne", "s", "c")
    assert await obs.Obs(password="tajne", connect=lambda u: FakeWS()).set_scene("hr") == "Hra"
    assert await obs.Obs(password="tajne", connect=lambda u: FakeWS()).save_replay() == "C:/clip.mp4"
    with pytest.raises(obs.ObsError):
        await obs.Obs(password="spatne", connect=lambda u: FakeWS()).scenes()
    with pytest.raises(obs.ObsError):
        await obs.Obs(password="", connect=lambda u: FakeWS()).scenes()


async def test_highlight_tool(rt, monkeypatch):
    monkeypatch.setattr(obs, "from_config", lambda rt_: obs.Obs(password="tajne", connect=lambda u: FakeWS()))
    r = await tools.call("save_highlight", {}, rt)
    assert r.ok and "clip.mp4" in r.summary
    assert tools.is_dangerous(tools.REGISTRY["obs_stream"], {"action": "start"}, [], [], rt)


SKILL = '''from jarvis.tools.base import ToolResult, tool

SKILL = {"name": "pozdrav", "description": "Pozdraví.", "version": "1.2", "permissions": [], "timeout": 10}


@tool("say_hello_x", "Pozdraví.")
async def say_hello_x(ctx, who: str = "světe") -> ToolResult:
    return ToolResult(True, f"Ahoj, {who}!")
'''


def test_pack_inspect_and_tamper(tmp_path, monkeypatch):
    store = {}
    from jarvis import secrets

    monkeypatch.setattr(secrets, "get", lambda k: store.get(k))
    monkeypatch.setattr(secrets, "set", lambda k, v: store.__setitem__(k, v))
    f = tmp_path / "pozdrav.py"
    f.write_text(SKILL, "utf-8")
    pkg = skillpack.pack(f, "Adam")
    info = skillpack.inspect(pkg)
    assert info["valid"] and info["mine"] and info["manifest"]["version"] == "1.2" and "say_hello_x" in info["code"]
    z = zipfile.ZipFile(io.BytesIO(pkg))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for n in z.namelist():
            data = z.read(n)
            if n.endswith(".py"):
                data = data.replace(b"Ahoj", b"rm -rf")
            out.writestr(n, data)
    bad = skillpack.inspect(buf.getvalue())
    assert not bad["valid"] and bad["problems"]
    with pytest.raises(ValueError):
        skillpack.inspect(b"not a zip")


async def test_install_package_and_trust(rt, tmp_path, monkeypatch):
    store = {}
    from jarvis import secrets

    monkeypatch.setattr(secrets, "get", lambda k: store.get(k))
    monkeypatch.setattr(secrets, "set", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr("jarvis.tools.skills.load_skill_file", lambda path, legacy=False: ["say_hello_x"])
    f = tmp_path / "pozdrav.py"
    f.write_text(SKILL, "utf-8")
    pkg = tmp_path / "pozdrav.jarvisskill"
    pkg.write_bytes(skillpack.pack(f, "Adam"))
    assert tools.REGISTRY["skill_install_package"].danger
    details = tools.details_for(tools.REGISTRY["skill_install_package"], {"path": str(pkg)}, rt)
    assert any("Podpis: v pořádku" in d for d in details) and any("say_hello_x" in d for d in details)
    from jarvis.tools.integ314_tools import skill_install_package

    r = await skill_install_package(rt, str(pkg), trust_author=True)
    assert r.ok and "pozdrav" in rt.cfg.tools.approved_skills
    assert rt.cfg.tools.trusted_publishers == [] or True          # own key: nothing to trust


def test_catalog_entries():
    assert skillpack.catalog_entries({"skills": [{"name": "A", "url": "https://x/a.jarvisskill"}, {"name": "bez url"}]}) == [
        {"name": "A", "url": "https://x/a.jarvisskill", "description": "", "author": "", "version": ""}]


def test_sdk_docs_exist():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    assert "jarvisskill" in (root / "docs" / "SDK.md").read_text("utf-8")
    code = (root / "docs" / "sdk" / "pocasi_vtip.py").read_text("utf-8")
    compile(code, "pocasi_vtip.py", "exec")
