"""WebSocket protocol (spec §6). Keep in sync with web/src/shared/protocol.ts."""
from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .. import config as config_mod
from .. import secrets, tools
from ..tools.system import system_snapshot

log = logging.getLogger(__name__)

CLIENT_TYPES = [
    "hello", "user_text", "audio_chunk", "audio_end", "voice_upload", "confirm_response", "stop", "quick_action",
    "share", "history_get", "conversations_get", "switch_conversation", "new_chat", "delete_conversation",
    "regenerate", "settings_get", "settings_set", "secret_set", "provider_test", "memory_get", "fact_update",
    "fact_delete", "memory_wipe", "pairing_get", "speak", "tts_request", "shelf_add", "shelf_remove", "system_get",
    "weather_get", "timers_get", "tools_get", "jobs_get", "job_delete", "skills_get", "mcp_get", "push_to_talk",
    "voice_toggle", "ping", "mood_set", "pet_command", "update_check", "update_install",
    "stop_all", "tasks_get", "task_get", "task_pause", "task_resume", "task_cancel", "task_retry", "tasks_clear",
]
SERVER_TYPES = [
    "welcome", "state", "level", "transcript", "user_message", "assistant_delta", "assistant_done", "tool_start",
    "tool_end", "confirm_request", "confirm_timeout", "notify", "brain", "error", "settings_changed", "task_progress",
    "media", "history", "conversations", "settings", "provider_test_result", "memory", "pairing", "tts_audio",
    "shelf", "system", "weather", "timers", "tools", "jobs", "skills", "mcp", "quick_result", "pong", "voice_status",
    "mood", "pet_state", "update_status", "confirm_resolved", "task_update",
    "tasks", "task", "stopped", "screen_capture",
]

QUICK_ACTIONS = {"media_control", "volume", "system_power", "screenshot", "window_control", "open_app", "open_url",
                 "youtube_play", "set_timer", "cancel_timer", "clipboard_set", "set_dark_mode", "press_keys",
                 "save_attachment", "send_to_phone"}
LOCAL_ONLY = {"settings_set", "secret_set", "provider_test", "fact_update", "fact_delete", "memory_wipe", "pairing_get",
              "update_install", "tasks_clear"}


