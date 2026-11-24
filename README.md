# JARVIS 2

Osobní AI asistent pro **Windows PC** a **Android telefon**. Mluví česky, má chat s přílohami, vlastní nastavení,
„notch“ nahoře na obrazovce jako MacBook a umí ovládat počítač. Funguje zdarma (OmniRoute / Ollama) a z telefonu
ho ovládáš odkudkoli.

## Instalace (2 soubory)

Stáhni z **[Releases](../../releases/latest)**:

| Soubor | Kam | Jak |
|---|---|---|
| `JARVIS-Setup.exe` | PC (Windows 10/11, 64 bit) | Spusť, klikni Další. Instalátor nabídne i OmniRoute, Ollamu a Tailscale. |
| `JARVIS.apk` | Telefon (Android 8+) | Otevři v telefonu a povol „Instalovat z tohoto zdroje“. |

Pak na PC: JARVIS → **Telefon** → v aplikaci na mobilu **Naskenovat QR kód**. Hotovo.

Nebo přes Správce balíčků Windows (až bude JARVIS v katalogu winget – viz `docs/WINGET.md`):

```bash
winget install adamekk778.JARVIS
```

> Při prvním spuštění se Windows zeptá na povolení v bráně firewall: povol **Soukromé sítě**, jinak se telefon nepřipojí.
> Hlasové modely (Whisper ~460 MB) se stáhnou automaticky při prvním použití hlasu.

## Mozek (AI) zdarma

JARVIS zkouší poskytovatele v pořadí z **Nastavení → Mozek** a když jeden nejde, vezme další:

1. **OmniRoute** (výchozí, `http://localhost:20128/v1`): bezplatná brána k mnoha AI. Po instalaci otevři
   `http://localhost:20128` a přidej si poskytovatele zdarma. JARVIS OmniRoute sám spouští.
2. **Ollama** (offline): JARVIS si sám stáhne malý model `qwen2.5:3b`. Funguje bez internetu.
3. Cokoli s OpenAI API: OpenRouter, Groq, Gemini, LM Studio, vlastní URL. Klíč vložíš v Nastavení (uloží se do Správce pověření Windows).

## Co umí

- **Hlas:** „Hey Jarvis“ nebo Ctrl+Alt+Mezerník, česky, offline rozpoznávání (Whisper), hlas Microsoft Edge (zdarma) / Piper offline, dá se přerušit.
- **Chat** jako ChatGPT (Ctrl+Alt+J): Markdown, kód, historie, hledání, 🔊 přečíst nahlas.
- **Přílohy:** fotky (popíše), PDF, Word, Excel, PowerPoint, kód, hlasovky (přepíše), cokoli dalšího uloží/otevře.
- **Postavička JARVIS:** lesklý černý blob s očima, který bydlí v notchi a má 24 nálad (poslouchá, přemýšlí, mluví, tančí do hudby, pracuje, spí, chyba, limit, bez internetu, upozornění, radost…). Barvu a velikost změníš v Nastavení → Vzhled nebo hlasem.
- **Notch:** najeď myší nahoru doprostřed obrazovky → JARVIS se probudí a vyjede lišta; klik na něj otevře velký panel (Chat, Rychlé akce, Systém, Soubory, Nástroje, Nastavení).
- **Aktualizace:** panel → Systém → Zkontrolovat / Aktualizovat (instaluje jen po potvrzení).
- **Ovládání PC:** aplikace, YouTube, Spotify/média, hlasitost, okna, soubory, schránka, screenshot, vypnutí (s potvrzením), PowerShell.
- **Internet:** vyhledávání a čtení stránek, počasí.
- **Superschopnosti:** ovládání počítače jako člověk (vidí obrazovku a kliká), ovládání prohlížeče, spouštění Python kódu,
  generování obrázků, MCP servery (Gmail, kalendář, …), **učí se nové dovednosti** (napíše si nástroj, ty schválíš kód),
  rutiny („každý den v 7:00 mi řekni počasí“).
- **Telefon:** chat a hlas, ovládání PC, Sdílet → JARVIS (odkaz se otevře na PC, soubor přistane v polici notche), notifikace.
- **Nastavení:** úplně všechno (mozek, hlas, notch, vzhled, zkratky, oprávnění nástrojů, integrace, paměť, záloha). Základní věci i hlasem („mluv rychleji“).

Nebezpečné akce (vypnutí, mazání, nákupy, příkazy) vždy nejdřív potvrdíš ty.

## Novinky ve verzi 3.17 – Rychlost doma, chytřejší dílna, bezpečnější nástroje

- **Rychlost:** první věta hraje po kouscích, ještě než je celá vyrobená; při váhavé pauze se JARVIS zeptá AI
  s předstihem (nástroje spustí až na dořečená slova); živý přepis malým modelem; čekání na konec věty podle tvého
  tempa; Claude s hodinovou cache a úsporou v Diagnostice; **Změřit rychlost** u tebe doma a **Průvodce rychlostí**.
