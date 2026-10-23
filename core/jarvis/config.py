"""Settings: config.toml in the data dir, validated by pydantic."""
from __future__ import annotations

import copy
import secrets as _secrets
import tomllib
from typing import Any, Literal

import tomli_w
from pydantic import BaseModel, Field, ValidationError

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


class Voice(BaseModel):
    enabled: bool = True
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


class Notch(BaseModel):
    enabled: bool = True
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
    tiles: list[str] = Field(default_factory=lambda: [
        "ask", "media", "shelf", "quick", "timers", "system", "weather", "phone"])


class Appearance(BaseModel):
    theme: Literal["stark", "light"] = "stark"
    accent: str = "#2ee6ff"
    animations: Literal["full", "reduced"] = "full"


class Hotkeys(BaseModel):
    talk: str = "ctrl+alt+space"
    chat: str = "ctrl+alt+j"
    stop: str = "esc"


class Tools(BaseModel):
    disabled: list[str] = Field(default_factory=list)
    always_confirm: list[str] = Field(default_factory=list)
    trusted: list[str] = Field(default_factory=list)
    computer_use: bool = True
    allowed_folders: list[str] = Field(default_factory=list)


class McpServer(BaseModel):
    name: str
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class Integrations(BaseModel):
    mcp: list[McpServer] = Field(default_factory=list)
    image_provider: str = "pollinations"


class Device(BaseModel):
    id: str
    name: str = "Telefon"


class Phone(BaseModel):
    token: str = Field(default_factory=lambda: _secrets.token_urlsafe(32))
    port: int = 8765
    devices: list[Device] = Field(default_factory=list)


class MemoryCfg(BaseModel):
    context_messages: int = 20
    max_upload_mb: int = 200


class Character(BaseModel):
    color: Literal["black", "midnight", "violet", "rose", "white"] = "black"
    glow: str = ""            # empty = JARVIS blue (#4f8dff)
    size: Literal["S", "M", "L"] = "M"
    pet_mode: bool = False    # living on the desktop instead of the notch
    pet_x: int = -1
    pet_y: int = -1


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


# Keys JARVIS may change by itself (voice "mluv rychleji", "přepni na Groq").
SETTABLE_BY_VOICE: set[str] = {
    "general.user_name", "general.address_as", "general.language", "general.personality", "general.city",
    "brain.chain", "brain.temperature", "brain.offline_only",
    "voice.wake_word", "voice.tts_voice", "voice.tts_rate", "voice.tts_pitch", "voice.tts_volume",
    "voice.speak_mode", "voice.stt_language",
    "notch.enabled", "notch.tiles", "notch.hide_in_fullscreen",
    "appearance.theme", "appearance.accent", "appearance.animations",
    "character.color", "character.glow", "character.size",
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
