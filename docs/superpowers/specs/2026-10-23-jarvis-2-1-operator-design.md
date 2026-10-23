# JARVIS 2.1: operátor Windows, režim Agent, správce lokální AI (spec)

Datum: 2026-10-23
Stav: ke schválení
Navazuje na: `2026-10-23-jarvis-design.md` (jádro) a `2026-10-23-jarvis-character-design.md` (postavička, notch, mazlíček).
Zdroj požadavků: dlouhý prompt uživatele „PROJECT JARVIS — ULTIMATE PERSONAL AI OPERATING ASSISTANT“ (sekce 1–20).

## 1. Cíl

Všechno, co JARVIS 2.0 umí, zůstává beze změny (notch, postavička 1:1 podle předlohy, hlas, chat, přílohy, OmniRoute/Ollama,
paměť, ~60 nástrojů, telefon, mazlíček, instalátor, aktualizace). Verze 2.1 doplní to, co z promptu chybí:

1. skutečné ovládání oken přes Windows UI Automation (strom přístupnosti) + plné ovládání myši,
2. režim Agent: plán → kroky → průběh, pauza/pokračovat/zrušit/zopakovat, náhled před změnami, nouzové STOP, historie úkolů,
3. správce lokální AI: detekce HW, doporučené modely s velikostí, stahování jen se souhlasem, výkonové režimy, uvolňování, test GPU,
4. pomocník pro programování: git (stav, diff, historie, commit, push, záchytné body), porovnání souborů, testy, Claude Code,
5. chat a paměť: úprava zprávy, přejmenování, složky, hledání v nastavení, export/import paměti, hlasový režim,
6. notch, zvuky, výkon: trvalé připnutí, kontrolka snímání obrazovky, zvuky rozhraní, výběr reproduktoru, angličtina,
   úsporná animace, diagnostika, rozšířený systémový přehled, rádce výkonu, asistent schránky,
7. oprávnění a skilly: kategorie oprávnění, které jde kdykoli odebrat; manifest skillů s oprávněními a časovým limitem.

### Co řekl uživatel
- „to co je tak nech tak jak to je, akorát přidej to, co je v promptu, aby to bylo ještě lepší“.
- Schválil návrh v chatu (body 1–6 + skilly) a sepsání specu.
- Hardware: Windows 11, 32 GB RAM, AMD Radeon RX 6600, SSD. Dříve měl problémy se zpomalováním PC.

### Rozhodnutí o technologii
Zůstává současný stack (Python jádro + FastAPI/WebSocket, webové UI Vite + TypeScript, pywebview/WebView2, PyInstaller + Inno Setup).
Prompt preferuje Tauri 2, ale dovoluje jinou volbu s odůvodněním: stack je hotový, otestovaný v CI a uživatel chce zachovat,
co funguje. Přepis by nic nepřidal a zabral by týdny. Postavička zůstává 2.5D (SVG + kód), protože odpovídá schválené předloze
a v klidu je výrazně levnější než WebGL.

### Kritéria úspěchu
1. „Jarvisi, otevři Kalkulačku a spočítej 12×7“ → JARVIS najde tlačítka podle názvu (UIA), klikne, přečte výsledek a ověří ho.
2. „Najdi PDF ve Stažených, roztřiď je podle data a udělej přehled“ → panel Úkoly ukáže plán, pak náhled přesunů,
   čeká na schválení, provede, ověří a shrne. Pauza/zrušit/STOP fungují uprostřed úkolu.
3. Nastavení → Mozek → Lokální AI ukáže RAM/GPU, doporučené modely s velikostí v GB; nic se nestáhne bez kliknutí.
   „Otestovat GPU“ řekne pravdivě, jestli model běží na GPU, nebo jen na procesoru.
4. „Udělej záchytný bod a uprav soubor X“ → změna jde vrátit jedním příkazem; git historie projektu zůstane nedotčená.
5. Zprávu v chatu jde upravit a poslat znovu; konverzace jde přejmenovat a dát do složky; paměť jde exportovat a importovat.
6. V klidu (notch zavřený, wake word vypnutý, bez lokálního modelu) bere JARVIS < 2 % jednoho jádra a < 400 MB RAM.
   Měření dělá `--bench`; čísla se reportují tak, jak vyjdou.
