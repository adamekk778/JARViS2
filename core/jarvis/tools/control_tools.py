"""OMEGA wave 1 by voice: the mission queue, resuming, AI usage, the audit export, the data inventory, the microphone
log and the mission workspace. Turning safety off (read-only, permissions, reset, backups) is only in the UI — an AI
must never switch its own limits off."""
from __future__ import annotations

import datetime as dt
import re
import time
from typing import Annotated

from .base import ToolResult, tool


def _when(text: str, now: dt.datetime | None = None) -> float | None:
    """"18:30", "za 20 minut", "zítra 8:00" → timestamp (None when empty / not understood)."""
    t = (text or "").strip().lower()
    if not t:
        return None
    now = now or dt.datetime.now()
    m = re.search(r"za\s+(\d+)\s*(min|minut|h|hod)", t)
    if m:
        n = int(m.group(1))
        return (now + dt.timedelta(hours=n) if m.group(2).startswith("h") else now + dt.timedelta(minutes=n)).timestamp()
    m = re.search(r"(\d{1,2})[:.](\d{2})", t)
    if m:
        at = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if "zítra" in t or "zitra" in t or at <= now:
            at += dt.timedelta(days=1)
        return at.timestamp()
    return None


@tool("queue_mission", "Zařadí misi do fronty JARVISe: proběhne, až bude volno, nebo v daný čas (at: „18:30“, „za 20 "
      "minut“), volitelně s termínem (deadline), o kterém JARVIS dá vědět. template „pc_report“ = kontrola PC bez AI; "
      "jinak goal = úkol v přirozené řeči.", category="systém", perm="apps")
async def queue_mission(ctx, goal: str = "", template: str = "", at: str = "", deadline: str = "",
                        priority: Annotated[str, "vysoká / normální / nízká (prázdné = odhadne se z textu)"] = "") -> ToolResult:
    from ..missions import TEMPLATES

    nb, dl = _when(at), _when(deadline)
    if at and nb is None:
        return ToolResult(False, "Čas nerozumím – zkus „18:30“ nebo „za 20 minut“.")
    if template:
        if template not in TEMPLATES:
            return ToolResult(False, f"Šablonu „{template}“ neznám. Mám: {', '.join(TEMPLATES)}.")
        tid = ctx.missions.enqueue_template(template, dl, nb)
        goal = TEMPLATES[template][0]
    elif goal.strip():
        tid = ctx.missions.enqueue(goal.strip(), None, dl, nb, priority if priority in ("vysoká", "normální", "nízká") else "")
    else:
        return ToolResult(False, "Řekni, co má mise udělat (goal), nebo zvol šablonu.")
    when = dt.datetime.fromtimestamp(nb).strftime("%d.%m. %H:%M") if nb else "hned, až bude volno"
    tail = f", termín {dt.datetime.fromtimestamp(dl):%d.%m. %H:%M}" if dl else ""
    return ToolResult(True, f"Mise „{goal[:80]}“ je ve frontě ({when}{tail}).", data={"id": tid})


@tool("mission_queue", "Co čeká ve frontě misí (a kdy).", category="systém", perm="apps")
async def mission_queue(ctx) -> ToolResult:
    q = ctx.tasks.queue()
    if not q:
        return ToolResult(True, "Fronta misí je prázdná.")
    lines = [f"{i}. {t['goal'][:80]}" + (f" – od {dt.datetime.fromtimestamp(t['not_before']):%H:%M}" if t["not_before"] else "")
             + (f" – termín {dt.datetime.fromtimestamp(t['deadline']):%d.%m. %H:%M}" if t["deadline"] else "")
             + f" ({', '.join(t['why'])})" for i, t in enumerate(q, 1)]
    return ToolResult(True, "\n".join(lines), data=q)


@tool("resume_mission", "Naváže přerušenou nebo nedokončenou misi tam, kde skončila (task_id; prázdné = poslední "
      "přerušená).", category="systém", perm="apps")
