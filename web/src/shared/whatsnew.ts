// "Co je nového" (3.0): shown once in the window after JARVIS updates to a new feature version.
import { h, icon } from "./dom";
import type { JarvisClient } from "./ws";

export const WHATS_NEW: Record<string, { icon: string; title: string; line: string }[]> = {
  "3.10": [
    { icon: "plugs", title: "OmniRoute jen s klíčem", line: "U OmniRoute stačí vložit API klíč: JARVIS ho hned vyzkouší a sám si najde model, který tvůj OmniRoute nabízí. Když něco chybí, napíše srozumitelně co. Všechny rozměry a časy notche v Nastavení se navíc projeví hned." },
    { icon: "wave-sine", title: "Plynulý notch", line: "Notch se otevírá a zavírá plynule: jeho okraj už při animaci neposkakuje a okno notche nemění velikost na začátku a na konci každého pohybu." },
    { icon: "wrench", title: "Notch bez šedého rámečku", line: "Kolem notche už není šedý obdélník: v tmavém režimu Windows za notch kreslily efekt Mica, ten je teď vypnutý. Notch má zase ostré okraje, které fungují na každém počítači (vyhlazené si můžeš zapnout v Nastavení → Notch), a když Windows zahodí oříznutí okna na tvar notche, JARVIS ho do dvou sekund vrátí." },
    { icon: "smiley", title: "Mochi ožívá", line: "Když pracují agenti, odštěpí se od Mochiho malí pomocníci a po práci s ním zase splynou (dvojklik = rozdělí se pro radost). Mochiho si můžeš vzít do telefonu, odkazy a soubory mezi PC a mobilem viditelně přeletí, po delším klidu proběhne po okraji obrazovky a notch se přesune nad okno, ve kterém JARVIS právě pracuje. Zvuky přicházejí ze strany, kde se něco děje. Nově je tu nápověda (F1) s prohlídkou, 3D pohled do počítače a ovládání telefonu jednou rukou." },
    { icon: "moon-stars", title: "Klid na práci a lepší přehled", line: "Režim soustředění ztiší a zprůhlední notch a upozornění ti dá až potom najednou – stejně tak při schůzce nebo hře. U označeného textu hned uvidíš částku v korunách, dny do data, součty a kontrolu IČO či IBAN. Protokol si přehraješ nanečisto jako animovaný graf, v Úkolech vidíš živou mapu agentů, v notchi mapu oken (přepínáš i šipkami) a můžeš zapnout velké živé titulky." },
    { icon: "monitor-play", title: "PC hlídá a sdílí", line: "Každý den sám zazálohuje složku na disk (a připomene, když disk chybí), dá vědět, když se dokončí stahování nebo instalace, uklidí snímky obrazovky a klipy, ukáže baterii Bluetooth sluchátek a myši. Obrazovku PC uvidíš na telefonu (jen po potvrzení a na chvíli), propojíš další počítač s JARVISem, v notchi se hýbou pruhy podle hudby a mapa ukáže, kdo s kým a s jakým projektem souvisí. Nově umí (po zapnutí) poznat únavu nebo spěch z tónu hlasu." },
    { icon: "pen-nib", title: "Designové studio", line: "Kontrola webu na telefonu, tabletu i monitoru (co přečnívá, malá tlačítka), editor animačních křivek s úchyty, skleněný panel s hlídáním čitelnosti, jednotná sada ikon ze složky SVG, časová osa animace z obyčejného popisu a teplotní mapa, kde je obrazovka přeplněná." },
    { icon: "record", title: "Nahraj postup a pošli ho dál", line: "Řekni „začni nahrávat“, udělej práci a po „stop“ z ní JARVIS udělá dovednost na jeden příkaz (zapisuje jen své kroky a názvy aplikací). Postup pošleš kamarádovi bez hesel a klíčů – a cizí postup ti ukáže krok po kroku, než ho přidáš. Navíc návrh animované scény s náhledem a skriptem pro Blender, kostra pro 3D postavu a přepnutí zvuku na sluchátka či reproduktory." },
    { icon: "chalkboard-teacher", title: "Schůzky, učení a klienti", line: "JARVIS spočítá, kolik hodin měsíčně ti berou opakované porady a které z nich nic nepřinesly – a poradí zkrátit, zředit nebo zrušit. Ke schůzce udělá složku se zápisem, úkoly a dokumenty. Dá ti programovací úlohu a zkontroluje řešení testy, naučí tě něco na skutečném projektu krok za krokem a klientovi připraví soukromou stránku s jeho nabídkami a stavem požadavků." },
    { icon: "brain", title: "JARVIS přemýšlí dopředu", line: "Pod odpovědí vidíš Zdroje – weby, soubory a e-maily, ze kterých čerpal. Odhadne, co budeš dělat dál, všimne si práce, kterou děláš pořád dokola, a nabídne z ní jednu dovednost. Najde rozpory ve smlouvách (30 vs. 14 dní), opraví kód, dokud neprojdou testy (jen v kopii), poradí, co odložit, když se úkoly nevejdou, přenese tabulku ze schránky do Excelu nebo text do kalendáře, zjistí, co umí program v PC, a ukáže všechno o člověku či projektu napříč počítačem. Na dotykové obrazovce se tlačítka sama zvětší." },
    { icon: "cpu", title: "Chytřejší místní AI", line: "JARVIS spočítá, kolik modelu se vejde na grafickou kartu, a tvoje dotazy pustí vždy před práci na pozadí. Opakované otázky si pamatuje a hra přes celou obrazovku, slabá baterie či plná paměť mají přednost – model na chvíli ustoupí. Přidáš offline balíčky znalostí (složka nebo zip s návody), vytvoříš webhook pro e-shop či GitHub, konektor k API z příkazu curl, zkusíš ho nanečisto a přehraješ si, co by automatizace udělaly." },
    { icon: "device-mobile", title: "Telefon umí víc", line: "Widget na plochu telefonu (co JARVIS dělá a co máš připnuté), zkratky na ikoně, fotka z telefonu rovnou na PC – nebo „Fotka → úkoly“ z papírku či tabule. Když PC není dostupné, zprávy a nahrávky počkají v telefonu. V telefonu procházíš soubory ze složek, které na PC povolíš. Kamarád dostane dočasný QR jen na hudbu a hlasitost, na dveře si vytiskneš QR s příkazem, telefon umí místa pro „Když přijdu domů…“ (poloha zůstává v telefonu) a na PC určíš, co smí telefon dělat." },
    { icon: "push-pin", title: "Notch ví, co děláš", line: "Klikni pravým tlačítkem na postavičku: kolem ní se objeví akce přesně pro aplikaci, ve které jsi (Excel, prohlížeč, Word…), a co se hodí teď – schůzka za chvíli, odkaz ve schránce. Do notche si připneš malé úkoly s časem („zítra v 9“), uložíš si pracovní plochy s okny, zamkneš notch proti náhodnému otevření a v HUD přepneš rozložení (i na prezentaci). Postavička je pružnější, po delším klidu se schová za okraj – a v aplikaci je nová minihra „Chyť hvězdy“." },
    { icon: "smiley-wink", title: "Postavička reaguje na svět", line: "Po probuzení počítače se protáhne, ukáže hlasitost i ztlumení, všimne si připojeného disku, přepnutí AI a kopírování souborů. Podle počasí si vezme deštník, ráno kávu, v noci tlumí záři. Když se nudí, hraje si. Vyber jí povahu a v Nastavení si nadefinuj vlastní reakce – a zkus jí říct „udělej barrel roll“." },
    { icon: "film-strip", title: "Video studio", line: "Video na výšku pro TikTok a Reels s výřezem, který sleduje děj, krátké klipy z nejlepších momentů, barevné sjednocení záběrů (LUT), kapitoly podcastu, srovnání titulků s řečí, animace loga a textů, knihovna zvukových efektů, uspořádání fotek a videí – a fronta renderů na pozadí." },
    { icon: "wrench", title: "Péče o počítač", line: "Který ovladač způsobil pády a jak ho vrátit, nastavení napájení a zdraví baterie, záchranný disk, které služby na sobě závisí, plynulost her, jak rychle se otevírají programy, profily výkonu – a po restartu nabídne otevřít okna jako minule." },
    { icon: "briefcase", title: "Firma pod kontrolou", line: "Číslované nabídky s přehledem, co se přijalo, podklady k fakturaci z výkazu, požadavky zákazníků s termíny, srovnání dodavatelů, vyhodnocení kampaní, příjmy a výdaje z výpisu z banky, SEO audit webu, hlídání konkurence a komu se dnes ozvat." },
    { icon: "waveform", title: "Čistý hlas", line: "JARVIS odfiltruje hluk místnosti, neslyší sám sebe (můžeš mu skočit do řeči), zesílí tichý hlas z dálky a při poslouchání ztiší hudbu. Navíc kontrola mikrofonu, nastavení citlivosti „Hey Jarvis“, záložky v hovorech, rozlišení mluvčích a nácvik výslovnosti." },
    { icon: "flask", title: "Laboratoř", line: "Co říká graf, odkud se v databázi berou čísla, fyzikální simulace s hledáním nejlepšího parametru, ověření citací (i stažených článků), návrh pokusu, plán zkoušek prototypu a procvičování obvodů, které se přizpůsobí." },
    { icon: "palette", title: "Kreativní studio", line: "Jedna fotka do všech formátů sítí, kontrola barev značky, varianty popisků, evidence licencí a původu, pohyb kamery a světla pro Blender, rada k mixu, storyboard na časovou osu a klikací ukázka produktu." },
    { icon: "game-controller", title: "Herní studio", line: "Svět ze semínka, generátor levelů, kontrola dialogů a questů, šance na loot, ekonomika, férovost mapy, balanc jednotek a jak hru vidí barvoslepí." },
    { icon: "circuitry", title: "Dílna a plánování", line: "Kusovník součástek, jestli k sobě moduly sedí (3,3 V vs 5 V), sériový monitor pro Arduino, graf ze senzorů, rameno robota, plán úkolů s kritickou cestou – a „kde jsem to viděl?“ hledá všude najednou." },
    { icon: "house-line", title: "Chytrá domácnost", line: "„Zhasni v obýváku“, kolik spotřebovala pračka, které čidlo má slabou baterii, co čeká na aktualizaci, co se doma dělo – a pravidla „Když … tak …“ si vyzkoušíš nanečisto." },
    { icon: "hard-drives", title: "Servisní technik", line: "Kde na disku jsou vadná místa, které USB zařízení zlobí kvůli napájení, jak zachránit data z umírajícího disku a protokol pro servis. A u webů: certifikát, e-mailové záznamy, výpadky, logy a zálohy." },
    { icon: "browsers", title: "Chytrý prohlížeč", line: "Nahraj postup na webu a JARVIS ho zopakuje (hesla nikdy neukládá), odmítne cookies, ukáže kdo tě sleduje, ověří stahovaný soubor a spočítá, kolik platíš za předplatná." },
    { icon: "plugs-connected", title: "Připoj jakékoli API", line: "Dej JARVISovi popis API (OpenAPI) a ptej se běžnou řečí – čtení hned, změny jen po potvrzení. Klíče v trezoru Windows, hlídání vypršení a limitů, převod a slučování dat." },
    { icon: "books", title: "Tvoje dokumenty", line: "„Zaindexuj složku Dokumenty“ a pak se ptej: JARVIS odpoví jen z tvých smluv, PDF a poznámek a u každé věty řekne, odkud je. Plus test rychlosti a přesnosti místních modelů." },
    { icon: "film-slate", title: "Studio", line: "Vystřihne ticha z nahrávky, ztiší hudbu pod řečí, vyčistí šum, změří hlasitost pro YouTube či podcast, najde střihy ve videu, opraví titulky – a barvy, kontrast a design systém pro web." },
    { icon: "briefcase", title: "Podnikání", line: "Cenová nabídka s DPH do Wordu, kteří zákazníci odcházejí, které leady jsou horké, kde utíká trychtýř, co udělá zdražení, předpověď tržeb a které zakázky prodělávají." },
    { icon: "flask", title: "Inženýr a vědec", line: "Počítání s jednotkami („5 km za 2 h na m/s“), odpor pro LED, kolik stojí spotřebiče, je rozdíl skutečný (statistika, A/B test), frekvence ve zvuku, čištění tabulek, tolerance a kontrola 3D modelu před tiskem." },
    { icon: "factory", title: "Softwarová továrna", line: "Z nápadu požadavky a akceptační kritéria, z kontraktu API testovací server i hotová knihovna pro volání, plán návratu na starší verzi a kontrola naplánovaných úloh." },
    { icon: "test-tube", title: "Testovací laboratoř", line: "Zátěž s desítkami uživatelů, divné vstupy, simulace špatné sítě, únik paměti, poškozená data – a web na telefonu, bez internetu, jen klávesnicí nebo jako uživatel krok po kroku se snímky." },
    { icon: "code", title: "Vývojářská laboratoř", line: "Rizika a zranitelnosti knihoven, plán aktualizací, SBOM, proč selhal build, kontrola API proti kontraktu, náhled migrace, mutační testy, nestabilní testy a poznámky k vydání z commitů." },
    { icon: "database", title: "Databáze", line: "Co je v databázi, jestli není poškozená, proč je dotaz pomalý (a jaký index pomůže), jestli jde záloha opravdu obnovit a kde jsou osobní údaje. Anonymní kopie pro testování – originál zůstane." },
  ],
  "3.9": [
    { icon: "squares-four", title: "Pracovní prostředí", line: "„Ulož si tohle rozložení jako Práce“ – příště JARVIS otevře chybějící programy a rozmístí okna. I okno na druhý monitor a zkratky pro aplikaci." },
    { icon: "suitcase-rolling", title: "Každý den", line: "Co zabalit podle počasí v cíli, kdy jít ven, plán stěhování nebo svatby, nákup podle oddělení a co ještě nastavit." },
    { icon: "lightbulb", title: "JARVIS myslí dopředu", line: "„Co mám dělat teď?“ – hořící termíny, zapomenuté úkoly, nedořešené otázky a tvoje rutiny. V noci, na schůzce a ve hře mlčí (budík ale vždy zazvoní)." },
    { icon: "graduation-cap", title: "Učení", line: "Kartičky s chytrým opakováním, testy z tvých zápisků, kontrola výpočtů krok po kroku, ústní zkoušení a plán před zkouškou." },
    { icon: "tray", title: "Jedna schránka", line: "E-maily i zprávy z telefonu seřazené podle důležitosti, co po tobě kdo chce, na co ti neodpověděli, karty kontaktů a zápisy ze schůzek s úkoly." },
    { icon: "users-three", title: "Tým specialistů", line: "„Ať to otestuje tester“, „nech architekta posoudit projekt“ – a hloubkový výzkum, kde je každé tvrzení doložené zdrojem." },
    { icon: "brain", title: "Paměť a projekty", line: "Najdi cokoli, o čem jste mluvili (i bez háčků), časová osa dne, projekty s vlastní pamětí a „navaž, kde jsme skončili“. JARVIS pozná, když si něco odporuje." },
    { icon: "folders", title: "Soubory", line: "Duplicity do koše, podobné fotky, roztřídění Stažených podle obsahu, hromadné přejmenování s vrácením, převody formátů a záloha s ověřením." },
    { icon: "eraser", title: "Fotky bez polohy", line: "Před sdílením odstraní z fotek GPS, fotoaparát i autora dokumentů – originál zůstane." },
  ],
  "3.8": [
    { icon: "first-aid-kit", title: "Záchrana a výkon", line: "Nová stránka: proč PC padá (modré obrazovky česky), ovladače, USB, disky, pomalý start, služby – jen čte a radí, report ověří." },
    { icon: "gauge", title: "Co brzdí počítač", line: "Procesor, grafika, RAM, disk i odezva internetu v jednom měření. Test výkonu s porovnáním před/po a graf za 24 hodin." },
    { icon: "shield-warning", title: "Bezpečnostní centrum", line: "Je odkaz podvod? Je stažený soubor bezpečný? Uniklo heslo? Klíče v kódu, ověření zálohy a bod obnovy jedním klikem." },
  ],
  "3.7": [
    { icon: "shield-check", title: "Bezpečí a soukromí", line: "Nová stránka: režim jen pro čtení, dvojí potvrzení, dočasná oprávnění, soukromý režim, mazání starých dat, šifrovaná záloha a export." },
    { icon: "queue", title: "Fronta misí", line: "Úkoly → Fronta misí: naplánuj misi na čas, s termínem. Přerušená mise jde Pokračovat od místa, kde skončila." },
    { icon: "coins", title: "Spotřeba a limit AI", line: "Kolik dnes stály odpovědi a kam co šlo – a denní limit, po kterém JARVIS použije jen bezplatné modely." },
  ],
  "3.6": [
    { icon: "stethoscope", title: "Mise: stav počítače", line: "Úkoly → Zkontrolovat PC (nebo „zjisti stav mého počítače“): jen čte, uloží report a ověří ho – kritéria, důkazy a soubor uvidíš v Úkolech." },
    { icon: "magic-wand", title: "Skill Forge", line: "Z hotové mise udělej dovednost („ulož to jako dovednost“). Každá úprava má verzi a jde vrátit zpět." },
    { icon: "shield-check", title: "Mise přežijí restart", line: "Když se JARVIS vypne uprostřed práce, mise se označí jako Přerušená a jde jedním klikem zopakovat." },
  ],
  "3.5": [
    { icon: "flow-arrow", title: "Automatizace „Když … tak …“", line: "„Když otevřu Spotify, dej hlasitost na 30“, „když mi napíše máma, řekni mi to“, „když odejdu od PC, pozastav hudbu“." },
    { icon: "house-line", title: "Chytrá domácnost", line: "Připoj Home Assistant: „rozsviť v obýváku“, „zhasni všechno“, „nastav topení na 22“. Zámky a vrata vždy potvrdíš." },
    { icon: "list-checks", title: "Seznamy a peníze", line: "„Přidej mléko na nákup“ (seznam máš i v mobilu), „kolik je euro“, „dej vědět, až bitcoin klesne pod…“." },
    { icon: "device-mobile", title: "Najdi můj telefon a Wi-Fi", line: "„Najdi můj telefon“ ho rozezvučí naplno, „kdo je na Wi-Fi“, „zapni počítač v pracovně“." },
  ],
  "3.4": [
    { icon: "envelope-simple", title: "JARVIS a tvůj e-mail", line: "Připoj Seznam nebo Gmail: „co mi přišlo“, „odpověz Petrovi…“. Nové e-maily hlásí hned, odeslání vždy potvrdíš." },
    { icon: "phone-call", title: "JARVIS ti zavolá", line: "Telefon zazvoní jako hovor a JARVIS řekne, co potřebuje. „Zavolej mi za 20 minut a připomeň…“." },
    { icon: "chat-circle-text", title: "Volání, SMS, WhatsApp", line: "„Zavolej mámě“, „pošli Petrovi SMS“, a na PC uvidíš, kdo ti píše na telefon." },
    { icon: "calendar-check", title: "Kalendář", line: "„Co mám zítra?“, „naplánuj schůzku ve 3“ – i Google a Seznam kalendář, s připomínkou." },
  ],
  "3.3": [
    { icon: "text-aa", title: "Označený text kdekoli", line: "Označ text v jakékoli aplikaci a zmáčkni Ctrl+Alt+E: opravit, přeložit, zkrátit, vysvětlit. Nebo to řekni." },
    { icon: "clipboard-text", title: "Historie schránky", line: "„Co jsem kopíroval před chvílí?“ – jen v paměti, hesla si nepamatuje." },
    { icon: "eye", title: "Hlídání webu", line: "„Dej mi vědět, až bude na téhle stránce skladem.“" },
    { icon: "broom", title: "Úklid, rychlost, čas u PC, e-maily", line: "„Co mi zabírá místo“, „ukliď počítač“, „jak rychlý mám internet“, „kolik jsem dnes hrál“, „napiš e-mail…“." },
  ],
  "3.2": [
    { icon: "circle-notch", title: "Stark HUD", line: "Holografický přehled přes celou obrazovku s arc reaktorem: Ctrl+Alt+H, tlačítko v notchi nebo „ukaž HUD“." },
    { icon: "lightning", title: "Protokoly", line: "„Spusť protokol Párty“, „Dobrou noc“, „Pracovní režim“… a vlastní si poskládáš v sekci Stark." },
    { icon: "sun-horizon", title: "Ranní brífink", line: "Ráno ti JARVIS sám řekne počasí, plány, stav PC a hlavní zprávy." },
    { icon: "shield-check", title: "Strážce", line: "Sám upozorní na slabou baterii, přetížený procesor, plný disk nebo výpadek internetu." },
  ],
  "3.1": [
    { icon: "arrows-out-simple", title: "Celý chat přes celou obrazovku", line: "Tlačítko v notchi, v okně i v liště: chat jako ChatGPT, s režimy Chat a Agent." },
    { icon: "browser", title: "JARVIS staví weby", line: "Řekni „udělej mi web pro…“ a náhled uvidíš hned v chatu – i jak vypadá na telefonu." },
    { icon: "sparkle", title: "Ostré a plynulé", line: "Notch a okna jsou ostré i při zvětšení ve Windows. Mazlíček na ploše je pryč." },
  ],
  "3.0": [
    { icon: "microphone", title: "Diktování kdekoli", line: "Drž pravý Ctrl v jakékoli aplikaci, mluv a pusť – text se napíše sám." },
    { icon: "record", title: "Nahrávání hovorů", line: "Přepis po lidech, shrnutí a úkoly. Žádný bot v hovoru, zvuk se pak smaže." },
    { icon: "terminal-window", title: "Claude Code v notchi", line: "Vidíš, co Claude dělá, a schvaluješ jeho akce z notche i z telefonu (otiskem prstu)." },
    { icon: "sparkle", title: "Nový vzhled a živější JARVIS", line: "Okno ve stylu Coucou, statistiky, týdenní přehled, šatník a vlastní zvuky." },
  ],
};

export function whatsNewOverlay(client: JarvisClient) {
  let shown = false;
  client.on("welcome", (m) => {
    const items = WHATS_NEW[m.whats_new];
    if (!items || shown) return;
    shown = true;
    const close = () => { root.remove(); window.removeEventListener("keydown", onKey); client.send("whats_new_seen"); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    const root = h("div", { class: "palette show recap-overlay", onclick: (e: MouseEvent) => { if (e.target === root) close(); } },
      h("div", { class: "recap-box" }, h("div", { class: "card whatsnew" },
        h("div", { class: "rc-head" }, h("div", {}, h("p", { class: "group-label" }, `JARVIS ${m.whats_new}`), h("h2", {}, "Co je nového")),
          h("button", { class: "icon-btn", type: "button", "aria-label": "Zavřít", onclick: close }, icon("x"))),
        ...items.map((it) => h("div", { class: "wn-item" }, h("span", { class: "suggest-ico" }, icon(it.icon)),
          h("div", {}, h("strong", {}, it.title), h("p", {}, it.line)))),
        h("div", { class: "btn-row" }, h("button", { class: "btn primary", type: "button", onclick: close }, "Super, jdeme na to")))));
    document.body.append(root);
  });
}
