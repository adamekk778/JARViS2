// "Co je nového" (3.0): shown once in the window after JARVIS updates to a new feature version.
import { h, icon } from "./dom";
import type { JarvisClient } from "./ws";

export const WHATS_NEW: Record<string, { icon: string; title: string; line: string }[]> = {
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
