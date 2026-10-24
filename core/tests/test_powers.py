"""3.3 everyday powers: selected text, clipboard history, screen time, breaks, website watching, clean-up, e-mail."""
import asyncio
import datetime as dt
import os
import time

import httpx
from conftest import FakeRouter, drain

from jarvis import config, powers, tools


# ---------- selected text ----------
def test_grab_selection_copies_and_restores_clipboard(rt):
    rt.platform.clipboard = "moje schránka"
    rt.platform.selection = "Dobry den, posilam fakturu"
    text, win = powers.grab_selection(rt)
    assert text == "Dobry den, posilam fakturu" and win["app"] == "Poznámkový blok"
    assert rt.platform.clipboard == "moje schránka"
    assert ("hotkey", ("ctrl", "c")) in rt.platform.calls


def test_grab_selection_nothing_selected(rt):
    rt.platform.clipboard = "x"
    rt.platform.selection = None        # Ctrl+C copies nothing → the marker stays
    text, _ = powers.grab_selection(rt)
    assert text == "" and rt.platform.clipboard == "x"


def test_grab_selection_goes_back_to_the_app_when_jarvis_is_in_front(rt):
    rt.activity.last_external = {"hwnd": 777, "pid": 1, "app": "Word", "title": "Dopis"}
    rt.platform.front = {"hwnd": 5, "pid": os.getpid(), "app": "JARVIS", "title": "JARVIS Chat"}
    rt.platform.selection = "text"
    text, win = powers.grab_selection(rt)
    assert ("focus_window", 777) in rt.platform.calls and win["app"] == "Word" and text == "text"


async def test_fix_spelling_replaces_the_selection(rt):
    rt.router = FakeRouter(["Dobrý den, posílám fakturu."])
    rt.platform.clipboard = "puvodni"
    rt.platform.selection = "Dobry den, posilam fakturu"
    q = rt.bus.subscribe()
    await powers.selection_menu(rt)
    ev = drain(q)
    sel = next(e for e in ev if e["type"] == "selection")
    assert sel["text"] == "Dobry den, posilam fakturu" and {a["key"] for a in sel["actions"]} >= {"fix", "translate", "explain"}
    res = await powers.run_selection_action(rt, "fix")
    assert res["replaced"] and res["text"] == "Dobrý den, posílám fakturu."
    pasted = [c for c in rt.platform.calls if c[0] == "clipboard_set"]
    assert ("clipboard_set", "Dobrý den, posílám fakturu.") in pasted and rt.platform.clipboard == "puvodni"
    assert ("hotkey", ("ctrl", "v")) in rt.platform.calls
    assert "Oprav pravopis" in rt.router.calls[0]["messages"][0]["content"]


async def test_explain_does_not_touch_the_app(rt):
    rt.router = FakeRouter(["Je to žádost o zaplacení."])
    rt.platform.selection = "Invoice due in 14 days"
    await powers.selection_menu(rt)
    q = rt.bus.subscribe()
    res = await powers.run_selection_action(rt, "explain")
    assert not res["replaced"] and ("hotkey", ("ctrl", "v")) not in rt.platform.calls
    assert next(e for e in drain(q) if e["type"] == "selection_result")["text"] == "Je to žádost o zaplacení."


async def test_selection_tools_for_voice(rt):
    rt.router = FakeRouter([[("selected_text", {})], [("replace_selected_text", {"text": "Hello"})], "Hotovo."])
    rt.platform.selection = "Ahoj"
    await rt.agent.handle("přelož označené do angličtiny a nahraď to")
    assert ("clipboard_set", "Hello") in rt.platform.calls and ("hotkey", ("ctrl", "v")) in rt.platform.calls


