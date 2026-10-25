# FEATURE MATRIX – funkce → sdílené jádro

Které existující moduly/nástroje nesou které funkce. Jedna schopnost = jedna implementace; překrývající se položky katalogu i původního seznamu ukazují na stejný modul (žádné duplikáty: jeden plánovač `scheduler.py`, jedna paměť `memory.py`, jeden systém oprávnění `permissions.py`, jedny mise `tasks.py`, jedna postavička `character/blob.ts`). Generováno `docs/audit/build_audit.py`.

| Modul / nástroj | Funkce (ID) |
|---|---|
| `Claude Code` | 046, 049, 331, 339, 340, 345, 735, P5.01, P5.02, P5.03, P5.04, P5.05, P5.06, P5.07, P5.10, P5.13, P5.14, P6.02, P10.05 |
| `computer_use` | 116, 117, 118, 531, P2.02, P4.04, P11.03 |
| `tasks.py` | 002, 010, 152, 209, 217, 223 |
| `Home Assistant` | 165, 423, 434, P13.02, P13.05 |
| `STOP` | 176, 405, P3.04, P6.07, P14.04 |
| `find_file` | 038, 316, 322, P2.11, P11.11 |
| `make_website` | 352, 353, 354, P5.02, P6.05 |
| `pcreport.py` | 011, 012, 013, 025, P2.08 |
| `run_python` | 457, 766, 768, P5.12, P11.10 |
| `UI Automation` | 028, 274, P2.03, P4.02 |
| `mood.py` | 076, 241, 737, P7.01 |
| `powers.py` | 026, 027, 077, 236 |
| `run_shell` | P2.05, P2.13, P5.11, P5.12 |
| `run_tests` | 058, 339, 340, P5.08 |
| `ui_read` | 028, 033, P2.03, P4.03 |
| `update_plan` | 001, 198, 202, P1.05 |
| `home.py` | 165, 435, P13.01 |
| `notetaker.py` | 128, 166, 167 |
| `pc_health_report` | 025, 224, P6.04 |
| `speed_test` | 021, 311, 717 |
| `stark.py` | 034, 303, 508 |
| `tests/test_omega.py` | 002, 025, 076 |
| `tools/dev.py` | 046, 050, 058 |
| `web_read` | 003, P6.03, P11.01 |
| `web_search` | 003, P6.03, P11.01 |
| `app_open` | 034, P12.06 |
| `automations.py` | 034, 147 |
| `browser_type` | 530, P11.03 |
| `character/looks.ts` | 250, 251 |
| `claude_bridge.py` | 046, P5.01 |
| `close_app` | P2.01, P2.06 |
| `desktop/host.py` | 226, P8.01 |
| `home_control` | 424, P13.01 |
| `mail.py` | 541, P11.05 |
| `memory.py` | 039, P1.03 |
| `move_files` | 325, P2.11 |
| `network.py` | 165, 406 |
| `network_devices` | 021, 426 |
| `open_app` | P2.01, P12.09 |
| `permissions.py` | 177, P14.01 |
| `phone.py` | 145, 541 |
| `screen_time` | 313, 792 |
| `search_history` | 038, 520 |
| `send_to_phone` | 138, 408 |
| `storage_report` | 327, P2.11 |
| `system_snapshot` | 190, 304 |
| `tools/files.py` | 029, 511 |
| `tools/uia.py` | 028, 274 |
| `top_processes` | 305, P2.06 |
| `ui_inspect` | 028, P2.03 |
| `wake_word` | 098, P3.01 |
| `agent.py` | 001 |
| `audio_devices` | 105 |
| `break_minutes` | 077 |
| `calendar_.py` | 171 |
| `character/blob.ts` | 071 |
| `claude_code` | 046 |
| `clipboard_set` | 138 |
| `compare_files` | 029 |
| `copy_file` | P2.11 |
| `danger_if` | 203 |
| `dashboard/palette.ts` | 757 |
| `dashboard/tasks.ts` | 002 |
| `delete_file` | P14.02 |
| `dictation.py` | 097 |
| `email_search` | 551 |
| `email_send` | P11.06 |
| `fact_delete` | 039 |
| `fact_update` | 039 |
| `finance.py` | 379 |
| `foreground_info` | 026 |
| `generate_image` | 132 |
| `git_log` | 050 |
| `git_status` | P5.09 |
| `home_scene` | 423 |
| `hone.java` | 420 |
| `link_alive` | 410 |
| `list_folder` | P2.11 |
| `local_unload` | 576 |
| `looks_secret` | 681 |
| `mcp_client` | 048 |
| `media_control` | P12.01 |
| `media_player` | P13.03 |
| `memory_export` | 045 |
| `memory_import` | 045 |
| `memory_wipe` | 794 |
| `mobile/native.ts` | 143 |
| `pairing_get` | 184 |
| `phone_battery` | 417 |
| `press_keys` | P2.02 |
| `price_alert` | 379 |
| `provider_test` | 587 |
| `read_text_file` | P5.05 |
| `read_website` | P11.04 |
| `redact.py` | 179 |
| `restore_checkpoint` | 328 |
| `scheduler.py` | 155 |
| `send_file` | P9.03 |
| `server/pairing.py` | 144 |
| `shared/taskcard.ts` | 087 |
| `skillforge.py` | 150 |
| `speak_mode` | P3.07 |
| `stop_all` | 176 |
| `task_actions` | 010 |
| `task_evidence` | 645 |
| `task_retry` | 010 |
| `test_agent` | 176 |
| `test_tasks` | 176 |
| `tests/test_automations.py` | 147 |
| `tests/test_home.py` | 435 |
| `tools/base.py` | 203 |
| `tools/browser.py` | 003 |
| `tools/list_tools.py` | 785 |
| `tools/mission_tools.py` | 025 |
| `tools/notes.py` | 380 |
| `tools/plan.py` | 001 |
| `tools/web.py` | 003 |
| `type_text` | P2.02 |
| `ui_click` | P2.02 |
| `update_progress` | 075 |
| `voice/loop.py` | 259 |
| `wake_device` | 416 |
| `watch_website` | 378 |
| `window_control` | P2.01 |
| `write_text_file` | P5.05 |

