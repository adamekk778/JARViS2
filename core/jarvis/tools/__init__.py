"""Built-in tools. Importing a module registers its tools."""
import importlib
import logging

from .base import REGISTRY, ToolResult, ToolSpec, call, details_for, is_dangerous, schemas, tool  # noqa: F401

BUILTIN = ["apps", "web", "youtube", "media", "system", "windows", "files", "clipboard", "info", "weather",
           "shell", "screenshot", "timers", "phone", "settings", "memory_tools", "attachment_tools",
           "computer_use", "browser", "code", "images", "schedule", "skills", "plan"]


def load_builtin() -> None:
    for m in BUILTIN:
        try:
            importlib.import_module(f"{__name__}.{m}")
        except ModuleNotFoundError as e:
            if e.name and e.name.endswith(m):
                continue  # module not written yet / optional
            logging.getLogger(__name__).warning("tool module %s unavailable: %s", m, e)
