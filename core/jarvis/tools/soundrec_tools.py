"""3.13 Nahrávání zvuku z PC: start right away, stop by word – soundrec.py records."""
from __future__ import annotations

import asyncio
from typing import Annotated

from .base import ToolResult, tool


@tool("sound_record_start", "Nahraj zvuk, který hraje z počítače (písnička, video, cokoli pustíš) do souboru – začne hned, "
      "skončí na „stop nahrávání“. Nahrává jen zvuk z PC, ne mikrofon.", category="média")
async def sound_record_start(ctx, name: Annotated[str, "jak soubor pojmenovat (nepovinné)"] = "") -> ToolResult:
    from .. import soundrec

    rec = soundrec.of(ctx)
    if rec.on:
        return ToolResult(True, f"Už nahrávám ({rec.seconds()} s). Až budeš chtít skončit, řekni „stop nahrávání“.")
    path = await asyncio.to_thread(rec.start, name)
    await asyncio.sleep(0.4)
    if rec.error:
        return ToolResult(False, f"Nahrávání nejde spustit: {rec.error}")
    try:
        ctx.notify("Nahrávám zvuk z PC", "Řekni „stop nahrávání“, až budeš chtít skončit.", speak=False)
    except Exception:  # noqa: BLE001
        pass
    return ToolResult(True, "Nahrávám – pusť to. Až budeš chtít skončit, řekni „stop nahrávání“.", data={"path": str(path)})


@tool("sound_record_stop", "Ukončí nahrávání zvuku z PC a uloží soubor.", category="média")
async def sound_record_stop(ctx) -> ToolResult:
    from .. import soundrec

    rec = soundrec.of(ctx)
    if not rec.on:
        return ToolResult(True, "Teď nic nenahrávám.")
    st = await asyncio.to_thread(rec.stop)
    m, s = divmod(st["seconds"], 60)
    return ToolResult(True, f"Hotovo – nahráno {m} min {s} s. Uloženo do složky Nahrávky.", data=st)
