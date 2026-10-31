// Dashboard → Automatizace (3.5): "Když … tak …" rules that run by themselves – a time, an app opening, an e-mail
// from someone, a message on the phone, the battery or charger, leaving / coming back to the PC.
import { hero, HEROES } from "../shared/hero";
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import { stepsEditor, stepText, type Step } from "./stark";
import { missionGraph } from "../shared/viz";

interface Trigger { type: string; value: string; text: string; days: number[] }
interface Automation { id: string; name: string; enabled: boolean; trigger: Trigger; steps: Step[] }

/** Each trigger: label, what `value` means (none = no field), whether `text` matters, an example. */
const TRIGGERS: Record<string, { label: string; ico: string; value?: { label: string; ph: string; type?: string }; text?: string; hint: string }> = {
  time: { label: "V určitý čas", ico: "clock", value: { label: "Čas", ph: "07:30", type: "time" }, hint: "Třeba každý všední den v 7:30 brífink." },
  boot: { label: "Když zapnu PC", ico: "power", hint: "Když se JARVIS spustí." },
  app_open: { label: "Když otevřu aplikaci", ico: "app-window", value: { label: "Aplikace", ph: "Spotify" }, hint: "Třeba Spotify → hlasitost na 30 %." },
  app_close: { label: "Když zavřu aplikaci", ico: "x-square", value: { label: "Aplikace", ph: "Steam" }, hint: "Třeba po hraní → světlý režim." },
  mail: { label: "Když přijde e-mail", ico: "envelope-simple", value: { label: "Od koho (prázdné = kdokoli)", ph: "šéf@firma.cz" },
    text: "Předmět obsahuje", hint: "{sender} = odesílatel, {subject} = předmět." },
  phone_message: { label: "Když mi přijde zpráva na mobil", ico: "chat-circle-dots", value: { label: "Kdo píše (prázdné = kdokoli)", ph: "Máma" },
    text: "Zpráva obsahuje", hint: "WhatsApp, SMS, Messenger… {sender} = kdo, {text} = zpráva." },
  phone_call: { label: "Když mi někdo volá", ico: "phone-incoming", value: { label: "Kdo volá (prázdné = kdokoli)", ph: "Petr" }, hint: "{sender} = kdo volá." },
  battery: { label: "Když je slabá baterie", ico: "battery-low", value: { label: "Pod kolik %", ph: "20", type: "number" }, hint: "{percent} = stav baterie." },
  power: { label: "Nabíječka", ico: "plug", hint: "Připojení nebo odpojení nabíječky." },
  away: { label: "Když odejdu od PC", ico: "person-simple-walk", value: { label: "Po kolika minutách", ph: "10", type: "number" }, hint: "Třeba pozastavit hudbu a zamknout." },
  home_state: { label: "Když čidlo v domácnosti…", ico: "thermometer", value: { label: "Čidlo / zařízení (název z Home Assistantu)", ph: "Teplota obývák" }, text: "Stav nebo hodnota: on, off, open… nebo > 25, < 10 (prázdné = při každé změně)", hint: "JARVIS se dívá do Home Assistantu každých 30 s a spustí to, když podmínka začne platit." },
  webhook: { label: "Když přijde webhook", ico: "webhooks-logo", value: { label: "Název webhooku (prázdné = jakýkoli)", ph: "E-shop" },
    text: "Obsah obsahuje", hint: "Webhook vytvoříš větou „vytvoř webhook E-shop“. {text} = obsah (jen data)." },
  back: { label: "Když se vrátím k PC", ico: "hand-waving", value: { label: "Po aspoň kolika minutách pryč", ph: "30", type: "number" }, hint: "Třeba „Vítejte zpět“ a co jsem zmeškal." },
};
const DAYS = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"];

