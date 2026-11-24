"""3.16 Paměť nástrojů (návrhy 12, 13, 14, 17, 24): JARVIS remembers which tool worked for which words.

- Paměť: every successful request is remembered (the words, the tool, its arguments, the answer). Next time the tools
  that worked for similar words come with the message at once.
- Reflexy: the same words that went well at least twice with the same harmless action (and an answer without
  numbers – "Pouštím lo-fi.", not "Venku je 5 °C") are done right away, without the AI. A correction ("ne, to ne")
  cancels the reflex. Off in Nastavení → Mozek.
- Příklady: for a request like an earlier one, the AI gets how it was done then ("pusť lo-fi" → youtube_play …).
- Podle významu: with the local meaning model (e5-small, downloaded in Paměť) each tool has its vector; the words of a
  message find tools by meaning, not only by shared word stems.
- Podle obrazovky: the app in front adds its own area (VS Code → programming, Blender → 3D, a game → games).
- Zvyky: tools you use at this hour of the day are offered first.
Everything stays in JARVIS's database on this PC; nothing sensitive (passwords, health, bank) is remembered.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("jarvis.toolmind")

SQL = """CREATE TABLE IF NOT EXISTS tool_memory (phrase TEXT, tool TEXT, args TEXT, answer TEXT, ok INTEGER DEFAULT 0,
           bad INTEGER DEFAULT 0, last REAL, PRIMARY KEY (phrase, tool, args));
         CREATE TABLE IF NOT EXISTS tool_uses (tool TEXT, hour INTEGER, ts REAL);"""
REFLEX_MIN = 2
APP_AREAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"visual studio|\bcode\b|vscode|pycharm|intellij|cursor|rider|terminal|powershell|git", ("programování", "kód")),
    (r"blender|fusion|freecad|openscad|prusa|bambu|cura|orca|kicad|sketchup|solidworks", ("design", "dílna", "hardware")),
    (r"arduino|platformio|esp", ("hardware",)),
    (r"steam|epic|riot|valorant|minecraft|roblox|league|counter-strike|cs2|fortnite|unity|godot|unreal", ("hry",)),
    (r"chrome|edge|firefox|opera|brave|vivaldi", ("web", "prohlížeč")),
    (r"word|excel|powerpoint|onenote|libreoffice|notion|obsidian", ("produktivita", "soubory")),
    (r"outlook|thunderbird|gmail|pošta|mail", ("e-mail", "kalendář", "komunikace")),
    (r"spotify|youtube|vlc|obs|premiere|davinci|audacity|resolve|capcut", ("média",)),
    (r"photoshop|figma|illustrator|gimp|affinity|canva|krita", ("design",)),
    (r"discord|whatsapp|telegram|messenger|signal|teams|slack|zoom", ("komunikace", "telefon")),
)


def _db(rt):
    rt.db.conn.executescript(SQL)
    return rt.db


def norm(text: str) -> str:
    import unicodedata

    t = "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))
    t = re.sub(r"\b(prosim|prosimte|jarvisi|jarvis|hej|hey|pane|dik|diky)\b", " ", t)
    t = re.sub(r"[^\w\s%.,:-]", " ", t)
    return re.sub(r"\s+", " ", t).strip(" .,")


def _sensitive(rt, text: str) -> bool:
    try:
        from . import brainplus

        return bool(brainplus.sensitive(text or ""))
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------------------------------ learning
def learn(rt, text: str, calls: list[tuple[str, dict, bool]], answer: str) -> int:
    """After an answer: remember the tools that worked for these words (not for anything sensitive)."""
    if not text or not calls or _sensitive(rt, text):
        return 0
    db = _db(rt)
    key = norm(text)
    now = time.time()
    n = 0
    one = len(calls) == 1
    for name, args, ok in calls:
        if name in ("find_tools", "use_tool"):
            continue
        a = json.dumps(args or {}, ensure_ascii=False, sort_keys=True)[:400]
        db.exec("INSERT OR IGNORE INTO tool_memory (phrase, tool, args, answer, ok, bad, last) VALUES (?,?,?,?,0,0,?)",
                (key, name, a, "", now))
        if ok:
            db.exec("UPDATE tool_memory SET ok=ok+1, last=?, answer=? WHERE phrase=? AND tool=? AND args=?",
                    (now, (answer or "").strip()[:200] if one else "", key, name, a))
            db.exec("INSERT INTO tool_uses (tool, hour, ts) VALUES (?,?,?)", (name, time.localtime(now).tm_hour, now))
        else:
            db.exec("UPDATE tool_memory SET bad=bad+1, last=? WHERE phrase=? AND tool=? AND args=?", (now, key, name, a))
        n += 1
    return n


def punish(rt, text: str) -> int:
    """"Ne, to ne" after an answer: what was done for those words does not become (or stays) a reflex."""
    cur = _db(rt).exec("UPDATE tool_memory SET bad=bad+1 WHERE phrase=?", (norm(text),))
    return int(getattr(cur, "rowcount", 0) or 0)


def reflex(rt, text: str, allowed: set[str]) -> tuple[str, dict, str] | None:
    """(tool, args, answer) to do at once without the AI, or None."""
    if not getattr(rt.cfg.agent, "reflexes", True) or not text or _sensitive(rt, text):
        return None
    from . import tools

    rows = _db(rt).all("SELECT tool, args, answer, ok, bad FROM tool_memory WHERE phrase=? ORDER BY ok DESC", (norm(text),))
    good = [r for r in rows if r["ok"] >= REFLEX_MIN and r["bad"] == 0]
    if len(good) != 1 or any(r["bad"] for r in rows):
        return None
    r = good[0]
    ans = (r["answer"] or "").strip()
    if not ans or len(ans) > 140 or re.search(r"\d", ans):        # an answer with numbers depends on the moment
        return None
    spec = tools.REGISTRY.get(r["tool"])
    if spec is None or r["tool"] not in allowed:
        return None
    args = json.loads(r["args"] or "{}")
    t = rt.cfg.tools
    if tools.is_dangerous(spec, args, t.always_confirm, t.trusted, rt):
        return None
    return r["tool"], args, ans


def examples(rt, text: str, limit: int = 2) -> list[dict]:
    """Earlier requests like this one that went well: [{phrase, tool, args}]."""
    from .tools import select as sel

    q = sel.stems(text)
    if len(q) < 1:
        return []
    rows = _db(rt).all("SELECT phrase, tool, args, ok FROM tool_memory WHERE ok > 0 AND bad = 0 ORDER BY last DESC LIMIT 400")
    scored = []
    key = norm(text)
    for r in rows:
        if r["phrase"] == key:
            s = 1.0
        else:
            w = sel.stems(r["phrase"])
            s = len(q & w) / max(1, len(q | w))
        if s >= 0.34:
            scored.append((s, r["ok"], r))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    out, seen = [], set()
    for _, _, r in scored:
        if r["tool"] in seen:
            continue
        seen.add(r["tool"])
        out.append({"phrase": r["phrase"], "tool": r["tool"], "args": json.loads(r["args"] or "{}")})
        if len(out) >= limit:
            break
    return out


def habits(rt, hour: int | None = None, days: int = 30, limit: int = 3) -> list[str]:
    """Tools used at least 3× around this hour of the day lately."""
    h = time.localtime().tm_hour if hour is None else hour
    near = [(h - 1) % 24, h, (h + 1) % 24]
    rows = _db(rt).all(f"SELECT tool, COUNT(*) AS n FROM tool_uses WHERE ts > ? AND hour IN ({','.join('?' * 3)}) "
                       "GROUP BY tool HAVING n >= 3 ORDER BY n DESC LIMIT ?", (time.time() - days * 86400, *near, limit))
    return [r["tool"] for r in rows]


def screen_areas(rt) -> tuple[str, tuple[str, ...]]:
    """(the app in front, its areas)."""
    try:
        app = str(rt.platform.foreground_app() or "")
    except Exception:  # noqa: BLE001
        app = ""
    a = app.lower()
    for rx, areas in APP_AREAS:
        if a and re.search(rx, a):
            return app, areas
    return app, ()


def screen_tools(rt, registry: dict, text: str, limit: int = 4) -> list[str]:
    """Tools of the front app's areas that fit the words (nothing when no word fits – no noise)."""
    from .tools import select as sel

    _, areas = screen_areas(rt)
    if not areas:
        return []
    found = sel.search(registry, text, 40)
    return [n for n in found if getattr(registry.get(n), "category", "") in areas][:limit]


