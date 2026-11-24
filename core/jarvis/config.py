"""Settings: config.toml in the data dir, validated by pydantic."""
from __future__ import annotations

import copy
import secrets as _secrets
import tomllib
from typing import Any, Literal

import tomli_w
from pydantic import BaseModel, Field, ValidationError, model_validator

from . import paths


# Groq models switched off in 2026 → the replacement Groq names (console.groq.com/docs/deprecations)
GROQ_BEST, GROQ_FAST = "openai/gpt-oss-120b", "openai/gpt-oss-20b"
GROQ_RETIRED = {"llama-3.3-70b-versatile": GROQ_BEST, "llama3-70b-8192": GROQ_BEST, "qwen/qwen3-32b": GROQ_BEST,
                "moonshotai/kimi-k2-instruct": GROQ_BEST, "moonshotai/kimi-k2-instruct-0905": GROQ_BEST,
                "meta-llama/llama-4-scout-17b-16e-instruct": GROQ_BEST, "meta-llama/llama-4-maverick-17b-128e-instruct": GROQ_BEST,
                "deepseek-r1-distill-llama-70b": GROQ_BEST, "llama-3.1-8b-instant": GROQ_FAST, "llama3-8b-8192": GROQ_FAST,
                "gemma2-9b-it": GROQ_FAST}
# 3.12 other services switched models off too (Nov 2026): a saved dead model moves to one that exists – Gemini to its
# pinned newest Flash (Google asks for versioned names; a "-latest" alias can point at a switched-off model), OpenRouter to its router of free models, NVIDIA to GPT-OSS
RETIRED = {
    "gemini": {m: "gemini-3.8-flash" for m in ("gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash", "gemini-2.5-flash",
                                               "gemini-2.5-pro", "gemini-1.5-flash-latest", "gemini-pro", "gemini-flash-latest",
                                               "gemini-pro-latest", "gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3.7-flash")}
              | {m: "gemini-3.5-flash-lite" for m in ("gemini-1.5-flash-8b", "gemini-2.0-flash-lite", "gemini-2.5-flash-lite",
                                                     "gemini-flash-lite-latest", "gemini-3.1-flash-lite-preview")},
    "openrouter": {"meta-llama/llama-3.3-70b-instruct:free": "openrouter/free", "deepseek/deepseek-chat:free": "openrouter/free",
                   "google/gemini-2.0-flash-exp:free": "openrouter/free", "meta-llama/llama-3.1-8b-instruct:free": "openrouter/free"},
    "nvidia": {"meta/llama-3.3-70b-instruct": "openai/gpt-oss-20b", "meta/llama-3.1-70b-instruct": "openai/gpt-oss-20b",
               "meta/llama-3.1-405b-instruct": "openai/gpt-oss-20b"},
}


class ProviderCfg(BaseModel):
    id: str
    preset: str = "custom"
    base_url: str = ""
    model: str = ""
    vision_model: str = ""
    fast_model: str = ""
    enabled: bool = True


def _default_providers() -> list[ProviderCfg]:
    return [
        ProviderCfg(id="omniroute", preset="omniroute", base_url="http://localhost:20128/v1", model="auto"),
        ProviderCfg(id="ollama", preset="ollama", base_url="http://localhost:11434", model="qwen3:4b"),
    ]


class General(BaseModel):
    user_name: str = ""
    address_as: str = "pane"
    language: str = "cs"
    personality: Literal["jarvis", "friday", "friend", "brief", "custom"] = "jarvis"
    custom_prompt: str = ""
    autostart: bool = True
    city: str = "Praha"
    update_url: str = "https://api.github.com/repos/adamekk778/JARViS2/releases/latest"
    auto_update: bool = True       # 3.12 a new version installs itself at night (2–6 h) while nobody uses the PC
    update_channel: Literal["stable", "beta"] = "stable"   # 3.14 beta: test builds come first (návrh 13)
    auto_rollback: bool = True     # 3.14 the check after an update finds the notch / voice broken → previous version (12)
    night_care: bool = True        # 3.12 Noční údržba: old temp files, disk health, waiting Windows updates (once a night)
    onboarded: bool = False        # 3.12 the first-run guide was finished or skipped
    traits: dict[str, int] = Field(default_factory=lambda: {"humor": 1, "formal": 1, "brevity": 1})   # 3.14 0–2 each (29)


class Brain(BaseModel):
    providers: list[ProviderCfg] = Field(default_factory=_default_providers)
    chain: list[str] = Field(default_factory=lambda: ["omniroute", "ollama"])
    temperature: float = 0.6
    max_tokens: int = 2048
    offline_only: bool = False
    first_token_timeout: float = 15.0
    local_enabled: bool = True     # off: local models (Ollama, LM Studio) are skipped and unloaded
    local_mode: Literal["eco", "balanced", "performance"] = "balanced"
    local_gpu: str = ""            # result of the last GPU test: "gpu" | "cpu" | ""
    local_gpu_layers: int = -1     # OMEGA 574: layers on the graphics card (-1 = let Ollama decide)
    save_limits: bool = True       # 3.12 Šetřič limitů: background work (chat summaries) by the AI on this PC when its backup is on
    adaptive_local: bool = True    # OMEGA P15.10: local models step aside during games, on low battery, when RAM runs out
    quick_preface: bool = True     # 3.14 a hard question asked aloud: one sentence at once from the quick model (23)
    learn_corrections: bool = True  # 3.14 "ne, myslel jsem…" → a rule for next time (24)
    verify_answers: bool = True    # 3.14 claims the read web pages do not support are marked under the answer (26)
    second_opinion: bool = True    # 3.14 money / health / law / deleting: weigh it twice, ask other AIs (30)
    private_local: bool = True     # 3.14 passwords, health, bank details → only the AI on this PC, when it runs (32)
    only_primary: bool = False     # 3.14 "Jen tento mozek": only the brain you picked answers (no backup AIs)
    split: bool = False            # 3.14 chytré rozdělení: easy questions → split_easy, hard tasks → split_hard
    split_easy: str = ""           # a provider id (e.g. "ollama" – free, on this PC)
    split_hard: str = ""           # a provider id (e.g. "anthropic" – the strongest)