7. Každou kategorii oprávnění jde vypnout a nástroje z ní okamžitě zmizí.

## 2. Oprávnění (`core/jarvis/permissions.py`)

Kategorie (Nastavení → **Oprávnění**, nová stránka; config `permissions: dict[str, bool]`):

| Klíč | Co povoluje | Výchozí |
|---|---|---|
| `apps` | spouštět/zavírat aplikace, okna | zapnuto |
| `input` | myš, klávesnice, UI Automation, `computer_use` | zapnuto |
| `screen` | snímky obrazovky, čtení obrazovky | zapnuto |
| `files_read` | číst soubory a složky | zapnuto |
| `files_write` | vytvářet/přesouvat/mazat soubory | zapnuto (mazání vždy s potvrzením) |
| `shell` | PowerShell, Python, testy, Claude Code | zapnuto (vždy s potvrzením) |
| `network` | web, prohlížeč, stahování | zapnuto |
| `system` | napájení, nastavení Windows | zapnuto (napájení s potvrzením) |

- Každý `@tool` dostane parametr `perm: str` (výchozí podle modulu). Nově přidané nástroje ho musí mít.
- `tools.schemas()` vynechá nástroje z vypnutých kategorií. `tools.call()` je odmítne, i kdyby je model zavolal,
  s hláškou „Oprávnění X je vypnuté“.
- Stávající `tools.computer_use: bool` se převede na `permissions.input`; starý config se migruje.
- Změna se projeví okamžitě, bez restartu.

## 3. Ovládání Windows přes UI Automation

### 3.1 Platformní vrstva
- Nová závislost (jen Windows): `uiautomation` (MIT, čistý Python nad COM).
- `tools/platform/base.py` dostane metody:
  - `ui_tree(window: str = "", depth: int = 4, limit: int = 150) -> list[UiNode]`
  - `ui_find(window, name="", role="", automation_id="", timeout=0) -> UiNode | None`
  - `ui_act(node_ref, action: "invoke"|"click"|"double"|"right"|"focus"|"expand"|"toggle"|"select") -> str`
  - `ui_set_text(node_ref, text) -> None`
  - `ui_read(window, limit=4000) -> str`
  - `drag(x1, y1, x2, y2)`
- `UiNode = {ref, role, name, automation_id, value, enabled, rect:[x,y,w,h], children?}`. `ref` je krátké ID
  (`w3:17`), platné do dalšího `ui_tree` na stejné okno; implementace drží mapu ref → element.
- `NullPlatform` vrací deterministický falešný strom (pro testy).
- Okno se cílí podle části titulku; prázdné = okno v popředí.
- JARVIS nikdy nekliká do vlastních oken (titulek začíná „JARVIS“).

### 3.2 Nástroje (`tools/uia.py`, perm `input`, čtení perm `screen`)
- `ui_inspect(window="", depth=4)` → zploštělý seznam ovládacích prvků (role, název, ref, povoleno).
  Pro LLM se zkrátí na 150 prvků.
- `ui_click(target, window="", action="invoke")`. `target` = ref nebo název. Nejdřív zkusí UIA vzor (Invoke/Toggle/Select),
  až potom klik myší do středu prvku. Vrací ověření: zda prvek ještě existuje, nový titulek okna a prvek s fokusem.
- `ui_type(target, text, window="", submit=false)` → ValuePattern, jinak fokus + psaní. Ověření: přečte hodnotu zpět.
- `ui_wait(name, window="", timeout=10)` → čeká na objevení prvku.
- `ui_read(window="")` → viditelný text okna.
- `mouse(action: click|double|right|scroll|drag|move, x, y, x2=None, y2=None, amount=0)` → perm `input`.
- Nebezpečnost: `ui_click`/`ui_type` nejsou samy o sobě nebezpečné. Pokud název cíle nebo titulek okna obsahuje
  „smazat / odstranit / delete / odeslat / send / koupit / buy / zaplatit / pay / instalovat / install / formátovat“
  (`danger_if`), vyžadují potvrzení.