# ------------------------------------------------------------------------------------------ by meaning (e5-small)
class Semantic:
    """Each tool's vector, made once in the background (and kept on disk) when the meaning model is there."""

    def __init__(self):
        self.names: list[str] = []
        self.mat: Any = None
        self.key = ""
        self.busy = False
        self._lock = threading.Lock()

    @staticmethod
    def _texts(registry: dict) -> tuple[list[str], list[str], str]:
        names = sorted(registry)
        texts = [f"{n.replace('_', ' ')}: {registry[n].description[:300]}" for n in names]
        key = hashlib.sha1("\n".join(texts).encode()).hexdigest()[:16]
        return names, texts, key

    def build(self, registry: dict, folder: Path | None = None) -> bool:
        import numpy as np

        from . import embedder

        if not embedder.ready():
            return False
        names, texts, key = self._texts(registry)
        if key == self.key and self.mat is not None:
            return True
        cache = (folder / f"toolvec-{key}.npy") if folder else None
        mat = None
        if cache and cache.exists():
            try:
                mat = np.load(cache)
            except (OSError, ValueError):
                mat = None
        if mat is None or len(mat) != len(names):
            vecs = embedder.encode(texts, kind="passage")
            mat = np.asarray(vecs, dtype=np.float32)
            mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
            if cache:
                try:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    np.save(cache, mat)
                except OSError:
                    pass
        with self._lock:
            self.names, self.mat, self.key = names, mat, key
        return True

    def build_async(self, registry: dict, folder: Path | None = None) -> None:
        if self.busy or self.mat is not None:
            return
        self.busy = True

        def go() -> None:
            try:
                self.build(registry, folder)
            except Exception as e:  # noqa: BLE001
                log.info("tool vectors: %s", e)
            finally:
                self.busy = False
        threading.Thread(target=go, daemon=True, name="toolvec").start()

    def search(self, text: str, limit: int = 6, min_score: float = 0.80) -> list[str]:
        import numpy as np

        from . import embedder

        if self.mat is None or not text.strip():
            return []
        try:
            q = np.asarray(embedder.encode([text], kind="query")[0], dtype=np.float32)
        except Exception as e:  # noqa: BLE001
            log.debug("tool search by meaning: %s", e)
            return []
        q /= np.linalg.norm(q) + 1e-9
        with self._lock:
            sims = self.mat @ q
            order = np.argsort(-sims)[:limit]
            top = float(sims[order[0]]) if len(order) else 0.0
            return [self.names[i] for i in order if sims[i] >= max(min_score, top - 0.06)]


