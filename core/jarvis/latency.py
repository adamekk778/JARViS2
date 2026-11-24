"""3.16 Měření rychlosti (návrh 16): how long each step of an answer takes, and how often the right tool was there at
once – Diagnostika shows the medians of the last 60 answers.

Steps (ms from the start of the answer): for voice the start is the end of your speech; then "stt" (the words are
written), "agent" (JARVIS starts working), "first_token" (the AI's first word), "first_audio" (the first word is heard),
"done". Typed messages start at "agent".
"Trefa nástroje napoprvé": an answer that used tools without asking for more (no find_tools, no wrong use_tool call).
"""
from __future__ import annotations

import statistics
import time
from collections import deque
from typing import Any

STAGES = ("stt", "agent", "first_token", "first_audio", "done")
LABELS = {"stt": "Přepis řeči", "agent": "Začátek práce", "first_token": "První slovo AI", "first_audio": "První zvuk",
          "done": "Hotovo"}


class Latency:
    def __init__(self, keep: int = 60):
        self.turns: deque[dict] = deque(maxlen=keep)
        self.cur: dict | None = None
        self.notes: deque[dict] = deque(maxlen=30)      # 3.18 side events (Claude's cache warmed again…)

    def note(self, kind: str, data: Any = None) -> None:
        self.notes.append({"kind": kind, "data": data, "ts": time.time()})

    def begin(self, source: str, t0: float | None = None) -> None:
        """A new answer starts (voice: at the end of speech)."""
        self.cur = {"source": source, "t0": t0 if t0 is not None else time.monotonic(), "marks": {}, "info": {}}

    def mark(self, stage: str, t: float | None = None) -> None:
        if self.cur is None:
            return
        if stage not in self.cur["marks"]:                    # the first time counts
            self.cur["marks"][stage] = round(((t if t is not None else time.monotonic()) - self.cur["t0"]) * 1000)

    def agent_start(self, source: str) -> None:
        """The agent begins: a voice answer begun at the end of speech goes on; anything else starts here."""
        cur = self.cur
        if cur is None or cur["source"] != "voice" or source != "voice" or "agent" in cur["marks"] \
                or time.monotonic() - cur["t0"] > 30:
            self.begin(source)
        self.mark("agent")

    def finish(self, **info: Any) -> dict | None:
        cur = self.cur
        if cur is None:
            return None
        self.mark("done")
        cur["info"].update(info)
        cur["ts"] = time.time()
        self.turns.append(cur)
        self.cur = None
        return cur

    def stats(self) -> dict:
        out: dict[str, Any] = {"n": len(self.turns), "stages": {}, "voice": {}}
        for scope, turns in (("stages", list(self.turns)), ("voice", [t for t in self.turns if t["source"] == "voice"])):
            for st in STAGES:
                vals = [t["marks"][st] for t in turns if st in t["marks"]]
                if vals:
                    out[scope][st] = {"median": int(statistics.median(vals)), "n": len(vals), "label": LABELS[st]}
        with_tools = [t for t in self.turns if t["info"].get("tools")]
        if with_tools:
            hit = [t for t in with_tools if not t["info"].get("find_tools") and not t["info"].get("use_tool_errors")]
            out["first_try"] = round(100 * len(hit) / len(with_tools))
            out["first_try_n"] = len(with_tools)
        inst = [t for t in self.turns if t["info"].get("instant")]
        out["instant"] = len(inst)
        cat = [t for t in self.turns if t["info"].get("catalog")]
        out["catalog"] = len(cat)
        warms = [n for n in self.notes if n["kind"] == "cache_warm"]
        if warms:
            out["cache_warms"] = len(warms)
        return out


def get(rt) -> Latency:
    lat = getattr(rt, "latency", None)
    if lat is None:
        lat = rt.latency = Latency()
    return lat