### 3.3 `computer_use`
Na začátku každého kroku přidá do promptu zkrácený UIA strom okna v popředí a preferuje akce `ui_*`. Na souřadnice
ze snímku obrazovky sáhne, jen když strom prvek neobsahuje (hry, plátna) nebo UIA selže.

### 3.4 Indikace
Každé pořízení snímku obrazovky (screenshot, computer_use, vision) publikuje `screen_capture {active: true/false}`.
Notch pak ukáže červenou tečku a „Vidím obrazovku“ (viz §8).

## 4. Režim Agent a Úkoly (`core/jarvis/tasks.py`)

### 4.1 Data (SQLite, odděleně od paměti)
```
tasks(id TEXT PK, conv_id TEXT, goal TEXT, status TEXT, created REAL, finished REAL, summary TEXT)
task_steps(task_id TEXT, idx INT, title TEXT, status TEXT, note TEXT)
task_actions(id INTEGER PK, task_id TEXT, ts REAL, tool TEXT, args TEXT, ok INT, summary TEXT, ms INT)
```
- `status` úkolu: `running | paused | waiting | done | failed | cancelled`.
- `status` kroku: `pending | running | done | failed | skipped`.
- `args` se ukládá **po redakci** (§9.2) a zkráceně na 500 znaků.

### 4.2 Životní cyklus
- `Agent._handle` založí úkol při prvním volání nástroje v dané odpovědi; čistě textová odpověď úkol nevytváří.
  Každé volání nástroje = řádek v `task_actions`.
- Nový nástroj `update_plan(steps: list[str], current: int = 0, note: str = "")`. Model ho volá na začátku vícekrokového
  úkolu a pak při každém posunu; kroky před `current` jsou hotové. Nástroj je vždy povolený a neprovádí žádnou akci.
- Konec úkolu:
  - úspěšný konec → zbývající kroky `done`, `summary` = první věta odpovědi,
  - výjimka/chyba → `failed`,
  - STOP/zrušení → `cancelled`.
- **Pauza:** `TaskManager.pause()` nastaví `asyncio.Event`. Agent na něj čeká před každým voláním nástroje a před
  dalším kolem LLM; probíhající nástroj doběhne. `resume()` ho uvolní.
- **Zrušit** = stávající `Agent.stop()`.
- **Zopakovat** = nová zpráva „Zopakuj úkol: <goal>“ ve stejné konverzaci.
- **Režim Agent** (`agent.mode: bool`, výchozí vypnuto; přepínač v notch panelu a v Úkolech):
  - zapnuto: `MAX_ROUNDS = 25` a prompt doplní „nejdřív zavolej update_plan, pak pracuj krok po kroku, na konci ověř výsledek“,
  - vypnuto: chování jako teď (8 kol).

### 4.3 Náhled před změnami
- `confirm_request` dostane volitelné pole `details: list[str]` (max 50 řádků + „…a dalších N“). Dialogy v notchi,
  dashboardu i na mobilu ho zobrazí jako rolovací seznam.
- Nový nástroj `move_files(moves: list[{src, dst}], create_dirs=true)` (perm `files_write`, vždy nebezpečný).
  Před potvrzením ukáže všechny přesuny. Po provedení ověří existenci cílů a vrátí `{moved, failed}`.
- Stávající `delete_file`, `move_file`, `copy_file` dostanou `details` s cestami a velikostí.

### 4.4 Nouzové STOP
- Zpráva WS `stop_all`, globální zkratka `hotkeys.stop_all = "ctrl+alt+x"` (stávající Esc zůstává) a tlačítko STOP.
- Co STOP udělá:
  1. zruší agenta a `computer_use`,
  2. zastaví TTS a nahrávání,
  3. uvolní stisknuté klávesy a tlačítka myši (`keyboard.release` / `mouseUp`),
  4. pozastaví plánované úlohy na 10 minut,
  5. publikuje `stopped`.
- Tlačítko STOP je v notchi (lišta a živá bublina, když `agent.busy`), v hlavičce dashboardu, na stránce Úkoly a na mobilu.

