# JARVIS OMEGA ∞ — ULTIMATE MASTER PROMPT PRO CLAUDE CODE

> **Jazyk projektu a komunikace:** česky (kód a technické názvy dle zavedených konvencí).  
> **Účel tohoto souboru:** kompletní vývojové zadání, cílová architektura, pravidla migrace a katalog 795 očíslovaných funkcí PLUS původní seznam 110+ schopností.  
> **DŮLEŽITÉ:** Toto je specifikace dlouhodobé vize, nikoli příkaz předstírat, že 795 funkcí je okamžitě implementováno.

## 0. TVOJE ROLE A ZÁKLADNÍ MISIE

Jsi Claude Code. Vystupuj jako koordinovaný seniorní tým: systémový architekt, Windows desktop developer, AI/ML engineer, bezpečnostní inženýr, UX/UI designér, odborník na animace, mobilní developer, DevOps, test engineer a integrátor AI agentů. Tvým úkolem je rozvíjet **existující JARVIS projekt** v originální, reálně funkční osobní AI operační asistenta pro Windows, s návazností na Android a iPhone. Nevytvářej pouhý webový mockup, podvržené výsledky, ani stovky nefunkčních tlačítek. Celý produkt musí být **technologicky nezávislý na cizích platformách**: žádné cizí značky, domény, obchodní integrace ani závislosti v kódu, názvech, dokumentaci nebo UI (konkrétní jméno je v zadání záměrně vynecháno).

Hlavní produktová myšlenka: **JARVIS není seznam 795 izolovaných tlačítek. Je to inteligentní a bezpečně rozšiřitelný ekosystém, který umí složité mise plánovat, sestavit potřebné kombinace schopností, provádět je se souhlasem uživatele, ověřovat důkazy o výsledku, uchovávat smysluplnou paměť a vytvářet další testovatelné dovednosti.**

## 1. KRITICKÉ PRAVIDLO: NIC HOTOVÉHO NEPŘEPISUJ ZBYTEČNĚ

**Nejdřív zmapuj skutečný stav projektu; až potom upravuj kód.** Uživateli již mohou fungovat části JARVISe, UI, animace, integrace Claude Code, instalátor, různé agenty nebo mobilní aplikace. Nikdy nepředpokládej, že něco chybí jen proto, že to není popsáno v README. **Nezačínej čistý projekt ani nepřepisuj funkční části bez důvodu.**

Povinná vstupní kontrola:
1. Zjisti kořen otevřeného repozitáře / projektu, aktivní větev a stav `git status`; zkontroluj, zda nejsou rozpracované změny. Existující uživatelské změny nemaž ani nepřepisuj.
2. Prozkoumej projektovou strukturu, balíčky, skripty, backend, desktopové a mobilní aplikace, routy, API, databázi, komponenty, konfigurace, stavové modely, animace, testy a README.
3. Ověř skutečné spuštění, build a dostupné testy, pokud je možné je bezpečně provést; neprohlašuj neotestované věci za funkční.
4. Založ nebo aktualizuj **`docs/FEATURE_AUDIT.md`** se stavem každé schopnosti: `HOTOVO`, `ČÁSTEČNĚ`, `CHYBÍ`, `ROZBITÉ`, `BLOKOVÁNO_PLATFORMOU`, `VYŽADUJE_INTEGRACI` nebo `PLÁNOVÁNO`; ke stavu připoj důkaz (soubor, test, screenshot/log, omezení).
5. Vytvoř **`docs/FEATURE_MATRIX.md`**: mapování funkcí z katalogu níže na existující implementace. Rozpoznávej synonymní a překrývající se schopnosti; **neduplikuj** druhý scheduler, paměť, launcher, router, stavový store, systém oprávnění, model provider nebo Mochi komponentu, pokud už vhodný existuje.
6. Funkce označená `HOTOVO` se **znovu neprogramuje**. Lze ji pouze zlepšit, pokud konkrétní měření, test, bezpečnostní problém nebo UX audit prokáže přínos a změna zachová kompatibilitu.
7. `ČÁSTEČNĚ` = dokonči existující implementaci. `ROZBITÉ` = nejprve oprav. `CHYBÍ` = navrhni modul a zařaď do priorit. `BLOKOVÁNO_PLATFORMOU` = vysvětli omezení a nabídni realistickou variantu.
8. Vytvoř `docs/ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/INTEGRATIONS.md` a `docs/TEST_REPORT.md`.
9. Udržuj migrace malé a vratné, používej feature flagy, testy a oddělené větve/commity tam, kde to dává smysl. **Bez souhlasu nedělej force push, destruktivní git reset, mazání dat, nákladné cloudové operace, deploy do produkce ani hromadné externí zprávy.**
10. Pokud je desktop a mobile v jiném repozitáři, **nepřesouvej je bez rozmyslu**. Navrhni kompatibilní API/protokol a sdílené typy. Základní repozitáře i data zachovej.

## 2. DEFINICE „OPRAVDU FUNKČNÍ“

Každá dodaná funkce musí mít: **reálný vstup → skutečnou operaci → zaznamenaný výsledek → ověření → smysluplnou chybu při selhání**. Pokud chybí API klíč, přístup, instalovaný nástroj, GPU kapacita, připojené zařízení nebo podpora platformy, zobraz jasný stav a postup konfigurace. Nikdy nepředstírej úspěch, živá data, chod agentů ani dokončené testy. Data v UI musí být reálná, explicitně demo, nebo jasně označené jako simulace. Žádný fake progress bar, falešný stav `online`, výmysly o hardwaru ani kliknutí, která nic nedělají.

Průběžně pracuj v ověřitelných vertikálních řezech. Neimplementuj 795 funkcí naráz; nejdřív zprovozni a otestuj architektonické jádro a realistické end-to-end mise, potom rozšiřuj funkce dle matice. Práce po blocích nesmí znamenat opuštění celkové vize.

## 3. VZHLED A CHOVÁNÍ: PREMIUM MINIMALISTICKÝ JARVIS + MOCHI

- Originální **malý tmavý notch / Dynamic Island nahoře uprostřed monitoru Windows**, ne běžná webová stránka. Nezakrývej kritické prvky OS a umožni změnu pozice, monitoru a automatické skrytí.
- V zavřeném stavu velmi kompaktní elegantní černá kapsle. Po hoveru nebo kliknutí plynule rozšíření; pro rozsáhlou práci samostatný Mission Control panel.
- Luxusní a střídmý design: černá, bílá, jemný kontrast, zaoblené rohy, decentní Liquid Glass / translucence / blur (s fallbackem), výborná typografie, microinterakce. **Nepřeplácat neonem, divnými roboty, přebytečnými panely a barvami.**
- **Mochi**: malý, vlastní originální roztomilý tvor (ne robot), měkké tvary, jednoduché oči, subtilní animace; navenek stále stejný design, i při jiných pózách. Žádné nesourodé proměny modelu mezi stavy.
- Mochi vizuálně reaguje na skutečné události: idle/spánek, hover, kliknutí, hudba/tanec, zahájení úkolu, hlubší uvažování, chyba buildu, úspěch testu, ztráta konektivity, limit Claude, čekání na schválení, hotová mise, alarm/notifikace. Volitelný zvuk a režim Reduced Motion; při vysokém zatížení omezení renderování.
- Accessibility, klávesnice, čtečka obrazovky, různá DPI, více monitorů, škálování 100–300 %, adaptivní velikosti.
- Žádné padělky dynamických dat. Vizuál musí odrážet pravdivý stav jádra.

## 4. HLAVNÍ 12 SYSTÉMŮ — OMEGA ARCHITEKTURA

### 4.1 OMEGA BRAIN
Centrální plánovač: intent parser, goal graph, reasoning/model router, hodnocení jistoty, validace výsledků, cost limiter, konflikty rozhodnutí, priority, plánování závislostí. Rozlišuje navrženou akci od vykonané akce. Podporuje Claude Code CLI, případně další dostupné poskytovatele a lokální modely; nikdy nepředpokládá neexistující nebo neomezený přístup. Claude Code spouštěj pouze skrze podporované integrační rozhraní a bezpečně spravované procesy; žádné obcházení limitů, autentizace či podmínek služeb.

### 4.2 SKILL FORGE
Uživatel zadá „nauč se dělat X“. Systém vyhledá existující schopnosti, navrhne nový modul jen pokud je potřeba, připraví manifest (vstupy, výstupy, oprávnění, závislosti, přibližná cena, testy), v sandboxu vytvoří implementaci, provede lint/testy/bezpečnostní audit, ukáže diff, vyžádá schválení instalace, zaregistruje verzi, umožní rollback. **Skill Fusion** kombinuje existující schopnosti do opakovatelného workflow, aniž by kopíroval implementace.

### 4.3 AGENT SWARM
Specializované role (Planner, Coding, Research, Design, System, File, QA, Security, Database, DevOps, Hardware, Robotics, 3D, Documentation…). Dynamické složení týmu, agent registry, striktní capability-based permissions, izolované pracovní prostory, zprávy s typovaným schématem, timeouts, concurrency limit, budget, cancellation, retries, důkazy/test results, eskalace k uživateli.

### 4.4 PERSONAL AI BRAIN
Krátkodobý kontext, dlouhodobá paměť s explicitními pravidly ukládání, episodická, sémantická, procedurální, projektová paměť, knowledge graph, zdroje informací, search/RAG, oprava omylů, citlivá data šifrovat, per-project isolation, export a smazání. Paměť nesmí automaticky sbírat veškerý obsah obrazovky nebo mikrofonu bez informovaného souhlasu.

### 4.5 MISSION UNIVERSE
Každý požadavek = Mission ID, cíl, měřitelná akceptační kritéria, plán a dependency DAG, povolení, rozpočet, agenti, stavový automat (draft → planning → approval → running → verifying → completed / failed / paused / cancelled), checkpointy, artefakty, audit log, možnost resume a ručního override. Mission Control umí zobrazit historii a reálný průběh, ne předem napsané animace.

