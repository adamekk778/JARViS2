"""Omega Brain (catalogue 004 / 008 / 009).

* 009 dynamic priorities – the mission queue is ordered by a score that moves with time: how urgent the deadline is,
  how important the task sounds or was marked, how long it has waited (nothing starves), whether it fits what you
  work on now. Every score comes with its reasons in plain Czech.
* 008 error prediction – before a plan runs: steps that cannot work (an unknown tool, a missing file, a switched-off
  permission, an integration that is not set up, no internet), steps that often failed before (from the action log),
  and steps that will ask for confirmation.
* 004 the problem solver – several genuinely different approaches; for code each one is tried against the project's
  tests in its own throw-away copy (intelplus.improve_loop), otherwise each plan is checked by the error predictor
  and scored; the best one wins and the comparison is shown. Nothing is applied without the user."""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 009 dynamic priorities
IMPORTANCE = {"vysoká": 30, "normální": 10, "nízká": 0}


def priority_score(item: dict, now: float | None = None, focus: str = "") -> tuple[float, list[str]]:
    """How soon this queued mission should run, and why."""
    from .bizops import priority_of

    now = now or time.time()
    score, why = 0.0, []
    nb = item.get("not_before")
    if nb and nb > now:
        return -1e6, [f"čeká do {time.strftime('%H:%M', time.localtime(nb))}"]
    level = item.get("priority") or priority_of(item.get("goal", ""))
    score += IMPORTANCE.get(level, 10)
    if level == "vysoká":
        why.append("důležité")
    dl = item.get("deadline")
    if dl:
        hours = (dl - now) / 3600
        if hours <= 0:
            score += 100
            why.append("termín už vypršel")
        elif hours <= 1:
            score += 80
            why.append(f"termín za {max(1, round(hours * 60))} min")
        elif hours <= 4:
            score += 60
            why.append(f"termín za {hours:.0f} h")
        elif hours <= 24:
            score += 40
            why.append("termín dnes nebo zítra")
        elif hours <= 72:
            score += 20
            why.append("termín do tří dnů")
    waited = (now - (item.get("created") or now)) / 3600
    if waited >= 0.5:                                         # aging: whatever waits long enough moves up
        score += min(25, waited * 2.5)
        why.append(f"čeká {waited:.0f} h" if waited >= 1 else "čeká půl hodiny")
    words = {w for w in re.findall(r"\w{4,}", (focus or "").lower())}
    if words and words & set(re.findall(r"\w{4,}", item.get("goal", "").lower())):
        score += 10
        why.append("souvisí s tím, na čem právě děláš")
    fails = int(item.get("failures") or 0)
    if fails:
        score -= 5 * fails
        why.append(f"{fails}× se nepovedla")
    return round(score, 1), why or ["běžné pořadí"]


def rank(items: list[dict], now: float | None = None, focus: str = "") -> list[dict]:
    out = []
    for it in items:
        s, why = priority_score(it, now, focus)
        out.append({**it, "score": s, "why": why})
    return sorted(out, key=lambda x: (-x["score"], x.get("created") or 0))


# ---------------------------------------------------------------- 008 error prediction
PATH_KEYS = ("path", "file", "src", "source", "folder", "directory", "dir", "input", "image")
WRITE_HINTS = ("write", "save", "create", "move", "copy", "rename", "delete", "organize", "export", "download")
KEYWORDS: list[tuple[str, str]] = [
    (r"st[aá]hn|download|web|internet|vyhledej|najdi na", "network"),
    (r"e-?mail|po[sš]t|napi[sš] mail", "mail"),
    (r"sv[eě]tl|topen|termostat|z[aá]suvk|[zž]aluzi", "home"),
    (r"zavolej|sms|whatsapp|telefon", "phone"),
]


def _online() -> bool:
    import socket

    try:
        socket.create_connection(("1.1.1.1", 53), timeout=1.5).close()
        return True
    except OSError:
        return False