def semantic(rt) -> Semantic:
    s = getattr(rt, "tool_semantic", None)
    if s is None:
        s = rt.tool_semantic = Semantic()
    return s


# ------------------------------------------------------------------------------------------ together
def suggest(rt, registry: dict, allowed: set[str], text: str, limit: int = 8) -> list[str]:
    """The tools memory, meaning, the screen and habits point to for this message (best first, allowed only)."""
    out: list[str] = []

    def add(names: list[str]) -> None:
        for n in names:
            if n in allowed and n in registry and n not in out and len(out) < limit:
                out.append(n)
    try:
        add([e["tool"] for e in examples(rt, text, 3)])
    except Exception as e:  # noqa: BLE001
        log.debug("memory: %s", e)
    try:
        sem = semantic(rt)
        if sem.mat is None:
            from . import paths

            sem.build_async(registry, paths.sub("cache"))
        add(sem.search(text))
    except Exception as e:  # noqa: BLE001
        log.debug("meaning: %s", e)
    try:
        add(screen_tools(rt, registry, text))
    except Exception as e:  # noqa: BLE001
        log.debug("screen: %s", e)
    try:
        add(habits(rt))
    except Exception as e:  # noqa: BLE001
        log.debug("habits: %s", e)
    return out


def examples_hint(rt, text: str) -> str:
    ex = examples(rt, text, 2)
    if not ex:
        return ""
    lines = [f"- „{e['phrase']}“ → {e['tool']} {json.dumps(e['args'], ensure_ascii=False)[:160]}" for e in ex]
    return "Takhle se ti to dřív povedlo u podobných požadavků (použij stejně, pokud sedí):\n" + "\n".join(lines)
