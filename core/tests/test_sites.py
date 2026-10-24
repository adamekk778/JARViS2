"""3.1 website builder: "udělej mi web" → files in the sites folder, a sandboxed preview in the chat, the full chat page."""
from conftest import FakeRouter, drain
from fastapi.testclient import TestClient

from jarvis import tools
from jarvis.server.app import create_app
from jarvis.tools.sites import list_sites, safe_rel, site_path, slugify

PAGE = "<!doctype html><html><head><link rel=stylesheet href=style.css></head><body><h1>Kavárna</h1></body></html>"


def test_slug_and_safe_paths():
    assert slugify("Kavárna U Lípy!") == "kavarna-u-lipy" and slugify("???") == "web"
    assert safe_rel("style.css") == "style.css" and safe_rel("./js/app.js") == "js/app.js"
    for bad in ("../x.html", "/etc/passwd.html", "a/../../b.css", "C:/x.html", "run.exe", "a//b.css", ""):
        assert safe_rel(bad) is None, bad


async def test_make_website_and_update(rt):
    res = await tools.call("make_website", {"title": "Kavárna U Lípy", "html": PAGE, "files": {"style.css": "h1{color:red}"}}, rt)
    assert res.ok and res.preview.startswith("/sites/kavarna-u-lipy-") and res.preview.endswith("/index.html")
    sid = res.data["site"]
    root = site_path(sid)
    assert (root / "index.html").read_text("utf-8") == PAGE and (root / "style.css").exists()
    assert list_sites()[0]["title"] == "Kavárna U Lípy"
    upd = await tools.call("make_website", {"title": "Kavárna U Lípy", "site": sid, "files": '{"style.css": "h1{color:blue}"}'}, rt)
    assert upd.ok and upd.data["site"] == sid and (root / "style.css").read_text("utf-8") == "h1{color:blue}"
    assert (await tools.call("read_website", {"site": sid, "file": "style.css"}, rt)).summary == "h1{color:blue}"


async def test_make_website_refuses_bad_input(rt):
    assert not (await tools.call("make_website", {"title": "x", "files": {"style.css": "a"}}, rt)).ok   # new site needs index.html
    assert not (await tools.call("make_website", {"title": "x", "html": PAGE, "files": {"../evil.html": "x"}}, rt)).ok
    assert not (await tools.call("make_website", {"title": "x", "html": PAGE, "site": "neni-0123456789"}, rt)).ok
    assert not (await tools.call("read_website", {"site": "../config"}, rt)).ok


async def test_agent_sends_preview_with_tool_end_and_keeps_it_in_history(rt):
    rt.router = FakeRouter([[("make_website", {"title": "Portfolio", "html": PAGE})], "Hotovo, tady je náhled."])
    q = rt.bus.subscribe()
    await rt.agent.handle("udělej mi web portfolio")
    end = next(e for e in drain(q) if e["type"] == "tool_end")
    assert end["ok"] and end["preview"].startswith("/sites/portfolio-")
    card = rt.memory.recent()[-1]["meta"]["tools"][0]
    assert card["preview"] == end["preview"] and card["label"] == "Stavím web: Portfolio"


async def test_site_is_served_sandboxed_without_token(rt):
    res = await tools.call("make_website", {"title": "Test", "html": PAGE, "files": {"style.css": "h1{}"}}, rt)
    app = create_app(rt, manage_runtime=False)
    with TestClient(app, client=("192.168.1.9", 5000)) as c:   # the phone: no token, the random id is the key
        r = c.get(res.preview)
        assert r.status_code == 200 and "Kavárna" in r.text
        assert "sandbox" in r.headers["content-security-policy"] and "allow-same-origin" not in r.headers["content-security-policy"]
        assert c.get(res.preview.replace("index.html", "style.css")).status_code == 200
        assert c.get(res.preview.replace("index.html", "..%2F..%2Fconfig.json")).status_code == 404
        assert c.get("/sites/test-0000000000/index.html").status_code == 404
        assert c.get("/sites/..%2F..%2F/index.html").status_code == 404


def test_full_chat_and_site_messages_are_local_only(rt):
    app = create_app(rt, manage_runtime=False)
    opened = []
    rt.ui_hook = opened.append
    with TestClient(app, client=("192.168.1.9", 5000)).websocket_connect(f"/ws?token={rt.cfg.phone.token}") as ws:
        ws.receive_json()
        ws.send_json({"type": "open_window", "view": "full"})
        assert ws.receive_json()["type"] == "error" and opened == []
    with TestClient(app, client=("127.0.0.1", 5000)).websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "open_window", "view": "full"})
        ws.send_json({"type": "sites_get"})
        while (m := ws.receive_json())["type"] != "sites":
            pass
        assert opened == ["full"] and m["items"] == []
