# JARVIS 2.1 Operator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend JARVIS 2.0 with permissions, agent mode + task dashboard + STOP, Windows UI Automation, a local AI manager, developer tools, chat/memory upgrades, voice mode, performance/diagnostics, and skill manifests, without changing existing behaviour.

**Architecture:** Every feature is a backend module in `core/jarvis` that is reachable through tools and WebSocket messages, plus a UI view in `web/src`.
- Tools stay `@tool` functions.
- New persistent data lives in the existing SQLite DB.
- Events go through `rt.bus`.

The WS protocol lists in `core/jarvis/server/ws.py` and `web/src/shared/protocol.ts` must stay identical; `tests/test_protocol_sync.py` enforces it.

**Tech Stack:**
- Python 3.13: FastAPI, pydantic, httpx, psutil.
- New dependencies: `uiautomation` (Windows only) and `sounddevice` (already used by voice).
- Vite + TypeScript with no framework, Phosphor icons.
- pywebview, PyInstaller + Inno Setup, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-23-jarvis-2-1-operator-design.md`

## Global Constraints

- Nothing existing is removed or renamed. Existing tests (112) keep passing.
- UI copy is Czech. JARVIS may *answer* in English (spec §8); the UI is not localized.
- No silent downloads of models. Nothing reads the clipboard, screen or microphone without an explicit user action or an enabled feature.
- Always confirm (never skippable via `trusted`): `delete_file`, `claude_code`. Also always confirm, but `trusted` may skip these: `run_shell`, `run_python`, `run_tests`, `git_commit`, `git_push`, `restore_checkpoint`, `move_files`, `system_power` (shutdown/restart), `create_skill`.
- Every new WS type is appended to both `CLIENT_TYPES`/`SERVER_TYPES` lists, in the same order.
- Every new tool has a Czech description and a `perm` (Task 1).
- New config keys get defaults so old `config.toml` files load unchanged. `tools.computer_use=false` migrates to `permissions.input=false`.
- Performance targets:
  - idle CPU < 2 % of one core, RAM < 400 MB (no local model);
  - the CI gate fails only above 2× (4 %, 800 MB).
- Commit attribution lines from the session's system reminder. Intermediate commits use `[skip ci]`.
- Commands:
  - Python tests: `cd core && timeout 300 /home/user/.venv-jarvis/bin/pytest -q`
  - Web: `cd web && npx tsc --noEmit && npx vite build`

## Review Focus

1. STOP pressed while a confirmation dialog is open. The pending confirmation resolves as rejected, the task ends `cancelled`, and no dialog is left hanging. Test in Task 3.
2. A paused task when the user sends a new chat message or presses STOP. There is no deadlock: STOP cancels it, and a new message waits for the lock exactly as it does today. Test in Task 2.
3. Local AI page opened while Ollama is not installed or not running. `local_status` returns `{"running": false}` and does not raise. Test in Task 5.
4. Dev tools given a folder outside `allowed_folders`, a folder that is not a git repo, or a machine without git installed. A clear Czech ToolResult, never an exception. Test in Task 6.
5. `message_edit` while the agent is busy, or with an id that does not exist. It is refused with an `error` event, and the history is unchanged. Test in Task 7.

---

### Task 1: Permissions + redaction

**Files:**
- Create: `core/jarvis/permissions.py`, `core/jarvis/redact.py`, `core/tests/test_permissions.py`
- Modify: `core/jarvis/config.py` (new `Permissions` model, `Config.permissions`, migration), `core/jarvis/tools/base.py` (`ToolSpec.perm`, `tool(..., perm=None)`, `schemas`, `call`), `core/jarvis/agent.py` (pass perms to `schemas`), `core/jarvis/tools/computer_use.py:102` (use `cfg.permissions.input`), `core/jarvis/__main__.py` or logging setup (install `RedactFilter` on root handlers)

**Interfaces:**
- Produces:
  - `config.Permissions(apps: bool=True, input: bool=True, screen: bool=True, files_read: bool=True, files_write: bool=True, shell: bool=True, network: bool=True, system: bool=True)`
  - `Config.permissions: Permissions`
  - `permissions.PERMS: dict[str, str]`: key → Czech label for the UI.
  - `permissions.perm_of(spec: ToolSpec) -> str`
  - `permissions.allowed(cfg, spec) -> bool`
  - `ToolSpec.perm: str | None` (None → derived)
  - `tools.schemas(disabled=(), cfg=None) -> list[dict]`: when `cfg` is given, filters out tools whose perm is off.
  - `tools.call(name, args, ctx)`: refuses with `ToolResult(False, "Oprávnění „<label>“ je vypnuté (Nastavení → Oprávnění).")` when `ctx.cfg.permissions` forbids it.
  - `redact.redact(text: str) -> str`
  - `redact.looks_secret(text: str) -> bool`
  - `redact.RedactFilter(logging.Filter)`

- [ ] **Step 1: Write failing tests** in `test_permissions.py`:
  - `test_default_mapping`: `perm_of` returns
    - `open_app`→`apps`, `computer_use`→`input`, `type_text`→`input`, `press_keys`→`input`
    - `screenshot`→`screen`, `read_text_file`→`files_read`, `list_folder`→`files_read`, `write_text_file`→`files_write`
    - `run_shell`→`shell`, `run_python`→`shell`, `create_skill`→`shell`
    - `web_search`→`network`, `browser_open`→`network`, `system_power`→`system`
    - `clipboard_get`→`apps`, `get_time`→`apps`
  - `test_schemas_filtered`: with `permissions.shell=False`, no schema named `run_shell`.
  - `test_call_refused` (async, `ctx` fixture): with `input=False`, `tools.call("type_text", {"text": "x"}, ctx)` is not ok, and its summary contains "Oprávnění".
  - `test_migration`: `Config.model_validate({"tools": {"computer_use": False}}).permissions.input is False`.
  - `test_redact`: `redact("klíč sk-abcdefghijklmnop1234 a token=ABCDEF0123456789abcdef")` contains neither secret and contains "•••". `looks_secret("heslo je Tajne123!")` is True. `looks_secret("mám rád pizzu")` is False.
- [ ] **Step 2: Run** `pytest tests/test_permissions.py -q`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement.**
  - `perm_of` uses `spec.perm` when set. Otherwise it applies `TOOL_PERM` (per-tool overrides), then `CATEGORY_PERM`:

    | Category | Perm |
    |---|---|
    | aplikace, okna, média, schránka, čas, info, nastavení, paměť, přílohy, telefon, dovednosti, tvorba | apps |
    | ovládání počítače | input |
    | obrazovka | screen |
    | soubory | files_read |
    | prohlížeč, web | network |
    | systém | system |

    `TOOL_PERM` overrides: `type_text`, `press_keys`→input; `write_text_file`, `copy_file`, `move_file`, `delete_file`, `save_attachment`→files_write; `run_shell`, `run_python`, `create_skill`, `delete_skill`→shell; `open_url`, `google_search`, `generate_image`, `youtube_search`→network.

    The fallback for anything else is `apps`. MCP tools (`source` starting with `mcp:`) map to `network`.
  - Migration: a `model_validator(mode="before")` on `Config` copies `tools.computer_use is False` into `permissions.input=False` when `permissions` is absent. Keep `Tools.computer_use` as a deprecated field.
  - Redaction regexes: `sk-[A-Za-z0-9_-]{12,}`, `gh[pousr]_[A-Za-z0-9]{20,}`, `xox[abpr]-[A-Za-z0-9-]{10,}`, `AIza[0-9A-Za-z_-]{20,}`, JWT `eyJ[\w-]+\.[\w-]+\.[\w-]+`, `(key|token|secret|password|heslo|pass)\s*[=:]\s*\S{6,}`, plus the phone pairing token passed via `redact.add_literal(s)`. Replacement is `•••`.
  - `looks_secret` is true if `redact(t) != t` or `re.search(r"\b(heslo|password|pin|passwd)\b", t, re.I)`.
  - Install `RedactFilter` on root logging handlers in the existing logging setup.
  - `Runtime.__init__` calls `redact.add_literal(cfg.phone.token)`.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(core): permission categories and secret redaction [skip ci]`

