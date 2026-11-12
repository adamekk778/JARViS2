"""Runtime: wires config, bus, memory, attachments, router, agent, timers, voice, scheduler, MCP."""
from __future__ import annotations

import asyncio
import logging
import sys
import time
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


PRESET_LABEL = {"groq": "Groq", "gemini": "Gemini", "openrouter": "OpenRouter", "openai": "OpenAI", "anthropic": "Claude",
                "omniroute": "OmniRoute", "ollama": "Ollama"}


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
        from .pccontrol import PcControl

        self.pc_control = PcControl(self)      # 3.12 "JARVIS právě ovládá tvůj PC": frame + take over / stop
        from .meetings import Meetings

        self.meetings = Meetings(self)         # 3.12 chytrý režim schůzky
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
        self.lyrics_state: dict = {}     # 3.12: synced lyrics of the song playing (for the notch)
        self.ui_hook = None           # desktop host: show window (second launch)
        self.voice_mode = False       # dashboard voice mode is open → follow-up listening on
        from .mood import MoodEngine

        self.mood = MoodEngine(self)
        self.updater: Any = None
        from .stark import Guardian

        self.guardian = Guardian(self)
        from .powers import Activity

        self.activity = Activity(self)
        self.selection: dict = {}      # the last selected text JARVIS copied (and the window it came from)
        from .calendar_ import Calendar
        from .mail import Mail

        self.mail = Mail(self)
        self.calendar = Calendar(self)
        from .phone import PhoneLink

        self.phone = PhoneLink(self)   # 3.4: rings, dials, SMS / WhatsApp, the phone's notifications
        from .automations import Automations

        self.automations = Automations(self)   # 3.5: "když … tak …"
        from .home import Home

        self.home = Home(self)                 # 3.5: Home Assistant
        self.skill_note = ""                   # OMEGA Skill Forge: why the next skill version was saved
        from .missions import Missions
        from .privacy import MicLog
        from .usage import Usage

        self.usage = Usage(self)               # OMEGA 178: AI usage ledger and the daily limit
        self.router.on_usage = self.usage.record
        self.router.gate = self.usage.blocked
        # a provider's minute limit: say so while JARVIS waits instead of going quiet (or giving up)
        self.router.on_switch = self._brain_switched
        self.router.on_wait = lambda pid, secs: self.notify(
            f"{PRESET_LABEL.get(pid, pid)} – minutový limit", f"Čekám {round(secs)} s a pokračuju v úkolu.", speak=False)
        from . import aiplus

        aiplus.install(self)                   # OMEGA 577 / 584 / P15.10: local queue, answer cache, adaptive local models
        from .sysplus import ScreenShare

        self.screen_share = ScreenShare(self)  # OMEGA P9.08: the screen to the phone, only while switched on
        from .uixplus import Attention

        self.attention = Attention(self)       # OMEGA 753 / 234: notices wait while you are focused
        self.mochi_at = "pc"                   # OMEGA 195: where Mochi is right now (pc / phone)
        self.on_anchor = None                  # OMEGA 752: the desktop host moves the notch above a window
        self.voice_mood: dict | None = None    # OMEGA P3.12: last read of the tone of voice (when enabled)
        self.missions = Missions(self)         # OMEGA 211–225: queue, deadlines, resume
        self.miclog = MicLog(self)             # OMEGA 679: when the microphone listened
        from .knowledge import Knowledge
        from .perf import PerfHistory

        self.knowledge = Knowledge(self)       # OMEGA §04: categories, sources, projects, conflicts, timeline, search
        from .learning import Learning

        self.learning = Learning(self)         # OMEGA §10 / §36: flashcards, tests, weak spots, exam plans

        self.perf = PerfHistory(self)          # OMEGA 312: a light performance sample every 5 minutes
        import collections as _collections

        self.recent_changes: _collections.deque = _collections.deque(maxlen=20)   # 3.12: JARVIS's own file edits (diffs)
        from .netwatch import NetWatch

        self.netwatch = NetWatch(self)         # OMEGA 708/709/719: watched webs, certificates, line loss history
        from .link.manager import Link

        self.link = Link(self)                 # 3.12 JARVIS Link: the phone reaches the PC from anywhere (own Tailscale)
        from .remotedesk import RemoteDesk

        self.remote_desk = RemoteDesk(self)    # 3.12 Vzdálená plocha v telefonu
        from .photobackup import PhotoBackup

        self.photo_backup = PhotoBackup(self)  # 3.12 Záloha fotek z telefonu
        from .healthwatch import HealthWatch

        self.health = HealthWatch(self)        # 3.12 Zdraví PC v telefonu
        from .guard import Guard

        self.guard = Guard(self)               # 3.12 Hlídání PC (switched on from the phone)
        from .phonemirror import PhoneMirror

        self.phone_mirror = PhoneMirror(self)  # 3.12 Telefon na monitoru PC
        from .nightcare import NightCare

        self.nightcare = NightCare(self)       # 3.12 Noční údržba PC
        self.memory.set_private(self.cfg.privacy.private_mode)
        tools.load_builtin()

    # ---------- lifecycle ----------
    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.bus.bind_loop(self.loop)
        from . import diagnostics

        diagnostics.start_stall_watch(self, self.loop)   # a stuck loop logs where it is stuck
        self.store.transcribe = self._transcribe_file
        self.mood.start()
        self.guardian.start()
        self.activity.start()
        self.activity.prune()
        self.mail.start()
        self.calendar.start()
        self.automations.start()
        self.missions.start()
        from . import privacy

        self._privacy_task = asyncio.get_running_loop().create_task(privacy.watch(self))
        from . import sysplus

        self._sys_tasks = [asyncio.get_running_loop().create_task(sysplus.watch_loop(self)),    # OMEGA P10.03
                           asyncio.get_running_loop().create_task(sysplus.music_loop(self)),    # OMEGA P12.02
                           asyncio.get_running_loop().create_task(sysplus.volume_loop(self))]   # 3.11 volume bar
        from . import netwatch

        self._sys_tasks.append(asyncio.get_running_loop().create_task(netwatch.loop(self)))   # OMEGA 708/709/719
        from . import focusguard

        self._sys_tasks.append(asyncio.get_running_loop().create_task(focusguard.loop(self)))   # 3.12 focus guard
        from . import meetings

        self._sys_tasks.append(asyncio.get_running_loop().create_task(meetings.loop(self)))     # 3.12 calls → notes
        from . import fsplus

        self._sys_tasks.append(asyncio.get_running_loop().create_task(fsplus.version_loop(self)))   # OMEGA 328
        self._sys_tasks.append(asyncio.get_running_loop().create_task(self.link.start()))          # 3.12 JARVIS Link
        self._sys_tasks.append(asyncio.get_running_loop().create_task(self.health.run()))          # 3.12 Zdraví PC
        self._sys_tasks.append(asyncio.get_running_loop().create_task(self.guard.loop()))          # 3.12 Hlídání PC
        from . import morning

        self._sys_tasks.append(asyncio.get_running_loop().create_task(morning.loop(self)))         # 3.12 Ranní souhrn
        self._sys_tasks.append(asyncio.get_running_loop().create_task(self.nightcare.loop()))      # 3.12 Noční údržba
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
        if sys.platform == "win32" and self.cfg.stark.layout_memory:
            try:              # OMEGA 31: the layout as it was when JARVIS (and usually Windows) shut down
                from . import pccare

                pccare.autosave_layout(self)
            except Exception as e:  # noqa: BLE001
                log.debug("layout autosave: %s", e)
        self.mood.stop()
        self.guardian.stop()
        self.activity.stop()
        self.mail.stop()
        self.calendar.stop()
        self.automations.stop()
        self.missions.stop()
        if getattr(self, "_privacy_task", None):
            self._privacy_task.cancel()
        for t in getattr(self, "_sys_tasks", []):
            t.cancel()
        if getattr(self, "screen_share", None):
            self.screen_share.stop()
        if self.scheduler:
            self.scheduler.stop()
        if self.mcp:
            await self.mcp.stop()
        try:
            await self.link.stop()            # also gives the router its port back
        except Exception as e:  # noqa: BLE001
            log.debug("link stop: %s", e)

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

    def _brain_switched(self, errors: dict, now: str) -> None:
        """3.12 an AI ran out (limit) and another carries on: say so once an hour, not silently and not every message."""
        import re as _re

        limited = [p for p, why in errors.items() if _re.search(r"429|413|limit|quota|too many", str(why), _re.I)]
        if not limited:
            return
        key = (tuple(sorted(limited)), now)
        seen = getattr(self, "_switch_said", {})
        if time.time() - seen.get(key, 0) < 3600:
            return
        seen[key] = time.time()
        self._switch_said = seen
        names = ", ".join(PRESET_LABEL.get(p, p) for p in limited)
        self.notify("Přepínám mozek", f"{names} má dnes vyčerpaný limit – pokračuju přes {PRESET_LABEL.get(now, now)}.", speak=False)

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
        from . import tlsctx

        return httpx.AsyncClient(transport=self.transport, follow_redirects=True, verify=tlsctx.context())

    def update_config(self, patch: dict) -> config_mod.Config:
        was_local = self.cfg.brain.local_enabled
        old_cfg = self.cfg
        self.cfg = config_mod.apply_patch(self.cfg, patch)
        if "privacy" in patch:
            self.memory.set_private(self.cfg.privacy.private_mode)
        if "stark" in patch or "automations" in patch:
            from . import skillforge

            skillforge.on_config_change(self, old_cfg, self.cfg)   # every saved change of a skill / automation = a new version
        if was_local and not self.cfg.brain.local_enabled:
            try:
                asyncio.get_running_loop().create_task(self.local.unload())
            except RuntimeError:
                pass
        if self.persist_config:
            config_mod.save(self.cfg)
        self.router.update(self.cfg.brain)
        self.mail.sync()
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

    def notify(self, title: str, body: str, url: str = "", speak: bool = True, target: str = "all", urgent: bool = False) -> int:
        """urgent = something the user asked for at this time (a timer, an alarm, a reminder): always said aloud."""
        att = getattr(self, "attention", None)
        if att is not None and target == "all" and not att.gate(title, body, urgent):
            return 0                                   # kept for the summary after the focus / meeting / game
        self.bus.publish("notify", title=title, body=body, url=url, target=target)
        if target == "all" and self.user_away():          # 3.12 away from the PC → it comes to the phone
            self.phone_push("notify", title=title[:80], body=body[:400])
        if speak and not urgent and getattr(self.cfg.stark, "smart_quiet", True):
            from .proactive import quiet_reason      # OMEGA 500: shown, but not said aloud in a meeting / at night / in a game

            try:
                speak = not quiet_reason(self)
            except Exception:  # noqa: BLE001 – never lose a notification over this
                pass
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
        if getattr(self, "remote_desk", None) is not None and self.remote_desk.on:
            self.remote_desk.stop()           # STOP also ends a phone driving the PC
        self.pc_control.reset()
        if self.speaker:
            self.speaker.stop()
        if self.voice and hasattr(self.voice, "cancel_capture"):
            self.voice.cancel_capture()
        subs = getattr(self, "live_subs", None)
        if subs is not None and subs.on:        # 3.12: subtitles listen to what the PC plays → stop them too
            subs.stop()
        try:
            self.platform.release_all_input()
        except Exception as e:
            log.warning("release input: %s", e)
        if getattr(self, "scheduler", None):
            self.scheduler.pause_for(600)
        self.bus.publish("stopped")

    def set_anchor(self, win: dict | None) -> None:
        """OMEGA 752 / 084: JARVIS works in this window → the notch (and Mochi) move above it; None = back to the middle."""
        if not getattr(self.cfg.notch, "follow_window", True):
            win = None
        if (win or {}).get("hwnd") == (getattr(self, "_anchor", None) or {}).get("hwnd"):
            return
        self._anchor = win
        try:
            w, _ = self.platform.screen_size()
        except Exception:  # noqa: BLE001
            w = 1920
        self.bus.publish("anchor", title=(win or {}).get("title", ""), cx=round((win["x"] + win["w"] / 2) / w, 3) if win else None)
        if self.on_anchor:
            try:
                self.on_anchor(win)
            except Exception as e:  # noqa: BLE001
                log.debug("anchor: %s", e)

    def speak(self, text: str, lang: str = "cs") -> None:
        if getattr(self.cfg.appearance, "captions", False) and text.strip():      # OMEGA 790: live captions
            from .uixplus import caption_chunks, caption_timing

            self.bus.publish("caption", who="jarvis", lines=caption_timing(caption_chunks(text)))
        if self.speaker:
            asyncio.get_running_loop().create_task(self.speaker.say(text, lang))

    def wants_speech(self, source: str) -> bool:
        if source == "headset":           # 3.12 talking through the phone: the answer plays there, the PC stays quiet
            return False
        mode = self.cfg.voice.speak_mode
        return mode == "always" or (mode == "voice" and source in ("voice", "mobile_voice"))

    def maybe_speak(self, text: str, source: str, lang: str = "cs") -> None:
        if self.wants_speech(source):
            self.speak(text, lang)

    def speech_stream(self, source: str, lang: str = "cs"):
        """3.12 an answer that will be spoken: speech starts with its first sentence (voice/stream.py)."""
        if not self.speaker or not self.wants_speech(source) or not getattr(self.cfg.voice, "stream_speech", True):
            return None
        from .voice.stream import SpeechStream

        return SpeechStream(self, lang)

    # ---------- 3.12 away from the PC: notices and confirmations come to the phone ----------
    AWAY_S = 120

    def user_away(self) -> bool:
        try:
            return float(self.platform.idle_seconds()) >= self.AWAY_S
        except Exception:  # noqa: BLE001
            return False

    def phone_push(self, kind: str, **data) -> bool:
        """A command for the paired phone – only when its link is alive (no pile of commands for a phone that is off)."""
        phone = getattr(self, "phone", None)
        if phone is None or (kind in ("notify", "confirm") and not getattr(self.cfg.phone_link, "away_push", True)):
            return False
        if not (phone.link_alive() or self.mobile_clients()):
            return False
        phone.send(kind, **data)
        return True

    def on_confirm_request(self, cid: str, desc: str) -> None:
        if self.user_away():
            self.phone_push("confirm", cid=cid, text=desc[:300])
        if self.speaker and self.cfg.voice.speak_mode != "never":
            self.speak(f"Potřebuji potvrzení: {desc}. Ano, nebo ne?")
        if self.voice and hasattr(self.voice, "expect_confirmation"):
            self.voice.expect_confirmation(cid)

    def _timer_fired(self, label: str) -> None:
        self.notify("⏲ " + label, f"{label} – čas vypršel!", target="all", urgent=True)