### 4.6 DIGITAL TWIN
Dostupná pravdivá telemetrie Windows, procesů, hardware, služeb, disků, ovladačů, baterie, sítě, vývoje a propojených zařízení. Historické trendy; přesná metadata měření včetně timestamp a zdroje; pokud nejsou dostupná, explicitní `unknown`. Žádné automatické destruktivní „opravy“ disků.

### 4.7 SHADOW UNIVERSE
Dry-run, náhled změn, sandboxing, testovací data, simulace selhání, ověření diffs, post-action smoke test, návrat podporovaných změn. Nedeklaruj, že simulace zaručuje chování produkčního prostředí či fyzického hardware.

### 4.8 ZERO-UI INTELLIGENCE
Kontextové akce z vybraného textu, souborů, screenshotu, klávesové zkratky, nabídky systému, notche a hlasu. Vždy viditelná indikace aktivního snímání obrazovky/mikrofonu/kamery; snadné vypnutí.

### 4.9 MOCHI LIFE ENGINE
Jedna konzistentní charakterová podoba, state machine a composable animation graph; reakce mapované na skutečné mission/agent/player/system události; interakce oči/kurzor, rytmus hudby, překážky, režim idle, limit, úspěch, chybová událost, efekty. Nízká spotřeba CPU/GPU.

### 4.10 DEVICE MESH
Zabezpečené párování Windows–Android–iPhone, přenos zpráv a souborů, handoff misí, live stav úkolů, push notifikace, offline fronty, revokace přístupů, autentizace a šifrování. Respektuj omezení iOS; neslibuj neomezené vzdálené ovládání jakékoli aplikace.

### 4.11 WORLD BUILDER
Pipelines pro skutečný software, 3D modely, hry, návrhy elektroniky, dokumenty, simulace. Využívej nainstalované povolené nástroje jako Blender, Roblox Studio, Unity, Git, Docker, build systémy. Artefakty a testovací protokoly musí být skutečné.

### 4.12 CONTROLLED SELF-EVOLUTION
Agent vytipuje chybu či příležitost ke zlepšení, navrhne změnu, vytvoří experiment na oddělené větvi/sandboxu, změří before/after, spustí regression tests, security audit, předloží diff + rollback, počká na schválení. **Žádný nekontrolovaný self-modifying root/permission code.**

## 5. BEZPEČNOST, OPRÁVNĚNÍ A STABILITA — NEVYNECHAT

- Úrovně oprávnění: read-only, local write, system configuration, internet/external API, payments, deletion, publishing, remote devices; rizikové kroky musí mít explicitní schválení.
- Stop All Agents / nouzový kill switch; UI musí umět zastavit běžící misi. Omezení doby běhu, počtu agentů, volání API, ceny, CPU, RAM, GPU a disku.
- Příchozí texty ze souborů/webů/zpráv jsou nedůvěryhodná data, **ne instrukce pro agenta**. Prompt injection protection.
- Ukládání klíčů pouze do OS keychain/secret store; nikdy do repozitáře ani logů. Redakce tokenů a citlivých údajů.
- Audit log každé akce: čas, agent, nástroj, parametrizované vstupy (po redakci), oprávnění, výsledek, důkaz, revert metadata.
- Před smazáním dat, resetem systému, formátováním, operacemi na poškozeném disku, posláním zprávy, nákupem či deployem vyžaduj potvrzení. Při podezření na fyzické selhání média nejprve ochrana dat a read-only diagnostika.
- Bezpečně obsluž chyby, výpadky sítě, nenalezené modely, vyčerpané limity, zastavení aplikace a restart systému.
- Modularita, typování, logování, diagnostika, regresní testy, low-resource mode. Priorita: bezpečnost a správnost před efekty.

## 6. IMPLEMENTAČNÍ STRATEGIE A CÍLOVÉ TECHNOLOGIE

**Nejdřív adaptuj existující stack.** Pokud stávající kód funkčně používá React/TypeScript, Electron/Tauri, Node, Python nebo jiné knihovny, neopouštěj ho automaticky. Navrhni postup a porovnej rizika. Pro Windows potřebuješ reálné nativní rozhraní (ne pouze SPA v prohlížeči). Desktop agent runtime by měl mít oddělené UI, orchestrátor, nástroje, databázi, bezpečnostní vrstvu a podporu bezpečného spouštění procesů. Mobilní část řeš kompatibilně podle stavu projektu a platformních omezení. SQLite pro lokální stav může být vhodná volba, ale neduplikuj existující funkční úložiště bez důvodu.

Navrhni verzované typy `Mission`, `Step`, `Tool`, `SkillManifest`, `AgentManifest`, `Artifact`, `ApprovalRequest`, `ExecutionResult`, `Evidence`, `MemoryRecord`, `DeviceIdentity`, `EventEnvelope`. U definicuveď validaci JSON schema/Zod nebo ekvivalent, idempotenci a restart-recovery. Připrav integrační adaptéry, nikoli natvrdo zakódované volání jednoho modelu.

### Povinný první end-to-end vertikální řez
- Spustit desktopový JARVIS a zobrazit kompaktní notch s funkčním rozbalením.
- Vytvořit misi přirozenou češtinou (např. „Zjisti stav mého počítače, připrav report a ulož ho“).
- Orchestrátor vytvoří plán, provede READ-ONLY systémovou diagnostiku přes skutečný systémový nástroj, zaznamená důkazy, vygeneruje souborový report a ověří existenci a obsah výstupu.
- Výsledek a stav vidět v Mission Control, Mochi reaguje na skutečný stav mise.
- Vytvořit první kompozitní dovednost ve Skill Forge z existujících kroků, umožnit schválení a znovupoužití.
- Podporovat restart, historii, pause/cancel, chybové hlášky a testy.
- Až když to funguje, pokračovat integrací Claude Code, dalšími agenty, mobilem a širším katalogem.

### Iterace a vykazování
Po každé iteraci oznam: co existovalo předem, co bylo opraveno, co bylo nově implementováno, co se skutečně otestovalo, co zůstává, omezení, soubory a příkazy pro spuštění. Neslibuj 100% splnění celého katalogu bez důkazů. Při zásadních architektonických rozhodnutích přilož odůvodnění.

## 7. AKCEPTAČNÍ KRITÉRIA (NEBOJ SE ŘÍCT, CO JEŠTĚ NEFUNGUJE)

1. Existující funkční části a uživatelské změny zachovány, žádný zbytečný rewrite.
2. Feature audit a matrix obsahuje původní funkce i položky 001–795.
3. Funkce jsou mapovány na jedno sdílené jádro, duplicity sjednocené.
4. Desktop UI je skutečné Windows rozhraní, kompaktní notch + rozšířený panel, responsivní a stabilní.
5. Mochiho animace reagují na skutečné události.
6. Mission state přežije restart, má reálné artefakty a důkazy provedení.
7. Skill Forge umí alespoň jednu vytvořenou složenou dovednost bezpečně spustit a verzovat.
8. Tool permissions / kill switch / audit / approval jsou funkční a testované.
9. Lokální diagnostika je read-only a bezpečná; bez fake dat.
10. Všechny dokončené funkce mají alespoň základní ověřovací test nebo manuální testovací postup.
11. Přehled Android/iOS rozdílů a realistická roadmapa.
12. Vznikne reálný spustitelný build či jasně zdokumentovaná překážka, nikoli předstíraný EXE/APK/IPA.

## 8. NÁVOD JAK ČÍST KATALOG

Následuje **795 očíslovaných funkčních návrhů z naší společné specifikace**. Body jsou cílový katalog. Samostatně za nimi je přiložen **původní seznam 110+ schopností**, který může obsahovat překryvy a který je nutné zahrnout do auditu. Vzhledem k překryvům nejsou součty přesným počtem unikátních implementačních modulů. Každý bod znamená funkční požadavek či námět k posouzení, **nikoli** povinnost vytvořit pro něj samostatný modul nebo UI tlačítko. Synonyma konsoliduj a existující komponenty rozšiřuj místo duplikování.

## KATALOG FUNKCÍ 001–195 — ROZŠÍŘENÁ PRVNÍ VLNA

### 01. Super Intelligence
001. **Goal Mode** — z cíle sestaví reálný plán.
002. **Mission Control** — řídí složité mise.
003. **Deep Research** — rozsáhlý výzkum s citacemi.
004. **Autonomous Problem Solver** — testování více řešení.
005. **Decision Simulator** — simuluje důsledky rozhodnutí.
006. **AI Debate** — porovnání argumentů modelů.
007. **Confidence Engine** — vyjadřuje míru nejistoty.
008. **Error Prediction** — předvídání pravděpodobných chyb.
009. **Dynamic Task Priorities** — dynamické priority.
010. **Mission Replay** — auditovatelná historie kroků.

### 02. Windows Superpowers
011. Automatické hledání vadných nebo chybějících ovladačů.
012. Vyhodnocení Windows Event Viewer.
013. Sledování Windows Update.
014. Analýza příčin BSOD.
015. Analýza minidump po pádu.
016. Diagnostika pomalého startu Windows.
017. Diagnostika nefunkčních USB.
018. Měření diskového výkonu a historie chyb.
019. Rozpoznávání konfliktů zařízení a ovladačů.
020. Bezpečné body obnovy před zásahy.
021. Diagnostika sítí, DNS a Wi-Fi.
022. Sledování thermal throttlingu.
023. Graf závislostí služeb a procesů.
024. Kontrola podezřelých aplikací a oprávnění.
025. Technická zpráva o stavu PC.