### Task 2: Task manager + agent integration (plan, pause, agent mode)

**Files:**
- Create: `core/jarvis/tasks.py`, `core/jarvis/tools/plan.py`, `core/tests/test_tasks.py`
- Modify: `core/jarvis/memory.py` (schema: 3 new tables), `core/jarvis/agent.py`, `core/jarvis/runtime.py` (`self.tasks = TaskManager(self)`), `core/jarvis/config.py` (`class AgentCfg(mode: bool=False)`, `Config.agent`, add `"agent.mode"` to `SETTABLE_BY_VOICE`), `core/jarvis/tools/__init__.py` (add `"plan"` to BUILTIN), `core/jarvis/prompt.py` (agent-mode addendum)

**Interfaces:**
- Produces:
  - `TaskManager(rt)` methods:
    - `begin(goal: str, conv_id: str) -> str`
    - `current: dict | None`
    - `set_plan(steps: list[str], current: int, note: str = "")`
    - `log_action(tool: str, args: dict, ok: bool, summary: str, ms: int)`
    - `finish(status: Literal["done","failed","cancelled"], summary: str = "")`
    - `pause() -> bool`
    - `resume() -> bool`
    - `async checkpoint()`: awaits while paused.
    - `list(limit=50, q="", status="") -> list[dict]`
    - `get(task_id) -> dict | None` (with steps and actions)
    - `clear() -> int`
  - Task dict shape: `{id, conv_id, goal, status, created, finished, summary, steps:[{idx,title,status,note}], done, total, current_action}`.
  - Publishes `task_update {task}`, throttled to at most 4 per second; the last update is always sent.
  - Tool `update_plan(steps: list[str], current: int = 0, note: str = "")`, perm `apps`, never dangerous.
  - `agent.MAX_ROUNDS_AGENT = 25`.
  - `Agent._rounds()` returns 25 when `cfg.agent.mode`, else `MAX_ROUNDS`.

- [ ] **Step 1: Write failing tests** in `test_tasks.py` (use `rt` + `FakeRouter`):
  - `test_text_answer_creates_no_task`: a plain answer → `rt.tasks.list() == []`.
  - `test_tool_call_creates_task`: script `[[("get_time", {})], "Je 10:00."]` → one task with `status == "done"`, one action `get_time` with `ok == 1`, `summary` starting "Je 10:00".
  - `test_update_plan`:
    - script `[[("update_plan", {"steps": ["a","b","c"], "current": 1})], [("get_time", {})], "Hotovo."]`
    - final steps are all `done`, `total == 3`
    - a `task_update` event was published with `steps[0].status == "done"` and `steps[1].status == "running"`.
  - `test_pause_resume` (Review Focus 2):
    - script with two tool rounds;
    - pause right after the first `tool_end` event; assert no second `tool_start` within 0.2 s; `resume()`; the task finishes `done`;
    - then a second run: pause, `rt.agent.stop()`, and the handle task returns within 1 s with the task `cancelled`.
  - `test_failed_task`: `FakeRouter([[("get_time", {})], AllProvidersFailed(...)])` → status `failed`.
  - `test_args_redacted`: `log_action("web_read", {"url": "https://x?token=ABCDEF0123456789abcdef"}, …)` → stored args contain no `ABCDEF0123456789abcdef`.
  - `test_agent_mode_rounds`: with `cfg.agent.mode=True` and `FakeRouter([[("get_time", {})]] * 40)` → `len(router.calls) == 26`.
- [ ] **Step 2: Run** `pytest tests/test_tasks.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - DB tables exactly as spec §4.1 (`CREATE TABLE IF NOT EXISTS`).
  - Agent hooks in `_run_call`:
    - before the tool, `await rt.tasks.checkpoint()`; on first call with no current task, `rt.tasks.begin(text, conv)`;
    - after the tool, `log_action` with duration;
    - `update_plan` calls go to `rt.tasks.set_plan` through the tool (the tool reads `ctx.tasks`).
  - `await rt.tasks.checkpoint()` also runs before each LLM round after round 0.
  - `finish` runs in `_handle`: `done` on normal end, `failed` on `AllProvidersFailed`/`ProviderError`, `cancelled` on `CancelledError`.
  - Pause uses `asyncio.Event` (set = running). `checkpoint` awaits it. Cancellation propagates naturally because `wait()` is cancellable.
  - Agent-mode prompt addendum: "Režim Agent: u úkolu s více kroky nejdřív zavolej update_plan se seznamem kroků, po každém kroku ho aktualizuj a na konci ověř výsledek."
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(core): task manager, update_plan, pause/resume, agent mode [skip ci]`