# ---------- activity: clipboard history, screen time, breaks ----------
def test_clipboard_history_skips_passwords_and_duplicates(rt):
    a = rt.activity
    a.sample(now=1000)                       # first look: what was there before is not history
    for t in ["nákupní seznam: mléko", "nákupní seznam: mléko", "Tr0ub4dor&3xK", "https://example.com/a?b=1", "  "]:
        rt.platform.clipboard = t
        a.sample(now=1001)
    assert [c["text"] for c in a.clips] == ["https://example.com/a?b=1", "nákupní seznam: mléko"]
    assert powers.looks_secret("sk-abcdefghijklmnop1234") and not powers.looks_secret("ahoj světe")


async def test_clipboard_history_tool_and_restore(rt):
    rt.activity.clips.appendleft({"text": "adresa: Dlouhá 1", "ts": 1, "app": "Chrome"})
    rt.activity.clips.appendleft({"text": "číslo účtu 123", "ts": 2, "app": "Word"})
    r = await tools.call("clipboard_history", {"query": "adresa"}, rt)
    assert r.ok and "Dlouhá 1" in r.summary and len(r.data) == 1
    assert (await tools.call("clipboard_restore", {"index": 2}, rt)).ok and rt.platform.clipboard == "adresa: Dlouhá 1"
    rt.cfg = config.apply_patch(rt.cfg, {"powers": {"clipboard_history": False}})
    assert not (await tools.call("clipboard_history", {}, rt)).ok


async def test_screen_time_counts_only_when_present(rt):
    a = rt.activity
    rt.platform.front = {"hwnd": 1, "pid": 10, "app": "Steam", "title": "Hra"}
    for i in range(40):                      # 40 samples × 3 s = 2 min of play
        a.sample(now=time.time(), dt_s=3)
    rt.platform.idle = 600                   # away from the PC: not counted
    for i in range(40):
        a.sample(now=time.time(), dt_s=3)
    rt.platform.idle = 0
    rt.platform.front = {"hwnd": 2, "pid": 11, "app": "Word", "title": "Dopis"}
    for i in range(20):
        a.sample(now=time.time(), dt_s=3)
    assert a.screen_time(1) == [{"app": "Steam", "minutes": 2}, {"app": "Word", "minutes": 1}]
    r = await tools.call("screen_time", {"period": "today"}, rt)
    assert r.ok and r.summary.startswith("Dnes celkem 3 min. Steam 2 min, Word 1 min")


def test_jarvis_itself_is_not_screen_time(rt):
    rt.platform.front = {"hwnd": 3, "pid": os.getpid(), "app": "JARVIS", "title": "JARVIS"}
    for _ in range(30):
        rt.activity.sample(dt_s=3)
    assert rt.activity.screen_time(1) == []


async def test_break_reminder_once_and_reset_after_a_break(rt, monkeypatch):
    said = []
    monkeypatch.setattr(rt, "notify", lambda title, body, **k: said.append(body))
    monkeypatch.setattr(rt, "call_soon", lambda fn, *a: fn(*a))
    rt.cfg = config.apply_patch(rt.cfg, {"powers": {"break_minutes": 60}})
    a = rt.activity
    for m in range(0, 70):
        a._breaks(1000 + m * 60, 0, 60)
    assert len(said) == 1 and "60 minut" in said[0]
    a._breaks(1000 + 71 * 60, 400, 60)       # away for more than 5 minutes = the break happened
    for m in range(72, 140):
        a._breaks(1000 + m * 60, 0, 60)
    assert len(said) == 2


# ---------- website watching ----------
def _site(text):
    return httpx.MockTransport(lambda req: httpx.Response(200, text=f"<html><script>x()</script><body><h1>Boty</h1><p>{text}</p></body></html>"))


