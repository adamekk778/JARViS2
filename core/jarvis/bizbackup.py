"""3.13 Velín firmy: the whole company setup in one file – the profile, every agent (what it does, when, which services,
what it hands on, its rules), the goals, the limits and the company brain. For a backup, or to move the company to
another PC. Never the keys: the logins to the services stay in Windows' secure storage and are connected again there.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any

VERSION = 1
AGENT_KEYS = ("name", "icon", "role", "task", "tools", "every_min", "daily_at", "work_hours", "enabled", "dept", "skill", "replaces",
              "bkey", "triggers", "next", "tier", "auto")
MAX_BYTES = 8_000_000


def export(rt: Any) -> dict:
    from . import bizagents, bizcompany, bizgoals

    return {"jarvis_velin": VERSION, "exported": dt.datetime.now().isoformat(timespec="seconds"),
            "profile": bizcompany.profile(rt),
            "agents": [{k: a.get(k) for k in AGENT_KEYS} for a in bizagents.agents(rt)],
            "goals": [{k: g.get(k) for k in ("name", "metric", "target", "unit", "period", "direction")} for g in bizgoals.goals(rt)],
            "budget": bizcompany.budget(rt), "dept_budget": bizcompany.dept_budgets(rt),
            "phone": bizcompany._kv(rt, "biz_phone", "away"), "events_every": bizcompany._kv(rt, "biz_events_every", "60"),
            "brain": [{"text": n["text"], "source": n.get("source", "")} for n in reversed(bizcompany.brain_notes(rt, 5000))]}


def save_file(rt: Any) -> str:
    from . import paths

    folder = paths.data_dir() / "Zálohy"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"velin_firmy_{dt.datetime.now().strftime('%Y-%m-%d_%H-%M')}.json"
    out.write_text(json.dumps(export(rt), ensure_ascii=False, indent=1), encoding="utf-8")
    return str(out)


def restore(rt: Any, data: Any, replace: bool = False) -> dict:
    """Load a saved setup. replace=False adds to what is here (an agent of the same name is updated), True starts over
    (the agents, goals and the brain here are replaced). Returns what was done."""
    from . import bizagents, bizcompany, bizgoals

    if isinstance(data, (str, bytes)):
        if len(data) > MAX_BYTES:
            raise ValueError("Soubor je moc velký.")
        try:
            data = json.loads(data)
        except ValueError:
            raise ValueError("Tohle není záloha Velínu (soubor .json z „Zálohovat nastavení“).") from None
    if not isinstance(data, dict) or "jarvis_velin" not in data:
        raise ValueError("Tohle není záloha Velínu (soubor .json z „Zálohovat nastavení“).")
    if int(data.get("jarvis_velin") or 0) > VERSION:
        raise ValueError("Záloha je z novější verze JARVIS – nejdřív JARVIS aktualizuj.")
    db = bizagents._db(rt)
    if replace:
        db.exec("DELETE FROM biz_agents")
        bizgoals._db(rt).exec("DELETE FROM biz_goals")
        db.exec("DELETE FROM biz_brain")
    if isinstance(data.get("profile"), dict) and (replace or not any(bizcompany.profile(rt).values())):
        bizcompany.save_profile(rt, data["profile"])
    known = {t["name"] for t in bizagents.allowed_tools()}
    by_name = {a["name"].lower(): a for a in bizagents.agents(rt)}
    added = updated = skipped = 0
    for raw in (data.get("agents") or [])[:500]:
        if not isinstance(raw, dict):
            continue
        a = {k: raw.get(k) for k in AGENT_KEYS if k in raw}
        a["tools"] = [t for t in a.get("tools") or [] if t in known]          # a tool this JARVIS does not have is left out
        if not a["tools"]:
            skipped += 1
            continue
        old = by_name.get(str(a.get("name") or "").lower())
        try:
            if old:
                bizagents.save(rt, {**old, **a, "id": old["id"]})
                updated += 1
            else:
                bizagents.save(rt, a)
                added += 1
        except ValueError:
            skipped += 1
    goals = 0
    have = {g["name"].lower() for g in bizgoals.goals(rt)}
    for g in (data.get("goals") or [])[:50]:
        if isinstance(g, dict) and str(g.get("name", "")).lower() not in have:
            try:
                bizgoals.save(rt, g)
                goals += 1
            except ValueError:
                pass
    notes = 0
    if replace or not bizcompany.brain_notes(rt, 1):
        for n in (data.get("brain") or [])[:5000]:
            if isinstance(n, dict) and str(n.get("text", "")).strip():
                try:
                    bizcompany.brain_add(rt, str(n["text"]), str(n.get("source") or "záloha"))
                    notes += 1
                except ValueError:
                    pass
    if isinstance(data.get("budget"), int):
        bizcompany.set_budget(rt, data["budget"])
    for dept, n in (data.get("dept_budget") or {}).items() if isinstance(data.get("dept_budget"), dict) else []:
        if dept in bizcompany.DEPTS:
            try:
                bizcompany.set_dept_budget(rt, dept, int(n))
            except (TypeError, ValueError):
                pass
    if data.get("phone") in ("away", "always", "off"):
        bizcompany._set(rt, "biz_phone", data["phone"])
    if str(data.get("events_every")) in ("60", "180", "600"):
        bizcompany._set(rt, "biz_events_every", str(data["events_every"]))
    bizcompany.log_action(rt, {"id": None, "name": "Velín"}, "restore", "", f"obnoveno ze zálohy: {added} nových, {updated} upravených "
                          f"agentů, {goals} cílů, {notes} poznámek", True)
    return {"added": added, "updated": updated, "skipped": skipped, "goals": goals, "notes": notes, "at": time.time()}
