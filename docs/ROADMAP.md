# Roadmapa JARVIS OMEGA ∞

Malé ověřitelné milníky; každý končí testy, CI na skutečném Windows a aktualizovaným auditem
(`python docs/audit/build_audit.py`). Pořadí podle priority z OMEGA §6 a §10.

| Milník | Obsah | Akceptační kritéria | Hlavní rizika |
|---|---|---|---|
| **M1 ✔ (3.6)** | Mise s kritérii, artefakty a důkazy; obnova po restartu; read-only report PC; Skill Forge (složené dovednosti, verze, návrat) | report ověřen 5/5 na Windows v CI; dovednost z mise uložena se schválením a jde vrátit na v1; testy `test_omega.py` | rozdíly mezi edicemi Windows v CIM/PowerShellu |
| M2 | Mission Control 2: navázání přerušené mise od posledního kroku, fronta misí, rozpočet (čas/počet volání/cena), export auditu do souboru, dočasná oprávnění | mise přežije restart a pokračuje; překročený rozpočet misi zastaví s důkazem | idempotence kroků, které mění svět |
| M3 | Omega Brain + Agent Swarm: registr agentů (Planner, System, File, Research, Security) nad jedním jádrem, typované zprávy, limity souběhu, per-agent oprávnění, limit nákladů AI, hodnocení jistoty | 2 agenti paralelně na jedné misi s důkazy; Security agent zamítne krok mimo oprávnění | cena a latence modelů |
| M4 | PC Rescue (jen čtení): minidumpy (cdb, pokud je nainstalovaný), časová osa startu, USB/disk diagnostika, body obnovy před změnami se schválením | report „proč se PC seká“ s příčinami z logů; žádná zápisová operace bez schválení | přístup k logům bez admin práv |
| M5 | Paměť 2: projektová paměť, zdroje poznatků, režim bez ukládání, sémantické hledání v povolených složkách (místní embeddingy jen s potvrzeným stažením) | hledání najde dokument podle významu; režim soukromí nic neukládá (test) | velikost modelů, výkon |
| M6 | Device Mesh 2: TLS/relay mimo LAN, revokace jednotlivých zařízení, schránka mezi zařízeními, widgety a akce z notifikací, schvalování misí z telefonu | spárování přes internet bez Tailscale; odvolané zařízení se nepřipojí | bezpečnost relay, baterie telefonu |
| M7 | Controlled Self-Evolution: návrh změny vlastních dovedností na samostatné větvi/sandboxu, měření před/po, testy, diff + schválení + rollback | změna dovednosti projde testy a jde vrátit | nikdy nesahat na kód oprávnění |
| M8 | World Builder a experimentální: Blender/Unity/Roblox přes jejich API, sériový port/Arduino, AR/gesta (jen pokud je HW) | reálný artefakt (soubor modelu/projektu) s důkazem | závislost na nainstalovaných nástrojích |

## 3.14 – „nejlepší JARVIS“ (118 návrhů v 11 dávkách)
Hotovo v kódu s testy: spolehlivost a měření kvality, Claude přes SDK, hlas, paměť s místním vyhledáváním podle
významu, proaktivita, notch, ovládání PC, telefon (odpovědi z hodinek, Android Auto na úrovni oznámení, widget),
propojení (OBS, podepsané balíčky dovedností), bezpečnost (kód v omezeném prostředí, záznam přístupů, režim host,
samooprava dovedností, oprávnění pro každého agenta zvlášť) a dosah (angličtina, winget, web, statistiky se souhlasem).

Co z 3.14 zbývá (a proč):
- **Vlastní aplikace pro Wear OS** – dnes hodinky odpovídají přes oznámení telefonu (RemoteInput); samostatná aplikace ne.
- **Plné Android Auto** – jen oznámení s odpovědí; vlastní obrazovka v autě vyžaduje šablony Car App Library.
- **Geofencing na pozadí** – potřebuje službu s typem location a oprávnění „vždy“; zatím jen v popředí.
- **Plně obousměrná offline synchronizace telefonu a PC** – zatím fronta zpráv odeslaných bez připojení.
- **Klíčové snímky pro animace notche (editor)** a **mazlíček na ploše** (odstraněn ve 3.1).
- **„Hmm, aha“ během poslechu** (zpětná vazba hlasem) – mikrofon by ji nahrál; potřeba echo-cancel.
- **Vlastní velký hlasový model** – potřebuje GPU a token Hugging Face.
- **iOS** – nativní build vyžaduje Mac a účet Apple; zatím PWA.
- **Podpis kódu a Microsoft Store** – CI je připravené (docs/SIGNING.md), certifikát a účet musí pořídit správce.
- **Angličtina** – slovník pokrývá hlavní obrazovky; méně častá místa zůstávají česky a doplňují se postupně.