### 4.5 UI
- **Dashboard → Úkoly** (`#tasks`, nová položka menu): karta aktuálního úkolu. Obsahuje:
  - cíl,
  - kroky s ikonami stavu,
  - průběh `hotovo/celkem`,
  - aktuální akci (poslední `tool_start`),
  - čekající schválení s tlačítky Povolit/Zamítnout,
  - chyby,
  - tlačítka Pozastavit/Pokračovat/Zrušit/Zopakovat/STOP.

  Pod kartou je historie úkolů (hledání, filtr podle stavu, detail s akcemi) a tlačítko „Smazat historii“.
- **Notch:** v živé bublině řádek „Krok 2/5 · Hledám soubory“ + mini STOP. Postavička je v náladě `working` s `progress = hotovo/celkem`.
- **Mobil:** stejná karta aktuálního úkolu nad chatem.
- **WS:**
  - ze serveru: `task_update {task}` (celý stav úkolu, max 4× za sekundu),
  - z klienta: `tasks_get {limit, q}`, `task_get {id}`, `task_pause`, `task_resume`, `task_cancel`, `task_retry {id}`, `tasks_clear`.

## 5. Správce lokální AI (`core/jarvis/llm/local.py`)

### 5.1 Hardware
`detect_hardware()`:
- RAM a počet jader přes `psutil`,
- GPU (název, VRAM) přes PowerShell `Get-CimInstance Win32_VideoController`.

Výsledek se uloží do cache na 1 hodinu.

### 5.2 Katalog
Statický seznam `MODELS` s polem `{name, label, size_gb, min_ram_gb, vision: bool, note}`. Velikosti podle oficiální
knihovny Ollamy v době psaní:

| Model | Velikost (GB) | Vision | Pro koho |
|---|---|---|---|
| `qwen2.5:3b` | 1,9 | ne | výchozí |
| `llama3.2:3b` | 2,0 | ne | |
| `gemma3:4b` | 3,3 | ano | |
| `qwen2.5:7b` | 4,7 | ne | |
| `llama3.1:8b` | 4,9 | ne | |
| `qwen2.5vl:7b` | 6,0 | ano | |
| `qwen2.5-coder:7b` | 4,7 | ne | programování |

- Doporučení podle RAM: méně než 16 GB → 3–4B modely; 32 GB → až 7–8B.
- U každého modelu se ukáže velikost, aktuálně volné místo na disku a jestli je nainstalovaný (`/api/tags`, skutečná velikost).

### 5.3 Operace (WS, jen z dashboardu po kliknutí)
- `local_status` vrací:
  - verzi Ollamy (`/api/version`) nebo „neběží“,
  - nainstalované modely,
  - načtené modely (`/api/ps`) včetně `size_vram`.
- `local_pull {name}` stahuje se streamovaným průběhem `local_pull_progress {name, completed, total}`. Stažení jde zrušit.
- `local_delete {name}` maže s potvrzením v UI.
- `local_unload` volá generate s `keep_alive: 0`.
- `local_gpu_test` spustí krátké generování a pak přečte `/api/ps`:
  - `size_vram > 0` → „Model běží na GPU (x GB ve VRAM)“,
  - jinak → „Model běží jen na procesoru“, s poznámkou, že RX 6600 nemusí mít v Ollamě akceleraci a JARVIS tím pádem jede na CPU.

  Výsledek se uloží do `brain.local_gpu`.

### 5.4 Žádné tiché stahování
`bootstrap.ensure_ollama_model` přestane stahovat. Když model chybí, publikuje `local_model_missing {name, size_gb}`.
Dashboard i notch pak ukážou kartu „Pro offline režim stáhni qwen2.5:3b (1,9 GB)“ s tlačítkem.

### 5.5 Výkonové režimy (`brain.local_mode`)
Hodnoty se předávají Ollamě v `options` / `keep_alive`.

| Režim | `num_ctx` | `num_thread` | `keep_alive` |
|---|---|---|---|
| úsporný | 2048 | max(2, jádra/4) | 1 min |
| vyvážený (výchozí) | 4096 | jádra/2 | 5 min |
| výkon | 8192 | jádra−1 | 30 min |

