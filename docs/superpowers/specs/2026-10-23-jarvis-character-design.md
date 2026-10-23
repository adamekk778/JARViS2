# JARVIS 2: postavička, nový notch a mazlíček na ploše (spec)

Datum: 2026-10-23
Stav: ke schválení
Navazuje na: `2026-10-23-jarvis-design.md` (sekce 9a Notch se tímto nahrazuje)
Předloha: `assets/jarvis-character-reference.png` (obrázek od uživatele, 24 stavů)

## 1. Cíl

JARVIS dostane tvář: roztomilou lesklou černou postavičku („blob“) s bílýma očima, která bydlí v notchi,
má 24 stavů a nálad, otevírá nový velký panel a dá se vytáhnout na plochu jako mazlíček.

### Co řekl uživatel
- Poslal obrázek se stavy 1–24 a novým panelem (viz předloha).
- Mazlíček na ploše: chodí sám, reaguje na myš, dvojklik ho vrátí do notche.
- Schválil: vektorová postavička animovaná kódem (přístup A), notch + panel (část 2), mazlíček + technika (část 3).

### Kritéria úspěchu
1. V klidu z notche koukají jen oči; JARVIS mrká, rozhlíží se a sleduje kurzor.
2. Najetí myší → probudí se → vyklouzne → lišta (chat, mikrofon, nastavení); klik → velký panel jako na předloze.
3. Při „Hey Jarvis“ postavička vyleze a je vidět poslouchá → přemýšlí → pracuje → mluví (+ bublina s textem).
4. Když hraje hudba, tančí do rytmu; po nečinnosti usne; při chybě/limitu/bez internetu ukáže správný stav.
5. Postavičku jde vytáhnout na plochu, chodí po hlavním panelu a oknech, dvojklik ji vrátí.
6. Barva/vzhled jde změnit v Nastavení i hlasem.
7. Screenshoty všech 24 stavů odpovídají předloze (vzhled a výraz, ne pixel po pixelu).

## 2. Postavička (`web/src/character/`)

Jedna komponenta `Blob` (SVG + CSS/JS animace), používá ji notch, panel, mazlíček, dashboard i mobil.

**Anatomie (SVG vrstvy):** stín pod tělem → tělo (lesklá kapka: radiální přechod, horní odlesk, jemná
modrá záře okraje) → oči (2 tvary, morfují mezi výrazy) → doplňky (noty, jiskry, zzz, notebook, sluchátka,
srdíčka, odznak s číslem, ikona wifi, ukazatel průběhu, kolečko „…“, vlny zvuku, hodiny, vykřičník).

**Parametry stavu (`Look`):** `eyes` (open | happy ^^ | sleepy ‿ | closed — | sad | focused | wide),
`gaze` (x, y −1..1, sledování kurzoru), `squash` (stlačení/protažení), `bob` (houpání), `tilt`,
`glow` (síla a barva záře), `accessory` (seznam), `badge` (číslo), `progress` (0–1 | null),
`audio` (true = tělo a vlny reagují na úroveň zvuku). Přechod mezi stavy = interpolace parametrů 250–400 ms
(pružina). Respektuje `prefers-reduced-motion` a nastavení animací.

**Idle život:** dýchání (pomalé škálování), mrknutí každých 3–7 s (náhodně, občas dvojité), občas pohled
do strany, oči sledují kurzor (v notchi i na ploše), po 10 min nečinnosti → spí.

**Vzhledy (personalizace):** `character.color` (black | midnight | violet | rose | white),
`character.glow` (barva záře, výchozí akcent), `character.size` (S | M | L). Nastavení → Vzhled,
hlasem přes `update_setting` (přidat klíče do `SETTABLE_BY_VOICE`).

## 3. Stavy a nálady