## 3.18 – cesty a rezervace po potvrzení + 18 vylepšení (37 návrhů v 6 balících)
Hotovo v kódu s testy: samotest integrací v Diagnostice, odkaz s daty po cizím textu se ptá, záznam cizího textu
v Bezpečí, Šifrovat i doma; STL na Bambu přes OrcaSlicer, kontrola před tiskem, bohatší CAD (díry, text, zaoblení,
3MF), fotka a časosběr hotového tisku; rychlejší živý přepis, teplá cache Clauda, průběžné hlášení, rozdělený agent,
hlídání paměti a CPU při dlouhém běhu; GLS s klíčem, „vyzvedni do“, Web Push pro iPhone, aplikace Wear OS s dlaždicí.
Cesty: kritéria z popisu (AI + kontrola), srovnání 3–5 nabídek s důvody, „jako minule“, celá cesta, LiteAPI a Duffel
(hotely, lety), prohlížeč se zastavením před platbou, přednost zrušení zdarma a platby na hotelu, pojistky (dvakrát,
přesná částka z vlastního hledání, telefon s otiskem, limit, měsíční rozpočet, nikdy po cizím textu, nová kontrola
ceny těsně před platbou), kalendář / Cesty / složka cesty, připomínky, hlídání zlevnění, zrušení a změna, zpráva
hotelu, náklady pro účetní, hlídání cen, vstupenky, útrata.

Co nejde nebo zatím není:
- **Test na tvém PC přes Remote Control (A3)** – k téhle cloudové relaci nebyl připojený žádný počítač, takže na
  skutečném Windows u tebe se nic nespouštělo; Windows v CI ano.
- **Ostré rezervace** – LiteAPI i Duffel jsou testované jen se simulovanými odpověďmi podle jejich dokumentace; první
  rezervaci zkus se zkušebním klíčem (`sand_…`, `duffel_test_…`). U Duffel letenek zatím jen jeden cestující (víc lidí
  přes prohlížeč); u Duffel hotelů nevíme dopředu podmínky zrušení, takže se nehlídá jejich zlevnění.
- **Platba kartou přímo z JARVISe** – záměrně ne: JARVIS číslo karty nevidí; platí LiteAPI (karta v tvém účtu) nebo
  zůstatek Duffelu, jinak prohlížeč se zastavením před platbou.
- **E-mail hotelu sám od sebe** – adresu hotelu poskytovatelé nedávají; JARVIS napíše koncept a pošle ho po potvrzení
  na adresu, kterou mu řekneš.
- **Neověřeno na skutečném zařízení:** aplikace Wear OS (sestaví ji CI, na hodinkách nevyzkoušená), Web Push na
  iPhonu, GLS živě (bez klíče API vrací 403), OrcaSlicer s Bambu tiskárnou, časosběr se skutečnou kamerou.

## 3.17 – rychlost doma, chytřejší, bezpečnější, integrace (20 návrhů v 6 balících)
Hotovo v kódu s testy: Windows testy a Android emulátor v CI, měření rychlosti doma; hlas po kouscích, dotaz na AI
s předstihem při váhavé pauze (nástroje až po dořečení), průběžný přepis malým modelem, hodinová cache Clauda s úsporou
v Diagnostice, tvoje tempo, průvodce rychlostí; CAD z popisu (strom tvarů s kontrolou), gesta prsty (MediaPipe),
testy z tvých povelů, přehled a mazání reflexů, vzorové reflexy; cizí text v úkolu už neřídí kroky, které něco mění
(i `use_tool`), kontrola nových rychlých cest; Bambu napřímo (MQTT + FTPS + kamera P1/A1, připnutý certifikát),
STEP v prohlížeči (occt-import-js, LGPL), DPD a PPL živě, otázky z hodinek Wear OS přes notifikace telefonu.

Co nejde nebo zatím není:
- **Aplikace pro iPhone** – nativní build potřebuje Mac s Xcode a placený účet Apple Developer; v tomhle prostředí ji
  nejde sestavit ani podepsat. Zůstává webová aplikace v Safari (mikrofon v Safari jen přes HTTPS).
- **Samostatná aplikace pro Wear OS** (dlaždice, vlastní obrazovka) – otázky z hodinek jdou přes notifikace telefonu,
  které Wear OS zobrazuje; vlastní modul hodinek by potřeboval Android SDK a hodinky k vyzkoušení.