### Task 3: Task WS API, STOP all, confirmation details, move_files

**Files:**
- Create: `core/tests/test_stop.py`
- Modify:
  - `core/jarvis/server/ws.py`, `web/src/shared/protocol.ts` (new types)
  - `core/jarvis/agent.py` (`_ask_confirm` sends `details`, `cancel_confirms()`)
  - `core/jarvis/runtime.py` (`stop_all()`)
  - `core/jarvis/scheduler.py` (`pause_for(seconds)`)
  - `core/jarvis/tools/base.py` (`ToolSpec.details: Callable[[dict], list[str]] | None`, `tool(..., details=None)`)
  - `core/jarvis/tools/files.py` (`move_files`, `details` for delete/move/copy)
  - `core/jarvis/tools/platform/base.py` + `windows.py` + `null.py` (`release_all_input()`)
  - `core/jarvis/config.py` (`Hotkeys.stop_all = "ctrl+alt+x"`)
  - `core/jarvis/desktop/host.py` (register `stop_all` hotkey)

**Interfaces:**
- Consumes: TaskManager (Task 2).
- Produces:
  - `Runtime.stop_all() -> None`. It:
    1. calls `agent.cancel_confirms()` (resolves pending confirmations as False),
    2. stops the agent,
    3. stops the speaker and voice capture,
    4. calls `platform.release_all_input()`,
    5. calls `scheduler.pause_for(600)`,
    6. publishes `stopped {}`.
  - `confirm_request` gains `details: list[str]` (≤ 50 lines plus "…a dalších N").
  - Tool `move_files(moves: list[dict], create_dirs: bool = True)`, perm `files_write`, danger, `details` = `"src → dst"` lines. Returns `data={"moved": n, "failed": [..]}` after verifying every destination exists.
  - CLIENT_TYPES += `stop_all`, `tasks_get`, `task_get`, `task_pause`, `task_resume`, `task_cancel`, `task_retry`, `tasks_clear`.
  - SERVER_TYPES += `task_update`, `tasks`, `task`, `stopped`.
  - `task_retry {id}` spawns `agent.handle(f"Zopakuj úkol: {goal}")`.

- [ ] **Step 1: Write failing tests** in `test_stop.py`:
  - `test_stop_all_during_confirm` (Review Focus 1):
    - start `agent.handle` with a `system_power` script and wait for `confirm_request`;
    - call `rt.stop_all()`;
    - the handle task finishes within 1 s, the task status is `cancelled`, `("power", "shutdown") not in rt.platform.calls`, and `stopped` and `confirm_resolved` events (`approved=False`) were published;
    - `rt.agent.pending_confirm() is None`.
  - `test_move_files_details_and_verify` (ctx fixture, tmp files a.pdf, b.pdf):
    - `spec.details(args)` equals `["…a.pdf → …/2026/a.pdf", …]`;
    - the call moves both;
    - `data["moved"] == 2`.
  - `test_move_files_missing_source`: one missing source → `ok is False` and `data["failed"]` lists it; the other is moved.
  - `test_confirm_has_details`: the `delete_file` confirmation event contains `details` with the path.
  - `test_ws_task_api` (TestClient):
    - after one tool run, `tasks_get` returns `tasks` with 1 item;
    - `task_get` returns steps/actions;
    - `tasks_clear` empties the list.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Windows `release_all_input`: release Ctrl/Alt/Shift/Win with `keyboard.release` plus `pyautogui.mouseUp(button)` for left/right/middle.
  - Null records `("release_all_input",)`.
  - The `stop` WS message keeps its current behaviour; `stop_all` calls `rt.stop_all()`.
- [ ] **Step 4: Run** the full suite plus `test_protocol_sync`. Expected: pass.
- [ ] **Step 5: Commit** `feat: STOP all, task API, previews in confirmations, move_files [skip ci]`

### Task 4: UI Automation, mouse, screen-capture indicator

**Files:**
- Create: `core/jarvis/tools/uia.py`, `core/jarvis/tools/platform/uia_win.py`, `core/tests/test_uia.py`
- Modify:
  - `core/jarvis/tools/platform/base.py` (methods + `UiNode` TypedDict)
  - `core/jarvis/tools/platform/null.py` (fake tree)
  - `core/jarvis/tools/platform/windows.py` (delegate to `uia_win`)
  - `core/jarvis/tools/computer_use.py` (UIA context per step, `screen_capture` events)
  - `core/jarvis/tools/screenshot.py` (`screen_capture` events)
  - `core/jarvis/tools/__init__.py` (add `"uia"`)
  - `core/pyproject.toml` (`uiautomation>=2.0; sys_platform == 'win32'`)
  - `packaging/jarvis.spec` (hiddenimport `uiautomation`)
  - `core/jarvis/__main__.py` (`--selftest-uia`)
  - `core/jarvis/agent.py` TOOL_LABELS
  - `ws.py`/`protocol.ts` SERVER_TYPES += `screen_capture`

**Interfaces:**
- Produces:
  - Platform methods (Null implements them on a fixed tree for the window "Kalkulačka", with buttons "Sedm", "Krát", "Rovná se" and a text "Výsledek" whose value is "0"):
    - `ui_tree(window="", depth=4, limit=150) -> list[UiNode]`
    - `ui_find(window="", name="", role="", automation_id="", timeout=0.0) -> UiNode | None`
    - `ui_act(ref: str, action: str) -> str`
    - `ui_set_text(ref: str, text: str) -> None`
    - `ui_read(window="", limit=4000) -> str`
    - `drag(x1, y1, x2, y2) -> None`
  - Tools:
    - `ui_inspect(window="", depth=4)` (perm screen)
    - `ui_click(target, window="", action="invoke")` (perm input, `danger_if` per spec §3.2 keyword list)
    - `ui_type(target, text, window="", submit=False)` (perm input, same `danger_if`)
    - `ui_wait(name, window="", timeout=10)` (perm screen)
    - `ui_read(window="")` (perm screen)
    - `mouse(action, x=0, y=0, x2=None, y2=None, amount=0)` (perm input)
  - `ui_click`/`ui_type` results include `data={"verified": bool, "window": str, "focused": str, "value": str|None}`.
  - Event `screen_capture {active: bool, source: str}` published around each capture (try/finally).
  - Windows targets never match titles starting with "JARVIS" (`ui_*` returns "Do vlastních oken JARVIS neklikám.").