### 5.6 Vypnutí lokální AI
`brain.local_enabled: bool` (výchozí zapnuto). Vypnutí:
- vyřadí lokální poskytovatele (Ollama, LM Studio) z řetězu,
- jednou zavolá `local_unload`,
- bootstrap Ollamu nespouští.

Notch a všechno ostatní běží dál.

### 5.7 Lokální vs. cloud
- Každý poskytovatel v Nastavení → Mozek má štítek „Lokální“ / „Cloud“ podle `PRESETS[..].local`.
- Štítek u odpovědi v chatu (už ukazuje poskytovatele) dostane ikonu cpu/cloud.
- `brain.offline_only` zůstává.
- V UI je text: „Předplatné Claude Code nedává API klíč; Claude jako mozek potřebuje klíč z console.anthropic.com.“
- Klíče se dál ukládají do Windows Credential Manageru (`secrets.py`, beze změny).

## 6. Pomocník pro programování (`tools/dev.py`)

- **Projekty** = `tools.allowed_folders` (Nastavení → Nástroje → Povolené složky).
  - Mimo povolené složky dev nástroje odmítnou pracovat.
  - Prázdný seznam = povolená jen složka Dokumenty\Projekty a ostatní se musí přidat.
- Git přes `git` z PATH (subprocess, timeout 60 s, `GIT_TERMINAL_PROMPT=0`). Když git chybí, nástroje vrátí ToolResult s návodem, jak ho nainstalovat přes winget.

| Nástroj | Perm | Popis |
|---|---|---|
| `git_status(project)` | files_read | větev, změněné soubory, ahead/behind |
| `git_diff(project, path="", staged=false)` | files_read | diff zkrácený na 12 000 znaků |
| `git_log(project, n=15)` | files_read | historie |
| `git_commit(project, message, add_all=true)` | files_write, nebezpečný | commit |
| `git_push(project)` | network, nebezpečný | push pomocí uživatelových přihlašovacích údajů; žádné ukládání tokenů |
| `checkpoint(project, label="")` | files_write | záchytný bod (viz níže) |
| `checkpoints(project)` | files_read | seznam záchytných bodů |
| `restore_checkpoint(project, id)` | files_write, nebezpečný | návrat k záchytnému bodu (viz níže) |
| `compare_files(a, b)` | files_read | unified diff (difflib) + počty změn; funguje i mimo git |
| `run_tests(project, command="")` | shell, nebezpečný | detekce `pytest` / `npm test` / `cargo test` / `dotnet test`; timeout 10 min, posledních 200 řádků výstupu, `ok` = návratový kód 0 |
| `claude_code(project, task)` | shell, vždy nebezpečný | viz níže |