| # | stav (`mood`) | kdy (spouštěč) | vzhled |
|---|---|---|---|
| 1 | closed | notch v klidu | jen horní polovina hlavy, oči `— —` napůl schované |
| 2 | idle | klid, okno aktivní | oči `^ ^`/otevřené, mrká, rozhlíží se |
| 3 | hover | myš nad notchem | oči `wide`, mírné vyskočení |
| 4 | opening | přechod do lišty | vyklouznutí dolů, squash |
| 5 | expanded | lišta (chat, mic, nastavení) | celá hlava pod notchem |
| 6 | closing | odjetí myši | zasunutí nahoru |
| 7 | listening | voice state `listening` | vlny zvuku po stranách podle `level`, oči otevřené |
| 8 | thinking | agent `thinking` | oči `sleepy` nahoru, „…“ pod tělem |
| 9 | speaking | `speaking` | oči `happy`, pod tělem vlna podle `level` |
| 10 | dancing | hraje hudba (media.playing) a nic jiného | houpání v rytmu (beat z `level` přehrávání / 120 BPM výchozí), noty |
| 11 | working | agent `acting` (nástroj běží) | notebook, soustředěné oči, ukazatel průběhu (`task_progress`) |
| 12 | success | `tool_end ok` na konci úlohy | jiskry, oči `happy`, 2 s |
| 13 | error | `error` event / nástroj selhal | oči `sad`, červený vykřičník, 4 s |
| 14 | sleeping | 10 min bez aktivity nebo ruční „uspat“ | oči `closed`, zzz, pomalé dýchání |
| 15 | limit | všichni poskytovatelé selhali s 429/limit | červená záře, výstražný trojúhelník, bublina s vysvětlením a radou |
| 16 | offline | PC bez internetu | ikona wifi, šedší záře |
| 17 | updating | stahuje se aktualizace | šipka dolů + ukazatel průběhu |
| 18 | notify | nepřečtené notifikace | zvonek s číslem (`badge`) |
| 19 | dragged | táhneš ji na plochu | protažení ve směru tahu, oči `wide` |
| 20 | desktop_interact | klik/najetí na ploše | otočení k myši, kurzor ikona, vlnka |
| 21 | focus | režim „nerušit“ | sluchátka, oči `closed`, bez animací navíc |
| 22 | personalize | náhled v nastavení vzhledu | řada barevných variant |
| 23 | waiting | `confirm_request` / čeká na tebe | hodiny, jemné houpání |
| 24 | joy | pochvala („díky“, „super“), náhodně ≤1× za hodinu | srdíčka, oči `happy`, poskok |

**Priorita (vyšší vyhrává):** dragged > waiting > error > limit > listening > speaking > working >
thinking > updating > success > offline > focus > notify > dancing > joy > hover/opening/expanded/closing >
sleeping > idle > closed. Krátkodobé stavy (success 2 s, error 4 s, joy 3 s) po vypršení spadnou zpět.

**Kde se počítá:** v jádru `core/jarvis/mood.py` (`MoodEngine`): poslouchá bus (state, tool_end, error,
media, notify, task_progress, settings), drží časovače a publikuje `mood {mood, badge, progress, detail}`
všem klientům. UI-lokální stavy (hover, opening, expanded, closing, dragged, desktop_interact, personalize)
řeší UI samo nad hodnotou z jádra. Nové události protokolu: `mood` (server→klient),
`mood_set {mood}` (klient→server: „uspat“, „fokus“), `pet_command`, `update_status`.

**Bez internetu:** `MoodEngine` každých 15 s ověří síť (HEAD na `https://www.msftconnecttest.com/connecttest.txt`,
záložně `1.1.1.1:443` TCP). **Limit:** router při `AllProvidersFailed`, kde všechny chyby jsou 429/limit/quota,
pošle `error {kind: "limit"}`. **Joy:** agent po odpovědi na zprávu obsahující díky/super/miluju/skvělý.

**Aktualizace:** `core/jarvis/updater.py` 1× denně (a při startu) zkontroluje
`https://api.github.com/repos/adamekk778/JARViS2/releases/latest` (repo je soukromé → bez tokenu nemusí jít;
pak tiše nic). Když je novější verze: notify + v panelu tlačítko „Aktualizovat“ → stáhne `JARVIS-Setup.exe`
(stav updating s průběhem) → po potvrzení spustí instalátor `/SILENT` a JARVIS se ukončí. URL releasu lze
změnit v configu (`general.update_url`).