class Voice(BaseModel):
    enabled: bool = True
    emotion: bool = False          # OMEGA P3.12: read the tone of voice (tired / tense / lively) – off unless you turn it on
    wake_word: bool = True
    wake_word_model: str = "hey_jarvis"
    wake_threshold: float = 0.5
    input_device: str = ""
    stt_model: str = "small"
    stt_language: str = "cs"
    stt_provider: Literal["auto", "local", "groq"] = "auto"   # 3.12 auto: Groq with a Groq key, else on this PC
    stt_download_ok: bool = False   # 3.12 the local speech model (~0.5 GB) downloads only after the user allows it
    tts_voice: str = "cs-CZ-AntoninNeural"
    piper_voice: str = "cs_CZ-jirka-medium"
    # voice studio: which engine speaks, an imported own Piper voice, an ElevenLabs voice, an effect on top
    tts_engine: Literal["edge", "piper", "elevenlabs"] = "edge"
    piper_custom: str = ""            # name of an imported voice in models/piper/custom (empty = piper_voice)
    eleven_voice_id: str = ""
    eleven_model: str = "eleven_multilingual_v2"
    effect: Literal["none", "jarvis", "radio", "robot", "hall"] = "none"
    tts_rate: str = "+0%"
    tts_pitch: str = "+0Hz"
    tts_volume: str = "+0%"
    speak_mode: Literal["always", "voice", "never"] = "voice"
    silence_seconds: float = 0.6     # 3.13 the answer starts sooner after you stop talking (was 0.8)
    silence_rev: int = 1            # fresh configs are already migrated (a saved 0 would undo your own 0.8 s later)
    followup: bool = False          # after an answer, listen 6 s more without the wake word
    game_quiet: bool = True         # 3.13 Herní režim: while a game runs, announcements wait and come as one line afterwards
    output_device: str = ""         # speaker name; empty = Windows default
    tts_voice_en: str = "en-GB-RyanNeural"
    piper_voice_en: str = "en_GB-alan-medium"
    noise_suppression: bool = True  # clean the recording before it is recognised (filter the hum and hiss)
    auto_gain: bool = True          # level a quiet / distant voice up before recognition
    echo_cancel: bool = True        # remove JARVIS's own voice from the microphone (talking over it works)
    barge_in: bool = True           # 3.13 start talking while JARVIS speaks → it stops and listens (needs echo_cancel)
    duck_media: bool = True         # turn other programs down while JARVIS listens or speaks
    duck_level: float = 0.3         # … to this share of their volume
    adaptive_tone: bool = True      # 3.14 slower and quieter at night, livelier in the morning (44)
    whisper_reply: bool = True      # 3.14 you whisper → JARVIS answers quietly (41)
    pronounce: list["Replacement"] = Field(default_factory=list)   # 3.14 how to say names / abbreviations (43)
    custom_wake: bool = False       # 3.14 your own wake word (recorded in Nastavení → Hlas), next to "Hey Jarvis" (37)
    owner_only: bool = True         # 3.14 a voice profile of the owner exists → risky actions by voice only in that voice (38)
    look_to_talk: bool = False      # 3.14 alone at the PC and looking at the screen → just talk, no wake word (camera, opt-in)
    camera_index: int = 0           # 3.14 which camera (0 = the first one)
    interpreter_out: str = ""       # 3.14 tlumočník: the virtual microphone device (e.g. "CABLE Input") for your translated voice


class NotchWidget(BaseModel):
    """3.14 a small tile in the notch: a read-only tool run every few minutes and its one-line answer (návrh 76)."""
    id: str
    name: str = "Widget"
    icon: str = "squares-four"
    tool: str = "weather"
    args: dict[str, Any] = Field(default_factory=dict)
    every_min: int = 15


class Notch(BaseModel):
    enabled: bool = True
    music_viz: bool = True         # OMEGA P12.02: bars moving with the music while something plays
    spectrum: bool = False         # 3.14 the bars from the real spectrum of what plays (loopback, 10× a second) (74)
    widgets: list[NotchWidget] = Field(default_factory=list)   # 3.14 your own tiles in Více (76)
    follow_window: bool = True     # OMEGA 752: while JARVIS works in a window, the notch moves above it
    edge_play: bool = True         # OMEGA 247: when nothing happens for a while, Mochi plays along the screen edge
    monitor: int = 0
    offset_x: int = 0
    width: int = 200
    height: int = 34
    expanded_width: int = 1000
    expanded_height: int = 410
    open_delay_ms: int = 150
    close_delay_ms: int = 400
    linger_s: float = 6.0
    hide_in_fullscreen: bool = True
    subs_translate: bool = True    # 3.12: subtitles of a foreign video translated to Czech (through the AI)
    subs_speak: bool = False       # 3.14: …and the translation read aloud (the video is turned down meanwhile)
    lyrics: bool = True            # 3.12: song lyrics in the notch, the line being sung marked by a running bar (LRCLIB)
    lyrics_translate: bool = True  # 3.12: a small Czech translation under a foreign line (the AI, once per song)
    lyrics_autosync: bool = True   # 3.14: the timing fitted to the singing by listening to the PC's sound once per song
    habit_ring: bool = False       # 3.12: today's habits as a small ring in the closed notch when nothing else is shown
    habit_ring_rev: int = 2        # 3.12: the ring was on by default once – switched off (the idle notch shows the eyes)
    # 3.12: the island's colour – the song's cover while music plays, and with "song_wall" the wallpaper otherwise
    tint: Literal["song_wall", "song", "black"] = "song_wall"
    tint_rev: int = 1               # fresh configs are already migrated (else your own "song" turned back next start)
    focus_guard: bool = True       # 3.12: while you focus, the notch blinks when YouTube, Netflix, TikTok… come to the front
    native_region_anim: bool = False   # 3.12: JARVIS animates the window outline itself (experimental, off: hung in CI)
    pinned: bool = False   # big panel stays open (also after restart)
    smooth_edges: bool = True   # replaced by `edges` (kept so older config files still load)
    # "hard" = the window is cut to the notch shape (works on every PC); "smooth" = per-pixel alpha with
    # anti-aliased curves, which on some PCs made Windows draw a grey box around the notch
    edges: Literal["hard", "smooth"] = "smooth"
    edges_rev: int = 1             # 3.12: saved "hard" (the 3.10.89 default, before the grey box was traced to Mica) → smooth once
    # 3.11: "island" = two glowing eyes + live info left / right and a home screen of big cards; "mochi" = the character
    style: Literal["dynamic", "island", "mochi"] = "dynamic"
    style_rev: int = 1             # 3.12: configs saved before Dynamic Island (0) move from "island" to "dynamic" once
    tiles: list[str] = Field(default_factory=lambda: [
        "ask", "media", "shelf", "quick", "timers", "system", "weather", "phone"])
    open_on: Literal["hover", "click"] = "hover"   # OMEGA 092: "click" = najetí myší panel neotevře (proti náhodnému otevření)
    tuck_minutes: int = 10                     # OMEGA 078: po kolika minutách klidu se postavička schová za okraj (0 = nikdy)
    app_actions: list[dict] = Field(default_factory=list)   # OMEGA 089: vlastní akce {app, label, text, icon}


