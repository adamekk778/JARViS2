// Dashboard → Stark (3.2): protocols you can run by voice ("spusť protokol Párty"), from the HUD or the phone,
// plus the switches for the morning briefing, the guardian and the "JARVIS online" greeting.
import { hero, HEROES } from "../shared/hero";
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";

interface Step { say?: string; tool?: string; args?: Record<string, any>; ask?: string; when?: string }
interface Protocol { id: string; name: string; icon: string; steps: Step[] }

/** What a non-programmer can pick as an action. `param` = one value the user types. */
const ACTIONS: { key: string; label: string; param?: { label: string; type: "number" | "text"; def: string }; make: (v: string) => Step;
  match: (s: Step) => string | null }[] = [
  { key: "volume", label: "Hlasitost na…", param: { label: "%", type: "number", def: "30" },
    make: (v) => ({ tool: "volume", args: { action: "set", level: Math.max(0, Math.min(100, +v || 0)) } }),
    match: (s) => (s.tool === "volume" && s.args?.action === "set" ? String(s.args.level) : null) },
  { key: "mute", label: "Ztlumit zvuk", make: () => ({ tool: "volume", args: { action: "mute" } }),
    match: (s) => (s.tool === "volume" && s.args?.action === "mute" ? "" : null) },
  { key: "pause", label: "Pozastavit hudbu (když hraje)", make: () => ({ tool: "media_control", args: { action: "play_pause" }, when: "playing" }),
    match: (s) => (s.tool === "media_control" && s.when === "playing" ? "" : null) },
  { key: "next", label: "Další skladba", make: () => ({ tool: "media_control", args: { action: "next" } }),
    match: (s) => (s.tool === "media_control" && s.args?.action === "next" ? "" : null) },
  { key: "yt", label: "Pustit na YouTube…", param: { label: "co pustit", type: "text", def: "lo-fi hudba" },
    make: (v) => ({ tool: "youtube_play", args: { query: v } }), match: (s) => (s.tool === "youtube_play" ? s.args?.query ?? "" : null) },
  { key: "app", label: "Otevřít aplikaci…", param: { label: "název", type: "text", def: "Spotify" },
    make: (v) => ({ tool: "open_app", args: { name: v } }), match: (s) => (s.tool === "open_app" ? s.args?.name ?? "" : null) },
  { key: "url", label: "Otevřít web…", param: { label: "adresa", type: "text", def: "https://" },
    make: (v) => ({ tool: "open_url", args: { url: v } }), match: (s) => (s.tool === "open_url" ? s.args?.url ?? "" : null) },
  { key: "dark", label: "Tmavý režim Windows", make: () => ({ tool: "set_dark_mode", args: { dark: true } }),
    match: (s) => (s.tool === "set_dark_mode" && s.args?.dark ? "" : null) },
  { key: "light", label: "Světlý režim Windows", make: () => ({ tool: "set_dark_mode", args: { dark: false } }),
    match: (s) => (s.tool === "set_dark_mode" && !s.args?.dark ? "" : null) },
  { key: "timer", label: "Časovač na… minut", param: { label: "min", type: "number", def: "25" },
    make: (v) => ({ tool: "set_timer", args: { seconds: Math.max(1, Math.round(+v || 1)) * 60, label: `${Math.round(+v || 1)} min` } }),
    match: (s) => (s.tool === "set_timer" ? String(Math.round((s.args?.seconds || 60) / 60)) : null) },
  { key: "brief", label: "Ranní brífink", make: () => ({ tool: "briefing" }), match: (s) => (s.tool === "briefing" ? "" : null) },
  { key: "hud", label: "Otevřít Stark HUD", make: () => ({ tool: "show_hud" }), match: (s) => (s.tool === "show_hud" ? "" : null) },
  { key: "lock", label: "Zamknout počítač", make: () => ({ tool: "system_power", args: { action: "lock" } }),
    match: (s) => (s.tool === "system_power" && s.args?.action === "lock" ? "" : null) },
  { key: "sleep", label: "Uspat počítač (zeptá se)", make: () => ({ tool: "system_power", args: { action: "sleep" } }),
    match: (s) => (s.tool === "system_power" && s.args?.action === "sleep" ? "" : null) },
];
const ICONS = ["lightning", "sun-horizon", "moon-stars", "briefcase", "game-controller", "confetti", "film-strip", "music-notes",
  "coffee", "barbell", "book-open", "rocket-launch", "shield-check", "house", "car", "heart"];

