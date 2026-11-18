"""3.13 Programy po startu: what starts with Windows, and turning it off (or on again) – the same switch as
Správce úloh → Po spuštění (StartupApproved). Nothing is deleted: the program stays installed and can be switched back.
Programs for all users need an administrator's yes from Windows itself (UAC) – JARVIS never goes around it: it opens
Správce úloh on that tab instead.
"""
from __future__ import annotations

import asyncio
import struct
import sys
import time
from typing import Annotated, Any

from .base import ToolResult, tool

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
UWP = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\SystemAppData"
# never switched off by JARVIS: protection, sound and input drivers, JARVIS itself
KEEP = ("securityhealth", "windows defender", "defender", "avast", "avg", "eset", "kaspersky", "bitdefender", "norton", "mcafee",
        "malwarebytes", "realtek", "rtkaud", "synaptics", "elan", "nahimic", "jarvis", "igfx", "onedrive setup")


def enabled_from(data: bytes | None) -> bool:
    """StartupApproved value: the first byte is even (02, 06) when allowed, odd (03, 07) when switched off; none = on."""
    return True if not data else not (data[0] & 1)


def approved_value(on: bool, now: float | None = None) -> bytes:
    if on:
        return b"\x02" + b"\x00" * 11
    ft = int(((now or time.time()) + 11644473600) * 10_000_000)       # FILETIME: when it was switched off
    return b"\x03\x00\x00\x00" + struct.pack("<Q", ft)


def protected(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in KEEP)


def _items() -> list[dict]:
    import os
    import winreg
    from pathlib import Path

    out: list[dict] = []

    def approved(hive, sub: str, name: str) -> bytes | None:
        try:
            with winreg.OpenKey(hive, f"{APPROVED}\\{sub}") as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None
    for hive, key, sub, scope in ((winreg.HKEY_CURRENT_USER, RUN, "Run", "jen tobě"), (winreg.HKEY_LOCAL_MACHINE, RUN, "Run", "všem"),
                                  (winreg.HKEY_LOCAL_MACHINE, RUN32, "Run32", "všem")):
        try:
            with winreg.OpenKey(hive, key) as k:
                for i in range(winreg.QueryInfoKey(k)[1]):
                    name, cmd, _ = winreg.EnumValue(k, i)
                    out.append({"name": name, "command": str(cmd)[:300], "where": "registr", "scope": scope,
                                "enabled": enabled_from(approved(hive, sub, name)), "_ref": ("reg", hive, sub, name)})
        except OSError:
            pass
    for folder, hive, scope in ((Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup", winreg.HKEY_CURRENT_USER, "jen tobě"),
                                (Path(os.environ.get("ProgramData", "")) / r"Microsoft\Windows\Start Menu\Programs\StartUp", winreg.HKEY_LOCAL_MACHINE, "všem")):
        if folder.is_dir():
            for f in folder.iterdir():
                if f.suffix.lower() in (".lnk", ".exe", ".bat", ".cmd", ".url"):
                    out.append({"name": f.stem, "command": str(f), "where": "složka Po spuštění", "scope": scope,
                                "enabled": enabled_from(approved(hive, "StartupFolder", f.name)), "_ref": ("reg", hive, "StartupFolder", f.name)})
    try:                                          # Store apps (Spotify, Teams, Discord from the Store…): their own switch
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UWP) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                pkg = winreg.EnumKey(root, i)
                try:
                    with winreg.OpenKey(root, pkg) as pk:
                        for j in range(winreg.QueryInfoKey(pk)[0]):
                            task = winreg.EnumKey(pk, j)
                            try:
                                with winreg.OpenKey(pk, task) as tk:
                                    state = winreg.QueryValueEx(tk, "State")[0]
                            except OSError:
                                continue
                            out.append({"name": pkg.split("_")[0].split(".")[-1], "command": pkg, "where": "aplikace z Microsoft Store",
                                        "scope": "jen tobě", "enabled": int(state) == 2, "_ref": ("uwp", f"{UWP}\\{pkg}\\{task}")})
                except OSError:
                    continue
    except OSError:
        pass
    return out


