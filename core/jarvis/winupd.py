"""OMEGA 013: which Windows updates are waiting (not installed, not hidden) and whether a restart is pending. Read-only:
the Windows Update Agent search API, nothing is downloaded or installed (that stays with Windows Update itself)."""
from __future__ import annotations

import base64
import json
import sys

from .pcreport import run_quiet

PS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$o = @{ updates = @(); reboot = $false }
try {
  $s = New-Object -ComObject Microsoft.Update.Session
  $r = $s.CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0")
  foreach ($u in $r.Updates) {
    $kb = ($u.KBArticleIDs | ForEach-Object { "KB$_" }) -join ","
    $cat = ($u.Categories | Select-Object -First 1).Name
    $o.updates += @{ title = $u.Title; kb = $kb; category = $cat; severity = $u.MsrcSeverity; mb = [math]::Round($u.MaxDownloadSize / 1MB);
                     downloaded = $u.IsDownloaded; mandatory = $u.IsMandatory; released = $u.LastDeploymentChangeTime.ToString("yyyy-MM-dd") }
  }
} catch { $o.error = $_.Exception.Message }
try { $o.reboot = (New-Object -ComObject Microsoft.Update.SystemInfo).RebootRequired } catch {}
$o | ConvertTo-Json -Depth 4 -Compress
"""


def parse(out: str) -> dict:
    try:
        d = json.loads(out[out.find("{"):]) if "{" in out else {}
    except ValueError:
        return {"error": "nečitelný výstup", "updates": []}
    ups = d.get("updates") or []
    if isinstance(ups, dict):                       # PowerShell collapses a single-item array
        ups = [ups]
    order = {"Critical": 0, "Important": 1, "Moderate": 2, "Low": 3}
    ups.sort(key=lambda u: (order.get(u.get("severity") or "", 4), u.get("title") or ""))
    return {"updates": ups, "reboot": bool(d.get("reboot")), "error": d.get("error"),
            "security": sum(1 for u in ups if (u.get("category") or "").lower().startswith(("security", "zabezpeč")) or u.get("severity")),
            "mb": sum(u.get("mb") or 0 for u in ups)}


def pending() -> dict:
    if sys.platform != "win32":
        return {"error": "jen na Windows", "updates": []}
    enc = base64.b64encode(PS.encode("utf-16-le")).decode()
    _code, out, err = run_quiet(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], 180)
    r = parse(out)
    if not out.strip() and err:
        r["error"] = err[:200]
    return r


def summary(r: dict) -> str:
    if r.get("error") and not r.get("updates"):
        return f"Čekající aktualizace nejdou zjistit: {r['error']}"
    ups = r["updates"]
    if not ups:
        return "Windows je aktuální – nic nečeká." + (" Jen čeká restart, aby se dokončila instalace." if r.get("reboot") else "")
    n = len(ups)
    txt = f"Čeká {n} {'aktualizace' if n < 5 else 'aktualizací'} ({r['mb']} MB)"
    if r.get("security"):
        txt += f", z toho {r['security']} bezpečnostní"
    txt += ": " + "; ".join(u["title"][:80] for u in ups[:4]) + ("…" if n > 4 else "") + "."
    if r.get("reboot"):
        txt += " A čeká se na restart."
    return txt + " Nainstaluješ je v Nastavení → Windows Update."
