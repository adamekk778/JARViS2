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
