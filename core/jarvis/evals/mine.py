"""3.17 Testy z tvých povelů (návrh 12): what you asked and what worked becomes a check of its own – kept only on this
PC. After an update (or on the button in Diagnostika) every remembered request is tried again offline: does it still
reach the same tool (the instant command, the reflex, or the tools sent with the message)? What would now go
differently is listed, so an update can never quietly break the way you talk to JARVIS.
"""
from __future__ import annotations

import json
from typing import Any


def check(rt: Any, limit: int = 300) -> dict:
    from .. import instant, toolmind, tools
    from ..tools import select as sel

    tools.load_builtin()
    db = toolmind._db(rt)
    rows = db.all("SELECT phrase, tool, args, ok FROM tool_memory WHERE ok > 0 AND bad = 0 ORDER BY ok DESC, last DESC LIMIT ?",
                  (limit,))
    allowed = {n for n in tools.REGISTRY}
    failed, ok = [], 0
    seen: set[tuple[str, str]] = set()
    for r in rows:
        key = (r["phrase"], r["tool"])
        if key in seen:
            continue
        seen.add(key)
        if r["tool"] not in tools.REGISTRY:
            failed.append({"phrase": r["phrase"], "tool": r["tool"], "got": "nástroj už neexistuje"})
            continue
        p = instant.plan(r["phrase"])
        if p is not None:
            if p.calls and p.calls[0][0] == r["tool"]:
                ok += 1
            else:
                failed.append({"phrase": r["phrase"], "tool": r["tool"], "got": f"okamžitý příkaz {p.calls[0][0] if p.calls else '?'}"})
            continue
        picked = sel.pick(tools.REGISTRY, allowed, r["phrase"], [])
        if r["tool"] in picked:
            ok += 1
        else:
            failed.append({"phrase": r["phrase"], "tool": r["tool"], "got": "nástroj už nejde se zprávou"})
    out = {"checked": len(seen), "ok": ok, "failed": failed}
    try:
        db.exec("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
        db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES ('mine_check', ?)", (json.dumps(out, ensure_ascii=False)[:20000],))
    except Exception:  # noqa: BLE001
        pass
    return out


def after_update(rt: Any) -> dict | None:
    """Once per new version: check, and tell when something of yours would now go differently."""
    from .. import __version__

    db = rt.db
    db.exec("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    row = db.one("SELECT v FROM kv WHERE k='mine_version'")
    if row and row["v"] == __version__:
        return None
    db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES ('mine_version', ?)", (__version__,))
    res = check(rt)
    if res["failed"]:
        rt.notify("Kontrola po aktualizaci", f"{len(res['failed'])} z {res['checked']} tvých obvyklých povelů by teď šlo jinak – "
                  "podívej se do Diagnostiky → Moje povely.", speak=False)
    return res