class Connection:
    def __init__(self, ws: WebSocket, rt: Any, local: bool):
        self.ws = ws
        self.rt = rt
        self.local = local
        self.id = uuid.uuid4().hex[:8]
        self.client = "unknown"
        self.name = ""
        self.audio = bytearray()
        self.audio_sr = 16000
        self.send_lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()

    async def send(self, type: str, **data) -> None:  # noqa: A002
        async with self.send_lock:
            await self.ws.send_json({"type": type, **data})

    def spawn(self, coro) -> None:
        t = asyncio.get_running_loop().create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    # ---------- main loop ----------
    async def run(self) -> None:
        q = self.rt.bus.subscribe()
        self.rt.clients[self.id] = {"client": self.client, "name": self.name, "local": self.local}
        pump = asyncio.get_running_loop().create_task(self._pump(q))
        try:
            await self.send_welcome()
            while True:
                msg = await self.ws.receive_json()
                if not isinstance(msg, dict) or "type" not in msg:
                    continue
                try:
                    await self.dispatch(msg)
                except Exception as e:
                    log.exception("ws handler %s failed", msg.get("type"))
                    await self.send("error", message=f"{type(e).__name__}: {e}")
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            pump.cancel()
            self.rt.bus.unsubscribe(q)
            self.rt.clients.pop(self.id, None)

    async def _pump(self, q: asyncio.Queue) -> None:
        try:
            while True:
                msg = await q.get()
                tgt = msg.get("target")
                if tgt and tgt not in ("all", self.client):
                    continue
                if msg["type"] == "level" and self.client == "mobile":
                    continue
                await self.send(**msg)
        except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
            pass

    async def send_welcome(self) -> None:
        rt = self.rt
        await self.send("welcome", version=__import__("jarvis").__version__, local=self.local,
                        settings=config_mod.public_dump(rt.cfg), conversation=rt.memory.current_conversation,
                        history=self._history(), conversations=rt.memory.list_conversations(),
                        busy=rt.agent.busy, brain=list(rt.router.last_used) if rt.router.last_used else None,
                        media=rt.media_state, shelf=[rt.public_attachment(a) for a in rt.shelf],
                        timers=rt.timers.list(), voice=self._voice_status(),
                        pending_confirm=rt.agent.pending_confirm(), mood=rt.mood.current,
                        pet_mode=rt.cfg.character.pet_mode,
                        update=rt.updater.status if rt.updater else None)

    def _history(self, conv_id: str | None = None, before: float | None = None, limit: int = 60) -> list[dict]:
        msgs = self.rt.memory.history(conv_id, before, limit)
        for m in msgs:
            m["attachments"] = [self.rt.public_attachment(a) for a in m["attachments"]]
        return msgs

    def _voice_status(self) -> dict:
        v = self.rt.voice
        return v.status() if v and hasattr(v, "status") else {"available": False, "listening": False}

    def _source(self, voice: bool = False) -> str:
        if self.client == "mobile":
            return "mobile_voice" if voice else "mobile"
        return "voice" if voice else ("notch" if self.client == "notch" else "chat")

    # ---------- handlers ----------
    async def dispatch(self, m: dict) -> None:
        t = m["type"]
        rt = self.rt
        if t in LOCAL_ONLY and not self.local:
            await self.send("error", message="Tohle jde změnit jen přímo na počítači.")
            return
        if t == "hello":
            self.client = m.get("client", "unknown")
            self.name = m.get("name", "")
            rt.clients[self.id] = {"client": self.client, "name": self.name, "local": self.local}
        elif t == "ping":
            await self.send("pong", t=m.get("t"))
        elif t == "user_text":
            text = (m.get("text") or "").strip()
            atts = [a for a in (m.get("attachments") or []) if rt.store.get(a)]
            if text or atts:
                self.spawn(rt.agent.handle(text, atts, self._source()))
        elif t == "audio_chunk":
            self.audio += base64.b64decode(m.get("pcm16_b64", ""))
            self.audio_sr = int(m.get("sample_rate", 16000))
        elif t == "audio_end":
            pcm, self.audio = bytes(self.audio), bytearray()
            self.spawn(self._transcribe_pcm_and_handle(pcm, self.audio_sr))
        elif t == "voice_upload":
            self.spawn(self._voice_note(m["attachment_id"]))
        elif t == "confirm_response":
            rt.agent.confirm(m.get("id", ""), bool(m.get("approved")))
        elif t == "stop":
            rt.agent.stop()
            if rt.speaker:
                rt.speaker.stop()
        elif t == "stop_all":
            rt.stop_all()
        elif t == "tasks_get":
            await self.send("tasks", items=rt.tasks.list(int(m.get("limit", 50)), m.get("q", ""), m.get("status", "")),
                            current=rt.tasks.current)
        elif t == "task_get":
            await self.send("task", task=rt.tasks.get(m.get("id", "")))
        elif t == "task_pause":
            rt.tasks.pause()
        elif t == "task_resume":
            rt.tasks.resume()
        elif t == "task_cancel":
            rt.agent.stop()
        elif t == "task_retry":
            old = rt.tasks.get(m.get("id", ""))
            if old:
                self.spawn(rt.agent.handle(f"Zopakuj úkol: {old['goal']}", [], self._source()))
        elif t == "tasks_clear":
            rt.tasks.clear()
            await self.send("tasks", items=rt.tasks.list(), current=rt.tasks.current)
        elif t == "quick_action":
            name = m.get("action", "")
            if name not in QUICK_ACTIONS:
                await self.send("quick_result", action=name, ok=False, summary="Nepovolená akce")
                return
            spec = tools.REGISTRY.get(name)
            args = m.get("args") or {}
            if spec and tools.is_dangerous(spec, args, rt.cfg.tools.always_confirm, rt.cfg.tools.trusted) and not m.get("confirmed"):
                await self.send("quick_result", action=name, ok=False, needs_confirm=True, summary="Potvrď akci")
                return
            res = await tools.call(name, args, rt)
            await self.send("quick_result", action=name, ok=res.ok, summary=res.summary,
                            attachments=[rt.public_attachment(a) for a in res.attachments])
        elif t == "share":
            await self._share(m)
        elif t == "history_get":
            await self.send("history", conversation=m.get("conversation") or rt.memory.current_conversation,
                            messages=self._history(m.get("conversation"), m.get("before"), int(m.get("limit", 60))),
                            prepend=bool(m.get("before")))
        elif t == "conversations_get":
            await self.send("conversations", items=rt.memory.list_conversations(), current=rt.memory.current_conversation)
        elif t == "switch_conversation":
            if rt.memory.switch(m.get("id", "")):
                rt.bus.publish("history", conversation=rt.memory.current_conversation, messages=self._history())
        elif t == "new_chat":
            rt.memory.new_conversation()
            rt.bus.publish("history", conversation=rt.memory.current_conversation, messages=[])
            rt.bus.publish("conversations", items=rt.memory.list_conversations(), current=rt.memory.current_conversation)
        elif t == "delete_conversation":
            rt.memory.delete_conversation(m.get("id", ""))
            rt.bus.publish("conversations", items=rt.memory.list_conversations(), current=rt.memory.current_conversation)
            rt.bus.publish("history", conversation=rt.memory.current_conversation, messages=self._history())
        elif t == "regenerate":
            u = rt.memory.delete_last_assistant()
            if u:
                rt.bus.publish("history", conversation=rt.memory.current_conversation, messages=self._history())
                self.spawn(rt.agent.handle(u["text"], u["attachments"], self._source(), record_user=False))
        elif t == "settings_get":
            await self.send("settings", settings=config_mod.public_dump(rt.cfg), secrets=self._secret_flags(),
                            presets=__import__("jarvis.llm.presets", fromlist=["PRESETS"]).PRESETS,
                            voice=self._voice_status())
        elif t == "settings_set":
            try:
                rt.update_config(m.get("patch") or {})
                await self.send("settings", settings=config_mod.public_dump(rt.cfg), secrets=self._secret_flags())
            except ValueError as e:
                await self.send("error", message=f"Neplatné nastavení: {e}")
        elif t == "secret_set":
            secrets.set(m["name"], m.get("value", ""))
            await self.send("settings", settings=config_mod.public_dump(rt.cfg), secrets=self._secret_flags())
        elif t == "provider_test":
            await self.send("provider_test_result", **(await self._provider_test(m.get("id", ""))))
        elif t == "memory_get":
            await self.send("memory", facts=rt.memory.facts())
        elif t == "fact_update":
            if m.get("id"):
                rt.memory.update_fact(int(m["id"]), m.get("text", ""))
            else:
                rt.memory.remember(m.get("text", ""))
            await self.send("memory", facts=rt.memory.facts())
        elif t == "fact_delete":
            rt.memory.delete_fact(int(m["id"]))
            await self.send("memory", facts=rt.memory.facts())
        elif t == "memory_wipe":
            rt.memory.wipe()
            await self.send("memory", facts=[])
            rt.bus.publish("history", conversation=rt.memory.current_conversation, messages=[])
        elif t == "pairing_get":
            from .pairing import pairing_info

            if m.get("regenerate"):
                import secrets as pysecrets

                rt.update_config({"phone": {"token": pysecrets.token_urlsafe(32)}})
            await self.send("pairing", **pairing_info(rt.cfg.phone.token, rt.cfg.phone.port),
                            devices=[c for c in rt.clients.values() if c.get("client") == "mobile"])
        elif t == "speak":
            rt.speak(m.get("text", ""))
        elif t == "tts_request":
            self.spawn(self._tts(m.get("text", ""), m.get("message_id")))
        elif t == "shelf_add":
            if rt.store.get(m.get("attachment_id", "")) and m["attachment_id"] not in rt.shelf:
                rt.shelf.append(m["attachment_id"])
            rt.bus.publish("shelf", items=[rt.public_attachment(a) for a in rt.shelf])
        elif t == "shelf_remove":
            rt.shelf = [a for a in rt.shelf if a != m.get("attachment_id")]
            rt.bus.publish("shelf", items=[rt.public_attachment(a) for a in rt.shelf])
        elif t == "system_get":
            await self.send("system", **(await asyncio.to_thread(system_snapshot)))
        elif t == "weather_get":
            from ..tools.weather import fetch_weather

            try:
                await self.send("weather", **(await fetch_weather(rt, m.get("city") or rt.cfg.general.city)))
            except Exception as e:
                await self.send("weather", error=str(e))
        elif t == "timers_get":
            await self.send("timers", items=rt.timers.list())
        elif t == "tools_get":
            await self.send("tools", items=[{"name": s.name, "description": s.description, "danger": s.danger or bool(s.danger_if),
                                             "category": s.category, "source": s.source,
                                             "enabled": s.name not in rt.cfg.tools.disabled}
                                            for s in tools.REGISTRY.values()])
        elif t == "jobs_get":
            await self.send("jobs", items=rt.scheduler.list() if rt.scheduler else [])
        elif t == "job_delete":
            if rt.scheduler:
                rt.scheduler.delete(m.get("id", ""))
                await self.send("jobs", items=rt.scheduler.list())
        elif t == "skills_get":
            from ..tools.skills import list_skills

            await self.send("skills", items=list_skills())
        elif t == "mcp_get":
            await self.send("mcp", items=rt.mcp.status() if rt.mcp else [])
        elif t == "push_to_talk":
            if rt.voice:
                rt.voice.push_to_talk()
        elif t == "mood_set":
            if m.get("clear") == "notify":
                rt.mood.clear_notify()
            else:
                rt.mood.set_manual(m.get("mood"))
        elif t == "pet_command":
            action = m.get("action", "")
            if action in ("undock", "dock", "toggle") and rt.pet_hook:
                await asyncio.to_thread(rt.pet_hook, action)  # pywebview calls block
            elif action in ("undock", "dock", "toggle"):
                rt.update_config({"character": {"pet_mode": action == "undock" or (action == "toggle" and not rt.cfg.character.pet_mode)}})
        elif t == "update_check":
            if rt.updater:
                self.spawn(rt.updater.check(force=True))
        elif t == "update_install":
            if rt.updater:
                self.spawn(rt.updater.download_and_install())
        elif t == "voice_toggle":
            if rt.voice:
                rt.voice.set_paused(not rt.voice.paused)
                rt.bus.publish("voice_status", **self._voice_status())

    def _secret_flags(self) -> dict:
        return {p.id: secrets.has(p.id) for p in self.rt.cfg.brain.providers}

    async def _provider_test(self, pid: str) -> dict:
        from ..llm.router import Router

        brain = self.rt.cfg.brain.model_copy(deep=True)
        brain.chain = [pid]
        brain.providers = [p for p in brain.providers if p.id == pid]
        if not brain.providers:
            return {"id": pid, "ok": False, "message": "Poskytovatel nenalezen"}
        r = Router(brain, secrets.get, self.rt.router.transport)
        t0 = time.time()
        try:
            text = await asyncio.wait_for(r.complete([{"role": "user", "content": "Odpověz jen slovem: funguju"}]), 60)
            return {"id": pid, "ok": True, "message": text.strip()[:200], "ms": round((time.time() - t0) * 1000)}
        except Exception as e:
            return {"id": pid, "ok": False, "message": str(e)[:300]}

    async def _share(self, m: dict) -> None:
        rt = self.rt
        kind, value = m.get("kind"), m.get("value", "")
        if kind == "url":
            await tools.call("open_url", {"url": value}, rt)
            rt.bus.publish("notify", title="Odkaz z telefonu", body=value, url=value, target="all")
        elif kind == "text":
            rt.platform.clipboard_set(value)
            rt.bus.publish("notify", title="Text z telefonu (ve schránce)", body=value[:200], target="all")
        elif kind == "file":
            aid = m.get("attachment_id", "")
            if rt.store.get(aid):
                if aid not in rt.shelf:
                    rt.shelf.append(aid)
                rt.bus.publish("shelf", items=[rt.public_attachment(a) for a in rt.shelf])
                att = rt.store.get(aid)
                rt.bus.publish("notify", title="Soubor z telefonu", body=f"{att.name} je v polici notche", target="all")
        await self.send("quick_result", action="share", ok=True, summary="Odesláno do PC")

    async def _transcribe(self, func, *args) -> str:
        return (await asyncio.to_thread(func, *args)).strip()

    async def _transcribe_pcm_and_handle(self, pcm: bytes, sr: int) -> None:
        rt = self.rt
        stt = getattr(rt.voice, "transcriber", None) if rt.voice else None
        if stt is None:
            await self.send("error", message="Rozpoznávání řeči na PC není dostupné.")
            return
        text = await self._transcribe(stt.transcribe, pcm, sr)
        rt.bus.publish("transcript", text=text, final=True)
        if text:
            await rt.agent.handle(text, [], self._source(voice=True))

    async def _voice_note(self, aid: str) -> None:
        rt = self.rt
        att = await rt.store.ensure(aid)
        if not att:
            return
        text = (att.text or "").strip()
        if not text:
            await self.send("error", message=att.error or "Nerozuměl jsem nahrávce.")
            return
        rt.bus.publish("transcript", text=text, final=True)
        await rt.agent.handle(text, [], self._source(voice=True))

    async def _tts(self, text: str, message_id: str | None) -> None:
        rt = self.rt
        if not rt.speaker:
            await self.send("error", message="Hlasový výstup není dostupný.")
            return
        audio, mime = await rt.speaker.synth(text)
        att = await rt.store.save(f"tts-{message_id or 'x'}.{'mp3' if 'mpeg' in mime else 'wav'}", audio, mime)
        await self.send("tts_audio", message_id=message_id, attachment=att.public())
