"""3.14 tools: memory (decisions with a reason, imports, clean-up, encrypted data folder)."""
from __future__ import annotations

import asyncio
from typing import Annotated

from .base import ToolResult, tool


@tool("remember_decision", "Zapamatuje si rozhodnutí i s DŮVODEM (proč) – aby šlo později dohledat, proč se něco "
      "rozhodlo („rozhodli jsme se pro nabídku B, protože je levnější o 20 %“). Pro obyčejné fakty použij remember.",
      category="paměť", perm="files_write")
async def remember_decision(ctx, decision: Annotated[str, "co se rozhodlo"], reason: Annotated[str, "proč"]) -> ToolResult:
    from .. import memplus

    text = memplus.decision_text(decision, reason)
    know = getattr(ctx, "knowledge", None)
    res = know.add_fact(text, source="rozhodnutí") if know else {"stored": False, "reason": "paměť není"}
    return ToolResult(bool(res.get("stored")), f"Zapamatováno: {text}" if res.get("stored") else f"Neuloženo: {res.get('reason')}")


@tool("import_memory", "Načte do JARVISe historii z exportu ChatGPT nebo Claude (conversations.json / ZIP) nebo poznámky "
      "Google Keep (Takeout). Bez confirm jen ukáže, co by se načetlo; s confirm=true to načte do složky Import "
      "(prohledávatelné, dá se smazat).", danger_if=lambda a: bool(a.get("confirm")), category="paměť", perm="files_write",
      details=lambda a: [f"Soubor: {a.get('path', '')}", "Konverzace/poznámky půjdou do historie (složka Import)."])
async def import_memory(ctx, path: str, confirm: bool = False) -> ToolResult:
    from .. import memplus

    try:
        prev = await asyncio.to_thread(memplus.preview_import, path)
    except (ValueError, OSError) as e:
        return ToolResult(False, f"Nejde přečíst: {e}")
    if not confirm:
        what = (f"{prev['conversations']} konverzací ({prev['messages']} zpráv)" if prev["kind"] == "chat"
                else f"{prev['notes']} poznámek z Google Keep")
        return ToolResult(True, f"Načetlo by se {what}. Ukázka: {', '.join(prev['titles'][:5])}.", data=prev)
    res = await asyncio.to_thread(memplus.run_import, ctx, path)
    return ToolResult(True, f"Načteno {res['imported']} zpráv/poznámek do {res['conversations']} konverzací (složka Import).", data=res)


@tool("memory_cleanup", "Úklid paměti: najde skoro stejné fakty a ty, které už neplatí (prošlý termín). Bez ids jen "
      "navrhne; s ids smaže vybrané fakty.", danger_if=lambda a: bool(a.get("ids")), category="paměť", perm="files_write")
async def memory_cleanup(ctx, ids: list[int] | None = None) -> ToolResult:
    from .. import memplus

    if ids:
        n = await asyncio.to_thread(memplus.apply_cleanup, ctx, ids)
        return ToolResult(True, f"Smazáno {n} faktů.")
    s = await asyncio.to_thread(memplus.cleanup_suggestions, ctx)
    return ToolResult(True, f"{len(s['duplicates'])} dvojic skoro stejných faktů, {len(s['expired'])} prošlých.", data=s)


@tool("encrypt_data", "Zašifruje složku s daty JARVISe (paměť, historie, nahrávky) pomocí EFS ve Windows – číst ji pak jde "
      "jen pod přihlášením uživatele. Na Windows Home EFS není (pak BitLocker).", danger=True, category="systém", perm="system",
      details=lambda a: ["Složka s daty JARVISe se zašifruje (EFS, klíč z tvého přihlášení do Windows).",
                         "Zálohuj si certifikát EFS, jinak data po přeinstalaci Windows neotevřeš."])
async def encrypt_data(ctx) -> ToolResult:
    from .. import memplus, paths

    r = await asyncio.to_thread(memplus.encrypt_data_folder, paths.data_dir())
    return ToolResult(r["ok"], r["message"])
