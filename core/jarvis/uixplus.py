"""OMEGA wave 46: attention-aware notifications and a quiet focus mode (753, 234), a data lens for selected text (759), the
dependency graph of a mission / protocol and its dry-run animation (755, 192), the live map of agents (754), a spatial
window navigator (230) and live captions (790)."""
from __future__ import annotations

import datetime as dt
import math
import re
import time


# ---------------------------------------------------------------- 753 / 234 attention and focus
class Attention:
    """Non-urgent notices wait while you are focused (focus mode, a full-screen game / video, a meeting in the calendar) and
    come afterwards as one short summary. Urgent ones (timers, alarms, things you asked for) always go through."""

    def __init__(self, rt):
        self.rt = rt
        self.focus_until = 0.0
        self.deferred: list[dict] = []

    def focus(self, minutes: float) -> None:
        self.focus_until = time.time() + max(1, min(minutes, 8 * 60)) * 60 if minutes > 0 else 0.0
        self.rt.bus.publish("focus", active=self.focus_until > time.time(), until=self.focus_until)

    def busy_reason(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        if self.focus_until > now:
            return "soustředění"
        if not getattr(getattr(self.rt.cfg, "stark", None), "attention_aware", True):
            return ""
        try:
            info = self.rt.platform.foreground_info() or {}
            if info.get("fullscreen"):
                return "aplikace přes celou obrazovku"
        except Exception:  # noqa: BLE001
            pass
        db = getattr(self.rt, "db", None)
        if db is not None and db.one("SELECT name FROM sqlite_master WHERE name='cal_events'"):
            if db.one("SELECT id FROM cal_events WHERE start <= ? AND end >= ? LIMIT 1", (now, now)):
                return "schůzka v kalendáři"
        return ""

    def gate(self, title: str, body: str, urgent: bool) -> bool:
        """True = show now; False = kept for later."""
        if urgent:
            return True
        why = self.busy_reason()
        if not why:
            return True
        self.deferred.append({"title": title, "body": body, "ts": time.time()})
        self.deferred = self.deferred[-50:]
        self.rt.bus.publish("focus", active=True, until=self.focus_until, waiting=len(self.deferred), why=why)
        return False

    def flush(self, now: float | None = None) -> dict | None:
        if not self.deferred or self.busy_reason(now):
            return None
        items, self.deferred = self.deferred, []
        heads = [i["title"] for i in items]
        body = "; ".join(f"{t}: {b[:80]}" for t, b in ((i["title"], i["body"]) for i in items[:5])) + (f" a dalších {len(items) - 5}" if len(items) > 5 else "")
        self.rt.bus.publish("focus", active=False, until=0, waiting=0)
        return {"title": f"Zatímco jsi byl soustředěný: {len(items)} upozornění", "body": body, "titles": heads}


# ---------------------------------------------------------------- 759 data lens
RATES_CZK = {"eur": 25.3, "€": 25.3, "usd": 23.4, "$": 23.4, "gbp": 29.6, "£": 29.6, "pln": 5.85, "chf": 26.4}
UNITS = {"km": ("mi", 0.621371), "mi": ("km", 1.609344), "kg": ("lb", 2.20462), "lb": ("kg", 0.453592), "cm": ("in", 0.393701),
         "in": ("cm", 2.54), "m": ("ft", 3.28084), "ft": ("m", 0.3048), "l": ("gal", 0.264172), "gal": ("l", 3.78541), "kwh": ("MJ", 3.6),
         "mb": ("GB", 1 / 1024), "gb": ("MB", 1024), "°f": ("°C", None), "°c": ("°F", None)}


def _num(s: str) -> float:
    return float(s.replace(" ", "").replace(" ", "").replace(",", "."))


def lens(text: str, now: dt.date | None = None) -> list[dict]:
    """What is in the selected text, at a glance: money in CZK, other units, days until / since a date, a quick summary of
    a list of numbers, colours, an ICO / IBAN check, word and character counts. No AI, instant."""
    now = now or dt.date.today()
    t = text.strip()
    out: list[dict] = []
    for m in re.finditer(r"(?:(€|\$|£)\s?(\d[\d\s ]*(?:[.,]\d+)?))|(?:(\d[\d\s ]*(?:[.,]\d+)?)\s?(eur|usd|gbp|pln|chf|€|\$|£)\b)", t, re.I):
        sym = (m.group(1) or m.group(4)).lower()
        val = _num(m.group(2) or m.group(3))
        out.append({"kind": "měna", "text": m.group(0).strip(), "value": f"≈ {val * RATES_CZK[sym]:,.0f} Kč".replace(",", " "), "note": "orientační kurz"})
    for m in re.finditer(r"(-?\d+(?:[.,]\d+)?)\s?(km|mi|kg|lb|cm|in|m|ft|l|gal|kwh|mb|gb|°f|°c)\b", t, re.I):
        unit = m.group(2).lower()
        v = _num(m.group(1))
        to, k = UNITS[unit]
        conv = (v - 32) * 5 / 9 if unit == "°f" else v * 9 / 5 + 32 if unit == "°c" else v * k
        out.append({"kind": "jednotky", "text": m.group(0), "value": f"{conv:.4g} {to}"})
    for m in re.finditer(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b", t):
        try:
            d = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m.group(1) else dt.date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        except ValueError:
            continue
        diff = (d - now).days
        out.append({"kind": "datum", "text": m.group(0), "value": ("dnes" if diff == 0 else f"za {diff} dní" if diff > 0 else f"před {-diff} dny")
                    + f" ({['po', 'út', 'st', 'čt', 'pá', 'so', 'ne'][d.weekday()]})"})
    nums = [_num(x) for x in re.findall(r"(?<![\w.,])-?\d+(?:[.,]\d+)?(?![\w.,]?\d)", t.replace(" ", " "))]
    lines = [ln for ln in t.splitlines() if ln.strip()]
    if len(nums) >= 3 and (len(lines) >= 3 or "\t" in t or ";" in t):
        out.append({"kind": "čísla", "text": f"{len(nums)} čísel", "value": f"součet {sum(nums):g}, průměr {sum(nums) / len(nums):.4g}, min {min(nums):g}, max {max(nums):g}"})
    for m in re.finditer(r"#[0-9a-fA-F]{6}\b", t):
        from .design import contrast_report

        c = m.group(0)
        out.append({"kind": "barva", "text": c, "value": f"kontrast s bílou {contrast_report(c, '#ffffff')['ratio']}:1, s černou {contrast_report(c, '#000000')['ratio']}:1", "color": c})
    for m in re.finditer(r"\bIČO?:?\s*(\d{8})\b", t):
        d = m.group(1)
        s = sum(int(d[i]) * (8 - i) for i in range(7))
        ok = (11 - s % 11) % 10 == int(d[7])
        out.append({"kind": "IČO", "text": d, "value": "kontrolní číslice sedí" if ok else "NEPLATNÉ (kontrolní číslice nesedí)"})
    for m in re.finditer(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?)\b", t):
        raw = m.group(1).replace(" ", "")
        num = "".join(str(int(ch, 36)) for ch in raw[4:] + raw[:4])
        out.append({"kind": "IBAN", "text": raw, "value": "platný" if int(num) % 97 == 1 else "NEPLATNÝ"})
    words = len(re.findall(r"\w+", t))
    if words >= 12:
        out.append({"kind": "text", "text": f"{words} slov", "value": f"{len(t)} znaků, čtení ~{max(1, round(words / 200))} min"})
    return out[:12]


# ---------------------------------------------------------------- 755 / 192 mission dependency graph
def step_layers(steps: list[dict]) -> dict:
    """Protocol steps with `needs` (indices of steps that must finish first) → layers that can run together, edges and any
    cycle or broken reference. Steps without `needs` follow the previous step (like the runner)."""
    n = len(steps)
    deps: list[list[int]] = []
    problems = []
    for i, st in enumerate(steps):
        need = st.get("needs")
        if need is None or need == []:
            d = [i - 1] if i and not any(s.get("needs") for s in steps) else []
        else:
            d = [j for j in need if isinstance(j, int)]
            for j in d:
                if not 0 <= j < n or j == i:
                    problems.append(f"Krok {i + 1} čeká na neexistující krok {j + 1}.")
            d = [j for j in d if 0 <= j < n and j != i]
        deps.append(d)
    level = [-1] * n
    visiting = set()

    def depth(i: int) -> int:
        if level[i] >= 0:
            return level[i]
        if i in visiting:
            problems.append(f"Kroky se navzájem čekají (smyčka u kroku {i + 1}).")
            return 0
        visiting.add(i)
        level[i] = 1 + max((depth(j) for j in deps[i]), default=-1)
        visiting.discard(i)
        return level[i]
    for i in range(n):
        depth(i)
    layers: list[list[int]] = []
    for i, lv in enumerate(level):
        while len(layers) <= lv:
            layers.append([])
        layers[lv].append(i)
    edges = [{"from": j, "to": i} for i in range(n) for j in deps[i]]
    return {"layers": layers, "edges": edges, "problems": sorted(set(problems)), "parallel": max((len(x) for x in layers), default=0)}


EST = {"web_search": 6, "fetch_page": 5, "deep_research": 120, "open_app": 3, "send_email": 4, "read_text_file": 1}


def simulate(steps: list[dict], describe, dangerous, perm_of) -> list[dict]:
    """A dry run: what each step would do, whether it asks first, which permission it uses, roughly how long it takes."""
    out = []
    for i, st in enumerate(steps):
        if st.get("tool"):
            label = describe(st["tool"], st.get("args") or {})
            out.append({"n": i, "label": label, "kind": "nástroj", "asks": bool(dangerous(st["tool"], st.get("args") or {})),
                        "perm": perm_of(st["tool"]), "seconds": EST.get(st["tool"], 3)})
        elif st.get("ask"):
            out.append({"n": i, "label": f"AI: {st['ask'][:80]}", "kind": "úkol pro AI", "asks": False, "perm": "", "seconds": 20})
        else:
            out.append({"n": i, "label": f"Řekne: {st.get('say', '')[:80]}", "kind": "řeč", "asks": False, "perm": "", "seconds": 2})
    return out


def critical_seconds(sim: list[dict], graph: dict) -> int:
    """Total time when independent steps run together (longest path through the layers)."""
    finish: dict[int, float] = {}
    deps: dict[int, list[int]] = {}
    for e in graph["edges"]:
        deps.setdefault(e["to"], []).append(e["from"])
    for layer in graph["layers"]:
        for i in layer:
            finish[i] = max((finish.get(j, 0) for j in deps.get(i, [])), default=0) + sim[i]["seconds"]
    return round(max(finish.values(), default=0))


# ---------------------------------------------------------------- 230 spatial window navigator
def window_map(wins: list[dict], screen: tuple[int, int]) -> list[dict]:
    """Windows as boxes scaled to a 0–1 map of the screen (minimised ones left out)."""
    W, H = screen
    out = []
    for w in wins:
        if w.get("state") == "minimized" or w.get("w", 0) <= 0 or w.get("h", 0) <= 0:
            continue
        out.append({"hwnd": w["hwnd"], "title": (w.get("title") or "")[:60], "app": w.get("app", ""), "x": round(w["x"] / W, 4), "y": round(w["y"] / H, 4),
                    "w": round(w["w"] / W, 4), "h": round(w["h"] / H, 4)})
    return out


def neighbour(wins: list[dict], current: int, direction: str) -> dict | None:
    """The window in that direction (left / right / up / down) from the current one: nearest centre within a 90° cone."""
    cur = next((w for w in wins if w["hwnd"] == current), None)
    if not cur:
        return wins[0] if wins else None
    cx, cy = cur["x"] + cur["w"] / 2, cur["y"] + cur["h"] / 2
    vec = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}[direction]
    best, score = None, math.inf
    for w in wins:
        if w["hwnd"] == current:
            continue
        dx, dy = w["x"] + w["w"] / 2 - cx, w["y"] + w["h"] / 2 - cy
        along = dx * vec[0] + dy * vec[1]
        across = abs(dx * vec[1] - dy * vec[0])
        if along <= 0 or across > along:
            continue
        s = along + 2 * across
        if s < score:
            best, score = w, s
    return best


# ---------------------------------------------------------------- 790 live captions
def caption_chunks(text: str, max_chars: int = 84) -> list[str]:
    """Spoken text → caption lines (sentence first, then by words), never cutting a word."""
    out = []
    for sent in re.split(r"(?<=[.!?…])\s+", " ".join(text.split())):
        line = ""
        for w in sent.split(" "):
            if line and len(line) + 1 + len(w) > max_chars:
                out.append(line)
                line = w
            else:
                line = f"{line} {w}".strip()
        if line:
            out.append(line)
    return out


def caption_timing(chunks: list[str], chars_per_s: float = 14.0) -> list[dict]:
    t, out = 0.0, []
    for c in chunks:
        d = max(1.2, len(c) / chars_per_s)
        out.append({"text": c, "at": round(t, 2), "duration": round(d, 2)})
        t += d
    return out


