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


def perm_of(spec: Any) -> str:
    if getattr(spec, "perm", None):
        return spec.perm
    if spec.name in TOOL_PERM:
        return TOOL_PERM[spec.name]
    if (spec.category or "").startswith("MCP"):
        return "network"
    return CATEGORY_PERM.get(spec.category, "apps")


def allowed(cfg: Any, spec: Any) -> bool:
    perms = getattr(cfg, "permissions", None)
    return perms is None or bool(getattr(perms, perm_of(spec), True))