- **GLS živě** – GLS zrušilo otevřené sledování (vyžaduje registraci API); JARVIS drží odkaz.
- **PPL** – oficiální API dává PPL jen firemním zákazníkům (Client ID od obchodního zástupce); bez něj odkaz.
- **Kamera Bambu X1** (RTSP) – záměrně ne: přístupový kód by šel bez kontroly certifikátu; použij adresu snímku.
- **Neověřeno na skutečném zařízení:** tiskárna Bambu (protokol testovaný proti simulované tiskárně přes skutečné
  TLS), DPD a PPL (odpovědi podle veřejných popisů – ze sandboxu byly služby nedostupné), gesta prsty se skutečnou
  kamerou, hodinky Wear OS, změny v Android aplikaci (Java prošla jen kontrolou syntaxe; APK sestaví CI).

## 3.16 – „Odpověď hned“ a nástroje v hlavě (24 návrhů v 7 balících)
Hotovo v kódu s testy: katalog všech nástrojů v cache + `use_tool` (kontrola a oprava parametrů), pokyny rozdělené pro
cache, pevná sada nástrojů pro velkou AI, měření časů kroků a trefy nástroje; paměť nástrojů, reflexy, příklady
z historie, výběr podle významu, podle aplikace a zvyků; přepis při pauze, chytrý konec věty, živý přepis, tvoje
slova, udržovaná spojení a předehřátí; povely s údaji bez AI, bez druhého kola AI, slovo při delší práci, připravené
fráze, rychlá první věta podle změřených časů, odpovědi dopředu; rodiny nástrojů v katalogu a audit; místní reflexní
model; oprava za běhu, „pokračuj“, rychlejší Piper / ElevenLabs, tiché „mhm“.

Co nejde nebo zatím není:
- **AI se nespouští na nedokončené větě** – start s předstihem je přepis a rozhodnutí o konci věty; spustit AI (a tím
  i nástroje) na půlce věty by mohlo udělat něco, co jsi nechtěl.
- **Slučování nástrojů** – audit nenašel skutečné duplicity (podobná jména jsou doplňkové akce), takže se nic
  neslučovalo; katalog jen seskupuje rodiny (úspora ~5 %).
- **Streamování zvuku po kouscích uvnitř věty** (Edge / ElevenLabs) – hlas pořád hraje po větách; zrychlení je
  v udržovaném spojení, kratším prvním kousku, připravených frázích a modelu Flash.
- **Skutečné časy** (o kolik je to rychlejší na tvém PC a s tvou AI) se v kontejneru změřit nedají – ukáže je
  Diagnostika → Rychlost odpovědí po pár desítkách otázek.

## 3.15 – „Mega animace“ a dílna (45 návrhů v 8 balících)
Hotovo v kódu s testy: základ pohybu (úrovně kvality podle grafiky, hlídání FPS, pauza ve hře a na baterii, zvukový
design), Stark HUD ve 3D (reaktor, start, glóbus, paralaxa, telemetrie, orbit nástrojů, ovládání hlasem, Holo),
notch a Mochi (tekutý kov, pružiny, rytmus, emoce, tekutá upozornění, denní doba), chat a aplikace (zhmotnění textu,
živé karty, grafy, přechody, hlasový režim, úvod, barevná schémata), telefon (EDITH AR, start, haptika, SOS, hovor,
widgety), plocha Windows (zaměřovač, paprsek, OSD, „Vítejte zpět“, živá tapeta, holo-plocha), gesta kamerou v HUD
a celá dílna: text → CAD s verzemi a úpravami hlasem, 3D model v HUD s rozloženým pohledem, 3D tiskárna s hlídáním
selhání, deník projektů s díly a nákupním seznamem, simulace (nosník, teplo, obvod, RC/RL). Elektronika (Arduino /
ESP build a upload, sériový monitor, schéma) už byla z dřívějška a deník projektů zapisuje i do ní.

Co je potřeba od uživatele: OpenSCAD (přesné STL z CAD, jinak náhled s mírně zaoblenými hranami), FreeCAD (STEP v HUD),
PrusaSlicer + profil tiskárny (tisk ze STL), OctoPrint / Moonraker nebo Bambu v Home Assistantu, kamera u tiskárny
a AI s obrazem (hlídání tisku), webkamera (gesta).

Co nejde nebo zatím není:
- **STEP přímo v prohlížeči** – knihovna occt-import-js je pod LGPL; nepřidal jsem ji bez souhlasu. Teď přes FreeCAD.
- **Bambu Lab napřímo** (MQTT + FTP s kódem z tiskárny) – jen přes integraci ha-bambulab v Home Assistantu; poslat
  soubor k tisku na Bambu jde z Bambu Studia.
- **Parametrický CAD je šablonový** (krabička, L-držák, deska, sloupek, háček, knoflík) – libovolný tvar z věty
  neumí; na složité díly je .scad, který jde dál upravit.