class Appearance(BaseModel):
    theme: Literal["glass", "stark", "light"] = "glass"     # 3.12 glass: frosted panels over a soft aurora
    density: Literal["auto", "compact", "comfortable", "large"] = "auto"   # OMEGA 758: hustota a velikost rozhraní
    input_mode: Literal["auto", "mouse", "touch", "voice"] = "auto"      # OMEGA 522: ovládání myší / dotykem / hlasem
    captions: bool = False              # OMEGA 790: live captions of what JARVIS says and what it heard
    high_contrast: bool = False         # 3.14 stronger borders and text for weaker eyes (68)
    font_scale: float = 1.0             # 3.14 the whole interface larger (1.0–1.6) (68)
    gestures: bool = False              # OMEGA 188: hand gestures through the PC camera (off unless turned on; red dot while on)
    accent: str = "#4f8dff"    # JARVIS blue (2.2); the 2.0 default cyan is migrated to it
    animations: Literal["full", "reduced", "auto"] = "full"   # auto = reduced on battery (OMEGA 240 / 764)
    sounds: bool = True        # subtle interface sounds in the notch
    sound_volume: int = 30     # 0–100
    spatial_sounds: bool = True   # OMEGA 102 / 761: sounds come from where things happen (phone right, notch centre…)

    theme_rev: int = 0                  # 3.12: the glass look came – once, a saved "stark" (the old default) becomes "glass"

    @model_validator(mode="before")
    @classmethod
    def _new_default_accent(cls, data: Any) -> Any:
        if isinstance(data, dict) and str(data.get("accent", "")).lower() == "#2ee6ff":
            data = {**data, "accent": "#4f8dff"}
        if isinstance(data, dict) and int(data.get("theme_rev") or 0) < 1:
            data = {**data, "theme_rev": 1, **({"theme": "glass"} if data.get("theme", "stark") == "stark" else {})}
        return data


class Hotkeys(BaseModel):
    talk: str = "ctrl+alt+space"
    chat: str = "ctrl+alt+j"
    hud: str = "ctrl+alt+h"
    selection: str = "ctrl+alt+e"   # what to do with the selected text (fix, translate, explain…)
    stop: str = "esc"
    stop_all: str = "ctrl+alt+x"
    notch_toggle: str = "ctrl+alt+n"   # 3.12: hide / show the notch (also over a game or a video)
    subtitles: str = "ctrl+alt+t"      # 3.12: subtitles of what the PC plays, in the notch
    screen_ask: str = "ctrl+alt+s"     # 3.12: pick a part of the screen and ask about it
    device_listen: str = "ctrl+alt+l"  # 3.12: write down everything the PC plays, then a prompt / summary / notes


class Tools(BaseModel):
    disabled: list[str] = Field(default_factory=list)
    always_confirm: list[str] = Field(default_factory=list)
    trusted: list[str] = Field(default_factory=list)
    full_trust: bool = False    # 3.13 Plná důvěra: PC actions without asking (see trust.py for what still asks)
    sandbox_code: bool = True   # 3.14 run_python in a fenced process: no programs, no network, writes only in its folder (10)
    sandbox_network: bool = False   # 3.14 …but with the network allowed
    computer_use: bool = True   # deprecated: migrated to permissions.input
    allowed_folders: list[str] = Field(default_factory=list)
    approved_skills: list[str] = Field(default_factory=list)   # skills allowed to load (spec §10)
    trusted_publishers: list[str] = Field(default_factory=list)   # 3.14 fingerprints of skill authors you trust
    legacy_skills: list[str] = Field(default_factory=list)     # 2.0 skills: keep their full ctx (platform, store)


class McpServer(BaseModel):
    name: str
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    trusted: bool = False   # OMEGA 686: untrusted servers ask before every action; their output is always data


class Webhook(BaseModel):
    """OMEGA 590: an incoming webhook (its secret lives in the OS secure storage, never in the config)."""
    id: str
    name: str = "Webhook"
    action: Literal["notify", "automation"] = "notify"
    enabled: bool = True


class Peer(BaseModel):
    """OMEGA P9.09: another PC with JARVIS (its pairing key lives in the OS secure storage)."""
    name: str
    url: str


class Integrations(BaseModel):
    mcp: list[McpServer] = Field(default_factory=list)
    webhooks: list[Webhook] = Field(default_factory=list)
    peers: list[Peer] = Field(default_factory=list)
    image_provider: str = "pollinations"
    obs_url: str = "ws://127.0.0.1:4455"   # 3.14 OBS Studio's WebSocket server (its password is in the keyring as "obs")
    skill_catalogs: list[str] = Field(default_factory=list)   # 3.14 catalogs of skill packages (JSON lists on the web)


class Device(BaseModel):
    """OMEGA 184 / 185 / 402: a paired phone with its own key (only a hash is stored) – revocable one by one."""
    id: str
    name: str = "Telefon"
    token_hash: str = ""
    created: float = 0.0
    last_seen: float = 0.0


class Guest(BaseModel):
    """OMEGA 727: a temporary pairing (someone else's phone) – only music and volume, expires by itself."""
    id: str
    name: str = "Host"
    token_hash: str
    expires: float


