"""Self-extension: JARVIS writes new tools (skills) in Python, you approve the code, it loads instantly."""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Annotated

from .. import paths
from .base import REGISTRY, ToolResult, tool, unregister_source

log = logging.getLogger(__name__)
SKILL_TEMPLATE = '''Kód skillu musí vypadat takto:

from jarvis.tools.base import tool, ToolResult

SKILL = {"name": "nazev", "description": "co umí", "version": "1.0",
         "permissions": ["network"],   # z: apps, input, screen, files_read, files_write, shell, network, system
         "timeout": 30}

@tool("nazev_nastroje", "Co nástroj dělá (česky).")
async def nazev_nastroje(ctx, parametr: str, pocet: int = 1) -> ToolResult:
    # ctx.platform (ovládání PC), ctx.http() (httpx klient), ctx.store (soubory), ctx.notify(title, body)
    return ToolResult(True, "shrnutí", data={...})
'''


def skills_dir():
    return paths.sub("skills")


def _module_name(name: str) -> str:
    return f"jarvis_skill_{name}"


def read_manifest(path) -> dict:
    """The SKILL = {...} dict, read with ast (the skill's code is NOT executed)."""
    out = {"name": Path(path).stem, "description": "", "version": "", "permissions": [], "timeout": 30}
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SKILL" for t in node.targets):
                data = ast.literal_eval(node.value)
                if isinstance(data, dict):
                    out.update({k: data[k] for k in out if k in data})
    except (SyntaxError, ValueError, OSError):
        pass
    out["permissions"] = [str(p) for p in out.get("permissions") or [] if isinstance(p, str)]
    try:
        out["timeout"] = max(1, min(300, int(out["timeout"])))
    except (TypeError, ValueError):
        out["timeout"] = 30
    return out


def _runner_cmd(path: Path, tool_name: str, args: dict) -> list[str]:
    payload = json.dumps(args, ensure_ascii=False)
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run-skill", str(path), tool_name, payload]
    return [sys.executable, "-m", "jarvis.skill_runner", str(path), tool_name, payload]


def _wrap(path: Path, tool_name: str, timeout: int):
    async def run_isolated(ctx, **kwargs) -> ToolResult:
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2]) + os.pathsep
               + os.environ.get("PYTHONPATH", ""), "PYTHONIOENCODING": "utf-8"}
        proc = await asyncio.create_subprocess_exec(*_runner_cmd(path, tool_name, kwargs), env=env,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                    creationflags=0x08000000 if os.name == "nt" else 0)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult(False, f"Skill překročil časový limit {timeout} s")
        except asyncio.CancelledError:
            proc.kill()
            raise
        result = None
        for line in out.decode("utf-8", "replace").splitlines():
            if line.startswith("@@NOTIFY "):
                n = json.loads(line[9:])
                ctx.notify(n.get("title", ""), n.get("body", ""))
            elif line.startswith("@@RESULT "):
                result = json.loads(line[9:])
        if proc.returncode != 0 or result is None:
            last = (err.decode("utf-8", "replace").strip().splitlines() or ["neznámá chyba"])[-1]
            return ToolResult(False, f"Skill spadl: {last}")
        return ToolResult(bool(result["ok"]), str(result["summary"]), data=result.get("data"))

    return run_isolated


def load_skill_file(path) -> list[str]:
    path = Path(path)
    name = path.stem
    mod_name = _module_name(name)
    unregister_source(mod_name)
    manifest = read_manifest(path)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)  # registers the tool specs (names, schemas); calls run in a subprocess
    names = sorted(k for k, v in REGISTRY.items() if v.source == mod_name)
    for k in names:
        ts = REGISTRY[k]
        ts.perm = manifest["permissions"][0] if manifest["permissions"] else "apps"
        ts.func = _wrap(path, k, manifest["timeout"])
    return names


def migrate_existing(rt) -> list[str]:
    """2.0 → 2.1: skills that existed before approval was introduced were all written via create_skill → approve once."""
    if rt.db.one("SELECT v FROM kv WHERE k='skills_migrated'"):
        return []
    rt.db.exec("INSERT OR REPLACE INTO kv VALUES ('skills_migrated', '1')")
    names = [f.stem for f in sorted(skills_dir().glob("*.py")) if f.stem not in rt.cfg.tools.approved_skills]
    if names:
        rt.update_config({"tools": {"approved_skills": list(rt.cfg.tools.approved_skills) + names}})
    return names


def load_all_skills(approved: set[str] | list[str] | None = None) -> dict[str, list[str] | str]:
    """Loads approved skills only; others stay listed but switched off until the user approves them."""
    allowed = set(approved or ())
    out: dict = {}
    for f in sorted(skills_dir().glob("*.py")):
        if f.stem not in allowed:
            unregister_source(_module_name(f.stem))
            out[f.stem] = "neschváleno"
            continue
        try:
            out[f.stem] = load_skill_file(f)
        except Exception as e:
            log.warning("skill %s failed: %s", f.name, e)
            out[f.stem] = f"chyba: {e}"
    return out


def list_skills(approved: set[str] | list[str] | None = None) -> list[dict]:
    allowed = set(approved or ())
    items = []
    for f in sorted(skills_dir().glob("*.py")):
        tools = [k for k, v in REGISTRY.items() if v.source == _module_name(f.stem)]
        try:
            code = f.read_text(encoding="utf-8")[:20000]
        except OSError:
            code = ""
        items.append({"name": f.stem, "file": str(f), "tools": tools, "size": f.stat().st_size,
                      "approved": f.stem in allowed, "manifest": read_manifest(f), "code": code})
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
        approved = list(ctx.cfg.tools.approved_skills)
        if name not in approved:
            ctx.update_config({"tools": {"approved_skills": approved + [name]}})
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
    items = list_skills(ctx.cfg.tools.approved_skills)
    return ToolResult(True, f"{len(items)} skillů", data=items)
