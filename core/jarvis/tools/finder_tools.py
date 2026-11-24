"""find_tools: the AI gets a small set of tools with each message and asks for more here (see tools/select.py)."""
from __future__ import annotations

from typing import Annotated

from .base import REGISTRY, ToolResult, tool
from .select import FIND, search

USE_TOOL = "use_tool"


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


def _inner_danger(a: dict, ctx=None) -> bool:
    """use_tool is as risky as the tool it calls (unknown = ask)."""
    from .base import is_dangerous

    inner = REGISTRY.get(str((a or {}).get("name") or ""))
    if inner is None:
        return True
    args = (a or {}).get("args") or {}
    t = getattr(getattr(ctx, "cfg", None), "tools", None)
    return is_dangerous(inner, args if isinstance(args, dict) else {}, getattr(t, "always_confirm", ()) or (),
                        getattr(t, "trusted", ()) or (), ctx=ctx)


@tool(USE_TOOL, "Zavolá KTERÝKOLI nástroj z katalogu „Všechny tvoje nástroje“ jedním krokem: name = jméno nástroje, args = jeho "
      "parametry jako objekt. Použij, když potřebný nástroj nemáš mezi nabídnutými – nic nehledej, vyber ze seznamu.",
      category="obecné", danger_if=_inner_danger)
async def use_tool(ctx, name: Annotated[str, "jméno nástroje z katalogu, např. printer_control"],
                   args: Annotated[dict, "parametry nástroje jako objekt, např. {\"action\": \"pause\"}"] = None) -> ToolResult:  # type: ignore[assignment]
    # JARVIS's agent runs the inner tool itself (with its own confirmation and card); this path is for anything else
    from ..permissions import allowed as perm_ok
    from ..toolcatalog import unwrap
    from .base import call

    cfg = getattr(ctx, "cfg", None)
    names = {n for n, s in REGISTRY.items() if cfg is None or perm_ok(cfg, s)}
    u = unwrap(REGISTRY, names, {"name": name, "args": args or {}})
    if u.error:
        return ToolResult(False, u.error)
    return await call(u.name, u.args, ctx)
