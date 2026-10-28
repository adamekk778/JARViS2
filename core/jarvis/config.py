"""Settings: config.toml in the data dir, validated by pydantic."""
from __future__ import annotations

import copy
import secrets as _secrets
import tomllib
from typing import Any, Literal

import tomli_w
from pydantic import BaseModel, Field, ValidationError, model_validator

from . import paths


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
        ProviderCfg(id="ollama", preset="ollama", base_url="http://localhost:11434", model="qwen2.5:3b"),
    ]


class General(BaseModel):
    user_name: str = ""
    address_as: str = "pane"
    language: str = "cs"
    personality: Literal["jarvis", "friend", "brief", "custom"] = "jarvis"
    custom_prompt: str = ""
    autostart: bool = True
    city: str = "Praha"
    update_url: str = "https://api.github.com/repos/adamekk778/JARViS2/releases/latest"


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
    adaptive_local: bool = True    # OMEGA P15.10: local models step aside during games, on low battery, when RAM runs out


class Voice(BaseModel):
    enabled: bool = True
    emotion: bool = False          # OMEGA P3.12: read the tone of voice (tired / tense / lively) – off unless you turn it on
    wake_word: bool = True
    wake_word_model: str = "hey_jarvis"
    wake_threshold: float = 0.5
    input_device: str = ""
    stt_model: str = "small"
    stt_language: str = "cs"
    stt_provider: Literal["local", "groq"] = "local"
    tts_voice: str = "cs-CZ-AntoninNeural"
    piper_voice: str = "cs_CZ-jirka-medium"
    tts_rate: str = "+0%"
    tts_pitch: str = "+0Hz"
    tts_volume: str = "+0%"
    speak_mode: Literal["always", "voice", "never"] = "voice"
    silence_seconds: float = 0.8
    followup: bool = False          # after an answer, listen 6 s more without the wake word
    output_device: str = ""         # speaker name; empty = Windows default
    tts_voice_en: str = "en-GB-RyanNeural"
    piper_voice_en: str = "en_GB-alan-medium"
    noise_suppression: bool = True  # clean the recording before it is recognised (filter the hum and hiss)
    auto_gain: bool = True          # level a quiet / distant voice up before recognition
    echo_cancel: bool = True        # remove JARVIS's own voice from the microphone (talking over it works)
    duck_media: bool = True         # turn other programs down while JARVIS listens or speaks
    duck_level: float = 0.3         # … to this share of their volume


class Notch(BaseModel):
    enabled: bool = True
    music_viz: bool = True         # OMEGA P12.02: bars moving with the music while something plays
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
    pinned: bool = False   # big panel stays open (also after restart)
    smooth_edges: bool = True   # replaced by `edges` (kept so older config files still load)
    # "hard" = the window is cut to the notch shape (works on every PC); "smooth" = per-pixel alpha with
    # anti-aliased curves, which on some PCs made Windows draw a grey box around the notch
    edges: Literal["hard", "smooth"] = "hard"
    tiles: list[str] = Field(default_factory=lambda: [
        "ask", "media", "shelf", "quick", "timers", "system", "weather", "phone"])
    open_on: Literal["hover", "click"] = "hover"   # OMEGA 092: "click" = najetí myší panel neotevře (proti náhodnému otevření)
    tuck_minutes: int = 10                     # OMEGA 078: po kolika minutách klidu se postavička schová za okraj (0 = nikdy)
    app_actions: list[dict] = Field(default_factory=list)   # OMEGA 089: vlastní akce {app, label, text, icon}