def _failure_stats(rt, days: int = 30) -> dict[str, dict]:
    since = time.time() - days * 86400
    out: dict[str, dict] = {}
    try:
        rows = rt.db.all("SELECT tool, ok, summary FROM task_actions WHERE ts>=? ORDER BY ts", (since,))
    except Exception:
        return out
    for r in rows:
        s = out.setdefault(r["tool"], {"n": 0, "bad": 0, "last_error": ""})
        s["n"] += 1
        if not r["ok"]:
            s["bad"] += 1
            s["last_error"] = (r["summary"] or "")[:160]
    return out


def _integration(rt, need: str) -> str | None:
    """None when it is ready, else what to do."""
    if need == "mail" and not rt.cfg.mail.accounts:
        return "nemáš přidaný e-mailový účet (Nastavení → E-mail)"
    if need == "home" and not rt.cfg.home.url:
        return "není propojený Home Assistant (Nastavení → Domácnost)"
    if need == "phone":
        ph = getattr(rt, "phone", None)
        if not (ph and ph.link_alive()) and not any(c.get("client") == "mobile" for c in getattr(rt, "clients", {}).values()):
            return "telefon s JARVISem teď není připojený"
    return None


def predict_errors(rt, steps: list[Any], online: bool | None = None) -> list[dict]:
    """Each step is {"tool", "args"} or a plain sentence. Returns findings: level blok / riziko / info."""
    from . import permissions, tools

    stats = _failure_stats(rt)
    out: list[dict] = []
    net_checked: bool | None = online

    def add(i, level, text, fix=""):
        out.append({"step": i, "level": level, "text": text, "fix": fix})

    def need_net(i):
        nonlocal net_checked
        if net_checked is None:
            net_checked = _online()
        if not net_checked:
            add(i, "riziko", "PC teď není připojené k internetu", "připoj se, nebo misi naplánuj na později")

    for i, st in enumerate(steps):
        if isinstance(st, str):
            low = st.lower()
            for pat, need in KEYWORDS:
                if re.search(pat, low):
                    if need == "network":
                        need_net(i)
                    elif (why := _integration(rt, need)):
                        add(i, "blok", why, "nastav to, nebo krok vynech")
            continue
        name, args = st.get("tool", ""), st.get("args") or {}
        spec = tools.REGISTRY.get(name)
        if spec is None:
            add(i, "blok", f"nástroj „{name}“ neexistuje")
            continue
        blocked = permissions.blocked_by(rt.cfg, spec)
        if blocked:
            add(i, "blok", f"oblast oprávnění „{blocked}“ je vypnutá", "zapni ji v Nastavení → Oprávnění")
        for k in PATH_KEYS:
            v = args.get(k)
            if not isinstance(v, str) or not v.strip() or "://" in v:
                continue
            p = Path(v).expanduser()
            writes = any(w in name for w in WRITE_HINTS) and k not in ("src", "source", "input")
            if writes:
                if not p.parent.exists():
                    add(i, "blok", f"složka {p.parent} neexistuje")
                else:
                    try:
                        free = shutil.disk_usage(p.parent).free
                        if free < 1 << 30:
                            add(i, "riziko", f"na disku zbývá jen {free / 2**30:.1f} GB", "uvolni místo")
                    except OSError:
                        pass
            elif not p.exists():
                add(i, "blok", f"{p} neexistuje", "zkontroluj cestu")
        perm = permissions.perm_of(spec)
        if perm == "network" or spec.category in ("web", "prohlížeč"):
            need_net(i)
        need = {"e-mail": "mail", "domácnost": "home", "telefon": "phone"}.get(spec.category)
        if need and (why := _integration(rt, need)):
            add(i, "blok", why, "nastav to, nebo krok vynech")
        if tools.is_dangerous(spec, args, ctx=rt):
            add(i, "info", f"{name} se před provedením zeptá na potvrzení")
        s = stats.get(name)
        if s and s["n"] >= 3 and s["bad"] / s["n"] >= 0.4:
            add(i, "riziko", f"{name} se v posledních 30 dnech nepovedl {s['bad']}× z {s['n']}"
                + (f" (naposledy: {s['last_error']})" if s["last_error"] else ""))
    return out


def summarize(findings: list[dict]) -> str:
    if not findings:
        return "Nevidím nic, co by mělo selhat."
    icon = {"blok": "⛔", "riziko": "⚠", "info": "ℹ"}
    return "\n".join(f"{icon.get(f['level'], '•')} krok {f['step'] + 1}: {f['text']}" + (f" → {f['fix']}" if f["fix"] else "")
                     for f in findings)


