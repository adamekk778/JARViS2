"""3.14 Samooprava dovedností (návrh 113): a skill that keeps failing gets a proposed fix.

- every failure of a skill is remembered (the last error line and the tail of its output) – shown in the notch once an
  hour per skill with "Řekni: oprav dovednost …"
- skill_fix asks the AI for the whole corrected file, checks that it compiles and keeps the same tools, and shows the
  change line by line (a diff) – nothing is written yet
- skill_fix_apply writes it only after your confirmation (the confirmation card shows the diff), keeps the old version
  in skills/.backup and reloads the skill; a fix that does not load is rolled back
"""
from __future__ import annotations

import difflib
import re
import time
from pathlib import Path
from typing import Any

LAST_ERRORS: dict[str, dict] = {}
PROPOSALS: dict[str, dict] = {}
NOTICE_EVERY_S = 3600
_noticed: dict[str, float] = {}
TOOL_RX = re.compile(r"@tool\(\s*[\"']([A-Za-z0-9_]+)[\"']")
PROMPT = """Oprav tuhle dovednost (skill) asistenta JARVIS. Je to Python soubor s nástroji označenými @tool(...).

Pravidla:
- vrať CELÝ opravený soubor v jediném bloku ```python … ```, nic jiného nepiš kromě jedné věty, co bylo špatně
- zachovej názvy nástrojů (@tool("…")) i jejich parametry, manifest (MANIFEST / komentáře nahoře) a importy JARVISe
- oprav jen chybu, nic nepřidávej navíc; žádné spouštění programů, mazání souborů ani síť, pokud tam předtím nebyly

Chyba:
{error}

Co uživatel hlásí: {problem}

Soubor {name}.py:
```python
{code}
```"""


def record_failure(rt: Any, name: str, tool: str, error: str, notify: bool = True) -> None:
    LAST_ERRORS[name] = {"tool": tool, "error": error[-2000:], "ts": time.time()}
    now = time.time()
    if notify and now - _noticed.get(name, 0) > NOTICE_EVERY_S:
        _noticed[name] = now
        try:
            last = (error.strip().splitlines() or ["chyba"])[-1][:140]
            rt.notify("Dovednost spadla", f"{name}: {last}. Řekni „oprav dovednost {name}“ a navrhnu opravu.", speak=False)
        except Exception:  # noqa: BLE001 – a notice must never break the tool result
            pass


def tool_names(code: str) -> list[str]:
    return sorted(set(TOOL_RX.findall(code or "")))


def extract_code(answer: str) -> str:
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", answer or "", re.S)
    return m.group(1).strip() + "\n" if m else ""


def check(old: str, new: str) -> list[str]:
    """Why a proposed fix cannot be used ([] = fine)."""
    problems = []
    if not new.strip():
        return ["AI nevrátila kód"]
    try:
        compile(new, "<skill>", "exec")
    except SyntaxError as e:
        problems.append(f"syntaktická chyba na řádku {e.lineno}: {e.msg}")
    if "@tool(" not in new:
        problems.append("chybí @tool(...)")
    lost = set(tool_names(old)) - set(tool_names(new))
    if lost:
        problems.append(f"zmizely nástroje: {', '.join(sorted(lost))}")
    if new.strip() == old.strip():
        problems.append("oprava nic nemění")
    return problems


def diff(old: str, new: str, name: str) -> list[str]:
    return list(difflib.unified_diff(old.splitlines(), new.splitlines(), f"{name}.py (teď)", f"{name}.py (oprava)", lineterm="", n=2))


async def propose(rt: Any, name: str, problem: str = "") -> dict:
    from .tools.skills import skills_dir

    path = skills_dir() / f"{name}.py"
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", name or "") or not path.exists():
        raise ValueError(f"Dovednost „{name}“ nemám.")
    old = path.read_text(encoding="utf-8")
    err = LAST_ERRORS.get(name, {})
    if not err and not problem.strip():
        raise ValueError(f"U dovednosti „{name}“ nemám zaznamenanou chybu – řekni, co nefunguje.")
    msg = PROMPT.format(error=err.get("error") or "(žádná zaznamenaná)", problem=problem.strip() or "(nic)", name=name,
                        code=old[:30000])
    answer = await rt.router.complete([{"role": "user", "content": msg}])
    new = extract_code(answer)
    problems = check(old, new)
    why = re.sub(r"```.*?```", "", answer or "", flags=re.S).strip()[:300]
    out = {"name": name, "code": new, "diff": diff(old, new, name) if new else [], "problems": problems, "why": why,
           "error": err.get("error", ""), "ts": time.time()}
    if not problems:
        PROPOSALS[name] = out
    return out


def apply(rt: Any, name: str) -> dict:
    from .tools.skills import load_skill_file, skills_dir

    prop = PROPOSALS.get(name)
    if not prop:
        raise ValueError(f"Pro „{name}“ nemám připravenou opravu – nejdřív řekni „oprav dovednost {name}“.")
    path = skills_dir() / f"{name}.py"
    old = path.read_text(encoding="utf-8")
    backup_dir = skills_dir() / ".backup"
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.py"
    backup.write_text(old, encoding="utf-8")
    path.write_text(prop["code"], encoding="utf-8")
    legacy = name in set(getattr(rt.cfg.tools, "legacy_skills", []) or [])
    try:
        tools = load_skill_file(path, legacy)
    except Exception as e:
        path.write_text(old, encoding="utf-8")
        load_skill_file(path, legacy)
        raise ValueError(f"Oprava se nenačetla ({type(e).__name__}: {e}) – vrátil jsem původní verzi.") from e
    PROPOSALS.pop(name, None)
    LAST_ERRORS.pop(name, None)
    return {"tools": tools, "backup": str(backup)}


def details(name: str) -> list[str]:
    prop = PROPOSALS.get(name)
    if not prop:
        return [f"Pro „{name}“ zatím není připravená oprava."]
    return [f"Dovednost {name} se změní takto (stará verze se uloží do zálohy):", *prop["diff"][:45]]


def backups(name: str) -> list[Path]:
    from .tools.skills import skills_dir

    return sorted((skills_dir() / ".backup").glob(f"{name}-*.py"))
