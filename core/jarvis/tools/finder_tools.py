"""find_tools: the AI gets a small set of tools with each message and asks for more here (see tools/select.py)."""
from __future__ import annotations

from typing import Annotated

from .base import REGISTRY, ToolResult, tool
from .select import FIND, search


@tool(FIND, "Najdi další nástroje JARVISe, když žádný z nabídnutých nestačí (JARVIS jich má stovky: soubory, e-mail, "
      "telefon, kalendář, hry, kód, design, PC diagnostika…). Popiš pár slovy, co potřebuješ udělat; nalezené "
      "nástroje můžeš hned v dalším kroku použít.", category="obecné")
async def find_tools(ctx, query: Annotated[str, "co potřebuješ udělat, pár slov (např. 'smazat duplicitní fotky')"]) -> ToolResult:
    from ..permissions import allowed

    cfg = getattr(ctx, "cfg", None)
    off = set(getattr(getattr(cfg, "tools", None), "disabled", []) or [])
    names = [n for n in search(REGISTRY, query, 24) if n not in off and (cfg is None or allowed(cfg, REGISTRY[n]))][:8]
    if not names:
        return ToolResult(False, "Nic takového jsem nenašel – zkus to popsat jinými slovy.", data={"tools": []})
    lines = [f"- {n}: {REGISTRY[n].description[:140]}" for n in names]
    return ToolResult(True, "Teď můžeš použít:\n" + "\n".join(lines), data={"tools": names})