## 4. Notch (nahrazuje spec 9a)

Okno notche zůstává (pywebview, průhledné, bez taskbaru). Režimy UI:

- **closed/idle** (~200×34): černý notch, postavička zasunutá tak, že ze spodní hrany koukají oči.
  Live activity vpravo zůstává (časovač, hudba) jako malý text.
- **hover** (po 150 ms): notch o 10 % větší, postavička se probudí.
- **bar** (= stav 5, ~360×56): postavička pod notchem uprostřed, vlevo tlačítko chat, vpravo mikrofon a
  nastavení. Klik na postavičku / chat → panel. Odjetí myši → closing (400 ms) → idle.
- **live**: když agent/hlas něco dělá a panel není otevřený: postavička pod notchem v příslušném stavu +
  bublina vpravo (přepis, „⚙ nástroj“, streamovaná odpověď, potvrzovací Ano/Ne). Po skončení 6 s a zpět.
- **alert**: upozornění = postavička ve stavu notify + bublina s textem 5 s.
- **panel**: viz sekce 5.

Tah postavičky z notche dolů o > 60 px → stav dragged → po puštění vznikne mazlíček na ploše (sekce 6) a
v notchi zůstane prázdný výřez (live activity dál funguje).

## 5. Velký panel (`web/src/notch/panel/`)

~1000×330 px, černé sklo, zaoblení 24 px, postavička v „bouli“ uprostřed horní hrany (jako předloha),
vpravo nahoře připnout a minimalizovat.

- **Levé menu:** Chat, Rychlé akce, Systém, Soubory, Nástroje, Nastavení (ikony Phosphor, aktivní = akcent).
- **Chat (výchozí):** střed: „Ahoj{, jméno}! Jak ti dnes můžu pomoct?“ + podtitul, pod tím pole
  (+ příloha, text, mikrofon, odeslat). Po první zprávě se střed přepne na kompaktní konverzaci
  (sdílená `ChatView` v kompaktním režimu, posledních ~20 zpráv), „↗“ otevře velké okno chatu.
  Pravý sloupec: karta Rychlé akce 2×2 (Otevřít aplikaci → předvyplní „Otevři “, Hledat soubory →
  „Najdi soubor “, Shrnout text → vloží schránku „Shrň: …“, Analyzovat obrázek → výběr obrázku);
  když hraje hudba, nad ní karta Právě hraje.
- **Rychlé akce:** mřížka: přehrát/pauza, další, hlasitost ±, ztlumit, screenshot, zamknout, tmavý režim,
  fokus (nerušit), uspat JARVISe, minutky +1/+5/+10/+25, vytáhnout na plochu.
- **Systém:** CPU, RAM, disk, baterie, síť (online/offline), počasí (dnes + 3 dny), verze + aktualizace.
- **Soubory:** police (přetažené soubory: otevřít, zeptat se, na telefon, odebrat), poslední přílohy z chatu,
  velká zóna pro přetažení.
- **Nástroje:** dlaždice kategorií nástrojů (počet), naučené dovednosti, MCP servery se stavem.
- **Nastavení:** rychlé přepínače (hlas, wake word, mluvit nahlas, animace), vzhled postavičky
  (barva, záře, velikost s živým náhledem = stav 22), „Otevřít celé nastavení“.

Panel se zavře: odjetí myši na 400 ms (ne když se píše, je připnutý nebo čeká potvrzení), Esc, klik na
postavičku.

## 6. Mazlíček na ploše

**Okno:** `JARVIS Pet` (pywebview, průhledné, vždy navrchu, bez taskbaru, ~220×220, stránka `/pet`).
Bublina s odpovědí se kreslí ve stejném okně (okno se při bublině rozšíří na ~420×260).

**Fyzika (Python, `core/jarvis/desktop/pet.py`, 30 Hz, čistá logika testovatelná bez Windows):**
- Svět = pracovní plocha monitoru + „plošiny“: horní hrana hlavního panelu (spodek pracovní plochy) a horní
  hrany viditelných nemaximalizovaných oken (EnumWindows, max 15, bez JARVIS oken, ≥ 200 px široké).
