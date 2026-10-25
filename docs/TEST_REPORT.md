# Test report – OMEGA řez 1 (JARVIS 3.6)

Co se opravdu spustilo a s jakým výsledkem. Neověřené věci jsou uvedené zvlášť.

## Automatické testy (Linux, `cd core && pytest`)
- **413 testů prošlo** (0 selhalo). Nové pro OMEGA:
  - `tests/test_omega.py` – mise „stav PC“ end-to-end (plán 4 kroky, 5 kritérií, artefakt se SHA-256, 11 důkazů
    měření + 5 důkazů ověření, stav `verifying` → `done`); ověření odhalí změněný soubor; Windows sonda obsahuje
    jen povolené `Get-*` cmdlety; parsování výstupu sondy (chybná zařízení, neočekávaná vypnutí); restart → mise
    `interrupted`; Skill Forge z mise (schválení, manifest, verze 1 → 2 → návrat = verze 3); reakce postavičky.
  - `tests/test_docs_audit.py` – katalog má přesně 795 položek v 58 sekcích, platné stavy, vygenerovaný audit je
    aktuální, vyloučená značka není v kódu, UI, nativním kódu, CI ani dokumentaci.
- Web: `tsc --noEmit` bez chyb, `vite build` OK; `tests/test_protocol_sync.py` hlídá shodu typů zpráv Python ↔ TS.

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

## Neověřeno / omezení
- Report na Windows mimo CI (různé edice, bez práv správce) – čeká na zpětnou vazbu uživatele.
- Teploty CPU na Windows nejsou bez ovladače výrobce dostupné → report píše „neznámá“ (záměrně, žádný odhad).
- Android: zvonění na zamčeném telefonu a vytáčení ověřeno v emulátoru; přijetí hovoru klepnutím zakryl systémový
  dialog přetíženého emulátoru – ověřit na skutečném telefonu.
