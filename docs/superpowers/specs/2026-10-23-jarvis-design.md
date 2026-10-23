# JARVIS 2 — návrh (spec)

Datum: 2026-10-23
Stav: ke schválení

## 1. Cíl

Osobní hlasový asistent ve stylu JARVIS pro Windows PC, výrazně lepší než
„Fully Offline JARVIS“ (heynixi) z ukázkového videa, s Android aplikací, přes
kterou jde PC ovládat odkudkoli. Hobby projekt — **vše musí jít provozovat
zdarma**.

### Co řekl uživatel
- JARVIS jako ve videu (pilulka nahoře na obrazovce, hlas, otevře YouTube a
  pustí video), ale „1 000 000× lepší“.
- Na PC i na telefonu, telefon propojený s PC.
- AI mozek: hybrid, primárně **OmniRoute**, podpora dalších API, nemá peníze.
- Telefon má PC ovládat **odkudkoli**, ne jen doma.
- Priorita: aby výsledek byl co nejlepší.

### Předpoklady (potvrzeno v rámci návrhu)
- PC: Windows 10/11. Telefon: Android.
- Primární jazyk ovládání a odpovědí: čeština (angličtina funguje taky).

### Kritéria úspěchu (verze 1)
1. Řeknu „Hey Jarvis, pusť na YouTube trailer na Avengers“ → nahoře se
   rozevře notch, ukáže přepis, JARVIS odpoví česky hlasem a video se
   přehraje v prohlížeči.
2. Bez internetu JARVIS pořád funguje (Ollama + Whisper + Piper), jen hloupěji.
3. Telefon spárovaný přes QR kód umí napsat/namluvit příkaz, který se
   provede na PC, i když je telefon na mobilních datech (přes Tailscale).
4. Do chatu (PC i telefon) pošlu fotku, PDF nebo hlasovku a JARVIS ji
   přečte/popíše/shrne; odpověď vidím v chatu a zároveň ji umí říct nahlas.
5. Instalace na PC jedním skriptem, APK ke stažení z GitHub Releases.
6. Najedu myší na notch → plynule se rozevře panel (zeptej se, právě hraje,
   police, rychlé akce…); odjedu → zavře se.
7. Všechno jde nastavit v Nastavení, a základní věci i hlasem.
8. „Nastav ve Windows tmavý režim“ → JARVIS to udělá sám přes ovládání
   počítače (po potvrzení).
9. Provoz nic nestojí.

## 2. Architektura

```
┌─────────────────── PC (Windows) ────────────────────┐
│  JARVIS Core (Python 3.11+, tray ikona)              │
│   ├─ voice/   mikrofon → wake word → STT → TTS       │
│   ├─ llm/     řetěz poskytovatelů (OmniRoute → … →   │
│   │           Ollama)                                │
│   ├─ agent    smyčka s voláním nástrojů              │
│   ├─ tools/   ovládání Windows                       │
│   ├─ memory   SQLite                                 │
│   └─ server   FastAPI + WebSocket :8765 + statické UI│
│         ▲              ▲                             │
│   Notch   (pywebview  Dashboard (prohlížeč /         │
│   overlay okno)       pywebview okno)                │
└─────────┼──────────────┼─────────────────────────────┘
          │  LAN / Tailscale, token z QR párování
┌─────────┴── Telefon (Android APK, Capacitor) ───────┐
│  chat + hlas, rychlá tlačítka, Sdílet → JARVIS,      │
│  notifikace z PC                                     │
└──────────────────────────────────────────────────────┘
```

Všechny klienty (notch, dashboard, telefon) mluví s jádrem **jen** přes
WebSocket protokol (sekce 6). Jádro o konkrétním UI nic neví → později lze
přidat nativní klienty (Flutter, Tauri) beze změny jádra.