- Stavy pohybu: `walk` (40 px/s, otočí se u kraje plošiny), `idle` (3–12 s), `jump` (na okno v dosahu
  ±250 px vodorovně, max 400 px výšky, parabola 0,6 s), `fall` (gravitace 1800 px/s², když plošina zmizí),
  `sit`, `sleep` (po 5 min bez myši/aktivity), `held` (táhne ho uživatel), `return` (let zpět do notche).
- Volby další akce náhodně s váhami; v režimu fokus jen `sit`. Ve fullscreen hře/videu se okno skryje.
- Pozice okna = pozice postavičky; Python volá `window.move()`; směr a fáze pohybu posílá do stránky
  (`pet_state {action, facing}`), stránka animuje nohy/poskoky (blob nemá nohy → „hop-walk“ squash).

**Interakce:** najetí → podívá se na tebe (desktop_interact); klik → poslech (push-to-talk); tažení →
held (sleduje myš), po puštění spadne na nejbližší plošinu; dvojklik nebo puštění < 80 px od notche →
návrat do notche; pravé tlačítko → menu (Chat, Panel, Uspat/Probudit, Zpět do notche).
Stav (na ploše/v notchi, poslední pozice) se pamatuje v configu `character.pet_mode`.

**Mobil:** postavička nahrazuje orb v hlavičce a v prázdném chatu, ukazuje `mood` z PC (bez mazlíčka).

## 7. Testování

- **pytest:** `MoodEngine` (priority, časovače success/error/joy, sleep po nečinnosti, limit z 429,
  dancing jen při hudbě, waiting při confirm), `pet.py` fyzika (chůze a otočení u kraje, pád při zmizení
  plošiny, přistání na okně, nezajede mimo monitor, held → drop → fall, návrat k notchi), updater
  (porovnání verzí, žádná akce bez potvrzení), protokol (nové typy v sync testu).
- **UI:** `npm run build` + screenshoty v Chromiu: galerie všech 24 stavů (`/character-gallery`, jen vývoj),
  notch (closed/hover/bar/live/alert), panel (všech 6 sekcí), pet stránka; vizuální porovnání s předlohou.
- **CI na Windows:** stávající smoke testy exe + nový test, že `/pet` a `/notch` stránky se načtou bez chyb.
- **Ručně na PC:** checklist v README (vytáhnout na plochu, chůze po oknech, návrat dvojklikem).

## 8. Mimo rozsah

- Ručně kreslené Rive/Lottie animace (přístup B), zvukové efekty postavičky, víc mazlíčků najednou,
  mazlíček na telefonu mimo aplikaci (overlay přes jiné aplikace).

## Revize v2 – vzhled 1:1 podle `assets/jarvis-character-reference-v2.png`

- Tělo: lesklá černá „želé kopule“ – téměř kruhová elipsa (rx 90, ry 86) seříznutá rovně dole se zaoblenými rohy.
  Bez obrysu a bez tvrdého bílého odlesku; jen měkké světlo po horní hraně (rim light) a modrá záře na podlaze pod tělem.
- Výchozí barva záře `#4f8dff` (modrá z obrázku), nezávislá na akcentu aplikace.
- Oči: velké svítící bílé ovály níž v těle (66 % výšky); výrazy podle dlaždic – ◠ ◠ (radost/úspěch/tanec/hover),
  přivřená víčka (přemýšlí/limit/fokus), ‿ ‿ (spí), smutná víčka (chyba), srpky ( ) (bez internetu), bez očí + kroužek (aktualizace).
- Doplňky podle dlaždic: modré vlny / tečky / ekvalizér / noty, notebook, modrý ✓ v kroužku, červené ⓘ/⚠/mrak, kroužek aktualizace,
  zvonek s červenou tečkou, čárkovaný rámeček + kurzor s plusem, kurzor, modré ⊖, modré čtyřcípé hvězdy, červené srdce.
