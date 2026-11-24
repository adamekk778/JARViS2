# Integrace

| Integrace | Stav | Jak se připojuje | Kde jsou tajemství | Omezení |
|---|---|---|---|---|
| AI poskytovatelé (Claude, OpenAI, Gemini, Groq, OmniRoute, kompatibilní API) | funkční | Nastavení → Mozek | trezor OS | limity a cena podle poskytovatele; řetěz s náhradou |
| Claude přes oficiální SDK (3.14) | funkční | Nastavení → Mozek → Kdo odpovídá → Claude (klíč sk-ant- z console.anthropic.com) | trezor OS | modely Opus 5.5 / Sonnet 5.5 / Haiku 5.5 / Fable 5.2 přepínatelné v JARVISovi; placené podle tokenů; předplatné Claude Pro/Max klíč nedává |
| Místní modely (Ollama, LM Studio) | funkční, volitelné | Nastavení → Mozek | — | stažení jen ručně; výkon podle GPU |
| Claude Code CLI | funkční | háčky Claude Code → notch/telefon (claude_bridge.py) | — | jen podporovaným rozhraním, bez obcházení limitů |
| MCP servery | funkční | Nastavení → Integrace | trezor OS | nástroje MCP spadají pod oprávnění Internet |
| E-mail (IMAP/SMTP: Seznam, Gmail, Centrum, Atlas, iCloud, vlastní) | funkční | E-mail a telefon | trezor OS (heslo pro aplikace) | odeslání vždy po schválení |
| Kalendář | funkční | vlastní + odběr ICS (jen čtení) | — | zápis do Google kalendáře chybí |
| Telefon (Android) | funkční | QR párování, služba na pozadí | token v nastavení | iOS: viz ROADMAP (omezení platformy) |
| Twilio (skutečný hovor) | volitelné | E-mail a telefon → Twilio | trezor OS | placená služba |
| Home Assistant | funkční | Domov → adresa + dlouhodobý token | trezor OS | zámky/alarm/brány vždy s potvrzením |
| Kurzy ČNB, CoinGecko, Stooq | funkční | bez účtu | — | veřejná data, zpoždění podle zdroje |
| Google Zprávy RSS, Open-Meteo počasí | funkční | bez účtu | — | — |
| GitHub, Google Drive | přes MCP | MCP server | podle serveru | — |
| Blender, Unity, Roblox Studio | jen přes ovládání počítače | — | — | nativní integrace v ROADMAP |
| MHD Praha (PID, Golemio) | funkční s klíčem | Nastavení → Propojení → Golemio | trezor OS | bezplatný klíč z api.golemio.cz; jen Praha |
| Jízdní řády mimo Prahu | chybí | — | — | chybí veřejné API |
| OBS Studio (3.14) | funkční | obs-websocket 5 (OBS 28+), Nastavení → Propojení → OBS | trezor OS (heslo) | scény, nahrávání, stream, uložení posledních chvil |
| PresentMon (FPS ve hrách, 3.14) | volitelné | nainstalovaný PresentMon | — | bez něj se FPS neměří |
| winget (3.14) | připraveno | manifesty v příloze každého vydání | — | zařazení do katalogu = ruční PR do microsoft/winget-pkgs (docs/WINGET.md) |
| Webová stránka (GitHub Pages, 3.14) | připraveno | `site/` + workflow `pages.yml` | — | správce zapne Pages: Settings → Pages → GitHub Actions |
| Hlasové satelity a reproduktory (3.14) | funkční s HA | Home Assistant → integrace Ollama → adresa z „nastav satelit“ | klíč v adrese (jen domácí síť) | ESP32-S3 / HA Voice PE; hlášení přes media_player |
| Frigate NVR (3.14) | volitelné | Domov → Kamery → adresa Frigate | — | osoby na kamerách, zóny; zvonek přes binary_sensor v HA |
| Auto přes Home Assistant (3.14) | funkční s HA | „najdi auto v Home Assistantu“ | trezor OS (token HA) | integrace výrobce (MySkoda, VW, Tesla, BMW, Kia…) nebo OBD přes ESPHome/Torque; odemčení s potvrzením |
| Vysavač a sekačka (3.14) | funkční s HA | domény vacuum / lawn_mower v HA | trezor OS (token HA) | úklid místnosti jen se segmenty (Roborock/Xiaomi); sekačka s potvrzením |
| Health Connect (3.14) | funkční (Android) | aplikace v telefonu → Návyky → Propojit | jen v PC | kroky, spánek, klidový tep, variabilita, kyslík; hodinky musí do Health Connect zapisovat |
| Twilio – AI sekretářka a volání za tebe (3.14) | volitelné, placené | E-mail a telefon → Twilio + veřejná HTTPS adresa | trezor OS (token) | ověřuje podpis Twilia; hovory se vždy představí jako AI; přesměrování u operátora (**61*…#) |
| AeroDataBox (3.14) | volitelné | Propojení → Cesty a zásilky | trezor OS | zpoždění, terminál, gate; bezplatný plán na RapidAPI |
| OpenSky, RainViewer, OSRM, Nominatim (3.14) | funkční | bez účtu | — | veřejné služby s limity (letadla, radar, trasa, geokódování) |
| Česká pošta / Balíkovna (3.14) | funkční | bez účtu | — | veřejné sledování zásilek |
| DPD (3.17) | funkční (neověřeno živě) | bez účtu | — | veřejné sledování DPD; ze sandboxu nedostupné, testováno se simulovanou odpovědí |
| PPL (3.17) | volitelné | Propojení → PPL | trezor OS | oficiální CPL API, Client ID a secret od obchodního zástupce PPL; bez nich odkaz |
| GLS | odkaz | — | — | otevřené sledování GLS zrušilo (API jen po registraci) |
| Spotová cena elektřiny (3.14) | funkční | bez účtu (spotovaelektrina.cz) | — | ceny OTE za MWh, dnes a zítra |
| Have I Been Pwned (3.14) | volitelné | Bezpečí a soukromí | trezor OS | placený klíč; bez něj brífink úniky nekontroluje |
| VB-Cable (tlumočník, 3.14) | volitelné | nainstalovaný ovladač VB-Audio Cable | — | jen Windows |
| DJI Tello (3.14) | volitelné | PC na Wi-Fi dronu | — | limity: 1,5 m, 1 m na pohyb, 2 min, baterie > 25 %; neověřeno na dronu |
| Anonymní statistiky (3.14) | vypnuté | Bezpečí a soukromí → Anonymní statistiky + adresa serveru | — | jen se souhlasem; sběrný server `packaging/stats-worker` (Cloudflare Worker) |
| OctoPrint (3.15) | volitelné | Integrace → Dílna – 3D tiskárna | trezor OS (klíč API „printer“) | stav, pauza, pokračovat, zrušit, nahrání a tisk, snímek z /webcam; neověřeno na skutečné tiskárně |
| Klipper / Moonraker (3.15) | volitelné | Integrace → Dílna – 3D tiskárna (adresa :7125) | trezor OS (volitelný klíč) | print_stats, pause/resume/cancel, upload s tiskem, kamera ze /server/webcams |
| Bambu Lab přes Home Assistant (3.15) | volitelné | integrace ha-bambulab v HA + Dílna | trezor OS (token HA) | stav, pauza, stop, kamera; soubor k tisku jen z Bambu Studia |
| Bambu Lab napřímo (3.17) | volitelné | Integrace → Dílna → Bambu Lab napřímo (LAN) | trezor OS (přístupový kód) | MQTT s TLS 8883, FTPS 990, kamera P1/A1 6000; certifikát tiskárny připnutý při prvním spojení |
| Wear OS hodinky (3.17) | volitelné | spárovaný Android telefon | — | „Zeptej se JARVISe“ jako tichá notifikace s hotovými otázkami; odpověď hlasem z hodinek |
| occt-import-js (3.17) | vestavěné | — | — | STEP v HUD bez FreeCADu; LGPL-2.1, viz docs/THIRD_PARTY.md |
| LiteAPI – hotely (3.18) | volitelné | Propojení → LiteAPI | trezor OS (klíč API) | hledání, prebook s kontrolou ceny, rezervace; platí karta v účtu LiteAPI nebo peněženka; `sand_` = zkušební; neověřeno ostře |
| Duffel – letenky a hotely (3.18) | volitelné | Propojení → Duffel | trezor OS (token) | offer requests, kontrola nabídky, objednávka ze zůstatku, zrušení; Stays: search → quote → booking; neověřeno ostře |
| Booking.com, Airbnb, Google Flights, GetYourGuide (3.18) | bez účtu | prohlížeč JARVISe | — | vyplněné hledání; JARVIS se před platbou vždy zastaví a zeptá |
| GLS (3.18) | volitelné | Propojení → GLS | trezor OS (klíč API) | Track & Trace API s klíčem; bez klíče odkaz |
| Web Push pro iPhone (3.18) | volitelné | webová aplikace na ploše (iOS 16.4+) přes HTTPS (Tailscale / Cloudflare) | klíč VAPID v trezoru OS | šifrování RFC 8291; viz docs/IPHONE.md; neověřeno na iPhonu |
| Wear OS aplikace (3.18) | volitelné | Nastavení → Telefon → Spárovat hodinky (kód 6 číslic) | vlastní klíč zařízení | dlaždice se stavem, otázka hlasem; sestavuje CI, neověřeno na hodinkách |
| OrcaSlicer (3.18) | volitelné | nainstalovaný + profil a filament v Dílně | — | STL → nakrájený 3MF pro Bambu napřímo |
| ČNB kurzy (3.19) | funkční | bez účtu | — | denní kurz pro limity, rozpočet a „kolik je 50 eur“; poslední kurz uložený pro výpadek |
| RegioJet (3.19) | funkční | bez účtu | — | veřejný jízdní řád (spoje, ceny, volná místa); koupě na regiojet.cz v prohlížeči JARVISe |
| IDOS (3.19) | odkaz | bez účtu | — | ČD, Leo Express a další dopravci – otevřené hledání |
| MZV ČR – cestujeme (3.19) | odkaz | — | — | vstupní podmínky jsou shrnutí v JARVISi, k ověření vždy odkaz na MZV |
| PrusaSlicer (3.15) | volitelné | nainstalovaný + profil .ini v Nastavení | — | STL / 3MF → G-code před tiskem |
| OpenSCAD (3.15) | volitelné | nainstalovaný | — | přesné STL z text → CAD; bez něj náhled ze sítě JARVISe |
| FreeCAD (3.15) | volitelné | nainstalovaný (freecadcmd) | — | STEP → OBJ s díly pro HUD |

Kontrola funkčnosti: Nastavení → Mozek (test poskytovatele), E-mail a telefon (stav účtů a spojení s telefonem),
Domov (test Home Assistantu při uložení), Diagnostika.