export function whenText(t: Trigger): string {
  const v = (t.value || "").trim(), x = (t.text || "").trim();
  switch (t.type) {
    case "time": {
      const d = t.days?.length ? [...t.days].sort() : [0, 1, 2, 3, 4, 5, 6];
      const which = d.length === 7 ? "Každý den" : d.join() === "0,1,2,3,4" ? "Ve všední dny" : d.join() === "5,6" ? "O víkendu" : d.map((i) => DAYS[i]).join(", ");
      return `${which} v ${v || "?"}`;
    }
    case "app_open": return `Když otevřu ${v || "aplikaci"}`;
    case "app_close": return `Když zavřu ${v || "aplikaci"}`;
    case "mail": return `Když přijde e-mail${v ? ` od „${v}“` : ""}${x ? ` s „${x}“` : ""}`;
    case "phone_message": return `Když mi${v ? ` „${v}“` : ""} napíše na mobil${x ? ` „${x}“` : ""}`;
    case "phone_call": return `Když mi volá ${v ? `„${v}“` : "kdokoli"}`;
    case "battery": return `Když baterie klesne pod ${v || 20} %`;
    case "power": return v === "out" ? "Když odpojím nabíječku" : "Když připojím nabíječku";
    case "away": return `Když odejdu od PC na ${v || 10} min`;
    case "back": return `Když se vrátím k PC (po ${v || 10}+ min)`;
    case "webhook": return `Když přijde webhook${v ? ` „${v}“` : ""}${x ? ` s „${x}“` : ""}`;
    default: return TRIGGERS[t.type]?.label || t.type;
  }
}

