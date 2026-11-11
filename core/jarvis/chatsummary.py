"""3.12 Chytřejší paměť chatu: the older part of a long conversation is kept as a short summary.

Free AI limits are small, so a long chat used to lose its oldest messages. Now, after a turn, the part beyond the last
few messages is summarised in the background by the provider's quick model (on Groq it has its own allowance) – facts,
names, decisions, unfinished things. Each request then carries the summary plus the recent messages: JARVIS still
knows what you talked about an hour ago, for a fraction of the tokens. Nothing is summarised in the private mode.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

KEEP = 8            # the newest messages always go word for word
REFRESH = 6         # summarise again once this many more have piled up beyond KEEP
PROMPT = ("Shrň dosavadní konverzaci uživatele s asistentem JARVIS do nejvýš 8 krátkých českých vět. Zachovej fakta "
          "o uživateli, jména, čísla, rozhodnutí, co se domluvilo a co zůstalo rozdělané. Žádný úvod, jen shrnutí.")


def _key(conv: str) -> str:
    return f"conv_summary:{conv}"


def load(rt, conv: str | None = None) -> dict:
    conv = conv or rt.memory.current_conversation
    row = rt.db.one("SELECT v FROM kv WHERE k=?", (_key(conv),))
    try:
        return json.loads(row["v"]) if row else {}
    except (ValueError, TypeError):
        return {}


def apply(rt, history: list[dict]) -> tuple[str, list[dict]]:
    """(summary, the messages after it) for the request; no summary yet → ("", history unchanged)."""
    if rt.memory.private:
        return "", history
    s = load(rt)
    if not s.get("summary"):
        return "", history
    rest = [m for m in history if float(m.get("created") or 0) > float(s.get("upto") or 0)]
    return s["summary"], rest


async def refresh(rt) -> bool:
    """After a turn: summarise what lies beyond the newest KEEP messages, when enough has piled up."""
    if rt.memory.private:
        return False
    conv = rt.memory.current_conversation
    s = load(rt, conv)
    upto = float(s.get("upto") or 0)
    rows = rt.db.all("SELECT role, content, created FROM messages WHERE conv_id=? AND created>? AND role IN ('user','assistant') "
                     "ORDER BY created", (conv, upto))
    if len(rows) < KEEP + REFRESH:
        return False
    old = rows[:-KEEP]
    lines = [f"{'Uživatel' if r['role'] == 'user' else 'JARVIS'}: {(r['content'] or '')[:1200]}" for r in old]
    text = (f"Dosavadní shrnutí: {s['summary']}\n\n" if s.get("summary") else "") + "Další část konverzace:\n" + "\n".join(lines)
    try:
        summary = (await rt.router.complete([{"role": "system", "content": PROMPT}, {"role": "user", "content": text[-14000:]}],
                                            fast=True)).strip()
    except Exception as e:  # noqa: BLE001 – no AI right now: the chat simply goes on without a new summary
        log.debug("chat summary: %s", e)
        return False
    if not summary:
        return False
    rt.db.exec("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)",
               (_key(conv), json.dumps({"summary": summary[:2000], "upto": old[-1]["created"], "n": (s.get("n") or 0) + len(old)},
                                       ensure_ascii=False)))
    return True