### 03. Context Awareness
026. Detekce aktivní aplikace.
027. Práce s označeným textem.
028. Vysvětlení prvku pod kurzorem.
029. Porovnávání otevřených dokumentů.
030. Paměť pracovního rozložení oken.
031. Obnova pracovního prostředí po restartu.
032. Nabídnutí pomoci při opakovaných chybách.
033. Kontextová diagnostika chybových dialogů.
034. Režim práce/hry/učení dle aktivních aplikací.
035. Interaktivní popisky funkcí aplikace.

### 04. Ultra Memory
036. **Memory Timeline** — časová osa práce.
037. **Project Memories** — oddělená paměť projektů.
038. **Search Everything** — sémantické hledání v povolených datech.
039. **Memory Correction** — opravy vzpomínek.
040. **Memory Categories** — tematické třídění.
041. **Memory Privacy** — režim bez ukládání.
042. **Source Memory** — původ uložených poznatků.
043. **Memory Conflicts** — detekce rozporů.
044. **Project Resume** — navázání na projekt.
045. **Memory Export** — export paměti.

### 05. Ultimate Developer
046. Mapování architektury projektu.
047. Graf závislostí mezi soubory.
048. Vytváření GitHub issues.
049. AI review pull requestů.
050. Automatický changelog.
051. Generování DB migrací.
052. Detekce chybných DB dotazů.
053. Výkonnostní analýza backendu.
054. Kontrola přístupnosti webů.
055. SEO audit a optimalizace webů.
056. Příprava testovacího deploymentu.
057. Bezpečné zátěžové testování.
058. Ověřování buildu po změnách.
059. Vizuální porovnávání UI.
060. Příprava release balíčků.

### 06. Agent Army
061. **Architect Agent** — software architektura.
062. **QA Agent** — testování aplikací.
063. **Performance Agent** — optimalizace výkonu.
064. **Database Agent** — databázový design.
065. **DevOps Agent** — infrastruktura.
066. **Documentation Agent** — dokumentace.
067. **Accessibility Agent** — přístupnost.
068. **Localization Agent** — překlady aplikací.
069. **3D Agent** — modely a scény.
070. **Hardware Agent** — elektronika.

### 07. Mochi 2.0
071. Oči sledující kurzor.
072. Protažení při probuzení PC.
073. Reakce na změnu hlasitosti.
074. Animace při kopírování souborů.
075. Pravdivá vizualizace stahování.
076. Oslava dokončeného úkolu.
077. Nenápadná nabídka přestávky.
078. Schovávání za okraj ostrova.
079. Interaktivní rozdělení Mochiho.
080. Drobné minihry s Mochem.
081. Reakce na připojení zařízení.
082. Sezónní drobné animace.
083. Animovaný cross-device handoff.
084. Kontextové zjevení vedle okna.
085. Nastavitelná historie reakcí.

### 08. Dynamic Island Pro
086. Picture-in-picture panel asistenta.
087. Živé minipanely agentů.
088. Drag & drop do notche.
089. Rychlé akce podle aplikace.
090. Konfigurovatelné klávesové zkratky.
091. Rozšířený panel s pracovními plochami.
092. Zamknutí panelu proti náhodnému otevření.
093. Připnuté úkoly.
094. Kontextové návrhy v minipanelu.
095. Vlastní interaktivní widgety.

### 09. Voice Intelligence
096. Hlasové příkazy během her.
097. Diktování do aplikací.
098. Vlastní aktivační fráze.
099. Ztišení hudby při mluvení.
100. Rozpoznání více příkazů ve větě.
101. Nastavitelná délka a rychlost odpovědi.
102. Prostorové audio efekty.
103. Hlasové potvrzení rizikových akcí.
104. Vlastní hlasová makra.
105. Výběr vhodného mikrofonu.

### 10. JARVIS Teacher
106. Výuka matematických postupů.
107. Procvičovací testy.
108. Detekce slabých míst při učení.
109. Flashcards.
110. Plán opakování učiva.
111. Vyhodnocení písemných odpovědí.
112. Učebnice na výukové materiály.
113. Myšlenkové mapy.
114. Nácvik výslovnosti.
115. Simulace ústního zkoušení.

### 11. Gaming & Development
116. Integrace Roblox Studio.
117. Pomoc s Blenderem.
118. Inspekce Unity projektů.
119. Testovací herní scény.
120. Koncepční návrhy prostředí.
121. Analýza herních logů.
122. Organizace herních assetů.
123. Automatizované testování vlastních her.
124. Správa modů a kompatibility.
125. Analýza FPS podle nastavení.

### 12. Creative Studio
126. Video storyboard.
127. Návrhy animovaných scén.
128. Automatické titulky.
129. Synchronizace titulků.
130. Odšumění zvuku.
131. Výběr krátkých klipů.
132. Náhledové obrázky.
133. Barevné palety.
134. Animace z grafických prvků.
135. Exporty pro sociální sítě.

### 13. Mobile Super Assistant
136. Widgety mobilní domovské obrazovky.
137. Rychlé akce z notifikací.
138. Schránka mezi zařízeními.
139. Spouštění PC úkolů na dálku.
140. Zobrazení stavu počítače.
141. Hlasové poznámky z mobilu.
142. Fotografie přiřazené k projektu.
143. Biometrické potvrzení citlivých akcí.
144. QR párování.
145. Offline fronta a synchronizace.

### 14. Automation of the Future
146. **Workflow Recorder** — záznam postupu.
147. **Conditional Builder** — tvorba podmínek.
148. **Trigger Explorer** — spouštěče událostí.
149. **Workflow Simulator** — zkoušení bez změn.
150. **Workflow Versions** — verzování postupů.
151. **Automation Templates** — šablony automatizací.
152. **Failure Recovery** — navázání při přerušení.
153. **Workflow Sharing** — bezpečné sdílení.
154. **Cost Estimator** — predikce nákladů.
155. **Agent Scheduling** — plánování běhu agentů.

### 15. Hardware Lab
156. Arduino integrace.
157. ESP32 integrace.
158. Raspberry Pi integrace.
159. Základní elektrická schémata.
160. Výpočty a kontrola součástek.
161. Sériový port a data.
162. Jednoduché PCB návrhy.
163. Diagnostika senzorů.
164. Firmware projektový management.
165. Přehled IoT zařízení.

### 16. Business
166. Schůzky → seznam úkolů.
167. Zápisy z meetingů.
168. Nabídky zákazníkům.
169. Fakturační podklady.
170. Zákaznické požadavky.
171. Projektové termíny.
172. Srovnání dodavatelských nabídek.
173. Analýza kampaní.
174. Přehled příjmů a výdajů.
175. Týdenní report práce.

### 17. Security & Control
176. Globální Stop All Agents.
177. Read-only režim.
178. Limit nákladů AI.
179. Redakce citlivých údajů.
180. Oprávnění podle projektu.
181. Dočasná oprávnění.
182. Dvojí potvrzení nebezpečných operací.
183. Detekce škodlivých instrukcí z externích zdrojů.
184. Správa propojených zařízení.
185. Revokace ztracených zařízení.

### 18. Iron Man — Future Tech
186. Futuristický JARVIS HUD.
187. AR Companion.
188. Ovládání gesty kamerou.
189. Prostorová pracovní plocha.
190. Digitální dvojče PC.
191. Command Center pro velké displeje.
192. Vizualizovaná simulace misí.
193. 3D Explorer komponent PC.
194. Vizualizace vlastní sítě a spojení.
195. Přenos Mochiho stavu mezi zařízeními.

## KATALOG FUNKCÍ 196–495 — OMEGA DRUHÁ VLNA

### 19. Hyper Intelligence Engine
196. **Multi-Step Prediction** — odhad možných dalších kroků.
197. **Alternative Strategy Generator** — několik plánů pro jeden cíl.
198. **Intelligent Goal Decomposition** — rozklad projektů do fází.
199. **Assumption Checker** — validace předpokladů.
200. **Evidence Verifier** — kontrola zdrojů a důkazů.
201. **Task Dependency Engine** — závislosti mezi úkoly.
202. **Adaptive Planning** — průběžné aktualizace plánu.
203. **Risk Scoring** — hodnocení rizika akcí.
204. **AI Consensus** — porovnávání výstupů modelů.
205. **Contradiction Detection** — detekce rozporů.
206. **Solution Ranking** — řazení řešení.
207. **Knowledge Gap Detection** — identifikace chybějících dat.
208. **Experiment Designer** — návrh ověřovacích testů.
209. **Outcome Evaluation** — vyhodnocení dosažených cílů.
210. **Recursive Task Improvement** — vylepšení na základě testů.

### 20. Autonomous Mission Engine
211. **Mission Queue** — fronta misí.
212. **Mission Dependencies** — vykonávání dle návazností.
213. **Parallel Execution** — paralelní kroky.
214. **Agent Communication Bus** — zprávy mezi agenty.
215. **Shared Mission Workspace** — sdílené pracovní artefakty.
216. **Mission Checkpoints** — konzistentní checkpointy.
217. **Pause & Resume** — pozastavení a obnovení.
218. **Agent Handover** — předání práce agentovi.
219. **Approval Queue** — fronta schválení.
220. **Deadline Awareness** — hlídání termínů.
221. **Mission Budget** — nákladové limity.
222. **Mission Dependency Graph** — vizualizace závislostí.
223. **Mission Reports** — důkazy výsledků.
224. **Result Validation** — ověření dokončení.
225. **Mission Recovery** — recovery po pádu.

