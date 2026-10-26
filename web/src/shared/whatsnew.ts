// "Co je nového" (3.0): shown once in the window after JARVIS updates to a new feature version.
import { h, icon } from "./dom";
import type { JarvisClient } from "./ws";

export const WHATS_NEW: Record<string, { icon: string; title: string; line: string }[]> = {
  "3.10": [
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