- **Gesta** jsou pohyb ruky (ne prsty / štípnutí) – rozpoznávání prstů by potřebovalo model pro ruku.
- **Nativní efekty na ploše a živá tapeta** (vrstvená okna, WorkerW) – napsané podle Win32 API, ale **neověřené na
  skutečném Windows** (tady je Linux); stejně tak widgety a animace hovoru v Androidu bez skutečného telefonu.
- **Nic z dílny nebylo vyzkoušené na skutečné tiskárně** – OctoPrint, Moonraker i Home Assistant jen v simulaci.

## 3.14 – „JARVIS jako z filmu“ (58 návrhů, bez sekce C – dílna)
Hotovo v kódu s testy (simulovaná zařízení a služby): hlas a osobnost (živý rozhovor, bez „Hey Jarvis“ přes kameru,
FRIDAY, humor, tlumočník), celý dům (satelity, reproduktory, následuj mě, uvítání, scény, kiosk, víc PC, Docker server,
spotová elektřina), oči a uši (EDITH, obličeje, zvuky, pomocník na obrazovce, letadla), bezpečnost (Frigate, zvonek,
fotka při hlídání, SOS, brífink, dětský režim), zdraví (Health Connect, stav systémů, hlídání u PC), auto přes Home
Assistant, cestovní režim, zásilky, mapa světa v HUD, AI sekretářka a volání za tebe (Twilio), shrnutí chatů, noční
učení, Paměť života, mise na dny, „co když“, vysavač, sekačka a dron Tello.

Co je potřeba od uživatele: webkamera (bez „Hey Jarvis“, obličeje, držení těla), VB-Cable (tlumočník), Home Assistant
(satelity, reproduktory, auto, vysavač, sekačka, zvonek), Frigate (kamery), Twilio + veřejná HTTPS adresa (sekretářka,
volání), klíč AeroDataBox (zpoždění a gate letů), klíč HIBP (úniky e-mailů v brífinku), nouzové kontakty (SOS),
hodinky zapisující do Health Connect, DJI Tello a PC na jeho Wi-Fi, Docker (nonstop server).

Co z „filmu“ nejde nebo zatím není:
- **Sekce C – dílna** – doplněná ve verzi 3.15 (viz výše).
- **Vlastní aplikace pro Wear OS** – hodinky dál odpovídají přes oznámení telefonu (RemoteInput); samostatnou aplikaci
  pro hodinky tady nejde sestavit ani vyzkoušet.
- **Garmin / Fitbit napřímo** – jen přes Health Connect (aplikace Garmin Connect a Fitbit do něj zapisují).
- **OBD adaptér napřímo** – přes Home Assistant (ESPHome / Torque Pro), ne přímo z PC.
- **Zpoždění vlaků** – veřejné API Českých drah / RegioJetu chybí; JARVIS zná jízdní řád z jízdenky.
- **Stav zásilek PPL, DPD, GLS** – jen odkaz na sledování (jejich veřejná API tady nešlo ověřit); Česká pošta a
  Balíkovna živě, Zásilkovna s API heslem.
- **Nic z toho nebylo vyzkoušené na skutečném hardwaru** (kamera, satelity, Frigate, Twilio, auto, vysavač, dron,
  hodinky) – jen s jejich simulací v testech.

## Android vs. iPhone
| Schopnost | Android (dnes) | iPhone |
|---|---|---|
| Chat, hlas, ovládání PC, Domov, seznamy | ✔ | proveditelné jako web/PWA nebo Capacitor iOS build (vyžaduje Mac + Apple účet) |
| JARVIS volá (celoobrazovkový hovor) | ✔ (full-screen intent) | jen přes push notifikaci (APNs) nebo skutečný hovor přes Twilio; CallKit vyžaduje VoIP push |
| Vytáčení, SMS na pozadí | ✔ (se svolením) | ne – iOS aplikaci nedovolí poslat SMS ani volat bez ťuknutí uživatele |
| Zrcadlení oznámení jiných aplikací na PC | ✔ (Notification access) | ne – iOS to aplikacím neumožňuje |
| Najdi můj telefon (hlasitý alarm) | ✔ | jen kritické upozornění se zvláštním oprávněním Apple, jinak Najít iPhone |
| Služba na pozadí | ✔ (foreground service) | omezeno; jen push |

## Co zůstává po M1 (stručně)
Viz `FEATURE_AUDIT.md`: z katalogu 001–795 je 499 položek CHYBÍ a 45 PLÁNOVÁNO. Většina jsou nové domény
(obchod, výuka, multimédia, databáze, herní studio), které dávají smysl až nad Agent Swarm (M3) a Skill Forge.
