// WebSocket protocol (spec §6). Must match core/jarvis/server/ws.py (checked by test_protocol_sync.py).

export const CLIENT_TYPES = [
  "hello", "user_text", "audio_chunk", "audio_end", "voice_upload", "confirm_response", "stop", "quick_action",
  "share", "history_get", "conversations_get", "switch_conversation", "new_chat", "delete_conversation",
  "regenerate", "settings_get", "settings_set", "secret_set", "provider_test", "memory_get", "fact_update",
  "fact_delete", "memory_wipe", "pairing_get", "speak", "tts_request", "shelf_add", "shelf_remove", "system_get",
  "weather_get", "timers_get", "tools_get", "jobs_get", "job_delete", "skills_get", "mcp_get", "push_to_talk",
  "voice_toggle", "ping", "mood_set", "pet_command", "update_check", "update_install",
  "stop_all", "tasks_get", "task_get", "task_pause", "task_resume", "task_cancel", "task_retry", "tasks_clear",
  "local_status", "local_pull", "local_pull_cancel", "local_delete", "local_unload", "local_gpu_test",
  "message_edit", "conversation_rename", "conversation_move", "memory_export", "memory_import",
  "audio_devices_get", "voice_mode", "diagnostics_get", "diagnostics_export", "skill_approve",
  "dictation_get", "dictation_delete", "dictation_clear", "recap_get", "recap_seen",
  "notes_get", "note_get", "note_delete", "note_start", "note_stop", "note_cancel",
  "claude_sessions_get", "claude_decision", "claude_hooks_status", "claude_hooks_preview", "claude_hooks_apply",
  "whats_new_seen", "sounds_folder", "open_window", "site_open", "sites_get", "protocol_run", "briefing_get", "selection_action",
  "mail_status_get", "mail_account_add", "mail_account_remove", "calendar_get",
  "phone_status_get", "phone_ack", "twilio_set", "automation_run", "automations_get", "home_set", "home_get", "home_action",
  "lists_get", "list_update", "network_get", "network_wake", "network_name",
  "mission_start", "artifact_open", "skill_from_task", "skill_versions_get", "skill_rollback",
  "usage_get", "privacy_get", "audit_export", "data_export", "backup_create", "backup_restore", "reset_all",
  "perm_grant", "approvals_get", "queue_get", "queue_add", "queue_cancel", "mission_resume",
  "rescue_run", "rescue_open", "perf_get", "perf_bench", "netcheck", "seccheck", "files_run",
  "knowledge_get", "knowledge_search", "timeline_get", "project_set", "conflict_resolve",
  "learn_get", "learn_next", "learn_grade", "learn_add", "learn_tool",
  "notch_context_get", "pins_get", "pin_add", "pin_done", "pin_remove", "pins_clear_done",
  "workspaces_get", "workspace_save", "workspace_restore", "workspace_delete",
  "guest_info", "guests_get", "guest_add", "guest_revoke", "pc_files", "clean_text", "command_qr", "phone_photo",
  "phone_zone", "client_state",
] as const;

export const SERVER_TYPES = [
  "welcome", "state", "level", "transcript", "user_message", "assistant_delta", "assistant_done", "tool_start",
  "tool_end", "confirm_request", "confirm_timeout", "notify", "brain", "error", "settings_changed", "task_progress",
  "media", "history", "conversations", "settings", "provider_test_result", "memory", "pairing", "tts_audio",
  "shelf", "system", "weather", "timers", "tools", "jobs", "skills", "mcp", "quick_result", "pong", "voice_status",
  "mood", "pet_state", "update_status", "confirm_resolved", "task_update",
  "tasks", "task", "stopped", "screen_capture", "local_info", "local_pull_progress", "local_model_missing",
  "memory_export_data", "memory_import_result", "audio_devices",
  "diagnostics", "diagnostics_file",
  "dictation", "dictation_data", "recap", "notetaker", "notes", "note", "render",
  "claude_sessions", "claude_permission", "claude_permission_resolved", "claude_hooks", "sounds", "sites", "protocol", "briefing", "guardian", "boot", "selection", "selection_result", "mail_status", "mail_new", "calendar",
  "phone_cmd", "phone_ack", "phone_ring", "phone_notification", "phone_status", "automation", "automations", "home", "lists", "network", "skill_draft", "skill_versions", "usage", "privacy", "approvals", "queue", "export_done",
  "rescue", "perf", "netcheck", "seccheck", "files_result", "knowledge", "knowledge_hits", "timeline", "project_resume",
  "learn", "learn_card", "learn_result",
  "app_context", "pins", "workspaces", "workspace_result",
  "guests", "pc_files", "clean_text_result", "command_qr", "phone_photo_request", "phone_photo_result", "phone_zone", "webhook",
] as const;

export type ClientType = (typeof CLIENT_TYPES)[number];
export type ServerType = (typeof SERVER_TYPES)[number];

export type AgentState = "idle" | "listening" | "thinking" | "acting" | "speaking" | "waiting";

export interface Attachment {
  id: string;
  name: string;
  mime: string;
  size: number;
  kind: "image" | "pdf" | "office" | "text" | "audio" | "video" | "other";
  url: string;
  thumb: string | null;
  has_text?: boolean;
  error?: string | null;
  missing?: boolean;
}

export interface ToolCard {
  name: string;
  label: string;
  ok: boolean;
  summary: string;
  preview?: string;
}

export interface Message {
  id: string;
  conv_id?: string;
  role: "user" | "assistant";
  text: string;
  attachments: Attachment[];
  source?: string;
  created?: number;
  meta?: { tools?: ToolCard[]; brain?: [string, string] | null };
}

export interface Conversation {
  id: string;
  title: string;
  created: number;
  updated: number;
}

export type ServerMsg = { type: ServerType; [k: string]: any };
