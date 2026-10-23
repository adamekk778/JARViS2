// Dictation anywhere (3.0): the Diktování page (greeting band, history, numbers), the Statistiky page and the
// weekly recap. Layout after the Coucou window: a band, history on the left, a narrow column of numbers.
import { fmtTime, h, icon, toast } from "../shared/dom";
import { hero, HEROES } from "../shared/hero";
import type { JarvisClient } from "../shared/ws";

const KEY_LABEL: Record<string, string> = {
  "right ctrl": "pravý Ctrl", "right alt": "pravý Alt", "caps lock": "Caps Lock", "scroll lock": "Scroll Lock",
  f8: "F8", f9: "F9", f10: "F10",
};
export const dictKey = (s: any) => KEY_LABEL[s?.dictation?.key] ?? "pravý Ctrl";

const n = (v: number) => v.toLocaleString("cs-CZ");
function dur(s: number): string {
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1).replace(".", ",")} h`;
}
const plural = (v: number, one: string, few: string, many: string) => (v === 1 ? one : v >= 2 && v <= 4 ? few : many);

function dayLabel(ts: number): string {
  const d = new Date(ts * 1000);
  const today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Dnes";
  if (d.toDateString() === y.toDateString()) return "Včera";
  return d.toLocaleDateString("cs-CZ", { weekday: "long", day: "numeric", month: "numeric" });
}

/** The Diktování page. */
export function buildDictation(client: JarvisClient, go: (v: string) => void) {
  let settings: any = null;
  const sub = h("p", {});
  const band = hero(HEROES.dictate, "Ahoj", null, [
    h("button", { class: "btn primary", type: "button", onclick: () => go("notetaker") }, icon("record", "ph-fill"), "Nahrát hovor"),
    h("button", { class: "btn", type: "button", onclick: () => go("dictation") }, icon("sliders"), "Nastavení"),
  ]);
  band.querySelector(".hero-copy h1")!.after(sub);
  const title = band.querySelector(".hero-copy h1")!;

  const q = h("input", { class: "input", type: "search", placeholder: "Hledat v diktátech…", "aria-label": "Hledat v diktátech" }) as HTMLInputElement;
  let qt = 0;
  q.oninput = () => { clearTimeout(qt); qt = window.setTimeout(() => client.send("dictation_get", { q: q.value, period: "month" }), 250); };
  const list = h("div", { class: "d-history" });
  const side = h("div", { class: "d-side" });
  const el = h("section", { class: "page-view" },
    h("div", { class: "page-inner" }, band,
      h("div", { class: "d-columns" },
        h("div", { class: "d-main" }, h("div", { class: "d-history-head" }, h("p", { class: "group-label" }, "Historie"), q), list),
        side)));

  function header(s: any) {
    settings = s;
    const name = s?.general?.address_as || s?.general?.user_name;
    title.textContent = name ? `Ahoj, ${name}` : "Ahoj";
    sub.textContent = s?.dictation?.enabled === false
      ? "Diktování je vypnuté. Zapneš ho v nastavení diktování."
      : `Drž ${dictKey(s)} kdekoli, mluv a pusť: text se vloží tam, kde píšeš. Dvojité ťuknutí = bez držení.`;
  }

  function render(m: any) {
    const st = m.stats || {};
    side.replaceChildren(
      h("div", { class: "card d-numbers" },
        h("div", { class: "d-num" }, h("b", {}, n(st.total_words ?? 0)), h("span", {}, "slov nadiktováno")),
        h("div", { class: "d-num" }, h("b", {}, n(st.wpm ?? 0)), h("span", {}, "slov za minutu")),
        h("div", { class: "d-num" }, h("b", {}, n(st.streak ?? 0)), h("span", {}, plural(st.streak ?? 0, "den v řadě", "dny v řadě", "dní v řadě"))),
        h("div", { class: "d-free" }, icon("check", "ph-bold"), "Zdarma, offline, bez limitu")),
      h("div", { class: "card d-promo" },
        h("strong", {}, "Nahrávání hovorů"),
        h("p", {}, "Hovor přepsaný po lidech, se shrnutím a úkoly. Žádný bot v hovoru."),
        h("button", { class: "link-btn", type: "button", onclick: () => go("notetaker") }, "Otevřít nahrávání →")));
    const items: any[] = m.history || [];
    if (!items.length) {
      list.replaceChildren(h("div", { class: "card d-empty" }, icon("microphone"),
        h("p", {}, q.value ? "Nic nenalezeno." : `Zatím žádné diktáty. Zkus to: podrž ${dictKey(settings)} v jakémkoli okně, řekni pár slov a pusť.`)));
      return;
    }
    const groups = new Map<string, any[]>();
    for (const it of items) {
      const k = dayLabel(it.ts);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k)!.push(it);
    }
    list.replaceChildren(...[...groups].flatMap(([day, rows]) => [
      h("p", { class: "d-day" }, day),
      h("div", { class: "d-entries" }, ...rows.map((it) => h("div", { class: "d-entry" },
        h("div", { class: "d-when" }, h("span", {}, fmtTime(it.ts).split(" ").pop()!), it.app ? h("span", { class: "tag" }, it.app) : null),
        h("div", { class: "d-words" }, it.text),
        h("div", { class: "d-tools" },
          h("button", { class: "icon-btn sm", type: "button", title: "Kopírovat", onclick: () => { navigator.clipboard?.writeText(it.text); toast("Zkopírováno", "ok"); } }, icon("copy")),
          h("button", { class: "icon-btn sm", type: "button", title: "Smazat", onclick: () => client.send("dictation_delete", { id: it.id }) }, icon("trash"))))))]));
  }

  client.on("welcome", (m) => header(m.settings));
  client.on("settings_changed", (m) => header(m.settings));
  client.on("dictation_data", (m) => { if (!el.hidden) render(m); });
  client.on("dictation", (m) => { if (m.state === "done" && !el.hidden) client.send("dictation_get", { q: q.value, period: "month" }); });
  return { el, show: () => client.send("dictation_get", { q: q.value, period: "month" }) };
}

/** The Statistiky page: what you dictated, how fast, where, and what JARVIS did for you. */
export function buildStats(client: JarvisClient) {
  let period = "month";
  const seg = h("span", { class: "segmented" });
  const setPeriod = (p: string) => { period = p; client.send("dictation_get", { period, limit: 1 }); paintSeg(); };
  const paintSeg = () => seg.replaceChildren(...([["week", "Týden"], ["month", "Měsíc"], ["all", "Vše"]] as const)
    .map(([v, l]) => h("button", { type: "button", class: v === period ? "on" : "", onclick: () => setPeriod(v) }, l)));
  paintSeg();
  const tiles = h("div", { class: "s-tiles" });
  const chart = h("div", { class: "card s-chart" });
  const apps = h("div", { class: "card s-apps" });
  const recapBox = h("div", {});
  const el = h("section", { class: "page-view" },
    h("div", { class: "page-inner" },
      hero(HEROES.stats, "Statistiky", "Co jsi nadiktoval, jak rychle a kde. A co za tebe JARVIS udělal.", [seg]),
      tiles, h("div", { class: "s-row" }, chart, apps), recapBox,
      h("p", { class: "help" }, "Počítá se jen u tebe na PC, nikam se neposílá.")));

  const tile = (label: string, value: string, note = "") =>
    h("div", { class: "card s-tile" }, h("span", {}, label), h("b", {}, value), note ? h("small", {}, note) : null);

  client.on("dictation_data", (m) => {
    if (el.hidden) return;
    const s = m.stats || {};
    tiles.replaceChildren(
      tile("Nadiktovaná slova", n(s.words ?? 0)),
      tile("Ušetřený čas", dur(s.saved_s ?? 0), "oproti psaní 40 slov/min"),
      tile("Rychlost", n(s.wpm ?? 0), "slov za minutu"),
      tile("Diktování", n(s.dictations ?? 0)));
    const series: any[] = s.series || [];
    const max = Math.max(1, ...series.map((x) => x.words));
    const step = Math.max(1, Math.ceil(series.length / 8));
    chart.replaceChildren(h("h2", {}, "Slova za den"),
      h("div", { class: "bars" }, ...series.map((x, i) => h("div", { class: "bar-col", title: `${x.day}: ${x.words} slov` },
        h("i", { style: { height: `${x.words ? Math.max(4, (x.words / max) * 100) : 0}%` }, class: x.words ? "" : "zero" }),
        h("span", {}, i % step === 0 || i === series.length - 1 ? String(new Date(x.day).getDate()) : "")))));
    const a: any[] = s.apps || [];
    apps.replaceChildren(h("h2", {}, "Kde diktuješ"),
      ...(a.length ? a.map((x) => h("div", { class: "app-row" }, h("div", { class: "app-line" }, h("span", {}, x.app), h("span", {}, `${x.share} %`)),
        h("div", { class: "meter" }, h("i", { style: { width: `${x.share}%` } }))))
        : [h("p", { class: "help" }, "Zatím nic.")]));
  });
  client.on("recap", (m) => { if (!el.hidden) recapBox.replaceChildren(recapCard(m.data)); });
  return { el, show: () => { client.send("dictation_get", { period, limit: 1 }); client.send("recap_get"); } };
}

/** "Tvůj týden s JARVISem": last Monday–Sunday in numbers. */
export function recapCard(r: any, onClose?: () => void): HTMLElement {
  const from = new Date(r.week).toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" });
  const to = new Date(r.until).toLocaleDateString("cs-CZ", { day: "numeric", month: "numeric" });
  const max = Math.max(1, ...(r.per_day || [0]));
  const fact = (v: string, l: string) => h("div", { class: "rc-fact" }, h("b", {}, v), h("span", {}, l));
  return h("div", { class: "card recap" },
    h("div", { class: "rc-head" }, h("div", {}, h("p", { class: "group-label" }, `Minulý týden · ${from} – ${to}`), h("h2", {}, "Tvůj týden s JARVISem")),
      onClose ? h("button", { class: "icon-btn", type: "button", "aria-label": "Zavřít", onclick: onClose }, icon("x")) : null),
    r.empty ? h("p", { class: "help" }, "Minulý týden byl klid. Tenhle týden to rozjedeme.") : h("div", { class: "rc-facts" },
      fact(n(r.messages), "zpráv JARVISovi"), fact(n(r.tasks_done), `${plural(r.tasks_done, "úkol hotový", "úkoly hotové", "úkolů hotových")}`),
      fact(n(r.actions), "akcí na PC"), fact(n(r.words), "nadiktovaných slov"),
      fact(dur(r.saved_s), "ušetřeno diktováním"), fact(r.busiest_day ? r.busiest_day[0].toUpperCase() + r.busiest_day.slice(1) : "–", "nejrušnější den")),
    r.empty ? null : h("div", { class: "rc-week" }, ...["Po", "Út", "St", "Čt", "Pá", "So", "Ne"].map((d, i) =>
      h("div", { class: "rc-day" }, h("i", { style: { height: `${((r.per_day?.[i] || 0) / max) * 100}%` } }), h("span", {}, d)))));
}

/** Monday: show the recap once over the window. */
export function recapOverlay(client: JarvisClient) {
  let shown = false;
  client.on("welcome", (m) => { if (m.recap_due && !shown) client.send("recap_get"); });
  client.on("recap", (m) => {
    if (!m.due || shown) return;
    shown = true;
    const close = () => { root.remove(); window.removeEventListener("keydown", onKey); client.send("recap_seen"); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    const root = h("div", { class: "palette show recap-overlay", onclick: (e: MouseEvent) => { if (e.target === root) close(); } },
      h("div", { class: "recap-box" }, recapCard(m.data, close)));
    document.body.append(root);
  });
}