- **Chytřejší:** 3D díl z jakéhokoli popisu (AI navrhne, JARVIS zkontroluje), gesta prsty (štípnutí = zoom, dlaň =
  otáčení, pěst = rozložit), vzorové reflexy („pusť {cokoli} na YouTube“), přehled a mazání naučeného a kontrola
  tvých obvyklých povelů po každé aktualizaci.
- **Bezpečnost:** po přečtení cizího textu (e-mail, web, soubor, obrázek, schránka) smí AI bez ptaní jen číst; co
  mění, potvrdíš – i s plnou důvěrou.
- **Integrace:** Bambu Lab napřímo po síti (MQTT/FTPS, ověřený certifikát tiskárny), STEP v HUD i bez FreeCADu,
  zásilky DPD a PPL živě, „JARVIS na hodinkách“ Wear OS přes telefon.
- **Ověřování:** Windows testy a Android emulátor v CI.

## Novinky ve verzi 3.16 – Odpověď hned a nástroje v hlavě

- **Nástroje v hlavě:** velká AI (Claude, OpenAI, Gemini, DeepSeek, Mistral) má seznam všech ~900 nástrojů najednou
  v cache a zavolá kterýkoli jedním krokem (`use_tool`), bez hledání. Pokyny jsou rozdělené na neměnnou část (v cache)
  a „Aktuální situaci“, takže první slovo přijde dřív. Malé modely (Ollama, Groq zdarma) mají dál menší sadu.
- **Paměť nástrojů a reflexy:** co na jaká slova fungovalo, výběr nástrojů podle významu (místní model e5-small),
  podle aplikace na popředí a podle zvyků; stejná slova dvakrát úspěšně → příště bez AI.
- **Rychlý poslech:** přepis při každé pauze, hotová věta končí po 0,25 s, rozdělaná počká; tvoje slova pro
  rozpoznávání; „Hey Jarvis“ předehřeje spojení k AI; spojení k AI i k ElevenLabs zůstává otevřené.
- **Odpověď hned:** desítky povelů s údaji bez AI („přidej mléko na nákup“, „rozsviť v kuchyni“, „pozastav tisk“,
  „počasí v Brně“), bez druhého kola AI, když nástroj řekl vše, „Moment, pane.“ u delší práce, připravené fráze
  a počasí / kalendář / zprávy dopředu.
- **Rozhovor:** „ne, tu modrou“ uprostřed práce, „pokračuj“ po přerušení, Piper bez opakovaného načítání, volitelně
  ElevenLabs Flash a tiché „mhm“; volitelný místní reflexní model; v Diagnostice časy kroků a trefa nástroje napoprvé.

## Novinky ve verzi 3.15 – Mega animace a dílna

- **Pohyb všude:** Nastavení → Vzhled → Kvalita efektů (Ultra / Vysoká / Úsporná / Vypnuto, Automaticky podle grafiky);
  ve hře a na baterii se animace samy ztiší, Diagnostika ukazuje FPS každého okna. Nový zvukový design a barevná
  schémata Stark, Mark, Friday, Stealth.
- **Stark HUD ve 3D:** reaktor s částicemi, filmový start, 3D glóbus s oblouky cest, paralaxa, telemetrie, nástroje
  kroužící kolem reaktoru, rozložení Holo (prosvítá plocha) a ovládání hlasem („přibliž mapu“, „schovej panely“).
- **Notch a Mochi z tekutého kovu:** pružiny, tep do rytmu hudby, emoce podle odpovědi, tekutá upozornění, denní doba.
- **Chat a aplikace:** zhmotňování textu, živé karty výsledků, grafy, plynulé přechody, hlasový režim přes celou
  obrazovku, nový úvod.
- **Telefon:** EDITH s rámečky kolem věcí, start reaktorem, haptika, filmové SOS a příchozí hovor, widgety.
- **Plocha Windows:** zaměřovač tam, kam JARVIS kliká, skenovací paprsek, vlastní displej hlasitosti a jasu,
  „Vítejte zpět“ po odemčení, živá tapeta s reaktorem nebo glóbem za ikonami.
- **Dílna:** text → 3D model s úpravami hlasem („o 5 mm širší“, „vrať to“), hologram modelu v HUD s rozloženým pohledem
  (STL, OBJ, GLB, 3MF, STEP přes FreeCAD), 3D tiskárna (OctoPrint, Klipper, Bambu přes Home Assistant) s hlídáním
  tisku kamerou a AI, deník projektů s díly a nákupním seznamem, simulace (nosník, teplo v desce, obvod, RC/RL).
- **Gesta kamerou ovládají HUD:** otáčení modelu a glóbu, přiblížení, rozložení; bez HUD dál hudba.

## Novinky ve verzi 3.14

Velká vlna vylepšení (118 návrhů, rozdělených do 11 oblastí). Nejdůležitější:

- **Spolehlivost:** sada 300+ zkušebních otázek hlídá kvalitu odpovědí při každé změně, Diagnostika ukáže selhávající
  nástroje a rychlost každé AI, rozbitá aktualizace se sama vrátí, kanál Beta, kontrola rozhraní v prohlížeči.
