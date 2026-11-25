"""Voice test set (návrh 15): your own recordings → speech recognition → the command JARVIS would run.

A folder with WAV files and `cases.json`:  {"hlasitost30.wav": {"text": "hlasitost na 30", "tool": "volume"}, …}
Record the same sentences with different microphones, a TV in the background, from across the room – the report
says the word error rate (WER) of each recording and whether the right command came out of it.

    python -m jarvis.evals --voice C:\\Users\\me\\JARVIS-hlas
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable


def _words(s: str) -> list[str]:
    t = unicodedata.normalize("NFKD", (s or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", t)


def wer(ref: str, hyp: str) -> float:
    """Word error rate: (substitutions + insertions + deletions) / words in the reference; accents ignored."""
    r, h = _words(ref), _words(hyp)
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return prev[-1] / len(r)


def tool_for(text: str) -> str:
    """The command these words become: an instant command, else the first tool the selector's intents point to."""
    from .. import instant
    from ..tools import select

    p = instant.plan(text)
    if p and p.calls:
        return p.calls[0][0]
    hits = select.intents(text)
    return hits[0] if hits else ""


def run(folder: str | Path, transcribe: Callable[[str], str]) -> dict[str, Any]:
    folder = Path(folder)
    cases = json.loads((folder / "cases.json").read_text("utf-8"))
    rows = []
    for name, exp in cases.items():
        f = folder / name
        if not f.exists():
            rows.append({"file": name, "error": "soubor chybí"})
            continue
        try:
            heard = transcribe(str(f)) or ""
        except Exception as e:  # noqa: BLE001
            rows.append({"file": name, "error": str(e)[:120]})
            continue
        want = exp.get("tool", "")
        got = tool_for(heard) if want else ""
        rows.append({"file": name, "expected": exp.get("text", ""), "heard": heard, "wer": round(wer(exp.get("text", ""), heard), 3),
                     "tool_ok": (got == want) if want else None, "tool": got})
    scored = [r for r in rows if "wer" in r]
    tools_ = [r for r in scored if r["tool_ok"] is not None]
    return {"mode": "voice", "files": len(rows), "errors": [r for r in rows if "error" in r],
            "wer": round(sum(r["wer"] for r in scored) / len(scored), 3) if scored else None,
            "commands_ok": round(sum(1 for r in tools_ if r["tool_ok"]) / len(tools_), 3) if tools_ else None,
            "rows": rows}