class Phone(BaseModel):
    token: str = Field(default_factory=lambda: _secrets.token_urlsafe(32))
    port: int = 8765
    devices: list[Device] = Field(default_factory=list)
    shared_folders: list[str] = Field(default_factory=list)   # OMEGA 415: PC folders the phone may browse (read-only)
    # OMEGA 419: what a paired phone may do on the PC (permission areas); a switched-off one is refused from the phone only
    allowed: list[str] = Field(default_factory=lambda: ["apps", "input", "screen", "files_read", "files_write", "shell",
                                                         "network", "system", "home"])
    guests: list[Guest] = Field(default_factory=list)
    approve_nearby_only: bool = False   # OMEGA 733: approvals from the phone only on the home network (not over the internet)


class MemoryCfg(BaseModel):
    context_messages: int = 20
    max_upload_mb: int = 200
    embed_model: str = ""        # OMEGA 038: a LOCAL Ollama embedding model for search by meaning ("" = any installed one)


class CustomReaction(BaseModel):
    """OMEGA 750: the user's own reaction – when it happens and what the character does."""
    name: str = ""
    when: Literal["notify", "message", "mail"] = "notify"
    match: str = ""                  # comma-separated words; empty = always
    enabled: bool = True
    look: dict = Field(default_factory=lambda: {"eyes": "wide", "icon": "star", "motion": "hop", "color": "", "seconds": 3})


class Character(BaseModel):
    color: Literal["black", "midnight", "violet", "rose", "white", "blue", "orange", "green", "amber", "cyan"] = "black"
    glow: str = ""            # empty = JARVIS blue (#4f8dff)
    outfit: Literal["auto", "none", "beanie", "crown", "party", "santa", "witch", "sunglasses", "bow", "cap",
                    "headphones", "graduate", "flower", "halo"] = "auto"   # 3.14 the last four unlock with Mochi's level
    size: Literal["S", "M", "L"] = "M"
    personality: Literal["vyvážený", "hravý", "klidný", "profesionální"] = "vyvážený"   # OMEGA 242: how lively he is
    ambient: bool = True      # OMEGA 739–741: accessories by weather and time of day, dimmer at night
    reactions: list[CustomReaction] = Field(default_factory=list)
    pet_mode: bool = False    # 3.1: the desktop pet was removed; always False

    @model_validator(mode="before")
    @classmethod
    def _no_pet(cls, data: Any) -> Any:
        return {**data, "pet_mode": False} if isinstance(data, dict) and data.get("pet_mode") else data
    pet_x: int = -1
    pet_y: int = -1


class Snippet(BaseModel):
    trigger: str              # say this…
    text: str                 # …and this whole text is pasted


class Replacement(BaseModel):
    src: str                  # what the recognizer writes
    dst: str                  # what you want instead


Voice.model_rebuild()         # 3.14 Voice.pronounce uses Replacement, defined after it


class Dictation(BaseModel):
    """Hold a key anywhere, speak, let go: the words are pasted where you type (3.0)."""
    enabled: bool = True
    key: Literal["right ctrl", "right alt", "caps lock", "scroll lock", "f8", "f9", "f10"] = "right ctrl"
    hands_free: bool = True           # tap twice: dictate without holding, tap once to paste
    cleanup: Literal["off", "natural", "polished"] = "off"   # AI clean-up of what you said
    keep_days: int = 30               # history (0 = keep nothing)
    words: list[str] = Field(default_factory=list)            # names the recognizer must spell right
    replacements: list[Replacement] = Field(default_factory=list)
    snippets: list[Snippet] = Field(default_factory=list)
    paste_again: str = "ctrl+alt+v"
    sounds: bool = True


class ClaudeCfg(BaseModel):
    """Claude Code in the notch (3.0)."""
    enabled: bool = True
    approvals: bool = True            # Allow / Deny from the notch and the phone
    notify_done: bool = True
    always_allow: list[str] = Field(default_factory=list)   # tools allowed with "Vždy" (e.g. "Read")


class ProtocolStep(BaseModel):
    """One step of a protocol: JARVIS says something, runs one of his tools, or gets a task for the AI."""
    say: str = ""
    tool: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    ask: str = ""
    when: Literal["", "playing"] = ""   # "playing": only while music/video plays (e.g. pause it)
    needs: list[int] = Field(default_factory=list)   # 3.7: indices of steps that must finish first (steps without
    #                                                  a dependency between them run at the same time)


class Protocol(BaseModel):
    id: str
    name: str
    icon: str = "lightning"
    steps: list[ProtocolStep] = Field(default_factory=list)


def _default_protocols() -> list[Protocol]:
    S = ProtocolStep
    return [
        Protocol(id="rano", name="Ranní", icon="sun-horizon", steps=[S(tool="briefing")]),
        Protocol(id="prace", name="Pracovní režim", icon="briefcase", steps=[
            S(tool="media_control", args={"action": "play_pause"}, when="playing"),
            S(tool="volume", args={"action": "set", "level": 25}),
            S(say="Pracovní režim aktivní. Ztlumil jsem zvuk a hudbu jsem pozastavil. Soustřeďte se, pane.")]),
        Protocol(id="hry", name="Herní režim", icon="game-controller", steps=[
            S(tool="volume", args={"action": "set", "level": 60}),
            S(say="Herní režim aktivní. Hlasitost na šedesát procent. Hodně štěstí, pane.")]),
        Protocol(id="party", name="Párty", icon="confetti", steps=[
            S(say="Spouštím protokol Párty."),
            S(tool="volume", args={"action": "set", "level": 70}),
            S(tool="youtube_play", args={"query": "party mix 2026"})]),
        Protocol(id="noc", name="Dobrou noc", icon="moon-stars", steps=[
            S(tool="media_control", args={"action": "play_pause"}, when="playing"),
            S(tool="set_dark_mode", args={"dark": True}),
            S(tool="volume", args={"action": "set", "level": 15}),
            S(say="Dobrou noc, pane. Ztlumil jsem zvuk a přepnul na tmavý režim.")]),
    ]


