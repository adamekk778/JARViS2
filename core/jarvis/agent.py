"""The agent loop: message → LLM → tools → … → answer."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from . import tools
from .llm.base import AllProvidersFailed, ProviderError, ToolCall
from .prompt import build_system_prompt

log = logging.getLogger(__name__)

MAX_ROUNDS = 8
CONFIRM_TIMEOUT = 30.0
NO_BRAIN = ("Omlouvám se, teď nemám spojení s žádným AI mozkem. Zkontroluj prosím, jestli běží OmniRoute nebo "
            "Ollama, případně přidej jiného poskytovatele v Nastavení → Mozek.")

TOOL_LABELS = {
    "youtube_play": "Pouštím YouTube", "open_app": "Spouštím aplikaci", "close_app": "Zavírám aplikaci",
    "web_search": "Hledám na webu", "web_read": "Čtu stránku", "weather": "Zjišťuji počasí",
    "volume": "Hlasitost", "media_control": "Média", "screenshot": "Snímek obrazovky",
    "system_power": "Napájení", "run_shell": "PowerShell", "computer_use": "Ovládám počítač",
    "run_python": "Spouštím kód", "generate_image": "Kreslím obrázek", "set_timer": "Časovač",
    "set_reminder": "Připomínka", "find_file": "Hledám soubor", "open_file": "Otevírám soubor",
    "remember": "Pamatuji si", "send_file": "Posílám soubor", "send_to_phone": "Posílám na telefon",
    "create_skill": "Učím se novou dovednost", "schedule_task": "Plánuji úlohu",
    "browser_open": "Otevírám stránku", "browser_click": "Klikám v prohlížeči", "browser_type": "Píšu do prohlížeče",
}


def describe_call(name: str, args: dict) -> str:
    label = TOOL_LABELS.get(name, name)
    key = next((args[k] for k in ("query", "name", "text", "task", "prompt", "url", "command", "action", "path", "city")
                if isinstance(args.get(k), (str, int)) and args.get(k) != ""), None)
    return f"{label}: {key}" if key is not None else label


def _stored_to_llm(m: dict) -> dict:
    text = m["text"] or ""
    if m["attachments"]:
        text += "\n" + " ".join(f"[příloha id={a}]" for a in m["attachments"])
    return {"role": "assistant" if m["role"] == "assistant" else "user", "content": text}


class Agent:
    def __init__(self, rt: Any):
        self.rt = rt
        self._lock = asyncio.Lock()
        self._confirms: dict[str, asyncio.Future] = {}
        self._task: asyncio.Task | None = None
        self.busy = False

    # ---------- public ----------
    async def handle(self, text: str, attachments: list[str] | None = None, source: str = "chat",
                     record_user: bool = True, extra_system: str = "") -> str:
        async with self._lock:
            self._task = asyncio.current_task()
            self.busy = True
            try:
                return await self._handle(text, attachments or [], source, record_user, extra_system)
            finally:
                self.busy = False
                self._task = None
                self.rt.bus.publish("state", state="idle")

    def confirm(self, cid: str, approved: bool) -> bool:
        fut = self._confirms.get(cid)
        if fut and not fut.done():
            fut.set_result(bool(approved))
            return True
        return False

    def pending_confirm(self) -> str | None:
        return next((k for k, f in self._confirms.items() if not f.done()), None)

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    # ---------- internals ----------
    async def _build_messages(self, text: str, attachments: list[str], voice: bool, extra: str) -> tuple[list[dict], bool]:
        rt = self.rt
        facts = [f["text"] for f in rt.memory.facts()]
        msgs: list[dict] = [{"role": "system", "content": build_system_prompt(rt.cfg, facts, voice, extra)}]
        history = rt.memory.recent(rt.cfg.memory.context_messages + 1)
        if history and history[-1]["role"] == "user" and history[-1]["text"] == text:
            history = history[:-1]
        msgs += [_stored_to_llm(m) for m in history if m["role"] in ("user", "assistant")]
        need_vision = False
        if attachments:
            parts: list[dict] = [{"type": "text", "text": text or "(uživatel poslal přílohu bez textu — zpracuj ji)"}]
            for aid in attachments:
                att = rt.store.get(aid)
                is_img = bool(att and att.kind == "image")
                need_vision |= is_img
                parts += await rt.store.llm_parts(aid, vision=True)
            msgs.append({"role": "user", "content": parts})
        else:
            msgs.append({"role": "user", "content": text})
        return msgs, need_vision

    async def _ask_confirm(self, call: ToolCall) -> bool:
        cid = uuid.uuid4().hex[:10]
        fut = asyncio.get_running_loop().create_future()
        self._confirms[cid] = fut
        desc = describe_call(call.name, call.arguments)
        self.rt.bus.publish("confirm_request", id=cid, description=desc, tool=call.name, args=call.arguments)
        self.rt.on_confirm_request(cid, desc)
        try:
            return await asyncio.wait_for(fut, CONFIRM_TIMEOUT)
        except asyncio.TimeoutError:
            self.rt.bus.publish("confirm_timeout", id=cid)
            return False
        finally:
            self._confirms.pop(cid, None)

    async def _run_call(self, call: ToolCall, tool_cards: list[dict], attachments: list[str]) -> dict:
        rt = self.rt
        spec = tools.REGISTRY.get(call.name)
        disabled = set(rt.cfg.tools.disabled)
        if spec is None or call.name in disabled:
            res = tools.ToolResult(False, f"Nástroj {call.name} neexistuje nebo je vypnutý.")
        else:
            approved = True
            if tools.is_dangerous(spec, call.arguments, rt.cfg.tools.always_confirm, rt.cfg.tools.trusted):
                rt.bus.publish("state", state="waiting")
                approved = await self._ask_confirm(call)
            if not approved:
                res = tools.ToolResult(False, "Uživatel akci nepotvrdil – NEPROVEDENO. Nezkoušej to znovu.")
                rt.bus.publish("tool_end", id=call.id, ok=False, summary="Zrušeno")
            else:
                rt.bus.publish("state", state="acting")
                rt.bus.publish("tool_start", id=call.id, name=call.name, args=call.arguments,
                               label=describe_call(call.name, call.arguments))
                res = await tools.call(call.name, call.arguments, rt)
                rt.bus.publish("tool_end", id=call.id, ok=res.ok, summary=res.summary)
        attachments += [a for a in res.attachments if a not in attachments]
        tool_cards.append({"name": call.name, "label": describe_call(call.name, call.arguments), "ok": res.ok,
                           "summary": res.summary})
        return {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": res.for_llm()}

    async def _handle(self, text: str, attachments: list[str], source: str, record_user: bool, extra: str) -> str:
        rt = self.rt
        bus = rt.bus
        voice = source in ("voice", "mobile_voice")
        if record_user:
            um = rt.memory.add_message("user", text, attachments, source)
            bus.publish("user_message", id=um["id"], text=text, source=source,
                        attachments=[rt.public_attachment(a) for a in attachments])
        bus.publish("state", state="thinking")
        msgs, need_vision = await self._build_messages(text, attachments, voice, extra)
        schemas = tools.schemas(rt.cfg.tools.disabled)
        full_text = ""
        tool_cards: list[dict] = []
        out_atts: list[str] = []
        cancelled = False
        try:
            for rnd in range(MAX_ROUNDS + 1):
                round_text = ""
                calls: list[ToolCall] | None = None
                use_tools = schemas if rnd < MAX_ROUNDS else None
                async for ch in rt.router.stream(msgs, use_tools, need_vision=need_vision):
                    if ch.text:
                        if not round_text and full_text:
                            bus.publish("assistant_delta", text="\n\n")
                            full_text += "\n\n"
                        round_text += ch.text
                        full_text += ch.text
                        bus.publish("assistant_delta", text=ch.text)
                    if ch.tool_calls:
                        calls = ch.tool_calls
                if rt.router.last_used:
                    bus.publish("brain", provider=rt.router.last_used[0], model=rt.router.last_used[1])
                if not calls:
                    break
                if rnd >= MAX_ROUNDS:
                    break
                msgs.append({"role": "assistant", "content": round_text or None, "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
                    for c in calls]})
                safe = [c for c in calls if not (tools.REGISTRY.get(c.name) and tools.is_dangerous(
                    tools.REGISTRY[c.name], c.arguments, rt.cfg.tools.always_confirm, rt.cfg.tools.trusted))]
                results: dict[str, dict] = {}
                if len(safe) > 1:
                    outs = await asyncio.gather(*(self._run_call(c, tool_cards, out_atts) for c in safe))
                    results.update({c.id: o for c, o in zip(safe, outs)})
                for c in calls:
                    if c.id not in results:
                        results[c.id] = await self._run_call(c, tool_cards, out_atts)
                msgs += [results[c.id] for c in calls]
                bus.publish("state", state="thinking")
            else:
                pass
            if not full_text.strip():
                full_text = "Hotovo." if tool_cards else "…"
                bus.publish("assistant_delta", text=full_text)
        except AllProvidersFailed as e:
            log.warning("all providers failed: %s", e)
            bus.publish("error", message=f"Žádný AI poskytovatel neodpověděl: {e}")
            full_text = (full_text + "\n\n" if full_text else "") + NO_BRAIN
            bus.publish("assistant_delta", text=NO_BRAIN)
        except ProviderError as e:
            bus.publish("error", message=str(e))
            full_text += f"\n\n(Spojení s AI se přerušilo: {e})"
        except asyncio.CancelledError:
            cancelled = True
            full_text = (full_text + " …(přerušeno)").strip()
        am = rt.memory.add_message("assistant", full_text, out_atts, source,
                                   meta={"tools": tool_cards, "brain": rt.router.last_used})
        bus.publish("assistant_done", id=am["id"], text=full_text, tools=tool_cards,
                    attachments=[rt.public_attachment(a) for a in out_atts])
        if not cancelled:
            rt.maybe_speak(full_text, source)
        return full_text