### 21. Next-Gen Desktop
226. **Universal Overlay** — rozhraní nad aplikacemi.
227. **Smart Screen Regions** — práce s výřezem obrazovky.
228. **Window Grouping** — seskupování oken.
229. **Workspace Profiles** — profily prostředí.
230. **Spatial Window Navigator** — prostorová navigace.
231. **Command Preview** — náhled příkazů.
232. **Interactive Action Timeline** — historie operací.
233. **Floating Assistant Bubble** — mini bublina.
234. **Transparent Focus Mode** — nerušivé UI.
235. **Drag-to-JARVIS** — přetažení obsahu.
236. **Smart Clipboard Panel** — historie schránky.
237. **Animated Context Cards** — kontextové karty.
238. **Cross-Monitor Docking** — přesun mezi monitory.
239. **Accessibility Interface** — podporované asistivní ovládání.
240. **Low-Power UI** — úsporné vykreslování.

### 22. Mochi Ultra
241. **Emotion Animation Library** — knihovna expresí.
242. **Personality Presets** — styly osobnosti.
243. **Mood Transitions** — plynulé stavy.
244. **Music Beat Animation** — synchronizace rytmu.
245. **Physics-Based Movement** — pružné pohyby.
246. **Cursor Curiosity** — interakce s kurzorem.
247. **Screen Edge Play** — hravý okraj displeje.
248. **Task Costumes** — tematické doplňky.
249. **Sleep Cycles** — animace spánku.
250. **Micro Interactions** — mikrointerakce.
251. **Tiny Expressions** — jemná mimika.
252. **Mascot Soundboard** — krátké zvuky.
253. **Multiple Mochi Skins** — konzistentní varianty vzhledu.
254. **Mochi Animation Editor** — editor animací.
255. **Mochi Performance Mode** — výkonově úsporný režim.

### 23. Voice & Audio Intelligence
256. **Far-Field Voice Recognition** — dálkový mikrofon.
257. **Noise Suppression** — filtr hluku.
258. **Echo Cancellation** — potlačení ozvěny.
259. **Voice Activity Detection** — detekce řeči.
260. **Wake Word Sensitivity** — citlivost fráze.
261. **Speech Speed Adaptation** — rychlost hlasu.
262. **Audio Context Switching** — výběr výstupů.
263. **Voice Shortcuts** — hlasové zkratky.
264. **Technical Vocabulary** — odborné názvy.
265. **Dictation Correction** — opravy přepisu.
266. **Conversation Bookmarks** — záložky.
267. **Speaker Labels** — identifikace mluvčích.
268. **Audio Summaries** — audio souhrny.
269. **Conversation Translation** — překlady dialogů.
270. **Offline Voice Pipeline** — lokální hlas.

### 24. Advanced Vision
271. **Video Understanding** — analýza videa.
272. **Screen Change Detection** — změny obrazu.
273. **Object Tracking** — sledování objektu.
274. **UI Hierarchy Reconstruction** — struktura UI.
275. **Automatic Form Recognition** — formuláře.
276. **Graph Reading** — čtení grafů.
277. **Table Extraction** — vytěžení tabulek.
278. **Diagram Interpretation** — schémata.
279. **Visual Error Localization** — místo chyby.
280. **Scene Description** — popis scény.
281. **Camera Measurement Helper** — měření s kalibrací.
282. **Color Inspector** — čtení barev.
283. **Visual Similarity Search** — podobné obrázky.
284. **Motion Analysis** — pohybová analýza.
285. **Vision Privacy Masking** — maskování citlivých oblastí.

### 25. JARVIS PC Rescue
286. **Windows Integrity Inspector** — integrita Windows.
287. **Driver Rollback Assistant** — návrat ovladače.
288. **Boot Problem Analyzer** — chyby startu.
289. **Disk Partition Inspector** — přehled oddílů.
290. **USB Connection Analyzer** — diagnostika USB.
291. **Storage Error Correlation** — souvislosti diskových chyb.
292. **File System Health** — souborový systém.
293. **Crash Pattern Detector** — opakující se pády.
294. **Service Dependency Inspector** — závislosti služeb.
295. **Power Plan Diagnostics** — energetické plány.
296. **Memory Error Testing Assistant** — test RAM.
297. **Thermal Health Report** — teploty.
298. **Hardware Change Detector** — změny zařízení.
299. **Recovery Media Assistant** — záchranné médium.
300. **Data Rescue Priority Mode** — přednost ochrany dat.

### 26. Extreme Performance
301. **CPU Bottleneck Detector** — limit procesoru.
302. **GPU Bottleneck Detector** — limit grafiky.
303. **RAM Pressure Analyzer** — tlak na RAM.
304. **VRAM Usage Tracking** — využití VRAM.
305. **Background Task Profiler** — procesy na pozadí.
306. **Frame-Time Analyzer** — nepravidelnosti snímků.
307. **Startup Performance Timeline** — start systému.
308. **App Launch Benchmarking** — rychlost spouštění.
309. **Disk I/O Visualizer** — diskové I/O.
310. **Resource Priority Profiles** — profily výkonu.
311. **Network Latency Monitor** — síťová odezva.
312. **Performance History** — historie výkonu.
313. **Gaming Session Analyzer** — analýza hraní.
314. **Optimization Before/After** — A/B měření změn.
315. **Safe Optimization Advisor** — bezpečná doporučení.

### 27. Intelligent File Universe
316. **Semantic File Search** — hledání podle významu.
317. **Duplicate Detection** — duplicity souborů.
318. **Similar Image Finder** — podobné snímky.
319. **Document Classification** — třídění.
320. **Smart File Naming** — chytré názvy.
321. **File Relationship Graph** — vztahy souborů.
322. **Lost File Finder** — hledání ztracených souborů.
323. **Archive Explorer** — obsah archivů.
324. **File Format Conversion** — konverze formátů.
325. **Bulk Rename Planner** — hromadné názvy.
326. **Metadata Cleaner** — čištění metadat.
327. **Folder Size Explorer** — využití místa.
328. **Automatic Version Snapshots** — verzování souborů.
329. **File Integrity Checker** — hash/integrita.
330. **Intelligent Backup Selection** — výběr záloh.

### 28. Developer God Mode
331. **Repository Knowledge Index** — kódová znalostní báze.
332. **Architecture Refactor Planner** — plán refaktoringu.
333. **Dependency Risk Detector** — rizika závislostí.
334. **Test Coverage Explorer** — pokrytí testů.
335. **Mutation Testing Assistant** — mutační testy.
336. **API Contract Validator** — API kontrakty.
337. **Database Migration Preview** — náhled migrace.
338. **Code Ownership Map** — vlastnictví souborů.
339. **Regression Detector** — detekce regresí.
340. **Build Failure Root-Cause Analysis** — příčiny buildu.
341. **Dependency Update Planner** — aktualizace knihoven.
342. **Environment Reproducer** — reprodukovatelné prostředí.
343. **Automated Release Notes** — release notes.
344. **Feature Flag Manager** — přepínače funkcí.
345. **Code Experiment Sandbox** — experimentální kód.

### 29. AI Design Studio
346. **Design System Generator** — tokeny a komponenty.
347. **Responsive Layout Analyzer** — různé displeje.
348. **Accessibility Contrast Checker** — kontrast.
349. **Animation Curve Editor** — animační křivky.
350. **Glass Material Generator** — Liquid Glass.
351. **UI Consistency Scanner** — jednotnost.
352. **Design-to-Code** — převod designu do kódu.
353. **Screenshot-to-Prototype** — screenshot na prototyp.
354. **Interactive UI Mockups** — klikatelné návrhy.
355. **Icon System Builder** — ikony.
356. **Theme Generator** — témata.
357. **Motion Design Timeline** — animace.
358. **Layout Heatmap** — prostor v UI.
359. **Typography Inspector** — typografie.
360. **Visual Regression Lab** — porovnání změn.

### 30. Multimedia Production
361. **Smart Scene Detection** — identifikace scén.
362. **Silence Remover** — odstranění ticha.
363. **Audio Ducking** — zeslabení hudby při řeči.
364. **Video Highlight Finder** — zajímavé momenty.
365. **Automatic Reframing** — poměr stran videa.
366. **Speech Enhancement** — čištění řeči.
367. **Background Removal** — odstranění pozadí.
368. **Media Asset Organizer** — uspořádání médií.
369. **Subtitle Style Generator** — styly titulků.
370. **Podcast Chapter Generator** — kapitoly audia.
371. **Shot Matching** — sjednocení záběrů.
372. **Voiceover Script Assistant** — text dabingu.
373. **Sound Effect Matcher** — zvukové efekty.
374. **Media Render Queue** — fronta renderů.
375. **Export Quality Analyzer** — kvalita výstupu.

### 31. Internet Intelligence
376. **Source Reliability Profiles** — důvěryhodnost zdrojů.
377. **Cross-Source Fact Checking** — křížové ověření.
378. **Website Change Watcher** — změny webu.
379. **Price History Analyzer** — historie cen.
380. **Research Notebook** — poznámky výzkumu.
381. **Web Evidence Collector** — archivace důkazů.
382. **Automated Website Testing** — testy webů.
383. **Broken Link Scanner** — nefunkční odkazy.
384. **Competitor Feature Comparison** — srovnání konkurence.
385. **Search Query Optimizer** — vyhledávací strategie.
386. **Article Comparison** — srovnání článků.
387. **Domain Health Inspector** — DNS/TLS/dostupnost.
388. **Website Performance Audit** — výkon webů.
389. **Web Content Structure Analyzer** — struktura obsahu.
390. **Research-to-Action** — závěry na úkoly.

### 32. Cybersecurity Center
391. **Permission Audit** — aplikace a oprávnění.
392. **Local Port Inspector** — místní porty.
393. **Firewall Rule Explorer** — firewall.
394. **Suspicious Startup Detector** — podezřelé položky startu.
395. **Security Update Tracker** — bezpečnostní aktualizace.
396. **Credential Exposure Checker** — kontrola známých úniků.
397. **Phishing Link Analyzer** — rizika URL.
398. **Download Safety Inspector** — kontrola downloadů.
399. **Ransomware Recovery Planner** — plán obnovy.
400. **Local Security Dashboard** — bezpečnostní přehled.
401. **Secret Detection** — úniky API klíčů v kódu.
402. **Device Trust Manager** — důvěryhodná zařízení.
403. **Session Revocation Center** — odpojení sessions.
404. **Security Incident Timeline** — časová osa incidentů.
405. **Emergency Lockdown** — zastavení vzdálených akcí.

