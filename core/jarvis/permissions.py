"""Permission categories (spec §2): every tool belongs to one; a switched-off category hides and blocks its tools."""
from __future__ import annotations

from typing import Any

PERMS: dict[str, str] = {
    "apps": "Aplikace a okna",
    "input": "Myš, klávesnice a ovládání aplikací",
    "screen": "Obrazovka",
    "files_read": "Čtení souborů",
    "files_write": "Změny souborů",
    "shell": "PowerShell, Python a kód",
    "network": "Internet a prohlížeč",
    "system": "Systém a napájení",
}

CATEGORY_PERM = {
    "ovládání počítače": "input", "obrazovka": "screen", "soubory": "files_read",
    "prohlížeč": "network", "web": "network", "systém": "system",
}
TOOL_PERM = {
    "type_text": "input", "press_keys": "input",
    "write_text_file": "files_write", "copy_file": "files_write", "move_file": "files_write",
    "delete_file": "files_write", "save_attachment": "files_write",
    "run_shell": "shell", "run_python": "shell", "create_skill": "shell", "delete_skill": "shell",
    "open_url": "network", "google_search": "network", "generate_image": "network", "youtube_search": "network",
}


# Tools that need more than one area (computer_use looks at the screen AND drives mouse/keyboard).
EXTRA_PERMS = {"computer_use": ["screen"]}


def required(spec: Any) -> list[str]:
    return [perm_of(spec), *EXTRA_PERMS.get(spec.name, [])]


def perm_of(spec: Any) -> str:
    if getattr(spec, "perm", None):
        return spec.perm
    if spec.name in TOOL_PERM:
        return TOOL_PERM[spec.name]
    if (spec.category or "").startswith("MCP"):
        return "network"
    return CATEGORY_PERM.get(spec.category, "apps")


def blocked_by(cfg: Any, spec: Any) -> str | None:
    """The first switched-off permission this tool needs, or None."""
    perms = getattr(cfg, "permissions", None)
    if perms is None:
        return None
    return next((p for p in required(spec) if not getattr(perms, p, True)), None)


def allowed(cfg: Any, spec: Any) -> bool:
    return blocked_by(cfg, spec) is None
