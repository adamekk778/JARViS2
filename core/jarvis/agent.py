"""The agent loop: message → LLM → tools → … → answer."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from . import tools
from .llm.base import AllProvidersFailed, ProviderError, ToolCall
from .prompt import build_system_prompt

log = logging.getLogger(__name__)

MAX_ROUNDS = 8
MAX_ROUNDS_AGENT = 25
CONFIRM_TIMEOUT = 30.0
NO_LIMIT = ("Narazil jsem na limit u všech AI poskytovatelů. Chvíli počkej, nebo v Nastavení → Mozek přidej "
            "dalšího poskytovatele (třeba Groq nebo Gemini mají limity zdarma), případně zapni Ollamu pro offline režim.")
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
    "ui_click": "Klikám", "ui_type": "Píšu do aplikace", "ui_inspect": "Prohlížím okno", "ui_read": "Čtu okno",
    "ui_wait": "Čekám na okno", "mouse": "Myš", "move_files": "Přesouvám soubory", "update_plan": "Plán",
    "git_status": "Git stav", "git_diff": "Git změny", "git_commit": "Git commit", "git_push": "Git push",
    "checkpoint": "Záchytný bod", "restore_checkpoint": "Obnovuji záchytný bod", "compare_files": "Porovnávám soubory",
    "run_tests": "Spouštím testy", "claude_code": "Claude Code",
}


AGENT_MODE_RULE = ("Režim Agent: u úkolu s více kroky nejdřív zavolej update_plan se seznamem kroků, po každém kroku "
                   "ho aktualizuj a na konci ověř výsledek.")


def _first_sentence(text: str) -> str:
    import re

    m = re.match(r"\s*(.+?[.!?])(\s|$)", text or "", re.S)
    return (m.group(1) if m else (text or "")).strip()[:300]


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
        self._goal = ""
        self._lang = "cs"
        self._gen = 0  # bumped by drop_queued(): requests waiting for the lock are discarded

    # ---------- public ----------
    async def handle(self, text: str, attachments: list[str] | None = None, source: str = "chat",
                     record_user: bool = True, extra_system: str = "", lang: str = "") -> str:
        rt = self.rt
        if self._lock.locked() and rt.tasks.current and rt.tasks.current["status"] == "paused":
            msg = "Úkol je pozastavený – nejdřív ho nech pokračovat, nebo ho zruš (Úkoly nebo STOP)."
            rt.bus.publish("error", message=msg)
            return msg
        gen = self._gen
        async with self._lock:
            if gen != self._gen:  # STOP was pressed while this request waited → drop it
                return ""
            self._task = asyncio.current_task()
            self.busy = True
            try:
                if lang == "en":
                    extra_system = (extra_system + "\n" if extra_system else "") + "Odpověz anglicky."
                self._lang = lang or "cs"
                return await self._handle(text, attachments or [], source, record_user, extra_system)
            finally:
                self.busy = False
                self._task = None
                self.rt.bus.publish("state", state="idle")

    def confirm(self, cid: str, approved: bool) -> bool:
        fut = self._confirms.get(cid)
        if fut and not fut.done():
            fut.set_result(bool(approved))
            self.rt.bus.publish("confirm_resolved", id=cid, approved=bool(approved))
            return True
        return False

    def pending_confirm(self) -> str | None:
        return next((k for k, f in self._confirms.items() if not f.done()), None)

    def drop_queued(self) -> None:
        self._gen += 1

    def cancel_confirms(self) -> None:
        for cid in list(self._confirms):
            self.confirm(cid, False)

    def stop(self) -> None:
        self.cancel_confirms()  # an open "Ano / Ne" must not outlive the task it belongs to
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
        spec = tools.REGISTRY.get(call.name)
        details = await asyncio.to_thread(tools.details_for, spec, call.arguments, self.rt) if spec else []
        self.rt.bus.publish("confirm_request", id=cid, description=desc, tool=call.name, args=call.arguments,
                            details=details)
        self.rt.on_confirm_request(cid, desc)
        try:
            return await asyncio.wait_for(fut, CONFIRM_TIMEOUT)
        except asyncio.TimeoutError:
            self.rt.bus.publish("confirm_timeout", id=cid)
            return False
        finally:
            self._confirms.pop(cid, None)

    def _rounds(self) -> int:
        return MAX_ROUNDS_AGENT if self.rt.cfg.agent.mode else MAX_ROUNDS

    async def _run_call(self, call: ToolCall, tool_cards: list[dict], attachments: list[str]) -> dict:
        rt = self.rt
        await rt.tasks.checkpoint()
        if rt.tasks.current is None:
            rt.tasks.begin(self._goal, rt.memory.current_conversation)
        spec = tools.REGISTRY.get(call.name)
        disabled = set(rt.cfg.tools.disabled)
        if spec is None or call.name in disabled:
            res = tools.ToolResult(False, f"Nástroj {call.name} neexistuje nebo je vypnutý.")
        else:
            approved = True
            if tools.is_dangerous(spec, call.arguments, rt.cfg.tools.always_confirm, rt.cfg.tools.trusted, rt):
                rt.bus.publish("state", state="waiting")
                rt.tasks.set_waiting(True)
                try:
                    approved = await self._ask_confirm(call)
                finally:
                    rt.tasks.set_waiting(False)
            if not approved:
                res = tools.ToolResult(False, "Uživatel akci nepotvrdil – NEPROVEDENO. Nezkoušej to znovu.")
                rt.bus.publish("tool_end", id=call.id, ok=False, summary="Zrušeno")
            else:
                rt.bus.publish("state", state="acting")
                label = describe_call(call.name, call.arguments)
                rt.bus.publish("tool_start", id=call.id, name=call.name, args=call.arguments, label=label)
                if call.name != "update_plan":
                    rt.tasks.action_started(label)
                t0 = time.monotonic()
                res = await tools.call(call.name, call.arguments, rt)
                rt.bus.publish("tool_end", id=call.id, ok=res.ok, summary=res.summary)
                if call.name != "update_plan":
                    rt.tasks.log_action(call.name, call.arguments, res.ok, res.summary,
                                        int((time.monotonic() - t0) * 1000))
        attachments += [a for a in res.attachments if a not in attachments]
        tool_cards.append({"name": call.name, "label": describe_call(call.name, call.arguments), "ok": res.ok,
                           "summary": res.summary})
        return {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": res.for_llm()}

    async def _handle(self, text: str, attachments: list[str], source: str, record_user: bool, extra: str) -> str:
        rt = self.rt
        bus = rt.bus
        voice = source in ("voice", "mobile_voice")
        self._goal = text or "(příloha)"
        status = "done"
        if record_user:
            um = rt.memory.add_message("user", text, attachments, source)
            bus.publish("user_message", id=um["id"], text=text, source=source,
                        attachments=[rt.public_attachment(a) for a in attachments])
        bus.publish("state", state="thinking")
        if rt.cfg.agent.mode:
            extra = (extra + "\n" if extra else "") + AGENT_MODE_RULE
        msgs, need_vision = await self._build_messages(text, attachments, voice, extra)
        schemas = tools.schemas(rt.cfg.tools.disabled, rt.cfg)
        full_text = ""
        tool_cards: list[dict] = []
        out_atts: list[str] = []
        cancelled = False
        try:
            rounds = self._rounds()
            for rnd in range(rounds + 1):
                if rnd:
                    await rt.tasks.checkpoint()
                round_text = ""
                calls: list[ToolCall] | None = None
                use_tools = schemas if rnd < rounds else None
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
                if rnd >= rounds:
                    break
                msgs.append({"role": "assistant", "content": round_text or None, "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
                    for c in calls]})
                safe = [c for c in calls if not (tools.REGISTRY.get(c.name) and tools.is_dangerous(
                    tools.REGISTRY[c.name], c.arguments, rt.cfg.tools.always_confirm, rt.cfg.tools.trusted, rt))]
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
            status = "failed"
            log.warning("all providers failed: %s", e)
            bus.publish("error", message=f"Žádný AI poskytovatel neodpověděl: {e}", kind="limit" if e.is_limit else "brain")
            msg = NO_LIMIT if e.is_limit else NO_BRAIN
            full_text = (full_text + "\n\n" if full_text else "") + msg
            bus.publish("assistant_delta", text=msg)
        except ProviderError as e:
            status = "failed"
            bus.publish("error", message=str(e))
            full_text += f"\n\n(Spojení s AI se přerušilo: {e})"
        except asyncio.CancelledError:
            cancelled = True
            status = "cancelled"
            full_text = (full_text + " …(přerušeno)").strip()
        except Exception as e:  # a bug must not leave the task "running" forever
            log.exception("agent failed")
            status = "failed"
            bus.publish("error", message=f"Něco se pokazilo: {type(e).__name__}: {e}")
            full_text = (full_text + "\n\n" if full_text else "") + "Omlouvám se, při práci se něco pokazilo."
        if rt.tasks.current is not None:
            rt.tasks.finish(status, _first_sentence(full_text))
        am = rt.memory.add_message("assistant", full_text, out_atts, source,
                                   meta={"tools": tool_cards, "brain": rt.router.last_used})
        bus.publish("assistant_done", id=am["id"], text=full_text, tools=tool_cards,
                    attachments=[rt.public_attachment(a) for a in out_atts])
        if not cancelled:
            rt.maybe_speak(full_text, source, self._lang)
        return full_text
