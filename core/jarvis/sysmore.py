"""Diagnostics and helpers that complete partial features: partitions (289), disks Windows does not see and USB bridges
(698 / 693 / 694), game sessions (313), a Monte-Carlo decision simulator (005) and one health check of every connection
(586 / 587). Read-only."""
from __future__ import annotations

import base64
import datetime as dt
import json
import random
import re
import statistics
import sys

from .pcreport import run_quiet

DISK_PS = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$o = @{}
try { $o.partitions = @(Get-Partition -ErrorAction Stop | ForEach-Object { $v = $_ | Get-Volume -ErrorAction SilentlyContinue; [pscustomobject]@{
  Disk = $_.DiskNumber; Number = $_.PartitionNumber; Letter = "$($_.DriveLetter)"; Type = "$($_.Type)"; GB = [math]::Round($_.Size / 1GB, 2);
  FS = "$($v.FileSystem)"; Label = "$($v.FileSystemLabel)"; FreeGB = if ($v) { [math]::Round($v.SizeRemaining / 1GB, 2) } else { $null };
  Health = "$($v.HealthStatus)"; Boot = $_.IsBoot; System = $_.IsSystem } }) } catch { $o.partitions_error = $_.Exception.Message }
try { $o.disks = @(Get-Disk -ErrorAction Stop | Select-Object Number, FriendlyName, @{n='Bus'; e={ "$($_.BusType)" }}, @{n='Style'; e={ "$($_.PartitionStyle)" }},
  @{n='Status'; e={ "$($_.OperationalStatus)" }}, IsOffline, @{n='GB'; e={ [math]::Round($_.Size / 1GB, 1) }}) } catch {}
