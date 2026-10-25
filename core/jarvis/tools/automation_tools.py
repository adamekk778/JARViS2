"""3.5 "Když … tak …" by voice: "když otevřu Spotify, ztlum zvuk na 30", "když mi napíše máma, řekni mi to nahlas"."""
from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal

from .base import ToolResult, tool

Trigger = Literal["time", "boot", "app_open", "app_close", "mail", "phone_message", "phone_call", "battery", "power",
                  "away", "back"]


def _steps(say: str, ask: str, protocol: str) -> list:
    from ..config import ProtocolStep

    out = []
    if protocol:
        out.append(ProtocolStep(tool="run_protocol", args={"name": protocol}))
    if say:
        out.append(ProtocolStep(say=say))
    if ask:
        out.append(ProtocolStep(ask=ask))
    return out


def _build(a: dict):
    from ..config import AutoTrigger, Automation

    days = [int(d) for d in (a.get("days") or []) if str(d).lstrip("-").isdigit() and 0 <= int(d) <= 6]
    t = AutoTrigger(type=a.get("trigger", "time"), value=str(a.get("value") or "").strip(),
                    text=str(a.get("text") or "").strip(), days=days)
    return Automation(id=uuid.uuid4().hex[:8], name=str(a.get("name") or "Automatizace").strip()[:60], trigger=t,
                      steps=_steps(str(a.get("say") or "").strip(), str(a.get("ask") or "").strip(),
                                   str(a.get("protocol") or "").strip()))


def _details(args: dict) -> list[str]:
    from ..automations import describe_steps, describe_trigger

    a = _build(args)
    return [f"Název: {a.name}", f"Když: {describe_trigger(a.trigger)}", *[f"Tak: {x}" for x in describe_steps(a.steps)]]


def _problem(a) -> str:
    t = a.trigger
    if not a.steps:
        return "Chybí, co se má stát (say, ask nebo protocol)."
    if t.type == "time" and not re.fullmatch(r"\d{1,2}:\d\d", t.value):
        return "U času zadej value ve tvaru HH:MM, např. 07:30."
    if t.type in ("app_open", "app_close") and not t.value:
        return "Zadej název aplikace do value."
    if t.type in ("battery", "away", "back") and t.value and not re.fullmatch(r"\d+", t.value):
        return "Do value patří číslo (procenta / minuty)."
    if t.type == "power" and t.value not in ("", "in", "out"):
        return "U nabíječky je value „in“ (připojení) nebo „out“ (odpojení)."
    return ""


@tool("create_automation",
      "Vytvoří automatizaci „Když … tak …“, která běží sama. trigger: time (value HH:MM, days 0=po…6=ne), boot (start PC), "
      "app_open / app_close (value = název aplikace), mail (value = od koho, text = předmět obsahuje), phone_message "
      "(value = kdo píše, text = zpráva obsahuje), phone_call (value = kdo volá), battery (value = %), power (value in/out "
      "= nabíječka připojena/odpojena), away / back (value = minuty pryč od PC). Co udělat: say = co JARVIS řekne "
      "(může obsahovat {sender}, {subject}, {text}, {app}, {percent}, {minutes}), ask = úkol pro JARVISe v přirozené řeči "
      "(např. „ztlum zvuk na 30 %“, „přečti mi ten e-mail“), protocol = název protokolu ke spuštění. "
      "Vždy se uživatele zeptá na potvrzení.",
      danger=True, details=_details, category="systém", perm="apps")
async def create_automation(ctx, name: Annotated[str, "krátký název, např. „Spotify potichu“"], trigger: Trigger,
                            value: str = "", text: str = "", days: list[int] | None = None,
                            say: Annotated[str, "co JARVIS řekne"] = "",
                            ask: Annotated[str, "úkol pro JARVISe v přirozené řeči"] = "",
                            protocol: Annotated[str, "název protokolu ke spuštění"] = "") -> ToolResult:
    from ..automations import describe_trigger

    a = _build({"name": name, "trigger": trigger, "value": value, "text": text, "days": days, "say": say, "ask": ask,
                "protocol": protocol})
    bad = _problem(a)
    if bad:
        return ToolResult(False, bad)
    items = [x.model_dump(mode="json") for x in ctx.cfg.automations.items] + [a.model_dump(mode="json")]
    ctx.update_config({"automations": {"items": items}})
    return ToolResult(True, f"Automatizace „{a.name}“ je nastavená: {describe_trigger(a.trigger)}.", data={"id": a.id})


@tool("list_automations", "Seznam automatizací „Když … tak …“ (zapnuté i vypnuté) a co se naposledy spustilo.",
      category="systém", perm="apps")
async def list_automations(ctx) -> ToolResult:
    from ..automations import describe_steps, describe_trigger

    items = ctx.cfg.automations.items
    if not items:
        return ToolResult(True, "Žádné automatizace. Vytvořit je jde hlasem („když otevřu Spotify, ztlum zvuk“) "
                                "nebo v Nastavení → Automatizace.")
    lines = [f"{'✓' if a.enabled else '✗'} {a.name}: {describe_trigger(a.trigger)} → {'; '.join(describe_steps(a.steps))}"
             for a in items]
    return ToolResult(True, "\n".join(lines), data={"log": list(ctx.automations.log)[:5]})


@tool("delete_automation", "Smaže automatizaci podle názvu.", category="systém", perm="apps")
async def delete_automation(ctx, name: str) -> ToolResult:
    a = ctx.automations.find(name)
    if a is None:
        return ToolResult(False, f"Automatizaci „{name}“ nemám.")
    items = [x.model_dump(mode="json") for x in ctx.cfg.automations.items if x.id != a.id]
    ctx.update_config({"automations": {"items": items}})
    return ToolResult(True, f"Automatizace „{a.name}“ smazána.")


@tool("toggle_automation", "Zapne nebo vypne jednu automatizaci (enabled), nebo všechny najednou (name = „vše“).",
      category="systém", perm="apps")
async def toggle_automation(ctx, name: str, enabled: bool) -> ToolResult:
    if name.strip().lower() in ("vše", "vse", "všechny", "vsechny", "all", "*"):
        ctx.update_config({"automations": {"enabled": enabled}})
        return ToolResult(True, "Automatizace zapnuty." if enabled else "Všechny automatizace jsou pozastavené.")
    a = ctx.automations.find(name)
    if a is None:
        return ToolResult(False, f"Automatizaci „{name}“ nemám.")
    items = [x.model_dump(mode="json") | ({"enabled": enabled} if x.id == a.id else {}) for x in ctx.cfg.automations.items]
    patch = {"automations": {"items": items}}
    if enabled:
        patch["automations"]["enabled"] = True
    ctx.update_config(patch)
    return ToolResult(True, f"Automatizace „{a.name}“ {'zapnuta' if enabled else 'vypnuta'}.")