class Appearance(BaseModel):
    theme: Literal["stark", "light"] = "stark"
    density: Literal["auto", "compact", "comfortable", "large"] = "auto"   # OMEGA 758: hustota a velikost rozhraní
    input_mode: Literal["auto", "mouse", "touch", "voice"] = "auto"      # OMEGA 522: ovládání myší / dotykem / hlasem
    captions: bool = False              # OMEGA 790: live captions of what JARVIS says and what it heard
    accent: str = "#4f8dff"    # JARVIS blue (2.2); the 2.0 default cyan is migrated to it
    animations: Literal["full", "reduced"] = "full"
    sounds: bool = True        # subtle interface sounds in the notch
    sound_volume: int = 30     # 0–100
    spatial_sounds: bool = True   # OMEGA 102 / 761: sounds come from where things happen (phone right, notch centre…)

    @model_validator(mode="before")
    @classmethod
    def _new_default_accent(cls, data: Any) -> Any:
        if isinstance(data, dict) and str(data.get("accent", "")).lower() == "#2ee6ff":
            data = {**data, "accent": "#4f8dff"}
        return data


class Hotkeys(BaseModel):
    talk: str = "ctrl+alt+space"
    chat: str = "ctrl+alt+j"
    hud: str = "ctrl+alt+h"
    selection: str = "ctrl+alt+e"   # what to do with the selected text (fix, translate, explain…)
    stop: str = "esc"
    stop_all: str = "ctrl+alt+x"


class Tools(BaseModel):
    disabled: list[str] = Field(default_factory=list)
    always_confirm: list[str] = Field(default_factory=list)
    trusted: list[str] = Field(default_factory=list)
    computer_use: bool = True   # deprecated: migrated to permissions.input
    allowed_folders: list[str] = Field(default_factory=list)
    approved_skills: list[str] = Field(default_factory=list)   # skills allowed to load (spec §10)
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


class Device(BaseModel):
    id: str
    name: str = "Telefon"


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
    outfit: Literal["auto", "none", "beanie", "crown", "party", "santa", "witch", "sunglasses", "bow", "cap"] = "auto"
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
    hud_layout: Literal["full", "minimal", "focus", "presentation"] = "full"   # OMEGA 756: rozložení HUD
    protocols: list[Protocol] = Field(default_factory=_default_protocols)


class Powers(BaseModel):
    """3.3 everyday powers. Everything here stays on this PC."""
    clipboard_history: bool = True   # the last 30 copied texts, in memory only (never written to disk)
    download_watch: bool = True      # OMEGA P10.03: "stahování dokončeno" / "instalace dokončena"
    screen_time: bool = True         # which app is in front, minutes per day (30 days)
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


class PhoneLinkCfg(BaseModel):
    """3.4 the JARVIS app on your phone: it rings, dials, sends SMS and mirrors your phone's notifications."""
    announce: bool = True        # someone writes to you on WhatsApp / SMS / Messenger or calls → JARVIS tells you on the PC
    speak: bool = False          # …aloud
    # optional real phone calls when the phone app cannot be reached (Twilio; the token is in the keyring)
    twilio_sid: str = ""
    twilio_from: str = ""        # your Twilio number, +1…
    my_number: str = ""          # your mobile, +420…


class CalendarCfg(BaseModel):
    ics_urls: list[str] = Field(default_factory=list)   # read-only calendars ("tajná adresa ve formátu iCal")
    remind_minutes: int = 15


class AutoTrigger(BaseModel):
    """3.5 "Když …": what starts an automation."""
    type: Literal["time", "boot", "app_open", "app_close", "mail", "phone_message", "phone_call", "battery", "power",
                  "away", "back", "zone_enter", "zone_leave", "webhook"] = "time"
    value: str = ""    # time "07:30" · app "Spotify" · mail/phone sender · battery % · power "in"/"out" · away/back minutes
    text: str = ""     # …and the subject / message must contain this
    days: list[int] = Field(default_factory=list)   # time: 0 = Monday … 6 = Sunday; empty = every day


class Automation(BaseModel):
    """3.5 "Když … tak …": a trigger and protocol-like steps ({sender}, {subject}, {text}, {app}, {percent} fill in)."""
    id: str
    name: str
    enabled: bool = True
    trigger: AutoTrigger = Field(default_factory=AutoTrigger)
    steps: list[ProtocolStep] = Field(default_factory=list)


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


