import httpx

from jarvis.updater import Updater, newer


def test_newer():
    assert newer("2.0.10", "2.0.9")
    assert newer("v2.1.0", "2.0.99")
    assert not newer("2.0.8", "2.0.8")
    assert not newer("2.0.7", "2.0.8")


def release(tag):
    return {"tag_name": tag, "body": "novinky", "assets": [
        {"name": "JARVIS.apk", "browser_download_url": "https://x/JARVIS.apk"},
        {"name": "JARVIS-Setup.exe", "browser_download_url": "https://x/JARVIS-Setup.exe"}]}


async def test_check_available_publishes_and_notifies(rt):
    u = Updater(rt, httpx.MockTransport(lambda r: httpx.Response(200, json=release("v2.0.9"))), current="2.0.8")
    q = rt.bus.subscribe()
    res = await u.check()
    assert res["version"] == "2.0.9" and u.status["available"]
    types = []
    while not q.empty():
        types.append(q.get_nowait()["type"])
    assert "update_status" in types and "notify" in types


async def test_check_silent_on_404_and_offline(rt):
    q = rt.bus.subscribe()
    u = Updater(rt, httpx.MockTransport(lambda r: httpx.Response(404, json={"message": "Not Found"})), current="2.0.8")
    assert await u.check() is None

    def boom(r):
        raise httpx.ConnectError("offline")

    u2 = Updater(rt, httpx.MockTransport(boom), current="2.0.8")
    assert await u2.check() is None
    assert q.empty()


async def test_same_version_no_update(rt):
    u = Updater(rt, httpx.MockTransport(lambda r: httpx.Response(200, json=release("v2.0.8"))), current="2.0.8")
    assert await u.check() is None and not u.status["available"]


async def test_download_reports_progress_but_never_installs_itself(rt, monkeypatch):
    payload = b"MZ" + b"x" * 200_000

    def handler(r):
        if r.url.path.endswith("latest"):
            return httpx.Response(200, json=release("v9.9.9"))
        return httpx.Response(200, content=payload, headers={"content-length": str(len(payload))})

    u = Updater(rt, httpx.MockTransport(handler), current="2.0.8")
    u.min_size = 1000
    installed = []
    monkeypatch.setattr(u, "install", lambda p: installed.append(p))
    await u.check()
    assert installed == []  # check alone never installs
    q = rt.bus.subscribe()
    path = await u.download()
    assert path.read_bytes() == payload and u.status["state"] == "ready"
    progress = []
    while not q.empty():
        e = q.get_nowait()
        if e["type"] == "update_status" and e["state"] == "downloading":
            progress.append(e["progress"])
    assert progress and progress == sorted(progress)
    assert installed == []


async def test_failed_download_says_why_in_the_status(rt):
    def handler(r):
        if r.url.path.endswith("latest"):
            return httpx.Response(200, json=release("v9.9.9"))
        return httpx.Response(200, content=b"<html>not an installer</html>")

    u = Updater(rt, httpx.MockTransport(handler), current="2.0.8")
    await u.check()
    await u.download_and_install()
    assert u.status["state"] == "error" and "instalátor" in u.status["error"]


def test_built_app_knows_its_version():
    """CI writes jarvis/_version.py with the build number; without it every build said 3.10.0 and kept offering
    the update it had just installed."""
    import pathlib

    wf = (pathlib.Path(__file__).parents[2] / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    assert "core/jarvis/_version.py" in wf and "$r.version -ne $env:JARVIS_VERSION" in wf
