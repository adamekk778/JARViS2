# Test report – JARVIS OMEGA (3.6 → 3.9, vlny 1–11)

Co se opravdu spustilo a s jakým výsledkem. Neověřené věci jsou uvedené zvlášť.

## Automatické testy (Linux, `cd core && pytest`)
- **413 testů prošlo** (0 selhalo) – stav k release v3.6.47. Nové pro OMEGA:
  - `tests/test_omega.py` – mise „stav PC“ end-to-end (plán 4 kroky, 5 kritérií, artefakt se SHA-256, 11 důkazů
    měření + 5 důkazů ověření, stav `verifying` → `done`); ověření odhalí změněný soubor; Windows sonda obsahuje
    jen povolené `Get-*` cmdlety; parsování výstupu sondy (chybná zařízení, neočekávaná vypnutí); restart → mise
    `interrupted`; Skill Forge z mise (schválení, manifest, verze 1 → 2 → návrat = verze 3); reakce postavičky.
  - `tests/test_docs_audit.py` – katalog má přesně 795 položek v 58 sekcích, platné stavy, vygenerovaný audit je
    aktuální, vyloučená značka není v kódu, UI, nativním kódu, CI ani dokumentaci.
- Web: `tsc --noEmit` bez chyb, `vite build` OK; `tests/test_protocol_sync.py` hlídá shodu typů zpráv Python ↔ TS.

- **3.9 (vlny 2–11): 568 testů prošlo** (Linux) – nové `tests/test_wave2.py` … `test_wave11.py`: sondy záchrany PC na
  nahraných výstupech Windows, report s ověřením, výkon, síť, bezpečnost; soubory na skutečných souborech; paměť a projekty;
  agenti přes falešný model (stejná cesta potvrzování); učení (SM-2, kontrola výpočtů); komunikace s falešnou schránkou;
  proaktivita; web proti falešnému webu; každodenní pomocníci s falešnou předpovědí; pracovní profily s falešnými okny.

- **3.14 (118 návrhů, 11 dávek): 1747 testů prošlo, 20 přeskočeno** (Linux) – nové `tests/test_*314*.py` (kvalita, evals, mozek,
  hlas, paměť, proaktivita, notch, PC, telefon, propojení, bezpečnost, omezené prostředí, dosah). Navíc:
  - `python -m jarvis.evals --offline --min-score 0.9` – 303 zkušebních otázek, 100 % (brána v CI),
  - `ruff` a `mypy` (vybrané moduly) bez chyb, ESLint bez chyb,
  - `python -m jarvis.uicheck` (Playwright + axe-core) česky i anglicky (`--lang en`): 5 stránek × velikosti bez chyb,
    bez přetékání, anglické rozhraní ověřené na postranním panelu,
  - omezené prostředí ověřené na Linuxu (výpočty a soubory ve vlastní složce projdou; zápis mimo, mazání, programy
    a síť zablokované; 127.0.0.1 není „síť“). Windows Job Object ověří CI na windows-latest.

- **3.14 „JARVIS jako z filmu“ (8 balíků): 1860 testů prošlo, 20 přeskočeno** (Linux). Nové `tests/test_voice_persona.py`,
  `test_house.py`, `test_eyes.py`, `test_safety.py`, `test_body.py`, `test_travel.py`, `test_callagent.py`, `test_mind.py`
  – všechna zařízení a služby simulované (Home Assistant, Frigate, Twilio s ověřením podpisu, AeroDataBox, Česká pošta,
  OSRM, Health Connect data, dron Tello přes falešné UDP spojení). Navíc:
  - evals 371 zkušebních požadavků, 100 % (brána v CI),
  - `ruff`, `mypy` (67 souborů včetně všech nových modulů), ESLint, `tsc`, `vite build` bez chyb,
  - `python -m jarvis.uicheck` česky i anglicky: 10 stránek × velikosti bez chyb,
  - mapa světa v HUD ověřená v prohlížeči (Playwright): skutečné dlaždice OpenStreetMap a živý radar RainViewer,
  - veřejné API České pošty ověřené živým dotazem; DPD, GLS a OpenSky odsud nedostupné (jen simulace).
  - **Neověřeno na skutečném hardwaru:** webkamera, VB-Cable, satelity, Frigate, Twilio, auto, vysavač, sekačka,
    dron, hodinky, Docker na Raspberry Pi.