### Struktura repozitáře
```
core/                    Python balíček `jarvis`
  pyproject.toml
  jarvis/
    __main__.py          start: tray + server + voice loop + overlay
    config.py            načtení/uložení config.toml (pydantic)
    events.py            interní event bus (asyncio) — vše co jde do UI
    agent.py             agentní smyčka
    memory.py            SQLite: konverzace, fakta o uživateli
    attachments/
      store.py           ukládání souborů, metadata, náhledy
      extract.py         text z PDF/Office/textu, OCR, přepis audia
    llm/
      base.py            rozhraní LLMProvider
      openai_compat.py   OpenAI-kompatibilní API (OmniRoute, OpenRouter,
                         Groq, Gemini OpenAI endpoint, LM Studio, …)
      ollama.py          Ollama (nativní API)
      router.py          fallback řetěz + presety poskytovatelů
    tools/
      base.py            @tool dekorátor, registr, JSON schéma, danger flag
      apps.py web.py youtube.py media.py system.py windows.py
      files.py clipboard.py info.py weather.py screenshot.py
      timers.py shell.py phone.py settings.py
      computer_use.py browser.py code.py images.py
      schedule.py skills.py
    mcp/                 MCP klient (stdio + HTTP), načtení nástrojů
    scheduler.py         rutiny a plánované úlohy
      platform/          Windows implementace + Null/mock implementace
    voice/
      audio.py           mikrofon (sounddevice), VAD
      wakeword.py        openWakeWord („hey_jarvis“)
      stt.py             faster-whisper (lokálně) / volitelně API
      tts.py             edge-tts → záloha Piper
    server/
      app.py             FastAPI, statické soubory web/dist
      ws.py              WebSocket protokol
      pairing.py         tokeny, QR kód
  tests/
web/                     Vite + TypeScript UI (bez frameworku)
  src/notch/  src/dashboard/  src/mobile/  src/shared/ (ws klient, protokol)
mobile/                  Capacitor projekt → Android APK
install.ps1              instalace na Windows
.github/workflows/       testy + sestavení APK + release
docs/
```

## 3. AI mozek (llm/)

- Rozhraní `LLMProvider.chat(messages, tools, stream) -> async iterator`
  s podporou volání nástrojů (OpenAI formát `tools` / `tool_calls`).
- `openai_compat.py` pokrývá vše s endpointem `/v1/chat/completions`.
  Presety v configu (uživatel jen vyplní klíč, kde je potřeba):
  | preset     | base_url                                   | klíč |
  |------------|--------------------------------------------|------|
  | omniroute  | `http://localhost:20128/v1`                | volitelný |
  | openrouter | `https://openrouter.ai/api/v1`             | ano (free modely) |
  | groq       | `https://api.groq.com/openai/v1`           | ano (free tier) |
  | gemini     | `https://generativelanguage.googleapis.com/v1beta/openai` | ano (free tier) |
  | lmstudio   | `http://localhost:1234/v1`                 | ne |
  | custom     | libovolná URL                              | volitelný |
- `ollama.py` — lokální offline záloha (`http://localhost:11434`).
- `router.py` — řetěz poskytovatelů dle configu, výchozí:
  `omniroute → ollama`. Při chybě sítě, 429, 5xx nebo timeoutu (15 s na první
  token) se zkusí další. Úspěšný poskytovatel se hlásí v UI („mozek: OmniRoute“).
- Pokud model nepodporuje nástroje (chyba 400 s tools), router to pro daného
  poskytovatele zapamatuje a pošle dotaz bez nástrojů (jen konverzace).

## 4. Agent

1. Vstup (hlas nebo text, z PC nebo z telefonu) → zpráva uživatele.
2. Systémový prompt: osobnost JARVIS (stručný, vtipný, oslovuje „pane“
   nebo jménem z configu), jazyk = jazyk uživatele, aktuální čas, OS,
   relevantní fakta z paměti.
3. Volání LLM se seznamem nástrojů; streamuje text do UI.
4. Pokud LLM vrátí `tool_calls` → provést nástroje (paralelně, pokud jsou
   nezávislé) → výsledky zpět do LLM. Max **8 kol** na jeden dotaz.
