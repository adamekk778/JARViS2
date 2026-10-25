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
