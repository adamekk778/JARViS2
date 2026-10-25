// "Co je nového" (3.0): shown once in the window after JARVIS updates to a new feature version.
import { h, icon } from "./dom";
import type { JarvisClient } from "./ws";

export const WHATS_NEW: Record<string, { icon: string; title: string; line: string }[]> = {
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