5. Nástroj s `danger=True` (vypnutí, restart, shell, mazání, zavření všech
   oken) → event `confirm_request` do všech klientů; čeká se na
   `confirm_response` (max 30 s, jinak zrušeno). Hlasově stačí „ano“/„ne“.
6. Finální text → TTS (pokud vstup byl hlasový nebo je zapnuté „vždy mluvit“)
   + uložit do paměti.
7. Přerušení: nové „Hey Jarvis“ nebo tlačítko stop zastaví TTS i probíhající
   generování.

Paměť: tabulky `conversations`, `messages` (posledních N zpráv aktuální
konverzace jako kontext, výchozí 20; hlas i chat jdou do stejné konverzace),
`attachments` (sekce 6a) a
`facts` (nástroj `remember(fact)` / `forget(fact)`, AI je sama ukládá, když
řekneš „zapamatuj si…“).

## 5. Nástroje (verze 1)

Každý nástroj = funkce s dekorátorem `@tool(name, description, danger=False)`;
parametry z typových anotací → JSON schéma. Windows specifika jsou za
rozhraním `platform/` (Windows implementace + Null implementace pro testy a
Linux).

| nástroj | co dělá | danger |
|---|---|---|
| open_app / close_app | spustí/zavře aplikaci (Start menu index, známé aliasy: „spotify“, „discord“, „steam“…) | close: ne |
| open_url | otevře URL ve výchozím prohlížeči | |
| web_search | vyhledá na webu (DuckDuckGo přes `ddgs`, zdarma, bez klíče) a vrátí AI výsledky — JARVIS tak odpovídá i na aktuální otázky | |
| web_read | stáhne stránku a vytáhne čitelný text (`trafilatura`) — „shrň mi tenhle článek“ | |
| read_attachment | přečte obsah přílohy podle id (pro dlouhé soubory po částech) | |
| save_attachment | uloží přílohu do zvolené složky na PC a případně otevře | |
| send_file | pošle soubor z PC do chatu (na telefon) jako přílohu | |
| youtube_play | najde video (yt-dlp `ytsearch1:`, bez API klíče) a otevře `watch?v=…` s autoplay | |
| media_control | play/pause/next/prev (media klávesy) | |
| volume | nastavit/zvýšit/snížit/ztlumit (pycaw) | |
| window_control | minimalizovat vše, přepnout na okno, maximalizovat | |
| system_power | lock, sleep, shutdown, restart, zrušit vypnutí | ano (kromě lock) |
| find_file / open_file | hledání v uživatelských složkách, otevření | |
| clipboard_get / clipboard_set | schránka | |
| system_info | CPU, RAM, disk, baterie, IP (psutil) | |
| weather | Open-Meteo (zdarma, bez klíče), město z configu nebo z dotazu | |
| screenshot | snímek obrazovky, uloží; když model umí obraz, popíše ho | |
| set_timer / set_reminder | časovač/připomínka → hlas + notch + notifikace na telefon | |
| run_shell | PowerShell příkaz, výstup zpět AI | ano |
| send_to_phone | pošle text/odkaz/notifikaci na telefon | |
| remember / forget | paměť faktů | |
| get_time | datum a čas | |

## 5a. Superschopnosti („umí úplně všechno“)

Doslova „všechno“ nejde slíbit žádnému programu — ale tyhle schopnosti
dohromady znamenají, že JARVIS zvládne prakticky cokoli, co by udělal
člověk u počítače, a co neumí, to se naučí:

| schopnost | jak | danger |
|---|---|---|
| **Ovládání počítače jako člověk** (`computer_use`) | vidí obrazovku (screenshot → vision model), kliká, píše, scrolluje, mačká zkratky (`pyautogui`) ve smyčce, dokud úkol nesplní („v Excelu udělej graf z tabulky“, „nastav ve Windows tmavý režim“). Zastavení: Esc nebo „stop“. Max 30 kroků. | ano (potvrzení na začátku úkolu; v nastavení lze „důvěřovat“) |
| **Ovládání prohlížeče** (`browser_*`) | Playwright s vlastním profilem Edge/Chrome: otevřít, klikat, vyplňovat formuláře, číst stránky, stahovat („najdi na Alze nejlevnější sluchátka do 1000 Kč“) | odeslání formuláře / nákup = ano |
| **Spouštění kódu** (`run_python`) | Python v odděleném procesu s timeoutem — výpočty, převody souborů, grafy, úprava obrázků, Excel; výsledné soubory přijdou jako přílohy | ne pro výpočty v sandbox složce; zápis mimo ni = ano |
| **Generování obrázků** (`generate_image`) | Pollinations.ai (zdarma, bez klíče), volitelně jiný poskytovatel; výsledek jako příloha v chatu | |
| **MCP integrace** | JARVIS je MCP klient: připojíš libovolný MCP server (Gmail, Kalendář, Spotify, GitHub, Notion, chytrá domácnost, …) a jeho nástroje se mu objeví | podle serveru |
| **Učí se nové dovednosti** (`create_skill`) | když něco neumí, napíše si nový nástroj v Pythonu do `%APPDATA%\JARVIS\skills\`, ukáže ti kód, po schválení ho načte bez restartu a příště ho použije | ano (schválení kódu) |
| **Rutiny a plánování** (`schedule`) | „každý den v 7:00 mi řekni počasí a co mám v plánu“, „v pátek v 18:00 vypni PC“, podmínky („až dojde baterie na 20 %…“); uloženo v SQLite, běží na pozadí | dle akce |
| **Agent na pozadí** | dlouhé úkoly běží na pozadí (karta v notchi s průběhem), můžeš mezitím mluvit dál | |

Pravidla bezpečnosti platí vždy: nebezpečné akce potvrzuješ ty (hlasem,
klikem, z telefonu); vše, co JARVIS udělal, je vidět v logu akcí v chatu.

## 6. WebSocket protokol

Endpoint `ws://<pc>:8765/ws?token=<token>`. Zprávy JSON
`{"type": "...", ...}`.

Klient → jádro:
- `hello {client: "notch"|"dashboard"|"mobile", name}`
- `user_text {text, attachments: [attachment_id]}` (přílohy se předem
  nahrají přes HTTP `POST /api/upload`, viz sekce 6a)
- `history_get {before?, limit}` (načtení starší historie chatu)
- `new_chat {}` (nová konverzace; stará zůstane v historii)
- `audio_chunk {pcm16_b64, sample_rate}` + `audio_end {}` (hlas z telefonu → STT na PC)
- `confirm_response {id, approved}`
- `stop {}`
- `quick_action {action, args}` (rychlá tlačítka = přímé volání nástroje bez LLM)
- `share {kind: "url"|"text", value}` (Sdílet → JARVIS)
- `settings_get {}` / `settings_set {patch}` (jen dashboard z localhostu)

Jádro → klienti (broadcast všem):
- `state {state: "idle"|"listening"|"thinking"|"acting"|"speaking"}`
- `level {rms}` (hlasitost mikrofonu/TTS pro animaci vln, ~20×/s)
- `transcript {text, final}`
- `user_message {id, text, attachments, source}` (zpráva od uživatele z
  libovolného zařízení — chat je synchronní na PC i telefonu)
- `assistant_delta {text}` / `assistant_done {id, text, attachments}`
- `history {messages}`
- `tool_start {id, name, args}` / `tool_end {id, ok, summary}`
- `confirm_request {id, description}`
- `notify {title, body}`
- `brain {provider, model}`
- `settings_changed {patch}`
- `task_progress {id, title, step, total, done}` (úlohy na pozadí, computer use)
- `media {title, artist, thumb, playing}` (pro dlaždici Právě hraje)
- `error {message}`

Sdílené TS typy v `web/src/shared/protocol.ts` a Python modely v
`server/ws.py` drží stejný tvar; test kontroluje, že se shodují.

## 6a. Chat a přílohy

JARVIS je plnohodnotný chat (jako ChatGPT/Claude) **a zároveň** mluví —
obojí současně, jedna společná konverzace na PC i telefonu.

