# FEATURE AUDIT – JARVIS OMEGA ∞

Stav každé schopnosti ze zadání (docs/OMEGA_SPEC.md): katalog 001–795 a původní seznam 110+ schopností.
Generováno skriptem `docs/audit/build_audit.py` z `docs/audit/status.txt` a `docs/audit/original.txt` – **neupravuj ručně**, uprav zdrojové soubory a spusť skript.

Stavy: ✅ HOTOVO · 🟡 ČÁSTEČNĚ · 🔴 ROZBITÉ · 🔌 VYŽADUJE_INTEGRACI · ⛔ BLOKOVÁNO_PLATFORMOU · 🗓️ PLÁNOVÁNO · ⬜ CHYBÍ. Co není výslovně ověřeno, je vedeno jako CHYBÍ.

## Souhrn

| Stav | Katalog 001–795 | Původní seznam |
|---|---:|---:|
| ✅ HOTOVO | 221 | 74 |
| 🟡 ČÁSTEČNĚ | 154 | 58 |
| 🔴 ROZBITÉ | 0 | 0 |
| 🔌 VYŽADUJE_INTEGRACI | 12 | 10 |
| ⛔ BLOKOVÁNO_PLATFORMOU | 0 | 0 |
| 🗓️ PLÁNOVÁNO | 21 | 4 |
| ⬜ CHYBÍ | 387 | 17 |
| **Celkem** | **795** | **163** |

Pozn.: položky se překrývají (viz FEATURE_MATRIX.md), součty nejsou počtem unikátních modulů.

## 01. Super Intelligence

✅ 4 · 🟡 2 · 🔌 1 · 🗓️ 3

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 001 | Goal Mode — z cíle sestaví reálný plán. | ✅ HOTOVO | goal_plan: z cíle fáze, kroky (kdo je udělá), akceptační kritéria a rizika → sledovaná mise v Úkolech |
| 002 | Mission Control — řídí složité mise. | 🟡 ČÁSTEČNĚ | Mission Control = stránka Úkoly: plán, kroky, audit akcí, kritéria, artefakty, důkazy, pauza/zrušení (tasks.py, dashboard/tasks.ts, tests/test_omega.py); chybí DAG |
| 003 | Deep Research — rozsáhlý výzkum s citacemi. | ✅ HOTOVO | deep_research: víc dotazů, přečtené zdroje, report s citacemi [n], mechanická kontrola citací, uložený jako artefakt |
| 004 | Autonomous Problem Solver — testování více řešení. | 🗓️ PLÁNOVÁNO | Omega Brain – milník M3 v ROADMAP.md |
| 005 | Decision Simulator — simuluje důsledky rozhodnutí. | 🟡 ČÁSTEČNĚ | compare_options: u každé varianty pravděpodobné důsledky a rizika (odhad AI, ne simulace) |
| 006 | AI Debate — porovnání argumentů modelů. | 🔌 VYŽADUJE_INTEGRACI | ask_models: stejná otázka víc AI poskytovatelům a porovnání – potřebuje aspoň dva nastavené poskytovatele |
| 007 | Confidence Engine — vyjadřuje míru nejistoty. | ✅ HOTOVO | jistota u doporučení (compare_options) a podle shody modelů (ask_models); research hlásí nesedící citace |
| 008 | Error Prediction — předvídání pravděpodobných chyb. | 🗓️ PLÁNOVÁNO | Omega Brain – milník M3 v ROADMAP.md |
| 009 | Dynamic Task Priorities — dynamické priority. | 🗓️ PLÁNOVÁNO | Omega Brain – milník M3 v ROADMAP.md |
| 010 | Mission Replay — auditovatelná historie kroků. | ✅ HOTOVO | Přehrát průběh mise (dashboard/tasks.ts replay) + audit akcí |

## 02. Windows Superpowers

✅ 9 · 🟡 5 · ⬜ 1

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 011 | Automatické hledání vadných nebo chybějících ovladačů. | ✅ HOTOVO | pc_diagnose drivers: zařízení s chybovým kódem (česky co znamená), nepodepsané a staré ovladače (rescue._an_drivers) |
| 012 | Vyhodnocení Windows Event Viewer. | ✅ HOTOVO | logy System/Application vyhodnocené po oblastech: pády, aplikace, služby, disky (rescue.PROBES) |
| 013 | Sledování Windows Update. | 🟡 ČÁSTEČNĚ | stáří poslední aktualizace a virových definic (oblast security); čekající aktualizace se nesledují |
| 014 | Analýza příčin BSOD. | ✅ HOTOVO | kódy modrých obrazovek z událostí 1001 → název + česká příčina + rada, opakování, nečekaná vypnutí (rescue.BUGCHECKS, explain_crash_code) |
| 015 | Analýza minidump po pádu. | 🟡 ČÁSTEČNĚ | seznam výpisů pádů (Minidump) a kód z logu; rozbor obsahu výpisu potřebuje ladicí nástroj Windows (cdb) – zatím ne |
| 016 | Diagnostika pomalého startu Windows. | ✅ HOTOVO | časy startu a co ho zdržuje (Diagnostics-Performance 100–109), počet programů po spuštění, rychlé spuštění |
| 017 | Diagnostika nefunkčních USB. | ✅ HOTOVO | USB zařízení s chybou, opakované odpojování (Kernel-PnP), offline/RAW disky, USB rámečky (rescue._an_usb) |
| 018 | Měření diskového výkonu a historie chyb. | ✅ HOTOVO | test zápisu/čtení disku s historií měření (perf_benchmark) + chyby disku z logu za 30 dní |
| 019 | Rozpoznávání konfliktů zařízení a ovladačů. | 🟡 ČÁSTEČNĚ | kódy ConfigManager vč. konfliktu prostředků (12); mapa konfliktů chybí |
| 020 | Bezpečné body obnovy před zásahy. | ✅ HOTOVO | create_restore_point – se schválením, srozumitelné chyby (správce, 24 h, vypnutá ochrana) + přehled bodů obnovy |
| 021 | Diagnostika sítí, DNS a Wi-Fi. | ✅ HOTOVO | network_check: Wi-Fi signál, DNS, odezva, ztráta, trasa, certifikát, dostupnost webu, veřejné DNS |
| 022 | Sledování thermal throttlingu. | 🟡 ČÁSTEČNĚ | škrcení poznám podle frekvence CPU pod zátěží (perf.bottlenecks); teplotu CPU Windows bez ovladače výrobce nehlásí |
| 023 | Graf závislostí služeb a procesů. | ⬜ CHYBÍ | — |
| 024 | Kontrola podezřelých aplikací a oprávnění. | 🟡 ČÁSTEČNĚ | podezřelý autostart (nepodepsané z AppData/Temp), skryté naplánované úlohy, programy otevřené do sítě; oprávnění aplikací ne |
| 025 | Technická zpráva o stavu PC. | ✅ HOTOVO | pc_health_report: read-only diagnostika, HTML report, ověření 5 kritérií (pcreport.py, tools/mission_tools.py, tests/test_omega.py, CI --selftest-report) |

## 03. Context Awareness

✅ 2 · 🟡 4 · ⬜ 4

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 026 | Detekce aktivní aplikace. | ✅ HOTOVO | foreground_info + Activity sampler (powers.py), automatizace „když otevřu…“ |
| 027 | Práce s označeným textem. | ✅ HOTOVO | označený text Ctrl+Alt+E: opravit/přeložit/zkrátit/vysvětlit (powers.py; CI test v Notepadu) |
| 028 | Vysvětlení prvku pod kurzorem. | 🟡 ČÁSTEČNĚ | ui_inspect / ui_read přes UI Automation (tools/uia.py) |
| 029 | Porovnávání otevřených dokumentů. | 🟡 ČÁSTEČNĚ | compare_files (tools/files.py) |
| 030 | Paměť pracovního rozložení oken. | ⬜ CHYBÍ | — |
| 031 | Obnova pracovního prostředí po restartu. | ⬜ CHYBÍ | — |
| 032 | Nabídnutí pomoci při opakovaných chybách. | ⬜ CHYBÍ | — |
| 033 | Kontextová diagnostika chybových dialogů. | 🟡 ČÁSTEČNĚ | screenshot + vision model, ui_read chybových dialogů |
| 034 | Režim práce/hry/učení dle aktivních aplikací. | 🟡 ČÁSTEČNĚ | protokoly Pracovní/Herní režim + automatizace app_open (stark.py, automations.py) |
| 035 | Interaktivní popisky funkcí aplikace. | ⬜ CHYBÍ | — |

## 04. Ultra Memory

✅ 9 · 🔌 1

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 036 | Memory Timeline — časová osa práce. | ✅ HOTOVO | memory_timeline + stránka: konverzace, mise, diktování, hovory, co si zapamatoval, čas v aplikacích za zvolený den |
| 037 | Project Memories — oddělená paměť projektů. | ✅ HOTOVO | projekty s vlastními fakty; do odpovědí jde jen paměť aktuálního projektu + obecná (izolace), poznámka a složka projektu |
| 038 | Search Everything — sémantické hledání v povolených datech. | 🔌 VYŽADUJE_INTEGRACI | search_memory: fulltext přes konverzace, fakta, diktování, hovory a mise (bez diakritiky, české tvary slov) funguje vždy; podle významu s místním modelem na embeddingy v Ollamě (nic se samo nestahuje) |
| 039 | Memory Correction — opravy vzpomínek. | ✅ HOTOVO | úprava a mazání faktů v paměti (memory.py, fact_update/fact_delete) |
| 040 | Memory Categories — tematické třídění. | ✅ HOTOVO | fakta tříděná do kategorií (Rodina, Zdraví, Práce, Domov, Preference…), přehled memory_overview, úprava kategorie |
| 041 | Memory Privacy — režim bez ukládání. | ✅ HOTOVO | Soukromý režim: konverzace jen v RAM, fakta se neukládají (memory.py set_private, tests/test_wave1.py) |
| 042 | Source Memory — původ uložených poznatků. | ✅ HOTOVO | u každého faktu původ: ve které konverzaci a kdy to uživatel řekl / zapsal ručně |
| 043 | Memory Conflicts — detekce rozporů. | ✅ HOTOVO | rozpor s dřívějším faktem (např. dvě adresy) se zapíše a JARVIS se zeptá; vyřešení „platí nové / staré / obojí“ |
| 044 | Project Resume — navázání na projekt. | ✅ HOTOVO | project_resume: poslední konverzace a odpověď, rozdělané mise, nedávné soubory, fakta, doporučený další krok |
| 045 | Memory Export — export paměti. | ✅ HOTOVO | export/import paměti (memory_export, memory_import) |

## 05. Ultimate Developer

🟡 3 · 🔌 3 · ⬜ 9

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 046 | Mapování architektury projektu. | 🔌 VYŽADUJE_INTEGRACI | přes Claude Code CLI (tools/dev.py claude_code, claude_bridge.py) |
| 047 | Graf závislostí mezi soubory. | ⬜ CHYBÍ | — |
| 048 | Vytváření GitHub issues. | 🔌 VYŽADUJE_INTEGRACI | přes MCP server GitHubu (integrations/mcp_client) |
| 049 | AI review pull requestů. | 🔌 VYŽADUJE_INTEGRACI | přes Claude Code |
| 050 | Automatický changelog. | 🟡 ČÁSTEČNĚ | git_log + AI shrnutí (tools/dev.py) |
| 051 | Generování DB migrací. | ⬜ CHYBÍ | — |
| 052 | Detekce chybných DB dotazů. | ⬜ CHYBÍ | — |
| 053 | Výkonnostní analýza backendu. | ⬜ CHYBÍ | — |
| 054 | Kontrola přístupnosti webů. | ⬜ CHYBÍ | — |
| 055 | SEO audit a optimalizace webů. | ⬜ CHYBÍ | — |
| 056 | Příprava testovacího deploymentu. | ⬜ CHYBÍ | — |
| 057 | Bezpečné zátěžové testování. | ⬜ CHYBÍ | — |
| 058 | Ověřování buildu po změnách. | 🟡 ČÁSTEČNĚ | run_tests (tools/dev.py) |
| 059 | Vizuální porovnávání UI. | ⬜ CHYBÍ | — |
| 060 | Příprava release balíčků. | 🟡 ČÁSTEČNĚ | vlastní CI JARVISe staví EXE/APK; obecně pro cizí projekty chybí |

## 06. Agent Army

✅ 7 · 🟡 1 · 🗓️ 2

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 061 | Architect Agent — software architektura. | ✅ HOTOVO | specialista Architekt (projde projekt, git, web) přes delegate_to_agent |
| 062 | QA Agent — testování aplikací. | ✅ HOTOVO | specialista Tester: run_tests, prohlížeč, kontrola přístupnosti, zápis testů se schválením |
| 063 | Performance Agent — optimalizace výkonu. | ✅ HOTOVO | specialista Výkon: perf_check, benchmark, historie, procesy, diagnostika |
| 064 | Database Agent — databázový design. | ✅ HOTOVO | specialista Databáze + sql_query (SQLite jen pro čtení – mode=ro, jen SELECT/PRAGMA/EXPLAIN) |
| 065 | DevOps Agent — infrastruktura. | 🟡 ČÁSTEČNĚ | specialista DevOps: git, CI soubory, testy, dostupnost a certifikáty; nasazení do cloudu chybí |
| 066 | Documentation Agent — dokumentace. | ✅ HOTOVO | specialista Dokumentace: čte kód, píše dokumentaci (zápis se schválením) |
| 067 | Accessibility Agent — přístupnost. | ✅ HOTOVO | specialista Přístupnost + a11y_check (WCAG: alt, popisky polí, kontrast, nadpisy, odkazy, jazyk, klávesnice) |
| 068 | Localization Agent — překlady aplikací. | ✅ HOTOVO | specialista Překlady + check_translation (chybějící klíče, rozbité zástupné znaky, nepřeložené texty) |
| 069 | 3D Agent — modely a scény. | 🗓️ PLÁNOVÁNO | Agent Swarm – dnes jeden agent + Claude Code; registr agentů je milník M3 |
| 070 | Hardware Agent — elektronika. | 🗓️ PLÁNOVÁNO | Agent Swarm – dnes jeden agent + Claude Code; registr agentů je milník M3 |

## 07. Mochi 2.0

✅ 3 · 🟡 2 · ⬜ 10

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 071 | Oči sledující kurzor. | ✅ HOTOVO | oči sledují kurzor (character/blob.ts lookAt) |
| 072 | Protažení při probuzení PC. | ⬜ CHYBÍ | — |
| 073 | Reakce na změnu hlasitosti. | ⬜ CHYBÍ | — |
| 074 | Animace při kopírování souborů. | ⬜ CHYBÍ | — |
| 075 | Pravdivá vizualizace stahování. | 🟡 ČÁSTEČNĚ | pravdivý průběh stahování aktualizace (mood update_progress) |
| 076 | Oslava dokončeného úkolu. | ✅ HOTOVO | radost po ověřené misi / úspěchu (mood.py joy/success, tests/test_omega.py) |
| 077 | Nenápadná nabídka přestávky. | ✅ HOTOVO | připomínka pauzy po N minutách u PC (powers.py break_minutes) |
| 078 | Schovávání za okraj ostrova. | ⬜ CHYBÍ | — |
| 079 | Interaktivní rozdělení Mochiho. | ⬜ CHYBÍ | — |
| 080 | Drobné minihry s Mochem. | ⬜ CHYBÍ | — |
| 081 | Reakce na připojení zařízení. | ⬜ CHYBÍ | — |
| 082 | Sezónní drobné animace. | ⬜ CHYBÍ | — |
| 083 | Animovaný cross-device handoff. | ⬜ CHYBÍ | — |
| 084 | Kontextové zjevení vedle okna. | ⬜ CHYBÍ | — |
| 085 | Nastavitelná historie reakcí. | 🟡 ČÁSTEČNĚ | historie úkolů a mise; samostatná historie reakcí chybí |

## 08. Dynamic Island Pro

