"""Omega Brain by voice: several solutions tried and compared (004), what could go wrong before it runs (008).
Dynamic priorities (009) work on their own in the mission queue (mission_queue shows the order and the reasons)."""
from __future__ import annotations

import time
import uuid
from typing import Annotated

from .. import paths
from .base import ToolResult, tool

_SOLUTIONS: dict[str, dict] = {}


def _solve_details(a: dict, ctx=None) -> list[str]:
    return [f"V dočasných kopiích projektu {a.get('project')} zkusí AI {a.get('n', 3)} různé přístupy a u každého spustí "
            f"tvůj příkaz testů: {a.get('test_cmd')}.", "Testy tak spustí kód, který napsala AI – jen v kopiích. Projekt se "
            "nezmění, vybrané řešení zapíšeš až příkazem „použij řešení…“."]


@tool("solve_problem", "Vyřeší problém víc způsoby a vybere nejlepší: AI navrhne několik opravdu různých přístupů. U kódu "
      "(project + test_cmd + files) každý vyzkouší proti testům v dočasné kopii; jinak každý plán prověří, co by "
      "selhalo, a ohodnotí. Ukáže srovnání a doporučení; nic sám nezapíše.", category="mozek", perm="shell",
      danger_if=lambda a, ctx=None: bool(a.get("project")), details=_solve_details)
async def solve_problem(ctx, problem: str, project: str = "", test_cmd: str = "",
                        files: Annotated[list[str], "soubory, které se smí měnit (u kódu)"] = [],  # noqa: B006
                        n: Annotated[int, "kolik různých přístupů (2–5)"] = 3) -> ToolResult:
    from .. import omega

    n = max(2, min(int(n or 3), 5))
    try:
        if project:
            from .devlab_tools import _proj

            root = _proj(ctx, project)
            if isinstance(root, ToolResult):
                return root
            if not test_cmd or not files:
                return ToolResult(False, "U kódu potřebuju příkaz testů (test_cmd) a soubory, které se smí měnit.")
            rel = []
            for f in files:
                p = (root / f).resolve()
                if not p.is_file() or root.resolve() not in p.parents:
                    return ToolResult(False, f"Soubor {f} v projektu není.")
                rel.append(str(p.relative_to(root.resolve())).replace("\\", "/"))
            r = await omega.solve_code(ctx, problem, root, test_cmd, rel, n)
            sid = uuid.uuid4().hex[:6]
            _SOLUTIONS[sid] = {"root": str(root), "candidates": r["candidates"], "ts": time.time()}
            out = paths.sub("vylepseni") / f"reseni-{sid}.diff"
            out.write_text("\n\n".join(f"### {chr(65 + i)}: {c['name']} – testy {'prošly' if c['ok'] else 'neprošly'}\n{c['diff'] or '(beze změn)'}"
                                       for i, c in enumerate(r["candidates"])), encoding="utf-8")
            table = "; ".join(f"{chr(65 + i)} {c['name']}: {'✓ testy prošly' if c['ok'] else '✗ neprošly'}, {c['rounds']} kol, "
                              f"{c['changed_lines']} řádků" for i, c in enumerate(r["candidates"]))
            best = r["candidates"][0]
            msg = (f"Zkusil jsem {len(r['candidates'])} přístupy. {table}. "
                   + (f"Nejlepší je A ({best['name']}) – řekni „použij řešení {sid} A“ a zapíšu ho." if best["ok"]
                      else "Žádný přístup testy neprošel; rozdíly jsou v příloze."))
            return ToolResult(True, msg, data={"id": sid, **{k: v for k, v in r.items() if k != "candidates"},
                                               "candidates": [{k: v for k, v in c.items() if k != "files"} for c in r["candidates"]]},
                              attachments=[str(out)])
        r = await omega.solve_plans(ctx, problem, n)
    except ValueError as e:
        return ToolResult(False, f"Řešení se nepovedlo: {e}")
    lines = []
    for i, c in enumerate(r["candidates"]):
        blocks = sum(f["level"] == "blok" for f in c["findings"])
        lines.append(f"{chr(65 + i)} {c['name']} (skóre {c['score']}; {c['rating'].get('why', '')}"
                     + (f"; {blocks} kroků by selhalo" if blocks else "") + ")")
    best = r["best"]
    return ToolResult(True, f"Doporučuji {best['name']}: {best.get('idea', '')} Kroky: {'; '.join(best.get('steps') or [])}. "
                      f"Srovnání: {' | '.join(lines)}.", data=r)


@tool("apply_solution", "Zapíše do projektu jedno z řešení, které solve_problem vyzkoušel (id a písmeno A/B/C).",
      category="mozek", perm="files_write", danger=True,
      details=lambda a, ctx=None: [f"Do projektu se zapíšou soubory řešení {a.get('which', 'A')} z pokusu {a.get('solution_id')}."])
async def apply_solution(ctx, solution_id: str, which: str = "A") -> ToolResult:
    from pathlib import Path

    s = _SOLUTIONS.get(solution_id)
    if not s:
        return ToolResult(False, "To řešení už nemám – spusť solve_problem znovu.")
    i = ord((which or "A").strip().upper()[:1]) - 65
    if not 0 <= i < len(s["candidates"]):
        return ToolResult(False, f"Řešení {which} neexistuje.")
    c = s["candidates"][i]
    if not c.get("files"):
        return ToolResult(False, "Tohle řešení nic nemění.")
    root = Path(s["root"])
    for f, text in c["files"].items():
        (root / f).write_text(text, encoding="utf-8")
    return ToolResult(True, f"Zapsáno řešení {chr(65 + i)} ({c['name']}): {', '.join(c['files'])}."
                      + ("" if c["ok"] else " Pozor: testy s ním neprošly."))


@tool("predict_errors", "Předpoví, co by se v plánu mohlo pokazit, ještě než se spustí: neexistující soubory, vypnutá "
      "oprávnění, nenastavené propojení (e-mail, domácnost, telefon), chybějící internet, nástroje, které poslední "
      "dobou často selhávají, a kroky, které budou chtít potvrzení.", category="mozek")
async def predict_errors(ctx, steps: Annotated[list, "kroky: věty nebo {tool, args}"] = [],  # noqa: B006
                         goal: str = "") -> ToolResult:
    from .. import omega

    items = list(steps or []) or ([goal] if goal else [])
    if not items:
        cur = getattr(ctx.tasks, "current", None)          # the running mission's plan
        items = [s["title"] for s in (cur or {}).get("steps", [])]
    if not items:
        return ToolResult(False, "Dej mi kroky plánu nebo cíl.")
    found = omega.predict_errors(ctx, items)
    return ToolResult(True, omega.summarize(found), data=found)
