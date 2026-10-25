"""OMEGA missions by voice: "zjisti stav mého počítače, připrav report a ulož ho" — a mission with a plan,
acceptance criteria, an artifact (the report file) and evidence of every check."""
from __future__ import annotations

import asyncio
import mimetypes

from .base import ToolResult, tool

STEPS = ["Sběr dat (jen čtení)", "Vyhodnocení", "Zápis reportu", "Ověření výsledku"]


@tool("pc_health_report", "Mise: zjistí stav počítače (jen čtení – CPU, paměť, disky a jejich zdraví, baterie, síť, "
      "procesy, chyby v logu, aktualizace, programy po spuštění, problémová zařízení), sepíše report, uloží ho jako "
      "soubor a ověří. Na „zjisti stav mého PC“, „proč se mi seká počítač“, „udělej report o počítači“.",
      category="systém", perm="system")
async def pc_health_report(ctx, open_report: bool = False) -> ToolResult:
    from .. import pcreport

    t = ctx.tasks
    t.set_criteria(pcreport.CRITERIA)
    t.set_plan(STEPS, 0)
    data = await asyncio.to_thread(pcreport.collect)
    for s in data["sections"]:
        t.add_evidence(s["source"], s["title"], "; ".join(f"{a}: {b}" for a, b in s["rows"][:3]) or s["note"],
                       s["ok"] is not False)
    t.set_plan(STEPS, 1)
    warn = [f["text"] for f in data["findings"] if f["level"] == "warn"]
    t.set_plan(STEPS, 2)
    path = await asyncio.to_thread(pcreport.write_report, data)
    art = t.add_artifact(path, "Report o stavu PC")
    t.set_plan(STEPS, 3)
    t.set_verifying()
    checks = await asyncio.to_thread(pcreport.verify, path, art["sha256"])
    for crit, ok, val in checks:
        t.add_evidence("ověření souboru", crit, val, ok)
    t.set_plan(STEPS, 4)
    failed = [c for c, ok, _ in checks if not ok]
    attachments = []
    try:
        att = await ctx.store.save_path(path, mimetypes.guess_type(path.name)[0] or "text/html")
        attachments = [att.id]
    except Exception:
        pass
    if open_report:
        try:
            await asyncio.to_thread(ctx.platform.open_path, str(path))
        except Exception:
            pass
    if failed:
        return ToolResult(False, f"Report je uložený ({path}), ale ověření neprošlo: {'; '.join(failed)}.",
                          data={"path": str(path), "checks": checks}, attachments=attachments)
    head = "Hlavní zjištění: " + " ".join(warn) if warn else "Všechno, co šlo změřit, je v pořádku."
    return ToolResult(True, f"{head} Report jsem uložil do {path} a ověřil (5/5 kritérií splněno).",
                      data={"path": str(path), "findings": data["findings"], "checks": [c for c, _, _ in checks]},
                      attachments=attachments)


def _last_task_id(ctx) -> str:
    cur = ctx.tasks.current
    for t in ctx.tasks.list(limit=20, status="done"):
        if not cur or t["id"] != cur["id"]:
            return t["id"]
    return ""


def _skill_details(args: dict, ctx=None) -> list[str]:
    from .. import skillforge
    from ..agent import describe_call

    try:
        p = skillforge.from_task(ctx, args.get("task_id") or _last_task_id(ctx), args.get("name", ""))
    except Exception as e:
        return [f"Nelze: {e}"]
    return [f"Název: {p['name']}"] + [f"{i + 1}. {describe_call(s['tool'], s['args'])}" for i, s in enumerate(p["steps"])]


@tool("save_mission_as_skill", "Skill Forge: uloží poslední dokončený úkol/misi jako znovupoužitelnou dovednost "
      "(protokol), aby ji šlo příště spustit jedním příkazem („spusť protokol …“). Na „ulož to jako dovednost“, "
      "„nauč se to dělat takhle“. Uživatel kroky vždy schválí.", danger=True, details=_skill_details,
      category="systém", perm="apps")
async def save_mission_as_skill(ctx, name: str, task_id: str = "") -> ToolResult:
    from .. import skillforge

    p = skillforge.from_task(ctx, task_id or _last_task_id(ctx), name)
    m = skillforge.manifest(ctx, p)
    if m["problems"]:
        return ToolResult(False, "Dovednost nejde uložit: " + " ".join(m["problems"]), data=m)
    items = [x.model_dump(mode="json") for x in ctx.cfg.stark.protocols if x.id != p["id"]] + [p]
    ctx.skill_note = "vytvořeno z mise"
    ctx.update_config({"stark": {"protocols": items}})
    v = skillforge.history(ctx, p["id"])[0]["version"]
    return ToolResult(True, f"Dovednost „{p['name']}“ uložena (verze {v}, {len(p['steps'])} kroků). "
                            f"Spustíš ji „spusť protokol {p['name'].lower()}“.", data={"id": p["id"], "manifest": m})
