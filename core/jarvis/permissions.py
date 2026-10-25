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
    "home": "Chytrá domácnost",
}
READ_ONLY = "read_only"   # not an area: the reason a change is blocked while "Režim jen pro čtení" is on
LABELS = {**PERMS, READ_ONLY: "Režim jen pro čtení (Nastavení → Oprávnění)"}
# Read-only mode (OMEGA 177): only these areas are reading; anything else (and anything dangerous) is blocked,
# except the reading tools listed below.
READ_PERMS = {"files_read", "screen", "network"}
READ_ONLY_OK = {
    "ai_usage", "briefing", "clipboard_get", "data_inventory", "get_settings", "get_time", "home_devices", "list_apps",
    "list_automations", "list_protocols", "list_scheduled", "list_show", "list_skills", "list_timers", "list_windows",
    "mic_history", "mission_queue", "phone_battery", "phone_messages", "read_attachment", "screen_time", "search_history",
    "show_hud", "system_info", "top_processes", "performance_report", "pc_health_report", "storage_report", "speed_test",
    "weather", "update_plan", "network_devices", "selected_text", "export_audit", "calendar_list", "email_inbox",
    "email_search", "price", "exchange_rate",
    "pc_diagnose", "explain_crash_code", "perf_check", "perf_benchmark", "perf_history", "network_check", "check_link",
    "check_download", "scan_secrets", "verify_copy", "data_rescue_plan", "system_integrity_check", "hardware_changes",
    "find_duplicates", "find_similar_photos", "archive_contents", "file_metadata", "file_versions", "folder_fingerprint",
    "folder_check", "recent_files", "find_in_files", "backup_plan",
    "search_memory", "memory_timeline", "memory_conflicts", "memory_overview", "project_list", "project_resume",
    "list_agents", "delegate_to_agent", "agent_team", "deep_research", "compare_options", "check_assumptions", "ask_models",
    "goal_plan", "sql_query", "a11y_check", "check_translation",
    "inbox_overview", "contact_card", "reply_context", "follow_up_check", "communication_digest", "calendar_check", "free_time",
    "meeting_prep", "learning_weak_spots", "study_stats", "check_math_steps", "quiz_from", "oral_exam",
    "what_next", "forgotten_work", "my_routines", "deadline_risks", "estimate_effort", "day_summary", "quiet_status",
    "broken_links", "website_audit", "source_reliability", "price_history", "fact_check",
}
# reading tools in a reading area that still change or send something
READ_PERM_WRITERS = {"open_url", "browser_click", "browser_type", "browser_open", "generate_image", "youtube_search",
                     "google_search", "watch_website", "email_mark_read", "price_alert", "wake_device", "name_device"}

# OMEGA 181 / 683: an area switched off can be allowed for a while ("povolit na 15 minut"); in memory only
TEMP_GRANTS: dict[str, float] = {}


def grant(perm: str, minutes: float) -> float:
    import time

    until = time.time() + max(1.0, float(minutes)) * 60
    TEMP_GRANTS[perm] = until
    return until


def granted(perm: str) -> bool:
    import time

    until = TEMP_GRANTS.get(perm, 0.0)
    if until and until < time.time():
        TEMP_GRANTS.pop(perm, None)
        return False
    return bool(until)

CATEGORY_PERM = {
    "ovládání počítače": "input", "obrazovka": "screen", "soubory": "files_read",
    "prohlížeč": "network", "web": "network", "systém": "system", "síť": "network", "bezpečnost": "files_read",
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
    """The first switched-off permission this tool needs (or READ_ONLY), or None."""
    perms = getattr(cfg, "permissions", None)
    if perms is None:
        return None
    limits = getattr(cfg, "limits", None)
    if limits is not None and limits.read_only and spec.name not in READ_ONLY_OK and (
            spec.danger or spec.danger_if is not None or perm_of(spec) not in READ_PERMS or spec.name in READ_PERM_WRITERS):
        return READ_ONLY
    return next((p for p in required(spec) if not getattr(perms, p, True) and not granted(p)), None)


def allowed(cfg: Any, spec: Any) -> bool:
    return blocked_by(cfg, spec) is None