- [ ] **Step 1: Write failing tests** in `test_uia.py` (ctx fixture with NullPlatform):
  - `test_inspect_lists_buttons`: the summary/data contains "Sedm" and refs.
  - `test_click_by_name_verifies`:
    - `ui_click("Sedm", window="Kalkulačka")` → ok, `data["verified"] is True`;
    - `ctx.platform.calls` has `("ui_act", <ref>, "invoke")`.
  - `test_type_reads_back`: `ui_type("Výsledek", "84")` → `data["value"] == "84"`.
  - `test_danger_keywords`: `is_dangerous(REGISTRY["ui_click"], {"target": "Smazat vše"})` is True; for `{"target": "Sedm"}` it is False.
  - `test_own_windows_refused`: `ui_click("x", window="JARVIS")` → not ok.
  - `test_czech_unicode_names`: `ui_find(name="Rovná se")` matches case- and diacritics-insensitively (`"rovna se"`).
  - `test_mouse_drag`: `mouse("drag", 1, 2, 3, 4)` → `("drag", 1, 2, 3, 4)` in calls.
  - `test_screen_capture_events`: the `screenshot` tool publishes `screen_capture` with active True, then False.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `uia_win.py` uses `uiautomation`. Element lookup is by window title substring via `uiautomation.GetRootControl().GetChildren()`. Tree walk uses `GetChildren()` up to `depth`.
  - Refs are `f"w{win_index}:{n}"` in a dict cleared on each `ui_tree` for that window.
  - Action order: Invoke → Toggle → SelectionItem → ExpandCollapse → click at the rect centre.
  - Verification re-finds the element and reads the window title and focused control.
  - Name matching uses `unicodedata` NFKD with accents stripped and casefold.
  - `computer_use` prepends `ui_tree(window="", depth=3, limit=80)` as text to each step's prompt and adds the system line "Preferuj prvky ze stromu (ui_click/ui_type); souřadnice jen když prvek ve stromu není." Fallback is unchanged.
  - `--selftest-uia` prints the JSON of the first 10 nodes of the foreground window, or `{"skipped": "<reason>"}`; exit 0.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat: Windows UI Automation tools, mouse, screen-capture indicator [skip ci]`

### Task 5: Local AI manager

**Files:**
- Create: `core/jarvis/llm/local.py`, `core/tests/test_local_ai.py`
- Modify:
  - `core/jarvis/bootstrap.py` (no pull; publish `local_model_missing`)
  - `core/jarvis/config.py` (`Brain.local_enabled: bool=True`, `Brain.local_mode: Literal["eco","balanced","performance"]="balanced"`, `Brain.local_gpu: str=""`)
  - `core/jarvis/llm/ollama.py` (send `options`/`keep_alive` from mode)
  - `core/jarvis/llm/router.py` (skip local providers when `local_enabled` is False)
  - `ws.py`/`protocol.ts`:
    - CLIENT += `local_status`, `local_pull`, `local_pull_cancel`, `local_delete`, `local_unload`, `local_gpu_test`
    - SERVER += `local_info`, `local_pull_progress`, `local_model_missing`
    - all of these are LOCAL_ONLY

**Interfaces:**
- Produces:
  - `local.MODELS: list[dict]` (spec §5.2 table, sizes in GB as floats)
  - `local.detect_hardware() -> {"ram_gb": float, "cores": int, "gpus": [{"name": str, "vram_gb": float|None}], "disk_free_gb": float}` (cached for 1 h; GPU via PowerShell CIM on Windows, `[]` elsewhere)
  - `local.recommend(hw) -> list[str]`
  - `local.mode_options(mode, cores) -> (options: dict, keep_alive: str)`; values per spec §5.5, keep_alive `"1m"`/`"5m"`/`"30m"`
  - `class LocalManager(rt)` async methods:
    - `status() -> dict` → `{running, version, installed: [{name, size_gb}], loaded: [{name, size_vram_gb}], hardware, catalog, recommended, mode, enabled, gpu}`
    - `pull(name)`: streams `local_pull_progress`, cancellable via `cancel_pull()`
    - `delete(name)`
    - `unload()`
    - `gpu_test() -> str`: stores into `brain.local_gpu`
  - `Runtime.local = LocalManager(self)`

- [ ] **Step 1: Write failing tests** with `httpx.MockTransport`:
  - `test_status_not_running` (Review Focus 3): a transport raising `ConnectError` → `status()["running"] is False`, no exception, `catalog` non-empty.
  - `test_status_lists_installed_and_loaded`: mocked `/api/version`, `/api/tags` (size 1_929_000_000 → 1.9), `/api/ps` (`size_vram` 2e9).
  - `test_pull_progress_and_cancel`: mocked NDJSON stream with total/completed → events `local_pull_progress` with increasing `completed`; `cancel_pull()` mid-stream stops it with a final event `{"cancelled": true}`.
  - `test_gpu_test_cpu_only`: `/api/ps` `size_vram=0` → message contains "jen na procesoru" and `cfg.brain.local_gpu == "cpu"`.
  - `test_mode_options`: `mode_options("eco", 12) == ({"num_ctx": 2048, "num_thread": 3}, "1m")`; balanced → `(4096, 6, "5m")`; performance → `(8192, 11, "30m")`.
  - `test_bootstrap_never_pulls`: the bootstrap function with a missing model makes no POST to `/api/pull` and publishes `local_model_missing {name: "qwen2.5:3b", size_gb: 1.9}`.
  - `test_router_skips_local_when_disabled`: `local_enabled=False` → the chain used by the router excludes `ollama`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement** as specified. `recommend`: ram < 16 → names with size ≤ 3.5; otherwise everything ≤ 6.0. `qwen2.5:3b` is always first. When `local_enabled` flips to False, call `unload()` once (in `Runtime.update_config`).
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat: local AI manager (hardware, catalog, pull with consent, modes, GPU test) [skip ci]`