async def test_watch_waits_for_text_then_fires_once(rt):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    rt.transport = _site("Momentálně vyprodáno")
    r = await tools.call("watch_website", {"url": "eshop.cz/boty", "text": "skladem", "minutes": 1}, rt)
    assert r.ok and "každých 5 min" in r.summary
    job = rt.scheduler.get(r.data["id"])
    assert job["kind"] == "watch" and job["payload"]["url"] == "https://eshop.cz/boty"
    said = []
    rt.notify = lambda title, body, **k: said.append(body)
    await rt.scheduler._run(job)
    assert said == []
    rt.transport = _site("Nyní skladem: 3 kusy")
    await rt.scheduler._run(job)
    assert len(said) == 1 and "skladem" in said[0] and rt.scheduler.get(job["id"]) is None


async def test_watch_any_change(rt):
    from jarvis.scheduler import Scheduler

    rt.scheduler = Scheduler(rt)
    rt.transport = _site("Cena 999 Kč")
    r = await tools.call("watch_website", {"url": "https://eshop.cz/tv"}, rt)
    job = rt.scheduler.get(r.data["id"])
    said = []
    rt.notify = lambda title, body, **k: said.append(body)
    await rt.scheduler._run(job)
    assert said == []
    rt.transport = _site("Cena 899 Kč")
    await rt.scheduler._run(rt.scheduler.get(job["id"]))
    assert said == ["Stránka https://eshop.cz/tv se změnila."] and rt.scheduler.get(job["id"]) is not None


def test_page_text_strips_scripts_and_tags():
    assert powers.page_text("<style>a{}</style><p>Ahoj&nbsp;<b>světe</b></p><script>alert(1)</script>") == "Ahoj světe"


# ---------- disk ----------
def test_clean_temp_only_old_files(tmp_path):
    old, new = tmp_path / "old.tmp", tmp_path / "new.tmp"
    sub = tmp_path / "dir"
    sub.mkdir()
    (sub / "old2.log").write_bytes(b"x" * 50)
    old.write_bytes(b"x" * 100)
    new.write_bytes(b"x" * 10)
    past = time.time() - 3 * 86400
    for f in (old, sub / "old2.log"):
        os.utime(f, (past, past))
    n, freed = powers.clean_temp([tmp_path])
    assert (n, freed) == (2, 150) and new.exists() and not old.exists() and not sub.exists()


def test_storage_report(tmp_path):
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "film.mkv").write_bytes(b"\0" * (101 * 2**20))
    (tmp_path / "Desktop").mkdir()
    (tmp_path / "Desktop" / "a.txt").write_text("ahoj")
    r = powers.storage_report(tmp_path)
    assert r["folders"][0]["name"] == "Downloads" and r["big_downloads"][0]["path"].endswith("film.mkv")
    assert powers.fmt_bytes(101 * 2**20) == "101,0 MB"


async def test_clean_pc_needs_confirmation(rt):
    assert tools.is_dangerous(tools.REGISTRY["clean_pc"], {}, [], [], rt)
    lines = tools.details_for(tools.REGISTRY["clean_pc"], {"temp": True, "recycle_bin": True}, rt)
    assert any("Vysypat koš" in x for x in lines) and any("Dočasné soubory" in x for x in lines)


# ---------- e-mail ----------
async def test_compose_email_only_opens_a_draft(rt):
    r = await tools.call("compose_email", {"to": "petr@example.cz", "subject": "Zítra", "body": "Ahoj Petře,\nzítra nepřijdu."}, rt)
    url = next(c[1] for c in rt.platform.calls if c[0] == "open_url")
    assert r.ok and url.startswith("mailto:petr@example.cz?subject=Z%C3%ADtra&body=Ahoj%20Pet%C5%99e%2C%0Az%C3%ADtra")


async def test_speed_test_reports_mbps(rt):
    def handler(req):
        if req.url.path == "/__down":
            return httpx.Response(200, content=b"\0" * 2_000_000)
        return httpx.Response(200, text="ok")

    rt.transport = httpx.MockTransport(handler)
    r = await tools.call("speed_test", {}, rt)
    assert r.ok and r.data["down_mbps"] > 0 and "Stahování" in r.summary
