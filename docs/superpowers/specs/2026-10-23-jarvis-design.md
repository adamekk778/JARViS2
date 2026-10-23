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
   roztáhne pilulka, ukáže přepis, JARVIS odpoví česky hlasem a video se
   přehraje v prohlížeči.
2. Bez internetu JARVIS pořád funguje (Ollama + Whisper + Piper), jen hloupěji.
3. Telefon spárovaný přes QR kód umí napsat/namluvit příkaz, který se
   provede na PC, i když je telefon na mobilních datech (přes Tailscale).
4. Instalace na PC jedním skriptem, APK ke stažení z GitHub Releases.
5. Provoz nic nestojí.

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
│   Pilulka (pywebview  Dashboard (prohlížeč /         │
│   overlay okno)       pywebview okno)                │
└─────────┼──────────────┼─────────────────────────────┘
          │  LAN / Tailscale, token z QR párování
┌─────────┴── Telefon (Android APK, Capacitor) ───────┐
│  chat + hlas, rychlá tlačítka, Sdílet → JARVIS,      │
│  notifikace z PC                                     │
└──────────────────────────────────────────────────────┘
```

Všechny klienty (pilulka, dashboard, telefon) mluví s jádrem **jen** přes
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
      timers.py shell.py phone.py
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
  src/pill/  src/dashboard/  src/mobile/  src/shared/ (ws klient, protokol)
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

Paměť: tabulka `messages` (posledních N zpráv jako kontext, výchozí 20) a
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
| open_url, web_search | otevře URL / hledání Google ve výchozím prohlížeči | |
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
| set_timer / set_reminder | časovač/připomínka → hlas + pilulka + notifikace na telefon | |
| run_shell | PowerShell příkaz, výstup zpět AI | ano |
| send_to_phone | pošle text/odkaz/notifikaci na telefon | |
| remember / forget | paměť faktů | |
| get_time | datum a čas | |

## 6. WebSocket protokol

Endpoint `ws://<pc>:8765/ws?token=<token>`. Zprávy JSON
`{"type": "...", ...}`.

Klient → jádro:
- `hello {client: "pill"|"dashboard"|"mobile", name}`
- `user_text {text}`
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
- `assistant_delta {text}` / `assistant_done {text}`
- `tool_start {id, name, args}` / `tool_end {id, ok, summary}`
- `confirm_request {id, description}`
- `notify {title, body}`
- `brain {provider, model}`
- `error {message}`

Sdílené TS typy v `web/src/shared/protocol.ts` a Python modely v
`server/ws.py` drží stejný tvar; test kontroluje, že se shodují.

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
  Alternativa: zkratka **Ctrl+Space** (push-to-talk / otevře psaní v pilulce).
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

- **Pilulka** (`/pill`): průhledné, bezrámové, vždy navrchu pywebview okno
  nahoře uprostřed. Stav idle = malá černá kapsle (~120×34 px) s tečkou;
  listening/thinking/speaking = plynulé roztažení (~520×64), animované vlny
  podle `level`, živý přepis, řádek „⚙ Otevírám YouTube…“ při nástroji;
  odpověď se ukáže a po 6 s se pilulka smrští. Potvrzovací dialog
  (Ano/Ne) přímo v pilulce. Klik = psaní.
- **Dashboard** (`/`): chat s historií a streamem, stav mozku, nastavení
  (poskytovatelé + pořadí + klíče + test připojení, hlas, wake word, jméno,
  město), párování (QR), seznam nástrojů.
- **Mobil** (`/mobile`, zabalené do APK): obrazovka připojení (sken QR /
  ruční zadání), chat, velké mikrofonní tlačítko (nahraje zvuk → pošle
  `audio_chunk`), mřížka rychlých tlačítek (play/pause, další, hlasitost ±,
  ztlumit, zamknout, screenshot PC), zobrazení potvrzení a notifikací.
- Vizuál: tmavý, „Stark HUD“ — černá/grafit, azurový akcent, jemná záře,
  plynulé animace; respektuje `prefers-reduced-motion`.

## 10. Android aplikace (mobile/)

- Capacitor obal kolem `web/dist` (stránka mobile).
- Pluginy: mikrofon (nahrávání), sken QR (kamera), lokální notifikace,
  share intent („Sdílet → JARVIS“), uložení párování.
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

Spuštění: `python -m jarvis` → tray ikona, pilulka, server; dashboard
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
  TestClient), paměť, nástroje s Null platformou.
- **web**: typecheck + build; test, že TS protokol odpovídá Python modelům.
- **CI**: GitHub Actions — pytest na Ubuntu i Windows (Windows runner ověří
  skutečné Windows importy), build webu, build APK.
- Ručně uživatel na PC: wake word, hlas, YouTube, hlasitost, telefon přes
  Tailscale (checklist v README).

## 14. Mimo verzi 1 (další fáze)

- Samostatný JARVIS na telefonu bez PC, ovládání telefonu z PC.
- Přenos velkých souborů, push notifikace při zavřené aplikaci (FCM).
- Rutiny/scény („dobré ráno“), kamera, ovládání chytré domácnosti.
- Pluginy nástrojů od třetích stran, nativní klienti (Flutter/Tauri).
