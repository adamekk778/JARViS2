# JARVIS Character, Notch Panel & Desktop Pet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give JARVIS an animated blob character with 24 moods, a new notch (closed/hover/bar/live/alert/panel) and a desktop pet that walks on the taskbar and windows.

**Architecture:** Core computes the mood (`MoodEngine`) and pet physics (`PetSim`, pure Python, driven at 30 Hz by the desktop host) and broadcasts them over the existing WebSocket. One SVG `Blob` web component renders every mood and is reused by notch, panel, pet page, dashboard and mobile.

**Tech Stack:** Python 3.11+, existing FastAPI/WS core, pywebview windows; Vite + TypeScript, SVG + CSS/rAF animation, Phosphor icons.

**Spec:** `docs/superpowers/specs/2026-10-23-jarvis-character-design.md` (reference image `docs/superpowers/specs/assets/jarvis-character-reference.png`)

## Global Constraints

- Mood priority (high→low): dragged > waiting > error > limit > listening > speaking > working > thinking > updating > success > offline > focus > notify > dancing > joy > hover/opening/expanded/closing > sleeping > idle > closed.
- Timed moods: success 2 s, error 4 s, joy 3 s; sleeping after 10 min inactivity; joy at most once per hour when random.
- Offline check every 15 s; update check at start + every 24 h; update installs only after user confirmation.
- Pet: window ~220×220 (with bubble ~420×260), 30 Hz, walk 40 px/s, gravity 1800 px/s², jump reach ±250 px horizontal / 400 px up, idle 3–12 s, sleep after 5 min, max 15 window platforms ≥ 200 px wide, return to notch when dropped < 80 px from it.
- Notch sizes: closed ~200×34, bar ~360×56, panel ~1000×330; open delay 150 ms, close delay 400 ms, live linger 6 s.
- Character colors: black | midnight | violet | rose | white; size S | M | L. New config section `character` {color, glow, size, pet_mode, pet_x, pet_y}.
- Respect `prefers-reduced-motion` and `appearance.animations == "reduced"`. No em dashes in UI copy. Icons from Phosphor only.

## Review Focus

1. Pet with multiple monitors / negative coordinates → stays inside the monitor it is on (test in Task 2).
2. Window platform disappears or moves under the sitting pet → it falls to the next platform, never into the void below the taskbar (test in Task 2).
3. Error event while music plays → error shows, then returns to dancing after 4 s (test in Task 1).
4. Update check fails (private repo 404, offline) → silent, no mood change, no crash (test in Task 3).
5. Notch in `closed` while a confirm request arrives → switches to live with Ano/Ne even if panel was closed (screenshot check in Task 5).

---

### Task 1: MoodEngine + protocol + config

**Files:** Create `core/jarvis/mood.py`; Modify `core/jarvis/config.py` (add `Character`), `core/jarvis/runtime.py` (start engine, `rt.activity()`), `core/jarvis/agent.py` (joy on thanks), `core/jarvis/llm/router.py` (`AllProvidersFailed.is_limit`), `core/jarvis/server/ws.py` + `web/src/shared/protocol.ts` (types `mood_set`, `pet_command` client; `mood`, `pet_state`, `update_status` server); Test `core/tests/test_mood.py`

**Interfaces — Produces:** `MoodEngine(rt, clock=time.monotonic)`: `on_event(msg: dict)`, `tick(now=None) -> str`, `current -> dict {mood, badge, progress, detail}`, `set_manual(mood: "sleeping"|"focus"|None)`, `touch()` (activity); publishes `mood` on change. `PRIORITY: list[str]`.

- [ ] Tests: listening beats dancing; error during music → error then dancing after 4 s; success expires after 2 s; confirm_request → waiting until confirm resolved/idle; idle 10 min → sleeping, `touch()` wakes; AllProvidersFailed all-429 → limit; notify count → badge; offline flag → offline; focus manual stays until cleared; "díky" message → joy.
- [ ] Implement; extend protocol sync; run full pytest; commit.

### Task 2: Pet physics + platforms

**Files:** Create `core/jarvis/desktop/pet.py` (`PetSim`), `core/jarvis/desktop/platforms.py` (`get_platforms(monitor) -> (work_rect, list[Rect])`, Windows via EnumWindows, Null elsewhere); Test `core/tests/test_pet.py`

**Interfaces — Produces:** `Rect(x, y, w, h)`; `PetSim(work: Rect, size=96, rng=random.Random)`: `step(dt, platforms: list[Rect]) -> PetFrame(x, y, action, facing)` with action ∈ walk|idle|jump|fall|sit|sleep|held|return; `grab()`, `drag_to(x, y)`, `release() -> "landed"|"return"`, `set_focus(bool)`, `notch_point: tuple[int,int]`.

