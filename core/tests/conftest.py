import pytest


@pytest.fixture(autouse=True)
def jarvis_home(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")
    monkeypatch.setenv("JARVIS_NO_NET", "1")
    return tmp_path / "home"


@pytest.fixture
def ctx(tmp_path):
    """Minimal tool context (the real one is jarvis.runtime.Runtime)."""
    from types import SimpleNamespace

    import httpx

    from jarvis import config
    from jarvis.attachments import AttachmentStore
    from jarvis.events import Bus
    from jarvis.memory import DB, Memory
    from jarvis.tools.platform.null import NullPlatform

    db = DB(tmp_path / "t.db")
    ns = SimpleNamespace(platform=NullPlatform(), bus=Bus(), cfg=config.load(), memory=Memory(db),
                         store=AttachmentStore(tmp_path / "files", db), transport=None, notified=[])
    ns.http = lambda: httpx.AsyncClient(transport=ns.transport)

    def notify(title, body, url="", speak=True, target="all", urgent=False):
        ns.notified.append((title, body, target))
        return 1

    ns.notify = notify
    ns.update_config = lambda patch: setattr(ns, "cfg", config.apply_patch(ns.cfg, patch))
    return ns


class FakeRouter:
    """Scripted LLM: each item is a str (answer) or list[(name, args)] (tool calls) or an Exception."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.last_used = ("fake", "fake-model")

    def update(self, brain):
        pass

    async def stream(self, messages, tools, need_vision=False, fast=False, only=None, model=None):
        from jarvis.llm.base import Chunk, ToolCall

        self.calls.append({"messages": messages, "tools": tools, "need_vision": need_vision, "only": only, "model": model})
        item = self.script.pop(0) if self.script else "konec"
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            for w in item.split(" "):
                yield Chunk(text=w + " ")
            yield Chunk(done=True)
        else:
            yield Chunk(tool_calls=[ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(item)], done=True)

    async def complete(self, messages, need_vision=False, fast=False, only=None, model=None, **kw):
        out = ""
        async for ch in self.stream(messages, None, need_vision, only=only, model=model):
            out += ch.text
        return out


@pytest.fixture
def rt():
    from jarvis.runtime import Runtime
    from jarvis.tools.platform.null import NullPlatform

    r = Runtime(platform=NullPlatform(), persist_config=False)
    r.cfg.stark.smart_quiet = False      # speaking must not depend on the hour the tests run; test_wave8 turns it on
    return r


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out