class Stark(BaseModel):
    """3.2 "Stark" features: protocols, the morning briefing, the guardian and the HUD."""
    boot_greeting: bool = True          # "JARVIS online" when the PC app starts
    briefing_auto: bool = True          # the first time you are at the PC in the morning
    briefing_speak: bool = True
    briefing_news: bool = True          # three headlines (Google News RSS)
    guardian: bool = True               # warns about battery, CPU, RAM, disk, internet
    guardian_speak: bool = True
    battery_low: int = 20
    disk_low_gb: int = 5
    network_watch: bool = False         # 3.5: tell me when a device I have not seen joins the home network
    hardware_watch: bool = True         # OMEGA 290: say when a USB device / monitor / disk is plugged in or removed
    perf_history: bool = True           # OMEGA 312: CPU / RAM / disk every 5 minutes, kept 30 days
    smart_quiet: bool = True            # OMEGA 500: no speaking at night, in a meeting, in focus mode or over a fullscreen app
    attention_aware: bool = True        # OMEGA 753: non-urgent notices wait during a meeting / full-screen app, then come as a summary
    layout_memory: bool = True          # OMEGA 31: keep the window layout, offer it back after a restart
    crash_help: bool = True             # OMEGA 32: a program crashed 3× today → offer to find out why
    evening_review: bool = True         # 3.14 a short evening review: done, left, tomorrow, unprepared meetings (58, 59)
    evening_time: str = "21:00"
    leave_briefing: bool = True         # 3.14 leaving home with the phone: weather, next event, departures (60)
    home_stop: str = ""                 # 3.14 your stop for the departures (Prague, Golemio key)
    proactive_daily_max: int = 8        # 3.14 at most this many proactive notices a day (66); 0 = no limit
    muted_kinds: list[str] = Field(default_factory=list)   # 3.14 kinds you kept ignoring – they stay quiet (64)
    hud_layout: Literal["full", "minimal", "focus", "presentation"] = "full"   # OMEGA 756: rozložení HUD
    protocols: list[Protocol] = Field(default_factory=_default_protocols)


class Powers(BaseModel):
    """3.3 everyday powers. Everything here stays on this PC."""
    clipboard_history: bool = True   # the last 30 copied texts, in memory only (never written to disk)
    download_watch: bool = True      # OMEGA P10.03: "stahování dokončeno" / "instalace dokončena"
    screen_time: bool = True         # which app is in front, minutes per day (30 days)
    net_watch: bool = True           # OMEGA 708/709/719: watched webs + line loss history every 10 minutes
    version_folders: list[str] = Field(default_factory=list)   # OMEGA 328: every saved change of a file here = a version
    break_minutes: int = 90          # remind a pause after this long at the PC without a break; 0 = off


class MailAccount(BaseModel):
    id: str
    address: str
    name: str = ""                 # your name in "From:"
    provider: str = "custom"       # seznam, gmail, centrum, atlas, icloud, custom
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 465
    # the password lives in the system keyring (secrets "mail:<id>"), never here


class MailCfg(BaseModel):
    accounts: list[MailAccount] = Field(default_factory=list)
    notify: bool = True            # announce new e-mails (notch, phone)
    speak: bool = True             # …and say it
    ignore_newsletters: bool = True
    vip: list[str] = Field(default_factory=list)   # names or addresses that always get through
    call_vip: bool = False         # an e-mail from a VIP rings your phone (3.4 phone)
    check_seconds: int = 20


class WorldCfg(BaseModel):
    """3.13 Přehled o světě: JARVIS reads the news by itself and knows what is going on."""
    enabled: bool = True
    topics: list[str] = Field(default_factory=lambda: ["cz", "world", "tech", "ai", "games"])
    interests: list[str] = Field(default_factory=list)   # your own topics ("Valorant", "Sparta Praha", "Bitcoin")
    every_min: int = 60              # how often the news is read
    digest: bool = True              # a few times a day the AI writes a short summary from the headlines
    in_answers: bool = True          # …and keeps it in mind in every answer


class MultitaskCfg(BaseModel):
    """3.14 Multitasking: JARVIS splits into many agents working at the same time (on more monitors too)."""
    parallel: int = 6                # how many agents may ask the AI at the same moment (free AI limits: keep it low)
    max_agents: int = 100            # how many agents one task may have
    watch_every_s: int = 20          # how often a watching agent looks at its monitor


class GamesCfg(BaseModel):
    """3.13 Herní pomocník: what you play is recognised; tips in the notch, playing time, the graphics card for the game."""
    tips: bool = True               # a short tip for the game in the notch now and then
    tips_every: int = 6             # …every this many minutes
    boost: bool = True              # while you play, the offline AI model leaves the graphics card
    stats: bool = True              # keep the playing time per game (Herní statistiky)


class PhoneLinkCfg(BaseModel):
    """3.4 the JARVIS app on your phone: it rings, dials, sends SMS and mirrors your phone's notifications."""
    announce: bool = True        # someone writes to you on WhatsApp / SMS / Messenger or calls → JARVIS tells you on the PC
    away_push: bool = True       # 3.12 away from the PC: what matters (and confirmations) comes to the phone
    clip_sync: bool = False      # 3.12 shared clipboard PC ↔ phone (text, never passwords) – switched on in the phone app
    remote_desktop: bool = False  # 3.12 Vzdálená plocha: a paired phone may see AND drive this PC (switched on here, once)
    photo_folder: str = ""        # 3.12 Záloha fotek: where the phone's photos go ("" = Obrázky\JARVIS Telefon)
    morning: bool = False         # 3.12 Ranní souhrn do telefonu (switched on in the phone app)
    morning_time: str = "07:00"
    morning_autoplay: bool = False   # …plays by itself when headphones are on
    speak: bool = False          # …aloud
    notch_events: bool = True    # 3.13 the phone plugged in / unplugged / low / full → a quiet notice in the notch (no voice)
    # optional real phone calls when the phone app cannot be reached (Twilio; the token is in the keyring)
    twilio_sid: str = ""
    twilio_from: str = ""        # your Twilio number, +1…
    my_number: str = ""          # your mobile, +420…
    # 3.14 AI sekretářka a volání za tebe (Twilio + a public HTTPS address for its webhooks)
    secretary: bool = False      # forwarded calls you do not take → JARVIS answers, asks, sends you a summary
    secretary_greeting: str = "" # own first sentence ("" = "Dobrý den, tady JARVIS. Jsem umělá inteligence…")
    public_url: str = ""         # https://… where Twilio reaches this JARVIS (nonstop server / Cloudflare tunnel)
    call_key: str = ""           # the secret part of the webhook address (made on first use)


