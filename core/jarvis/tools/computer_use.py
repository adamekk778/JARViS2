"""Computer use: JARVIS looks at the screen and drives mouse + keyboard until the task is done."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import re
from typing import Annotated

from .base import ToolResult, tool

MAX_STEPS = 30
SYSTEM = """Ovládáš Windows počítač uživatele pomocí myši a klávesnice. Dostaneš úkol a aktuální snímek obrazovky
(rozlišení {w}×{h} px, souřadnice 0,0 vlevo nahoře). Odpověz VŽDY jen jedním JSON objektem s další akcí, nic jiného:
{{"action":"click","x":123,"y":456,"button":"left","double":false,"why":"..."}}
{{"action":"type","text":"...","why":"..."}}          (napíše text do aktivního prvku)
{{"action":"key","keys":["ctrl","l"],"why":"..."}}   (klávesová zkratka; Enter = ["enter"], Windows = ["win"])
{{"action":"scroll","dy":-5,"why":"..."}}            (záporné = dolů)
{{"action":"wait","seconds":2,"why":"..."}}
{{"action":"ui_click","target":"název prvku nebo <ref>","why":"..."}}   (klik přes UI Automation – PREFERUJ)
{{"action":"ui_type","target":"název pole nebo <ref>","text":"...","why":"..."}}
{{"action":"done","summary":"co se povedlo"}}
{{"action":"fail","reason":"proč to nejde"}}
Postupuj po malých krocích, po každé akci dostaneš nový snímek. Klikej doprostřed prvků. Nedělej nic, co úkol nevyžaduje.
Preferuj prvky ze stromu (ui_click/ui_type); souřadnice jen když prvek ve stromu není."""


def _ui_context(p) -> str:
    try:
        from .uia import tree_text

        nodes = p.ui_tree("", 3, 80)
    except Exception:
        return ""
    return ("\nPrvky okna v popředí (UI Automation):\n" + tree_text(nodes)) if nodes else ""


def parse_action(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"model nevrátil JSON: {text[:200]}")
    raw = m.group(0)
    try:
        return json.loads(raw)
    except ValueError:
        # first balanced object
        depth = 0
        for i, ch in enumerate(raw):
            depth += ch == "{"
            depth -= ch == "}"
            if depth == 0:
                return json.loads(raw[: i + 1])
        raise


def _shrink(png: bytes, max_w: int = 1280) -> tuple[str, float]:
    from PIL import Image

    im = Image.open(io.BytesIO(png)).convert("RGB")
    scale = min(1.0, max_w / im.width)
    if scale < 1:
        im = im.resize((int(im.width * scale), int(im.height * scale)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), scale


async def run_computer_task(ctx, task: str, max_steps: int = MAX_STEPS) -> ToolResult:
    p = ctx.platform
    history: list[str] = []
    for step in range(1, max_steps + 1):
        from .screenshot import capturing

        with capturing(ctx, "computer_use"):
            png = await asyncio.to_thread(p.screenshot)
        ui = await asyncio.to_thread(_ui_context, p)
        url, scale = await asyncio.to_thread(_shrink, png)
        sw, sh = p.screen_size()
        w, h = int(sw * scale), int(sh * scale)
        msgs = [{"role": "system", "content": SYSTEM.format(w=w, h=h)},
                {"role": "user", "content": [
                    {"type": "text", "text": f"Úkol: {task}\nDosavadní kroky:\n" + ("\n".join(history[-12:]) or "(žádné)")
                     + ui + "\nJaká je další akce?"},
                    {"type": "image_url", "image_url": {"url": url}}]}]
        reply = await ctx.router.complete(msgs, need_vision=True)
        try:
            a = parse_action(reply)
        except Exception as e:
            history.append(f"{step}. (neplatná odpověď: {e})")
            continue
        act = a.get("action")
        ctx.bus.publish("task_progress", id="computer_use", title=task, step=step, total=max_steps,
                        done=act in ("done", "fail"), detail=a.get("why") or a.get("summary") or act)
        if act == "done":
            return ToolResult(True, a.get("summary", "Hotovo"), data={"steps": step})
        if act == "fail":
            return ToolResult(False, a.get("reason", "Nepovedlo se"), data={"steps": step})
        X = lambda v: int(round(float(v) / scale))  # noqa: E731
        if act == "click":
            await asyncio.to_thread(p.click, X(a["x"]), X(a["y"]), a.get("button", "left"), bool(a.get("double")))
        elif act == "type":
            await asyncio.to_thread(p.type_text, str(a.get("text", "")))
        elif act == "key":
            await asyncio.to_thread(p.hotkey, [str(k) for k in a.get("keys", [])])
        elif act == "scroll":
            await asyncio.to_thread(p.scroll, int(a.get("dy", -3)) * 120)
        elif act in ("ui_click", "ui_type"):
            from .uia import _own, ui_click, ui_type

            if _own(str(a.get("window", ""))):
                history.append(f"{step}. (do oken JARVIS neklikám)")
                continue
            r = await (ui_click(ctx, str(a.get("target", ""))) if act == "ui_click"
                       else ui_type(ctx, str(a.get("target", "")), str(a.get("text", ""))))
            history.append(f"{step}. {act} {a.get('target')!r} → {r.summary}")
            await asyncio.sleep(0.4)
            continue
        elif act == "wait":
            await asyncio.sleep(min(10, float(a.get("seconds", 1))))
        history.append(f"{step}. {json.dumps(a, ensure_ascii=False)}")
        await asyncio.sleep(0.6)
    return ToolResult(False, f"Úkol nedokončen po {max_steps} krocích", data={"history": history[-10:]})


@tool("computer_use", "Ovládne počítač jako člověk (vidí obrazovku, kliká, píše) a splní úkol, na který není jiný nástroj, "
      "např. 'v Excelu udělej graf z otevřené tabulky' nebo 'v nastavení Windows zapni noční světlo'.",
      danger=True, category="ovládání počítače")
async def computer_use(ctx, task: Annotated[str, "co přesně udělat"]) -> ToolResult:
    if not (ctx.cfg.permissions.input and ctx.cfg.permissions.screen):
        return ToolResult(False, "Ovládání počítače potřebuje oprávnění Myš/klávesnice i Obrazovka (Nastavení → Oprávnění).")
    return await run_computer_task(ctx, task)