- **3.15 „Mega animace“ a dílna (8 balíků, 45 návrhů): 1914 testů prošlo, 20 přeskočeno** (Linux). Nové
  `tests/test_fx.py` (úrovně efektů, FPS, snímky efektů na ploše, háčky klikání jen když JARVIS pracuje, OSD,
  „Vítejte zpět“, /wallpaper) a `tests/test_dilna.py` (CAD: všechny šablony dávají uzavřenou síť se správnou
  orientací, objem krychle a trubky proti vzorci, platné binární STL, úpravy česky, verze a návrat; knihovna modelů
  neposkytne nic mimo svou složku; STEP přes FreeCAD s falešným spuštěním; OctoPrint a Moonraker přes simulované
  HTTP; Bambu z entit HA; hlídání tisku: dvakrát špatně → pauza a upozornění s tlačítky; deník projektů a nákupní
  seznam; nosník, teplo s energetickou bilancí, obvod a RC proti učebnicovým hodnotám; gesta do HUD). Navíc:
  - web unit testy (`npm test`): úrovně efektů, zvuky, rozdělení STL na díly, rozložený pohled,
  - evals 401 zkušebních požadavků, 100 %; `ruff`, `mypy` (77 souborů), ESLint, `tsc`, `vite build` bez chyb,
  - `python -m jarvis.uicheck` česky i anglicky: 10 stránek × velikosti bez chyb,
  - v prohlížeči (Playwright, softwarové WebGL): 3D reaktor, glóbus, živá tapeta (reaktor i glóbus), prohlížeč modelu
    v HUD se skutečným STL z CAD (krabička + víko = 2 díly, rozložení zamáváním, otočení), ukazatel tisku,
    karta Dílna v Nastavení,
  - snímky efektů na ploše vykreslené a zkontrolované (zaměřovač, OSD, uvítání).
  - **Neověřeno na skutečném hardwaru / Windows:** vrstvená okna efektů a živá tapeta za ikonami (WorkerW), widgety
    a animace hovoru v Androidu, skutečná 3D tiskárna (OctoPrint / Klipper / Bambu), OpenSCAD, FreeCAD a PrusaSlicer
    (volání napsaná podle dokumentace, testovaná se simulovaným spuštěním), gesta se skutečnou webkamerou.

- **3.19 (4 dávky, 17 návrhů + doplňky): 2130 testů prošlo, 24 přeskočeno** (Linux). Nové `tests/test_money319.py` (kurz ČNB:
  použití, uložení pro offline a co se o něm řekne; limity s kurzem ČNB; co je platba – rezervace, vrácení, nákup na
  obrazovce, tlačítko v prohlížeči podle skutečného textu; vždy dvakrát a nikdy s plnou důvěrou; vrácení peněz se ptá
  dvakrát a zapíše se; cizí text vrácení nespustí; nákup na obrazovce dvakrát; návrhy agentů na platbu ne hromadně
  a s druhým potvrzením; přehled peněz; zkušební rezervace jen se zkušebním klíčem), `test_travel319.py` (vstupní
  podmínky, RegioJet se simulovanými odpověďmi, vlak/autobus s IDOS, spolucestující i v 7. pádě a letenka pro dva,
  soukromí spolucestujících, ubytování z e-mailu a e-mail, který rezervace není, zpoždění → hotel jednou, cestovní
  karta, stravné podle zákoníku práce), `test_share319.py` (hodinky: cesta a čekající platba; odkaz pro rodinu bez
  ceny a čísla rezervace, vyprší, jde zrušit, vždy se ptá). Navíc:
  - evals 446 (100 %); `ruff`, `mypy` (115 souborů), ESLint, `tsc`, `vite build` bez chyb; `python -m jarvis.uicheck`
    česky i anglicky bez chyb,
  - CI: testy na Windows rozdělené do dvou souběžných částí (`JARVIS_TEST_SHARD`), novější akce GitHubu,
  - **Neověřeno ve skutečnosti:** ČNB a RegioJet jen se simulovanými odpověďmi v testech (živě odpovídaly), skutečné
    e-maily z Booking.com / Airbnb, odkaz pro rodinu přes veřejnou adresu, dlaždice na hodinkách; test na tvém PC
    (žádný počítač připojený).