### Task 6: Developer tools

**Files:**
- Create: `core/jarvis/tools/dev.py`, `core/tests/test_dev.py`
- Modify: `core/jarvis/tools/__init__.py` (add `"dev"`), `core/jarvis/tools/files.py` (`write_text_file`/`move_files` call `dev.auto_checkpoint(ctx, path)`), `core/jarvis/agent.py` TOOL_LABELS

**Interfaces:**
- Produces:
  - Tools with signatures and perms exactly as in spec §6:
    - `git_status(project)`
    - `git_diff(project, path="", staged=False)`
    - `git_log(project, n=15)`
    - `git_commit(project, message, add_all=True)`
    - `git_push(project)`
    - `checkpoint(project, label="")`
    - `checkpoints(project)`
    - `restore_checkpoint(project, id)`
    - `compare_files(a, b)`
    - `run_tests(project, command="")`
    - `claude_code(project, task)`
  - `dev.resolve_project(ctx, project) -> Path | ToolResult`: accepts an absolute path or a folder name inside an allowed folder. Allowed = `cfg.tools.allowed_folders`, or `~/Documents/Projekty` if empty.
  - `dev.auto_checkpoint(ctx, path) -> str | None`: at most once per `rt.tasks.current["id"]` per repo.
  - Checkpoint ids are `YYYYMMDD-HHMMSS`; refs are `refs/jarvis/checkpoints/<id>`; non-git fallback dir is `paths.sub("checkpoints")/<project-name>/<id>/`.

- [ ] **Step 1: Write failing tests** (real `git` in `tmp_path`; skip the module if `shutil.which("git")` is None):
  - `test_outside_allowed_refused` (Review Focus 4): `git_status("/etc")` → not ok, "povolených složek" in summary.
  - `test_not_a_repo`: allowed folder without `.git` → `git_status` not ok, "není git repozitář".
  - `test_git_missing`: monkeypatch `shutil.which` → None → not ok, "winget install Git.Git".
  - `test_checkpoint_keeps_head_and_tree`:
    - repo with one commit; modify `a.txt`;
    - `checkpoint` → HEAD sha unchanged, `a.txt` still modified, `git for-each-ref refs/jarvis/checkpoints` has 1 ref.
  - `test_restore_checkpoint`:
    - checkpoint, modify again, restore;
    - `a.txt` content equals the checkpointed content;
    - a second ref (the automatic backup) exists;
    - `spec.details(args)` lists `a.txt`.
  - `test_checkpoint_untracked`: an untracked `new.txt` is included and restored.
  - `test_compare_files`: two files → `data == {"added": 1, "removed": 1}`, summary contains a `@@` line.
  - `test_run_tests_detects_pytest`: a folder with `pyproject.toml` → command `python -m pytest -q` (use monkeypatched subprocess).
  - `test_claude_code_missing`: `which("claude")` None → not ok with installation hint.
  - `test_auto_checkpoint_once_per_task`: two `write_text_file` calls inside one task → 1 ref.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - All git calls use `subprocess.run([...], cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=60, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})` inside `asyncio.to_thread`.
  - `checkpoint` algorithm:
    1. `GIT_INDEX_FILE=<tmp>` copy of `.git/index`;
    2. `git add -A` into that temp index;
    3. `tree=$(git write-tree)`;
    4. `commit=$(git commit-tree <tree> -p HEAD -m "JARVIS checkpoint <label>")`;
    5. `git update-ref refs/jarvis/checkpoints/<id> <commit>`.

    This captures untracked files without touching the real index or working tree.
  - `restore_checkpoint`: create a backup checkpoint, then `git checkout <commit> -- .`, then delete files tracked in HEAD-or-backup but absent from the checkpoint tree (from `git diff --name-only --diff-filter=A <commit> <backup>`).
  - `claude_code`: `[claude, "-p", task, "--output-format", "json"]` with timeout 900 s, cancellable (`proc.kill()` on CancelledError). Report `git status --porcelain` before and after.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat: developer tools (git, checkpoints, compare, tests, Claude Code) [skip ci]`

### Task 7: Chat and memory backend

**Files:**
- Create: `core/tests/test_chat_memory.py`
- Modify:
  - `core/jarvis/memory.py`: `folder` column migration; methods:
    - `truncate_from(msg_id) -> dict | None`: returns the removed user message
    - `rename(conv_id, title)`
    - `move(conv_id, folder)`
    - `export(include_conversations: bool) -> dict`
    - `import_data(data, merge=True) -> dict`
  - `core/jarvis/tools/memory_tools.py`: `remember` refuses when `redact.looks_secret`
  - `ws.py`/`protocol.ts`:
    - CLIENT += `message_edit`, `conversation_rename`, `conversation_move`, `memory_export`, `memory_import`
    - SERVER += `memory_export_data`, `memory_import_result`
    - `memory_import` is LOCAL_ONLY
  - `list_conversations` rows include `folder`

**Interfaces:**
- Produces:
  - Export JSON `{"version": 1, "exported": iso, "facts": [{"text","created"}], "conversations"?: [{"id","title","folder","created","messages":[{"role","text","ts"}]}]}`.
  - `import_data` returns `{"facts_added": n, "facts_skipped": n, "conversations_added": n}`. It raises `ValueError("Neplatný soubor paměti")` on a bad shape.
  - `message_edit {id, text}`:
    - when `agent.busy` → `error {message: "Počkej, až JARVIS dokončí odpověď."}`;
    - unknown id → `error`;
    - else truncate, publish `history`, spawn `agent.handle(text, original_attachments, source)`.

- [ ] **Step 1: Write failing tests:**
  - `test_truncate_from_middle`: 4 messages (u1, a1, u2, a2); `truncate_from(u2.id)` → recent is [u1, a1], returns u2.
  - `test_message_edit_busy_refused` (Review Focus 5):
    - TestClient; set `rt.agent.busy = True`; send `message_edit`;
    - receive `error`; the history count is unchanged.
  - `test_message_edit_unknown_id`: `error`, nothing changes.
  - `test_rename_and_folder`: `conversation_rename` / `conversation_move` → `conversations` event shows the new title and `folder == "Práce"`.
  - `test_folder_migration`: an old DB without the `folder` column opens and gets the column.
  - `test_export_import_roundtrip`:
    - export with conversations → import into a fresh DB with merge;
    - counts match;
    - re-import skips duplicate facts.
  - `test_import_bad_shape`: `{"foo": 1}` → `ValueError`.
  - `test_remember_refuses_secret`: `remember("heslo k wifi je Kocka123")` → not ok.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.** The migration checks `PRAGMA table_info(conversations)` and runs `ALTER TABLE ... ADD COLUMN folder TEXT DEFAULT ''` when the column is missing.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat: message editing, conversation folders/rename, memory export/import [skip ci]`

