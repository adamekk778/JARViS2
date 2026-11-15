"""3.12 Zapnout úplně vypnuté PC z telefonu: the Windows half done in one elevated click (the user confirms in UAC)."""
import os
import shutil
import subprocess

import pytest

from jarvis import wol


def test_prepare_script_lets_the_card_wake_and_turns_fast_startup_off():
    s = wol.prepare_script()
    assert "WakeOnMagicPacket Enabled" in s and "deviceenablewake" in s
    assert "HiberbootEnabled" in s and "/d 0" in s
    assert "Remove-" not in s and "Invoke-Expression" not in s          # changes only wake settings


def test_prepare_script_is_valid_powershell():
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        pytest.skip("no PowerShell here")
    check = ("$e = $null; [System.Management.Automation.Language.Parser]::ParseInput($env:JV_SCRIPT, [ref]$null, [ref]$e) | Out-Null; "
             "$e.Count")
    out = subprocess.run([ps, "-NoProfile", "-Command", check], capture_output=True, text=True, timeout=60,
                         env={**os.environ, "JV_SCRIPT": wol.prepare_script()})
    assert out.stdout.strip() == "0", out.stdout + out.stderr


def test_tips_offer_the_one_click_and_the_bios_steps():
    t = " ".join(wol.tips({"mac": "aabbccddeeff", "armed": False, "fast_startup": True, "away": True}))
    assert "Připravit PC" in t and "BIOS" in t and "Wake on LAN" in t
    assert not wol.prepare() or os.name == "nt"                        # never runs anything off Windows