**Chat:**
- Stream odpovědi, Markdown (nadpisy, seznamy, tabulky, odkazy), bloky kódu
  se zvýrazněním a tlačítkem Kopírovat.
- U každé odpovědi tlačítko 🔊 „přečíst nahlas“; přepínač „mluvit vždy /
  jen u hlasu / nikdy“.
- Hlasové zprávy se v chatu zobrazí jako přepsaný text (s ikonou mikrofonu).
- Karty nástrojů v chatu („▶ Pouštím YouTube: …“, „🔊 Hlasitost 40 %“).
- Historie konverzací (seznam vlevo), nová konverzace, hledání v historii,
  zastavit generování, znovu vygenerovat odpověď.

**Přílohy — co můžeš poslat a co s tím JARVIS udělá:**
| typ | zpracování |
|---|---|
| obrázky, fotky, screenshoty (png, jpg, webp, heic) | pošle se modelu jako obrázek (vision). Když aktuální model obrázky neumí, router zkusí dalšího poskytovatele s vision modelem; když žádný → lokální OCR (`rapidocr-onnxruntime`) a do AI jde text z obrázku |
| PDF | text přes `pypdf`; stránky bez textu (sken) → OCR |
| Word, Excel, PowerPoint (docx, xlsx, pptx) | text/tabulky přes `python-docx`, `openpyxl`, `python-pptx` |
| textové soubory, kód, CSV, JSON, Markdown | obsah přímo |
| audio (mp3, wav, m4a, ogg — i hlasovky) | přepis přes Whisper (STT) |
| video | uloží se; ve verzi 1 bez analýzy obsahu (jen info o souboru) |
| cokoli jiného | uloží se, AI dostane název/typ/velikost a umí soubor uložit nebo otevřít na PC |

- Krátký obsah (do ~8 000 znaků) jde rovnou do zprávy pro AI; delší se
  zkrátí a AI si zbytek dočte nástrojem `read_attachment` po částech.
- Jak poslat: tlačítko 📎, přetažení (drag & drop) do chatu nebo na notch,
  vložení Ctrl+V (obrázek ze schránky), na telefonu fotoaparát / galerie /
  soubory a „Sdílet → JARVIS“ z jiných aplikací (fotky, PDF, odkazy).
- JARVIS umí přílohy i posílat zpět: screenshot PC, soubor z PC
  („pošli mi na mobil tu prezentaci z Plochy“) → přijde jako příloha do
  chatu na telefonu a jde stáhnout.
- Limit velikosti: 200 MB na soubor (nastavitelné).

**HTTP API pro soubory** (stejný token jako WebSocket):
- `POST /api/upload` (multipart) → `{id, name, mime, size, kind}`; zpracování
  (extrakce textu, OCR, přepis) běží hned na pozadí.
- `GET /api/files/{id}` → stažení; `GET /api/files/{id}/thumb` → náhled.
- Uloženo v `%APPDATA%\JARVIS\files\`, metadata v SQLite tabulce
  `attachments` (id, název, mime, velikost, cesta, extrahovaný text,
  conversation_id). Mazání se starou konverzací.

## 7. Párování a vzdálený přístup

- Při prvním spuštění se vygeneruje náhodný token (32 B) uložený v configu.
- Dashboard zobrazí QR kód s `jarvis://pair?hosts=<lan-ip>,<tailscale-ip>&port=8765&token=…`.
- Telefon zkouší hosty v pořadí (LAN první, pak Tailscale `100.x`).
- Pro přístup odkudkoli: uživatel nainstaluje **Tailscale** (zdarma) na PC i
  telefon; `install.ps1` a dashboard ho k tomu navedou. Žádné porty do
  internetu se neotevírají.
- Server vyžaduje token pro všechny požadavky mimo `127.0.0.1`.
  Nastavení (`settings_set`) jen z localhostu.
- Token lze v dashboardu přegenerovat (odpojí staré telefony).

## 8. Hlas (voice/)

