"""3.12 Kontrola funkcí: every part checked on this PC, in plain words, with what to do."""
import asyncio

from jarvis import selfcheck


def test_runs_everywhere_and_says_what_to_do(rt, monkeypatch):
    monkeypatch.setattr(selfcheck, "internet", lambda: selfcheck._r("internet", "Internet pro JARVIS", True, "ok"))

    async def tester(pid):
        return {"ok": False, "message": "ConnectError: All connection attempts failed (localhost:20128)"}

    items = asyncio.run(selfcheck.run(rt, tester))
    keys = [i["key"] for i in items]
    assert keys[:7] == ["media", "loopback", "mic", "stt", "internet", "tts", "brain"] and "lan" in keys
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
    monkeypatch.setattr(selfcheck, "internet", lambda: selfcheck._r("internet", "Internet pro JARVIS", True, "ok"))
    monkeypatch.setattr(selfcheck, "phone_net", lambda rt_: [
        {"key": "lan", "ok": True, "detail": "ok", "fix": ""},
        {"key": "profile", "ok": False, "detail": "Síť „Doma“ je nastavená jako Veřejná", "fix": "Přepni na Soukromá."}])
    asyncio.run(selfcheck.warn_phone_blocked(rt, delay=0))
    asyncio.run(selfcheck.warn_phone_blocked(rt, delay=0))
    assert len(notes) == 1 and "Veřejná" in notes[0][1] and "Nastavení → Telefon" in notes[0][1]


def _refused(*a, **k):
    e = PermissionError(13, "Došlo k pokusu o přístup k soketu způsobem zakázaným jeho přístupovými oprávněními")
    e.winerror = 10013
    raise e


def test_internet_blocked_by_firewall_is_named(monkeypatch):
    """A real PC (3.10.186): WinError 10013 – the voice and the brain failed, neither said it was the firewall."""
    import socket

    monkeypatch.setattr(socket, "create_connection", _refused)
    monkeypatch.setattr(selfcheck, "security_products", lambda: ["Avast Antivirus"])
    r = selfcheck.internet()
    assert r["ok"] is False and "10013" in r["detail"] and "Avast" in r["fix"] and "Opravit síť" in r["fix"]
    monkeypatch.setattr(selfcheck, "security_products", lambda: [])
    assert "Opravit síť pro JARVIS" in selfcheck.internet()["fix"]


def test_voice_and_brain_point_to_the_internet_item(rt, monkeypatch):
    monkeypatch.setattr(selfcheck, "internet", lambda: selfcheck._r("internet", "Internet pro JARVIS", False, "blokováno", "oprav"))

    async def tester(pid):
        return {"ok": False, "message": "ConnectError"}

    items = {i["key"]: i for i in asyncio.run(selfcheck.run(rt, tester))}
    assert "Internet pro JARVIS" in items["brain"]["fix"]


def test_the_network_fix_only_touches_jarvis():
    sc = selfcheck.fix_network_script(r"C:\Users\Ad'am\AppData\Local\Programs\JARVIS\JARVIS.exe")
    assert "$exe = 'C:\\Users\\Ad''am" in sc                                    # quoted safely
    assert "-Program $exe" in sc and "Remove-NetFirewallRule" in sc and "-Direction Outbound" in sc
    assert "-Profile Private" in sc                                              # the phone: home networks only
    assert "Disable" not in sc and "Set-NetFirewallProfile" not in sc            # never switches the firewall off


def test_internet_warning_once_a_day(rt, monkeypatch):
    notes = []
    rt.notify = lambda title, body, **k: notes.append((title, body))
    monkeypatch.setattr(selfcheck, "WIN", True)
    monkeypatch.setattr(selfcheck, "internet", lambda: selfcheck._r("internet", "Internet pro JARVIS", False, "Windows zakazuje JARVISu internet.", "Klikni na Opravit síť pro JARVIS."))
    monkeypatch.setattr(selfcheck, "phone_net", lambda rt_: [])
    asyncio.run(selfcheck.warn_phone_blocked(rt, delay=0))
    asyncio.run(selfcheck.warn_phone_blocked(rt, delay=0))
    assert len(notes) == 1 and notes[0][0] == "JARVIS nesmí na internet"


def test_the_network_fix_is_valid_powershell():
    """Parsed by PowerShell itself (on Windows / where PowerShell exists) – a typo would only show as nothing happening."""
    import shutil
    import subprocess

    import pytest

    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        pytest.skip("no PowerShell here")
    script = selfcheck.fix_network_script(r"C:\Program Files\JARVIS\JARVIS.exe")
    check = ("$e = $null; [System.Management.Automation.Language.Parser]::ParseInput($env:JV_SCRIPT, [ref]$null, [ref]$e) | Out-Null; "
             "$e.Count")
    import os

    out = subprocess.run([ps, "-NoProfile", "-Command", check], capture_output=True, text=True, timeout=60,
                         env={**os.environ, "JV_SCRIPT": script})
    assert out.stdout.strip() == "0", out.stdout + out.stderr
