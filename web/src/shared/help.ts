// OMEGA 035: interactive feature tips. A "?" button (or F1) switches on help mode: hovering or focusing anything that has a
// tip shows what it does and how to ask for it by voice; "Prohlídka" walks through the main sections one by one.
import "./help.css";
import { h, icon } from "./dom";

export const HELP: Record<string, string> = {
  chat: "Piš nebo mluv – JARVIS odpoví a sám udělá, co jde (otevře, najde, napíše). Zkus: „co mám dnes v kalendáři?“",
  stark: "Protokoly na jedno slovo (Ranní, Párty…), ranní brífink, strážce PC a holografický HUD. Zkus: „spusť protokol ranní“.",
  auto: "Pravidla „Když … tak …“: když přijde e-mail, když odejdeš od PC, v určitý čas… Vyzkoušíš je nanečisto.",
  home: "Chytrá domácnost přes Home Assistant: světla, zásuvky, teplota. Zkus: „zhasni v obýváku“.",
  knowledge: "Co si JARVIS pamatuje, projekty, časová osa dne a rozpory v paměti. Zkus: „co víš o projektu Atlas?“",
  learn: "Kartičky s opakováním, testy, ústní zkouška, učení na projektu a programovací úlohy.",
  files: "Duplicity, třídění, hromadné přejmenování, převody, zálohy – změny vždy s náhledem a potvrzením.",
  rescue: "Proč je PC pomalé, co padá, ovladače, disky, baterie – a 3D pohled na součástky počítače.",
  security: "Antivirus, firewall, kdo smí kameru a mikrofon, souhlasy, soukromí a co JARVIS ukládá.",
  comms: "E-mail, kalendář a telefon: důležité zprávy, odpovědi k potvrzení, hovory a SMS z mobilu.",
  tasks: "Mise krok za krokem s důkazy, fronta úkolů a živá mapa agentů, kteří právě pracují.",
  "voice-mode": "Celá obrazovka jen pro rozhovor hlasem.",
  claude: "Claude Code v notchi: schvalování jeho kroků z PC i telefonu.",
  play: "Minihra s Mochim na odpočinek.",
  dictate: "Diktuj do jakékoli aplikace – podrž pravý Ctrl a mluv.",
  notetaker: "Nahrávání hovorů a schůzek se shrnutím a úkoly. Mikrofon se nikdy nezapne potají.",
  stats: "Kolik toho nadiktuješ a ušetříš času.",
  general: "Jméno, oslovení, město a jazyk.",
  brain: "Které AI JARVIS používá, pořadí záložních a místní modely bez internetu.",
  voice: "Hlas JARVISe, probouzecí slovo „Hey Jarvis“, navazování v rozhovoru a nálada z tónu hlasu.",
  notch: "Výřez nahoře na obrazovce s Mochim: co v něm vidíš, kdy se otevře, hudba a hra na okraji.",
  appearance: "Barvy, hustota a velikost rozhraní, ovládání dotykem, zvuky a živé titulky.",
  permissions: "Co smí JARVIS dělat sám, co jen s potvrzením a co vůbec.",
};

export function helpMode(nav: HTMLElement): HTMLElement {
  const tip = h("div", { class: "help-tip", role: "tooltip", hidden: true });
  let on = false;
  let tour = -1;
  const targets = () => [...nav.querySelectorAll<HTMLElement>("[data-view]")].filter((b) => HELP[b.dataset.view || ""]);
  nav.querySelectorAll<HTMLElement>("[data-view]").forEach((b) => { const t = HELP[b.dataset.view || ""]; if (t) b.dataset.help = t; });
  const show = (el: HTMLElement, extra?: HTMLElement) => {
    const r = el.getBoundingClientRect();
    tip.replaceChildren(h("strong", {}, el.getAttribute("title") || el.textContent || ""), h("p", {}, el.dataset.help || ""), extra || "");
    tip.hidden = false;
    tip.style.left = `${Math.min(window.innerWidth - 340, r.right + 12)}px`;
    tip.style.top = `${Math.max(8, Math.min(window.innerHeight - 160, r.top - 4))}px`;
    document.querySelectorAll(".help-focus").forEach((x) => x.classList.remove("help-focus"));
    el.classList.add("help-focus");
  };
  const hide = () => { tip.hidden = true; document.querySelectorAll(".help-focus").forEach((x) => x.classList.remove("help-focus")); };
  const set = (v: boolean) => { on = v; document.documentElement.classList.toggle("help-mode", v); btn.classList.toggle("on", v); if (!v) { hide(); tour = -1; } };
  const step = (d: number) => {
    const list = targets();
    tour = (tour + d + list.length) % list.length;
    const el = list[tour];
    el.scrollIntoView({ block: "nearest" });
    show(el, h("div", { class: "help-nav" },
      h("span", { class: "muted" }, `${tour + 1} / ${list.length}`),
      h("button", { class: "btn ghost sm", type: "button", onclick: () => step(-1) }, "Zpět"),
      h("button", { class: "btn primary sm", type: "button", onclick: () => step(1) }, "Další"),
      h("button", { class: "btn ghost sm", type: "button", onclick: () => set(false) }, "Konec")));
  };
  const over = (e: Event) => {
    if (!on || tour >= 0) return;
    const el = (e.target as HTMLElement).closest<HTMLElement>("[data-help]");
    if (el) show(el); else hide();
  };
  document.addEventListener("mouseover", over);
  document.addEventListener("focusin", over);
  document.addEventListener("keydown", (e) => {
    if (e.key === "F1") { e.preventDefault(); set(!on); }
    else if (e.key === "Escape" && on) set(false);
    else if (on && tour >= 0 && (e.key === "ArrowDown" || e.key === "ArrowRight")) step(1);
    else if (on && tour >= 0 && (e.key === "ArrowUp" || e.key === "ArrowLeft")) step(-1);
  });
  const btn = h("button", { class: "help-btn", type: "button", title: "Nápověda: co co dělá (F1)", "aria-label": "Nápověda", onclick: () => set(!on) }, icon("question"));
  const tourBtn = h("button", { class: "help-tour", type: "button", onclick: () => { set(true); tour = -1; step(1); } }, icon("signpost"), "Prohlídka");
  return h("div", { class: "help-host" }, tip, h("div", { class: "help-fab" }, tourBtn, btn));
}