# ---------------------------------------------------------------- 004 several solutions, the best one wins
def _json(text: str) -> Any:
    m = re.search(r"\[.*\]|\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("AI nevrátila seznam")
    return json.loads(m.group(0))


async def approaches(rt, problem: str, n: int = 3) -> list[dict]:
    prompt = (f"Problém: {problem}\n\nNavrhni {n} OPRAVDU RŮZNÉ přístupy, jak ho vyřešit (ne varianty jednoho). "
              "Vrať jen JSON pole objektů {\"name\": krátký název, \"idea\": jedna věta, \"steps\": [krátké kroky česky]}.")
    data = _json(await rt.router.complete([{"role": "user", "content": prompt}]))
    out = [d for d in data if isinstance(d, dict) and d.get("name")][:n]
    if not out:
        raise ValueError("AI nenavrhla žádný přístup")
    return out


async def judge(rt, problem: str, cand: dict, findings: list[dict]) -> dict:
    """Feasibility / risk / effort 1–10 from the AI, then the error predictor's findings count against it."""
    prompt = (f"Problém: {problem}\nPřístup: {cand['name']} – {cand.get('idea', '')}\nKroky: {cand.get('steps')}\n"
              f"Zjištěná rizika: {summarize(findings)}\n\nOhodnoť střízlivě. Vrať jen JSON "
              "{\"feasibility\": 1-10, \"risk\": 1-10, \"effort\": 1-10, \"why\": jedna věta}.")
    try:
        j = _json(await rt.router.complete([{"role": "user", "content": prompt}]))
    except Exception:
        j = {"feasibility": 5, "risk": 5, "effort": 5, "why": "AI hodnocení nedodala"}
    blocks = sum(f["level"] == "blok" for f in findings)
    risks = sum(f["level"] == "riziko" for f in findings)
    score = (float(j.get("feasibility", 5)) * 2 - float(j.get("risk", 5)) - float(j.get("effort", 5)) * 0.5
             - 6 * blocks - 2 * risks)
    return {**cand, "findings": findings, "rating": j, "score": round(score, 1)}


async def solve_plans(rt, problem: str, n: int = 3) -> dict:
    cands = await approaches(rt, problem, n)
    rated = [await judge(rt, problem, c, predict_errors(rt, c.get("steps") or [])) for c in cands]
    rated.sort(key=lambda c: -c["score"])
    return {"mode": "plány", "best": rated[0], "candidates": rated}


async def solve_code(rt, problem: str, root: Path, test_cmd: str, files: list[str], n: int = 3, runner=None) -> dict:
    """Each approach gets its own throw-away copy and the tests decide; the original project is never touched."""
    from . import intelplus

    cands = await approaches(rt, problem, n)
    results = []
    for c in cands:
        async def propose(current: dict, output: str, rnd: int, c=c) -> dict:
            prompt = (f"Problém: {problem}\nPřístup, který máš použít: {c['name']} – {c.get('idea', '')}\n"
                      f"Výstup testů:\n{output[-2500:]}\n\nSoubory:\n"
                      + "\n".join(f"=== {f} ===\n{t}" for f, t in current.items())
                      + "\n\nVrať jen JSON {\"cesta\": \"celý nový obsah souboru\"} pro soubory, které měníš. Testy neměň.")
            try:
                return _json(await rt.router.complete([{"role": "user", "content": prompt}]))
            except Exception:
                return {}

        kw = {"runner": runner} if runner else {}
        r = await intelplus.improve_loop(root, test_cmd, files, propose, max_rounds=3, **kw)
        changed = sum(1 for ln in r["diff"].splitlines() if ln[:1] in "+-" and ln[:3] not in ("+++", "---"))
        results.append({**c, "ok": r["ok"], "rounds": r["rounds"], "diff": r["diff"], "files": r["files"],
                        "changed_lines": changed, "score": (100 if r["ok"] else 0) - 5 * r["rounds"] - changed * 0.2})
    results.sort(key=lambda c: -c["score"])
    return {"mode": "kód", "best": results[0], "candidates": results, "solved": results[0]["ok"]}