export function buildAutomations(client: JarvisClient) {
  let items: Automation[] = [];
  let enabledAll = true;
  const save = (list: Automation[]) => client.send("settings_set", { patch: { automations: { items: list } } });

  const master = h("input", { type: "checkbox", role: "switch", "aria-label": "Automatizace zapnuté" }) as HTMLInputElement;
  master.onchange = () => client.send("settings_set", { patch: { automations: { enabled: master.checked } } });
  const grid = h("div", { class: "proto-grid" });
  const editor = h("div", { class: "proto-editor card", hidden: true });
  const logBox = h("ul", { class: "auto-log" });

  function render() {
    master.checked = enabledAll;
    grid.replaceChildren(...items.map((a) => {
      const sw = h("input", { type: "checkbox", role: "switch", "aria-label": `Zapnout ${a.name}` }) as HTMLInputElement;
      sw.checked = a.enabled;
      sw.onchange = () => save(items.map((x) => (x.id === a.id ? { ...x, enabled: sw.checked } : x)));
      return h("div", { class: `proto-card card auto-card ${a.enabled ? "" : "off"}` },
        h("div", { class: "pc-head" }, h("span", { class: "pc-ico" }, icon(TRIGGERS[a.trigger.type]?.ico || "lightning")), h("strong", {}, a.name),
          h("label", { class: "switch sm" }, sw, h("span"))),
        h("p", { class: "auto-when" }, icon("arrow-bend-down-right"), whenText(a.trigger)),
        h("ol", { class: "pc-steps" }, ...a.steps.slice(0, 4).map((s) => h("li", {}, stepText(s))),
          a.steps.length > 4 ? h("li", { class: "muted" }, `…a ${a.steps.length - 4} další`) : null),
        h("div", { class: "btn-row" },
          h("button", { class: "btn", type: "button", onclick: () => { client.send("automation_run", { id: a.id }); toast(`Zkouším ${a.name}`, "ok"); } }, icon("play", "ph-fill"), "Vyzkoušet"),
          h("button", { class: "btn", type: "button", title: "Ukáže, co by se stalo – nic neprovede", onclick: () => client.send("mission_simulate", { id: a.id, kind: "automation" }) }, icon("eye"), "Nanečisto"),
          h("button", { class: "btn", type: "button", onclick: () => edit(a) }, icon("pencil-simple"), "Upravit"),
          h("button", { class: "btn ghost", type: "button", title: "Verze a návrat zpět", "aria-label": `Verze automatizace ${a.name}`, onclick: () => client.send("skill_versions_get", { id: `auto:${a.id}` }) }, icon("clock-counter-clockwise")),
          h("button", { class: "btn ghost", type: "button", "aria-label": `Smazat automatizaci ${a.name}`, onclick: () => {
            if (confirm(`Smazat automatizaci ${a.name}?`)) save(items.filter((x) => x.id !== a.id));
          } }, icon("trash"))));
    }),
    h("button", { class: "proto-card card proto-new", type: "button", onclick: () => edit(null) }, icon("plus-circle"), h("strong", {}, "Nová automatizace"),
      h("span", { class: "muted" }, "Třeba: když otevřu Steam → herní protokol.")));
  }

  // OMEGA 149: dry run – the steps with test data, what would ask first and how long it takes; nothing is executed
  client.on("mission_sim", (m) => {
    if (m.kind !== "automation") return;
    const g = missionGraph(m.steps || [], m.graph, m.seconds || 0);
    editor.hidden = false;
    editor.replaceChildren(h("h3", {}, `Nanečisto: ${m.name}`),
      h("p", { class: "help" }, "Se zkušebními údaji (odesílatel „Test“, předmět „Zkouška“…). Nic se neprovedlo – „Vyzkoušet“ to spustí doopravdy."), g.el,
      h("div", { class: "btn-row" }, h("button", { class: "btn primary", type: "button", onclick: g.play }, icon("play", "ph-fill"), "Přehrát"),
        h("button", { class: "btn ghost", type: "button", onclick: () => { editor.hidden = true; } }, "Zavřít")));
    editor.scrollIntoView({ behavior: "smooth", block: "start" });
    window.setTimeout(g.play, 300);
  });
  // OMEGA 150: every saved change is a version; any one can be restored
  client.on("skill_versions", (m) => {
    if (!String(m.id).startsWith("auto:")) return;
    const id = String(m.id).slice(5), a = items.find((x) => x.id === id);
    const vs: any[] = m.items || [];
    editor.hidden = false;
    editor.replaceChildren(h("h3", {}, `Verze: ${a?.name || id}`),
      vs.length ? h("ol", { class: "pe-steps", reversed: true }, ...vs.map((v, i) => h("li", { class: "pe-version" },
        h("strong", {}, `v${v.version}`), h("span", { class: "muted" }, `${new Date(v.ts * 1000).toLocaleString("cs-CZ")} · ${v.note || ""}`),
        h("span", { class: "muted" }, `${whenText(v.protocol.trigger)} → ${(v.protocol.steps || []).map(stepText).join(" → ")}`),
        i === 0 ? h("span", { class: "muted" }, "aktuální") : h("button", { class: "btn", type: "button", onclick: () => {
          if (confirm(`Vrátit ${a?.name || id} na verzi ${v.version}?`)) client.send("skill_rollback", { id: m.id, version: v.version });
        } }, icon("arrow-counter-clockwise"), "Vrátit"))))
        : h("p", { class: "muted" }, "Zatím žádná uložená verze – vznikne při první úpravě."),
      h("div", { class: "btn-row" }, h("button", { class: "btn ghost", type: "button", onclick: () => { editor.hidden = true; } }, "Zavřít")));
    editor.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  function edit(a: Automation | null) {
    const draft: Automation = a ? JSON.parse(JSON.stringify(a)) : { id: "", name: "", enabled: true, trigger: { type: "app_open", value: "", text: "", days: [] }, steps: [{ say: "" }] };
    const name = h("input", { class: "input", value: draft.name, placeholder: "Název, např. Spotify potichu", "aria-label": "Název automatizace" }) as HTMLInputElement;
    const kind = h("select", { class: "input", "aria-label": "Kdy" }, ...Object.entries(TRIGGERS).map(([k, t]) => h("option", { value: k }, t.label))) as HTMLSelectElement;
    kind.value = draft.trigger.type;
    const whenBox = h("div", { class: "auto-when-edit" });
    const renderWhen = () => {
      const t = TRIGGERS[draft.trigger.type];
      const parts: HTMLElement[] = [h("p", { class: "help" }, t.hint)];
      if (t.value) {
        const v = h("input", { class: "input", type: t.value.type || "text", value: draft.trigger.value, placeholder: t.value.ph, "aria-label": t.value.label }) as HTMLInputElement;
        v.oninput = () => { draft.trigger.value = v.value; };
        parts.push(h("label", { class: "pe-row" }, h("span", {}, t.value.label), v));
      }
      if (draft.trigger.type === "power") {
        const sel = h("select", { class: "input", "aria-label": "Nabíječka" }, h("option", { value: "in" }, "Připojím"), h("option", { value: "out" }, "Odpojím")) as HTMLSelectElement;
        sel.value = draft.trigger.value === "out" ? "out" : "in";
        draft.trigger.value = sel.value;
        sel.onchange = () => { draft.trigger.value = sel.value; };
        parts.push(h("label", { class: "pe-row" }, h("span", {}, "Nabíječku"), sel));
      }
      if (t.text) {
        const x = h("input", { class: "input", value: draft.trigger.text, placeholder: "(nemusí)", "aria-label": t.text }) as HTMLInputElement;
        x.oninput = () => { draft.trigger.text = x.value; };
        parts.push(h("label", { class: "pe-row" }, h("span", {}, t.text), x));
      }
      if (draft.trigger.type === "time") {
        const days = h("div", { class: "auto-days", role: "group", "aria-label": "Dny" }, ...DAYS.map((d, i) => {
          const b = h("button", { type: "button", class: `chip ${!draft.trigger.days.length || draft.trigger.days.includes(i) ? "on" : ""}`, "aria-pressed": "false" }, d);
          b.onclick = () => {
            const cur = draft.trigger.days.length ? draft.trigger.days : [0, 1, 2, 3, 4, 5, 6];
            const next = cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i].sort();
            draft.trigger.days = next.length === 7 ? [] : next;
            renderWhen();
          };
          return b;
        }));
        parts.push(h("div", { class: "pe-row" }, h("span", {}, "Dny"), days));
      }
      whenBox.replaceChildren(...parts);
    };
    kind.onchange = () => { draft.trigger = { type: kind.value, value: "", text: "", days: [] }; renderWhen(); };
    renderWhen();
    const steps = stepsEditor(draft.steps, "Co JARVIS řekne, např. Píše vám {sender}");
    const done = () => { editor.hidden = true; };
    editor.hidden = false;
    editor.replaceChildren(
      h("h3", {}, a ? `Upravit automatizaci ${a.name}` : "Nová automatizace"),
      h("label", { class: "pe-row" }, h("span", {}, "Název"), name),
      h("label", { class: "pe-row" }, h("span", {}, "Když"), kind),
      whenBox,
      h("div", { class: "pe-row top" }, h("span", {}, "Tak"), h("div", {}, steps,
        h("button", { class: "btn ghost", type: "button", onclick: () => { draft.steps.push({ say: "" }); (steps as any).rerender(); } }, icon("plus"), "Přidat krok"))),
      h("p", { class: "help" }, "V textu můžeš použít {sender}, {subject}, {text}, {app}, {percent}, {minutes}. Akce, které něco mění, se vždycky nejdřív zeptají."),
      h("div", { class: "btn-row" },
        h("button", { class: "btn ghost", type: "button", onclick: done }, "Zrušit"),
        h("button", { class: "btn primary", type: "button", onclick: () => {
          const nm = name.value.trim();
          if (!nm) { toast("Dej automatizaci název", "error"); return; }
          const t = draft.trigger;
          if (t.type === "time" && !/^\d{1,2}:\d\d$/.test(t.value.trim())) { toast("Zadej čas, např. 07:30", "error"); return; }
          if ((t.type === "app_open" || t.type === "app_close") && !t.value.trim()) { toast("Napiš název aplikace", "error"); return; }
          const clean = draft.steps.filter((s) => (s.say ?? "").trim() || (s.ask ?? "").trim() || s.tool);
          if (!clean.length) { toast("Přidej aspoň jeden krok", "error"); return; }
          const id = draft.id || `a${Date.now().toString(36)}`;
          const next = { ...draft, id, name: nm, steps: clean };
          save(draft.id ? items.map((x) => (x.id === draft.id ? next : x)) : [...items, next]);
          toast(`Automatizace ${nm} uložena.`, "ok");
          done();
        } }, icon("check"), "Uložit")));
    editor.scrollIntoView({ behavior: "smooth", block: "start" });
    name.focus();
  }

  const renderLog = (log: { name: string; ts: number; why: string }[]) => logBox.replaceChildren(...(log.length ? log.slice(0, 8).map((e) =>
    h("li", {}, h("span", { class: "muted" }, new Date(e.ts * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })),
      h("strong", {}, e.name), h("span", { class: "muted" }, e.why))) : [h("li", { class: "muted" }, "Zatím se nic nespustilo.")]));
  let log: any[] = [];
  client.on("automations", (m) => { log = m.log || []; renderLog(log); });
  client.on("automation", (m) => { log = [m, ...log].slice(0, 30); renderLog(log); });
  const sync = (s: any) => { items = (s?.automations?.items || []) as Automation[]; enabledAll = s?.automations?.enabled !== false; render(); };
  client.on("welcome", (m) => { sync(m.settings); client.send("automations_get", {}); });
  client.on("settings_changed", (m) => sync(m.settings));
  renderLog([]);

  const el = h("section", { class: "tasks-view stark-view" },
    hero(HEROES.auto, "Automatizace", "„Když … tak …“ – JARVIS sám zareaguje na čas, aplikace, e-maily, zprávy na mobilu i na to, že odejdeš od PC.", []),
    h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Automatizace zapnuté"),
      h("span", { class: "help" }, "Hlavní vypínač. Hlasem: „vypni všechny automatizace“.")), h("span", { class: "switch" }, master, h("span"))),
    h("p", { class: "help" }, "Novou můžeš říct i hlasem: „Když otevřu Spotify, dej hlasitost na 30“ nebo „Když mi napíše máma, řekni mi to nahlas“."),
    grid, editor,
    h("h2", { class: "group-label" }, "Naposledy spuštěné"),
    logBox);
  return { el };
}
