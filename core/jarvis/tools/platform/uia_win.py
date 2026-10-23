"""Windows UI Automation backend (package `uiautomation`, MIT). Every call runs in a worker thread → COM init per call."""
from __future__ import annotations

import threading
import time

from .base import UiNode, norm

_lock = threading.RLock()
_refs: dict[str, object] = {}   # ref → uiautomation Control (valid until the next ui_tree on that window)
_seq = 0


def _auto():
    import uiautomation as auto

    return auto


class _Com:
    """COM must be initialised in each thread that touches UIA."""

    def __enter__(self):
        self._init = _auto().UIAutomationInitializerInThread()
        self._init.__enter__()
        return self

    def __exit__(self, *exc):
        return self._init.__exit__(*exc)


def _title(c) -> str:
    try:
        return c.Name or ""
    except Exception:
        return ""


def _window(window: str):
    auto = _auto()
    if not window:
        fg = auto.GetForegroundControl()
        top = fg.GetTopLevelControl() if fg else None
        return None if top is None or norm(_title(top)).startswith("jarvis") else top
    want = norm(window)
    for w in auto.GetRootControl().GetChildren():
        t = norm(_title(w))
        if t and want in t and not t.startswith("jarvis"):
            return w
    return None


def _node(c, depth: int, win_idx: int) -> UiNode:
    global _seq
    _seq += 1
    ref = f"w{win_idx}:{_seq}"
    _refs[ref] = c
    try:
        r = c.BoundingRectangle
        rect = [r.left, r.top, r.right - r.left, r.bottom - r.top]
    except Exception:
        rect = [0, 0, 0, 0]
    value = None
    try:
        vp = c.GetPattern(_auto().PatternId.ValuePattern)
        if vp:
            value = vp.Value
    except Exception:
        pass
    role = (getattr(c, "ControlTypeName", "") or "").removesuffix("Control")
    return {"ref": ref, "role": role, "name": _title(c), "automation_id": getattr(c, "AutomationId", "") or "",
            "value": value, "enabled": bool(getattr(c, "IsEnabled", True)), "rect": rect, "depth": depth}


def _walk(root, max_depth: int, limit: int, win_idx: int) -> list[UiNode]:
    out: list[UiNode] = []
    stack = [(root, 0)]
    while stack and len(out) < limit:
        c, d = stack.pop(0)
        if d > 0:
            out.append(_node(c, d, win_idx))
        if d < max_depth:
            try:
                stack[0:0] = [(ch, d + 1) for ch in c.GetChildren()]
            except Exception:
                pass
    return out


def ui_tree(window: str = "", depth: int = 4, limit: int = 150) -> list[UiNode]:
    with _lock, _Com():
        w = _window(window)
        if w is None:
            return []
        idx = abs(hash(_title(w))) % 1000
        for k in [k for k in _refs if k.startswith(f"w{idx}:")]:
            del _refs[k]
        return _walk(w, depth, limit, idx)


def _match(c, name: str, role: str, automation_id: str) -> int:
    """0 = no match, 2 = exact name, 1 = name contains."""
    if automation_id and getattr(c, "AutomationId", "") != automation_id:
        return 0
    if role and norm((getattr(c, "ControlTypeName", "") or "").removesuffix("Control")) != norm(role):
        return 0
    if not name:
        return 2
    n, want = norm(_title(c)), norm(name)
    return 2 if n == want else 1 if want and want in n else 0


def ui_find(window: str = "", name: str = "", role: str = "", automation_id: str = "",
            timeout: float = 0.0) -> UiNode | None:
    end = time.monotonic() + max(0.0, timeout)
    with _lock, _Com():
        while True:
            w = _window(window)
            if w is not None:
                best, best_score, stack = None, 0, [(w, 0)]
                while stack:
                    c, d = stack.pop()
                    if d > 0:
                        s = _match(c, name, role, automation_id)
                        if s > best_score:
                            best, best_score = c, s
                            if s == 2:
                                break
                    if d < 14:
                        try:
                            stack.extend((ch, d + 1) for ch in c.GetChildren())
                        except Exception:
                            pass
                if best is not None:
                    return _node(best, 1, abs(hash(_title(w))) % 1000)
            if time.monotonic() >= end:
                return None
            time.sleep(0.3)


def ui_get(ref: str) -> UiNode | None:
    with _lock, _Com():
        c = _refs.get(ref)
        if c is None:
            return None
        try:
            if not c.Exists(0, 0):
                return None
        except Exception:
            return None
        n = _node(c, 1, 0)
        _refs.pop(n["ref"], None)
        n["ref"] = ref
        return n


def ui_act(ref: str, action: str) -> str:
    with _lock, _Com():
        auto = _auto()
        c = _refs.get(ref)
        if c is None:
            raise LookupError("prvek už neexistuje – zavolej znovu ui_inspect")
        P = auto.PatternId
        if action == "invoke":
            for pid, fn in ((P.InvokePattern, "Invoke"), (P.TogglePattern, "Toggle"),
                            (P.SelectionItemPattern, "Select"), (P.ExpandCollapsePattern, "Expand")):
                pat = c.GetPattern(pid)
                if pat:
                    getattr(pat, fn)()
                    return fn.lower()
            c.Click(simulateMove=False)
            return "click"
        if action == "click":
            c.Click(simulateMove=False)
        elif action == "double":
            c.DoubleClick(simulateMove=False)
        elif action == "right":
            c.RightClick(simulateMove=False)
        elif action == "focus":
            c.SetFocus()
        elif action == "expand":
            c.GetExpandCollapsePattern().Expand()
        elif action == "toggle":
            c.GetTogglePattern().Toggle()
        elif action == "select":
            c.GetSelectionItemPattern().Select()
        return action


def ui_set_text(ref: str, text: str) -> None:
    with _lock, _Com():
        auto = _auto()
        c = _refs.get(ref)
        if c is None:
            raise LookupError("prvek už neexistuje – zavolej znovu ui_inspect")
        vp = c.GetPattern(auto.PatternId.ValuePattern)
        if vp and not getattr(vp, "IsReadOnly", False):
            vp.SetValue(text)
            return
        c.SetFocus()
        auto.SendKeys("{Ctrl}a", waitTime=0.05)
        auto.SetClipboardText(text)
        auto.SendKeys("{Ctrl}v", waitTime=0.1)


def ui_read(window: str = "", limit: int = 4000) -> str:
    with _lock, _Com():
        w = _window(window)
        if w is None:
            return ""
        parts: list[str] = []
        for n in _walk(w, 12, 600, 999):
            for s in (n["name"], n["value"]):
                if s and s not in parts[-3:]:
                    parts.append(str(s))
        for k in [k for k in _refs if k.startswith("w999:")]:
            del _refs[k]
        return "\n".join(parts)[:limit]


def ui_state(window: str = "") -> dict:
    with _lock, _Com():
        auto = _auto()
        w = _window(window) or auto.GetForegroundControl()
        f = auto.GetFocusedControl()
        return {"window": _title(w) if w else "", "focused": _title(f) if f else ""}


def selftest() -> dict:
    with _Com():
        auto = _auto()
        wins = [w for w in auto.GetRootControl().GetChildren() if _title(w)][:5]
        if not wins:
            return {"skipped": "žádné okno na ploše (runner bez interaktivní relace?)"}
        nodes = _walk(wins[0], 2, 10, 998)
        return {"window": _title(wins[0]), "windows": [_title(w) for w in wins],
                "nodes": [{k: n[k] for k in ("role", "name")} for n in nodes]}
