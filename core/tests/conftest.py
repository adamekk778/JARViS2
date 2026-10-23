import pytest


@pytest.fixture(autouse=True)
def jarvis_home(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.fail.Keyring")
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

    def notify(title, body, url="", speak=True, target="all"):
        ns.notified.append((title, body, target))
        return 1

    ns.notify = notify
    ns.update_config = lambda patch: setattr(ns, "cfg", config.apply_patch(ns.cfg, patch))
    return ns