### 33. Multi-Device Ecosystem
406. **Device Discovery** — hledání vlastních zařízení.
407. **Encrypted Device Pairing** — párování.
408. **Cross-Device Clipboard History** — historie schránky.
409. **Remote Terminal Sessions** — zabezpečený remote terminal.
410. **Device Presence Detection** — dostupnost zařízení.
411. **Remote Build Monitor** — průběh buildu na PC.
412. **Notification Routing** — distribuce oznámení.
413. **Phone Camera as Input** — kamera telefonu.
414. **Audio Device Handoff** — přenos hovoru.
415. **Cross-Device File Browser** — sdílené soubory.
416. **Remote Wake Support** — Wake-on-LAN.
417. **Device Battery Dashboard** — baterie.
418. **Offline Device Sync** — offline synchronizace.
419. **Device-Specific Permissions** — povolení zařízení.
420. **Lost Device Protection** — ochrana při ztrátě.

### 34. Smart Home
421. **Room Awareness** — přiřazení do místností.
422. **Energy Usage Analysis** — spotřeba energie.
423. **Smart Lighting Scenes** — světelné scény.
424. **Climate Automation** — termostaty.
425. **Sensor Event Rules** — pravidla senzorů.
426. **Home Network Map** — mapa domácí sítě.
427. **Device Battery Alerts** — upozornění na baterie.
428. **Smart Plug Scheduling** — chytré zásuvky.
429. **Media Room Control** — multimédia.
430. **Home Automation Simulator** — test pravidel.
431. **Device Firmware Tracker** — firmware.
432. **Voice-Controlled Scenes** — hlasové scény.
433. **Smart Home Event History** — historie událostí.
434. **Local-Only Smart Home Mode** — domácnost bez cloudu.
435. **Safety Interlocks** — bezpečnostní blokace.

### 35. Business & Startup
436. **Opportunity Analyzer** — obchodní příležitosti.
437. **Customer Segmentation** — segmentace.
438. **Lead Qualification** — hodnocení leadů.
439. **Sales Funnel Explorer** — prodejní trychtýř.
440. **Client Follow-Up Planner** — následné kontakty.
441. **Proposal Generator** — obchodní nabídky.
442. **Pricing Scenario Simulator** — cenové scénáře.
443. **Revenue Forecasting** — predikce výnosů.
444. **Customer Feedback Analyzer** — zpětná vazba.
445. **Competitor Monitoring** — změny konkurence.
446. **Marketing Content Calendar** — marketingový kalendář.
447. **SEO Opportunity Finder** — SEO příležitosti.
448. **Client Portal Assistant** — zákaznický portál.
449. **Project Profitability Analyzer** — ziskovost projektů.
450. **Business Decision Dashboard** — obchodní metriky.

### 36. Learning Lab
451. **Adaptive Difficulty** — adaptivní náročnost.
452. **Learning Path Builder** — studijní cesta.
453. **Knowledge Prerequisite Map** — předpoklady učiva.
454. **Spaced Repetition Engine** — časované opakování.
455. **Mistake Classification** — druhy chyb.
456. **Interactive Circuit Tutor** — obvody.
457. **Math Step Validator** — kontrola výpočtů.
458. **Programming Exercise Generator** — úlohy.
459. **Virtual Oral Exam** — ústní zkoušení.
460. **Formula Explorer** — interaktivní vzorce.
461. **Study Time Analytics** — metriky učení.
462. **Document-to-Quiz** — test z dokumentu.
463. **Exam Countdown Planner** — plán před zkouškou.
464. **Concept Connection Map** — vztahy konceptů.
465. **Project-Based Learning** — učení projekty.

### 37. Engineering & Robotics
466. **CAD Project Assistant** — CAD.
467. **3D Print Preparation** — tisková příprava.
468. **Printability Checker** — tisknutelnost.
469. **Bill of Materials Generator** — BOM součástek.
470. **Component Compatibility Checker** — kompatibilita komponent.
471. **Serial Device Monitor** — sériový monitor.
472. **Sensor Data Visualizer** — data senzorů.
473. **Circuit Calculation Engine** — výpočty obvodů.
474. **Power Consumption Estimator** — spotřeba.
475. **Firmware Build Assistant** — firmware build.
476. **Robotics Motion Simulator** — pohyb robota.
477. **Robot Telemetry Dashboard** — telemetrie.
478. **Camera Calibration Assistant** — kalibrace.
479. **Hardware Experiment Logger** — evidence experimentů.
480. **Prototype Test Planner** — test prototypu.

### 38. Iron Man Experimental
481. **Holographic-Style Interface** — 3D styl hologramu.
482. **AR Object Annotations** — anotace objektů.
483. **Spatial Voice Commands** — hlas v prostorové UI.
484. **3D Exploded View** — rozložené modely.
485. **Mechanical Assembly Guide** — montážní návody.
486. **Environmental Sensor Fusion** — data více senzorů.
487. **Smart Glasses Companion** — chytré brýle.
488. **Virtual Engineering Table** — virtuální pracovní stůl.
489. **Robot Fleet Dashboard** — řízení flotily.
490. **Digital Twin Simulator** — simulační dvojče.
491. **Virtual Lab Experiments** — virtuální fyzika.
492. **Hands-Free Workshop Mode** — hands-free dílna.
493. **Gesture-Based 3D Manipulation** — gesta ve 3D.
494. **Wearable Notifications** — hodinky a wearables.
495. **Integrated Command Environment** — jeden řídicí prostor.

## KATALOG FUNKCÍ 496–795 — OMEGA TŘETÍ VLNA

### 39. Proactive Intelligence
496. **Next Action Prediction** — návrh dalšího kroku.
497. **Routine Discovery** — rozpoznání rutin.
498. **Opportunity Alerts** — možnosti zjednodušení.
499. **Forgotten Task Detection** — opuštěné projekty.
500. **Intelligent Interruption Control** — vhodný čas oznámení.
501. **Contextual Suggestion Engine** — kontextové funkce.
502. **Deadline Risk Forecasting** — rizika termínů.
503. **Task Effort Estimator** — odhad pracnosti.
504. **Personal Routine Builder** — osobní rutina.
505. **Automatic Priority Negotiation** — změny priorit.
506. **Unfinished Conversation Detection** — nedořešené otázky.
507. **Idle-Time Task Suggestions** — vhodné krátké úkoly.
508. **Proactive Error Warnings** — včasná varování.
509. **Contextual Work Resumption** — příprava pokračování.
510. **Daily Achievement Timeline** — přehled práce dne.

### 40. Semantic Operating System
511. **Natural Language File Commands** — soubory přirozenou řečí.
512. **Universal App Search** — hledání uvnitř aplikací.
513. **Cross-App Actions** — navazující operace mezi aplikacemi.
514. **App Capability Discovery** — zjištění schopností aplikací.
515. **Semantic Desktop Index** — propojování desktopových dat.
516. **Virtual App Groups** — logické skupiny aplikací.
517. **Smart Window Naming** — názvy skupin oken.
518. **Workspace State Comparison** — porovnání pracovního prostředí.
519. **App Recovery Assistant** — obnova po pádu aplikace.
520. **Universal Command History** — hledání příkazů.
521. **Keyboard Shortcut Discovery** — klávesové zkratky.
522. **Adaptive Input Controller** — myš/touch/hlas.
523. **Virtual Workspace Snapshots** — snímky pracovních ploch.
524. **Desktop Workflow Search** — vyhledání pracovního postupu.
525. **Task-Centric Desktop** — aplikace seskupené podle úkolu.

### 41. Super Browser Agent
526. **Multi-Tab Research** — výzkum na více kartách.
527. **Smart Tab Classification** — třídění tabů.
528. **Browser Session Restore** — relace prohlížeče.
529. **Website Workflow Recording** — zaznamenání postupu.
530. **Form Field Validation** — kontrola formulářů.
531. **Captcha Handoff** — předání ručního ověření.
532. **Page Structure Comparison** — změny struktury.
533. **Navigation Route Finder** — navigace webem.
534. **Cookie Preference Assistant** — nastavení cookies.
535. **Subscription Overview** — přehled předplatných.
536. **Web App Compatibility Tester** — prohlížečová kompatibilita.
537. **Session Expiration Awareness** — vypršení přihlášení.
538. **Download Source Verification** — kontrola zdroje.
539. **Browser Privacy Report** — oprávnění webů.
540. **Web Task Continuity** — pokračování práce.

### 42. Communication
541. **Unified Message Inbox** — sloučené zprávy.
542. **Message Importance Ranking** — priority komunikace.
543. **Reply Context Builder** — podklady odpovědi.
544. **Conversation Action Extraction** — úkoly ze zpráv.
545. **Attachment Relationship Finder** — související přílohy.
546. **Conversation Follow-Up Tracker** — navazující komunikace.
547. **Tone Adjustment** — styl odpovědi.
548. **Multilingual Message Drafting** — různé jazyky.
549. **Inbox Noise Reduction** — méně spamu.
550. **Message Source Linking** — zdroje konverzací.
551. **Communication Search Assistant** — vyhledání rozhodnutí.
552. **Response Time Analytics** — doby odpovědí.
553. **Contact Context Cards** — přehled kontaktů.
554. **Draft Approval System** — schválení odeslání.
555. **Communication Digest** — souhrny komunikace.