class LimitsCfg(BaseModel):
    """OMEGA §5: what JARVIS may spend and change."""
    read_only: bool = False            # nothing that changes the PC, files, accounts or the home (only looking/reading)
    ai_daily_tokens: int = 0           # 0 = no limit; an estimate (characters / 4) across all providers
    ai_daily_cost: float = 0.0         # 0 = no limit; in `currency`, from the prices below
    currency: str = "Kč"
    prices: dict[str, float] = Field(default_factory=dict)   # provider id → price per 1 million tokens
    mission_max_actions: int = 60      # one mission may call at most this many tools …
    mission_max_minutes: int = 30      # … and run at most this long
    double_confirm: bool = True        # the most dangerous actions ask twice
    app_allowlist: list[str] = Field(default_factory=list)   # mouse/keyboard only in these apps (empty = any)
    project_isolation: bool = False    # OMEGA 688: while a project with a folder is active, file tools stay inside it
    project_perms: dict[str, list[str]] = Field(default_factory=dict)   # OMEGA 180: project name → permission areas allowed in it


class PrivacyCfg(BaseModel):
    private_mode: bool = False         # nothing new is written to the history or memory
    keep_days: int = 0                 # older conversations, missions and logs are deleted (0 = keep)
    mask_screens: bool = True          # OMEGA 285: password managers / banking windows blacked out before a screenshot goes to an AI
    mask_patterns: list[str] = Field(default_factory=list)   # own words to mask (empty = the built-in list)


class AgentCfg(BaseModel):
    mode: bool = False   # agent mode: plan first, up to 25 rounds


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
    automations: AutomationsCfg = Field(default_factory=AutomationsCfg)
    home: HomeCfg = Field(default_factory=HomeCfg)
    limits: LimitsCfg = Field(default_factory=LimitsCfg)
    privacy: PrivacyCfg = Field(default_factory=PrivacyCfg)

    @model_validator(mode="before")
    @classmethod
    def _migrate(cls, data: Any) -> Any:
        # 2.0 had a single tools.computer_use switch → permissions.input
        if isinstance(data, dict) and "permissions" not in data:
            if (data.get("tools") or {}).get("computer_use") is False:
                data = {**data, "permissions": {"input": False}}
        return data


# Keys JARVIS may change by itself (voice "mluv rychleji", "přepni na Groq").
SETTABLE_BY_VOICE: set[str] = {
    "general.user_name", "general.address_as", "general.language", "general.personality", "general.city",
    "brain.chain", "brain.temperature", "brain.offline_only",
    "voice.wake_word", "voice.tts_voice", "voice.tts_rate", "voice.tts_pitch", "voice.tts_volume",
    "voice.speak_mode", "voice.stt_language", "voice.followup", "notch.music_viz", "notch.follow_window", "notch.edge_play", "powers.download_watch",
    "notch.enabled", "notch.tiles", "notch.hide_in_fullscreen", "notch.open_on", "appearance.density", "appearance.input_mode", "stark.hud_layout",
    "appearance.theme", "appearance.accent", "appearance.animations",
    "character.color", "character.glow", "character.size", "character.outfit", "character.personality", "character.ambient",
    "agent.mode",
    "dictation.enabled", "dictation.cleanup",
    "stark.boot_greeting", "stark.briefing_auto", "stark.briefing_speak", "stark.briefing_news",
    "stark.guardian", "stark.guardian_speak", "stark.network_watch", "stark.hardware_watch", "stark.perf_history", "stark.smart_quiet", "stark.attention_aware", "appearance.captions", "appearance.spatial_sounds", "automations.enabled",
    "privacy.private_mode",
    "powers.clipboard_history", "powers.screen_time", "powers.break_minutes",
    "phone_link.announce", "phone_link.speak",
    "mail.notify", "mail.speak", "mail.ignore_newsletters", "mail.vip", "mail.call_vip", "calendar.remind_minutes",
}

# Never sent to remote clients.
SECRET_KEYS = {("phone", "token")}


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