### Task 8: Voice: follow-up, English, output device

**Files:**
- Create: `core/jarvis/lang.py`, `core/tests/test_voice_lang.py`
- Modify:
  - `core/jarvis/config.py`:
    - `Voice.followup: bool=False`
    - `Voice.output_device: str=""`
    - `Voice.tts_voice_en: str="en-GB-RyanNeural"`
    - `Voice.piper_voice_en: str="en_GB-alan-medium"`
    - `stt_language` accepts `"auto"`
  - `core/jarvis/voice/stt.py` (return the detected language)
  - `core/jarvis/voice/tts.py` (voice per language, output device)
  - `core/jarvis/voice/loop.py` (follow-up listening window 6 s)
  - `core/jarvis/agent.py` (`handle(..., lang: str = "")` → adds "Odpověz anglicky." to `extra_system` when `lang == "en"`)
  - `ws.py`/`protocol.ts`: CLIENT += `audio_devices_get`, `voice_mode`; SERVER += `audio_devices`

**Interfaces:**
- Produces:
  - `lang.detect(text: str) -> Literal["cs","en"]`. It returns `"en"` when there is no Czech diacritic and the share of tokens in a fixed English stop-word set ≥ 0.25 with at least 3 tokens.
  - `Transcriber.transcribe(...) -> tuple[str, str]` (text, lang). Callers are updated.
  - `Speaker.speak(text, lang="cs")`
  - `VoiceLoop.followup_window(seconds=6.0)`: starts listening without wake word and publishes `state listening` with `followup=True`. It ends on silence, "díky, to je vše", "stop", or "that's all".
  - `voice_mode {on: bool}` sets a runtime flag; follow-up is always on in voice mode.
  - `audio_devices {inputs: [str], outputs: [str]}` via `sounddevice.query_devices()`. It returns empty lists when unavailable.

- [ ] **Step 1: Write failing tests:**
  - `test_detect`: "Open Spotify and play some music please" → en; "otevři Spotify" → cs; "ok" → cs.
  - `test_agent_english_hint`: `handle("what time is it", lang="en")` → the system message contains "Odpověz anglicky".
  - `test_chat_text_english`: a chat `user_text` in English → the agent gets `lang="en"` (via `lang.detect`).
  - `test_tts_voice_choice`: `Speaker._voice_for("en")` == `cfg.tts_voice_en`.
  - `test_followup_ends_on_phrase`: fake STT returning "díky, to je vše" → the window closes and no agent call is made.
  - `test_audio_devices_empty_without_sounddevice`: monkeypatch import failure → `{"inputs": [], "outputs": []}`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement** per spec §7–8. The output device is passed as `device=` to `sounddevice.play`; empty means the default.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(voice): follow-up listening, English replies, output device [skip ci]`

### Task 9: Performance, diagnostics, system stats, performance report

**Files:**
- Create: `core/jarvis/diagnostics.py`, `core/tests/test_diagnostics.py`
- Modify:
  - `core/jarvis/tools/system.py`: `system_snapshot()` gains `disks`, `net_up_kbps`, `net_down_kbps`, `gpu`; new tool `performance_report()`
  - `core/jarvis/llm/router.py`: record time-to-first-token per provider, keeping the last 20 in a deque
  - `core/jarvis/__main__.py`: `--bench [seconds]`
  - `ws.py`/`protocol.ts`:
    - CLIENT += `diagnostics_get`, `diagnostics_export`
    - SERVER += `diagnostics`, `diagnostics_file`
    - `diagnostics_export` is LOCAL_ONLY

**Interfaces:**
- Produces:
  - `diagnostics.snapshot(rt) -> {"cpu_pct": float, "ram_mb": float, "threads": int, "children": [{"name","pid","ram_mb"}], "loop_lag_ms": float, "ttft": {provider: [ms]}, "voice": {...}, "log_tail": [str]}` (log tail redacted, last 100 lines of `jarvis.log`)
  - `diagnostics.export_zip(rt) -> Path`: logs plus config with `SECRET_KEYS` removed and text redacted.
  - `diagnostics.bench(seconds: int) -> dict` = `{"startup_s", "cpu_pct", "ram_mb", "seconds", "targets": {"cpu_pct": 2.0, "ram_mb": 400}}`. It runs Runtime start without UI or voice and samples `psutil.Process().cpu_percent` every second after a 3 s warm-up.
  - `--bench N` prints `bench(N)` JSON and exits 0. With `--bench-gate` it exits 1 if cpu > 4.0 or ram > 800.
  - GPU stats (Windows): name via CIM. Utilisation via `Get-Counter` runs only when `system_get` arrives with `{"gpu": true}`, at most every 3 s (cached). Otherwise `None`.
  - Network rate comes from the difference between consecutive snapshots.
  - Tool `performance_report()` (perm system, read-only). Data: top processes by CPU and RAM, memory percent, disk free per drive, startup entries count (HKCU/HKLM Run plus Startup folders, read-only), uptime h. The summary is a Czech list of recommendations (rule-based: RAM > 85 % → close the top RAM process; startup entries > 10 → review startup; disk < 10 % → free space). Never acts.

- [ ] **Step 1: Write failing tests:**
  - `test_snapshot_shape`: keys are present and types are correct.
  - `test_export_zip_has_no_secrets`:
    - config with `phone.token="SECRET_TOKEN_123456"` and a log line containing `sk-abcdefghijklmnop1234`;
    - no zip member contains either string.
  - `test_bench_runs`: `bench(2)` returns all keys within 15 s.
  - `test_system_snapshot_net_and_disks`: two calls → `net_down_kbps` is a float ≥ 0 and `disks` is a non-empty list of `{mount, used_pct, free_gb}`.
  - `test_performance_report_read_only`: summary non-empty, `ctx.platform.calls` gets no new entries.
  - `test_ttft_recorded`: after one `FakeRouter`-free real router call with a mock transport, the deque has 1 value.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.** Loop lag is measured by a background task sleeping 0.5 s and recording the overshoot. It is started only while a dashboard has requested `diagnostics_get` within the last 10 s.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat: diagnostics, --bench, richer system stats, performance report [skip ci]`