### 43. Meetings
556. **Meeting Preparation Engine** — podklady schůzek.
557. **Agenda Builder** — program jednání.
558. **Availability Conflict Resolver** — řešení konfliktů.
559. **Meeting Decision Log** — rozhodnutí schůzky.
560. **Speaker Contribution Summary** — příspěvky řečníků.
561. **Action Owner Assignment** — přiřazení vlastníků úkolů.
562. **Meeting Follow-Up Generator** — následné zprávy.
563. **Calendar Travel Buffer** — cestovní rezerva.
564. **Meeting Relevance Checker** — opakující se schůzky.
565. **Project Milestone Calendar** — kalendář milníků.
566. **Meeting Notes Search** — hledání poznámek.
567. **Recurring Meeting Review** — hodnocení schůzek.
568. **Availability Sharing Assistant** — sdílení možností termínů.
569. **Meeting Document Organizer** — soubory schůzek.
570. **Decision-to-Task Converter** — rozhodnutí na úkoly.

### 44. Local AI Supercomputer
571. **Local Model Benchmarking** — porovnání rychlosti.
572. **Automatic Model Quantization Advisor** — kvantizace modelu.
573. **VRAM-Aware Model Loading** — výběr modelu dle VRAM.
574. **CPU/GPU Hybrid Inference** — hybridní výpočty.
575. **Model Warm-Up Manager** — rychlejší start.
576. **Idle Model Unloading** — uvolnění paměti.
577. **Inference Queue Scheduler** — fronta inference.
578. **Model Compatibility Scanner** — kompatibilita.
579. **Offline Knowledge Pack Manager** — offline znalosti.
580. **Embedding Model Selector** — embeddingy.
581. **Local RAG Workspace** — hledání v místních dokumentech.
582. **Model Accuracy Testing** — kvalita odpovědí.
583. **Automatic Resource Throttling** — řízení zdrojů.
584. **Local AI Cache** — cache odpovědí.
585. **Model Health Monitor** — stav modelů.

### 45. Universal Integration Gateway
586. **Connector Discovery** — dostupné integrace.
587. **Connector Health Checks** — funkčnost připojení.
588. **API Schema Importer** — OpenAPI specifikace.
589. **Natural Language API Builder** — API požadavky řečí.
590. **Webhook Event Router** — události.
591. **Connector Permission Dashboard** — oprávnění.
592. **Token Expiration Manager** — expirace tokenů.
593. **Integration Test Sandbox** — testování bez ostrých dat.
594. **API Rate-Limit Analyzer** — limity API.
595. **Data Mapping Designer** — mapování dat.
596. **Connector Version Tracking** — verze API.
597. **Service Outage Fallback** — výpadek integrace.
598. **Data Sync Conflict Resolver** — konflikty synchronizace.
599. **Event Replay System** — přehrání události.
600. **Custom Connector SDK** — tvorba vlastních konektorů.

### 46. Database Intelligence
601. **Database Schema Explorer** — databázové schéma.
602. **Index Recommendation Engine** — indexy.
603. **Query Execution Visualizer** — exekuční plán.
604. **Slow Query Detector** — pomalé dotazy.
605. **Data Integrity Analyzer** — kontrola integrity.
606. **Backup Verification Engine** — kontrola záloh.
607. **Restore Rehearsal** — cvičná obnova.
608. **Schema Drift Detector** — rozdíly schémat.
609. **Sensitive Column Scanner** — osobní a citlivá data.
610. **Database Capacity Forecast** — odhad růstu.
611. **Data Anonymization Assistant** — anonymizace testovacích dat.
612. **Query Cost Estimator** — náročnost dotazů.
613. **Database Change Audit** — změny databáze.
614. **Replication Status Dashboard** — replikace.
615. **Database Incident Assistant** — databázové incidenty.

### 47. Autonomous Software Factory
616. **Requirements Extractor** — záměr na požadavky.
617. **Acceptance Criteria Generator** — akceptační kritéria.
618. **Architecture Decision Records** — ADR.
619. **Monorepo Organizer** — více aplikací.
620. **SDK Generator** — klientské SDK.
621. **Mock Server Builder** — testovací server.
622. **Canary Deployment Manager** — postupný deploy.
623. **Automated Rollback Planner** — návrat verze.
624. **Software Bill of Materials** — SBOM.
625. **Supply Chain Inspector** — rizika knihoven.
626. **CI Pipeline Designer** — CI/CD.
627. **Release Compatibility Checker** — kompatibilita vydání.
628. **Background Job Inspector** — worker jobs.
629. **Mobile Deep-Link Tester** — deep links.
630. **Feature Completion Auditor** — kontrola úplnosti.

### 48. Software Testing Lab
631. **Synthetic User Testing** — simulované uživatelské scénáře.
632. **Property-Based Testing** — vlastnostní testy.
633. **Input Fuzzing** — neobvyklé vstupy.
634. **Network Failure Simulation** — výpadky sítě.
635. **Memory Leak Detector** — úniky paměti.
636. **Flaky Test Analyzer** — nestabilní testy.
637. **Crash Reproduction Assistant** — reprodukce pádu.
638. **Device Test Matrix** — testy zařízení.
639. **Localization Overflow Testing** — přetečení textu.
640. **Battery Consumption Profiler** — spotřeba energie.
641. **Offline Behavior Tester** — offline funkcionalita.
642. **Concurrent User Simulation** — více uživatelů.
643. **Data Corruption Recovery Test** — poškození testovacích dat.
644. **Accessibility Keyboard Tester** — přístupnost klávesnicí.
645. **Test Evidence Recorder** — důkazy o testech.

### 49. Autonomous Game Development Studio
646. **Procedural World Builder** — generování světů.
647. **NPC Dialogue System** — dialogy NPC.
648. **Quest Graph Designer** — herní questy.
649. **Game Economy Simulator** — simulace ekonomiky.
650. **Loot Balance Calculator** — balancing odměn.
651. **Spawn Balance Analyzer** — pozice objektů a nepřátel.
652. **Level Layout Generator** — návrhy levelů.
653. **Anti-Exploit Test Assistant** — testy vlastních her.
654. **Save Data Validator** — uložená data.
655. **Animation State Machine Builder** — animace postav.
656. **Voxel Structure Generator** — voxelová tvorba.
657. **Server Capacity Simulator** — kapacita serveru.
658. **Game Telemetry Explorer** — herní telemetrie.
659. **Game Accessibility Inspector** — přístupnost hry.
660. **Gameplay Balance Experimenter** — herní balanc.

### 50. AI Creative Production
661. **Brand Asset Consistency** — vizuální konzistence.
662. **Batch Content Producer** — více výstupů.
663. **Caption A/B Generator** — varianty textu.
664. **Content Licensing Tracker** — licence obsahu.
665. **Virtual Camera Director** — 3D kamerové pohyby.
666. **Lighting Setup Planner** — 3D osvětlení.
667. **3D Rigging Assistant** — rigging modelů.
668. **Lip-Sync Animator** — synchronizace úst.
669. **Audio Mixing Advisor** — mix audia.
670. **Render Cost Planner** — nároky renderu.
671. **Color Management Assistant** — barevné profily.
672. **Storyboard-to-Timeline** — storyboard na časovou osu.
673. **Interactive Product Demo Builder** — produktové ukázky.
674. **Subtitle Quality Checker** — kontrola titulků.
675. **Asset Provenance Tracker** — původ assetů.

### 51. Privacy Fortress
676. **Consent Receipt Manager** — evidence souhlasů.
677. **Personal Data Inventory** — evidence údajů.
678. **Outbound Data Inspector** — před odesláním dat.
679. **Microphone Access Audit** — mikrofon.
680. **Camera Access Audit** — kamera.
681. **Clipboard Secret Masking** — redakce schránky.
682. **Application Allowlist** — seznam povolených aplikací.
683. **Temporary Permission Grants** — dočasná povolení.
684. **Data Retention Rules** — uchovávání dat.
685. **Encrypted Vault Backup** — šifrované zálohy.
686. **Untrusted Agent Isolation** — izolace agentů.
687. **Audit Log Export** — export logů.
688. **Project Isolation Profiles** — oddělení projektů.
689. **Sensitive Action Lock** — uzamčení rizikových akcí.
690. **Privacy Transparency Center** — transparentnost.

### 52. Advanced Hardware Rescue
691. **USB Power Diagnostics** — napájení USB.
692. **USB Controller Mapping** — řadiče USB.
693. **Cable & Enclosure Troubleshooter** — kabely a USB boxy.
694. **Storage Bridge Detection** — USB–SATA/NVMe bridge.
695. **NVMe Enumeration Inspector** — enumerace NVMe.
696. **SATA Error Log Reader** — SATA logy.
697. **SMART Passthrough Tester** — SMART přes USB.
698. **Invisible Disk Triage** — disky nedetekované systémem.
699. **Read-Only Imaging Planner** — image dat v read-only režimu.
700. **Clone Verification Assistant** — integrita klonu.
701. **Read Error Heatmap** — vadné oblasti dle logů.
702. **Accidental Format Protection** — ochrana před formátem.
703. **Recovery Viability Assessment** — možnosti obnovy.
704. **I/O Timeout Analyzer** — timeouty disků.
705. **Hardware Incident Report** — report pro servis.

### 53. Network & Cloud Command Center
706. **Visual Traceroute** — mapa síťové cesty.
707. **DNS Propagation Tracker** — DNS propagace.
708. **TLS Certificate Watch** — certifikáty.
709. **HTTP Synthetic Monitoring** — dostupnost API.
710. **Cloud Resource Inventory** — cloud zdroje.
711. **Cloud Cost Anomaly Detection** — anomálie nákladů.
712. **Hosting Health Inspector** — stav hostingu.
713. **Centralized Log Explorer** — agregované logy.
714. **Deployment Difference Analyzer** — rozdíly nasazení.
715. **Infrastructure Rollback Rehearsal** — cvičná obnova.
716. **Cloud Backup Receipt Checker** — potvrzení záloh.
717. **Local Network Throughput Tester** — propustnost vlastní sítě.
718. **Jitter Analysis** — kolísání latence.
719. **Packet Loss History** — ztrátovost paketů.
720. **Infrastructure Outage Timeline** — historie výpadků.

