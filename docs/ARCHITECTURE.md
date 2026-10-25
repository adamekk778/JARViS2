# Architektura JARVIS (stav 3.6 / OMEGA řez 1)

Skutečný stav kódu, ne cílová vize. Cíl a jeho mapování: `OMEGA_SPEC.md`, `FEATURE_AUDIT.md`, `FEATURE_MATRIX.md`.

## Přehled

```
 Windows PC                                                            Telefon (Android, Capacitor 8)
 ┌──────────────────────────────────────────────────────────────┐     ┌──────────────────────────────┐
 │ JARVIS.exe (PyInstaller)                                     │     │ web UI (mobile/*) ── WS      │
 │  desktop/host.py  ── pywebview (WebView2) okna:              │     │ LinkService (Java)           │
 │     notch · celý chat · dashboard · Stark HUD                │◄───►│   long-poll /api/phone/poll  │
 │  tray, globální zkratky, per-pixel alpha, DPI PMv2           │ LAN │   ring/dial/SMS/find, baterie│
 │                                                              │ /TS │ NotifMirror (oznámení → PC)  │
 │  server/app.py  FastAPI + WebSocket :8765  (token, origin)   │     │ CallActivity (JARVIS volá)   │
 │  runtime.py  ── jedno sdílené jádro:                         │     └──────────────────────────────┘
 │    agent.py (LLM smyčka, nástroje, potvrzení, STOP)          │
 │    llm/router.py (řetěz poskytovatelů + místní modely)       │
 │    tools/* (≈150 nástrojů, @tool registr, oprávnění)         │
 │    tasks.py (mise: plán, audit, kritéria, artefakty, důkazy) │
 │    memory.py (SQLite: konverzace, fakta, kv)                 │
 │    scheduler.py · automations.py · stark.py (strážce, brífink│
 │    protokoly) · skillforge.py · powers.py · mail.py ·        │
 │    calendar_.py · phone.py · home.py · network.py · mood.py  │
 │    voice/* (wake word, STT, TTS) · dictation.py · notetaker  │
 │  web/dist (Vite + TypeScript, bez frameworku)                │
 └──────────────────────────────────────────────────────────────┘
```

## Zásady jádra
- **Jedno jádro, žádné duplikáty.** Plánovač je jen `scheduler.py`, paměť jen `memory.py`, oprávnění jen
  `permissions.py`, mise jen `tasks.py`, složené dovednosti jsou protokoly (`config.stark.protocols`) verzované
  v `skillforge.py`, postavička je jen `web/src/character/blob.ts` řízená `mood.py`.
- **Každý nástroj** (`tools/base.py @tool`) má schéma, kategorii oprávnění, příznak nebezpečnosti (`danger`/`danger_if`)
  a náhled pro potvrzovací dialog (`details`). Nebezpečné akce čekají na schválení (PC dialog nebo otisk na telefonu).
- **Události** jdou přes `events.Bus` → WebSocket. Typy zpráv jsou v `server/ws.py` a `web/src/shared/protocol.ts`;
  shodu hlídá `tests/test_protocol_sync.py`.
- **Cizí data nejsou pokyny.** Obsah e-mailů, zpráv z telefonu, webů a automatizací se modelu předává s označením
  „cizí data“ (`tools/mail_tools.py`, `automations.THIRD_PARTY`).
- **Tajemství** jen v trezoru OS (`secrets.py` → keyring/Windows Credential Manager); logy a audit jdou přes `redact.py`.

## Mise (OMEGA §4.5) – `tasks.py`
Stavový automat: `running → (paused | waiting) → verifying → done | failed | cancelled`; po restartu se nedokončené
mise přepnou na `interrupted` (`TaskManager.recover`) a jdou zopakovat. Tabulky SQLite: `tasks` (+ `criteria`),
`task_steps`, `task_actions` (audit každé akce, redigovaný), `task_artifacts` (soubor + SHA-256 + velikost),
`task_evidence` (zdroj, tvrzení, hodnota, ok). UI: Úkoly (Mission Control), karta mise v notchi a v mobilu.
Typy z OMEGA §6 se mapují takto: `Mission`=tasks, `Step`=task_steps, `Artifact`=task_artifacts,
`Evidence`=task_evidence, `ApprovalRequest`=confirm_request, `ExecutionResult`=ToolResult, `Tool`=ToolSpec,
`SkillManifest`=skillforge.manifest, `EventEnvelope`=Bus zpráva `{type, …}`, `DeviceIdentity`=párovací token.

## První vertikální řez (OMEGA §6) – `pcreport.py` + `tools/mission_tools.py`
„Zjisti stav mého počítače, připrav report a ulož ho“ → nástroj `pc_health_report` (hlasem/chatem přes AI, nebo
tlačítkem Zkontrolovat PC bez AI) → plán 4 kroky → jeden PowerShell proces s pevným skriptem jen z `Get-*` cmdletů
+ psutil → každá část má zdroj a čas, neměřitelné = „neznámé“ s důvodem → HTML report v Dokumenty\JARVIS\Reporty
→ artefakt se SHA-256 → ověření 5 kritérií proti souboru na disku → stav done/failed, postavička se raduje/mračí.
Na skutečných Windows to ověřuje CI (`JARVIS-debug.exe --selftest-report`).

## Skill Forge – `skillforge.py`
Složená dovednost = protokol z existujících nástrojů (žádný nový kód, tudíž bez sandboxu). Vznik z dokončené mise
(`save_mission_as_skill` nebo tlačítko v Úkolech) vždy s náhledem kroků a schválením; manifest (nástroje, oprávnění,
problémy); každá uložená změna = nová verze (`skill_versions`); návrat na libovolnou verzi. Kódové skilly mají
vlastní schvalovací tok (`tools/skills.py`, `skill_runner.py`).

## Build a nasazení
GitHub Actions (`.github/workflows/build.yml`): testy jádra, web build, Windows (PyInstaller + Inno Setup +
kontroly na skutečném Windows: notch, HUD, celý chat, UI Automation, označený text, report PC, benchmark nečinnosti),
Android (Capacitor + nativní Java), release s `JARVIS-Setup.exe` a `JARVIS.apk`.