- **Mozek:** Claude přes oficiální SDK (cache promptu, úroveň přemýšlení podle obtížnosti), úplně offline balíček.
- **Hlas:** rozpozná tvůj hlas, mluví stylem podle situace, odpovídá od první věty.
- **Paměť:** místní vyhledávání podle významu, rozhodnutí i s důvodem, import z ChatGPT / Claude / Google Keep.
- **Myslí dopředu, notch, ovládání PC, telefon, propojení:** OBS a herní klipy, podepsané balíčky dovedností,
  odpovědi z hodinek a z auta, widget v telefonu.
- **Bezpečnost:** kód a dovednosti v omezeném prostředí, záznam toho, co JARVIS viděl a čeho se dotkl, režim host,
  upozornění na nové spárované zařízení, samooprava dovedností, vlastní oprávnění pro každého agenta.
- **Dosah:** anglické rozhraní (Nastavení → Obecné → Jazyk → English), winget, webová stránka projektu (`site/`),
  anonymní statistiky jen se souhlasem (ve výchozím stavu vypnuté), šablony pro hlášení chyb a nápadů.

### JARVIS jako z filmu (3.14, návrhy 1–58 kromě dílny)

- **Hlas a osobnost:** živý rozhovor bez „Hey Jarvis“ (když se díváš do kamery), druhá osobnost FRIDAY, humor podle
  situace, tlumočník do Discordu / Teams přes VB-Cable.
- **Celý dům:** hlasové satelity v místnostech (Home Assistant), hlášení do reproduktorů, „následuj mě“, uvítání doma,
  scény jedním slovem, nástěnný HUD na tabletu, víc PC jako jeden JARVIS, nonstop server v Dockeru (`docs/SERVER.md`),
  nejlevnější hodiny elektřiny.
- **Oči a uši:** EDITH v telefonu (kamera: co vidím, přečti, přelož, změř), kdo je doma, zvuky domu, pomocník na
  obrazovce, letadla a ISS nad domem.
- **Bezpečnost:** kamery Frigate, zvonek s fotkou, fotka při hlídání PC, SOS s polohou, týdenní brífink, dětský režim.
- **Zdraví:** spánek a tep z hodinek (Health Connect), ranní „stav systémů“, pitný režim, dlouhý den, spánek, držení těla.
- **Auto, cesty, svět:** auto přes Home Assistant („připrav auto na 7:30“), lety a vlaky z e-mailů a kdy vyrazit,
  zásilky, mapa světa s radarem v HUD.
- **Telefon:** AI sekretářka a volání za tebe (Twilio, vždy se představí jako AI), shrnutí chatů z oznámení.
- **Mozek:** noční učení, šifrovaná Paměť života (jen po zapnutí), mise na dny, „co když“ s grafem.
- **Roboti:** vysavač a sekačka přes Home Assistant, dron DJI Tello s pevnými bezpečnostními limity.

Co je k tomu potřeba (hardware, účty, nastavení) a co zatím nejde, je v `docs/ROADMAP.md` a `docs/INTEGRATIONS.md`.

## Ruční test po instalaci

- [ ] „Hey Jarvis, pusť na YouTube trailer na Avengers“ → rozevře se notch, JARVIS odpoví a pustí video.
- [ ] Ctrl+Alt+J → chat, pošli fotku → JARVIS ji popíše.
- [ ] „Ztlum zvuk“, „hlasitost na 30“, „jaké bude počasí“.
- [ ] Najeď myší na notch → JARVIS se probudí, vyjede lišta; klik na něj → velký panel; odjeď → zavře se.
- [ ] Pusť hudbu → JARVIS v notchi tancuje; nech PC 10 min být → usne.
- [ ] Telefon na Wi-Fi: napiš „otevři Spotify“ → otevře se na PC. Pak přes mobilní data se zapnutým Tailscale.
- [ ] „Vypni počítač“ → JARVIS se zeptá na potvrzení, řekni „ne“.

## Vývoj

```bash
cd web && npm ci && npm run build          # UI
pip install -e "./core[desktop,voice,dev]"  # jádro
python -m jarvis                           # spustí vše (na Linuxu: --no-ui)
cd core && pytest                          # testy
```

Struktura: `core/` Python jádro (agent, nástroje, hlas, server), `web/` UI (notch, chat, mobil),
`mobile/` Android obal (Capacitor), `packaging/` instalátor, návrh v `docs/superpowers/specs/`.

## Dokumentace (OMEGA)
- `docs/OMEGA_SPEC.md` – dlouhodobé zadání (katalog 001–795 + původních 110+ schopností)
- `docs/FEATURE_AUDIT.md` – stav každé schopnosti s důkazem (generuje `python docs/audit/build_audit.py`)
- `docs/FEATURE_MATRIX.md` – které moduly nesou které funkce, překryvy
- `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/INTEGRATIONS.md`, `docs/ROADMAP.md`, `docs/TEST_REPORT.md`

První mise k vyzkoušení: v aplikaci **Úkoly → Zkontrolovat PC**, nebo řekni „zjisti stav mého počítače a ulož report“.