✅ 2 · 🟡 3 · ⬜ 5

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 086 | Picture-in-picture panel asistenta. | 🟡 ČÁSTEČNĚ | rozbalovací panel notche (web/src/notch) |
| 087 | Živé minipanely agentů. | 🟡 ČÁSTEČNĚ | karta aktuálního úkolu v notchi (shared/taskcard.ts) |
| 088 | Drag & drop do notche. | ✅ HOTOVO | přetažení souborů do notche – police (shelf) |
| 089 | Rychlé akce podle aplikace. | ⬜ CHYBÍ | — |
| 090 | Konfigurovatelné klávesové zkratky. | ✅ HOTOVO | konfigurovatelné zkratky (Nastavení → Zkratky) |
| 091 | Rozšířený panel s pracovními plochami. | ⬜ CHYBÍ | — |
| 092 | Zamknutí panelu proti náhodnému otevření. | ⬜ CHYBÍ | — |
| 093 | Připnuté úkoly. | ⬜ CHYBÍ | — |
| 094 | Kontextové návrhy v minipanelu. | ⬜ CHYBÍ | — |
| 095 | Vlastní interaktivní widgety. | 🟡 ČÁSTEČNĚ | volitelné dlaždice notche |

## 09. Voice Intelligence

✅ 5 · 🟡 3 · ⬜ 2

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 096 | Hlasové příkazy během her. | 🟡 ČÁSTEČNĚ | push-to-talk zkratka funguje i ve hře |
| 097 | Diktování do aplikací. | ✅ HOTOVO | diktování kamkoli (dictation.py) |
| 098 | Vlastní aktivační fráze. | ✅ HOTOVO | vlastní aktivační fráze (voice.wake_word) |
| 099 | Ztišení hudby při mluvení. | ⬜ CHYBÍ | — |
| 100 | Rozpoznání více příkazů ve větě. | 🟡 ČÁSTEČNĚ | více příkazů ve větě řeší jazykový model |
| 101 | Nastavitelná délka a rychlost odpovědi. | ✅ HOTOVO | rychlost a hlasitost hlasu, osobnost |
| 102 | Prostorové audio efekty. | ⬜ CHYBÍ | — |
| 103 | Hlasové potvrzení rizikových akcí. | 🟡 ČÁSTEČNĚ | potvrzení rizikových akcí v UI a otiskem na telefonu; hlasové potvrzení chybí |
| 104 | Vlastní hlasová makra. | ✅ HOTOVO | hlasová makra = protokoly („spusť protokol …“) |
| 105 | Výběr vhodného mikrofonu. | ✅ HOTOVO | výběr mikrofonu (audio_devices) |

## 10. JARVIS Teacher

✅ 8 · 🟡 1 · ⬜ 1

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 106 | Výuka matematických postupů. | 🟡 ČÁSTEČNĚ | check_math_steps najde chybný krok výpočtu (skutečný výpočet); vysvětlení postupu dělá AI v chatu |
| 107 | Procvičovací testy. | ✅ HOTOVO | quiz_from: procvičovací test z dokumentu (výběr i otevřené otázky) |
| 108 | Detekce slabých míst při učení. | ✅ HOTOVO | learning_weak_spots: nejslabší témata, druhy chyb, zapomínané kartičky |
| 109 | Flashcards. | ✅ HOTOVO | kartičky: přidání, z dokumentu, opakování na stránce Učení i hlasem |
| 110 | Plán opakování učiva. | ✅ HOTOVO | časované opakování SM-2 + exam_plan s opakováním témat |
| 111 | Vyhodnocení písemných odpovědí. | ✅ HOTOVO | check_answer: hodnocení 0–100, co chybí, druh chyby (zapisuje se) |
| 112 | Učebnice na výukové materiály. | ✅ HOTOVO | flashcards_from / quiz_from / mind_map z vlastních materiálů (PDF, Word, poznámky) |
| 113 | Myšlenkové mapy. | ✅ HOTOVO | mind_map: větve, pojmy, souvislosti, uloženo jako Markdown s diagramem |
| 114 | Nácvik výslovnosti. | ⬜ CHYBÍ | — |
| 115 | Simulace ústního zkoušení. | ✅ HOTOVO | oral_exam: otázky k tématu podle úrovně a slabých míst, odpovědi hodnotí check_answer |

## 11. Gaming & Development

🔌 3 · ⬜ 7

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 116 | Integrace Roblox Studio. | 🔌 VYŽADUJE_INTEGRACI | Roblox Studio / Blender / Unity – jen přes computer_use, bez nativní integrace |
| 117 | Pomoc s Blenderem. | 🔌 VYŽADUJE_INTEGRACI | Roblox Studio / Blender / Unity – jen přes computer_use, bez nativní integrace |
| 118 | Inspekce Unity projektů. | 🔌 VYŽADUJE_INTEGRACI | Roblox Studio / Blender / Unity – jen přes computer_use, bez nativní integrace |
| 119 | Testovací herní scény. | ⬜ CHYBÍ | — |
| 120 | Koncepční návrhy prostředí. | ⬜ CHYBÍ | — |
| 121 | Analýza herních logů. | ⬜ CHYBÍ | — |
| 122 | Organizace herních assetů. | ⬜ CHYBÍ | — |
| 123 | Automatizované testování vlastních her. | ⬜ CHYBÍ | — |
| 124 | Správa modů a kompatibility. | ⬜ CHYBÍ | — |
| 125 | Analýza FPS podle nastavení. | ⬜ CHYBÍ | — |

## 12. Creative Studio

🟡 3 · ⬜ 7

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 126 | Video storyboard. | ⬜ CHYBÍ | — |
| 127 | Návrhy animovaných scén. | ⬜ CHYBÍ | — |
| 128 | Automatické titulky. | 🟡 ČÁSTEČNĚ | přepis řeči z nahrávek (notetaker.py) |
| 129 | Synchronizace titulků. | ⬜ CHYBÍ | — |
| 130 | Odšumění zvuku. | ⬜ CHYBÍ | — |
| 131 | Výběr krátkých klipů. | ⬜ CHYBÍ | — |
| 132 | Náhledové obrázky. | 🟡 ČÁSTEČNĚ | generate_image |
| 133 | Barevné palety. | 🟡 ČÁSTEČNĚ | palety přes AI chat |
| 134 | Animace z grafických prvků. | ⬜ CHYBÍ | — |
| 135 | Exporty pro sociální sítě. | ⬜ CHYBÍ | — |

## 13. Mobile Super Assistant

✅ 4 · 🟡 5 · ⬜ 1

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 136 | Widgety mobilní domovské obrazovky. | ⬜ CHYBÍ | — |
| 137 | Rychlé akce z notifikací. | 🟡 ČÁSTEČNĚ | akce v notifikacích hovoru JARVISe (Přijmout/Odmítnout/Odpovědět) |
| 138 | Schránka mezi zařízeními. | 🟡 ČÁSTEČNĚ | send_to_phone, clipboard_set z telefonu |
| 139 | Spouštění PC úkolů na dálku. | ✅ HOTOVO | Ovládání v mobilu: protokoly, média, aplikace, napájení (web/src/mobile) |
| 140 | Zobrazení stavu počítače. | 🟡 ČÁSTEČNĚ | stav úkolu v mobilu; stav PC jen přes chat |
| 141 | Hlasové poznámky z mobilu. | ✅ HOTOVO | hlasové zprávy z mobilu (push-to-talk upload) |
| 142 | Fotografie přiřazené k projektu. | 🟡 ČÁSTEČNĚ | přílohy fotek do chatu |
| 143 | Biometrické potvrzení citlivých akcí. | ✅ HOTOVO | otisk prstu pro citlivá schválení (mobile/native.ts verify) |
| 144 | QR párování. | ✅ HOTOVO | QR párování (server/pairing.py) |
| 145 | Offline fronta a synchronizace. | 🟡 ČÁSTEČNĚ | fronta příkazů PC→telefon (phone.py) |

## 14. Automation of the Future

✅ 5 · 🟡 3 · ⬜ 2

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 146 | Workflow Recorder — záznam postupu. | ⬜ CHYBÍ | — |
| 147 | Conditional Builder — tvorba podmínek. | ✅ HOTOVO | automatizace „Když … tak …“ (automations.py, tests/test_automations.py) |
| 148 | Trigger Explorer — spouštěče událostí. | ✅ HOTOVO | 11 spouštěčů: čas, start PC, aplikace, e-mail, zpráva/hovor na mobilu, baterie, nabíječka, odchod/návrat |
| 149 | Workflow Simulator — zkoušení bez změn. | 🟡 ČÁSTEČNĚ | tlačítko Vyzkoušet spustí automatizaci se zkušebními daty (ne dry-run) |
| 150 | Workflow Versions — verzování postupů. | 🟡 ČÁSTEČNĚ | verze a návrat zpět u protokolů (skillforge.py); automatizace zatím bez verzí |
| 151 | Automation Templates — šablony automatizací. | 🟡 ČÁSTEČNĚ | výchozí protokoly a ukázkové automatizace |
| 152 | Failure Recovery — navázání při přerušení. | ✅ HOTOVO | přerušená mise → Pokračovat od posledního hotového kroku (missions.resume, tests/test_wave1.py) |
| 153 | Workflow Sharing — bezpečné sdílení. | ⬜ CHYBÍ | — |
| 154 | Cost Estimator — predikce nákladů. | ✅ HOTOVO | odhad ceny úkolu podle průměru volání a ceny poskytovatele (usage.estimate, ai_usage) |
| 155 | Agent Scheduling — plánování běhu agentů. | ✅ HOTOVO | plánovač rutin a připomínek (scheduler.py) |

## 15. Hardware Lab

🟡 1 · ⬜ 9

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 156 | Arduino integrace. | ⬜ CHYBÍ | — |
| 157 | ESP32 integrace. | ⬜ CHYBÍ | — |
| 158 | Raspberry Pi integrace. | ⬜ CHYBÍ | — |
| 159 | Základní elektrická schémata. | ⬜ CHYBÍ | — |
| 160 | Výpočty a kontrola součástek. | ⬜ CHYBÍ | — |
| 161 | Sériový port a data. | ⬜ CHYBÍ | — |
| 162 | Jednoduché PCB návrhy. | ⬜ CHYBÍ | — |
| 163 | Diagnostika senzorů. | ⬜ CHYBÍ | — |
| 164 | Firmware projektový management. | ⬜ CHYBÍ | — |
| 165 | Přehled IoT zařízení. | 🟡 ČÁSTEČNĚ | Home Assistant + zařízení v síti (home.py, network.py) |

## 16. Business

🟡 4 · ⬜ 6

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 166 | Schůzky → seznam úkolů. | 🟡 ČÁSTEČNĚ | nahrávání a shrnutí hovorů/schůzek (notetaker.py) |
| 167 | Zápisy z meetingů. | 🟡 ČÁSTEČNĚ | nahrávání a shrnutí hovorů/schůzek (notetaker.py) |
| 168 | Nabídky zákazníkům. | ⬜ CHYBÍ | — |
| 169 | Fakturační podklady. | ⬜ CHYBÍ | — |
| 170 | Zákaznické požadavky. | ⬜ CHYBÍ | — |
| 171 | Projektové termíny. | 🟡 ČÁSTEČNĚ | kalendář a připomínky (calendar_.py) |
| 172 | Srovnání dodavatelských nabídek. | ⬜ CHYBÍ | — |
| 173 | Analýza kampaní. | ⬜ CHYBÍ | — |
| 174 | Přehled příjmů a výdajů. | ⬜ CHYBÍ | — |
| 175 | Týdenní report práce. | 🟡 ČÁSTEČNĚ | týdenní recap diktování/úkolů |

## 17. Security & Control

✅ 7 · 🟡 2 · ⬜ 1

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 176 | Globální Stop All Agents. | ✅ HOTOVO | STOP vše (Ctrl+Alt+X, runtime.stop_all) – test_tasks/test_agent |
| 177 | Read-only režim. | ✅ HOTOVO | Režim jen pro čtení – pustí jen čtecí nástroje, hlasem nejde vypnout (permissions.py, tests/test_wave1.py) |
| 178 | Limit nákladů AI. | ✅ HOTOVO | denní limit tokenů/ceny; po limitu jen bezplatné/místní modely (usage.py, llm/router gate) |
| 179 | Redakce citlivých údajů. | ✅ HOTOVO | redakce tokenů a hesel v logu a audit logu (redact.py) |
| 180 | Oprávnění podle projektu. | ⬜ CHYBÍ | — |
| 181 | Dočasná oprávnění. | ✅ HOTOVO | dočasné povolení vypnutého oprávnění na 15/60 min jen z UI (permissions.grant) |
| 182 | Dvojí potvrzení nebezpečných operací. | ✅ HOTOVO | nevratné akce (mazání, vypnutí PC, odemčení) se ptají dvakrát (agent._needs_second, tests/test_agent.py) |
| 183 | Detekce škodlivých instrukcí z externích zdrojů. | ✅ HOTOVO | skener skrytých pokynů v e-mailech, webech, souborech a zprávách (injection.py, tools/base.py UNTRUSTED_OUTPUT) |
| 184 | Správa propojených zařízení. | 🟡 ČÁSTEČNĚ | seznam připojených telefonů (pairing_get devices) |
| 185 | Revokace ztracených zařízení. | 🟡 ČÁSTEČNĚ | nový párovací kód odpojí všechna zařízení naráz |

## 18. Iron Man — Future Tech

✅ 1 · 🟡 3 · 🗓️ 3 · ⬜ 3

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 186 | Futuristický JARVIS HUD. | ✅ HOTOVO | Stark HUD přes celou obrazovku (web/src/hud, CI kontrola) |
| 187 | AR Companion. | 🗓️ PLÁNOVÁNO | AR / gesta kamerou – vize, M8 |
| 188 | Ovládání gesty kamerou. | 🗓️ PLÁNOVÁNO | AR / gesta kamerou – vize, M8 |
| 189 | Prostorová pracovní plocha. | 🗓️ PLÁNOVÁNO | AR / gesta kamerou – vize, M8 |
| 190 | Digitální dvojče PC. | 🟡 ČÁSTEČNĚ | system_snapshot + report stavu PC |
| 191 | Command Center pro velké displeje. | 🟡 ČÁSTEČNĚ | HUD na celou obrazovku |
| 192 | Vizualizovaná simulace misí. | ⬜ CHYBÍ | — |
| 193 | 3D Explorer komponent PC. | ⬜ CHYBÍ | — |
| 194 | Vizualizace vlastní sítě a spojení. | 🟡 ČÁSTEČNĚ | seznam zařízení v síti (bez grafu) |
| 195 | Přenos Mochiho stavu mezi zařízeními. | ⬜ CHYBÍ | — |

## 19. Hyper Intelligence Engine

✅ 7 · 🟡 2 · 🔌 1 · ⬜ 5

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 196 | Multi-Step Prediction — odhad možných dalších kroků. | ⬜ CHYBÍ | — |
| 197 | Alternative Strategy Generator — několik plánů pro jeden cíl. | ✅ HOTOVO | compare_options: 3 různé cesty k cíli |
| 198 | Intelligent Goal Decomposition — rozklad projektů do fází. | ✅ HOTOVO | goal_plan: rozklad na fáze a kroky |
| 199 | Assumption Checker — validace předpokladů. | ✅ HOTOVO | check_assumptions: skryté předpoklady, riziko, jak ověřit |
| 200 | Evidence Verifier — kontrola zdrojů a důkazů. | ✅ HOTOVO | kontrola citací výzkumu (neexistující a nepoužité zdroje, odstavce bez citace) |
| 201 | Task Dependency Engine — závislosti mezi úkoly. | ⬜ CHYBÍ | — |
| 202 | Adaptive Planning — průběžné aktualizace plánu. | 🟡 ČÁSTEČNĚ | plán se průběžně aktualizuje (update_plan) |
| 203 | Risk Scoring — hodnocení rizika akcí. | ✅ HOTOVO | riziko 1–5 s důvodem u každé varianty; nebezpečné akce se potvrzují (tools/base.py) |
| 204 | AI Consensus — porovnávání výstupů modelů. | 🔌 VYŽADUJE_INTEGRACI | ask_models: shoda/rozpory/společná odpověď – s aspoň dvěma poskytovateli |
| 205 | Contradiction Detection — detekce rozporů. | ⬜ CHYBÍ | — |
| 206 | Solution Ranking — řazení řešení. | ✅ HOTOVO | seřazení variant s odůvodněním |
| 207 | Knowledge Gap Detection — identifikace chybějících dat. | ✅ HOTOVO | co chybí vědět (missing_info) u rozhodování |
| 208 | Experiment Designer — návrh ověřovacích testů. | ⬜ CHYBÍ | — |
| 209 | Outcome Evaluation — vyhodnocení dosažených cílů. | 🟡 ČÁSTEČNĚ | akceptační kritéria mise + ověření (tasks.py criteria, evidence) |
| 210 | Recursive Task Improvement — vylepšení na základě testů. | ⬜ CHYBÍ | — |