def _set(ref: tuple, on: bool) -> None:
    import winreg

    if ref[0] == "uwp":
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ref[1], 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "State", 0, winreg.REG_DWORD, 2 if on else 1)
        return
    _, hive, sub, name = ref
    with winreg.CreateKeyEx(hive, f"{APPROVED}\\{sub}", 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, approved_value(on))


def public(items: list[dict]) -> list[dict]:
    return [{k: v for k, v in i.items() if not k.startswith("_")} | {"keep": protected(i["name"])} for i in items]


@tool("startup_apps", "Programy, které se spouštějí se startem Windows – co je zapnuté a co vypnuté (jako Správce úloh → Po spuštění).",
      category="systém")
async def startup_apps(ctx) -> ToolResult:
    if sys.platform != "win32":
        return ToolResult(False, "Programy po startu umím jen ve Windows.")
    items = public(await asyncio.to_thread(_items))
    on = [i for i in items if i["enabled"]]
    return ToolResult(True, f"Se startem se spouští {len(on)} programů ({len(items) - len(on)} je vypnutých). "
                            "Ochranu, zvuk a ovladače (keep: true) nevypínej.", data=items)


def _details(a: dict, ctx: Any = None) -> list[str]:
    names = a.get("names") or []
    return [("Vypnu" if not a.get("enabled") else "Zapnu") + " po startu Windows: " + ", ".join(str(n) for n in names[:12]),
            "Programy zůstanou nainstalované – jde to kdykoli vrátit."]


@tool("startup_app_set", "Vypne (nebo zapne) programy, které se spouštějí se startem Windows – podle názvů ze startup_apps. "
      "Program se nesmaže, jen se nespustí sám.", danger=True, details=_details, category="systém")
async def startup_app_set(ctx, names: Annotated[list[str], "názvy programů ze startup_apps"],
                          enabled: Annotated[bool, "false = vypnout po startu, true = zase zapnout"] = False) -> ToolResult:
    if sys.platform != "win32":
        return ToolResult(False, "Programy po startu umím jen ve Windows.")
    items = await asyncio.to_thread(_items)
    done, kept, admin, missing = [], [], [], []
    for want in names or []:
        hit = [i for i in items if i["name"].lower() == str(want).lower()] or [i for i in items if str(want).lower() in i["name"].lower()]
        if not hit:
            missing.append(str(want))
            continue
        for i in hit:
            if not enabled and protected(i["name"]):
                kept.append(i["name"])
                continue
            try:
                await asyncio.to_thread(_set, i["_ref"], bool(enabled))
                done.append(i["name"])
            except PermissionError:
                admin.append(i["name"])
            except OSError as e:
                if getattr(e, "winerror", 0) == 5:
                    admin.append(i["name"])
                else:
                    missing.append(f"{i['name']} ({e})")
    msg = []
    if done:
        msg.append(("Vypnuto" if not enabled else "Zapnuto") + " po startu: " + ", ".join(dict.fromkeys(done)) + ".")
    if kept:
        msg.append("Nechal jsem zapnuté (ochrana, zvuk, ovladače): " + ", ".join(dict.fromkeys(kept)) + ".")
    if admin:
        msg.append("Tyhle jsou pro všechny uživatele a Windows k nim chce potvrzení správce: " + ", ".join(dict.fromkeys(admin))
                   + " – otevřel jsem Správce úloh → Po spuštění, vypni je tam jedním klikem.")
        try:
            import subprocess

            subprocess.Popen(["taskmgr.exe", "/7", "/startup"])
        except OSError:
            pass
    if missing:
        msg.append("Nenašel jsem: " + ", ".join(missing) + ".")
    return ToolResult(bool(done) or not (admin or missing), " ".join(msg) or "Nic se nezměnilo.", data={"changed": done})