## Překryvy původního seznamu s katalogem

| Původní | Katalog | Schopnost |
|---|---|---|
| P1.01 | 597 | Multi-AI engine – Claude, GPT, Gemini a lokální modely |
| P1.02 | 004-009 | Automatický výběr modelu podle obtížnosti, ceny a dostupnosti |
| P1.03 | 036-045 | Dlouhodobá paměť |
| P1.04 | 036 | Krátkodobá paměť |
| P1.05 | 001, 198 | Autonomní plánování |
| P1.06 | 210 | Self-correction |
| P1.07 | 001 | Reasoning mode |
| P1.08 | 061-070 | Multi-agent systém |
| P1.09 | 039 | Učení z oprav a zpětné vazby |
| P1.10 | 270, 597 | Offline fallback |
| P2.01 | 026 | Spouštět, zavírat a přepínat aplikace |
| P2.02 | 522 | Klikat, psát, scrollovat, klávesnice i myš |
| P2.03 | 274 | Číst obrazovku a rozpoznávat prvky |
| P2.04 | 238 | Více monitorů |
| P2.06 | 016, 305 | Procesy, služby, aplikace při spuštění |
| P2.07 | 025 | Diagnostika RAM, CPU, GPU, SSD, HDD |
| P2.08 | 012, 018 | SMART, stav disků, systémové logy |
| P2.09 | 025 | Příčiny zamrzání a zpomalení |
| P2.11 | 511 | Organizovat soubory a stažené soubory |
| P2.12 | 147, 155 | Automatizovat opakované úkoly |
| P2.14 | 328 | Zálohy a obnova |
| P3.01 | 098 | Aktivace hlasem |
| P3.04 | 176 | Přerušit JARVISe během mluvení |
| P3.05 | 267 | Rozpoznávání mluvčích |
| P3.06 | 101 | Nastavitelný hlas a osobnost |
| P3.08 | 097 | Přepis mluveného slova |
| P3.09 | 269 | Překlady během konverzace |
| P3.10 | 555 | Čtení zpráv a dokumentů |
| P3.11 | 270 | Offline STT a TTS |
| P4.01 | 280 | Analýza screenshotů |
| P4.02 | 274 | Rozpoznávání textu, ikon, tlačítek, oken |
| P4.03 | 033 | Porozumění chybovým hláškám |
| P4.05 | 027 | Pomoc v reálném čase |
| P4.06 | 276-278 | Analýza obrázků, grafů a dokumentů |
| P4.07 | 188 | Volitelný přístup ke kameře |
| P4.08 | 413 | Rozpoznávání objektů kamerou telefonu |
| P4.09 | 059 | Vizuální porovnání před a po |
| P5.01 | 046 | Integrace s Claude Code CLI |
| P5.02 | 352 | Generování celých aplikací |
| P5.06 | 340 | Hledání a oprava bugů |
| P5.07 | 332 | Refactoring |
| P5.08 | 058 | Testy a kontrola výsledků |
| P5.10 | 049 | Pull requesty |
| P5.13 | 066 | Dokumentace projektů |
| P5.14 | 401 | Bezpečnostní kontrola kódu |
| P5.15 | 060 | Sestavení EXE a APK |
| P6.01 | 061 | Planner Agent – plánuje a řídí ostatní |
| P6.03 | 003 | Research Agent |
| P6.04 | 025 | System Agent |
| P6.07 | 176-185 | Security Agent |
| P6.08 | 147, 155 | Automation Agent |
| P7.01 | 249 | Spí, když dlouho nic neděláš |
| P7.02 | 244 | Tančí při hudbě (podle rytmu) |
| P7.03 | 241 | Přemýšlí při generování odpovědi |
| P7.04 | 076, 745 | Oslavuje dokončené úkoly |
| P7.05 | 071, 246 | Reaguje na kurzor a kliknutí |
| P7.06 | 744 | Zlobí se/je smutný při chybě |
| P7.07 | 748 | Reaguje na vyčerpání limitu AI |
| P7.08 | 241-253 | Desítky animací a výrazů |
| P7.09 | 252 | Vlastní zvukové reakce |
| P8.01 | 233 | Malý černý notch |
| P8.03 | 086 | Kompaktní režim a velký panel |
| P8.04 | 350 | Liquid Glass, blur, průhlednost |
| P8.09 | 763 | Aktuální AI úkoly |
| P9.02 | 139 | Telefon jako ovladač počítače |
| P9.04 | 412 | Push notifikace |
| P9.05 | 083 | Pokračování na jiném zařízení |
| P9.06 | 141 | Hlasové příkazy z telefonu |
| P9.07 | 142 | Fotografie a soubory se souhlasem |
| P9.10 | 407 | Bezpečný vzdálený přístup |
| P10.01 | 155 | Připomínky, budíky, časované úkoly |
| P10.02 | 508 | Pravidelné kontroly PC |
| P10.04 | 330 | Automatické zálohování |
| P10.06 | 542 | Upozornění na důležité zprávy |
| P10.07 | 510 | Ranní a večerní přehled |
| P10.08 | 147 | Spouštění vlastních workflow |
| P10.09 | 147 | Podmíněné akce |
| P10.10 | 155 | Plánovač autonomních agentů |
| P11.01 | 003 | Vyhledávání a ověřování zdrojů |
| P11.02 | 526 | Ovládání prohlížeče |
| P11.03 | 530 | Vyplňování formulářů |
| P11.05 | 541 | Správa e-mailů |
| P11.06 | 554 | Psaní a odesílání e-mailů |
| P11.07 | 565 | Google Calendar a schůzky |
| P11.09 | 547, 548 | Překlady a texty |
| P11.11 | 316 | Hledání v osobních souborech |
| P11.12 | 785 | Organizace úkolů a projektů |
| P12.03 | 244 | Animace postavičky podle hudby |
| P12.04 | 034 | Game Mode |
| P12.05 | 125, 297 | Monitoring FPS, CPU, GPU, teplot |
| P12.06 | 148 | Detekce spuštěné hry |
| P13.01 | 423 | Světla a zásuvky |
| P13.02 | 434 | Integrace s Home Assistantem |
| P13.03 | 429 | Televize a reproduktory |
| P13.06 | 432 | Automatizace domácnosti |
| P13.08 | 422 | Přehled senzorů a spotřeby |
| P14.01 | 180 | Oprávnění pro každého agenta |
| P14.02 | 182 | Potvrzování mazání a rizik |
| P14.03 | 232 | Historie operací |
| P14.04 | 176 | Zastavit běžícího agenta |
| P14.05 | 231 | Náhled změn |
| P14.06 | 328, 150 | Vrácení změn |
| P14.08 | 179 | Správa API klíčů |
| P14.10 | 794 | Mazání osobních dat |
| P14.11 | 183 | Ochrana před škodlivými instrukcemi |
| P14.12 | 686 | Omezené prostředí pro kód |
| P14.13 | 679 | Indikace mikrofonu/kamery/obrazovky |
| P15.01 | 146 | Teach Mode |
| P15.03 | 030 | Computer Memory |
| P15.04 | 496 | Predictive Assistant |
| P15.05 | 600 | Agent Marketplace |
| P15.06 | 757 | Universal Command Bar |
| P15.08 | 083 | Cross-device Handoff |
| P15.10 | 583 | Adaptive Resource Manager |