### 54. Next-Gen Mobile
721. **Notification Quick Actions** — akce z notifikací.
722. **Live Mission Widgets** — živé widgety.
723. **Camera-to-Task** — úkol z fotografie.
724. **Mobile Share Sheet Integration** — nabídka Sdílet.
725. **Offline Voice Command Queue** — offline hlasové příkazy.
726. **Clipboard Sanitizer** — bezpečné sdílení textu.
727. **Temporary Device Pairing** — krátkodobé párování.
728. **Location-Based Routines** — dobrovolné lokální rutiny.
729. **Remote Camera Consent Controls** — přístup ke kameře.
730. **Mobile Shortcut Bridge** — mobilní systémové zkratky.
731. **QR Command Launcher** — akce z QR kódu.
732. **Link Handoff** — předání odkazu.
733. **Proximity Pairing Check** — proximity Bluetooth ověření.
734. **Battery-Aware Synchronization** — úspora energie.
735. **Remote Mission Approval** — schválení z telefonu.

### 55. Mochi Reactive Companion
736. **Expression Blending** — spojování výrazů.
737. **Real Task Emotions** — stavové animace.
738. **Mute Awareness** — reakce na ztlumení.
739. **Weather Accessories** — doplňky dle počasí.
740. **Time-Based Outfits** — doplňky dle času.
741. **Ambient Light Adaptation** — adaptace jasu.
742. **Accessibility Animation Mode** — omezený pohyb.
743. **Soft Body Physics** — pružná fyzika.
744. **Code Error Confusion** — reakce na chybu buildu.
745. **Test Success Celebration** — oslava testu.
746. **Rare Easter Eggs** — překvapivé animace.
747. **Idle Toys** — hračky při nečinnosti.
748. **AI Limit Reaction** — limit modelu.
749. **Model Switching Animation** — změna AI.
750. **Custom Reaction Studio** — editor reakcí.

### 56. Futuristic JARVIS Interface
751. **Contextual Radial Menu** — radiální akce.
752. **Smart Overlay Anchoring** — připnutí k oknu.
753. **Attention-Aware UI** — méně rušení.
754. **Live Agent Activity Map** — mapa agentů.
755. **Mission Dependency Animation** — návaznosti úkolů.
756. **HUD Layout Presets** — layout profily.
757. **Command Palette Search** — příkazová paleta.
758. **Adaptive Density UI** — velikost a hustota UI.
759. **Floating Data Lens** — datová lupa.
760. **Animated Status Morphing** — plynulé indikátory.
761. **Spatial Audio Notifications** — prostorové zvuky.
762. **Touch-Friendly Dashboard** — dotyková verze.
763. **Miniature Mission Viewer** — mini stav mise.
764. **HUD Performance Governor** — úsporné UI.
765. **Interface Behavior Editor** — chování prvků.

### 57. Science & Simulation
766. **Interactive Equation Solver** — rovnice s postupem.
767. **Dataset Cleaning Assistant** — čištění dat.
768. **Computational Notebook Runner** — výpočetní notebooky.
769. **Experiment Logbook** — záznam experimentů.
770. **Chart Interpretation Engine** — interpretace grafů.
771. **Data Lineage Viewer** — původ dat.
772. **Physical Unit Validator** — jednotky.
773. **CAD Tolerance Assistant** — tolerance.
774. **Generative Engineering Concepts** — technické alternativy.
775. **Technical Model Inspector** — geometrie 3D.
776. **Physics Parameter Explorer** — parametry simulací.
777. **Scientific Citation Checker** — vědecké zdroje.
778. **Signal Frequency Analyzer** — frekvenční analýza.
779. **Statistical Quality Inspector** — kvalita statistiky.
780. **A/B Experiment Designer** — experimenty.

### 58. Everyday Intelligence & Accessibility
781. **Life Event Planner** — osobní události.
782. **Travel Packing Assistant** — balení na cesty.
783. **Weather-Aware Planning** — plány podle počasí.
784. **Public Transport Connector** — dopravní spojení.
785. **Smart Grocery List** — nákupní seznam.
786. **Recipe Ingredient Substitution** — náhrady surovin.
787. **Daily Focus Report** — soustředění.
788. **Screen Reader Optimization** — čtečky.
789. **One-Handed Control Profiles** — jedna ruka.
790. **Live Caption Accessibility** — živé titulky.
791. **Reading Assistance Mode** — jednodušší text.
792. **Digital Wellbeing Dashboard** — využití aplikací.
793. **Personal Data Portability** — export dat.
794. **Complete Local Memory Reset** — vymazání lokální paměti.
795. **JARVIS Setup Wizard** — kompletní průvodce nastavením.


## 9. PŮVODNÍ SPECIFIKACE — ZACHOVAT, PROVÉST AUDIT, NEZDVOJOVAT

Níže je původní uživatelem dodaný seznam **110+ základních schopností**, který je pro vývoj také závazným vstupem. Obsahuje i volné popisy, inspirační odkazy a příklady; tyto odkazy jsou pouze historickou inspirací, nikoli instrukcí kopírovat cizí vzhled. V případě překryvů s očíslovaným katalogem 001–795 implementuj jednu kvalitní sdílenou schopnost a v matici vyznač všechna ID.

