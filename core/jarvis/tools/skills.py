"""Self-extension: JARVIS writes new tools (skills) in Python, you approve the code, it loads instantly."""
from __future__ import annotations

import importlib.util
import logging
import re
import sys
from typing import Annotated

from .. import paths
from .base import REGISTRY, ToolResult, tool, unregister_source

log = logging.getLogger(__name__)
SKILL_TEMPLATE = '''Kód skillu musí vypadat takto:

from jarvis.tools.base import tool, ToolResult

@tool("nazev_nastroje", "Co nástroj dělá (česky).")
async def nazev_nastroje(ctx, parametr: str, pocet: int = 1) -> ToolResult:
    # ctx.platform (ovládání PC), ctx.http() (httpx klient), ctx.store (soubory), ctx.notify(title, body)
    return ToolResult(True, "shrnutí", data={...})
'''


def skills_dir():
    return paths.sub("skills")


def _module_name(name: str) -> str:
    return f"jarvis_skill_{name}"


def load_skill_file(path) -> list[str]:
    name = path.stem
    mod_name = _module_name(name)
    unregister_source(mod_name)
    before = set(REGISTRY)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return sorted(set(REGISTRY) - before | {k for k, v in REGISTRY.items() if v.source == mod_name})


def load_all_skills() -> dict[str, list[str] | str]:
    out: dict = {}
    for f in sorted(skills_dir().glob("*.py")):
        try:
            out[f.stem] = load_skill_file(f)
        except Exception as e:
            log.warning("skill %s failed: %s", f.name, e)
            out[f.stem] = f"chyba: {e}"
    return out


def list_skills() -> list[dict]:
    items = []
    for f in sorted(skills_dir().glob("*.py")):
        tools = [k for k, v in REGISTRY.items() if v.source == _module_name(f.stem)]
        items.append({"name": f.stem, "file": str(f), "tools": tools, "size": f.stat().st_size})
    return items


@tool("create_skill", "Naučí JARVISe novou dovednost: napíše nový nástroj v Pythonu, který se hned načte a příště ho "
      "můžeš použít. Použij, když na úkol nemáš nástroj a bude se hodit opakovaně. " + SKILL_TEMPLATE,
      danger=True, category="dovednosti")
async def create_skill(ctx, name: Annotated[str, "název souboru, jen a-z, 0-9, _"], code: Annotated[str, "Python kód skillu"]) -> ToolResult:
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", name):
        return ToolResult(False, "Neplatný název (malá písmena, čísla, podtržítko)")
    if "@tool(" not in code:
        return ToolResult(False, "Kód musí obsahovat aspoň jeden @tool(...)\n" + SKILL_TEMPLATE)
    path = skills_dir() / f"{name}.py"
    backup = path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(code, encoding="utf-8")
    try:
        new_tools = load_skill_file(path)
    except Exception as e:
        if backup is None:
            path.unlink()
        else:
            path.write_text(backup, encoding="utf-8")
        return ToolResult(False, f"Skill se nepodařilo načíst: {type(e).__name__}: {e}")
    return ToolResult(True, f"Naučil jsem se: {', '.join(new_tools) or name}", data={"tools": new_tools, "file": str(path)})


@tool("delete_skill", "Smaže naučenou dovednost (skill).", danger=True, category="dovednosti")
async def delete_skill(ctx, name: str) -> ToolResult:
    path = skills_dir() / f"{name}.py"
    if not path.exists():
        return ToolResult(False, "Takový skill neexistuje")
    unregister_source(_module_name(name))
    path.unlink()
    return ToolResult(True, f"Skill {name} smazán")


@tool("list_skills", "Vypíše naučené dovednosti.", category="dovednosti")
async def list_skills_tool(ctx) -> ToolResult:
    items = list_skills()
    return ToolResult(True, f"{len(items)} skillů", data=items)