const actionOf = (s: Step) => {
  for (const a of ACTIONS) { const v = a.match(s); if (v !== null) return { a, v }; }
  return null;
};
export const stepText = (s: Step) => {
  if (s.say) return `Řekne: „${s.say}“`;
  if (s.ask) return `AI: ${s.ask}`;
  const x = actionOf(s);
  return x ? `${x.a.label.replace("…", "")}${x.v ? " " + x.v : ""}`.replace(" na  ", " na ") : s.tool || "?";
};

export function buildStark(client: JarvisClient) {
  let protocols: Protocol[] = [];
  let settings: any = {};
  let editing: Protocol | null = null;
  const save = (list: Protocol[]) => client.send("settings_set", { patch: { stark: { protocols: list } } });

  const grid = h("div", { class: "proto-grid" });
  const editor = h("div", { class: "proto-editor card", hidden: true });
  const switches = h("div", { class: "group" });

  function render() {
    grid.replaceChildren(...protocols.map((p) => h("div", { class: "proto-card card" },
      h("div", { class: "pc-head" }, h("span", { class: "pc-ico" }, icon(p.icon || "lightning")), h("strong", {}, p.name),
        h("span", { class: "muted" }, `„spusť protokol ${p.name.toLowerCase()}“`)),
      h("ol", { class: "pc-steps" }, ...p.steps.slice(0, 5).map((s) => h("li", {}, stepText(s))),
        p.steps.length > 5 ? h("li", { class: "muted" }, `…a ${p.steps.length - 5} další`) : null),
      h("div", { class: "btn-row" },
        h("button", { class: "btn primary", type: "button", onclick: () => { client.send("protocol_run", { id: p.id }); toast(`Spouštím protokol ${p.name}`, "ok"); } }, icon("play", "ph-fill"), "Spustit"),
        h("button", { class: "btn", type: "button", onclick: () => edit(p) }, icon("pencil-simple"), "Upravit"),
        h("button", { class: "btn ghost", type: "button", "aria-label": `Smazat protokol ${p.name}`, onclick: () => {
          if (confirm(`Smazat protokol ${p.name}?`)) save(protocols.filter((x) => x.id !== p.id));
        } }, icon("trash"))))),
      h("button", { class: "proto-card card proto-new", type: "button", onclick: () => edit(null) }, icon("plus-circle"), h("strong", {}, "Nový protokol"),
        h("span", { class: "muted" }, "Třeba „Kino“: ztlumit, tmavý režim, pustit film.")));
  }

  function edit(p: Protocol | null) {
    editing = p ? JSON.parse(JSON.stringify(p)) : { id: "", name: "", icon: "lightning", steps: [{ say: "" }] };
    const draft = editing!;
    const name = h("input", { class: "input", value: draft.name, placeholder: "Název, např. Kino", "aria-label": "Název protokolu" }) as HTMLInputElement;
    const icons = h("div", { class: "pe-icons", role: "radiogroup", "aria-label": "Ikona" },
      ...ICONS.map((ic) => h("button", { type: "button", class: `pe-ic ${draft.icon === ic ? "on" : ""}`, "aria-label": ic,
        onclick: (e: Event) => { draft.icon = ic; icons.querySelectorAll(".pe-ic").forEach((b) => b.classList.toggle("on", b === e.currentTarget)); } }, icon(ic))));
    const steps = h("ol", { class: "pe-steps" });
    const renderSteps = () => steps.replaceChildren(...draft.steps.map((s, i) => stepRow(s, i)));
    const stepRow = (s: Step, i: number) => {
      const kind = s.say !== undefined && !s.tool && !s.ask ? "say" : s.ask !== undefined && !s.tool ? "ask" : "do";
      const type = h("select", { class: "input", "aria-label": "Druh kroku" },
        h("option", { value: "say" }, "JARVIS řekne"), h("option", { value: "do" }, "Akce"), h("option", { value: "ask" }, "Úkol pro AI")) as HTMLSelectElement;
      type.value = kind;
      type.onchange = () => { draft.steps[i] = type.value === "say" ? { say: "" } : type.value === "ask" ? { ask: "" } : ACTIONS[0].make(ACTIONS[0].param!.def); renderSteps(); };
      let body: HTMLElement;
      if (kind === "say" || kind === "ask") {
        const t = h("input", { class: "input", value: (kind === "say" ? s.say : s.ask) || "",
          placeholder: kind === "say" ? "Co JARVIS řekne" : "Co má AI udělat, např. najdi film na dnešní večer", "aria-label": "Text kroku" }) as HTMLInputElement;
        t.oninput = () => { draft.steps[i] = kind === "say" ? { say: t.value } : { ask: t.value }; };
        body = t;
      } else {
        const cur = actionOf(s);
        const sel = h("select", { class: "input", "aria-label": "Akce" }, ...ACTIONS.map((a) => h("option", { value: a.key }, a.label))) as HTMLSelectElement;
        sel.value = cur?.a.key || ACTIONS[0].key;
        const a = ACTIONS.find((x) => x.key === sel.value)!;
        const param = a.param ? h("input", { class: "input pe-param", type: a.param.type, value: cur?.v || a.param.def, placeholder: a.param.label, "aria-label": a.param.label }) as HTMLInputElement : null;
        sel.onchange = () => { const na = ACTIONS.find((x) => x.key === sel.value)!; draft.steps[i] = na.make(na.param?.def || ""); renderSteps(); };
        if (param) param.oninput = () => { draft.steps[i] = a.make(param.value); };
        body = h("div", { class: "pe-do" }, sel, param);
      }
      const move = (d: number) => { const j = i + d; if (j < 0 || j >= draft.steps.length) return; [draft.steps[i], draft.steps[j]] = [draft.steps[j], draft.steps[i]]; renderSteps(); };
      return h("li", { class: "pe-step" }, type, body,
        h("button", { class: "icon-btn sm", type: "button", title: "Nahoru", "aria-label": "Krok nahoru", onclick: () => move(-1) }, icon("arrow-up")),
        h("button", { class: "icon-btn sm", type: "button", title: "Dolů", "aria-label": "Krok dolů", onclick: () => move(1) }, icon("arrow-down")),
        h("button", { class: "icon-btn sm", type: "button", title: "Odebrat", "aria-label": "Odebrat krok", onclick: () => { draft.steps.splice(i, 1); renderSteps(); } }, icon("x")));
    };
    renderSteps();
    const done = () => { editor.hidden = true; editing = null; };
    editor.hidden = false;
    editor.replaceChildren(
      h("h3", {}, p ? `Upravit protokol ${p.name}` : "Nový protokol"),
      h("label", { class: "pe-row" }, h("span", {}, "Název"), name),
      h("div", { class: "pe-row" }, h("span", {}, "Ikona"), icons),
      h("div", { class: "pe-row top" }, h("span", {}, "Kroky"), h("div", {}, steps,
        h("button", { class: "btn ghost", type: "button", onclick: () => { draft.steps.push({ say: "" }); renderSteps(); } }, icon("plus"), "Přidat krok"))),
      h("p", { class: "help" }, "Akce, které něco mění (vypnutí, mazání…), se i v protokolu vždycky nejdřív zeptají."),
      h("div", { class: "btn-row" },
        h("button", { class: "btn ghost", type: "button", onclick: done }, "Zrušit"),
        h("button", { class: "btn primary", type: "button", onclick: () => {
          const nm = name.value.trim();
          if (!nm) { toast("Dej protokolu název", "error"); return; }
          const clean = draft.steps.filter((s) => (s.say ?? "").trim() || (s.ask ?? "").trim() || s.tool);
          if (!clean.length) { toast("Přidej aspoň jeden krok", "error"); return; }
          const id = draft.id || nm.toLowerCase().normalize("NFKD").replace(/[^\w]+/g, "-").replace(/^-|-$/g, "") || `p${Date.now()}`;
          const next = { ...draft, id, name: nm, steps: clean };
          save(draft.id ? protocols.map((x) => (x.id === draft.id ? next : x)) : [...protocols.filter((x) => x.id !== id), next]);
          toast(`Protokol ${nm} uložen. Řekni „spusť protokol ${nm.toLowerCase()}“.`, "ok", 4000);
          done();
        } }, icon("check"), "Uložit")));
    editor.scrollIntoView({ behavior: "smooth", block: "start" });
    name.focus();
  }

  function renderSwitches() {
    const s = settings?.stark || {};
    const sw = (key: string, title: string, desc: string) => {
      const inp = h("input", { type: "checkbox", role: "switch", "aria-label": title }) as HTMLInputElement;
      inp.checked = !!s[key];
      inp.onchange = () => client.send("settings_set", { patch: { stark: { [key]: inp.checked } } });
      return h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, title), h("span", { class: "help" }, desc)),
        h("span", { class: "switch" }, inp, h("span")));
    };
    const num = (key: string, title: string, desc: string, min: number, max: number) => {
      const inp = h("input", { class: "input sm", type: "number", min, max, value: s[key] ?? "", "aria-label": title }) as HTMLInputElement;
      inp.onchange = () => client.send("settings_set", { patch: { stark: { [key]: Math.max(min, Math.min(max, +inp.value || min)) } } });
      return h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, title), h("span", { class: "help" }, desc)), inp);
    };
    switches.replaceChildren(
      sw("boot_greeting", "„JARVIS online“ po spuštění", "Krátký pozdrav, když se JARVIS na PC spustí."),
      sw("briefing_auto", "Ranní brífink", "Když ráno poprvé sedneš k PC: počasí, plány, stav PC a zprávy."),
      sw("briefing_speak", "Přečíst brífink nahlas", "Jinak jen jako karta v notchi a v HUD."),
      sw("briefing_news", "Zprávy v brífinku", "Tři hlavní titulky (Google Zprávy)."),
      sw("guardian", "Strážce", "Sám upozorní na slabou baterii, přetížený procesor, plnou paměť nebo disk a výpadek internetu."),
      sw("guardian_speak", "Strážce mluví", "Upozornění řekne nahlas (jinak jen v notchi)."),
      num("battery_low", "Upozornit na baterii pod", "Procenta (pak ještě 10 % a 5 %).", 5, 80),
      num("disk_low_gb", "Upozornit na disk pod", "Gigabajty volného místa na disku C.", 1, 200));
  }

  const sync = (s: any) => {
    settings = s;
    protocols = (s?.stark?.protocols || []) as Protocol[];
    render();
    renderSwitches();
  };
  client.on("welcome", (m) => sync(m.settings));
  client.on("settings_changed", (m) => sync(m.settings));

  const openHud = () => (client.local ? client.send("open_window", { view: "hud" }) : toast("HUD jde otevřít jen na PC", "error"));
  const el = h("section", { class: "tasks-view stark-view" },
    hero(HEROES.stark, "Stark", "Protokoly, holografický HUD, ranní brífink a strážce – jako JARVIS z filmu.", [
      h("button", { class: "btn primary", type: "button", onclick: openHud }, icon("circle-notch"), "Otevřít HUD"),
      h("button", { class: "btn", type: "button", onclick: () => client.send("user_text", { text: "Brífink", attachments: [] }) }, icon("sun-horizon"), "Brífink teď")]),
    h("p", { class: "help" }, "HUD otevřeš i zkratkou Ctrl+Alt+H nebo hlasem „ukaž HUD“. Protokol spustíš hlasem „spusť protokol …“."),
    h("h2", { class: "group-label" }, "Protokoly"),
    grid, editor,
    h("h2", { class: "group-label" }, "Chování"),
    switches);
  return { el };
}