class LinkCfg(BaseModel):
    """3.12 JARVIS Link – our own way to reach the PC from anywhere (mobile data too), no Tailscale needed.

    Direct: an encrypted port on this PC that the home router opens by itself (UPnP) – fastest, needs a public IP.
    Relay: your own small server on the internet (a free VPS) that only passes encrypted bytes along – works behind
    any router. Either way the phone checks the PC's certificate fingerprint, so nobody in between can read anything.
    """
    enabled: bool = False
    port: int = 8766             # the encrypted (TLS) port on this PC
    upnp: bool = True            # ask the router to open the port (UPnP)
    public_port: int = 0         # the port on the router (0 = the same as `port`)
    public_host: str = ""        # a name or address for the home (DDNS / a port forwarded by hand) – optional
    relay_host: str = ""         # your relay server (IP or name); its access key is in the keyring
    relay_port: int = 8443
    room: str = Field(default_factory=lambda: _secrets.token_hex(16))   # this PC's place on the relay


class CalendarCfg(BaseModel):
    ics_urls: list[str] = Field(default_factory=list)   # read-only calendars ("tajná adresa ve formátu iCal")
    remind_minutes: int = 15


class AutoTrigger(BaseModel):
    """3.5 "Když …": what starts an automation."""
    type: Literal["time", "boot", "app_open", "app_close", "mail", "phone_message", "phone_call", "battery", "power",
                  "away", "back", "zone_enter", "zone_leave", "webhook", "home_state", "phone_power", "phone_battery",
                  "phrase"] = "time"      # 3.14 phrase: value = what you say ("jdu spát") → the steps run (návrh 48)
    value: str = ""    # time "07:30" · app "Spotify" · mail/phone sender · battery % · power "in"/"out" · away/back minutes
    #                    3.13 phone_power "in"/"out" (the phone on / off its charger) · phone_battery % (the phone runs low)
    text: str = ""     # …and the subject / message must contain this · home_state: the state ("on", "open") or "> 25" / "< 10"
    days: list[int] = Field(default_factory=list)   # time: 0 = Monday … 6 = Sunday; empty = every day


class Automation(BaseModel):
    """3.5 "Když … tak …": a trigger and protocol-like steps ({sender}, {subject}, {text}, {app}, {percent} fill in)."""
    id: str
    name: str
    enabled: bool = True
    trigger: AutoTrigger = Field(default_factory=AutoTrigger)
    steps: list[ProtocolStep] = Field(default_factory=list)
    say: Literal["voice", "notch", "phone"] = "voice"   # 3.13 how it speaks up: aloud · only in the notch (quiet) · on the phone
    once: bool = False   # 3.14 "připomeň mi, až…": removes itself after it fires once (61)


def _default_automations() -> list[Automation]:
    S, T = ProtocolStep, AutoTrigger
    return [
        Automation(id="zpet", name="Vítej zpět", enabled=False, trigger=T(type="back", value="30"), steps=[
            S(say="Vítejte zpět, pane."),
            S(ask="Stručně mi řekni, co se stalo, zatímco jsem byl pryč: nové e-maily a zprávy z telefonu. Když nic, řekni jen, že je klid.")]),
        Automation(id="nabijecka", name="Nabíječka", enabled=False, trigger=T(type="power", value="in"), steps=[
            S(say="Napájení připojeno.")]),
    ]


class AutomationsCfg(BaseModel):
    enabled: bool = True
    items: list[Automation] = Field(default_factory=_default_automations)


class HomeCfg(BaseModel):
    """3.5 smart home through Home Assistant (the long-lived access token is in the keyring)."""
    url: str = ""                   # http://homeassistant.local:8123
    # 3.14 JARVIS v celém domě
    speakers: list[str] = Field(default_factory=list)          # media_player entities for "the whole house"
    room_speakers: dict[str, str] = Field(default_factory=dict)  # room name → media_player entity
    tts_entity: str = ""            # Home Assistant's own TTS (tts.*) instead of JARVIS's voice (empty = JARVIS's voice)
    person_entity: str = ""         # person.* in Home Assistant for home / away (empty = by your phone on the Wi-Fi)
    welcome: bool = True            # back home after a while → "Vítejte doma, pane…"
    welcome_protocol: bool = True   # …and the "Vítej doma" protocol
    follow_me: bool = True          # spoken notices go where you are (a room with a satellite)
    satellite_key: str = ""         # the secret part of the address for Home Assistant voice satellites (made on first use)
    nodes: list[dict] = Field(default_factory=list)           # 3.14 other JARVIS PCs: {name, url, token, mac}
    sound_watch: Literal["off", "away", "always"] = "off"   # 3.14 smoke alarm / a crash heard by the PC's microphone → phone
    frigate_url: str = ""           # 3.14 Frigate NVR (person detection on the house cameras), e.g. http://frigate.local:5000
    camera_zones: list[str] = Field(default_factory=list)    # Frigate zones watched also by day (e.g. "vchod", "zahrada")
    doorbell_entity: str = ""       # binary_sensor of the doorbell in Home Assistant
    door_camera: str = ""           # camera.* at the door (its picture comes with "Někdo zvoní")
    car: dict[str, str] = Field(default_factory=dict)        # 3.14 the car's entities: battery, fuel, range, location, lock,
                                                             # climate, charging, odometer (+ name); found by car_setup
    travel_buffer_min: int = 120    # 3.14 be at the airport this long before a flight (a train: 10 minutes)