- **`checkpoint`:**
  - `git stash create` (+ untracked přes dočasný index) → `git update-ref refs/jarvis/checkpoints/<ts> <sha>`,
  - nemění pracovní strom, větev ani historii,
  - mimo git repozitář zkopíruje dotčené soubory do `%APPDATA%\JARVIS\checkpoints\<projekt>\<ts>\`.
- **`restore_checkpoint`:**
  - nejdřív automaticky vytvoří nový záchytný bod aktuálního stavu,
  - pak `git checkout <sha> -- .` (nebo kopie zpět),
  - v `details` ukáže seznam souborů, které se změní.
- **Automatický záchytný bod:** `write_text_file` a `move_files` do povoleného projektu (git repozitáře) ho vytvoří před zápisem, nejvýš jednou za úkol.
- **`claude_code`:**
  - když je `claude` v PATH, spustí `claude -p <task> --output-format json` v adresáři projektu,
  - používá oficiální headless režim a uživatelovo vlastní přihlášení Claude Code, bez jakýchkoli obcházení,
  - timeout 15 min, jde zrušit STOPem,
  - vrátí výsledek a seznam změněných souborů (`git status` před a po),
  - když `claude` chybí: „Claude Code není nainstalovaný – návod: …“.

## 7. Chat a paměť

- **Úprava zprávy:** WS `message_edit {id, text}`.
  1. Smaže zprávu a všechny pozdější v konverzaci (`Memory.truncate_from(id)`).
  2. Uloží novou verzi.
  3. Pustí agenta.

  V UI je u vlastních zpráv ikonka tužky. Úprava je nedostupná, když `agent.busy`.
- **Přejmenování:** `conversation_rename {id, title}`.
- **Složky:**
  - v DB nový sloupec `conversations.folder TEXT DEFAULT ''` (migrace přes `ALTER TABLE`, když sloupec chybí),
  - `conversation_move {id, folder}`,
  - postranní seznam konverzací seskupený podle složky (sbalitelné), „Bez složky“ nahoře,
  - kontextové menu: Přejmenovat / Přesunout do složky / Smazat.
- **Hledání** v konverzacích zůstává (`search`). Výsledek se otevře na dané zprávě.
- **Hledání v nastavení:** pole nad menu nastavení filtruje karty i položky podle textu (bez diakritiky, case-insensitive). Prázdný výsledek ukáže „Nic nenalezeno“.
- **Paměť:**
  - stránka Paměť má dvě záložky: „Trvalá paměť“ (fakta: úprava/mazání už je) a „Historie úkolů“ (odkaz na §4),
  - `memory_export` vrátí JSON `{version, exported, facts, conversations?}`. Konverzace jen při zaškrtnutí, přílohy se neexportují. Stáhne se jako soubor,
  - `memory_import {data, merge: bool}` validuje strukturu, duplicitní fakta přeskočí a vrátí počty,
  - do paměti se nikdy neukládají hesla a obsah obrazovky: `remember` odmítne text, který vypadá jako heslo nebo klíč (§9.2).
- **Hlasový režim** (`#voice` v dashboardu, tlačítko v notch panelu a na mobilu):
  - velká postavička (280 px), pod ní živá vlna (úroveň mikrofonu při poslechu a TTS při mluvení),
  - poslední výměna jako titulky a velké tlačítko mluvit/stop,
  - **navazování** (`voice.followup: bool`, v hlasovém režimu vždy zapnuto): po odpovědi JARVIS 6 s poslouchá bez wake wordu.
    Poslech je viditelně indikovaný. Ukončí ho ticho nebo „díky, to je vše“ / „stop“,
  - mimo hlasový režim se mikrofon zapne jen wake wordem, zkratkou nebo tlačítkem, nikdy potají.

## 8. Notch, zvuky, výkon, desktopové moduly

- **Připnutí:** stávající `pinned` se uloží do `notch.pinned` a přežije restart. Připnutý panel se nezavírá odjetím myši.
- **Kontrolka obrazovky:** při `screen_capture.active` ukáže notch v zavřeném stavu červenou tečku vlevo, v liště čip „Vidím obrazovku“. Tooltip v trayi se změní.
- **Zvuky rozhraní:**
  - `appearance.sounds: bool` (výchozí zapnuto) a `appearance.sound_volume` 0–100 (výchozí 30),
  - `web/src/shared/sounds.ts` syntetizuje krátké tóny přes WebAudio (žádné soubory ani licence): probuzení, začátek poslechu, hotovo, chyba, upozornění,
  - přehrává je jen okno notche (jedno místo, žádné zdvojení).
- **Výběr reproduktoru:**
  - `voice.output_device: str`,
  - TTS přehrávání přes `sounddevice` na zvolené zařízení,
  - WS `audio_devices_get` vrátí vstupy i výstupy,
  - prázdné = výchozí zařízení Windows.
- **Angličtina:**
  - `voice.stt_language` dostane volbu `auto`,
  - Whisper vrátí detekovaný jazyk; když je `en`, agent dostane do systémového promptu „Odpověz anglicky“ a TTS použije `voice.tts_voice_en` (`en-GB-RyanNeural`, Piper záloha `en_GB-alan-medium`),
  - totéž platí, když uživatel anglicky napíše do chatu (detekce jednoduchou heuristikou: podíl anglických stop-slov),
  - UI zůstává česky.