- Mikrofon: `sounddevice`, 16 kHz mono.
- Wake word: openWakeWord model `hey_jarvis` (běží na CPU), práh v configu.
  Alternativa: zkratka **Ctrl+Space** (push-to-talk / otevře psaní v notchi).
- Konec věty: VAD (`webrtcvad-wheels`) — 0,8 s ticha.
- STT: faster-whisper, model `small` (výchozí; `base` pro slabé PC,
  `large-v3-turbo` pro GPU), jazyk auto/cs. Volitelně STT přes Groq API
  (rychlejší na slabém PC, zdarma tier).
- TTS: edge-tts hlas `cs-CZ-AntoninNeural` (výchozí), záloha Piper
  `cs_CZ-jirka-medium` offline. Hlas nastavitelný.
- Když chybí mikrofon/model, voice loop se vypne a vše jede přes text; chyba
  se ukáže v dashboardu.

## 9. UI (web/)

Jedno Vite + TypeScript UI, tři vstupní stránky; jádro je servíruje
z `web/dist`.

- **Notch** (`/notch`) — hlavní tvář JARVISe na PC, ve stylu MacBook
  notche / Dynamic Islandu. Detail v sekci 9a.
- **Dashboard / Chat** (`/`, otevře se i jako samostatné okno „JARVIS“
  z traye nebo zkratkou Ctrl+Shift+J): plný chat dle sekce 6a (historie
  konverzací, Markdown, přílohy, 🔊, mikrofon), stav mozku, nastavení
  (poskytovatelé + pořadí + klíče + test připojení, hlas, wake word, jméno,
  město, „mluvit vždy“), párování (QR), seznam nástrojů.
- **Mobil** (`/mobile`, zabalené do APK): obrazovka připojení (sken QR /
  ruční zadání), plný chat dle sekce 6a včetně příloh (📎 fotoaparát,
  galerie, soubory), velké mikrofonní tlačítko (nahraje zvuk → pošle
  `audio_chunk`), odpovědi umí přečíst nahlas přímo na telefonu (TTS audio
  z PC se pošle jako příloha / stream), mřížka rychlých tlačítek
  (play/pause, další, hlasitost ±, ztlumit, zamknout, screenshot PC),
  zobrazení potvrzení a notifikací.
- Vizuál: tmavý, „Stark HUD“ — černá/grafit, azurový akcent, jemná záře,
  plynulé animace; respektuje `prefers-reduced-motion`.

## 9a. Notch (detail)

Černý „výřez“ přilepený k hornímu okraji obrazovky uprostřed — rovný horní
okraj, zaoblené spodní rohy a jemně prohnuté „ramena“ jako macOS notch.

**Stavy:**
1. **Klid** (~200×32 px): jen černý notch; vlevo malý dýchající JARVIS
   orb (barva = stav: azurová připraven, fialová přemýšlí, zelená mluví,
   červená chyba / offline), vpravo „live activity“ podle situace:
   mini vlny když hraje hudba, odpočet timeru, počet nových notifikací
   z telefonu, ikona 🎙 když poslouchá.
2. **Najetí myší** (po 150 ms) → pružinová animace (spring) rozevře notch do
   panelu ~680×240 px. Odjetí myši → po 400 ms se zavře (ne, pokud do něj
   píšeš nebo běží potvrzení).
3. **Hlasová aktivita** („Hey Jarvis“ / Ctrl+Space) → notch se rozevře do
   „live“ režimu: animované vlny podle `level`, živý přepis, řádek
   „⚙ Otevírám YouTube…“ (karty nástrojů), streamovaná odpověď. Po dokončení
   ještě 6 s zobrazí odpověď a smrští se.
4. **Upozornění** (timer, notifikace z telefonu, hotový úkol) → krátce
   „vyskočí“ (pulz + rozšíření) s textem, pak zpět.

**Rozevřený panel — dlaždice (zapnout/vypnout a řadit v nastavení):**
- **Zeptej se**: vstupní pole + 🎙 + 📎 (rychlý chat, odpověď přímo v notchi;
  „↗“ otevře celý chat).