## 20. Autonomous Mission Engine

✅ 14 · 🟡 1

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 211 | Mission Queue — fronta misí. | ✅ HOTOVO | fronta misí s časem spuštění (tasks.enqueue, missions.tick, Úkoly → Fronta misí) |
| 212 | Mission Dependencies — vykonávání dle návazností. | ✅ HOTOVO | kroky mise s needs běží ve vlnách, nezávislé současně (agent._waves, run_steps) |
| 213 | Parallel Execution — paralelní kroky. | ✅ HOTOVO | kroky mise s needs běží ve vlnách, nezávislé současně (agent._waves, run_steps) |
| 214 | Agent Communication Bus — zprávy mezi agenty. | ✅ HOTOVO | zadání a výsledek každého specialisty v misi jako důkazy (sběrnice agentů) |
| 215 | Shared Mission Workspace — sdílené pracovní artefakty. | ✅ HOTOVO | pracovní složka mise + mission_save_file jako artefakt (missions.workspace) |
| 216 | Mission Checkpoints — konzistentní checkpointy. | ✅ HOTOVO | kroky strukturované mise uložené (tasks.spec, task_steps) – navázání po přerušení |
| 217 | Pause & Resume — pozastavení a obnovení. | ✅ HOTOVO | pauza/pokračování mise (tasks.py pause/resume, UI) |
| 218 | Agent Handover — předání práce agentovi. | ✅ HOTOVO | agent_team: předání výsledku dalšímu specialistovi |
| 219 | Approval Queue — fronta schválení. | ✅ HOTOVO | fronta schválení: víc čekajících potvrzení najednou (agent.confirm_info, taskcard) |
| 220 | Deadline Awareness — hlídání termínů. | ✅ HOTOVO | termín mise: upozornění 15 min předem a po vypršení (missions.tick) |
| 221 | Mission Budget — nákladové limity. | ✅ HOTOVO | rozpočet mise: max. akcí a minut, pak zastavení (tasks.over_budget, BudgetExceeded) |
| 222 | Mission Dependency Graph — vizualizace závislostí. | 🟡 ČÁSTEČNĚ | vlny kroků vidět v seznamu kroků („vlna N“); grafické DAG zatím ne |
| 223 | Mission Reports — důkazy výsledků. | ✅ HOTOVO | výsledky mise: artefakty se SHA-256 a důkazy (tasks.py) |
| 224 | Result Validation — ověření dokončení. | ✅ HOTOVO | ověření dokončení proti kritériím (pc_health_report) |
| 225 | Mission Recovery — recovery po pádu. | ✅ HOTOVO | obnova po pádu: Přerušeno → Pokračovat ve stejné misi (tasks.recover, missions.resume) |

## 21. Next-Gen Desktop

✅ 5 · 🟡 5 · ⬜ 5

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 226 | Universal Overlay — rozhraní nad aplikacemi. | ✅ HOTOVO | notch a HUD nad aplikacemi (desktop/host.py) |
| 227 | Smart Screen Regions — práce s výřezem obrazovky. | ⬜ CHYBÍ | — |
| 228 | Window Grouping — seskupování oken. | ⬜ CHYBÍ | — |
| 229 | Workspace Profiles — profily prostředí. | ⬜ CHYBÍ | — |
| 230 | Spatial Window Navigator — prostorová navigace. | ⬜ CHYBÍ | — |
| 231 | Command Preview — náhled příkazů. | 🟡 ČÁSTEČNĚ | náhled akce v potvrzovacím dialogu (details) |
| 232 | Interactive Action Timeline — historie operací. | ✅ HOTOVO | časová osa akcí každé mise (audit) |
| 233 | Floating Assistant Bubble — mini bublina. | ✅ HOTOVO | notch s postavičkou |
| 234 | Transparent Focus Mode — nerušivé UI. | ⬜ CHYBÍ | — |
| 235 | Drag-to-JARVIS — přetažení obsahu. | ✅ HOTOVO | přetažení do notche |
| 236 | Smart Clipboard Panel — historie schránky. | ✅ HOTOVO | historie schránky (powers.py) |
| 237 | Animated Context Cards — kontextové karty. | 🟡 ČÁSTEČNĚ | karty výsledků nástrojů v chatu |
| 238 | Cross-Monitor Docking — přesun mezi monitory. | 🟡 ČÁSTEČNĚ | HUD a notch na monitoru s kurzorem |
| 239 | Accessibility Interface — podporované asistivní ovládání. | 🟡 ČÁSTEČNĚ | aria popisky, klávesnice |
| 240 | Low-Power UI — úsporné vykreslování. | 🟡 ČÁSTEČNĚ | vypnutí animací, úsporný režim místních modelů |

## 22. Mochi Ultra

✅ 9 · 🟡 3 · ⬜ 3

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 241 | Emotion Animation Library — knihovna expresí. | ✅ HOTOVO | nálady postavičky (mood.py PRIORITY) |
| 242 | Personality Presets — styly osobnosti. | ⬜ CHYBÍ | — |
| 243 | Mood Transitions — plynulé stavy. | ✅ HOTOVO | plynulé přechody nálad |
| 244 | Music Beat Animation — synchronizace rytmu. | 🟡 ČÁSTEČNĚ | tančí, když hraje hudba (bez synchronizace rytmu) |
| 245 | Physics-Based Movement — pružné pohyby. | ✅ HOTOVO | pružná fyzika postavičky |
| 246 | Cursor Curiosity — interakce s kurzorem. | ✅ HOTOVO | oči sledují kurzor |
| 247 | Screen Edge Play — hravý okraj displeje. | ⬜ CHYBÍ | — |
| 248 | Task Costumes — tematické doplňky. | ✅ HOTOVO | doplňky postavičky (character.outfit) |
| 249 | Sleep Cycles — animace spánku. | ✅ HOTOVO | spánek při nečinnosti |
| 250 | Micro Interactions — mikrointerakce. | ✅ HOTOVO | mikrointerakce a výrazy (character/looks.ts) |
| 251 | Tiny Expressions — jemná mimika. | ✅ HOTOVO | mikrointerakce a výrazy (character/looks.ts) |
| 252 | Mascot Soundboard — krátké zvuky. | ✅ HOTOVO | vlastní zvuky (sounds) |
| 253 | Multiple Mochi Skins — konzistentní varianty vzhledu. | 🟡 ČÁSTEČNĚ | barvy postavičky |
| 254 | Mochi Animation Editor — editor animací. | ⬜ CHYBÍ | — |
| 255 | Mochi Performance Mode — výkonově úsporný režim. | 🟡 ČÁSTEČNĚ | vypnutí animací |

## 23. Voice & Audio Intelligence

✅ 4 · 🟡 5 · ⬜ 6

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 256 | Far-Field Voice Recognition — dálkový mikrofon. | ⬜ CHYBÍ | — |
| 257 | Noise Suppression — filtr hluku. | ⬜ CHYBÍ | — |
| 258 | Echo Cancellation — potlačení ozvěny. | ⬜ CHYBÍ | — |
| 259 | Voice Activity Detection — detekce řeči. | 🟡 ČÁSTEČNĚ | detekce řeči v hlasové smyčce (voice/loop.py) |
| 260 | Wake Word Sensitivity — citlivost fráze. | ⬜ CHYBÍ | — |
| 261 | Speech Speed Adaptation — rychlost hlasu. | ✅ HOTOVO | rychlost hlasu |
| 262 | Audio Context Switching — výběr výstupů. | 🟡 ČÁSTEČNĚ | výběr zvukových zařízení |
| 263 | Voice Shortcuts — hlasové zkratky. | ✅ HOTOVO | hlasové zkratky = protokoly |
| 264 | Technical Vocabulary — odborné názvy. | ✅ HOTOVO | slovník a zkratky diktování |
| 265 | Dictation Correction — opravy přepisu. | ✅ HOTOVO | úprava přepisu diktování |
| 266 | Conversation Bookmarks — záložky. | ⬜ CHYBÍ | — |
| 267 | Speaker Labels — identifikace mluvčích. | ⬜ CHYBÍ | — |
| 268 | Audio Summaries — audio souhrny. | 🟡 ČÁSTEČNĚ | odpovědi nahlas |
| 269 | Conversation Translation — překlady dialogů. | 🟡 ČÁSTEČNĚ | překlad přes AI |
| 270 | Offline Voice Pipeline — lokální hlas. | 🟡 ČÁSTEČNĚ | volitelné místní modely (stahování jen s potvrzením) |

## 24. Advanced Vision

✅ 1 · 🟡 5 · ⬜ 9

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 271 | Video Understanding — analýza videa. | ⬜ CHYBÍ | — |
| 272 | Screen Change Detection — změny obrazu. | ⬜ CHYBÍ | — |
| 273 | Object Tracking — sledování objektu. | ⬜ CHYBÍ | — |
| 274 | UI Hierarchy Reconstruction — struktura UI. | ✅ HOTOVO | strom UI přes UI Automation (tools/uia.py, CI --selftest-uia) |
| 275 | Automatic Form Recognition — formuláře. | ⬜ CHYBÍ | — |
| 276 | Graph Reading — čtení grafů. | 🟡 ČÁSTEČNĚ | grafy/tabulky/schémata přes vision model ze screenshotu |
| 277 | Table Extraction — vytěžení tabulek. | 🟡 ČÁSTEČNĚ | grafy/tabulky/schémata přes vision model ze screenshotu |
| 278 | Diagram Interpretation — schémata. | 🟡 ČÁSTEČNĚ | grafy/tabulky/schémata přes vision model ze screenshotu |
| 279 | Visual Error Localization — místo chyby. | ⬜ CHYBÍ | — |
| 280 | Scene Description — popis scény. | 🟡 ČÁSTEČNĚ | popis obrazovky přes vision model |
| 281 | Camera Measurement Helper — měření s kalibrací. | ⬜ CHYBÍ | — |
| 282 | Color Inspector — čtení barev. | 🟡 ČÁSTEČNĚ | přes vision model |
| 283 | Visual Similarity Search — podobné obrázky. | ⬜ CHYBÍ | — |
| 284 | Motion Analysis — pohybová analýza. | ⬜ CHYBÍ | — |
| 285 | Vision Privacy Masking — maskování citlivých oblastí. | ⬜ CHYBÍ | — |

## 25. JARVIS PC Rescue

✅ 7 · 🟡 5 · ⬜ 3

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 286 | Windows Integrity Inspector — integrita Windows. | 🟡 ČÁSTEČNĚ | system_integrity_check: DISM /CheckHealth + SFC /VERIFYONLY (jen kontrola); CI ho nespouští (trvá minuty) |
| 287 | Driver Rollback Assistant — návrat ovladače. | ⬜ CHYBÍ | — |
| 288 | Boot Problem Analyzer — chyby startu. | ✅ HOTOVO | Boot Problem Analyzer = oblast boot |
| 289 | Disk Partition Inspector — přehled oddílů. | 🟡 ČÁSTEČNĚ | oddíly a jejich zaplnění v reportu |
| 290 | USB Connection Analyzer — diagnostika USB. | ✅ HOTOVO | USB Connection Analyzer = oblast usb |
| 291 | Storage Error Correlation — souvislosti diskových chyb. | 🟡 ČÁSTEČNĚ | chyby disku seskupené podle druhu (vadné sektory, timeouty, NTFS); časová souvislost s pády chybí |
| 292 | File System Health — souborový systém. | ✅ HOTOVO | stav svazků + chyby NTFS (55/98/140) z logu |
| 293 | Crash Pattern Detector — opakující se pády. | ✅ HOTOVO | opakující se pády podle kódu a podle aplikace + modulu (grafický ovladač, systémová knihovna) |
| 294 | Service Dependency Inspector — závislosti služeb. | 🟡 ČÁSTEČNĚ | automatické služby, které neběží, a chyby spouštění; graf závislostí chybí |
| 295 | Power Plan Diagnostics — energetické plány. | ⬜ CHYBÍ | — |
| 296 | Memory Error Testing Assistant — test RAM. | ✅ HOTOVO | schedule_memory_test (Diagnostika paměti Windows, se schválením) + čtení výsledku testu (MemoryDiagnostics-Results) |
| 297 | Thermal Health Report — teploty. | 🟡 ČÁSTEČNĚ | teploty disků (StorageReliabilityCounter, SMART); teplotu CPU Windows bez ovladače výrobce nehlásí |
| 298 | Hardware Change Detector — změny zařízení. | ✅ HOTOVO | strážce každých 5 min porovná zařízení a řekne, co se připojilo/odpojilo (stark.Guardian.check_hardware, hardware_changes) |
| 299 | Recovery Media Assistant — záchranné médium. | ⬜ CHYBÍ | — |
| 300 | Data Rescue Priority Mode — přednost ochrany dat. | ✅ HOTOVO | data_rescue_plan: pořadí záchrany složek, nic nekopíruje ani nemaže; u RAW/offline disku „NEFORMÁTUJ“ |

## 26. Extreme Performance

✅ 8 · 🟡 4 · ⬜ 3

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 301 | CPU Bottleneck Detector — limit procesoru. | ✅ HOTOVO | perf_check: vytížení CPU po jádrech + kdo ho bere |
| 302 | GPU Bottleneck Detector — limit grafiky. | ✅ HOTOVO | vytížení grafiky (čítače GPU Engine) a „brzdí grafika, ne procesor“ |
| 303 | RAM Pressure Analyzer — tlak na RAM. | ✅ HOTOVO | tlak na RAM + nejnáročnější programy |
| 304 | VRAM Usage Tracking — využití VRAM. | ✅ HOTOVO | využití VRAM (GPU Adapter Memory) |
| 305 | Background Task Profiler — procesy na pozadí. | 🟡 ČÁSTEČNĚ | nejnáročnější procesy během měření; profil v čase chybí |
| 306 | Frame-Time Analyzer — nepravidelnosti snímků. | ⬜ CHYBÍ | — |
| 307 | Startup Performance Timeline — start systému. | ✅ HOTOVO | časová osa startu z Diagnostics-Performance |
| 308 | App Launch Benchmarking — rychlost spouštění. | ⬜ CHYBÍ | — |
| 309 | Disk I/O Visualizer — diskové I/O. | 🟡 ČÁSTEČNĚ | čtení/zápis/vytížení každého disku během měření; graf chybí |
| 310 | Resource Priority Profiles — profily výkonu. | ⬜ CHYBÍ | — |
| 311 | Network Latency Monitor — síťová odezva. | ✅ HOTOVO | odezva, kolísání a ztráta (TCP handshake, bez práv správce) |
| 312 | Performance History — historie výkonu. | ✅ HOTOVO | historie výkonu každých 5 min, 30 dní, graf na stránce, perf_history |
| 313 | Gaming Session Analyzer — analýza hraní. | 🟡 ČÁSTEČNĚ | čas v aplikacích (screen_time) |
| 314 | Optimization Before/After — A/B měření změn. | ✅ HOTOVO | perf_benchmark s popiskem a porovnáním s minulým měřením (před/po) |
| 315 | Safe Optimization Advisor — bezpečná doporučení. | 🟡 ČÁSTEČNĚ | ke každému zjištění bezpečná rada; JARVIS sám nic neladí |

## 27. Intelligent File Universe

