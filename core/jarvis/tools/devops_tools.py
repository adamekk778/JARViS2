"""Developer chores by voice: CHANGELOG.md (050), check the build after changes (058), a release package (060), a CI
workflow (626), architecture decision records (618) and trying code in a throw-away copy (345)."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Annotated

from .base import ToolResult, tool
from .dev import _run_cmd, _tail, resolve_project


def _root(ctx, project: str):
    return resolve_project(ctx, project)


@tool("update_changelog", "Doplní na začátek CHANGELOG.md v projektu záznam pro novou verzi z commitů od poslední značky "
      "(novinky, opravy, zásadní změny). Bez write jen ukáže text.", category="programování", perm="files_write",
      danger_if=lambda a, ctx=None: bool(a.get("write")),
      details=lambda a, ctx=None: [f"Zapíše do {a.get('project')}/CHANGELOG.md záznam verze {a.get('version')}."])
async def update_changelog(ctx, project: str, version: str, write: bool = False, since: str = "") -> ToolResult:
    from .. import devlab, devops

    root = _root(ctx, project)
    if isinstance(root, ToolResult):
        return root
    try:
        notes = await asyncio.to_thread(devlab.release_notes, root, since, "HEAD", version)
    except Exception as e:  # noqa: BLE001 – not a git repo / no commits
        return ToolResult(False, f"Commity nejdou přečíst: {e}")
    entry = devops.changelog_entry(version, notes["markdown"])
    if not write:
        return ToolResult(True, entry, data={"entry": entry})
    f = root / "CHANGELOG.md"
    old = f.read_text(encoding="utf-8") if f.exists() else ""
    f.write_text(devops.prepend_changelog(old, entry), encoding="utf-8")
    return ToolResult(True, f"CHANGELOG.md doplněn o verzi {version} ({len(notes['commits'])} commitů).", data={"path": str(f)})


def _report_build(results: list[dict]) -> str:
    bad = [r for r in results if r["code"] != 0]
    if not results:
        return "Nevím, jak tenhle projekt sestavit."
    if bad:
        return f"Neprošlo: {bad[0]['cmd']} (kód {bad[0]['code']}).\n" + _tail(bad[0]["out"])
    return "Všechno prošlo: " + ", ".join(r["cmd"] for r in results) + "."


@tool("verify_build", "Ověří projekt po změnách: sestaví ho a spustí kontroly a testy (npm run build/test, pytest, dotnet "
      "build/test, cargo…) a řekne, co neprošlo. Na „funguje to ještě?“, „zkontroluj build“.", danger=True,
      category="programování", perm="shell", details=lambda a, ctx=None: [f"Spustí sestavení a testy v {a.get('project')} (spouští kód projektu)."])
async def verify_build(ctx, project: str) -> ToolResult:
    from .. import devops

    root = _root(ctx, project)
    if isinstance(root, ToolResult):
        return root
    results = []
    for c in devops.build_commands(root):
        code, out = await asyncio.to_thread(_run_cmd, c, root, 900)
        results.append({"cmd": c, "code": code, "out": out})
        if code != 0:
            break
    ok = bool(results) and all(r["code"] == 0 for r in results)
    return ToolResult(ok, _report_build(results), data={"steps": [{"cmd": r["cmd"], "code": r["code"]} for r in results]})


@tool("package_release", "Připraví balíček k vydání: dist/<projekt>-<verze>.zip se soubory projektu (bez .git, node_modules, "
      ".env…), poznámkami k vydání a otiskem SHA-256. Nic nepublikuje.", category="programování", perm="files_write",
      danger=True, details=lambda a, ctx=None: [f"Vytvoří {a.get('project')}/dist/…-{a.get('version')}.zip a SHA256SUMS."])
async def package_release(ctx, project: str, version: str) -> ToolResult:
    from .. import devlab, devops

    root = _root(ctx, project)
    if isinstance(root, ToolResult):
        return root
    extra = {}
    try:
        extra["RELEASE.md"] = (await asyncio.to_thread(devlab.release_notes, root, "", "HEAD", version))["markdown"]
    except Exception:  # noqa: BLE001 – no git: package without notes
        pass
    try:
        r = await asyncio.to_thread(devops.package, root, version, None, extra)
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"Balíček {Path(r['zip']).name}: {r['files']} souborů, {r['bytes'] / 2**20:.1f} MB, SHA-256 {r['sha256'][:16]}….",
                      data=r)


@tool("ci_setup", "Navrhne CI pro projekt (GitHub Actions): instalace, sestavení a testy na Windows i Linuxu při každém "
      "pushi a pull requestu – se stejnou verzí Node / Pythonu jako na PC. Bez write jen ukáže, s write zapíše "
      ".github/workflows/ci.yml (existující nepřepíše).", category="programování", perm="files_write",
      danger_if=lambda a, ctx=None: bool(a.get("write")), details=lambda a, ctx=None: ["Zapíše .github/workflows/ci.yml do projektu."])
async def ci_setup(ctx, project: str, write: bool = False) -> ToolResult:
    from .. import devlab, devops

    root = _root(ctx, project)
    if isinstance(root, ToolResult):
        return root
    try:
        wf = devops.ci_workflow(root, await asyncio.to_thread(devlab.env_snapshot))
    except ValueError as e:
        return ToolResult(False, str(e))
    if not write:
        return ToolResult(True, wf, data={"workflow": wf})
    f = root / ".github" / "workflows" / "ci.yml"
    if f.exists():
        return ToolResult(False, f"{f} už existuje – nepřepisuji ho. Návrh:\n{wf}", data={"workflow": wf})
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(wf, encoding="utf-8")
    return ToolResult(True, f"CI zapsáno: {f}. Po pushi na GitHub se spustí samo.", data={"path": str(f)})


@tool("record_decision", "Zapíše architektonické rozhodnutí (ADR) do docs/adr projektu: kontext, rozhodnutí, důsledky – "
      "číslované, aby se dalo dohledat, proč je něco tak, jak je.", category="programování", perm="files_write")
async def record_decision(ctx, project: str, title: str, context: str, decision: str, consequences: str,
                          status: Annotated[str, "Navrženo / Přijato / Nahrazeno"] = "Přijato") -> ToolResult:
    from .. import devops

    root = _root(ctx, project)
    if isinstance(root, ToolResult):
        return root
    p = await asyncio.to_thread(devops.adr, root / "docs" / "adr", title, context, decision, consequences, status)
    return ToolResult(True, f"Rozhodnutí zapsáno: {p.relative_to(root)}", data={"path": str(p)})


@tool("code_sandbox", "Vyzkouší příkaz v jednorázové kopii projektu (bez .git a node_modules): co vypsal, jestli prošel a "
      "které soubory by změnil. Originál se nezmění, kopie se pak smaže.", danger=True, category="programování",
      perm="shell", details=lambda a, ctx=None: [f"Zkopíruje {a.get('project')} do dočasné složky a tam spustí: {a.get('command')}",
                                                   "Originální projekt se nezmění."])
async def code_sandbox(ctx, project: str, command: str, timeout_s: int = 300) -> ToolResult:
    from .. import devops

    root = _root(ctx, project)
    if isinstance(root, ToolResult):
        return root
    box = await asyncio.to_thread(devops.sandbox_copy, root)
    try:
        code, out = await asyncio.to_thread(_run_cmd, command, box, max(10, min(1800, timeout_s)))
        diff = await asyncio.to_thread(devops.changed_files, root, box)
    finally:
        shutil.rmtree(box.parent, ignore_errors=True)
    ch = sum(len(v) for v in diff.values())
    return ToolResult(code == 0, f"$ {command} → {'OK' if code == 0 else f'chyba ({code})'}; v kopii by se změnilo {ch} souborů"
                      + (f" (např. {', '.join((diff['changed'] + diff['added'])[:3])})" if ch else "") + ".\n" + _tail(out),
                      data={"exit_code": code, **diff})
