"""Built-in tools. Importing a module registers its tools."""
import importlib
import logging

from .base import REGISTRY, ToolResult, ToolSpec, call, details_for, is_dangerous, schemas, tool  # noqa: F401

BUILTIN = ["apps", "web", "youtube", "media", "system", "windows", "files", "clipboard", "info", "weather",
           "shell", "screenshot", "timers", "phone", "settings", "memory_tools", "attachment_tools",
           "computer_use", "browser", "code", "images", "schedule", "skills", "plan", "uia", "dev", "notes", "sites", "stark_tools", "powers_tools", "mail_tools", "phone_link_tools", "automation_tools", "home_tools", "list_tools", "finance_tools", "network_tools", "mission_tools", "control_tools", "rescue_tools", "fileverse_tools", "brain_tools", "comms_tools", "learning_tools", "proactive_tools", "webintel_tools", "everyday_tools", "workspace_tools", "db_tools", "devlab_tools", "testlab_tools", "factory_tools", "science_tools", "business_tools", "studio_tools", "localai_tools", "gateway_tools", "browserplus_tools", "hwops_tools", "homeplus_tools", "maker_tools", "gamedev_tools", "creative_tools", "lab_tools", "voice_tools", "bizops_tools", "pccare_tools", "mediapro_tools", "uiplus_tools", "mobileplus_tools", "hwlab_tools", "devplus_tools", "vision_tools", "gameplus_tools", "secplus_tools", "aiplus_tools", "intelplus_tools", "workplus_tools", "flowplus_tools", "designplus_tools", "sysplus_tools", "uixplus_tools", "omega_tools", "bridge_tools", "watch_tools", "devices_tools", "work_tools", "devops_tools", "makerplus_tools"]


def load_builtin() -> None:
    for m in BUILTIN:
        try:
            importlib.import_module(f"{__name__}.{m}")
        except ModuleNotFoundError as e:
            if e.name and e.name.endswith(m):
                continue  # module not written yet / optional
            logging.getLogger(__name__).warning("tool module %s unavailable: %s", m, e)