async def resume_mission(ctx, task_id: str = "") -> ToolResult:
    if not task_id:
        row = ctx.db.one("SELECT id FROM tasks WHERE status IN ('interrupted','failed') ORDER BY created DESC LIMIT 1")
        if not row:
            return ToolResult(False, "Žádná přerušená mise není.")
        task_id = row["id"]
    t = ctx.tasks.get(task_id)
    if not t:
        return ToolResult(False, "Tu misi nemám.")
    import asyncio

    asyncio.get_running_loop().call_later(0.2, lambda: ctx.missions.resume(task_id))
    done = sum(s["status"] == "done" for s in t["steps"])
    return ToolResult(True, f"Navazuji na misi „{t['goal'][:80]}“ ({done} kroků už hotovo).")


@tool("ai_usage", "Kolik dnes JARVIS spotřeboval u AI (odhad tokenů a ceny, podle poskytovatelů), denní limit a "
      "odhad ceny dalšího úkolu (steps = počet kol AI).", category="systém", perm="apps")
async def ai_usage(ctx, steps: int = 0) -> ToolResult:
    u = ctx.usage.today()
    lines = [f"{r['provider']} ({r['model']}): {r['calls']}× · ~{r['tok_in'] + r['tok_out']} tokenů" for r in u["rows"]]
    lim = []
    if u["limit_tokens"]:
        lim.append(f"limit {u['limit_tokens']} tokenů")
    if u["limit_cost"]:
        lim.append(f"limit {u['limit_cost']:g} {u['currency']}")
    head = f"Dnes ~{u['tokens']} tokenů, cena ~{u['cost']:g} {u['currency']} (odhad)" + (f"; {', '.join(lim)}" if lim else "") + "."
    data = {"today": u}
    if steps:
        e = ctx.usage.estimate(steps)
        head += f" Úkol o {steps} kolech: ~{e['tokens']} tokenů, ~{e['cost']:g} {e['currency']}."
        data["estimate"] = e
    return ToolResult(True, head + ("\n" + "\n".join(lines) if lines else ""), data=data)


@tool("export_audit", "Uloží celý záznam misí a akcí (audit) do souborů JSON a CSV v datové složce JARVISe.",
      category="systém", perm="apps")
async def export_audit(ctx) -> ToolResult:
    import asyncio

    from ..missions import export_audit as ex

    r = await asyncio.to_thread(ex, ctx)
    return ToolResult(True, f"Audit uložen: {r['missions']} misí, {r['actions']} akcí → {r['csv']}", data=r)


@tool("data_inventory", "Jaká osobní data JARVIS ukládá, kolik a kde (konverzace, paměť, mise, soubory, tajemství "
      "jen podle názvu).", category="systém", perm="apps")
async def data_inventory(ctx) -> ToolResult:
    import asyncio

    from ..privacy import inventory

    inv = await asyncio.to_thread(inventory, ctx)
    lines = [f"{r['what']}: {r['count']}" for r in inv["database"] if r["count"]]
    return ToolResult(True, f"Data jsou v {inv['base']}. " + "; ".join(lines) +
                      f". Hesla a klíče: {inv['secrets_where']}.", data=inv)


@tool("mic_history", "Kdy byl za posledních 7 dní zapnutý mikrofon (naslouchání JARVISe). Kameru JARVIS nepoužívá.",
      category="systém", perm="apps")
async def mic_history(ctx) -> ToolResult:
    r = ctx.miclog.recent()
    n = len(r["sessions"])
    return ToolResult(True, f"Mikrofon naslouchal {n}× celkem {r['seconds'] // 60} min {r['seconds'] % 60} s za 7 dní"
                            + (" a teď právě poslouchá." if r["now"] else ".") + " Kameru JARVIS nepoužívá.", data=r)


@tool("mission_save_file", "Uloží soubor do pracovní složky aktuální mise (výsledek, poznámky, data) a zapíše ho mezi "
      "výsledky mise s otiskem SHA-256.", category="soubory", perm="files_write")
async def mission_save_file(ctx, name: Annotated[str, "název souboru, např. souhrn.md"], content: str) -> ToolResult:
    from pathlib import Path

    from ..missions import workspace

    cur = ctx.tasks.current
    if not cur:
        return ToolResult(False, "Neběží žádná mise.")
    safe = re.sub(r"[^\w.\- ]+", "_", Path(name).name).strip() or f"soubor-{int(time.time())}.txt"
    p = workspace(cur["id"]) / safe
    p.write_text(content, encoding="utf-8")
    art = ctx.tasks.add_artifact(p, safe)
    return ToolResult(True, f"Uloženo do mise: {p}", data=art)
