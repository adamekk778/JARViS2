from __future__ import annotations

import json
from typing import Annotated

from .. import config as config_mod
from .base import ToolResult, tool


@tool("update_setting", "Změní nastavení JARVISe, např. key='voice.tts_rate' value='+20%' (rychlejší řeč), "
      "'voice.speak_mode' ('always'|'voice'|'never'), 'brain.chain' (['groq','omniroute','ollama']), "
      "'appearance.accent' ('#ff3b30'), 'general.user_name'.", category="nastavení")
async def update_setting(ctx, key: Annotated[str, "tečkový klíč"], value: Annotated[str, "nová hodnota (JSON nebo text)"]) -> ToolResult:
    if key not in config_mod.SETTABLE_BY_VOICE:
        return ToolResult(False, f"Tohle nastavení ({key}) se mění jen ručně v Nastavení. Měnitelné: "
                                 + ", ".join(sorted(config_mod.SETTABLE_BY_VOICE)))
    try:
        val = json.loads(value)
    except (ValueError, TypeError):
        val = value
    ctx.update_config(config_mod.dotted_to_patch(key, val))
    return ToolResult(True, f"Nastaveno {key} = {val}")


@tool("get_settings", "Vrátí aktuální nastavení JARVISe (bez tajných klíčů).", category="nastavení")
async def get_settings(ctx) -> ToolResult:
    return ToolResult(True, "Nastavení", data=config_mod.public_dump(ctx.cfg))