✅ 11 · 🟡 3 · ⬜ 1

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 316 | Semantic File Search — hledání podle významu. | 🟡 ČÁSTEČNĚ | find_in_files hledá v textu PDF/Word/txt podle slov; hledání podle významu (embeddingy) chybí |
| 317 | Duplicate Detection — duplicity souborů. | ✅ HOTOVO | find_duplicates / remove_duplicates: stejný obsah (SHA-256), ponechá nejstarší, jen do koše, ověří ponechanou kopii |
| 318 | Similar Image Finder — podobné snímky. | ✅ HOTOVO | find_similar_photos: rozdílový hash – najde zmenšené, překomprimované a upravené kopie |
| 319 | Document Classification — třídění. | ✅ HOTOVO | sort_documents: faktury, smlouvy, výpisy, úřady, zdraví, práce, pojištění, účtenky, škola podle obsahu, jinak podle typu; jde vrátit |
| 320 | Smart File Naming — chytré názvy. | 🟡 ČÁSTEČNĚ | smart_rename: typ_datum_firma z obsahu dokumentu (bez AI); u jiných souborů název zůstane |
| 321 | File Relationship Graph — vztahy souborů. | ⬜ CHYBÍ | — |
| 322 | Lost File Finder — hledání ztracených souborů. | ✅ HOTOVO | recent_files (na čem jsem pracoval) + find_in_files (podle obsahu) |
| 323 | Archive Explorer — obsah archivů. | ✅ HOTOVO | archive_contents / extract_archive (ZIP, TAR; 7Z a RAR se 7-Zipem), ochrana proti „zip slip“, jen do nové složky; create_zip s ověřením |
| 324 | File Format Conversion — konverze formátů. | ✅ HOTOVO | convert_file: obrázky mezi sebou, do PDF, zmenšení; PDF → txt; Word → txt/md; Excel ↔ CSV; txt/md → Word |
| 325 | Bulk Rename Planner — hromadné názvy. | ✅ HOTOVO | rename_files: vzor s datem pořízení, pořadím, najdi/nahraď; náhled, dvoufázové přejmenování, undo_rename |
| 326 | Metadata Cleaner — čištění metadat. | ✅ HOTOVO | file_metadata / clean_metadata: GPS, fotoaparát, autor, program z fotek, Wordu a PDF; ověří výsledek |
| 327 | Folder Size Explorer — využití místa. | ✅ HOTOVO | storage_report (co zabírá místo) |
| 328 | Automatic Version Snapshots — verzování souborů. | 🟡 ČÁSTEČNĚ | save_file_version / file_versions / restore_file_version (otisk, 50 verzí); verze se uloží i před přepsáním; automatické sledování změn chybí |
| 329 | File Integrity Checker — hash/integrita. | ✅ HOTOVO | folder_fingerprint / folder_check: co se změnilo, chybí, přibylo (SHA-256) |
| 330 | Intelligent Backup Selection — výběr záloh. | ✅ HOTOVO | backup_plan (co zálohovat první) + backup_folder (jen nové/změněné, ověření SHA-256) |

## 28. Developer God Mode

🟡 3 · 🔌 1 · ⬜ 11

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 331 | Repository Knowledge Index — kódová znalostní báze. | 🔌 VYŽADUJE_INTEGRACI | Claude Code |
| 332 | Architecture Refactor Planner — plán refaktoringu. | ⬜ CHYBÍ | — |
| 333 | Dependency Risk Detector — rizika závislostí. | ⬜ CHYBÍ | — |
| 334 | Test Coverage Explorer — pokrytí testů. | ⬜ CHYBÍ | — |
| 335 | Mutation Testing Assistant — mutační testy. | ⬜ CHYBÍ | — |
| 336 | API Contract Validator — API kontrakty. | ⬜ CHYBÍ | — |
| 337 | Database Migration Preview — náhled migrace. | ⬜ CHYBÍ | — |
| 338 | Code Ownership Map — vlastnictví souborů. | ⬜ CHYBÍ | — |
| 339 | Regression Detector — detekce regresí. | 🟡 ČÁSTEČNĚ | run_tests + Claude Code |
| 340 | Build Failure Root-Cause Analysis — příčiny buildu. | 🟡 ČÁSTEČNĚ | run_tests + Claude Code |
| 341 | Dependency Update Planner — aktualizace knihoven. | ⬜ CHYBÍ | — |
| 342 | Environment Reproducer — reprodukovatelné prostředí. | ⬜ CHYBÍ | — |
| 343 | Automated Release Notes — release notes. | ⬜ CHYBÍ | — |
| 344 | Feature Flag Manager — přepínače funkcí. | ⬜ CHYBÍ | — |
| 345 | Code Experiment Sandbox — experimentální kód. | 🟡 ČÁSTEČNĚ | záchytné body + Claude Code |

## 29. AI Design Studio

🟡 3 · ⬜ 12

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 346 | Design System Generator — tokeny a komponenty. | ⬜ CHYBÍ | — |
| 347 | Responsive Layout Analyzer — různé displeje. | ⬜ CHYBÍ | — |
| 348 | Accessibility Contrast Checker — kontrast. | ⬜ CHYBÍ | — |
| 349 | Animation Curve Editor — animační křivky. | ⬜ CHYBÍ | — |
| 350 | Glass Material Generator — Liquid Glass. | ⬜ CHYBÍ | — |
| 351 | UI Consistency Scanner — jednotnost. | ⬜ CHYBÍ | — |
| 352 | Design-to-Code — převod designu do kódu. | 🟡 ČÁSTEČNĚ | make_website s náhledem v chatu |
| 353 | Screenshot-to-Prototype — screenshot na prototyp. | 🟡 ČÁSTEČNĚ | make_website s náhledem v chatu |
| 354 | Interactive UI Mockups — klikatelné návrhy. | 🟡 ČÁSTEČNĚ | make_website s náhledem v chatu |
| 355 | Icon System Builder — ikony. | ⬜ CHYBÍ | — |
| 356 | Theme Generator — témata. | ⬜ CHYBÍ | — |
| 357 | Motion Design Timeline — animace. | ⬜ CHYBÍ | — |
| 358 | Layout Heatmap — prostor v UI. | ⬜ CHYBÍ | — |
| 359 | Typography Inspector — typografie. | ⬜ CHYBÍ | — |
| 360 | Visual Regression Lab — porovnání změn. | ⬜ CHYBÍ | — |

## 30. Multimedia Production

⬜ 15

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 361 | Smart Scene Detection — identifikace scén. | ⬜ CHYBÍ | — |
| 362 | Silence Remover — odstranění ticha. | ⬜ CHYBÍ | — |
| 363 | Audio Ducking — zeslabení hudby při řeči. | ⬜ CHYBÍ | — |
| 364 | Video Highlight Finder — zajímavé momenty. | ⬜ CHYBÍ | — |
| 365 | Automatic Reframing — poměr stran videa. | ⬜ CHYBÍ | — |
| 366 | Speech Enhancement — čištění řeči. | ⬜ CHYBÍ | — |
| 367 | Background Removal — odstranění pozadí. | ⬜ CHYBÍ | — |
| 368 | Media Asset Organizer — uspořádání médií. | ⬜ CHYBÍ | — |
| 369 | Subtitle Style Generator — styly titulků. | ⬜ CHYBÍ | — |
| 370 | Podcast Chapter Generator — kapitoly audia. | ⬜ CHYBÍ | — |
| 371 | Shot Matching — sjednocení záběrů. | ⬜ CHYBÍ | — |
| 372 | Voiceover Script Assistant — text dabingu. | ⬜ CHYBÍ | — |
| 373 | Sound Effect Matcher — zvukové efekty. | ⬜ CHYBÍ | — |
| 374 | Media Render Queue — fronta renderů. | ⬜ CHYBÍ | — |
| 375 | Export Quality Analyzer — kvalita výstupu. | ⬜ CHYBÍ | — |

## 31. Internet Intelligence

✅ 8 · 🟡 3 · ⬜ 4

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 376 | Source Reliability Profiles — důvěryhodnost zdrojů. | ✅ HOTOVO | source_reliability: instituce, akademická doména, HTTPS, autor, datum, placený obsah, bulvár, podezřelá adresa |
| 377 | Cross-Source Fact Checking — křížové ověření. | ✅ HOTOVO | fact_check: tvrzení v několika nezávislých zdrojích, postoj každého s citací, verdikt |
| 378 | Website Change Watcher — změny webu. | ✅ HOTOVO | watch_website |
| 379 | Price History Analyzer — historie cen. | ✅ HOTOVO | price_history: každá zjištěná cena (dotaz i hlídání) se ukládá – min, max, změna |
| 380 | Research Notebook — poznámky výzkumu. | 🟡 ČÁSTEČNĚ | poznámky (tools/notes.py) |
| 381 | Web Evidence Collector — archivace důkazů. | ✅ HOTOVO | save_web_evidence: HTML + text + hlavičky + čas UTC + SHA-256, pozná změnu proti minulému záznamu |
| 382 | Automated Website Testing — testy webů. | ⬜ CHYBÍ | — |
| 383 | Broken Link Scanner — nefunkční odkazy. | ✅ HOTOVO | broken_links: projde stránky webu a ověří odkazy (HEAD/GET, jen čtení) |
| 384 | Competitor Feature Comparison — srovnání konkurence. | ⬜ CHYBÍ | — |
| 385 | Search Query Optimizer — vyhledávací strategie. | ⬜ CHYBÍ | — |
| 386 | Article Comparison — srovnání článků. | 🟡 ČÁSTEČNĚ | přes AI |
| 387 | Domain Health Inspector — DNS/TLS/dostupnost. | ⬜ CHYBÍ | — |
| 388 | Website Performance Audit — výkon webů. | ✅ HOTOVO | website_audit: rychlost, velikost, komprese, cache, obrázky bez rozměrů, počet skriptů |
| 389 | Web Content Structure Analyzer — struktura obsahu. | ✅ HOTOVO | website_audit: titulek, popis, h1, viewport, og:title, jazyk, osnova nadpisů |
| 390 | Research-to-Action — závěry na úkoly. | 🟡 ČÁSTEČNĚ | závěry → úkoly přes AI |

## 32. Cybersecurity Center

✅ 6 · 🟡 6 · ⬜ 3

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 391 | Permission Audit — aplikace a oprávnění. | ⬜ CHYBÍ | — |
| 392 | Local Port Inspector — místní porty. | ✅ HOTOVO | porty otevřené do sítě a jejich programy (Get-NetTCPConnection) |
| 393 | Firewall Rule Explorer — firewall. | 🟡 ČÁSTEČNĚ | firewall zapnutý/vypnutý po profilech; pravidla neprocházím |
| 394 | Suspicious Startup Detector — podezřelé položky startu. | ✅ HOTOVO | podezřelé položky startu (podpis, umístění) a naplánované úlohy (skryté PowerShell, AppData) |
| 395 | Security Update Tracker — bezpečnostní aktualizace. | 🟡 ČÁSTEČNĚ | stáří aktualizací Windows a definic Defenderu |
| 396 | Credential Exposure Checker — kontrola známých úniků. | ✅ HOTOVO | uniklé heslo přes Have I Been Pwned (k-anonymita: odejde 5 znaků otisku), jen ze stránky, nikdy přes AI |
| 397 | Phishing Link Analyzer — rizika URL. | ✅ HOTOVO | check_link: podvodné domény, napodobení bank/obchodů, IP, punycode, zkracovače – bez otevření |
| 398 | Download Safety Inspector — kontrola downloadů. | ✅ HOTOVO | check_download: původ (Zone.Identifier), skutečný typ, dvojitá přípona, podpis, SHA-256, sken Defenderem |
| 399 | Ransomware Recovery Planner — plán obnovy. | ⬜ CHYBÍ | — |
| 400 | Local Security Dashboard — bezpečnostní přehled. | 🟡 ČÁSTEČNĚ | Bezpečnostní centrum na stránce Záchrana a výkon + oblast security |
| 401 | Secret Detection — úniky API klíčů v kódu. | ✅ HOTOVO | scan_secrets: klíče a hesla v kódu, tajemství nikdy nevypíše celé |
| 402 | Device Trust Manager — důvěryhodná zařízení. | 🟡 ČÁSTEČNĚ | párování telefonu tokenem |
| 403 | Session Revocation Center — odpojení sessions. | 🟡 ČÁSTEČNĚ | nový token = odpojení všech zařízení |
| 404 | Security Incident Timeline — časová osa incidentů. | ⬜ CHYBÍ | — |
| 405 | Emergency Lockdown — zastavení vzdálených akcí. | 🟡 ČÁSTEČNĚ | STOP vše + Režim jen pro čtení; odpojení vzdálených zařízení = nový párovací kód |

## 33. Multi-Device Ecosystem

✅ 3 · 🟡 6 · ⬜ 6

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 406 | Device Discovery — hledání vlastních zařízení. | 🟡 ČÁSTEČNĚ | zařízení v síti (network.py) |
| 407 | Encrypted Device Pairing — párování. | 🟡 ČÁSTEČNĚ | párování tokenem; v LAN bez TLS (viz DECISIONS.md) |
| 408 | Cross-Device Clipboard History — historie schránky. | 🟡 ČÁSTEČNĚ | send_to_phone |
| 409 | Remote Terminal Sessions — zabezpečený remote terminal. | ⬜ CHYBÍ | — |
| 410 | Device Presence Detection — dostupnost zařízení. | ✅ HOTOVO | přítomnost telefonu (phone.link_alive) |
| 411 | Remote Build Monitor — průběh buildu na PC. | 🟡 ČÁSTEČNĚ | průběh úkolu v mobilu |
| 412 | Notification Routing — distribuce oznámení. | ✅ HOTOVO | směrování oznámení PC/telefon (runtime.notify target) |
| 413 | Phone Camera as Input — kamera telefonu. | ⬜ CHYBÍ | — |
| 414 | Audio Device Handoff — přenos hovoru. | ⬜ CHYBÍ | — |
| 415 | Cross-Device File Browser — sdílené soubory. | ⬜ CHYBÍ | — |
| 416 | Remote Wake Support — Wake-on-LAN. | ✅ HOTOVO | wake_device (Wake-on-LAN) |
| 417 | Device Battery Dashboard — baterie. | 🟡 ČÁSTEČNĚ | baterie PC + telefonu (phone_battery) |
| 418 | Offline Device Sync — offline synchronizace. | ⬜ CHYBÍ | — |
| 419 | Device-Specific Permissions — povolení zařízení. | ⬜ CHYBÍ | — |
| 420 | Lost Device Protection — ochrana při ztrátě. | 🟡 ČÁSTEČNĚ | najdi můj telefon (FindPhone.java) |

## 34. Smart Home

✅ 5 · 🟡 4 · ⬜ 6

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 421 | Room Awareness — přiřazení do místností. | ⬜ CHYBÍ | — |
| 422 | Energy Usage Analysis — spotřeba energie. | ⬜ CHYBÍ | — |
| 423 | Smart Lighting Scenes — světelné scény. | ✅ HOTOVO | scény Home Assistantu (home_scene) |
| 424 | Climate Automation — termostaty. | 🟡 ČÁSTEČNĚ | nastavení teploty (home_control climate) |
| 425 | Sensor Event Rules — pravidla senzorů. | 🟡 ČÁSTEČNĚ | automatizace JARVISe; spouštěče ze senzorů HA chybí |
| 426 | Home Network Map — mapa domácí sítě. | ✅ HOTOVO | mapa domácí sítě = seznam zařízení (network_devices) |
| 427 | Device Battery Alerts — upozornění na baterie. | ⬜ CHYBÍ | — |
| 428 | Smart Plug Scheduling — chytré zásuvky. | 🟡 ČÁSTEČNĚ | zásuvky + časové automatizace |
| 429 | Media Room Control — multimédia. | 🟡 ČÁSTEČNĚ | přehrávače HA |
| 430 | Home Automation Simulator — test pravidel. | ⬜ CHYBÍ | — |
| 431 | Device Firmware Tracker — firmware. | ⬜ CHYBÍ | — |
| 432 | Voice-Controlled Scenes — hlasové scény. | ✅ HOTOVO | hlasové scény |
| 433 | Smart Home Event History — historie událostí. | ⬜ CHYBÍ | — |
| 434 | Local-Only Smart Home Mode — domácnost bez cloudu. | ✅ HOTOVO | lokální REST Home Assistantu, bez cloudu |
| 435 | Safety Interlocks — bezpečnostní blokace. | ✅ HOTOVO | zámky, alarm, garáž a brány vždy s potvrzením (home.py risky, tests/test_home.py) |

## 35. Business & Startup

