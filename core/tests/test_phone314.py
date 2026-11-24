"""3.14 telefon (návrhy 9, 93, 94, 97, 99)."""
import subprocess
from pathlib import Path

from jarvis import phoneplus

ROOT = Path(__file__).resolve().parents[2]


def test_widget_push(rt):
    sent = []
    rt.phone_push = lambda kind, **d: sent.append((kind, d)) or True
    rt.tasks.begin("stáhni faktury", rt.memory.current_conversation)
    assert sent and sent[-1][0] == "widget" and "stáhni faktury" in sent[-1][1]["status"]
    rt.tasks.finish("done")
    assert sent[-1][1]["status"] == "Připraven"
    n = len(sent)
    assert not phoneplus.push_widget(rt)                   # nothing changed, too soon
    assert len(sent) == n


async def test_reply_from_phone_answers_to_phone(rt):
    from conftest import FakeRouter

    rt.router = FakeRouter(["Za 20 minut."])
    pushed = []
    rt.phone_push = lambda kind, **d: pushed.append((kind, d)) or True
    import asyncio

    ran = []
    rt.submit = lambda coro: ran.append(asyncio.ensure_future(coro))
    await rt.notice_action("ask", {"text": "kdy jede autobus?", "from_phone": True})
    await asyncio.gather(*ran)
    assert pushed[-1] == ("notify", {"title": "JARVIS", "body": "Za 20 minut."})


def test_phone_notice_route_allows_reply(rt):
    from fastapi.testclient import TestClient

    from jarvis.server.app import create_app

    calls = []

    async def fake(act, args):
        calls.append((act, args))
        return None
    rt.notice_action = fake
    with TestClient(create_app(rt, manage_runtime=False), client=("127.0.0.1", 5000)) as c:
        r = c.post("/api/phone/notice_action", json={"action": "ask", "args": {"text": "ahoj"}})
        assert r.status_code == 200 and calls[0] == ("ask", {"text": "ahoj", "from_phone": True})
        assert c.post("/api/phone/notice_action", json={"action": "run_shell"}).status_code == 400


def test_dynamic_lock_registry():
    cmds = []

    def runner(cmd):
        cmds.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    r = phoneplus.dynamic_lock(True, runner)
    assert r["ok"] and cmds[0][:3] == ["reg", "add", phoneplus.DYNAMIC_LOCK_KEY] and "1" in cmds[0]
    assert cmds[1][-1] == "ms-settings:bluetooth"


def test_android_reply_and_auto_wired():
    link = (ROOT / "mobile" / "native" / "JarvisLink.java").read_text("utf-8")
    assert "addRemoteInput" in link and "SEMANTIC_ACTION_REPLY" in link and 'case "widget"' in link and "MessagingStyle" in link
    conf = (ROOT / "mobile" / "native" / "ConfirmReceiver.java").read_text("utf-8")
    assert "getResultsFromIntent" in conf
    patch = (ROOT / "mobile" / "patch-android.mjs").read_text("utf-8")
    assert "com.google.android.gms.car.application" in patch
    assert (ROOT / "mobile" / "native-res" / "xml" / "automotive_app_desc.xml").exists()


def test_iphone_pwa_meta():
    html = (ROOT / "web" / "mobile.html").read_text("utf-8")
    assert "apple-mobile-web-app-capable" in html and "apple-touch-icon" in html