### Task 10: Skill manifest, runner, approval

**Files:**
- Create: `core/jarvis/skill_runner.py`, `core/tests/test_skill_runner.py`
- Modify:
  - `core/jarvis/tools/skills.py`: parse the `SKILL` manifest via `ast.literal_eval` of the top-level assignment, without executing code; keep the approved list in config; wrap tools to run in a subprocess
  - `core/jarvis/config.py`: `Tools.approved_skills: list[str] = []` (names); skills created by `create_skill` are added automatically
  - `ws.py`/`protocol.ts`: CLIENT += `skill_approve {name, approved}`; `skills` items gain `manifest`, `approved`, `code`

**Interfaces:**
- Produces:
  - `skills.read_manifest(path) -> {"name","description","version","permissions": list[str],"timeout": int}` (defaults `[]`, 30; timeout clamped to 1..300).
  - Unapproved skills are listed but not registered.
  - A registered skill tool gets `perm` = first permission or `apps`. Its call runs `python -m jarvis.skill_runner <file> <tool> <json-args>`; in the frozen exe, `sys.executable --run-skill ...`, so `__main__` accepts `--run-skill`. The runner prints a JSON ToolResult to stdout. On timeout → kill and `ToolResult(False, "Skill překročil časový limit <t> s")`. On non-zero exit → `ToolResult(False, "Skill spadl: <last stderr line>")`. STOP cancels it (kill).
  - The ctx inside the runner offers `http()`, `notify()` (prints a notify record which the parent forwards), and `platform` only if `input` or `apps` is in the permissions, else an object raising `PermissionError`.

- [ ] **Step 1: Write failing tests:**
  - `test_manifest_parse_without_exec`: a file whose body would raise on import still yields the manifest.
  - `test_unapproved_not_registered`: a foreign skill file in `skills_dir` → `list_skills()` shows `approved: False`, and the tool is not in REGISTRY.
  - `test_create_skill_auto_approved`.
  - `test_runner_timeout`: a skill sleeping 5 s with timeout 1 → not ok, "časový limit", finishes in < 3 s.
  - `test_runner_crash`: a skill raising → not ok, "Skill spadl".
  - `test_runner_result`: a skill returning `ToolResult(True, "ahoj", data={"x": 1})` → same at the parent.
  - `test_permission_from_manifest`: `permissions: ["network"]` → `perm_of(spec) == "network"`; with `network` off the tool is filtered.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement** as above. `create_skill` adds `SKILL = {...}` to its template text so new skills carry a manifest.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(skills): manifest, isolated runner with timeout, approval [skip ci]`

### Task 11: Web UI: tasks, STOP, notch indicators, sounds, efficient animation

**Files:**
- Create: `web/src/dashboard/tasks.ts`, `web/src/shared/sounds.ts`, `web/src/shared/taskcard.ts`
- Modify:
  - `web/src/dashboard/main.ts`: NAV gains `["tasks","list-checks","Úkoly"]` after chat; header STOP button visible while busy
  - `web/src/notch/main.ts` + `style.css`: task line in the live bubble, STOP button in bar/live while busy, red screen-capture dot/chip, `notch.pinned` persisted via `settings_set`, sounds on events
  - `web/src/notch/panel.ts`: Agent-mode toggle; quick actions "Shrň / Přelož / Vysvětli schránku" (read the clipboard via `navigator.clipboard.readText()` only on click, then `user_text`)
  - `web/src/shared/chat.ts`: confirmation card renders `details` as a scrollable list
  - `web/src/mobile/main.ts`: task card above the chat, STOP
  - `core/jarvis/desktop/host.py`: tray items "Shrň schránku" / "Přelož schránku" / "Vysvětli schránku" (read the clipboard only on click via `rt.platform.clipboard_get()`, then `rt.submit(rt.agent.handle(...))`), plus a tray item "STOP" → `rt.stop_all()`
  - `web/src/character/blob.ts`: fps cap
  - `core/jarvis/config.py`: `Notch.pinned: bool=False`, `Appearance.sounds: bool=True`, `Appearance.sound_volume: int=30`

**Interfaces:**
- Consumes:
  - `task_update`, `tasks`, `task` events and the `task_*`/`stop_all` messages (Task 3)
  - `screen_capture` (Task 4)
  - `stopped`
- Produces:
  - `TaskCard(client): {el, update(task)}`: shared by dashboard, notch panel and mobile.
  - `sounds.play(name: "wake"|"listen"|"done"|"error"|"notify")`: WebAudio oscillators ≤ 250 ms. Volume `appearance.sound_volume/100 * 0.3`. No-op when `appearance.sounds` is false or `animations` reduced *and* the volume is 0.
  - Blob: `frame()` skips rendering when `now - lastRender < 1000/cap`, where:
    - cap = 10 when `animations: reduced`;
    - 20 when the mood is in `idle|closed|sleeping|focus` and no pointer move for 3 s;
    - otherwise unlimited.
  - Blob exposes `renderedFrames` for testing.

- [ ] **Step 1: Implement** the files above following existing patterns (`h()`, `icon()`, `toast()` from `shared/dom.ts`, CSS tokens in the existing style files).
  - The Tasks page content is specified in spec §4.5.
  - Copy: "Úkoly", "Pozastavit", "Pokračovat", "Zrušit", "Zopakovat", "STOP", "Smazat historii", "Vidím obrazovku", "Krok {i}/{n}".
- [ ] **Step 2: Typecheck/build:** `cd web && npx tsc --noEmit && npx vite build`. Expected: no errors.
- [ ] **Step 3: Visual check.**
  - Start the demo server (`scratchpad/demo_server.py`).
  - Script a 3-step task with `update_plan` in its `DemoRouter`.
  - Playwright screenshots of `/#tasks` mid-task, the notch live bubble with the step line + STOP, the screen-capture dot, and a confirmation with details.
  - Check them by viewing.