- **Právě hraje**: obal, název, interpret, ovládání ⏮ ⏯ ⏭ — čte Windows
  media session (Spotify, YouTube v prohlížeči, cokoli) přes `winsdk`.
- **Police (shelf)**: přetáhni sem soubory → odloží se (jako NotchNook) a
  jde je pak přetáhnout jinam, poslat na telefon nebo „zeptat se JARVISe“.
- **Rychlé akce**: hlasitost, ztlumit, screenshot, zámek, režim „nerušit“,
  vlastní tlačítka (spouští příkaz/rutinu).
- **Timery a připomínky**, **Systém** (CPU, RAM, GPU, baterie, síť),
  **Počasí**, **Kalendář/rutiny dne**, **Telefon** (baterie telefonu,
  poslední notifikace, „pošli na mobil“).
- Ikona ⚙ → nastavení, ikona 💬 → plný chat.

**Technicky:** bezrámové průhledné pywebview okno vždy navrchu bez ikony
na liště. Okno samo mění velikost podle stavu (JS → Python API `resize`),
takže v klidu zabírá jen plochu notche a nepřekáží klikání. Hover
detekuje JS + polling pozice myši (pro spolehlivost i nad okrajem).
Výběr monitoru, posun, velikost a průhlednost v nastavení. Automaticky se
skryje při hře/videu na celou obrazovku (volitelné). Respektuje DPI
škálování Windows.

## 9b. Nastavení (vše nastavitelné)

Okno Nastavení (dashboard, z notche ⚙ nebo z traye) + **JARVIS umí své
nastavení měnit sám hlasem** („mluv rychleji“, „přepni na Groq“, „vypni
wake word“) přes nástroj `update_setting` (jen povolené klíče; citlivé věci
jako klíče a oprávnění jen ručně).

Sekce:
- **Obecné**: jméno uživatele, jak tě oslovuje, jazyk, osobnost (JARVIS
  formální / kamarád / stručný / vlastní prompt), spuštění po startu Windows,
  aktualizace.
- **Mozek (AI)**: poskytovatelé (presety + vlastní), pořadí záložního řetězu,
  model zvlášť pro chat / vidění (obrázky) / rychlé úlohy, kreativita
  (temperature), max délka, tlačítko „Otestovat“, offline režim (jen
  lokální modely).
- **Hlas**: mikrofon, wake word (zap/vyp, citlivost, test), push-to-talk
  zkratka, STT model a jazyk, TTS hlas (náhled poslechem), rychlost, výška,
  hlasitost, kdy mluvit (vždy / jen u hlasu / nikdy).
- **Notch**: monitor, pozice, velikost, zpoždění rozevření, dlaždice
  (pořadí, zap/vyp), skrývat ve fullscreenu, barva akcentu.
- **Vzhled**: motiv (Stark tmavý, světlý, vlastní akcent), animace
  (plné / omezené).
- **Zkratky**: všechny klávesové zkratky přenastavitelné.
- **Nástroje a oprávnění**: každý nástroj zap/vyp, které chtějí potvrzení,
  ovládání počítače (sekce 5a) zap/vyp, povolené složky pro soubory.
- **Integrace**: MCP servery (přidat/odebrat/test), rutiny.
- **Telefon**: spárovaná zařízení (přejmenovat, odpojit), nový QR,
  přegenerovat token, stav Tailscale.
- **Paměť**: co si o tobě pamatuje (zobrazit, upravit, smazat), historie
  konverzací, smazat vše.
- **Záloha**: export/import nastavení + paměti (jeden soubor).

Nastavení se ukládá do `config.toml`, mění se okamžitě bez restartu
(event `settings_changed` všem klientům), klíče API se ukládají do Windows
Credential Manageru (`keyring`), ne do souboru.

## 10. Android aplikace (mobile/)

- Capacitor obal kolem `web/dist` (stránka mobile).
- Pluginy: mikrofon (nahrávání), sken QR (kamera), lokální notifikace,
  share intent („Sdílet → JARVIS“ pro odkazy, text, fotky, soubory),
  výběr souborů a fotoaparát, stahování příloh, uložení párování.