🟡 1 · ⬜ 14

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 436 | Opportunity Analyzer — obchodní příležitosti. | ⬜ CHYBÍ | — |
| 437 | Customer Segmentation — segmentace. | ⬜ CHYBÍ | — |
| 438 | Lead Qualification — hodnocení leadů. | ⬜ CHYBÍ | — |
| 439 | Sales Funnel Explorer — prodejní trychtýř. | ⬜ CHYBÍ | — |
| 440 | Client Follow-Up Planner — následné kontakty. | ⬜ CHYBÍ | — |
| 441 | Proposal Generator — obchodní nabídky. | ⬜ CHYBÍ | — |
| 442 | Pricing Scenario Simulator — cenové scénáře. | ⬜ CHYBÍ | — |
| 443 | Revenue Forecasting — predikce výnosů. | ⬜ CHYBÍ | — |
| 444 | Customer Feedback Analyzer — zpětná vazba. | ⬜ CHYBÍ | — |
| 445 | Competitor Monitoring — změny konkurence. | ⬜ CHYBÍ | — |
| 446 | Marketing Content Calendar — marketingový kalendář. | 🟡 ČÁSTEČNĚ | kalendář |
| 447 | SEO Opportunity Finder — SEO příležitosti. | ⬜ CHYBÍ | — |
| 448 | Client Portal Assistant — zákaznický portál. | ⬜ CHYBÍ | — |
| 449 | Project Profitability Analyzer — ziskovost projektů. | ⬜ CHYBÍ | — |
| 450 | Business Decision Dashboard — obchodní metriky. | ⬜ CHYBÍ | — |

## 36. Learning Lab

✅ 7 · 🟡 2 · ⬜ 6

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 451 | Adaptive Difficulty — adaptivní náročnost. | ⬜ CHYBÍ | — |
| 452 | Learning Path Builder — studijní cesta. | 🟡 ČÁSTEČNĚ | exam_plan rozloží témata do dnů; obecná studijní cesta k cíli = goal_plan |
| 453 | Knowledge Prerequisite Map — předpoklady učiva. | ⬜ CHYBÍ | — |
| 454 | Spaced Repetition Engine — časované opakování. | ✅ HOTOVO | Spaced Repetition Engine (SM-2, opakování za 10 min / 1 / 6 / n dní) |
| 455 | Mistake Classification — druhy chyb. | ✅ HOTOVO | druh chyby u každé odpovědi (nepochopení, chybějící znalost, početní, nepozornost, neúplná) |
| 456 | Interactive Circuit Tutor — obvody. | ⬜ CHYBÍ | — |
| 457 | Math Step Validator — kontrola výpočtů. | ✅ HOTOVO | Math Step Validator: výrazy i rovnice, bezpečný vlastní vyhodnocovač (žádné eval), česká desetinná čárka |
| 458 | Programming Exercise Generator — úlohy. | ⬜ CHYBÍ | — |
| 459 | Virtual Oral Exam — ústní zkoušení. | ✅ HOTOVO | Virtual Oral Exam (oral_exam + check_answer, i hlasem) |
| 460 | Formula Explorer — interaktivní vzorce. | ⬜ CHYBÍ | — |
| 461 | Study Time Analytics — metriky učení. | ✅ HOTOVO | study_stats: opakování, úspěšnost, odpovědi, dny v řadě |
| 462 | Document-to-Quiz — test z dokumentu. | ✅ HOTOVO | Document-to-Quiz |
| 463 | Exam Countdown Planner — plán před zkouškou. | ✅ HOTOVO | Exam Countdown Planner |
| 464 | Concept Connection Map — vztahy konceptů. | 🟡 ČÁSTEČNĚ | souvislosti mezi pojmy v myšlenkové mapě |
| 465 | Project-Based Learning — učení projekty. | ⬜ CHYBÍ | — |

## 37. Engineering & Robotics

⬜ 15

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 466 | CAD Project Assistant — CAD. | ⬜ CHYBÍ | — |
| 467 | 3D Print Preparation — tisková příprava. | ⬜ CHYBÍ | — |
| 468 | Printability Checker — tisknutelnost. | ⬜ CHYBÍ | — |
| 469 | Bill of Materials Generator — BOM součástek. | ⬜ CHYBÍ | — |
| 470 | Component Compatibility Checker — kompatibilita komponent. | ⬜ CHYBÍ | — |
| 471 | Serial Device Monitor — sériový monitor. | ⬜ CHYBÍ | — |
| 472 | Sensor Data Visualizer — data senzorů. | ⬜ CHYBÍ | — |
| 473 | Circuit Calculation Engine — výpočty obvodů. | ⬜ CHYBÍ | — |
| 474 | Power Consumption Estimator — spotřeba. | ⬜ CHYBÍ | — |
| 475 | Firmware Build Assistant — firmware build. | ⬜ CHYBÍ | — |
| 476 | Robotics Motion Simulator — pohyb robota. | ⬜ CHYBÍ | — |
| 477 | Robot Telemetry Dashboard — telemetrie. | ⬜ CHYBÍ | — |
| 478 | Camera Calibration Assistant — kalibrace. | ⬜ CHYBÍ | — |
| 479 | Hardware Experiment Logger — evidence experimentů. | ⬜ CHYBÍ | — |
| 480 | Prototype Test Planner — test prototypu. | ⬜ CHYBÍ | — |

## 38. Iron Man Experimental

🟡 2 · 🗓️ 13

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 481 | Holographic-Style Interface — 3D styl hologramu. | 🟡 ČÁSTEČNĚ | holografický styl HUD |
| 482 | AR Object Annotations — anotace objektů. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 483 | Spatial Voice Commands — hlas v prostorové UI. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 484 | 3D Exploded View — rozložené modely. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 485 | Mechanical Assembly Guide — montážní návody. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 486 | Environmental Sensor Fusion — data více senzorů. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 487 | Smart Glasses Companion — chytré brýle. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 488 | Virtual Engineering Table — virtuální pracovní stůl. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 489 | Robot Fleet Dashboard — řízení flotily. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 490 | Digital Twin Simulator — simulační dvojče. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 491 | Virtual Lab Experiments — virtuální fyzika. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 492 | Hands-Free Workshop Mode — hands-free dílna. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 493 | Gesture-Based 3D Manipulation — gesta ve 3D. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 494 | Wearable Notifications — hodinky a wearables. | 🗓️ PLÁNOVÁNO | vize, M8 |
| 495 | Integrated Command Environment — jeden řídicí prostor. | 🟡 ČÁSTEČNĚ | HUD + dashboard |

## 39. Proactive Intelligence

✅ 11 · 🟡 2 · ⬜ 2

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 496 | Next Action Prediction — návrh dalšího kroku. | ✅ HOTOVO | what_next: další krok s důvodem (termíny, kartičky, nedořešené, rutina v tuto hodinu, zapomenuté, seznamy) |
| 497 | Routine Discovery — rozpoznání rutin. | ✅ HOTOVO | my_routines: aplikace ve stejnou hodinu v řadě dní (všední dny / víkend) z měření po hodinách |
| 498 | Opportunity Alerts — možnosti zjednodušení. | ⬜ CHYBÍ | — |
| 499 | Forgotten Task Detection — opuštěné projekty. | ✅ HOTOVO | forgotten_work: stojící mise, projekty bez práce, staré položky seznamů |
| 500 | Intelligent Interruption Control — vhodný čas oznámení. | ✅ HOTOVO | chytré ztišení: v noci, na schůzce, v soustředění a nad aplikací přes celou obrazovku se upozornění jen ukážou; budík, časovač a připomínky vždy nahlas |
| 501 | Contextual Suggestion Engine — kontextové funkce. | 🟡 ČÁSTEČNĚ | návrhy podle hodiny a rutin; kontext podle otevřené aplikace zatím ne |
| 502 | Deadline Risk Forecasting — rizika termínů. | ✅ HOTOVO | deadline_risks: mise (čas vs. zbývající kroky) a zkoušky bez opakování |
| 503 | Task Effort Estimator — odhad pracnosti. | ✅ HOTOVO | estimate_effort: medián času a kroků z podobných dokončených misí |
| 504 | Personal Routine Builder — osobní rutina. | 🟡 ČÁSTEČNĚ | rutiny se dají převést na automatizaci; skládání osobní rutiny zatím ne |
| 505 | Automatic Priority Negotiation — změny priorit. | ⬜ CHYBÍ | — |
| 506 | Unfinished Conversation Detection — nedořešené otázky. | ✅ HOTOVO | nedořešené rozhovory: tvoje otázka bez odpovědi / JARVISova otázka bez reakce |
| 507 | Idle-Time Task Suggestions — vhodné krátké úkoly. | ✅ HOTOVO | what_next s minutes: jen úkoly, které stihneš (kartičky, krátké položky) |
| 508 | Proactive Error Warnings — včasná varování. | ✅ HOTOVO | strážce: baterie, CPU, RAM, disk, internet, nové zařízení v síti (stark.py) |
| 509 | Contextual Work Resumption — příprava pokračování. | ✅ HOTOVO | project_resume (vlna 4) + nedořešené rozhovory |
| 510 | Daily Achievement Timeline — přehled práce dne. | ✅ HOTOVO | day_summary: dokončené mise, zprávy, diktování, opakování, čas v aplikacích |

## 40. Semantic Operating System

✅ 1 · 🟡 1 · ⬜ 13

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 511 | Natural Language File Commands — soubory přirozenou řečí. | ✅ HOTOVO | soubory přirozenou řečí (tools/files.py) |
| 512 | Universal App Search — hledání uvnitř aplikací. | ⬜ CHYBÍ | — |
| 513 | Cross-App Actions — navazující operace mezi aplikacemi. | ⬜ CHYBÍ | — |
| 514 | App Capability Discovery — zjištění schopností aplikací. | ⬜ CHYBÍ | — |
| 515 | Semantic Desktop Index — propojování desktopových dat. | ⬜ CHYBÍ | — |
| 516 | Virtual App Groups — logické skupiny aplikací. | ⬜ CHYBÍ | — |
| 517 | Smart Window Naming — názvy skupin oken. | ⬜ CHYBÍ | — |
| 518 | Workspace State Comparison — porovnání pracovního prostředí. | ⬜ CHYBÍ | — |
| 519 | App Recovery Assistant — obnova po pádu aplikace. | ⬜ CHYBÍ | — |
| 520 | Universal Command History — hledání příkazů. | 🟡 ČÁSTEČNĚ | search_history |
| 521 | Keyboard Shortcut Discovery — klávesové zkratky. | ⬜ CHYBÍ | — |
| 522 | Adaptive Input Controller — myš/touch/hlas. | ⬜ CHYBÍ | — |
| 523 | Virtual Workspace Snapshots — snímky pracovních ploch. | ⬜ CHYBÍ | — |
| 524 | Desktop Workflow Search — vyhledání pracovního postupu. | ⬜ CHYBÍ | — |
| 525 | Task-Centric Desktop — aplikace seskupené podle úkolu. | ⬜ CHYBÍ | — |

## 41. Super Browser Agent

🟡 3 · ⬜ 12

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 526 | Multi-Tab Research — výzkum na více kartách. | 🟡 ČÁSTEČNĚ | browser_* nástroje |
| 527 | Smart Tab Classification — třídění tabů. | ⬜ CHYBÍ | — |
| 528 | Browser Session Restore — relace prohlížeče. | ⬜ CHYBÍ | — |
| 529 | Website Workflow Recording — zaznamenání postupu. | ⬜ CHYBÍ | — |
| 530 | Form Field Validation — kontrola formulářů. | 🟡 ČÁSTEČNĚ | browser_type + čtení |
| 531 | Captcha Handoff — předání ručního ověření. | 🟡 ČÁSTEČNĚ | computer_use předá uživateli, co samo nesmí (captcha, přihlášení) |
| 532 | Page Structure Comparison — změny struktury. | ⬜ CHYBÍ | — |
| 533 | Navigation Route Finder — navigace webem. | ⬜ CHYBÍ | — |
| 534 | Cookie Preference Assistant — nastavení cookies. | ⬜ CHYBÍ | — |
| 535 | Subscription Overview — přehled předplatných. | ⬜ CHYBÍ | — |
| 536 | Web App Compatibility Tester — prohlížečová kompatibilita. | ⬜ CHYBÍ | — |
| 537 | Session Expiration Awareness — vypršení přihlášení. | ⬜ CHYBÍ | — |
| 538 | Download Source Verification — kontrola zdroje. | ⬜ CHYBÍ | — |
| 539 | Browser Privacy Report — oprávnění webů. | ⬜ CHYBÍ | — |
| 540 | Web Task Continuity — pokračování práce. | ⬜ CHYBÍ | — |

## 42. Communication

✅ 10 · 🟡 4 · ⬜ 1

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 541 | Unified Message Inbox — sloučené zprávy. | ✅ HOTOVO | inbox_overview: e-maily ze všech účtů + zprávy a zmeškané hovory z telefonu v jednom seznamu |
| 542 | Message Importance Ranking — priority komunikace. | ✅ HOTOVO | pořadí podle důležitosti s důvodem (důležitý kontakt, termín, požadavek, peníze, otázka, newsletter) |
| 543 | Reply Context Builder — podklady odpovědi. | ✅ HOTOVO | reply_context: vlákno, karta odesílatele, přílohy, co chce – podklady před odpovědí |
| 544 | Conversation Action Extraction — úkoly ze zpráv. | ✅ HOTOVO | message_actions: požadavky a termíny ze zpráv (do pátku, zítra, do 3. 11.), volitelně do seznamu úkolů |
| 545 | Attachment Relationship Finder — související přílohy. | 🟡 ČÁSTEČNĚ | k přílohám e-mailu najde v PC soubory se stejným názvem; podobnost obsahu ne |
| 546 | Conversation Follow-Up Tracker — navazující komunikace. | ✅ HOTOVO | follow_up_check: na co ti nikdo neodpověděl a na co jsi neodpověděl ty |
| 547 | Tone Adjustment — styl odpovědi. | 🟡 ČÁSTEČNĚ | formálnější/kratší přepis označeného textu |
| 548 | Multilingual Message Drafting — různé jazyky. | 🟡 ČÁSTEČNĚ | překlad |
| 549 | Inbox Noise Reduction — méně spamu. | ✅ HOTOVO | filtr newsletterů |
| 550 | Message Source Linking — zdroje konverzací. | ⬜ CHYBÍ | — |
| 551 | Communication Search Assistant — vyhledání rozhodnutí. | 🟡 ČÁSTEČNĚ | email_search |
| 552 | Response Time Analytics — doby odpovědí. | ✅ HOTOVO | průměrná doba tvé odpovědi (odeslaná pošta vs. doručená) |
| 553 | Contact Context Cards — přehled kontaktů. | ✅ HOTOVO | contact_card: zprávy, poslední kontakt, adresy, co o něm JARVIS ví, společné události |
| 554 | Draft Approval System — schválení odeslání. | ✅ HOTOVO | odeslání e-mailu/SMS jen po schválení |
| 555 | Communication Digest — souhrny komunikace. | ✅ HOTOVO | communication_digest: kolik čeho přišlo, co je důležité, co po tobě kdo chce |

## 43. Meetings

✅ 10 · 🟡 2 · ⬜ 3

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 556 | Meeting Preparation Engine — podklady schůzek. | ✅ HOTOVO | meeting_prep: podklady z paměti a e-mailů k nejbližší / zadané schůzce |
| 557 | Agenda Builder — program jednání. | ✅ HOTOVO | návrh programu schůzky z podkladů |
| 558 | Availability Conflict Resolver — řešení konfliktů. | ✅ HOTOVO | calendar_check: překrývající se schůzky |
| 559 | Meeting Decision Log — rozhodnutí schůzky. | ✅ HOTOVO | meeting_minutes: rozhodnutí z přepisu nahrávky |
| 560 | Speaker Contribution Summary — příspěvky řečníků. | ✅ HOTOVO | kdo kolik mluvil (podíl slov podle přepisu) |
| 561 | Action Owner Assignment — přiřazení vlastníků úkolů. | ✅ HOTOVO | úkoly ze schůzky s vlastníkem a termínem |
| 562 | Meeting Follow-Up Generator — následné zprávy. | ✅ HOTOVO | návrh následného e-mailu (odešle se až po schválení přes email_send) |
| 563 | Calendar Travel Buffer — cestovní rezerva. | ✅ HOTOVO | málo času na přesun mezi schůzkami na různých místech |
| 564 | Meeting Relevance Checker — opakující se schůzky. | ⬜ CHYBÍ | — |
| 565 | Project Milestone Calendar — kalendář milníků. | 🟡 ČÁSTEČNĚ | kalendář |
| 566 | Meeting Notes Search — hledání poznámek. | 🟡 ČÁSTEČNĚ | hledání v poznámkách |
| 567 | Recurring Meeting Review — hodnocení schůzek. | ⬜ CHYBÍ | — |
| 568 | Availability Sharing Assistant — sdílení možností termínů. | ✅ HOTOVO | free_time: volné termíny jako text k poslání |
| 569 | Meeting Document Organizer — soubory schůzek. | ⬜ CHYBÍ | — |
| 570 | Decision-to-Task Converter — rozhodnutí na úkoly. | ✅ HOTOVO | úkoly ze schůzky rovnou do seznamu (to_list) |