- [ ] **Step 4: FPS check.** In the character gallery with `?mood=idle`, after 4 s without pointer movement, `renderedFrames` over 2 s ≤ 45. With `?mood=dancing` it is > 90 (headless Chromium runs at 60 Hz).
- [ ] **Step 5: Commit** `feat(web): tasks page, STOP, screen indicator, sounds, efficient idle animation [skip ci]`

### Task 12: Web UI: settings pages, chat editing/folders, voice mode, diagnostics

**Files:**
- Create: `web/src/dashboard/voice-mode.ts`, `web/src/dashboard/diagnostics.ts`
- Modify:
  - `web/src/dashboard/settings.ts`: new section `permissions`; Brain gains a "Lokální AI" card plus local/cloud badges; Voice gains output device, `auto` language, follow-up; Memory gets tabs, export/import; Skills get manifest/approval; a settings search box
  - `web/src/dashboard/main.ts`: NAV gains `permissions` (icon `shield-check`, "Oprávnění"), `voice-mode` (icon `microphone-stage`, "Hlasový režim"), `diagnostics` (icon `pulse`, "Diagnostika")
  - `web/src/shared/chat.ts`: pencil on own messages → inline editor → `message_edit`; conversation list grouped by folder with context menu (Přejmenovat / Přesunout do složky / Smazat); cpu/cloud icon on the brain badge from `PRESETS[provider].local`
  - `web/src/notch/panel.ts`: button to the voice mode

**Interfaces:**
- Consumes: `local_*` (Task 5), `message_edit`/`conversation_*`/`memory_*` (Task 7), `audio_devices`/`voice_mode` (Task 8), `diagnostics*`/`system_get {gpu:true}` (Task 9), `skills`/`skill_approve` (Task 10), `config.permissions` + `permissions.PERMS` labels (sent in `settings` as `perm_labels`; add to `settings_get` in `ws.py`).

- [ ] **Step 1: Implement** per spec §2, §5.3–5.7, §7, §8.
  - The Local AI card shows:
    - hardware, Ollama status (or "Ollama neběží – Spustit / Stáhnout Ollamu" link to https://ollama.com/download);
    - catalog rows with size, disk free, installed/loaded badges;
    - Stáhnout (with confirm "Stáhnout <name> (<size> GB)?"), progress bar + Zrušit;
    - Smazat, Uvolnit z paměti, Otestovat GPU, mode select (Úsporný/Vyvážený/Výkon), "Lokální AI zapnutá" switch;
    - the sentence about Claude Code subscriptions from spec §5.7.
  - Settings search filters `.card` elements by normalized text (NFD, accents stripped, lowercase); "Nic nenalezeno".
  - Voice mode: Blob size 280, a canvas waveform from `level` events, the last exchange text, and a big talk/stop button. It sends `voice_mode {on:true}` on enter and `{on:false}` on leave.
  - Diagnostics polls `diagnostics_get` every 2 s while visible. The button "Proč je PC pomalý?" sends `user_text` "Proč je můj počítač pomalý? Použij performance_report." and switches to chat. "Exportovat diagnostiku" downloads the zip from `diagnostics_file.url`.
- [ ] **Step 2: Typecheck/build.** Expected: no errors.
- [ ] **Step 3: Visual check** with demo server screenshots:
  - Oprávnění, Mozek → Lokální AI (mock Ollama not running and running), Hlasový režim, Diagnostika;
  - chat with the edit pencil and editor open, conversation folders, settings search with results and without;
  - Paměť tabs.
- [ ] **Step 4: Run** Python tests (`settings_get` change). Expected: pass.
- [ ] **Step 5: Commit** `feat(web): permissions, local AI, voice mode, diagnostics, message editing, folders, settings search [skip ci]`

### Task 13: Packaging, CI, release v2.1

**Files:**
- Modify:
  - `packaging/jarvis.spec` (hidden imports: `uiautomation`, `comtypes`, `jarvis.skill_runner`, `jarvis.tools.dev`, `jarvis.tools.uia`, `jarvis.tools.plan`)
  - `core/pyproject.toml` (deps)
  - `.github/workflows/build.yml`: windows job, after the smoke tests, runs
    - `dist\JARVIS\JARVIS-debug.exe --bench 30 --bench-gate`
    - `dist\JARVIS\JARVIS-debug.exe --selftest-uia`

    and prints both outputs.
  - `core/jarvis/__init__.py` `__version__ = "2.1.0"`
  - Release tag scheme: keep `v2.0.${run_number}` → change to `v2.1.${run_number}`.

- [ ] **Step 1: Make the changes.**
- [ ] **Step 2: Verify locally.**
  - Full pytest and the web build.
  - `python -m jarvis --bench 5` prints JSON.
  - `python -m jarvis --selftest-uia` prints `{"skipped": ...}` on Linux.
- [ ] **Step 3: Review.** Run a whole-branch code review (`superpowers:requesting-code-review`) and fix blocking findings.
- [ ] **Step 4: Push and watch CI.**
  - Commit without `[skip ci]` and push to `ccr-1cc910fa-r3hpnj`.
  - Watch the run with `gh run watch <id> --exit-status`.
  - On failure, reproduce, fix and re-push until green.
- [ ] **Step 5: Deliver.**
  - Download `JARVIS-Setup.exe` and `JARVIS.apk` from the release into `downloads/` and send them to the user.
  - Report the bench numbers from the CI log verbatim and the UIA selftest outcome.
  - List what could not be verified (real app clicking on the user's PC, RX 6600 acceleration).