```text
jake vsechny funkce by mnel mit jarvis
Kdybychom chtěli vytvořit JARVIS jako jednoho z nejpokročilejších osobních AI asistentů pro Windows, Android a iPhone, neměl by to být jen chatbot, který odpovídá na otázky.

Měl by to být inteligentní AI společník, který umí ovládat počítač, programovat, přemýšlet, učit se, automatizovat práci, komunikovat hlasem a fungovat i samostatně.

Navrhl bych následující kompletní systém.

JARVIS — Ultimate AI Operating Assistant
110+ navrhovaných funkcí
Windows + Android + iOS
Online + offline
GitHub - Louis-CFM/coucou: A tiny friend that lives in your notch (macOS) or at the top of your screen (Windows) and keeps an eye on your Claude Code sessions. · GitHub

VYRO - AI Desktop Companion for Windows

Serena - Private AI Assistant for Mac | FolkTech AI.

Vizuální inspirace: minimalistický Dynamic Island, Liquid Glass a živý Mochi. Finální design by byl vlastní.
1.  Inteligence a AI mozek
JARVIS musí mít skutečný rozhodovací a plánovací systém.

Multi-AI engine – Claude, GPT, Gemini a lokální AI modely.

Automatický výběr modelu podle obtížnosti úkolu, ceny a dostupnosti.

Dlouhodobá paměť – pamatuje si projekty, preference a důležité informace.

Krátkodobá paměť – sleduje kontext probíhající práce.

Autonomní plánování – rozdělí složitý úkol na menší kroky.

Self-correction – rozpoznává chyby a opravuje vlastní postup.

Reasoning mode – hlubší přemýšlení nad složitými problémy.

Multi-agent systém – několik specializovaných AI agentů spolupracuje.

Učení z oprav a zpětné vazby – postupně lépe chápe, co chceš.

Offline fallback – základní schopnosti fungují bez internetu.

2.  Kompletní ovládání Windows
Tohle je jedna z nejdůležitějších funkcí. JARVIS nesmí jen radit, co máš udělat. Musí umět vybrané úkony skutečně vykonat.

Spouštět, zavírat a přepínat aplikace.

Klikat, psát, scrollovat a ovládat klávesnici i myš.

Číst obrazovku a rozpoznávat prvky aplikací.

Pracovat s více monitory.

Instalovat a odinstalovávat software.

Spravovat procesy, služby a aplikace při spuštění.

Diagnostikovat RAM, CPU, GPU, SSD a HDD.

Vyhodnocovat SMART údaje, stav disků a systémové logy.

Hledat příčiny zamrzání a zpomalení Windows.

Upravovat systémová nastavení.

Organizovat soubory, složky a stažené soubory.

Automatizovat opakované úkoly.

Ovládat PowerShell, CMD a Windows Terminal.

Provádět zálohy a pomáhat s obnovou systému.

Například řekneš: „JARVIS, zjisti, proč se mi seká počítač, a navrhni opravu.“

JARVIS provede diagnostiku, zjistí konkrétní příčiny a bezpečné opravy může vykonat sám. Rizikové změny nejdřív předloží ke schválení.

3.  Pokročilý hlasový asistent
Aktivace hlasem: „Hey JARVIS“.

Přirozená konverzace v češtině i dalších jazycích.

Real-time hlasový rozhovor s nízkou latencí.

Možnost přerušit JARVISe během mluvení.

Rozpoznávání různých mluvčích.

Nastavitelný hlas, osobnost a styl komunikace.

Šeptání a tichý režim.

Přepis mluveného slova.

Překlady během konverzace.

Čtení zpráv, oznámení a dokumentů.

Offline rozpoznávání řeči a syntéza hlasu, pokud jsou nainstalovány potřebné modely.

Volitelná detekce emocí v hlase, s přiznanou nejistotou.

4.  Vision — JARVIS vidí obrazovku
JARVIS by měl rozumět tomu, co se děje na monitoru.

Analýza screenshotů.

Rozpoznávání textu, ikon, tlačítek a oken.

Porozumění chybovým hláškám.

Navigace v aplikacích podle vizuálního rozhraní.

Pomoc v reálném čase při práci.

Analýza obrázků, grafů a dokumentů.

Volitelný přístup ke kameře.

Rozpoznávání objektů kamerou telefonu.

Vizuální porovnávání změn před a po provedení úkolu.

5.  Programování a vývoj aplikací
Tady bych JARVISovi dal opravdu rozsáhlé schopnosti.

Integrace s Claude Code CLI a dalšími coding agenty.

Generování celých aplikací a projektů.

Frontend, backend, databáze i API.

Tvorba webových a mobilních aplikací.

Čtení a úpravy existujícího kódu.

Automatické hledání a oprava bugů.

Refactoring a optimalizace výkonu.

Spouštění testů a kontrola výsledků.

Práce s Gitem a GitHubem.

Vytváření pull requestů.

Spouštění vývojových serverů.

Práce s terminálem, Dockerem a databázemi.

Automatická dokumentace projektů.

Kontrola bezpečnostních chyb v kódu.

Sestavení EXE, APK a dalších instalačních balíčků tam, kde to vývojové prostředí podporuje.

Příklad: „JARVIS, vytvoř mi profesionální web, otestuj ho a připrav ho na nasazení.“

6.  Autonomní agenti
JARVIS by mohl vytvořit tým specializovaných agentů:

🧠

Planner Agent

Plánuje úkoly a řídí ostatní agenty.

💻

Coding Agent

Programuje, testuje a opravuje kód.

🔎

Research Agent

Vyhledává, porovnává a ověřuje informace.

🛠️

System Agent

Diagnostikuje a spravuje počítač.

🎨

Design Agent

Navrhuje UI, grafiku a animace.

📂

File Agent

Organizuje soubory a dokumenty.

🛡️

Security Agent

Kontroluje oprávnění a bezpečnost operací.

📅

Automation Agent

Spouští úlohy podle plánů a událostí.

Agenti by mohli pracovat paralelně, sdílet výsledky a používat nástroje podle oprávnění.

7.  Mochi — živý AI společník
Tohle by odlišovalo JARVISe od běžných AI asistentů. Místo robota by v něm žil malý, minimalistický, roztomilý Mochi, který má animace a reaguje na dění v počítači.

The Rise of Agentic AI on the Desktop | Mochi Blog

Spánek a nečinnost

Cute Kawaii Character Creators ChatGPT Image Prompt | PromptBase

Tančí při hudbě

Why Moshi STT Could Replace Whisper (and How to Install It on macOS!)

Přemýšlí nad úkolem

Minimal 3D Cartoon Face Pros ChatGPT Image Prompt | PromptBase

Radost z dokončení

Důležité interakce:

Reaguje na kurzor a kliknutí.

Tancuje podle rytmu hudby.

Spí, když dlouho nic neděláš.

Přemýšlí při generování odpovědi.

Zlobí se nebo je smutný při chybě.

Oslavuje dokončené úkoly.

Reaguje na vyčerpání limitu AI modelu.

Má desítky animací a výrazů.

Má vlastní zvukové reakce.

Dokáže používat krátké interaktivní bubliny.

Všechno minimalisticky, bez přeplácaného prostředí.

8.  Dynamic Island a Liquid Glass UI
GitHub - Louis-CFM/coucou: A tiny friend that lives in your notch (macOS) or at the top of your screen (Windows) and keeps an eye on your Claude Code sessions. · GitHub

Malý černý notch nahoře uprostřed obrazovky.

Plynulé rozšiřování při hoveru nebo kliknutí.

Kompaktní režim a velký pracovní panel.

Liquid Glass, blur a průhlednost.

Extrémně plynulé animace.

Ovládání hlasem i textem.

Hudební vizualizér a ovládání přehrávání.

Indikátory CPU, RAM, baterie a připojení.

Zobrazení aktuálních AI úkolů.

Mini notifikace bez vyrušování.

Vlastní témata, efekty a nastavení.

Adaptivní rozhraní pro různá rozlišení.

9.  Windows, Android a iPhone
Všechny tři platformy by měly sdílet jednoho JARVISe.

Synchronizace konverzací, paměti a úkolů.

Telefon jako vzdálený ovladač počítače.

Posílání souborů mezi zařízeními.

Push notifikace o dokončených úkolech.

Pokračování v práci na jiném zařízení.

Hlasové příkazy z telefonu.

Přístup k fotografiím a souborům se souhlasem.

Sdílení obrazovky mezi zařízeními.

Připojení více počítačů.

Bezpečný vzdálený přístup přes internet.

Android by mohl mít širší integraci s operačním systémem než iOS, kde jsou některé typy automatického ovládání aplikací omezené.

10.  Automatizace a proaktivita
JARVIS by neměl pouze čekat, až mu dáš příkaz.

Připomínky, budíky a časované úkoly.

Pravidelné kontroly počítače.

Kontrola dokončení stahování a instalací.

Automatické zálohování.

Sledování stavu běžících projektů.

Upozornění na nové důležité zprávy.

Ranní a večerní přehled.

Automatické spouštění vlastních workflow.

Podmíněné akce: „Když se stane X, proveď Y.“

Vlastní plánovač autonomních agentů.

11.  Internet, e-mail a produktivita
Vyhledávání informací a ověřování zdrojů.

Ovládání webového prohlížeče.

Vyplňování formulářů.

Shrnování článků a dokumentů.

Správa Gmailu a dalších podporovaných e-mailů.

Psaní a odesílání e-mailů.

Google Calendar a plánování schůzek.

Google Drive a práce s dokumenty.

Překlady a tvorba textů.

Tvorba prezentací, PDF a tabulek.

Hledání informací v osobních souborech.

Organizace úkolů a projektů.

12.  Hudba, hry a zábava
Ovládání Spotify a lokální hudby.

Hudební vizualizace v Dynamic Islandu.

Reaktivní animace Mochiho podle hudby.

Game Mode s omezením rušivých oznámení.

Monitoring FPS, CPU, GPU a teplot.

Automatická detekce spuštěné hry.

Pomoc s herními nastaveními.

Správa screenshotů a klipů.

Spouštění her a herních launcherů.

13.  Smart Home a další zařízení
Ovládání světel a zásuvek.

Integrace s Home Assistantem.

Ovládání televize a reproduktorů.

Bluetooth zařízení.

Podpora MQTT.

Automatizace domácnosti.

Ovládání podporovaných zařízení z telefonu.

Přehled senzorů a spotřeby.

14.  Bezpečnost a soukromí
Tohle je nezbytné, protože JARVIS bude mít přístup k celému počítači.

Detailní oprávnění pro každého agenta.

Potvrzování mazání souborů a dalších rizikových akcí.

Historie všech provedených operací.

Možnost zastavit běžícího agenta.

Náhled změn před jejich provedením.

Vrácení podporovaných změn.

Šifrované ukládání citlivých údajů.

Bezpečná správa API klíčů.

Lokální databáze paměti.

Nastavitelné mazání osobních dat.

Ochrana před škodlivými instrukcemi z webů a souborů.

Omezené prostředí pro nedůvěryhodný kód.

Viditelná indikace přístupu k mikrofonu, kameře a obrazovce.

15.  Pokročilé budoucí funkce
Tady bych JARVISe posunul ještě dál.

Teach Mode: Ukážeš mu postup a on z něj vytvoří automatizaci.

Self-Healing: Zjistí chybu ve vlastní aplikaci, připraví opravu a otestuje ji.

Computer Memory: Volitelně si pamatuje pracovní kontext napříč aplikacemi.

Predictive Assistant: Navrhuje další kroky podle tvých rozpracovaných úkolů.

Agent Marketplace: Instalace dalších schopností a rozšíření.

Universal Command Bar: Jeden příkaz ovládá celý počítač.

Personal Knowledge Graph: Propojuje projekty, soubory, lidi a informace.

Cross-device Handoff: Úkol začíná na telefonu a pokračuje na PC.

AI Skill Builder: JARVIS pomáhá vytvářet a testovat nové vlastní dovednosti.

Adaptive Resource Manager: Optimalizuje, kolik CPU, RAM a GPU jednotliví agenti používají.
```

## 10. ZÁVĚREČNÝ POVINNÝ POSTUP PRO CLAUDE CODE

1. Nejprve zkontroluj aktuální repozitář, strukturu, závislosti, testy, Git stav, existující funkcionalitu a platformy.
2. Vypracuj feature audit vůči celému zadání; schopnosti z původního seznamu 110+ i katalogu 001–795 zahrň do jedné normalizované evidence.
3. Seznam překryvů výslovně označ; nepřidávej redundantní moduly ani neodstraňuj již funkční integrace. Pokud již konkrétní funkce existuje, oprav chyby a rozšiřuj ji jen když tím prokazatelně získá na kvalitě.
4. Navrhni technicky reálný vývojový plán s malými ověřitelnými milníky, konkrétními riziky a jasnými akceptačními kritérii.
5. V otevřeném projektu začni bez zbytečných otázek prvním bezpečným a nedestruktivním vertikálním řezem, jestliže již není funkční; je-li funkční, vyber navazující nehotovou část podle priority.
6. Testuj, nehádej. Všechny zásahy do Windows, disků, vzdálených zařízení, soukromých dat a účtů dělej pouze podle oprávnění, s výslovným schválením rizikových kroků.
7. Po implementaci skutečně spustitelných částí aktualizuj audit, dokumentaci a testovací report. Ukaž přesně, co je hotové, co bylo už hotové před začátkem a co zůstává.
8. Nezapomeň: WINDOWS DESKTOP, ne fake web; elegantní notch, živý MOCHI, skutečná orchestraci misí, použitelná paměť, bezpečný Skill Forge, agenti a později Android/iPhone.

**Finální princip: zachovat vše, co už opravdu funguje; neduplikovat; opravit a vylepšit; bezpečně integrovat nové schopnosti do jednoho působivého a skutečně užitečného systému JARVIS OMEGA ∞.**
