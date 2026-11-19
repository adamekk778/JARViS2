// 3.13 "Vyzkoušej novinky": after an update the new things one by one on YOUR PC – a button tries each, JARVIS ticks
// what it can see by itself (you said "Hey Jarvis", you talked over it, the phone went on the charger, a game started),
// and what does not work becomes one text to paste to the developer (with the diagnostics, never keys or passwords).
import { h, icon, toast } from "./dom";
import type { JarvisClient } from "./ws";

type State = "wait" | "ok" | "bad";
interface Item { id: string; icon: string; title: string; how: string; run?: string; auto?: (m: any, type: string) => boolean }

const ITEMS: Item[] = [
  { id: "notice", icon: "bell-simple", title: "Upozornění s tlačítky v notchi", how: "Klikni Vyzkoušet – v notchi se ukáže upozornění s tlačítkem.", run: "notice" },
  { id: "tip", icon: "lightbulb", title: "Tip do hry v notchi", how: "Klikni Vyzkoušet – notch ukáže tip k Valorantu s tlačítkem Další tip.", run: "game_tip" },
  { id: "voice", icon: "speaker-high", title: "Hlas JARVISe", how: "Klikni Vyzkoušet – JARVIS řekne krátkou větu.", run: "voice" },
  { id: "wake", icon: "microphone", title: "„Hey Jarvis“", how: "Řekni „Hey Jarvis“ – odškrtne se samo, jakmile tě uslyší.",
    auto: (m, t) => t === "state" && m.state === "listening" },
  { id: "barge", icon: "hand-palm", title: "Skočit JARVISovi do řeči", how: "Klikni Vyzkoušet a zatímco mluví, začni mluvit ty – měl by zmlknout.", run: "barge",
    auto: (_m, t) => t === "barge_in" },
  { id: "phone", icon: "device-mobile", title: "Telefon v notchi", how: "Dej telefon do nabíječky (nebo ho odpoj) – notch to ukáže a tady se to odškrtne.",
    auto: (_m, t) => t === "phone_event" },
  { id: "game", icon: "game-controller", title: "Herní režim a tipy", how: "Spusť hru přes celou obrazovku – notch ukáže, co hraješ, a JARVIS během ní nemluví.",
    auto: (m, t) => t === "game_state" && m.on },
];

export function openTrial(client: JarvisClient) {
  const state: Record<string, State> = Object.fromEntries(ITEMS.map((i) => [i.id, "wait"]));
  const rows: Record<string, HTMLElement> = {};
  const chip = (s: State) => h("span", { class: `tr-chip ${s}` }, s === "ok" ? "✓ funguje" : s === "bad" ? "✗ nefunguje" : "čeká");
  const paint = (it: Item) => {
    const row = rows[it.id];
    row.querySelector(".tr-chip")?.replaceWith(chip(state[it.id]));
    row.classList.toggle("done", state[it.id] !== "wait");
  };
  const set = (it: Item, s: State) => { state[it.id] = s; paint(it); };
  const list = h("div", { class: "tr-list" }, ...ITEMS.map((it) => {
    const row = h("div", { class: "tr-row" },
      h("span", { class: "suggest-ico" }, icon(it.icon)),
      h("div", { class: "tr-text" }, h("strong", {}, it.title), h("p", {}, it.how)),
      h("div", { class: "tr-acts" },
        chip("wait"),
        it.run ? h("button", { class: "btn sm", type: "button", onclick: () => client.send("trial_run", { item: it.run }) }, icon("play", "ph-fill"), "Vyzkoušet") : null,
        h("button", { class: "btn sm ghost", type: "button", title: "Funguje", "aria-label": "Funguje", onclick: () => set(it, "ok") }, icon("check")),
        h("button", { class: "btn sm ghost", type: "button", title: "Nefunguje", "aria-label": "Nefunguje", onclick: () => set(it, "bad") }, icon("x"))));
    rows[it.id] = row;
    return row;
  }));
  const offs = ITEMS.filter((i) => i.auto).map((it) => {
    const types = ["state", "barge_in", "phone_event", "game_state"];
    return types.map((t) => client.on(t as any, (m: any) => { if (state[it.id] === "wait" && it.auto!(m, t)) set(it, "ok"); }));
  });
  void offs;
  const report = h("button", { class: "btn", type: "button" }, icon("clipboard-text"), "Zkopírovat zprávu pro opravu");
  report.onclick = () => {
    const bad = ITEMS.filter((i) => state[i.id] === "bad").map((i) => `✗ ${i.title}`);
    const ok = ITEMS.filter((i) => state[i.id] === "ok").map((i) => `✓ ${i.title}`);
    const head = `Vyzkoušení novinek JARVIS:\n${[...bad, ...ok].join("\n") || "(nic nevyzkoušeno)"}`;
    const off = client.on("diagnostics_summary", (m: any) => {
      const text = `${head}\n\n${m.text || ""}`;
      navigator.clipboard?.writeText(text).catch(() => {});
      toast("Zkopírováno – vlož to do chatu s vývojářem", "ok");
      if (typeof off === "function") (off as () => void)();
    });
    client.send("diagnostics_summary");
  };
  const close = () => root.remove();
  const root = h("div", { class: "palette show recap-overlay", onclick: (e: MouseEvent) => { if (e.target === root) close(); } },
    h("div", { class: "recap-box" }, h("div", { class: "card whatsnew trial" },
      h("div", { class: "rc-head" }, h("div", {}, h("p", { class: "group-label" }, "Na tvém PC"), h("h2", {}, "Vyzkoušej novinky")),
        h("button", { class: "icon-btn", type: "button", "aria-label": "Zavřít", onclick: close }, icon("x"))),
      h("p", { class: "help" }, "Co se dá, odškrtne JARVIS sám. U ostatního klikni ✓ nebo ✗ – z toho, co nefunguje, je jedna zpráva pro opravu."),
      list,
      h("div", { class: "btn-row" }, report, h("button", { class: "btn primary", type: "button", onclick: close }, "Hotovo")))));
  document.body.append(root);
}