## 44. Local AI Supercomputer

✅ 1 · 🟡 3 · ⬜ 11

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 571 | Local Model Benchmarking — porovnání rychlosti. | ⬜ CHYBÍ | — |
| 572 | Automatic Model Quantization Advisor — kvantizace modelu. | ⬜ CHYBÍ | — |
| 573 | VRAM-Aware Model Loading — výběr modelu dle VRAM. | 🟡 ČÁSTEČNĚ | test GPU pro místní modely |
| 574 | CPU/GPU Hybrid Inference — hybridní výpočty. | ⬜ CHYBÍ | — |
| 575 | Model Warm-Up Manager — rychlejší start. | ⬜ CHYBÍ | — |
| 576 | Idle Model Unloading — uvolnění paměti. | ✅ HOTOVO | uvolnění místního modelu (local_unload) |
| 577 | Inference Queue Scheduler — fronta inference. | ⬜ CHYBÍ | — |
| 578 | Model Compatibility Scanner — kompatibilita. | ⬜ CHYBÍ | — |
| 579 | Offline Knowledge Pack Manager — offline znalosti. | ⬜ CHYBÍ | — |
| 580 | Embedding Model Selector — embeddingy. | ⬜ CHYBÍ | — |
| 581 | Local RAG Workspace — hledání v místních dokumentech. | ⬜ CHYBÍ | — |
| 582 | Model Accuracy Testing — kvalita odpovědí. | ⬜ CHYBÍ | — |
| 583 | Automatic Resource Throttling — řízení zdrojů. | 🟡 ČÁSTEČNĚ | režimy úsporný/vyvážený/výkon |
| 584 | Local AI Cache — cache odpovědí. | ⬜ CHYBÍ | — |
| 585 | Model Health Monitor — stav modelů. | 🟡 ČÁSTEČNĚ | stav místních modelů |

## 45. Universal Integration Gateway

✅ 1 · 🟡 3 · ⬜ 11

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 586 | Connector Discovery — dostupné integrace. | 🟡 ČÁSTEČNĚ | MCP servery |
| 587 | Connector Health Checks — funkčnost připojení. | 🟡 ČÁSTEČNĚ | test poskytovatele AI (provider_test) |
| 588 | API Schema Importer — OpenAPI specifikace. | ⬜ CHYBÍ | — |
| 589 | Natural Language API Builder — API požadavky řečí. | ⬜ CHYBÍ | — |
| 590 | Webhook Event Router — události. | ⬜ CHYBÍ | — |
| 591 | Connector Permission Dashboard — oprávnění. | 🟡 ČÁSTEČNĚ | stránka Oprávnění |
| 592 | Token Expiration Manager — expirace tokenů. | ⬜ CHYBÍ | — |
| 593 | Integration Test Sandbox — testování bez ostrých dat. | ⬜ CHYBÍ | — |
| 594 | API Rate-Limit Analyzer — limity API. | ⬜ CHYBÍ | — |
| 595 | Data Mapping Designer — mapování dat. | ⬜ CHYBÍ | — |
| 596 | Connector Version Tracking — verze API. | ⬜ CHYBÍ | — |
| 597 | Service Outage Fallback — výpadek integrace. | ✅ HOTOVO | řetěz poskytovatelů AI s náhradou při výpadku (llm/router) |
| 598 | Data Sync Conflict Resolver — konflikty synchronizace. | ⬜ CHYBÍ | — |
| 599 | Event Replay System — přehrání události. | ⬜ CHYBÍ | — |
| 600 | Custom Connector SDK — tvorba vlastních konektorů. | ⬜ CHYBÍ | — |

## 46. Database Intelligence

⬜ 15

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 601 | Database Schema Explorer — databázové schéma. | ⬜ CHYBÍ | — |
| 602 | Index Recommendation Engine — indexy. | ⬜ CHYBÍ | — |
| 603 | Query Execution Visualizer — exekuční plán. | ⬜ CHYBÍ | — |
| 604 | Slow Query Detector — pomalé dotazy. | ⬜ CHYBÍ | — |
| 605 | Data Integrity Analyzer — kontrola integrity. | ⬜ CHYBÍ | — |
| 606 | Backup Verification Engine — kontrola záloh. | ⬜ CHYBÍ | — |
| 607 | Restore Rehearsal — cvičná obnova. | ⬜ CHYBÍ | — |
| 608 | Schema Drift Detector — rozdíly schémat. | ⬜ CHYBÍ | — |
| 609 | Sensitive Column Scanner — osobní a citlivá data. | ⬜ CHYBÍ | — |
| 610 | Database Capacity Forecast — odhad růstu. | ⬜ CHYBÍ | — |
| 611 | Data Anonymization Assistant — anonymizace testovacích dat. | ⬜ CHYBÍ | — |
| 612 | Query Cost Estimator — náročnost dotazů. | ⬜ CHYBÍ | — |
| 613 | Database Change Audit — změny databáze. | ⬜ CHYBÍ | — |
| 614 | Replication Status Dashboard — replikace. | ⬜ CHYBÍ | — |
| 615 | Database Incident Assistant — databázové incidenty. | ⬜ CHYBÍ | — |

## 47. Autonomous Software Factory

🟡 3 · ⬜ 12

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 616 | Requirements Extractor — záměr na požadavky. | ⬜ CHYBÍ | — |
| 617 | Acceptance Criteria Generator — akceptační kritéria. | ⬜ CHYBÍ | — |
| 618 | Architecture Decision Records — ADR. | 🟡 ČÁSTEČNĚ | docs/DECISIONS.md |
| 619 | Monorepo Organizer — více aplikací. | ⬜ CHYBÍ | — |
| 620 | SDK Generator — klientské SDK. | ⬜ CHYBÍ | — |
| 621 | Mock Server Builder — testovací server. | ⬜ CHYBÍ | — |
| 622 | Canary Deployment Manager — postupný deploy. | ⬜ CHYBÍ | — |
| 623 | Automated Rollback Planner — návrat verze. | ⬜ CHYBÍ | — |
| 624 | Software Bill of Materials — SBOM. | ⬜ CHYBÍ | — |
| 625 | Supply Chain Inspector — rizika knihoven. | ⬜ CHYBÍ | — |
| 626 | CI Pipeline Designer — CI/CD. | 🟡 ČÁSTEČNĚ | vlastní CI (.github/workflows/build.yml) |
| 627 | Release Compatibility Checker — kompatibilita vydání. | ⬜ CHYBÍ | — |
| 628 | Background Job Inspector — worker jobs. | ⬜ CHYBÍ | — |
| 629 | Mobile Deep-Link Tester — deep links. | ⬜ CHYBÍ | — |
| 630 | Feature Completion Auditor — kontrola úplnosti. | 🟡 ČÁSTEČNĚ | tento audit (docs/FEATURE_AUDIT.md) |

## 48. Software Testing Lab

🟡 1 · ⬜ 14

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 631 | Synthetic User Testing — simulované uživatelské scénáře. | ⬜ CHYBÍ | — |
| 632 | Property-Based Testing — vlastnostní testy. | ⬜ CHYBÍ | — |
| 633 | Input Fuzzing — neobvyklé vstupy. | ⬜ CHYBÍ | — |
| 634 | Network Failure Simulation — výpadky sítě. | ⬜ CHYBÍ | — |
| 635 | Memory Leak Detector — úniky paměti. | ⬜ CHYBÍ | — |
| 636 | Flaky Test Analyzer — nestabilní testy. | ⬜ CHYBÍ | — |
| 637 | Crash Reproduction Assistant — reprodukce pádu. | ⬜ CHYBÍ | — |
| 638 | Device Test Matrix — testy zařízení. | ⬜ CHYBÍ | — |
| 639 | Localization Overflow Testing — přetečení textu. | ⬜ CHYBÍ | — |
| 640 | Battery Consumption Profiler — spotřeba energie. | ⬜ CHYBÍ | — |
| 641 | Offline Behavior Tester — offline funkcionalita. | ⬜ CHYBÍ | — |
| 642 | Concurrent User Simulation — více uživatelů. | ⬜ CHYBÍ | — |
| 643 | Data Corruption Recovery Test — poškození testovacích dat. | ⬜ CHYBÍ | — |
| 644 | Accessibility Keyboard Tester — přístupnost klávesnicí. | ⬜ CHYBÍ | — |
| 645 | Test Evidence Recorder — důkazy o testech. | 🟡 ČÁSTEČNĚ | důkazy misí (task_evidence) + 410 testů |

## 49. Autonomous Game Development Studio

⬜ 15

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 646 | Procedural World Builder — generování světů. | ⬜ CHYBÍ | — |
| 647 | NPC Dialogue System — dialogy NPC. | ⬜ CHYBÍ | — |
| 648 | Quest Graph Designer — herní questy. | ⬜ CHYBÍ | — |
| 649 | Game Economy Simulator — simulace ekonomiky. | ⬜ CHYBÍ | — |
| 650 | Loot Balance Calculator — balancing odměn. | ⬜ CHYBÍ | — |
| 651 | Spawn Balance Analyzer — pozice objektů a nepřátel. | ⬜ CHYBÍ | — |
| 652 | Level Layout Generator — návrhy levelů. | ⬜ CHYBÍ | — |
| 653 | Anti-Exploit Test Assistant — testy vlastních her. | ⬜ CHYBÍ | — |
| 654 | Save Data Validator — uložená data. | ⬜ CHYBÍ | — |
| 655 | Animation State Machine Builder — animace postav. | ⬜ CHYBÍ | — |
| 656 | Voxel Structure Generator — voxelová tvorba. | ⬜ CHYBÍ | — |
| 657 | Server Capacity Simulator — kapacita serveru. | ⬜ CHYBÍ | — |
| 658 | Game Telemetry Explorer — herní telemetrie. | ⬜ CHYBÍ | — |
| 659 | Game Accessibility Inspector — přístupnost hry. | ⬜ CHYBÍ | — |
| 660 | Gameplay Balance Experimenter — herní balanc. | ⬜ CHYBÍ | — |

## 50. AI Creative Production

⬜ 15

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 661 | Brand Asset Consistency — vizuální konzistence. | ⬜ CHYBÍ | — |
| 662 | Batch Content Producer — více výstupů. | ⬜ CHYBÍ | — |
| 663 | Caption A/B Generator — varianty textu. | ⬜ CHYBÍ | — |
| 664 | Content Licensing Tracker — licence obsahu. | ⬜ CHYBÍ | — |
| 665 | Virtual Camera Director — 3D kamerové pohyby. | ⬜ CHYBÍ | — |
| 666 | Lighting Setup Planner — 3D osvětlení. | ⬜ CHYBÍ | — |
| 667 | 3D Rigging Assistant — rigging modelů. | ⬜ CHYBÍ | — |
| 668 | Lip-Sync Animator — synchronizace úst. | ⬜ CHYBÍ | — |
| 669 | Audio Mixing Advisor — mix audia. | ⬜ CHYBÍ | — |
| 670 | Render Cost Planner — nároky renderu. | ⬜ CHYBÍ | — |
| 671 | Color Management Assistant — barevné profily. | ⬜ CHYBÍ | — |
| 672 | Storyboard-to-Timeline — storyboard na časovou osu. | ⬜ CHYBÍ | — |
| 673 | Interactive Product Demo Builder — produktové ukázky. | ⬜ CHYBÍ | — |
| 674 | Subtitle Quality Checker — kontrola titulků. | ⬜ CHYBÍ | — |
| 675 | Asset Provenance Tracker — původ assetů. | ⬜ CHYBÍ | — |

## 51. Privacy Fortress

✅ 11 · 🟡 1 · ⬜ 3

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 676 | Consent Receipt Manager — evidence souhlasů. | ⬜ CHYBÍ | — |
| 677 | Personal Data Inventory — evidence údajů. | ✅ HOTOVO | inventář dat: co, kolik a kde (privacy.inventory, Bezpečí a soukromí) |
| 678 | Outbound Data Inspector — před odesláním dat. | ✅ HOTOVO | spotřeba po poskytovatelích: kolik textu a obrázků šlo kam (usage.py) |
| 679 | Microphone Access Audit — mikrofon. | ✅ HOTOVO | záznam, kdy naslouchal mikrofon (privacy.MicLog) |
| 680 | Camera Access Audit — kamera. | ✅ HOTOVO | kamera se nepoužívá – uvedeno v přehledu mikrofonu a kamery |
| 681 | Clipboard Secret Masking — redakce schránky. | ✅ HOTOVO | hesla a tokeny se do historie schránky neukládají (powers.looks_secret) |
| 682 | Application Allowlist — seznam povolených aplikací. | ✅ HOTOVO | myš a klávesnice jen v povolených aplikacích (limits.app_allowlist, tools/base.py) |
| 683 | Temporary Permission Grants — dočasná povolení. | ✅ HOTOVO | dočasné povolení vypnutého oprávnění na 15/60 min jen z UI (permissions.grant) |
| 684 | Data Retention Rules — uchovávání dat. | ✅ HOTOVO | mazání dat starších než N dní (privacy.prune, denně) |
| 685 | Encrypted Vault Backup — šifrované zálohy. | ✅ HOTOVO | šifrovaná záloha AES-256-GCM + PBKDF2, obnova do nové složky (privacy.backup_encrypted) |
| 686 | Untrusted Agent Isolation — izolace agentů. | ⬜ CHYBÍ | — |
| 687 | Audit Log Export — export logů. | ✅ HOTOVO | export auditu do CSV + JSON (missions.export_audit) |
| 688 | Project Isolation Profiles — oddělení projektů. | ⬜ CHYBÍ | — |
| 689 | Sensitive Action Lock — uzamčení rizikových akcí. | 🟡 ČÁSTEČNĚ | potvrzení + otisk prstu |
| 690 | Privacy Transparency Center — transparentnost. | ✅ HOTOVO | stránka Bezpečí a soukromí (dashboard/security.ts) |

## 52. Advanced Hardware Rescue

✅ 3 · 🟡 4 · 🔌 1 · ⬜ 7

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 691 | USB Power Diagnostics — napájení USB. | ⬜ CHYBÍ | — |
| 692 | USB Controller Mapping — řadiče USB. | ⬜ CHYBÍ | — |
| 693 | Cable & Enclosure Troubleshooter — kabely a USB boxy. | 🟡 ČÁSTEČNĚ | rada u disků v USB rámečku a opakovaného odpojování |
| 694 | Storage Bridge Detection — USB–SATA/NVMe bridge. | 🟡 ČÁSTEČNĚ | rozpoznání USB rámečku podle názvu (JMicron, ASMedia, Realtek…) |
| 695 | NVMe Enumeration Inspector — enumerace NVMe. | ⬜ CHYBÍ | — |
| 696 | SATA Error Log Reader — SATA logy. | ⬜ CHYBÍ | — |
| 697 | SMART Passthrough Tester — SMART přes USB. | 🔌 VYŽADUJE_INTEGRACI | plný SMART přes smartctl, když je nainstalovaný smartmontools (rescue.smart_data) |
| 698 | Invisible Disk Triage — disky nedetekované systémem. | 🟡 ČÁSTEČNĚ | disky offline / RAW / bez oddílů (Get-Disk) |
| 699 | Read-Only Imaging Planner — image dat v read-only režimu. | ⬜ CHYBÍ | — |
| 700 | Clone Verification Assistant — integrita klonu. | ✅ HOTOVO | verify_copy: SHA-256 každého souboru, chybějící a odlišné |
| 701 | Read Error Heatmap — vadné oblasti dle logů. | ⬜ CHYBÍ | — |
| 702 | Accidental Format Protection — ochrana před formátem. | ✅ HOTOVO | run_shell nikdy nespustí format, diskpart, Clear-Disk, mazání stínových kopií… ani se schválením (tools/shell.py) |
| 703 | Recovery Viability Assessment — možnosti obnovy. | 🟡 ČÁSTEČNĚ | plán záchrany dat podle priorit; odhad úspěšnosti obnovy chybí |
| 704 | I/O Timeout Analyzer — timeouty disků. | ✅ HOTOVO | timeouty a resety řadiče (129, 153, 11) z logu |
| 705 | Hardware Incident Report — report pro servis. | ⬜ CHYBÍ | — |