try { $o.pnp = @(Get-PnpDevice -Class DiskDrive -ErrorAction Stop | Select-Object FriendlyName, Status, InstanceId, @{n='Present'; e={ $_.Present }}) } catch {}
try { $o.usb = @(Get-PnpDevice -PresentOnly -ErrorAction Stop | Where-Object { $_.InstanceId -like 'USB\VID_*' } | Select-Object FriendlyName, InstanceId, Status) } catch {}
$o | ConvertTo-Json -Depth 5 -Compress
"""

# USB–SATA / NVMe bridge chips by USB vendor id (what a disk enclosure really is inside)
BRIDGES = {"152D": "JMicron", "174C": "ASMedia", "0BDA": "Realtek", "2109": "VIA Labs", "7825": "Other World Computing",
           "1058": "Western Digital", "0BC2": "Seagate", "059F": "LaCie", "13FD": "Initio", "067B": "Prolific", "04E8": "Samsung",
           "0781": "SanDisk", "125F": "ADATA", "1F75": "Innostor", "357D": "Sunplus", "05E3": "Genesys Logic"}
BRIDGE_TIPS = {"JMicron": "JMS578/583: u některých se vyplatí aktualizovat firmware rámečku; SMART přes něj často jde.",
               "ASMedia": "ASM1153/2362: spolehlivé; při odpojování zkontroluj napájení (2,5\" disky chtějí silný port).",
               "Realtek": "RTL9210 (NVMe): hřeje se – při odpojování pod zátěží pomůže chladič nebo kratší přenosy.",
               "Genesys Logic": "Levnější převodník – při chybách zkus jiný rámeček.",
               "Initio": "Starší převodník – disky nad 2 TB může hlásit špatně."}


def _list(v) -> list:
    return v if isinstance(v, list) else [v] if isinstance(v, dict) else []


def disk_probe() -> dict:
    if sys.platform != "win32":
        return {}
    enc = base64.b64encode(DISK_PS.encode("utf-16-le")).decode()
    _code, out, _err = run_quiet(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], 60)
    try:
        return json.loads(out[out.find("{"):]) if "{" in out else {}
    except ValueError:
        return {}


def partitions_summary(d: dict) -> list[dict]:
    out = []
    for p in _list(d.get("partitions")):
        gb, free = p.get("GB") or 0, p.get("FreeGB")
        role = "systémový" if p.get("Boot") or p.get("System") else "obnovovací" if "recovery" in str(p.get("Type")).lower() else \
            "EFI" if "system" in str(p.get("Type")).lower() and gb < 1.1 else "data"
        out.append({"disk": p.get("Disk"), "letter": p.get("Letter") or "", "label": p.get("Label") or "", "fs": p.get("FS") or "bez souborového systému",
                    "gb": gb, "free_gb": free, "used_pct": round(100 * (1 - (free or 0) / gb)) if gb and free is not None else None,
                    "role": role, "health": p.get("Health") or ""})
    return out


def bridge_of(instance_id: str) -> str:
    m = re.search(r"VID_([0-9A-F]{4})", instance_id or "", re.I)
    return BRIDGES.get(m.group(1).upper(), "") if m else ""


def invisible_disks(d: dict) -> list[dict]:
    """Disks the device manager knows (or knows with a problem) but Windows' disk list does not show, offline / RAW ones,
    and what bridge chip a USB disk sits behind."""
    findings = []
    disks = _list(d.get("disks"))
    names = {str(x.get("FriendlyName") or "").lower() for x in disks}
    for p in _list(d.get("pnp")):
        nm = str(p.get("FriendlyName") or "")
        if str(p.get("Status")) not in ("OK", "") and p.get("Present", True):
            findings.append({"level": "bad", "text": f"{nm}: Windows ho zná, ale hlásí stav {p.get('Status')} – disk se nepřipojil.",
                             "fix": "Jiný kabel / port, napájený rozbočovač; ve Správci zařízení → Odinstalovat zařízení a znovu připojit. NIC neformátuj."})
        elif nm and nm.lower() not in names and p.get("Present", True):
            findings.append({"level": "warn", "text": f"{nm} je ve Správci zařízení, ale ne v seznamu disků.",
                             "fix": "Otevři Správu disků – pokud tam je „Nepřipojený“ nebo „Neinicializovaný“, NIC neinicializuj a nejdřív zachraň data."})
    for x in disks:
        if x.get("IsOffline"):
            findings.append({"level": "bad", "text": f"{x.get('FriendlyName')} je offline.", "fix": "Správa disků → pravým na disk → Online (data to nemění)."})
        elif str(x.get("Style")).upper() == "RAW":
            findings.append({"level": "bad", "text": f"{x.get('FriendlyName')} nemá rozpoznané oddíly (RAW).",
                             "fix": "Neformátuj ho, i když to Windows nabízí – data mohou jít zachránit (TestDisk / firma)."})
    for u in _list(d.get("usb")):
        b = bridge_of(str(u.get("InstanceId")))
        if b and re.search(r"mass storage|disk|sata|nvme|uas|storage", str(u.get("FriendlyName")), re.I):
            findings.append({"level": "info", "text": f"USB úložiště přes převodník {b} ({u.get('FriendlyName')}).", "fix": BRIDGE_TIPS.get(b, "")})
    return findings


# ---------------------------------------------------------------- 313 gaming
GAME_HINTS = re.compile(r"steam|epic|riot|valorant|league|minecraft|roblox|fortnite|battle\.net|overwatch|cs2|counter|dota|gta|"
                        r"cyberpunk|witcher|origin|ea app|ubisoft|genshin|rocket league|apex|pubg|elden|baldur|hogwarts|xbox|game", re.I)


def gaming_sessions(rows: list[dict], days: int = 7, today: dt.date | None = None) -> dict:
    """From hourly app usage: play time per day, the longest stretch, late-night play (22–6) and the most played games."""
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=days - 1)).isoformat()
    games = [r for r in rows if r["day"] >= since and GAME_HINTS.search(r["app"] or "")]
    per_day: dict[str, float] = {}
    per_app: dict[str, float] = {}
    late = 0.0
    hours_by_day: dict[str, list[int]] = {}
    for r in games:
        per_day[r["day"]] = per_day.get(r["day"], 0) + r["seconds"] / 3600
        per_app[r["app"]] = per_app.get(r["app"], 0) + r["seconds"] / 3600
        if r["hour"] >= 22 or r["hour"] < 6:
            late += r["seconds"] / 3600
        if r["seconds"] >= 600:
            hours_by_day.setdefault(r["day"], []).append(r["hour"])
    longest = 0
    for hs in hours_by_day.values():
        hs = sorted(set(hs))
        run = best = 1
        for a, b in zip(hs, hs[1:]):
            run = run + 1 if b == a + 1 else 1
            best = max(best, run)
        longest = max(longest, best)
    total = sum(per_day.values())
    return {"days": days, "total_h": round(total, 1), "avg_h": round(total / days, 1), "per_day": {k: round(v, 1) for k, v in sorted(per_day.items())},
            "top": [{"app": k, "hours": round(v, 1)} for k, v in sorted(per_app.items(), key=lambda kv: -kv[1])[:5]],
            "late_h": round(late, 1), "longest_h": longest if total else 0}


# ---------------------------------------------------------------- 005 decision simulator
def simulate_decision(options: dict[str, dict], runs: int = 20000, seed: int = 1) -> dict:
    """Each option: gain [min, likely, max] (triangular), cost [min, likely, max], success probability. Monte Carlo →
    expected result, chance of a loss, a bad case (5th percentile) and a good case (95th)."""
    rng = random.Random(seed)
    out = {}
    for name, o in options.items():
        g, c = o.get("gain") or [0, 0, 0], o.get("cost") or [0, 0, 0]
        p = float(o.get("p_success", 1.0))
        vals = []
        for _ in range(runs):
            gain = rng.triangular(g[0], g[2], g[1]) if rng.random() < p else 0.0
            vals.append(gain - rng.triangular(c[0], c[2], c[1]))
        vals.sort()
        out[name] = {"expected": round(statistics.fmean(vals), 2), "p_loss": round(sum(v < 0 for v in vals) / runs * 100, 1),
                     "bad_case": round(vals[int(runs * 0.05)], 2), "good_case": round(vals[int(runs * 0.95)], 2)}
    best = max(out, key=lambda k: out[k]["expected"])
    safest = min(out, key=lambda k: out[k]["p_loss"])
    return {"options": out, "best_expected": best, "safest": safest, "runs": runs}
