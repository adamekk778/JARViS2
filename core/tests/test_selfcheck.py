"""3.12 Kontrola funkcí: every part checked on this PC, in plain words, with what to do."""
import asyncio

from jarvis import selfcheck


def test_runs_everywhere_and_says_what_to_do(rt):
    async def tester(pid):
        return {"ok": False, "message": "ConnectError: All connection attempts failed (localhost:20128)"}

    items = asyncio.run(selfcheck.run(rt, tester))
    keys = [i["key"] for i in items]
    assert keys[:6] == ["media", "loopback", "mic", "stt", "tts", "brain"] and "lan" in keys
    brain = next(i for i in items if i["key"] == "brain")
    assert brain["ok"] is False and "API klíč" in brain["fix"]                   # the localhost brain → paste a key
    for i in items:
        assert i["name"] and i["detail"] and i["ok"] in (True, False, None)


def test_a_missing_part_says_reinstall(monkeypatch, rt):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "sounddevice":
            raise ModuleNotFoundError("No module named 'sounddevice'", name="sounddevice")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    r = selfcheck.microphone(rt)
    assert r["ok"] is False and "nainstaluj nejnovější" in r["fix"] and "sounddevice" in r["fix"]


def test_working_brain(rt):
    async def tester(pid):
        return {"ok": True, "ms": 321}

    r = asyncio.run(selfcheck.brain(rt, tester))
    assert r["ok"] and "321" in r["detail"]


def test_phone_blocked_warning_once_a_day(rt, monkeypatch):
    notes = []
    rt.notify = lambda title, body, **k: notes.append((title, body))
    monkeypatch.setattr(selfcheck, "WIN", True)
    monkeypatch.setattr(selfcheck, "phone_net", lambda rt_: [
        {"key": "lan", "ok": True, "detail": "ok", "fix": ""},
        {"key": "profile", "ok": False, "detail": "Síť „Doma“ je nastavená jako Veřejná", "fix": "Přepni na Soukromá."}])
    asyncio.run(selfcheck.warn_phone_blocked(rt, delay=0))
    asyncio.run(selfcheck.warn_phone_blocked(rt, delay=0))
    assert len(notes) == 1 and "Veřejná" in notes[0][1] and "Nastavení → Telefon" in notes[0][1]