## 53. Network & Cloud Command Center

✅ 2 · 🟡 5 · ⬜ 8

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 706 | Visual Traceroute — mapa síťové cesty. | 🟡 ČÁSTEČNĚ | trasa po skocích (tracert); grafická mapa chybí |
| 707 | DNS Propagation Tracker — DNS propagace. | ✅ HOTOVO | co o doméně říká Google DNS, Cloudflare a tento PC |
| 708 | TLS Certificate Watch — certifikáty. | 🟡 ČÁSTEČNĚ | kontrola certifikátu na požádání (platnost, vydavatel, protokol); průběžné hlídání chybí |
| 709 | HTTP Synthetic Monitoring — dostupnost API. | 🟡 ČÁSTEČNĚ | dostupnost webu/API na požádání; průběžné hlídání chybí |
| 710 | Cloud Resource Inventory — cloud zdroje. | ⬜ CHYBÍ | — |
| 711 | Cloud Cost Anomaly Detection — anomálie nákladů. | ⬜ CHYBÍ | — |
| 712 | Hosting Health Inspector — stav hostingu. | ⬜ CHYBÍ | — |
| 713 | Centralized Log Explorer — agregované logy. | ⬜ CHYBÍ | — |
| 714 | Deployment Difference Analyzer — rozdíly nasazení. | ⬜ CHYBÍ | — |
| 715 | Infrastructure Rollback Rehearsal — cvičná obnova. | ⬜ CHYBÍ | — |
| 716 | Cloud Backup Receipt Checker — potvrzení záloh. | ⬜ CHYBÍ | — |
| 717 | Local Network Throughput Tester — propustnost vlastní sítě. | 🟡 ČÁSTEČNĚ | speed_test (internet, ne LAN) |
| 718 | Jitter Analysis — kolísání latence. | ✅ HOTOVO | kolísání latence (jitter) v perf_check a network_check |
| 719 | Packet Loss History — ztrátovost paketů. | 🟡 ČÁSTEČNĚ | ztráta paketů při měření; historie jen z měření na požádání |
| 720 | Infrastructure Outage Timeline — historie výpadků. | ⬜ CHYBÍ | — |

## 54. Next-Gen Mobile

🟡 3 · ⬜ 12

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 721 | Notification Quick Actions — akce z notifikací. | 🟡 ČÁSTEČNĚ | akce v notifikacích |
| 722 | Live Mission Widgets — živé widgety. | ⬜ CHYBÍ | — |
| 723 | Camera-to-Task — úkol z fotografie. | ⬜ CHYBÍ | — |
| 724 | Mobile Share Sheet Integration — nabídka Sdílet. | ⬜ CHYBÍ | — |
| 725 | Offline Voice Command Queue — offline hlasové příkazy. | ⬜ CHYBÍ | — |
| 726 | Clipboard Sanitizer — bezpečné sdílení textu. | ⬜ CHYBÍ | — |
| 727 | Temporary Device Pairing — krátkodobé párování. | ⬜ CHYBÍ | — |
| 728 | Location-Based Routines — dobrovolné lokální rutiny. | ⬜ CHYBÍ | — |
| 729 | Remote Camera Consent Controls — přístup ke kameře. | ⬜ CHYBÍ | — |
| 730 | Mobile Shortcut Bridge — mobilní systémové zkratky. | ⬜ CHYBÍ | — |
| 731 | QR Command Launcher — akce z QR kódu. | ⬜ CHYBÍ | — |
| 732 | Link Handoff — předání odkazu. | 🟡 ČÁSTEČNĚ | otevření odkazu na PC z mobilu |
| 733 | Proximity Pairing Check — proximity Bluetooth ověření. | ⬜ CHYBÍ | — |
| 734 | Battery-Aware Synchronization — úspora energie. | ⬜ CHYBÍ | — |
| 735 | Remote Mission Approval — schválení z telefonu. | 🟡 ČÁSTEČNĚ | schvalování Claude Code z telefonu s otiskem |

## 55. Mochi Reactive Companion

✅ 4 · 🟡 1 · ⬜ 10

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 736 | Expression Blending — spojování výrazů. | ⬜ CHYBÍ | — |
| 737 | Real Task Emotions — stavové animace. | ✅ HOTOVO | nálady podle skutečných událostí (mood.py) |
| 738 | Mute Awareness — reakce na ztlumení. | ⬜ CHYBÍ | — |
| 739 | Weather Accessories — doplňky dle počasí. | ⬜ CHYBÍ | — |
| 740 | Time-Based Outfits — doplňky dle času. | ⬜ CHYBÍ | — |
| 741 | Ambient Light Adaptation — adaptace jasu. | ⬜ CHYBÍ | — |
| 742 | Accessibility Animation Mode — omezený pohyb. | ✅ HOTOVO | omezení animací |
| 743 | Soft Body Physics — pružná fyzika. | ⬜ CHYBÍ | — |
| 744 | Code Error Confusion — reakce na chybu buildu. | 🟡 ČÁSTEČNĚ | nálada chyba při selhání |
| 745 | Test Success Celebration — oslava testu. | ✅ HOTOVO | radost po ověřené misi |
| 746 | Rare Easter Eggs — překvapivé animace. | ⬜ CHYBÍ | — |
| 747 | Idle Toys — hračky při nečinnosti. | ⬜ CHYBÍ | — |
| 748 | AI Limit Reaction — limit modelu. | ✅ HOTOVO | reakce na limit AI (mood limit) |
| 749 | Model Switching Animation — změna AI. | ⬜ CHYBÍ | — |
| 750 | Custom Reaction Studio — editor reakcí. | ⬜ CHYBÍ | — |

## 56. Futuristic JARVIS Interface

✅ 2 · 🟡 3 · ⬜ 10

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 751 | Contextual Radial Menu — radiální akce. | ⬜ CHYBÍ | — |
| 752 | Smart Overlay Anchoring — připnutí k oknu. | ⬜ CHYBÍ | — |
| 753 | Attention-Aware UI — méně rušení. | ⬜ CHYBÍ | — |
| 754 | Live Agent Activity Map — mapa agentů. | ⬜ CHYBÍ | — |
| 755 | Mission Dependency Animation — návaznosti úkolů. | ⬜ CHYBÍ | — |
| 756 | HUD Layout Presets — layout profily. | ⬜ CHYBÍ | — |
| 757 | Command Palette Search — příkazová paleta. | ✅ HOTOVO | příkazová paleta Ctrl+K (dashboard/palette.ts) |
| 758 | Adaptive Density UI — velikost a hustota UI. | ⬜ CHYBÍ | — |
| 759 | Floating Data Lens — datová lupa. | ⬜ CHYBÍ | — |
| 760 | Animated Status Morphing — plynulé indikátory. | 🟡 ČÁSTEČNĚ | animované stavy |
| 761 | Spatial Audio Notifications — prostorové zvuky. | ⬜ CHYBÍ | — |
| 762 | Touch-Friendly Dashboard — dotyková verze. | 🟡 ČÁSTEČNĚ | mobilní aplikace |
| 763 | Miniature Mission Viewer — mini stav mise. | ✅ HOTOVO | mini stav mise v notchi a mobilu (taskcard) |
| 764 | HUD Performance Governor — úsporné UI. | 🟡 ČÁSTEČNĚ | vypnutí animací |
| 765 | Interface Behavior Editor — chování prvků. | ⬜ CHYBÍ | — |

## 57. Science & Simulation

🟡 2 · ⬜ 13

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 766 | Interactive Equation Solver — rovnice s postupem. | 🟡 ČÁSTEČNĚ | run_python / AI |
| 767 | Dataset Cleaning Assistant — čištění dat. | ⬜ CHYBÍ | — |
| 768 | Computational Notebook Runner — výpočetní notebooky. | 🟡 ČÁSTEČNĚ | run_python |
| 769 | Experiment Logbook — záznam experimentů. | ⬜ CHYBÍ | — |
| 770 | Chart Interpretation Engine — interpretace grafů. | ⬜ CHYBÍ | — |
| 771 | Data Lineage Viewer — původ dat. | ⬜ CHYBÍ | — |
| 772 | Physical Unit Validator — jednotky. | ⬜ CHYBÍ | — |
| 773 | CAD Tolerance Assistant — tolerance. | ⬜ CHYBÍ | — |
| 774 | Generative Engineering Concepts — technické alternativy. | ⬜ CHYBÍ | — |
| 775 | Technical Model Inspector — geometrie 3D. | ⬜ CHYBÍ | — |
| 776 | Physics Parameter Explorer — parametry simulací. | ⬜ CHYBÍ | — |
| 777 | Scientific Citation Checker — vědecké zdroje. | ⬜ CHYBÍ | — |
| 778 | Signal Frequency Analyzer — frekvenční analýza. | ⬜ CHYBÍ | — |
| 779 | Statistical Quality Inspector — kvalita statistiky. | ⬜ CHYBÍ | — |
| 780 | A/B Experiment Designer — experimenty. | ⬜ CHYBÍ | — |

## 58. Everyday Intelligence & Accessibility

✅ 4 · 🟡 5 · 🔌 1 · ⬜ 5

| ID | Funkce | Stav | Důkaz / modul / omezení |
|---|---|---|---|
| 781 | Life Event Planner — osobní události. | ⬜ CHYBÍ | — |
| 782 | Travel Packing Assistant — balení na cesty. | ⬜ CHYBÍ | — |
| 783 | Weather-Aware Planning — plány podle počasí. | 🟡 ČÁSTEČNĚ | počasí v brífinku |
| 784 | Public Transport Connector — dopravní spojení. | 🔌 VYŽADUJE_INTEGRACI | veřejné API pro jízdní řády ČR chybí |
| 785 | Smart Grocery List — nákupní seznam. | ✅ HOTOVO | nákupní seznam (tools/list_tools.py) |
| 786 | Recipe Ingredient Substitution — náhrady surovin. | ⬜ CHYBÍ | — |
| 787 | Daily Focus Report — soustředění. | 🟡 ČÁSTEČNĚ | čas v aplikacích |
| 788 | Screen Reader Optimization — čtečky. | 🟡 ČÁSTEČNĚ | aria popisky |
| 789 | One-Handed Control Profiles — jedna ruka. | ⬜ CHYBÍ | — |
| 790 | Live Caption Accessibility — živé titulky. | ⬜ CHYBÍ | — |
| 791 | Reading Assistance Mode — jednodušší text. | 🟡 ČÁSTEČNĚ | vysvětlení / zjednodušení označeného textu |
| 792 | Digital Wellbeing Dashboard — využití aplikací. | ✅ HOTOVO | čas u PC po aplikacích (screen_time) |
| 793 | Personal Data Portability — export dat. | ✅ HOTOVO | export všech dat do ZIP bez hesel (privacy.export_all) |
| 794 | Complete Local Memory Reset — vymazání lokální paměti. | ✅ HOTOVO | úplné smazání po napsání SMAZAT, odpojí telefony (privacy.reset_all) |
| 795 | JARVIS Setup Wizard — kompletní průvodce nastavením. | 🟡 ČÁSTEČNĚ | Co je nového + nastavení; plný průvodce chybí |

## Původní seznam 110+ schopností