- Udržuje WebSocket, s auto-reconnect (exponenciální čekání max 10 s).
  Notifikace z PC chodí, dokud je aplikace aktivní/na pozadí; push notifikace
  při úplně zavřené aplikaci nejsou ve verzi 1.
- APK sestavuje GitHub Actions (debug-podepsané APK, Release při tagu).

## 11. Instalace a spuštění na PC

`install.ps1`:
1. Zkontroluje/nainstaluje Python 3.11+ (winget), vytvoří venv, `pip install`.
2. Stáhne Whisper model, wake word model, Piper hlas.
3. Volitelně nabídne instalaci OmniRoute (`npm i -g omniroute`, potřebuje
   Node) a Ollamy + malého modelu (`qwen2.5:3b`) pro offline.
4. Vytvoří zástupce a volitelně spuštění po startu Windows.
5. Odkaz na Tailscale.

Spuštění: `python -m jarvis` → tray ikona, notch, server; dashboard
z menu traye.

Konfigurace: `%APPDATA%\JARVIS\config.toml` (+ `jarvis.db`).

## 12. Chyby a odolnost

- LLM: fallback řetěz (sekce 3); když selžou všichni → JARVIS řekne
  „Nemám teď spojení s žádným mozkem“ a UI ukáže, co selhalo.
- Nástroj vyhodí výjimku → vrací `{ok: false, error}` do LLM; agent pokračuje.
- TTS edge-tts selže → Piper; Piper chybí → jen text.
- WebSocket klienti se automaticky znovu připojují; jádro drží jen aktuální
  stav, historie se načte z paměti při `hello`.
- Logy do `%APPDATA%\JARVIS\logs` (rotace).

## 13. Testování

- **pytest** (`core/tests`): config, registr nástrojů a JSON schémata, agent
  s falešným LLM (scénáře: text, volání nástroje, více kol, danger +
  potvrzení/zamítnutí, limit kol), router (fallback při chybě/429/timeoutu,
  vypnutí tools), WebSocket protokol + token autentizace (FastAPI
  TestClient), paměť, nástroje s Null platformou, přílohy (upload/download
  s tokenem a bez, extrakce textu z ukázkového PDF/DOCX/TXT, obrázek →
  vision zpráva / OCR fallback, zkrácení dlouhého obsahu, synchronizace
  chatu mezi dvěma klienty).
- **web**: typecheck + build; test, že TS protokol odpovídá Python modelům.
- **CI**: GitHub Actions — pytest na Ubuntu i Windows (Windows runner ověří
  skutečné Windows importy), build webu, build APK.
- Ručně uživatel na PC: wake word, hlas, YouTube, hlasitost, telefon přes
  Tailscale (checklist v README).

## 14. Mimo verzi 1 (další fáze)

- Samostatný JARVIS na telefonu bez PC, ovládání telefonu z PC.
- Přenos velkých souborů, push notifikace při zavřené aplikaci (FCM).
- Kamera (webkamera jako oči JARVISe), zrcadlení notifikací z telefonu na PC
  (vyžaduje nativní Android NotificationListener).
- Nativní klienti (Flutter/Tauri).

## 15. Pořadí stavby (etapy)

Vše výše je cílem; stavíme po etapách, každá končí funkčním a otestovaným
stavem pushnutým do repa:

1. **Jádro**: config, event bus, LLM router (OmniRoute → … → Ollama),
   agent s nástroji, paměť, server + WebSocket + přílohy, základní nástroje.
2. **Web UI**: chat (dashboard) + notch (všechny stavy a dlaždice) +
   nastavení.
3. **Hlas**: wake word, STT, TTS, přerušování.
4. **Superschopnosti**: computer use, prohlížeč, kód, obrázky, MCP, skills,
   rutiny.
5. **Telefon**: mobilní UI, Capacitor projekt, CI build APK, párování
   QR + Tailscale.
6. **Instalace a doladění**: `install.ps1`, README s checklistem, CI na
   Windows.
