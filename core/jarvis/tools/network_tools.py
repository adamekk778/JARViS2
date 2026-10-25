"""3.5 home network by voice: "kdo je na mé Wi-Fi", "pojmenuj zařízení…", "zapni počítač v pracovně" (Wake-on-LAN)."""
from __future__ import annotations

from typing import Annotated

from .base import ToolResult, tool


@tool("network_devices", "Zařízení v domácí síti (Wi-Fi): IP, MAC, název; označí nová, která tu dřív nebyla. "
      "Na „kdo je připojený na Wi-Fi“, „je na síti něco cizího?“.", category="systém", perm="network")
async def network_devices(ctx) -> ToolResult:
    from .. import network

    items = await network.devices(ctx)
    if not items:
        return ToolResult(False, "Žádná zařízení jsem neviděl (PC není v síti, nebo síť nic neohlásila).")
    network.remember(ctx, network.known(ctx) | {d["mac"] for d in items})
    lines = [f"{d['name'] or 'bez názvu'} – {d['ip']} ({d['mac']}){' – NOVÉ' if d['new'] else ''}" for d in items]
    new = sum(d["new"] for d in items)
    head = f"V síti vidím {len(items)} zařízení" + (f", z toho {new} nových" if new else "") + "."
    return ToolResult(True, head + "\n" + "\n".join(lines), data=items)


@tool("name_device", "Pojmenuje zařízení v síti podle MAC nebo IP („to je Petrův mobil“), aby ho JARVIS příště poznal.",
      category="systém", perm="network")
async def name_device(ctx, device: Annotated[str, "MAC nebo IP adresa"], name: str) -> ToolResult:
    from .. import network

    mac = device.strip()
    if not network.MAC_RE.fullmatch(mac):
        hit = next((d for d in await network.devices(ctx) if d["ip"] == mac), None)
        if hit is None:
            return ToolResult(False, f"Zařízení {device} teď v síti nevidím.")
        mac = hit["mac"]
    network.set_name(ctx, mac, name.strip())
    return ToolResult(True, f"Zapamatováno: {network.norm_mac(mac)} je „{name.strip()}“.")


@tool("wake_device", "Zapne jiný počítač v síti na dálku (Wake-on-LAN) podle jména nebo MAC adresy. "
      "Počítač musí mít Wake-on-LAN zapnutý v BIOSu.", category="systém", perm="network")
async def wake_device(ctx, device: Annotated[str, "jméno (např. „počítač v pracovně“) nebo MAC"]) -> ToolResult:
    from .. import network

    hit = network.find([], ctx, device) or network.find(await network.devices(ctx), ctx, device)
    if hit is None:
        return ToolResult(False, f"„{device}“ neznám. Řekni mi jeho MAC adresu, nebo ho nejdřív pojmenuj (name_device).")
    network.wake(hit["mac"])
    return ToolResult(True, f"Posílám budicí signál pro {hit.get('name') or hit['mac']}. Za chvíli by měl naběhnout.")