class LimitsCfg(BaseModel):
    """OMEGA §5: what JARVIS may spend and change."""
    read_only: bool = False            # nothing that changes the PC, files, accounts or the home (only looking/reading)
    ai_daily_tokens: int = 0           # 0 = no limit; an estimate (characters / 4) across all providers
    ai_daily_cost: float = 0.0         # 0 = no limit; in `currency`, from the prices below
    claude_daily_usd: float = 0.0      # 3.14 Claude only: USD a day by its own price list (0 = no limit); over it → other AIs
    currency: str = "Kč"
    prices: dict[str, float] = Field(default_factory=dict)   # provider id → price per 1 million tokens
    mission_max_actions: int = 60      # one mission may call at most this many tools …
    mission_max_minutes: int = 30      # … and run at most this long
    mission_max_cost: float = 0.0      # 3.14 … and cost at most this much on paid AI keys (in `currency`; 0 = no limit)
    double_confirm: bool = True        # the most dangerous actions ask twice
    app_allowlist: list[str] = Field(default_factory=list)   # mouse/keyboard only in these apps (empty = any)
    project_isolation: bool = False    # OMEGA 688: while a project with a folder is active, file tools stay inside it
    project_perms: dict[str, list[str]] = Field(default_factory=dict)   # OMEGA 180: project name → permission areas allowed in it


class PrivacyCfg(BaseModel):
    private_mode: bool = False         # nothing new is written to the history or memory
    guest_mode: bool = False           # 3.14 someone else at the PC: nothing private in answers, notices, aloud (109)
    kids_mode: bool = False            # 3.14 a child at the PC: kind language, no shopping / locks / deleting / installing (41)
    guard_photo: bool = False          # 3.14 Hlídat PC: a webcam photo of whoever uses the PC while you are away (38)
    emergency_contacts: list[dict] = Field(default_factory=list)   # 3.14 [{name, phone}] for the emergency protocol (39)
    security_weekly: bool = True       # 3.14 the weekly security briefing (Sunday evening) (40)
    keep_days: int = 0                 # older conversations, missions and logs are deleted (0 = keep)
    mask_screens: bool = True          # OMEGA 285: password managers / banking windows blacked out before a screenshot goes to an AI
    mask_patterns: list[str] = Field(default_factory=list)   # own words to mask (empty = the built-in list)
    share_stats: bool = False          # 3.14 návrh 117: anonymous weekly statistics – only when switched on
    stats_url: str = ""                # where they go (HTTPS); empty = nothing is ever sent


class HealthCfg(BaseModel):
    """3.14 Zdraví jako ve filmu (42–44): the watch's numbers in the morning, care while you sit at the PC."""
    morning: bool = True               # "Stav systémů" (sleep, resting heart rate) in the morning briefing
    water_minutes: int = 0             # a glass of water every N minutes at the PC (0 = off)
    long_day_h: float = 10.0           # one notice after this many hours at the PC in a day (0 = off)
    bedtime: str = ""                  # "23:30": after this, while you still sit at the PC, a nudge to bed ("" = off)
    posture: bool = False              # posture from the webcam every 2 minutes (leaning in, slumped); only on your yes


class AgentCfg(BaseModel):
    mode: bool = False   # agent mode: plan first, up to 25 rounds
    instant: bool = True  # 3.13 everyday commands (volume, next song, open/close an app, time, timer, record) without the AI


class Permissions(BaseModel):
    apps: bool = True
    input: bool = True
    screen: bool = True
    files_read: bool = True
    files_write: bool = True
    shell: bool = True
    network: bool = True
    system: bool = True
    home: bool = True


class Config(BaseModel):
    general: General = Field(default_factory=General)
    brain: Brain = Field(default_factory=Brain)
    voice: Voice = Field(default_factory=Voice)
    notch: Notch = Field(default_factory=Notch)
    appearance: Appearance = Field(default_factory=Appearance)
    character: Character = Field(default_factory=Character)
    hotkeys: Hotkeys = Field(default_factory=Hotkeys)
    tools: Tools = Field(default_factory=Tools)
    integrations: Integrations = Field(default_factory=Integrations)
    phone: Phone = Field(default_factory=Phone)
    memory: MemoryCfg = Field(default_factory=MemoryCfg)
    permissions: Permissions = Field(default_factory=Permissions)
    agent: AgentCfg = Field(default_factory=AgentCfg)
    dictation: Dictation = Field(default_factory=Dictation)
    claude: ClaudeCfg = Field(default_factory=ClaudeCfg)
    stark: Stark = Field(default_factory=Stark)
    powers: Powers = Field(default_factory=Powers)
    mail: MailCfg = Field(default_factory=MailCfg)
    calendar: CalendarCfg = Field(default_factory=CalendarCfg)
    phone_link: PhoneLinkCfg = Field(default_factory=PhoneLinkCfg)
    games: GamesCfg = Field(default_factory=GamesCfg)
    world: WorldCfg = Field(default_factory=WorldCfg)
    multitask: MultitaskCfg = Field(default_factory=MultitaskCfg)
    link: LinkCfg = Field(default_factory=LinkCfg)
    automations: AutomationsCfg = Field(default_factory=AutomationsCfg)
    home: HomeCfg = Field(default_factory=HomeCfg)
    limits: LimitsCfg = Field(default_factory=LimitsCfg)
    privacy: PrivacyCfg = Field(default_factory=PrivacyCfg)
    health: HealthCfg = Field(default_factory=HealthCfg)

    @model_validator(mode="before")
    @classmethod
    def _migrate(cls, data: Any) -> Any:
        # 2.0 had a single tools.computer_use switch → permissions.input
        if isinstance(data, dict) and "permissions" not in data:
            if (data.get("tools") or {}).get("computer_use") is False:
                data = {**data, "permissions": {"input": False}}
        # 3.12: the old default look ("island") becomes the new Dynamic Island once; "mochi" (a real choice) stays
        if isinstance(data, dict) and isinstance(data.get("notch"), dict) and int(data["notch"].get("style_rev", 0) or 0) < 1:
            n = dict(data["notch"])
            if n.get("style", "island") == "island":
                n["style"] = "dynamic"
            n["style_rev"] = 1
            data = {**data, "notch": n}
        # 3.12: smooth (anti-aliased) edges are the default again – the grey box / white rim that made 3.10.89 switch to
        # hard edges was the Mica backdrop, turned off since 3.10.90; a saved "hard" moves to "smooth" once
        if isinstance(data, dict) and isinstance(data.get("notch"), dict) and int(data["notch"].get("edges_rev", 0) or 0) < 1:
            n = dict(data["notch"])
            if n.get("edges", "hard") == "hard":
                n["edges"] = "smooth"
            n["edges_rev"] = 1
            data = {**data, "notch": n}
        # 3.12: the habits ring in the closed notch was on by default – off once; the idle notch shows the eyes again
        if isinstance(data, dict) and isinstance(data.get("notch"), dict) and int(data["notch"].get("habit_ring_rev", 0) or 0) < 2:
            data = {**data, "notch": {**data["notch"], "habit_ring": False, "habit_ring_rev": 2}}   # 3.13 the eyes, always
        # 3.13: a saved 0.8 s wait after speech becomes 0.6 s once (faster answers; you can set it back)
        if isinstance(data, dict) and isinstance(data.get("voice"), dict) and int(data["voice"].get("silence_rev", 0) or 0) < 1:
            v = dict(data["voice"])
            if float(v.get("silence_seconds", 0.8) or 0.8) == 0.8:
                v["silence_seconds"] = 0.6
            v["silence_rev"] = 1
            data = {**data, "voice": v}
        # 3.12: the first notch colour setting was "song" only – the wallpaper joins it once (you can go back)
        if isinstance(data, dict) and isinstance(data.get("notch"), dict) and int(data["notch"].get("tint_rev", 0) or 0) < 1:
            n = dict(data["notch"])
            if n.get("tint", "song") == "song":
                n["tint"] = "song_wall"
            n["tint_rev"] = 1
            data = {**data, "notch": n}
        # 3.12: Groq switched off its Llama, Qwen 3 32B and Kimi K2 models in 2026 – a saved one moves to the model Groq
        # names as their replacement (GPT-OSS 120B; the small fast one to GPT-OSS 20B). Other providers stay as they are.
        if isinstance(data, dict) and isinstance(data.get("brain"), dict) and isinstance(data["brain"].get("providers"), list):
            provs, changed = [], False
            for p in data["brain"]["providers"]:
                if isinstance(p, dict) and p.get("preset") == "groq":
                    p = dict(p)
                    for key in ("model", "fast_model"):
                        if p.get(key) in GROQ_RETIRED:
                            p[key] = GROQ_RETIRED[p[key]]
                            changed = True
                elif isinstance(p, dict) and p.get("preset") in RETIRED:
                    p = dict(p)
                    for key in ("model", "fast_model", "vision_model"):
                        if p.get(key) in RETIRED[p["preset"]]:
                            p[key] = RETIRED[p["preset"]][p[key]]
                            changed = True
                provs.append(p)
            if changed:
                data = {**data, "brain": {**data["brain"], "providers": provs}}
        return data


