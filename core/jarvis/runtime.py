"""Runtime: wires config, bus, memory, attachments, router, agent, timers, voice, scheduler, MCP."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from . import config as config_mod
from . import paths, redact, secrets, tools
from .agent import Agent
from .llm.local import LocalManager
from .tasks import TaskManager
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
        self.tasks = TaskManager(self)
        from .dictation import Dictation

        self.dictation = Dictation(self)
        from .notetaker import Notetaker

        self.notetaker = Notetaker(self)
        from .claude_bridge import ClaudeBridge

        self.claude = ClaudeBridge(self)
        self.local = LocalManager(self)
        self.timers = Timers(self._timer_fired)
        self.voice: Any = None        # voice.loop.VoiceLoop when available
        self.speaker: Any = None      # voice.tts.Speaker
        self.scheduler: Any = None    # scheduler.Scheduler
        self.mcp: Any = None          # mcp.client.McpManager
        self.clients: dict[str, dict] = {}  # ws client id -> info
        self.shelf: list[str] = []    # notch shelf attachment ids
        self.media_state: dict = {}
        self.ui_hook = None           # desktop host: show window (second launch)
        self.voice_mode = False       # dashboard voice mode is open → follow-up listening on
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
            from .tools.skills import load_all_skills, migrate_existing

            migrate_existing(self)
            load_all_skills(self.cfg.tools.approved_skills, self.cfg.tools.legacy_skills)
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

    # ---------- your own interface sounds (3.0) ----------
    SOUND_FILES = {"wake": ("probuzeni", "wake"), "listen": ("poslech", "listen"), "done": ("hotovo", "done"),
                   "error": ("chyba", "error"), "notify": ("upozorneni", "notify")}
    SOUND_EXT = (".wav", ".mp3", ".ogg")

    def sounds_dir(self):
        d = paths.sub("sounds")
        readme = d / "PRECTI-ME.txt"
        if not readme.exists():
            readme.write_text(
                "Vlastní zvuky JARVISe\n\nDej sem soubor .wav, .mp3 nebo .ogg s jedním z těchto jmen a JARVIS ho použije místo svého zvuku:\n"
                "  probuzeni  – probuzení („Hey Jarvis“)\n  poslech    – začal poslouchat\n  hotovo     – úkol hotový\n"
                "  chyba      – něco se nepovedlo\n  upozorneni – upozornění\n\nNapř. hotovo.mp3. Krátké zvuky (do 2 s) fungují nejlíp.\n",
                encoding="utf-8")
        return d

    def custom_sounds(self) -> dict[str, str]:
        d = paths.sub("sounds")
        files = {f.stem.lower(): f.name for f in d.iterdir() if f.suffix.lower() in self.SOUND_EXT} if d.exists() else {}
        return {snd: files[n] for snd, names in self.SOUND_FILES.items() for n in names if n in files}

    def open_sounds_folder(self) -> None:
        try:
            self.platform.open_path(str(self.sounds_dir()))
        except Exception as e:
            log.warning("sounds folder: %s", e)

    # ---------- what's new (once after each feature version) ----------
    def whats_new_due(self) -> str:
        """'3.0' when this major.minor has not been introduced yet, else ''."""
        from . import __version__

        mm = ".".join(__version__.split(".")[:2])
        row = self.db.one("SELECT v FROM kv WHERE k='whats_new_seen'")
        return "" if row and row["v"] == mm else mm

    def whats_new_seen(self) -> None:
        mm = self.whats_new_due()
        if mm:
            self.db.exec("INSERT OR REPLACE INTO kv VALUES ('whats_new_seen', ?)", (mm,))

    # ---------- weekly recap (Mondays) ----------
    def recap_due(self) -> bool:
        """True from Monday until the recap of last week was opened (and only when there was something)."""
        from .dictation import recap, week_bounds

        start, _ = week_bounds()
        row = self.db.one("SELECT v FROM kv WHERE k='recap_seen'")
        if row and row["v"] == start.isoformat():
            return False
        try:
            return not recap(self)["empty"]
        except Exception:
            return False

    def recap_seen(self) -> None:
        from .dictation import week_bounds

        self.db.exec("INSERT OR REPLACE INTO kv VALUES ('recap_seen', ?)", (week_bounds()[0].isoformat(),))

    def _transcribe_file(self, path) -> str:
        stt = getattr(self.voice, "transcriber", None) if self.voice else None
        if stt is None:
            raise RuntimeError("rozpoznávání řeči není dostupné (hlasový modul neběží)")
        return stt.transcribe_file(str(path))

    # ---------- helpers used by tools ----------
    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, follow_redirects=True)

    def update_config(self, patch: dict) -> config_mod.Config:
        was_local = self.cfg.brain.local_enabled
        self.cfg = config_mod.apply_patch(self.cfg, patch)
        if was_local and not self.cfg.brain.local_enabled:
            try:
                asyncio.get_running_loop().create_task(self.local.unload())
            except RuntimeError:
                pass
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

    def stop_all(self) -> None:
        """Emergency STOP (spec §4.4): everything JARVIS is doing stops now."""
        self.agent.drop_queued()
        self.agent.stop()
        if self.speaker:
            self.speaker.stop()
        if self.voice and hasattr(self.voice, "cancel_capture"):
            self.voice.cancel_capture()
        try:
            self.platform.release_all_input()
        except Exception as e:
            log.warning("release input: %s", e)
        if getattr(self, "scheduler", None):
            self.scheduler.pause_for(600)
        self.bus.publish("stopped")

    def speak(self, text: str, lang: str = "cs") -> None:
        if self.speaker:
            asyncio.get_running_loop().create_task(self.speaker.say(text, lang))

    def maybe_speak(self, text: str, source: str, lang: str = "cs") -> None:
        mode = self.cfg.voice.speak_mode
        if mode == "always" or (mode == "voice" and source in ("voice", "mobile_voice")):
            self.speak(text, lang)

    def on_confirm_request(self, cid: str, desc: str) -> None:
        if self.speaker and self.cfg.voice.speak_mode != "never":
            self.speak(f"Potřebuji potvrzení: {desc}. Ano, nebo ne?")
        if self.voice and hasattr(self.voice, "expect_confirmation"):
            self.voice.expect_confirmation(cid)

    def _timer_fired(self, label: str) -> None:
        self.notify("⏲ " + label, f"{label} – čas vypršel!", target="all")
