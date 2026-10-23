"""Runtime: wires config, bus, memory, attachments, router, agent, timers, voice, scheduler, MCP."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from . import config as config_mod
from . import paths, redact, secrets, tools
from .agent import Agent
from .attachments import AttachmentStore
from .events import Bus
from .llm.router import Router
from .memory import DB, Memory
from .timers import Timers
from .tools.platform import Platform
from .tools.platform import get as get_platform

log = logging.getLogger(__name__)


class Runtime:
    def __init__(self, cfg: config_mod.Config | None = None, *, platform: Platform | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, llm_transport: httpx.AsyncBaseTransport | None = None,
                 persist_config: bool = True):
        self.cfg = cfg or config_mod.load()
        redact.add_literal(self.cfg.phone.token)
        self.persist_config = persist_config
        self.bus = Bus()
        self.platform = platform or get_platform()
        self.transport = transport
        self.db = DB(paths.data_dir() / "jarvis.db")
        self.memory = Memory(self.db)
        self.store = AttachmentStore(paths.sub("files"), self.db)
        self.router = Router(self.cfg.brain, secrets.get, llm_transport)
        self.agent = Agent(self)
        self.timers = Timers(self._timer_fired)
        self.voice: Any = None        # voice.loop.VoiceLoop when available
        self.speaker: Any = None      # voice.tts.Speaker
        self.scheduler: Any = None    # scheduler.Scheduler
        self.mcp: Any = None          # mcp.client.McpManager
        self.clients: dict[str, dict] = {}  # ws client id -> info
        self.shelf: list[str] = []    # notch shelf attachment ids
        self.media_state: dict = {}
        self.ui_hook = None           # desktop host: show window (second launch)
        self.pet_hook = None          # desktop host: pet commands (undock, dock, …)
        from .mood import MoodEngine

        self.mood = MoodEngine(self)
        self.updater: Any = None
        tools.load_builtin()

    # ---------- lifecycle ----------
    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.bus.bind_loop(self.loop)
        self.store.transcribe = self._transcribe_file
        self.mood.start()
        try:
            from .updater import Updater

            self.updater = Updater(self)
            self.updater.start()
        except Exception as e:  # pragma: no cover
            log.warning("updater: %s", e)
        try:
            from .tools.skills import load_all_skills

            load_all_skills()
        except Exception as e:  # pragma: no cover
            log.warning("skills: %s", e)
        try:
            from .scheduler import Scheduler

            self.scheduler = Scheduler(self)
            self.scheduler.start()
        except Exception as e:  # pragma: no cover
            log.warning("scheduler unavailable: %s", e)
        try:
            from .integrations.mcp_client import McpManager

            self.mcp = McpManager(self)
            asyncio.get_running_loop().create_task(self.mcp.start())
        except Exception as e:  # pragma: no cover
            log.warning("mcp unavailable: %s", e)

    async def stop(self) -> None:
        self.mood.stop()
        if self.scheduler:
            self.scheduler.stop()
        if self.mcp:
            await self.mcp.stop()

    # ---------- thread bridges (tray, hotkeys, voice run in other threads) ----------
    loop: asyncio.AbstractEventLoop | None = None

    def submit(self, coro):
        """Run a coroutine on the runtime loop from any thread."""
        if self.loop is None:
            raise RuntimeError("runtime not started")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def call_soon(self, fn, *args) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(fn, *args)

    def _transcribe_file(self, path) -> str:
        stt = getattr(self.voice, "transcriber", None) if self.voice else None
        if stt is None:
            raise RuntimeError("rozpoznávání řeči není dostupné (hlasový modul neběží)")
        return stt.transcribe_file(str(path))

    # ---------- helpers used by tools ----------
    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, follow_redirects=True)

    def update_config(self, patch: dict) -> config_mod.Config:
        self.cfg = config_mod.apply_patch(self.cfg, patch)
        if self.persist_config:
            config_mod.save(self.cfg)
        self.router.update(self.cfg.brain)
        self.bus.publish("settings_changed", settings=config_mod.public_dump(self.cfg))
        for hook in (self.voice, self.mcp):
            if hook and hasattr(hook, "on_config"):
                try:
                    hook.on_config(self.cfg)
                except Exception as e:
                    log.warning("config hook failed: %s", e)
        return self.cfg

    def public_attachment(self, aid: str) -> dict:
        att = self.store.get(aid)
        return att.public() if att else {"id": aid, "name": "?", "missing": True}

    def mobile_clients(self) -> int:
        return sum(1 for c in self.clients.values() if c.get("client") == "mobile")

    def notify(self, title: str, body: str, url: str = "", speak: bool = True, target: str = "all") -> int:
        self.bus.publish("notify", title=title, body=body, url=url, target=target)
        if speak:
            self.speak(body)
        try:
            self.platform.notify(title, body)
        except Exception:
            pass
        return self.mobile_clients()

    def speak(self, text: str) -> None:
        if self.speaker:
            asyncio.get_running_loop().create_task(self.speaker.say(text))

    def maybe_speak(self, text: str, source: str) -> None:
        mode = self.cfg.voice.speak_mode
        if mode == "always" or (mode == "voice" and source in ("voice", "mobile_voice")):
            self.speak(text)

    def on_confirm_request(self, cid: str, desc: str) -> None:
        if self.speaker and self.cfg.voice.speak_mode != "never":
            self.speak(f"Potřebuji potvrzení: {desc}. Ano, nebo ne?")
        if self.voice and hasattr(self.voice, "expect_confirmation"):
            self.voice.expect_confirmation(cid)

    def _timer_fired(self, label: str) -> None:
        self.notify("⏲ " + label, f"{label} – čas vypršel!", target="all")