- **3.18 (6 balíků, 37 návrhů): 2099 testů prošlo, 24 přeskočeno** (Linux). Nové `tests/test_travel318.py` (26 testů: kritéria z popisu
  a jejich kontrola, pořadí nabídek s důvody, „jako minule“, hledání přes LiteAPI a Duffel se simulovanými odpověďmi
  podle jejich dokumentace, rezervace s novou kontrolou ceny těsně před platbou – posunutá cena nic nezaplatí, limit,
  měsíční rozpočet a chybějící údaje platbu zastaví, špatná částka se ani nezeptá, cizí text rezervaci nespustí,
  vždy dvakrát i s plnou důvěrou, potvrzení ukazuje skutečnou nabídku a jde na telefon, prohlížeč se před Zaplatit
  zastaví; zrušení, letenka Duffel s objednávkou ze zůstatku a zrušením, hotel Duffel se sazbou, kterou jsi viděl;
  připomínky jen jednou, pas, zlevnění zarezervovaného hotelu, hlídání cen, útrata, stránka Cesty jen v PC, údaje
  cestujícího se neposílají do telefonu), `test_secure318.py`, `test_dilna318.py`, `test_speed318.py`, `test_phone318.py`.
  Navíc:
  - evals 438 (86 okamžitých povelů, 14 nových cestovních), 100 %; `ruff`, `mypy` (110 souborů), ESLint, `tsc`,
    `vite build` bez chyb; `python -m jarvis.uicheck` bez chyb včetně nové stránky Cesty,
  - opravené chyby z CI: snímky časosběru se na rychlém stroji přepsaly (stejná milisekunda) a na Windows zůstal
    otevřený první snímek; kontrola obrazovky hovoru v emulátoru hledala na špatném místě,
  - **Neověřeno ve skutečnosti:** ostré rezervace u LiteAPI a Duffel (jen simulované odpovědi), aplikace Wear OS na
    hodinkách (sestavuje ji CI), Web Push na iPhonu, GLS s klíčem, OrcaSlicer s Bambu, test na tvém PC přes Remote
    Control (žádný počítač nebyl připojený).

- **3.17 (6 balíků, 20 návrhů): 2034 testů prošlo, 24 přeskočeno** (Linux). Nové `tests/test_smart317.py` (vzorové
  reflexy, přehled a mazání naučeného, kontrola tvých povelů po aktualizaci, CAD z popisu: kontrola stromu, objem
  a uzavřená síť, návrh a úprava s druhým pokusem, model ruky jen celý stažený a jen z tohoto PC, hodnoty gest),
  `test_safe317.py` (cizí text: čtení volně, změny s dotazem i s plnou důvěrou, `use_tool` mimo nabídnuté nástroje,
  obrázek a schránka jako cizí text, nic se nenaučí; pravidlo shodné s Režimem jen pro čtení pro každý nástroj),
  `test_bambu317.py` (simulovaná tiskárna přes **skutečné TLS**: MQTT stav, příkazy, kamera, připnutí certifikátu –
  jinému zařízení přístupový kód nikdy neodejde, špatný kód, nahrání .3mf a start tisku), `test_parcels317.py`
  (DPD a PPL se simulovanými odpověďmi, token PPL se drží, bez přístupu jen odkaz), `test_watch317.py` (hodinky)
  a webové `handgest.test.ts` (čtení prstů) a `stepload.test.ts` (skutečný OpenCascade ve WebAssembly převede ukázkovou
  kostku 10 mm a sestavu na 18 dílů). Navíc:
  - evals 424 (86 okamžitých povelů), 100 %; `ruff`, `mypy` (95 souborů), ESLint, `tsc`, `vite build` bez chyb,
  - `python -m jarvis.uicheck` česky i anglicky bez chyb; okno „Co je nového 3.17“, karta „Co se JARVIS naučil“,
    přepínač Gesta prsty a nastavení Bambu napřímo ověřené v prohlížeči (bez chyb stránky),
  - Java v Android aplikaci prošla jen kontrolou syntaxe (`javac` bez Android SDK); APK sestaví CI.
  - **Neověřeno ve skutečnosti:** tiskárna Bambu (jen simulace protokolu), DPD a PPL živě (služby byly ze sandboxu
    nedostupné, PPL navíc potřebuje firemní přístup), gesta se skutečnou kamerou, hodinky Wear OS, rychlost na tvém PC
    (ukáže Diagnostika → Změřit rychlost).

- **3.16 „Odpověď hned“ (7 balíků, 24 návrhů): 1961 testů prošlo, 20 přeskočeno** (Linux). Nové `tests/test_toolbrain.py`
  (katalog s každým nástrojem, neměnná část pokynů stejná pro hlas i chat, `use_tool` s opravou a kontrolou parametrů,
  přesný popis a druhý pokus po chybě, potvrzení u rizikové akce, router posílá katalog jen velké AI, cache u Clauda,
  měření kroků; paměť nástrojů, reflex bez volání AI, oprava „ne, to ne“, žádný reflex u čísel / rizika / tajemství,
  příklady, obrazovka, zvyky, vyhledávání podle významu s falešným modelem), `test_fastear.py` (přepis při pauze,
  konec hotové / rozdělané věty, starý odhad po dalších slovech, slovník, udržovaná spojení, předehřátí),
  `test_instant316.py` (povely s háčky, co jde k AI, bez druhého kola AI, „Moment, pane.“, fráze z paměti, odpovědi
  dopředu, rodiny a audit, reflexní model) a `test_talk316.py` (oprava za běhu, „pokračuj“, co uživatel neslyšel,
  Piper načtený jednou, ElevenLabs Flash, „mhm“). Navíc:
  - evals 419 (86 okamžitých povelů), 100 %; `ruff`, `mypy` (85 souborů), ESLint, `tsc`, `vite build` bez chyb,
  - `python -m jarvis.uicheck` česky i anglicky bez chyb; Diagnostika s blokem „Rychlost odpovědí“ a okno
    „Co je nového 3.16“ ověřené v prohlížeči.
  - **Neměřeno ve skutečnosti:** o kolik je odpověď rychlejší s tvou AI, mikrofonem a sítí – to ukáže Diagnostika →
    Rychlost odpovědí po pár desítkách otázek; místní model e5-small a reflexní model v Ollamě testované jen s
    falešnými odpověďmi.

