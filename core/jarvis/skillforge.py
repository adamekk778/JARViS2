"""OMEGA §4.2 Skill Forge, first slice: composite skills.

A composite skill is a protocol (config `stark.protocols`): a named, repeatable series of existing tool steps — no new
code, so no sandbox is needed. Skill Forge adds what a skill needs to be trusted:
- a manifest (inputs, outputs, the permissions and tools it uses, a check that every tool exists and is allowed),
- creation from a finished mission ("ulož to jako dovednost"), always approved by the user before it is saved,
- a version history of every saved change, and rollback to any earlier version.
Code skills (tools/skills.py) keep their own approval flow; this module does not duplicate it.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_versions (proto_id TEXT, version INT, ts REAL, data TEXT, note TEXT,
  PRIMARY KEY (proto_id, version));
"""
# bookkeeping tools that make no sense to replay
SKIP_TOOLS = {"update_plan", "save_mission_as_skill", "list_protocols", "list_automations", "get_time", "checkpoints"}


def _db(rt):
    rt.db.conn.executescript(SCHEMA)
    return rt.db


def _canon(p: dict) -> str:
    return json.dumps(p, ensure_ascii=False, sort_keys=True)


def history(rt, pid: str) -> list[dict]:
    rows = _db(rt).all("SELECT version, ts, data, note FROM skill_versions WHERE proto_id=? ORDER BY version DESC", (pid,))
    return [{"version": r["version"], "ts": r["ts"], "note": r["note"], "protocol": json.loads(r["data"])} for r in rows]


def record(rt, protocols: list[dict], note: str = "") -> list[tuple[str, int]]:
    """Store a new version of every protocol that differs from its latest stored version. → [(id, version)]"""
    out = []
    db = _db(rt)
    for p in protocols:
        last = db.one("SELECT version, data FROM skill_versions WHERE proto_id=? ORDER BY version DESC LIMIT 1", (p["id"],))
        if last and _canon(json.loads(last["data"])) == _canon(p):
            continue
        v = (last["version"] if last else 0) + 1
        db.exec("INSERT INTO skill_versions VALUES (?,?,?,?,?)", (p["id"], v, time.time(), _canon(p), note[:200]))
        out.append((p["id"], v))
    return out


AUTO = "auto:"          # OMEGA 150: automations are versioned in the same table, their ids prefixed


def _record_one(rt, key: str, data: dict, note: str) -> int | None:
    db = _db(rt)
    last = db.one("SELECT version, data FROM skill_versions WHERE proto_id=? ORDER BY version DESC LIMIT 1", (key,))
    if last and _canon(json.loads(last["data"])) == _canon(data):
        return None
    v = (last["version"] if last else 0) + 1
    db.exec("INSERT INTO skill_versions VALUES (?,?,?,?,?)", (key, v, time.time(), _canon(data), note[:200]))
    return v


def rollback(rt, pid: str, version: int) -> dict:
    row = _db(rt).one("SELECT data FROM skill_versions WHERE proto_id=? AND version=?", (pid, int(version)))
    if not row:
        raise ValueError(f"Verze {version} dovednosti {pid} neexistuje.")
    old = json.loads(row["data"])
    if pid.startswith(AUTO):
        aid = pid[len(AUTO):]
        items = [x.model_dump(mode="json") for x in rt.cfg.automations.items]
        items = [old if x["id"] == aid else x for x in items] if any(x["id"] == aid for x in items) else items + [old]
        rt.skill_note = f"návrat na verzi {version}"
        rt.update_config({"automations": {"items": items}})
        return old
    items = [x.model_dump(mode="json") for x in rt.cfg.stark.protocols]
    items = [old if x["id"] == pid else x for x in items] if any(x["id"] == pid for x in items) else items + [old]
    rt.skill_note = f"návrat na verzi {version}"
    rt.update_config({"stark": {"protocols": items}})
    return old


def manifest(rt, proto: dict) -> dict:
    """What the skill needs and does: tools, permission areas, inputs/outputs, and problems that would stop it."""
    from . import tools
    from .permissions import LABELS, PERMS, blocked_by, perm_of

    used, perms, problems = [], set(), []
    for st in proto.get("steps", []):
        name = st.get("tool")
        if not name:
            continue
        used.append(name)
        spec = tools.REGISTRY.get(name)
        if spec is None:
            problems.append(f"Nástroj {name} neexistuje.")
            continue
        perms.add(perm_of(spec))
        if name in rt.cfg.tools.disabled:
            problems.append(f"Nástroj {name} je vypnutý.")
        off = blocked_by(rt.cfg, spec)
        if off:
            problems.append(f"Oprávnění „{LABELS[off]}“ je vypnuté.")
        if any("[REDACTED]" in str(v) or "***" in str(v) for v in (st.get("args") or {}).values()):
            problems.append(f"Krok {name} obsahoval citlivý údaj – doplň ho ručně.")
    asks = [st["ask"] for st in proto.get("steps", []) if st.get("ask")]
    return {"id": proto.get("id"), "name": proto.get("name"), "kind": "composite", "tools": used,
            "permissions": sorted(PERMS.get(p, p) for p in perms), "inputs": "žádné (spouští se hlasem, tlačítkem nebo automatizací)",
            "outputs": "výsledky jednotlivých kroků v chatu a v Úkolech", "ai_steps": len(asks),
            "dangerous_steps_confirm": True, "problems": problems}


def from_task(rt, task_id: str, name: str = "") -> dict:
    """A protocol draft from the successful tool calls of a finished mission (in order, duplicates folded)."""
    t = rt.tasks.get(task_id)
    if not t:
        raise ValueError("Ten úkol neexistuje.")
    steps: list[dict] = []
    for a in t["actions"]:
        if not a["ok"] or a["tool"] in SKIP_TOOLS:
            continue
        try:
            args = json.loads(a["args"] or "{}")
        except ValueError:
            continue                                   # truncated args → cannot replay this one exactly
        st = {"tool": a["tool"], "args": args if isinstance(args, dict) else {}}
        if not steps or steps[-1] != st:
            steps.append(st)
    if not steps:
        raise ValueError("V tomhle úkolu není nic, co by šlo zopakovat (žádná úspěšná akce).")
    nm = (name or t["goal"])[:40].strip() or "Moje dovednost"
    pid = re.sub(r"[^a-z0-9]+", "-", _ascii(nm.lower())).strip("-") or f"d{int(time.time())}"
    return {"id": pid, "name": nm, "icon": "magic-wand", "steps": steps[:20]}


def _ascii(s: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def on_config_change(rt, old: Any, new: Any) -> None:
    """Called after every settings change: a changed protocol gets a new version."""
    try:
        before = {p.id: p.model_dump(mode="json") for p in old.stark.protocols}
        after = [p.model_dump(mode="json") for p in new.stark.protocols]
        if any(before.get(p["id"]) != p for p in after):
            record(rt, after, getattr(rt, "skill_note", "") or "uloženo")
        a_before = {a.id: a.model_dump(mode="json") for a in old.automations.items}
        a_after = [a.model_dump(mode="json") for a in new.automations.items]
        changed = [a for a in a_after if a_before.get(a["id"]) != a]
        if changed:
            note = getattr(rt, "skill_note", "") or "uloženo"
            for a in changed:                      # the stored id carries the prefix, the data stays the automation
                _record_one(rt, AUTO + a["id"], a, note)
    finally:
        rt.skill_note = ""
