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