# Keys JARVIS may change by itself (voice "mluv rychleji", "přepni na Groq").
SETTABLE_BY_VOICE: set[str] = {
    "general.user_name", "general.address_as", "general.language", "general.personality", "general.city",
    "brain.chain", "brain.temperature", "brain.offline_only",
    "voice.wake_word", "voice.tts_voice", "voice.tts_rate", "voice.tts_pitch", "voice.tts_volume",
    "voice.speak_mode", "voice.stt_language", "voice.followup", "voice.game_quiet", "voice.barge_in", "notch.music_viz", "notch.follow_window", "notch.edge_play", "powers.download_watch",
    "notch.enabled", "notch.tiles", "notch.hide_in_fullscreen", "notch.open_on", "appearance.density", "appearance.input_mode", "stark.hud_layout",
    "appearance.theme", "appearance.accent", "appearance.animations",
    "character.color", "character.glow", "character.size", "character.outfit", "character.personality", "character.ambient",
    "agent.mode",
    "dictation.enabled", "dictation.cleanup",
    "stark.boot_greeting", "stark.briefing_auto", "stark.briefing_speak", "stark.briefing_news",
    "stark.guardian", "stark.guardian_speak", "stark.network_watch", "stark.hardware_watch", "stark.perf_history", "stark.smart_quiet", "stark.attention_aware", "appearance.captions", "appearance.spatial_sounds", "automations.enabled",
    "privacy.private_mode",
    "powers.clipboard_history", "powers.screen_time", "powers.break_minutes",
    "health.morning", "health.water_minutes", "health.long_day_h", "health.bedtime", "health.posture",
    "phone_link.announce", "phone_link.speak", "phone_link.notch_events", "games.tips", "games.tips_every", "games.boost", "games.stats",
    "world.enabled", "world.topics", "world.interests", "world.every_min", "world.digest", "world.in_answers",
    "multitask.parallel", "multitask.watch_every_s",
    "mail.notify", "mail.speak", "mail.ignore_newsletters", "mail.vip", "mail.call_vip", "calendar.remind_minutes",
}

# Never sent to remote clients.
SECRET_KEYS = {("phone", "token"), ("link", "room"), ("home", "satellite_key"), ("phone_link", "call_key")}


def config_path():
    return paths.data_dir() / "config.toml"


def load() -> Config:
    p = config_path()
    if p.exists():
        try:
            return Config.model_validate(tomllib.loads(p.read_text(encoding="utf-8")))
        except (ValidationError, tomllib.TOMLDecodeError):
            p.rename(p.with_suffix(".broken.toml"))
    cfg = Config()
    save(cfg)
    return cfg


def save(cfg: Config) -> None:
    p = config_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(tomli_w.dumps(cfg.model_dump(mode="json", exclude_none=True)).encode("utf-8"))
    tmp.replace(p)


def _merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def apply_patch(cfg: Config, patch: dict[str, Any]) -> Config:
    """Deep-merge patch into cfg; raises ValueError when the result is invalid."""
    data = cfg.model_dump(mode="json")
    unknown = [k for k in patch if k not in data]
    if unknown:
        raise ValueError(f"Neznámá sekce nastavení: {', '.join(unknown)}")
    try:
        return Config.model_validate(_merge(data, patch))
    except ValidationError as e:
        raise ValueError(str(e)) from e


def dotted_to_patch(key: str, value: Any) -> dict:
    out: dict = {}
    cur = out
    parts = key.split(".")
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value
    return out


def public_dump(cfg: Config) -> dict:
    data = cfg.model_dump(mode="json")
    for sec, key in SECRET_KEYS:
        data.get(sec, {}).pop(key, None)
    return data