- [ ] Tests: walks and turns at platform edge; falls when platform removed and lands on taskbar line (work bottom); jumps onto a window top within reach; never leaves work rect (incl. negative-origin monitor); held follows drag, release falls; release near notch → "return"; focus → only sit; sleeps after 5 min sim time.
- [ ] Implement; commit.

### Task 3: Updater

**Files:** Create `core/jarvis/updater.py`; Modify `config.py` (`general.update_url` default `https://api.github.com/repos/adamekk778/JARViS2/releases/latest`), `server/ws.py` (`update_check`, `update_install` handled via `pet_command`-style types: add client types `update_check`, `update_install`); Test `core/tests/test_updater.py`

**Interfaces — Produces:** `Updater(rt, transport=None)`: `async check() -> dict | None` ({version, url, notes}); `async download(on_progress) -> Path`; `install(path)` (runs `/SILENT`, exits); `newer(a: str, b: str) -> bool`.

- [ ] Tests: newer("2.0.10","2.0.9") True; 404/timeout → None, no publish; found → publishes `update_status {available}`; download publishes progress; no install without explicit `update_install`.
- [ ] Implement; commit.

### Task 4: Blob character component

**Files:** Create `web/src/character/{blob.ts,looks.ts,blob.css}`, `web/character.html` + `web/src/character/gallery.ts` (dev gallery of all 24 states); Modify `web/vite.config.ts` (inputs character, pet).

**Interfaces — Produces:** `class Blob { el: HTMLElement; constructor(opts?: {size?: number; interactive?: boolean}); setMood(m: Mood, extra?: {badge?: number; progress?: number|null}); setLevel(rms: number); lookAt(x: number, y: number) /* screen px or null */; setColor(c: CharacterColor, glow?: string); peek(amount: 0..1) /* how much of the head is visible: notch closed=0.35 */ }`; `type Mood` = the 24 spec ids; `LOOKS: Record<Mood, Look>`.

- [ ] Build: SVG body (radial gradient, specular highlight, rim glow), eyes morphing via path `d` interpolation per expression, accessories as Phosphor icons/SVG overlay positioned around the body, idle loop (breath, random blink 3–7 s, glances), audio-reactive squash.
- [ ] Gallery screenshot of all 24 states; compare with reference; commit.

### Task 5: Notch rewrite + panel

**Files:** Rewrite `web/src/notch/{main.ts,style.css}`; Create `web/src/notch/panel/{panel.ts,sections.ts,panel.css}`; keep `tiles.ts` logic reused inside sections where applicable.

- [ ] Modes closed/hover/bar/live/alert/panel per spec §4–5 with Blob in notch (peek), drag-down > 60 px → `pet_command {action:"undock"}`.
- [ ] Panel: left nav 6 sections, Chat center greeting + composer → compact ChatView, right quick cards 2×2 + now playing; other sections per spec.
- [ ] Screenshots of every mode/section; commit.

### Task 6: Pet window + host wiring

**Files:** Create `web/pet.html`, `web/src/pet/{main.ts,style.css}`; Modify `core/jarvis/desktop/host.py` (pet window, 30 Hz loop thread using PetSim + platforms, undock/dock, drag via JS api `grab/drag/release`, right-click menu actions), `core/jarvis/server/app.py` (`/pet` route).

- [ ] Pet page: Blob + bubble, mouse events → `window.pywebview.api` (grab, drag_to, release, click, dblclick, menu); renders `pet_state` (hop-walk, facing, fall stretch).
- [ ] Host: undock (from notch command or tray), dock (dblclick / release near notch), persist `character.pet_mode/pet_x/pet_y`, hide in fullscreen.
- [ ] Commit.

### Task 7: Dashboard, mobile, settings

**Files:** Modify `web/src/dashboard/{main.ts,settings.ts}`, `web/src/mobile/main.ts`, `web/src/shared/chat.ts` (avatar = small Blob), `core/jarvis/config.py` (`SETTABLE_BY_VOICE` += character.color/glow/size).

- [ ] Replace orb with Blob (header, empty chat, assistant avatar); Settings → Vzhled: character color/glow/size with live preview (personalize mood); Rychlé akce: fokus, uspat.
- [ ] Build, screenshots; commit.

### Task 8: Verify, ship

- [ ] Full pytest, `npm run build`, screenshot set, push; CI green (Windows smoke + APK); new release; send installer link + APK.
