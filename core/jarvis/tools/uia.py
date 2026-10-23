"""Windows UI Automation tools (spec §3.2): find buttons and fields by name instead of guessing coordinates."""
from __future__ import annotations

import asyncio
import re
import time
from typing import Annotated, Literal

from .base import ToolResult, tool
from .platform.base import norm

REF = re.compile(r"^w\d+:\d+$")
# Word prefixes that make a click/typing action risky (delete, send, buy, pay, install, format…).
RISKY = ("smaz", "odstran", "delete", "remove", "odesl", "send", "koup", "buy", "zaplat", "pay", "objedn",
         "instal", "format")


def _risky(args: dict, ctx=None) -> bool:
    target = str(args.get("target", ""))
    if REF.match(target.strip()):
        # a ref (from ui_inspect) says nothing by itself → judge the element it points to
        node = None
        try:
            node = ctx.platform.ui_get(target.strip()) if ctx is not None else None
        except Exception:
            pass
        if node is None:
            return True  # unknown element: better ask
        target = f"{node.get('name', '')} {node.get('automation_id', '')}"
    words = re.findall(r"\w+", norm(f"{target} {args.get('window', '')}"))
    return any(w.startswith(p) for w in words for p in RISKY)


def _own(window: str) -> bool:
    return norm(window).startswith("jarvis")


OWN = ToolResult(False, "Do vlastních oken JARVIS neklikám.")


def _node_line(n: dict) -> str:
    v = f" = {n['value']!r}" if n.get("value") not in (None, "") else ""
    off = "" if n.get("enabled", True) else " (neaktivní)"
    return f"{'  ' * max(0, n.get('depth', 1) - 1)}[{n.get('role', '?')}] {n.get('name') or '(bez názvu)'}{v}{off} <{n['ref']}>"


def tree_text(nodes: list[dict]) -> str:
    return "\n".join(_node_line(n) for n in nodes)


async def _resolve(ctx, target: str, window: str):
    p = ctx.platform
    if REF.match(target.strip()):
        return await asyncio.to_thread(p.ui_get, target.strip())
    return await asyncio.to_thread(p.ui_find, window, target, "", "", 2.0)


@tool("ui_inspect", "Vypíše ovládací prvky okna (tlačítka, pole, nabídky) i s jejich ref, aby šly použít v ui_click/ui_type. "
      "window = část titulku okna, prázdné = okno v popředí.", category="obrazovka", perm="screen")
async def ui_inspect(ctx, window: str = "", depth: int = 4) -> ToolResult:
    if _own(window):
        return OWN
    nodes = await asyncio.to_thread(ctx.platform.ui_tree, window, max(1, min(depth, 8)), 150)
    if not nodes:
        return ToolResult(False, f"Okno „{window or 'v popředí'}“ jsem nenašel nebo nemá čitelné prvky.")
    return ToolResult(True, f"{len(nodes)} prvků:\n" + tree_text(nodes), data=nodes)


@tool("ui_click", "Klikne na tlačítko/položku v aplikaci podle názvu nebo ref (z ui_inspect). Spolehlivější než klikání "
      "na souřadnice. action: invoke (výchozí), click, double, right, focus, expand, toggle, select.",
      category="ovládání počítače", perm="input", danger_if=_risky)
async def ui_click(ctx, target: Annotated[str, "název prvku nebo ref"], window: str = "",
                   action: Literal["invoke", "click", "double", "right", "focus", "expand", "toggle", "select"] = "invoke"
                   ) -> ToolResult:
    if _own(window):
        return OWN
    node = await _resolve(ctx, target, window)
    if not node:
        return ToolResult(False, f"Nenašel jsem prvek „{target}“ v okně „{window or 'v popředí'}“. Zkus ui_inspect.")
    p = ctx.platform
    try:
        how = await asyncio.to_thread(p.ui_act, node["ref"], action)
    except Exception as e:
        return ToolResult(False, f"Kliknutí na „{node.get('name')}“ selhalo: {e}")
    await asyncio.sleep(0.3)
    state = await asyncio.to_thread(p.ui_state, window)
    still = await asyncio.to_thread(p.ui_get, node["ref"])
    data = {"verified": True, "window": state.get("window", ""), "focused": state.get("focused", ""),
            "value": None, "exists": still is not None, "method": how}
    return ToolResult(True, f"Kliknuto na „{node.get('name')}“ ({how}); okno: {data['window']}", data=data)


