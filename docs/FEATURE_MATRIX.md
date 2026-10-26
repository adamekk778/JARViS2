# FEATURE MATRIX – funkce → sdílené jádro

Které existující moduly/nástroje nesou které funkce. Jedna schopnost = jedna implementace; překrývající se položky katalogu i původního seznamu ukazují na stejný modul (žádné duplikáty: jeden plánovač `scheduler.py`, jedna paměť `memory.py`, jeden systém oprávnění `permissions.py`, jedny mise `tasks.py`, jedna postavička `character/blob.ts`). Generováno `docs/audit/build_audit.py`.

| Modul / nástroj | Funkce (ID) |
|---|---|
| `Claude Code` | 046, 049, 331, 345, 735, P5.01, P5.02, P5.03, P5.04, P5.05, P5.06, P5.07, P5.10, P5.13, P5.14, P6.02, P10.05 |
| `computer_use` | 116, 117, 118, 531, P2.02, P4.04, P11.03 |
| `Home Assistant` | 165, 423, 434, P13.02, P13.05 |
| `STOP` | 176, 405, P3.04, P6.07, P14.04 |
| `make_website` | 352, 353, 354, P5.02, P6.05 |
| `run_shell` | 702, P2.05, P2.13, P5.11, P5.12 |
| `UI Automation` | 028, 274, P2.03, P4.02 |
| `mood.py` | 076, 241, 737, P7.01 |
| `powers.py` | 026, 027, 077, 236 |
| `run_python` | 766, 768, P5.12, P11.10 |
| `run_tests` | 058, 062, 334, P5.08 |
| `tasks.py` | 002, 209, 217, 223 |
| `ui_read` | 028, 033, P2.03, P4.03 |
| `ask_models` | 006, 007, 204 |
| `check_answer` | 111, 115, 459 |
| `compare_options` | 005, 007, 197 |
| `d_model` | 467, 468, 775 |
| `db_query_plan` | 602, 603, 612 |
| `goal_plan` | 001, 198, 452 |
| `home.py` | 165, 435, P13.01 |
| `memory.py` | 039, 041, P1.03 |
| `notetaker.py` | 128, 166, 167 |
| `pc_health_report` | 025, 224, P6.04 |
| `perf_check` | 063, 301, 718 |
| `test_wave` | 041, 152, 177 |
| `tests/test_omega.py` | 002, 025, 076 |
| `tools/base.py` | 183, 203, 682 |
| `tools/dev.py` | 046, 050, 058 |
| `app_open` | 034, P12.06 |
| `automations.py` | 034, 147 |
| `browser_type` | 530, P11.03 |
| `character/looks.ts` | 250, 251 |
| `circuit_calc` | 473, 474 |
| `claude_bridge.py` | 046, P5.01 |
| `close_app` | P2.01, P2.06 |
| `dashboard/tasks.ts` | 002, 010 |
| `db_growth` | 610, 613 |
| `dependency_risks` | 333, 625 |
| `desktop/host.py` | 226, P8.01 |
| `email_send` | 562, P11.06 |
| `exam_plan` | 110, 452 |
| `find_file` | P2.11, P11.11 |
| `find_in_files` | 316, 322 |
| `home_control` | 424, P13.01 |
| `injection.py` | 183, P14.11 |
| `mind_map` | 112, 113 |
| `network.py` | 165, 406 |
| `network_check` | 021, 718 |
| `open_app` | P2.01, P12.09 |
| `oral_exam` | 115, 459 |
| `pcreport.py` | 025, P2.08 |
| `perf_benchmark` | 018, 314 |
| `permissions.py` | 177, P14.01 |
| `project_resume` | 044, 509 |
| `quiz_from` | 107, 112 |
| `run_steps` | 212, 213 |
| `screen_time` | 313, 792 |
| `send_to_phone` | 138, 408 |
| `stark.py` | 034, 508 |
| `storage_report` | 327, P2.11 |
| `tools/files.py` | 029, 511 |
| `tools/uia.py` | 028, 274 |
| `ui_inspect` | 028, P2.03 |
| `update_plan` | 202, P1.05 |
| `usage.py` | 178, 678 |
| `video_scenes` | 361, 364 |
| `wake_word` | 098, P3.01 |
| `web_read` | P6.03, P11.01 |
| `web_search` | P6.03, P11.01 |
| `website_audit` | 388, 389 |
| `what_next` | 496, 507 |
| `_an_drivers` | 011 |
| `_an_usb` | 017 |
| `_needs_second` | 182 |
| `ab_test` | 780 |
| `agent_team` | 218 |
| `ai_usage` | 154 |
| `analyze_feedback` | 444 |
| `api_ask` | 589 |
| `api_breaking_changes` | 627 |
| `api_call` | 591 |
| `api_contract_check` | 336 |
| `api_import` | 588 |
| `api_rate_limits` | 594 |
| `api_set_key` | 592 |
| `app_allowlist` | 682 |
| `archive_contents` | 323 |
| `ask_documents` | 581 |
| `audio_devices` | 105 |
| `audio_highlights` | 364 |
| `background_jobs` | 628 |
| `backup_encrypted` | 685 |
| `backup_folder` | 330 |
| `backup_plan` | 330 |
| `best_time_outside` | 783 |
| `break_minutes` | 077 |
| `broken_links` | 383 |
| `calendar_.py` | 171 |
| `calendar_check` | 558 |
| `character/blob.ts` | 071 |
| `check_app_links` | 629 |
| `check_assumptions` | 199 |
| `check_download` | 398 |
| `check_formula_units` | 772 |
| `check_hardware` | 298 |
| `check_link` | 397 |
| `check_math_steps` | 106 |
| `check_subtitles` | 369 |
| `check_translation` | 068 |
| `claude_code` | 046 |
| `clean_metadata` | 326 |
| `clean_speech` | 366 |
| `clipboard_set` | 138 |
| `code_owners` | 338 |
| `color_theme` | 356 |
| `command_history` | 520 |
| `communication_digest` | 555 |
| `compare_embedding_models` | 580 |
| `compare_files` | 029 |
| `compare_groups` | 779 |
| `confirm_info` | 219 |
| `contact_card` | 553 |
| `contrast_check` | 348 |
| `convert_file` | 324 |
| `copy_file` | P2.11 |
| `corrupt_test_data` | 643 |
| `corruption_test` | 643 |
| `create_restore_point` | 020 |
| `create_zip` | 323 |
| `customer_segments` | 437 |
| `dashboard/palette.ts` | 757 |
| `dashboard/security.ts` | 690 |
| `data_rescue_plan` | 300 |
| `dataset_check` | 767 |
| `dataset_clean` | 767 |
| `day_summary` | 510 |
| `db_anonymize_copy` | 611 |
| `db_compare_schema` | 608 |
| `db_incident` | 615 |
| `db_integrity` | 605 |
| `db_restore_rehearsal` | 607 |
| `db_schema` | 601 |
| `db_sensitive_data` | 609 |
| `db_slow_queries` | 604 |
| `db_snapshot` | 610 |
| `db_verify_backup` | 606 |
| `deadline_risks` | 502 |
| `deep_research` | 003 |
| `delegate_to_agent` | 061 |
| `delete_file` | P14.02 |
| `dependency_update_plan` | 341 |
| `dependency_vulnerabilities` | 333 |
| `design_system` | 346 |
| `device_test` | 638 |
| `dictation.py` | 097 |
| `duck_music` | 363 |
| `email_search` | 551 |
| `environment_compare` | 342 |
| `environment_snapshot` | 342 |
| `estimate_effort` | 503 |
| `experiment_log` | 479 |
| `experiment_result` | 479 |
| `explain_build_failure` | 340 |
| `explain_crash_code` | 014 |
| `export_all` | 793 |
| `export_audit` | 687 |
| `extract_archive` | 323 |
| `fact_check` | 377 |
| `fact_delete` | 039 |
| `fact_update` | 039 |
| `feature_flags` | 344 |
| `file_metadata` | 326 |
| `file_versions` | 328 |
| `find_duplicates` | 317 |
| `find_flaky_tests` | 636 |
| `find_similar_image` | 283 |
| `find_similar_photos` | 318 |
| `flaky_tests` | 636 |
| `flashcards_from` | 112 |
| `focus_report` | 787 |
| `folder_check` | 329 |
| `folder_fingerprint` | 329 |
| `follow_up_check` | 546 |
| `foreground_info` | 026 |
| `foreign_key_check` | 605 |
| `forgotten_work` | 499 |
| `free_time` | 568 |
| `frequency_analysis` | 778 |
| `fuzz_inputs` | 633 |
| `generate_api_client` | 620 |
| `generate_image` | 132 |
| `git_log` | 050 |
| `git_status` | P5.09 |
| `hardware_changes` | 298 |
| `home_scene` | 423 |
| `hone.java` | 420 |
| `inbox_overview` | 541 |
| `index_documents` | 581 |
| `ingredient_substitute` | 786 |
| `integrity_check` | 605 |
| `keep_alive` | 575 |
| `keyboard_test` | 644 |
| `learning_weak_spots` | 108 |
| `life_event_plan` | 781 |
| `link_alive` | 410 |
| `list_folder` | P2.11 |
| `load_test` | 642 |
| `local_model_benchmark` | 571 |
| `local_models_fit` | 578 |
| `local_unload` | 576 |
| `looks_secret` | 681 |
| `mail.py` | P11.05 |
| `make_sbom` | 624 |
| `map_data` | 595 |
| `mcp_client` | 048 |
| `media_control` | P12.01 |
| `media_player` | P13.03 |
| `media_quality` | 375 |
| `meeting_minutes` | 559 |
| `meeting_prep` | 556 |
| `memory_export` | 045 |
| `memory_import` | 045 |
| `memory_leak_check` | 635 |
| `memory_overview` | 040 |
| `memory_timeline` | 036 |
| `merge_records` | 598 |
| `message_actions` | 544 |
| `migration_preview` | 337 |
| `missing_info` | 207 |
| `mission_save_file` | 215 |
| `mobile/native.ts` | 143 |
| `mock_server_start` | 621 |
| `module_map` | 332 |
| `monorepo_map` | 619 |
| `move_files` | P2.11 |
| `mutation_test` | 335 |
| `my_routines` | 497 |
| `network_devices` | 426 |
| `network_fault_start` | 634 |
| `offline_test` | 641 |
| `over_budget` | 221 |
| `packing_list` | 782 |
| `pairing_get` | 184 |
| `pc_diagnose` | 011 |
| `perf_history` | 312 |
| `phone.py` | 145 |
| `phone_battery` | 417 |
| `power_cost` | 474 |
| `press_keys` | P2.02 |
| `price_history` | 379 |
| `price_quote` | 441 |
| `pricing_scenarios` | 442 |
| `privacy.py` | P14.10 |
| `project_profitability` | 449 |
| `provider_test` | 587 |
| `pseudo_localize` | 639 |
| `quantization_advice` | 572 |
| `read_text_file` | P5.05 |
| `read_website` | P11.04 |
| `reading_level` | 791 |
| `recent_files` | 322 |
| `redact.py` | 179 |
| `release_notes` | 343 |
| `remove_duplicates` | 317 |
| `remove_silence` | 362 |
| `rename_files` | 325 |
| `reopen_crashed` | 519 |
| `reply_context` | 543 |
| `requirements_from_idea` | 616 |
| `reset_all` | 794 |
| `restore_file_version` | 328 |
| `restyle_subtitles` | 369 |
| `revenue_forecast` | 443 |
| `rollback_plan` | 623 |
| `sales_funnel` | 439 |
| `save_file_version` | 328 |
| `save_web_evidence` | 381 |
| `scan_secrets` | 401 |
| `schedule_memory_test` | 296 |
| `scheduler.py` | 155 |
| `score_leads` | 438 |
| `search_documents` | 581 |
| `search_memory` | 038 |
| `send_file` | P9.03 |
| `server/pairing.py` | 144 |
| `set_feature_flag` | 344 |
| `set_private` | 041 |
| `setup_check` | 795 |
| `shared/taskcard.ts` | 087 |
| `shopping_by_aisle` | 785 |
| `skillforge.py` | 150 |
| `smart_data` | 697 |
| `smart_rename` | 320 |
| `sort_documents` | 319 |
| `source_reliability` | 376 |
| `speak_mode` | P3.07 |
| `speed_test` | 717 |
| `sql_query` | 064 |
| `stop_all` | 176 |
| `study_stats` | 461 |
| `system_integrity_check` | 286 |
| `system_snapshot` | 190 |
| `task_steps` | 216 |
| `test_agent` | 176 |
| `test_coverage` | 334 |
| `test_model_accuracy` | 582 |
| `test_regressions` | 339 |
| `test_tasks` | 176 |
| `tests/test_agent.py` | 182 |
| `tests/test_automations.py` | 147 |
| `tests/test_home.py` | 435 |
| `to_list` | 570 |
| `token_expiry` | 592 |
| `tolerance_stackup` | 773 |
| `tools/mission_tools.py` | 025 |
| `tools/notes.py` | 380 |
| `tools/shell.py` | 702 |
| `top_processes` | P2.06 |
| `translation_overflow` | 639 |
| `typ_datum_firma` | 320 |
| `type_text` | P2.02 |
| `typography_check` | 359 |
| `ui_click` | P2.02 |
| `ui_consistency` | 351 |
| `undo_rename` | 325 |
| `unit_calc` | 772 |
| `update_progress` | 075 |
| `user_flow_test` | 631 |
| `verify_copy` | 700 |
| `visual_diff` | 360 |
| `voice/loop.py` | 259 |
| `wake_device` | 416 |
| `warm_up_model` | 575 |
| `watch_website` | 378 |
| `window_control` | P2.01 |
| `window_to_monitor` | 238 |
| `workspace_compare` | 518 |
| `workspace_restore` | 229 |
| `workspace_save` | 229 |
| `write_text_file` | P5.05 |
| `y_check` | 067 |

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
| P14.10 | 684, 794 | Mazání osobních dat |
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