## Ruční / vizuální ověření (Playwright proti skutečnému serveru)
- Úkoly → **Zkontrolovat PC**: mise doběhla, 5/5 kritérií zelených, artefakt „Report o stavu PC“ s otiskem,
  11 důkazů, audit akcí. **Uložit jako dovednost** → schválení → protokol „Kontrola PC“ v1 → Stark → Verze ukazuje v1.
- Bez chyb v konzoli prohlížeče.

## Na skutečném Windows (GitHub Actions, windows-latest)
- Notch, celý chat, HUD, UI Automation, označený text v Notepadu (oprava a nahrazení), seznam běžících aplikací,
  `arp -a`, benchmark nečinnosti (CPU ~1 %, RAM ~73 MB) – **prošlo**.
- `--selftest-report` (read-only diagnostika + ověření souboru): první verze se na Windows **zasekly**. Výpis fází
  ukázal, že sběr dat i zápis reportu trvají jen 4,5 s; zasekl se až konečný výpis výsledku – přesměrovaný výstup na
  Windows má kódovou stránku cp1252, česká písmena (č, ř, ě) ho shodila a ladicí build pak čekal na potvrzení
  chybového okna. Opraveno (ASCII výpis ve všech selftestech) a navíc zpevněno spouštění pomocných procesů (bez
  stdin, výstup do souboru, tvrdý limit) a pojistky v CI (4 min / 15 min).
- **Výsledek po opravě (běh 40206274484, release v3.6.47): report na skutečném Windows ověřen 5/5 za 5,8 s, všech
  11 částí změřeno (žádná „neznámá“), použité příkazy jen Get-*; build, instalátor i APK zelené.**

- **3.9 na windows-latest (běh 40223109409):** testy na Windows prošly (504 + 1 přeskočen; jeden test předtím padal na
  kódování cp1252 – opraveno, texty v testech se čtou/zapisují jako UTF-8). `--selftest-rescue`: **všech 11 sond vrátilo data**
  (ovladače 5,9 s, pády, aplikace, start, USB, disky, služby, bezpečnost 7,8 s, síť, obnova, zařízení), report ověřen 4/4,
  měření výkonu (CPU 3,9 %, grafika 5,9 %), test výkonu, celkem 41 s. Benchmark nečinnosti: CPU 0,63 %, RAM 75 MB.
- Co samotest odhalil a co je opravené: na Windows Serveru chybí log doby startu a body obnovy (hlášky teď říkají pravdu
  místo „smí jen správce“); když JARVIS spustí PowerShell 7, Windows PowerShell 5.1 nenačetl modul s
  Get-AuthenticodeSignature – pomocné PowerShelly se teď spouštějí bez proměnné PSModulePath.
- Sestavení 3.8 se jednou zaseklo v PyInstalleru (přes 27 min, normálně 4–5 min, lokálně 3,4 min); další běh prošel normálně.
  Krok má nově limit 25 min, aby případné zaseknutí skončilo s logem.

## Neověřeno / omezení
- Report a záchrana PC na Windows mimo CI (různé edice, bez práv správce) – čeká na zpětnou vazbu uživatele.
- Pracovní profily (rozložení oken) ověřuje samotest jen na Poznámkovém bloku; víc monitorů v CI není.
- Hledání podle významu potřebuje místní model na embeddingy v Ollamě; porovnání modelů aspoň dva poskytovatele AI.
- Teploty CPU na Windows nejsou bez ovladače výrobce dostupné → report píše „neznámá“ (záměrně, žádný odhad).
- Android: zvonění na zamčeném telefonu a vytáčení ověřeno v emulátoru; přijetí hovoru klepnutím zakryl systémový
  dialog přetíženého emulátoru – ověřit na skutečném telefonu.