- **Úsporná animace postavičky** (`blob.ts`):
  - když je nálada `idle | closed | sleeping | focus` a 3 s se nehnul kurzor, frame loop běží max 20 fps,
  - při `animations: reduced` max 10 fps,
  - při `document.hidden` stojí (už teď).
- **Výkonové cíle a měření:**
  - `JARVIS.exe --bench [sekundy=30]` spustí jádro bez GUI a hlasu, počká na ustálení a změří CPU % a RAM procesu (`psutil`) a čas startu. Vypíše JSON.
  - CI (Windows job) ho spustí a vypíše výsledek. Selže jen při > 2× cíli (CPU 4 %, RAM 800 MB), aby nebyl flaky.
  - Čísla jsou z CI runneru, ne z uživatelova PC; tak se to také uvede.
- **Diagnostika** (`#diagnostics`):
  - JARVIS: CPU %, RAM, vlákna, podprocesy (Ollama, prohlížeč, Whisper),
  - zpoždění event loopu,
  - posledních 20 časů do prvního tokenu podle poskytovatele,
  - stav hlasu a mikrofonu,
  - konec logu (redigovaný),
  - tlačítko „Exportovat diagnostiku“ (zip logů a configu bez tajemství).
  - Data se počítají jen s otevřenou stránkou, každé 2 s.
- **Systémový přehled** (stávající `system_get` a widget): navíc GPU a síť.
  - GPU: název; vytížení přes `Get-Counter '\GPU Engine(*engtype_3D)\Utilization Percentage'` nejvýš každé 3 s a jen s otevřeným přehledem; když nejde změřit, „n/a“.
  - Disky: obsazenost všech disků.
  - Síť: rychlost ↑/↓ z rozdílu `psutil.net_io_counters`.
- **Rádce výkonu:** nástroj `performance_report()` (perm `system`).
  - Sesbírá top procesy, tlak na paměť, volné místo, počet položek po spuštění (registry Run + složka Po spuštění, jen čtení) a uptime.
  - Vrátí doporučení. Nic sám nemaže ani nevypíná.
  - Dashboard má tlačítko „Proč je PC pomalý?“, které se na to zeptá.
- **Asistent schránky:** rychlé akce v notch panelu a v trayi „Shrň / Přelož / Vysvětli schránku“.
  - Pošlou `quick_action` s obsahem schránky až po kliknutí. Schránka se nikdy nečte automaticky.

## 9. Bezpečnost

### 9.1 Pravidla
- Shell, Python, testy, Claude Code, mazání, instalace, odesílání, napájení a git push vždy s potvrzením. „Důvěryhodné“ může povolit jen uživatel v Nastavení a nikdy ne pro `claude_code` a `delete_file`.
- Potvrzovací dialog vždy ukáže přesný příkaz nebo seznam souborů (`details`).
- Žádné skryté spouštění: autostart je viditelný přepínač (už je), tray ukazuje stav mikrofonu a obrazovky.
- JARVIS neobchází UAC ani bezpečnostní dialogy Windows. Na prvky UAC (secure desktop) UIA stejně nedosáhne, a když na ně narazí, řekne to uživateli.

### 9.2 Redakce (`core/jarvis/redact.py`)
- Funkce `redact(text)` maskuje:
  - API klíče a tokeny (`sk-…`, `ghp_…`, `xox…`, `AIza…`, JWT, dlouhé hex/base64 řetězce u slov key/token/secret/password/heslo),
  - párovací token telefonu.
- Používá se v `task_actions.args`, logovacím filtru a exportu diagnostiky.
- `looks_secret(text)` používá `remember`.

## 10. Skilly: manifest a izolace

- Soubor skillu může (a nové skilly vytvořené přes `create_skill` budou) obsahovat:
  ```python
  SKILL = {"name": "...", "description": "...", "version": "1.0", "permissions": ["network"], "timeout": 30}
  ```
  Bez manifestu = `permissions: []`, `timeout: 30`.