@tool("ui_type", "Napíše text do pole v aplikaci (podle názvu nebo ref) a ověří, že tam je. submit=true stiskne Enter.",
      category="ovládání počítače", perm="input", danger_if=_risky)
async def ui_type(ctx, target: Annotated[str, "název pole nebo ref"], text: str, window: str = "",
                  submit: bool = False) -> ToolResult:
    if _own(window):
        return OWN
    node = await _resolve(ctx, target, window)
    if not node:
        return ToolResult(False, f"Nenašel jsem pole „{target}“. Zkus ui_inspect.")
    p = ctx.platform
    try:
        await asyncio.to_thread(p.ui_set_text, node["ref"], text)
        if submit:
            await asyncio.to_thread(p.hotkey, ["enter"])
    except Exception as e:
        return ToolResult(False, f"Psaní do „{node.get('name')}“ selhalo: {e}")
    after = await asyncio.to_thread(p.ui_get, node["ref"])
    value = after.get("value") if after else None
    state = await asyncio.to_thread(p.ui_state, window)
    verified = value is None or text in str(value)
    data = {"verified": verified, "window": state.get("window", ""), "focused": state.get("focused", ""), "value": value}
    msg = f"Napsáno do „{node.get('name')}“" + ("" if verified else f" – ale pole teď obsahuje {value!r}")
    return ToolResult(verified, msg, data=data)


@tool("ui_wait", "Počká, až se v okně objeví prvek s daným názvem (např. po načtení dialogu).",
      category="obrazovka", perm="screen")
async def ui_wait(ctx, name: str, window: str = "", timeout: float = 10) -> ToolResult:
    t0 = time.monotonic()
    node = await asyncio.to_thread(ctx.platform.ui_find, window, name, "", "", max(0.0, min(float(timeout), 60.0)))
    if not node:
        return ToolResult(False, f"Prvek „{name}“ se do {timeout:.0f} s neobjevil.")
    return ToolResult(True, f"„{node.get('name')}“ je k dispozici ({time.monotonic() - t0:.1f} s)", data=node)


@tool("ui_read", "Přečte viditelný text okna (bez snímku obrazovky).", category="obrazovka", perm="screen")
async def ui_read(ctx, window: str = "") -> ToolResult:
    if _own(window):
        return OWN
    text = await asyncio.to_thread(ctx.platform.ui_read, window, 4000)
    return ToolResult(bool(text), text or "V okně jsem nenašel žádný text.")


@tool("mouse", "Myš: click, double, right (klik na x,y), scroll (amount: záporné = dolů), drag (z x,y na x2,y2), move.",
      category="ovládání počítače", perm="input")
async def mouse(ctx, action: Literal["click", "double", "right", "scroll", "drag", "move"], x: int = 0, y: int = 0,
                x2: int | None = None, y2: int | None = None, amount: int = 0) -> ToolResult:
    p = ctx.platform
    if action in ("click", "double", "right"):
        await asyncio.to_thread(p.click, x, y, "right" if action == "right" else "left", action == "double")
    elif action == "scroll":
        if x or y:
            await asyncio.to_thread(p.move, x, y)
        await asyncio.to_thread(p.scroll, int(amount or -3) * 120)
    elif action == "drag":
        if x2 is None or y2 is None:
            return ToolResult(False, "Pro drag chybí x2, y2")
        await asyncio.to_thread(p.drag, x, y, x2, y2)
    else:
        await asyncio.to_thread(p.move, x, y)
    return ToolResult(True, f"Myš: {action}")