| ID | Schopnost | Stav | Důkaz / modul | Překryv s katalogem |
|---|---|---|---|---|
| P1.01 | Multi-AI engine – Claude, GPT, Gemini a lokální modely | ✅ HOTOVO | řetěz poskytovatelů (Claude, OpenAI, Gemini, Groq, OmniRoute, Ollama/LM Studio) – llm/router | 597 |
| P1.02 | Automatický výběr modelu podle obtížnosti, ceny a dostupnosti | 🟡 ČÁSTEČNĚ | pořadí řetězu a fallback při výpadku; výběr podle obtížnosti/ceny chybí | 004-009 |
| P1.03 | Dlouhodobá paměť | ✅ HOTOVO | trvalá fakta + remember (memory.py) | 036-045 |
| P1.04 | Krátkodobá paměť | ✅ HOTOVO | historie konverzace v kontextu | 036 |
| P1.05 | Autonomní plánování | 🟡 ČÁSTEČNĚ | Režim Agent + update_plan | 001, 198 |
| P1.06 | Self-correction | 🟡 ČÁSTEČNĚ | agent vidí chyby nástrojů a zkouší jinak; ověření misí | 210 |
| P1.07 | Reasoning mode | 🟡 ČÁSTEČNĚ | Režim Agent (až 25 kroků) | 001 |
| P1.08 | Multi-agent systém | 🗓️ PLÁNOVÁNO | dnes jeden agent + Claude Code; Agent Swarm = M3 | 061-070 |
| P1.09 | Učení z oprav a zpětné vazby | 🟡 ČÁSTEČNĚ | fakta se dají opravit; učení z oprav chybí | 039 |
| P1.10 | Offline fallback | 🟡 ČÁSTEČNĚ | místní modely (Ollama) jako fallback, offline režim | 270, 597 |
| P2.01 | Spouštět, zavírat a přepínat aplikace | ✅ HOTOVO | open_app, close_app, window_control | 026 |
| P2.02 | Klikat, psát, scrollovat, klávesnice i myš | ✅ HOTOVO | mouse, type_text, press_keys, computer_use, ui_click | 522 |
| P2.03 | Číst obrazovku a rozpoznávat prvky | ✅ HOTOVO | ui_inspect/ui_read (UI Automation) + screenshot | 274 |
| P2.04 | Více monitorů | 🟡 ČÁSTEČNĚ | notch/HUD/okna na monitoru s kurzorem | 238 |
| P2.05 | Instalovat a odinstalovávat software | 🔌 VYŽADUJE_INTEGRACI | přes run_shell (winget) jen se schválením | — |
| P2.06 | Procesy, služby, aplikace při spuštění | 🟡 ČÁSTEČNĚ | top_processes, close_app; služby a autostart jen čtení v reportu | 016, 305 |
| P2.07 | Diagnostika RAM, CPU, GPU, SSD, HDD | 🟡 ČÁSTEČNĚ | report: CPU, RAM, disky; GPU název a ovladač | 025 |
| P2.08 | SMART, stav disků, systémové logy | 🟡 ČÁSTEČNĚ | Get-PhysicalDisk zdraví + chyby systémového logu (pcreport.py) | 012, 018 |
| P2.09 | Příčiny zamrzání a zpomalení | 🟡 ČÁSTEČNĚ | report: zatížení, paměť, autostart, chyby, neočekávaná vypnutí | 025 |
| P2.10 | Upravovat systémová nastavení | 🟡 ČÁSTEČNĚ | tmavý režim, hlasitost, napájení; další přes PowerShell se schválením | — |
| P2.11 | Organizovat soubory a stažené soubory | ✅ HOTOVO | find_file, move_files, copy_file, list_folder, storage_report | 511 |
| P2.12 | Automatizovat opakované úkoly | ✅ HOTOVO | protokoly, automatizace, plánovač | 147, 155 |
| P2.13 | PowerShell, CMD, Windows Terminal | ✅ HOTOVO | run_shell (PowerShell) vždy s potvrzením | — |
| P2.14 | Zálohy a obnova | 🟡 ČÁSTEČNĚ | záchytné body souborů; zálohy systému chybí | 328 |
| P3.01 | Aktivace hlasem | ✅ HOTOVO | aktivační slovo (voice.wake_word) | 098 |
| P3.02 | Přirozená konverzace | ✅ HOTOVO | čeština a další jazyky | — |
| P3.03 | Real-time hlasový rozhovor | 🟡 ČÁSTEČNĚ | hlasový režim; latence podle poskytovatele | — |
| P3.04 | Přerušit JARVISe během mluvení | ✅ HOTOVO | přerušení mluvení (STOP, nová věta) | 176 |
| P3.05 | Rozpoznávání mluvčích | ⬜ CHYBÍ | — | 267 |
| P3.06 | Nastavitelný hlas a osobnost | ✅ HOTOVO | hlas, rychlost, osobnost, oslovení | 101 |
| P3.07 | Šeptání a tichý režim | 🟡 ČÁSTEČNĚ | speak_mode never/tichý režim | — |
| P3.08 | Přepis mluveného slova | ✅ HOTOVO | diktování + přepis nahrávek | 097 |
| P3.09 | Překlady během konverzace | 🟡 ČÁSTEČNĚ | překlad přes AI | 269 |
| P3.10 | Čtení zpráv a dokumentů | ✅ HOTOVO | čte e-maily, zprávy z telefonu, brífink | 555 |
| P3.11 | Offline STT a TTS | 🟡 ČÁSTEČNĚ | místní modely volitelně, stahování jen s potvrzením | 270 |
| P3.12 | Detekce emocí v hlase | ⬜ CHYBÍ | — | — |
| P4.01 | Analýza screenshotů | ✅ HOTOVO | screenshot + vision model | 280 |
| P4.02 | Rozpoznávání textu, ikon, tlačítek, oken | ✅ HOTOVO | UI Automation + vision | 274 |
| P4.03 | Porozumění chybovým hláškám | 🟡 ČÁSTEČNĚ | vision + ui_read | 033 |
| P4.04 | Navigace v aplikacích podle obrazu | ✅ HOTOVO | computer_use | — |
| P4.05 | Pomoc v reálném čase | 🟡 ČÁSTEČNĚ | označený text, kontext aktivní aplikace | 027 |
| P4.06 | Analýza obrázků, grafů a dokumentů | ✅ HOTOVO | přílohy obrázků a dokumentů | 276-278 |
| P4.07 | Volitelný přístup ke kameře | ⬜ CHYBÍ | — | 188 |
| P4.08 | Rozpoznávání objektů kamerou telefonu | ⬜ CHYBÍ | — | 413 |
| P4.09 | Vizuální porovnání před a po | ⬜ CHYBÍ | — | 059 |
| P5.01 | Integrace s Claude Code CLI | ✅ HOTOVO | Claude Code v notchi, schvalování z PC i telefonu (claude_bridge.py) | 046 |
| P5.02 | Generování celých aplikací | 🟡 ČÁSTEČNĚ | make_website + Claude Code | 352 |
| P5.03 | Frontend, backend, databáze, API | 🔌 VYŽADUJE_INTEGRACI | přes Claude Code | — |
| P5.04 | Webové a mobilní aplikace | 🟡 ČÁSTEČNĚ | weby s náhledem; mobilní aplikace přes Claude Code | — |
| P5.05 | Čtení a úpravy kódu | ✅ HOTOVO | read_text_file, write_text_file, Claude Code | — |
| P5.06 | Hledání a oprava bugů | 🔌 VYŽADUJE_INTEGRACI | Claude Code | 340 |
| P5.07 | Refactoring | 🔌 VYŽADUJE_INTEGRACI | Claude Code | 332 |
| P5.08 | Testy a kontrola výsledků | ✅ HOTOVO | run_tests | 058 |
| P5.09 | Git a GitHub | ✅ HOTOVO | git_status/diff/log/commit/push | — |
| P5.10 | Pull requesty | 🔌 VYŽADUJE_INTEGRACI | Claude Code / MCP GitHub | 049 |
| P5.11 | Vývojové servery | 🟡 ČÁSTEČNĚ | run_shell se schválením | — |
| P5.12 | Terminál, Docker, databáze | 🟡 ČÁSTEČNĚ | run_shell, run_python | — |
| P5.13 | Dokumentace projektů | 🔌 VYŽADUJE_INTEGRACI | Claude Code | 066 |
| P5.14 | Bezpečnostní kontrola kódu | 🔌 VYŽADUJE_INTEGRACI | Claude Code | 401 |
| P5.15 | Sestavení EXE a APK | 🟡 ČÁSTEČNĚ | vlastní CI JARVISe | 060 |
| P6.01 | Planner Agent – plánuje a řídí ostatní | 🗓️ PLÁNOVÁNO | M3 | 061 |
| P6.02 | Coding Agent | 🔌 VYŽADUJE_INTEGRACI | Claude Code | — |
| P6.03 | Research Agent | 🟡 ČÁSTEČNĚ | web_search/web_read | 003 |
| P6.04 | System Agent | 🟡 ČÁSTEČNĚ | strážce + pc_health_report | 025 |
| P6.05 | Design Agent | 🟡 ČÁSTEČNĚ | make_website | — |
| P6.06 | File Agent | 🟡 ČÁSTEČNĚ | souborové nástroje | — |
| P6.07 | Security Agent | 🟡 ČÁSTEČNĚ | oprávnění, potvrzení, STOP | 176-185 |
| P6.08 | Automation Agent | ✅ HOTOVO | automatizace + plánovač | 147, 155 |
| P7.01 | Spí, když dlouho nic neděláš | ✅ HOTOVO | spánek při nečinnosti (mood.py) | 249 |
| P7.02 | Tančí při hudbě (podle rytmu) | 🟡 ČÁSTEČNĚ | tančí, když hraje hudba; bez rytmu | 244 |
| P7.03 | Přemýšlí při generování odpovědi | ✅ HOTOVO | nálada thinking/working | 241 |
| P7.04 | Oslavuje dokončené úkoly | ✅ HOTOVO | radost po úspěchu a ověřené misi | 076, 745 |
| P7.05 | Reaguje na kurzor a kliknutí | ✅ HOTOVO | oči sledují kurzor, reakce na klik | 071, 246 |
| P7.06 | Zlobí se/je smutný při chybě | ✅ HOTOVO | nálada chyba | 744 |
| P7.07 | Reaguje na vyčerpání limitu AI | ✅ HOTOVO | nálada limit | 748 |
| P7.08 | Desítky animací a výrazů | 🟡 ČÁSTEČNĚ | nálady, výrazy, doplňky | 241-253 |
| P7.09 | Vlastní zvukové reakce | ✅ HOTOVO | vlastní zvuky | 252 |
| P7.10 | Krátké interaktivní bubliny | 🟡 ČÁSTEČNĚ | bubliny/oznámení v notchi | — |
| P7.11 | Minimalisticky, bez přeplácání | ✅ HOTOVO | minimalistický notch | — |
| P8.01 | Malý černý notch | ✅ HOTOVO | notch nahoře uprostřed (desktop/host.py) | 233 |
| P8.02 | Plynulé rozšiřování | ✅ HOTOVO | rozbalení při najetí/kliknutí | — |
| P8.03 | Kompaktní režim a velký panel | ✅ HOTOVO | notch + celý chat + dashboard | 086 |
| P8.04 | Liquid Glass, blur, průhlednost | ✅ HOTOVO | průhlednost s plynulými okraji (per-pixel alpha) | 350 |
| P8.05 | Plynulé animace | ✅ HOTOVO | animace, test FPS | — |
| P8.06 | Ovládání hlasem i textem | ✅ HOTOVO | hlas i text | — |
| P8.07 | Hudební vizualizér a přehrávání | 🟡 ČÁSTEČNĚ | ovládání přehrávání; vizualizér chybí | — |
| P8.08 | Indikátory CPU, RAM, baterie, připojení | ✅ HOTOVO | dlaždice CPU/RAM/baterie/síť | — |
| P8.09 | Aktuální AI úkoly | ✅ HOTOVO | karta úkolu v notchi | 763 |
| P8.10 | Mini notifikace | ✅ HOTOVO | oznámení v notchi | — |
| P8.11 | Vlastní témata a nastavení | ✅ HOTOVO | Vzhled: témata, barvy, animace | — |
| P8.12 | Adaptivní rozhraní | ✅ HOTOVO | DPI per-monitor v2, 100–300 % | — |
| P9.01 | Synchronizace konverzací, paměti a úkolů | 🟡 ČÁSTEČNĚ | jeden server na PC; telefon je klient (sdílená historie) | — |
| P9.02 | Telefon jako ovladač počítače | ✅ HOTOVO | mobil → Ovládání | 139 |
| P9.03 | Posílání souborů | ✅ HOTOVO | send_file, přílohy | — |
| P9.04 | Push notifikace | ✅ HOTOVO | oznámení na telefon | 412 |
| P9.05 | Pokračování na jiném zařízení | 🟡 ČÁSTEČNĚ | stejná konverzace na PC i mobilu | 083 |
| P9.06 | Hlasové příkazy z telefonu | ✅ HOTOVO | push-to-talk z mobilu | 141 |
| P9.07 | Fotografie a soubory se souhlasem | 🟡 ČÁSTEČNĚ | přílohy se souhlasem systému | 142 |
| P9.08 | Sdílení obrazovky | ⬜ CHYBÍ | — | — |
| P9.09 | Více počítačů | ⬜ CHYBÍ | — | — |
| P9.10 | Bezpečný vzdálený přístup | 🟡 ČÁSTEČNĚ | Tailscale/LAN + token; bez vlastního relay | 407 |
| P10.01 | Připomínky, budíky, časované úkoly | ✅ HOTOVO | časovače, připomínky, rutiny, JARVIS zavolá | 155 |
| P10.02 | Pravidelné kontroly PC | ✅ HOTOVO | strážce + report | 508 |
| P10.03 | Kontrola dokončení stahování a instalací | ⬜ CHYBÍ | — | — |
| P10.04 | Automatické zálohování | ⬜ CHYBÍ | — | 330 |
| P10.05 | Sledování běžících projektů | 🟡 ČÁSTEČNĚ | stav misí a Claude Code relací | — |
| P10.06 | Upozornění na důležité zprávy | ✅ HOTOVO | nové e-maily, VIP, zprávy z telefonu | 542 |
| P10.07 | Ranní a večerní přehled | 🟡 ČÁSTEČNĚ | ranní brífink; večerní přehled chybí | 510 |
| P10.08 | Spouštění vlastních workflow | ✅ HOTOVO | automatizace a protokoly | 147 |
| P10.09 | Podmíněné akce | ✅ HOTOVO | automatizace Když → tak | 147 |
| P10.10 | Plánovač autonomních agentů | 🗓️ PLÁNOVÁNO | M3 | 155 |
| P11.01 | Vyhledávání a ověřování zdrojů | 🟡 ČÁSTEČNĚ | web_search/web_read | 003 |
| P11.02 | Ovládání prohlížeče | ✅ HOTOVO | browser_* | 526 |
| P11.03 | Vyplňování formulářů | 🟡 ČÁSTEČNĚ | browser_type, computer_use | 530 |
| P11.04 | Shrnování článků a dokumentů | ✅ HOTOVO | read_website, přílohy | — |
| P11.05 | Správa e-mailů | ✅ HOTOVO | IMAP/SMTP: Gmail, Seznam, … (mail.py) | 541 |
| P11.06 | Psaní a odesílání e-mailů | ✅ HOTOVO | email_send/reply vždy po schválení | 554 |
| P11.07 | Google Calendar a schůzky | 🟡 ČÁSTEČNĚ | vlastní kalendář + čtení ICS; zápis do Google kalendáře chybí | 565 |
| P11.08 | Google Drive | 🔌 VYŽADUJE_INTEGRACI | MCP server Google Drive | — |
| P11.09 | Překlady a texty | ✅ HOTOVO | AI, označený text | 547, 548 |
| P11.10 | Prezentace, PDF, tabulky | 🟡 ČÁSTEČNĚ | weby; PDF/tabulky přes run_python | — |
| P11.11 | Hledání v osobních souborech | 🟡 ČÁSTEČNĚ | find_file podle názvu | 316 |
| P11.12 | Organizace úkolů a projektů | 🟡 ČÁSTEČNĚ | seznamy, kalendář, úkoly | 785 |
| P12.01 | Ovládání hudby | ✅ HOTOVO | media_control, YouTube | — |
| P12.02 | Hudební vizualizace v notchi | ⬜ CHYBÍ | — | — |
| P12.03 | Animace postavičky podle hudby | 🟡 ČÁSTEČNĚ | tanec při hudbě | 244 |
| P12.04 | Game Mode | 🟡 ČÁSTEČNĚ | Herní režim (protokol) + automatizace při otevření hry | 034 |
| P12.05 | Monitoring FPS, CPU, GPU, teplot | 🟡 ČÁSTEČNĚ | CPU/RAM/GPU; FPS a teploty chybí | 125, 297 |
| P12.06 | Detekce spuštěné hry | ✅ HOTOVO | automatizace app_open | 148 |
| P12.07 | Pomoc s herními nastaveními | ⬜ CHYBÍ | — | — |
| P12.08 | Správa screenshotů a klipů | ⬜ CHYBÍ | — | — |
| P12.09 | Spouštění her a launcherů | ✅ HOTOVO | open_app | — |
| P13.01 | Světla a zásuvky | ✅ HOTOVO | home_control (home.py) | 423 |
| P13.02 | Integrace s Home Assistantem | ✅ HOTOVO | Home Assistant REST | 434 |
| P13.03 | Televize a reproduktory | 🟡 ČÁSTEČNĚ | media_player přes HA | 429 |
| P13.04 | Bluetooth zařízení | ⬜ CHYBÍ | — | — |
| P13.05 | MQTT | 🔌 VYŽADUJE_INTEGRACI | přes Home Assistant (MQTT integrace HA) | — |
| P13.06 | Automatizace domácnosti | ✅ HOTOVO | automatizace + scény | 432 |
| P13.07 | Ovládání z telefonu | ✅ HOTOVO | dlaždice v mobilu (Domov) | — |
| P13.08 | Přehled senzorů a spotřeby | 🟡 ČÁSTEČNĚ | senzory teploty/vlhkosti; spotřeba chybí | 422 |
| P14.01 | Oprávnění pro každého agenta | 🟡 ČÁSTEČNĚ | oprávnění podle oblastí (permissions.py); per agent v M3 | 180 |
| P14.02 | Potvrzování mazání a rizik | ✅ HOTOVO | delete_file vždy s potvrzením | 182 |
| P14.03 | Historie operací | ✅ HOTOVO | audit akcí v misích | 232 |
| P14.04 | Zastavit běžícího agenta | ✅ HOTOVO | Pozastavit / Zrušit / STOP | 176 |
| P14.05 | Náhled změn | 🟡 ČÁSTEČNĚ | detaily v potvrzovacím dialogu | 231 |
| P14.06 | Vrácení změn | 🟡 ČÁSTEČNĚ | záchytné body souborů, verze dovedností, navázání misí | 328, 150 |
| P14.07 | Šifrované citlivé údaje | ✅ HOTOVO | trezor Windows (keyring) | — |
| P14.08 | Správa API klíčů | ✅ HOTOVO | klíče jen v keyringu, redakce v logu | 179 |
| P14.09 | Lokální databáze paměti | ✅ HOTOVO | SQLite v %APPDATA% | — |
| P14.10 | Mazání osobních dat | ✅ HOTOVO | mazání po N dnech, úplné smazání, export (privacy.py) | 684, 794 |
| P14.11 | Ochrana před škodlivými instrukcemi | ✅ HOTOVO | skener skrytých pokynů + cizí data označená jako data (injection.py) | 183 |
| P14.12 | Omezené prostředí pro kód | 🟡 ČÁSTEČNĚ | skilly se schvalují; sandbox chybí | 686 |
| P14.13 | Indikace mikrofonu/kamery/obrazovky | ✅ HOTOVO | stav naslouchání v notchi + záznam mikrofonu; kamera se nepoužívá | 679 |
| P15.01 | Teach Mode | 🟡 ČÁSTEČNĚ | dovednost z provedené mise (Skill Forge) | 146 |
| P15.02 | Self-Healing | 🗓️ PLÁNOVÁNO | M7 – Controlled Self-Evolution | — |
| P15.03 | Computer Memory | ⬜ CHYBÍ | — | 030 |
| P15.04 | Predictive Assistant | ⬜ CHYBÍ | — | 496 |
| P15.05 | Agent Marketplace | 🟡 ČÁSTEČNĚ | MCP servery, schvalované skilly | 600 |
| P15.06 | Universal Command Bar | ✅ HOTOVO | příkazová paleta + notch + hlas | 757 |
| P15.07 | Personal Knowledge Graph | ⬜ CHYBÍ | — | — |
| P15.08 | Cross-device Handoff | 🟡 ČÁSTEČNĚ | stejná konverzace na telefonu i PC | 083 |
| P15.09 | AI Skill Builder | 🟡 ČÁSTEČNĚ | Skill Forge (složené dovednosti) + skilly se schválením | — |
| P15.10 | Adaptive Resource Manager | ⬜ CHYBÍ | — | 583 |