- Skilly z cizích zdrojů (soubor, který nevytvořil `create_skill`) se načtou **vypnuté**. Nastavení → Skilly ukáže kód, oprávnění a tlačítko Povolit.
- Nástroje skillu dostanou `perm` podle manifestu. Volání skillu s oprávněním z vypnuté kategorie se odmítne.
- Spouštění: každé volání nástroje ze skillu běží v podprocesu (`python -m jarvis.skill_runner`).
  - Timeout podle manifestu (max 300 s), jde zrušit STOPem.
  - Pád skillu neshodí JARVISe.
  - `ctx` v podprocesu má jen `http()`, `notify()` a `platform` podle oprávnění.
- **Upozornění v UI:** „Izolace chrání před pádem a zaseknutím, není to bezpečnostní sandbox – povoluj jen kód, kterému rozumíš.“
- MCP (už je) se nemění. Nástroje MCP spadají pod kategorii `network`, pokud server neurčí jinak.

## 11. Testování

- **pytest:**
  - oprávnění (filtrování schémat, odmítnutí volání, migrace `computer_use`),
  - TaskManager (vznik úkolu, `update_plan`, pauza/pokračování přes falešného agenta a falešný router, zrušení, retry, redakce args),
  - `move_files` (náhled `details`, ověření),
  - git nástroje na skutečném gitu v `tmp_path` (checkpoint nemění HEAD ani pracovní strom, restore vrátí obsah a vytvoří zálohu),
  - `compare_files`,
  - local manager s `httpx.MockTransport` (tags/ps/pull progress/delete/GPU test, žádný pull bez explicitního volání),
  - výkonové režimy → options,
  - `message_edit` / rename / složky / migrace DB,
  - export/import paměti,
  - redakce,
  - skill runner (timeout, pád, manifest, vypnuté cizí skilly),
  - UIA nástroje nad `NullPlatform`,
  - detekce angličtiny,
  - `--bench` (běží a vrací JSON).
- **Web:** `tsc --noEmit`, `vite build`, screenshoty nových stránek (Úkoly, Lokální AI, Oprávnění, Diagnostika, Hlasový režim, úprava zprávy, složky) přes demo server s Playwright. Kontrola, že úsporná animace snižuje počet snímků (počítadlo snímků v galerii).
- **CI Windows:**
  - smoke test obou exe (jako teď),
  - `--bench`,
  - `--selftest-uia`: najde okno Průzkumníka nebo plochy a vypíše prvních 10 prvků UIA, aby se ověřilo, že `uiautomation` je v balíčku a funguje. Pokud runner nemá interaktivní plochu, test se označí jako přeskočený a vypíše proč.
- **Co jde ověřit jen u uživatele:** skutečné klikání v jeho aplikacích, GPU akcelerace RX 6600 v Ollamě, výkon na jeho PC. Uživateli se řekne, co ověřeno nebylo.

## 12. Pořadí implementace

1. Oprávnění + redakce + TaskManager + `update_plan` + STOP + `details` v potvrzení.
2. UI Automation + `mouse` + `move_files` + kontrolka obrazovky.
3. Správce lokální AI (+ konec tichého stahování, výkonové režimy, vypnutí).
4. Pomocník pro programování (git, záchytné body, compare, testy, Claude Code).
5. Chat a paměť (úprava, složky, hledání v nastavení, export/import, hlasový režim, navazování, angličtina, reproduktor).
6. Notch/zvuky/úsporná animace/diagnostika/systémový přehled/rádce výkonu/schránka.
7. Skilly (manifest, runner, schvalování).
8. Web stránky a screenshoty, `--bench` a `--selftest-uia` v CI, vydání v2.1 (instalátor + APK).

## 13. Mimo rozsah

- Přepis na Tauri/Rust, iOS aplikace, WebGL/3D postavička (zůstává schválená 2.5D).
- Nákupy a platby (jen s potvrzením přes prohlížeč, žádná vlastní platební logika).
- Kalendářové integrace (Google/Outlook) – JARVIS má vlastní připomínky a úlohy. Kalendář až jako MCP server.
- GitHub API (issues/PR) mimo `git push` – lze přes MCP server GitHubu.
- Lokalizace UI do angličtiny (anglicky JARVIS jen mluví a odpovídá).
- Jakákoli značka nebo vazba na VexelOPS (v kódu žádná není a nebude).
