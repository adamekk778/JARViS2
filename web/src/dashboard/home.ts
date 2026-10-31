// Dashboard → Domov (3.5): the smart home (Home Assistant), shared lists (shopping, to-dos…) and the home network.
import { hero, HEROES } from "../shared/hero";
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import { netGraph } from "../shared/charts";

interface Device { id: string; name: string; domain: string; state: string; unit?: string; brightness?: number; target?: number; current?: number; position?: number }
interface NetDevice { ip: string; mac: string; name: string; host: string; new: boolean }

const DOMAIN: Record<string, { label: string; ico: string }> = {
  light: { label: "Světla", ico: "lightbulb" }, switch: { label: "Zásuvky a vypínače", ico: "plug" },
  fan: { label: "Ventilátory", ico: "fan" }, climate: { label: "Topení a klima", ico: "thermometer" },
  cover: { label: "Žaluzie a brány", ico: "blinds" }, scene: { label: "Scény", ico: "magic-wand" },
  script: { label: "Skripty", ico: "play" }, lock: { label: "Zámky", ico: "lock" },
  input_boolean: { label: "Přepínače", ico: "toggle-right" }, media_player: { label: "Přehrávače", ico: "speaker-high" },
  sensor: { label: "Teploty a vlhkost", ico: "gauge" },
};
const ORDER = ["scene", "light", "switch", "climate", "cover", "fan", "media_player", "input_boolean", "script", "lock", "sensor"];
const STATE: Record<string, string> = { on: "zapnuto", off: "vypnuto", open: "otevřeno", closed: "zavřeno", locked: "zamčeno", unlocked: "odemčeno",
  heat: "topí", cool: "chladí", playing: "hraje", paused: "pauza", idle: "nečinný", unavailable: "nedostupné" };

export function buildHome(client: JarvisClient) {
  let settings: any = {};
  let devices: Device[] = [];
  let configured = false;
  let lists: Record<string, string[]> = {};
  let current = "nákup";

  // ---------------- smart home ----------------
  const homeBox = h("div", { class: "home-box" });
  const url = h("input", { class: "input", placeholder: "http://homeassistant.local:8123", "aria-label": "Adresa Home Assistantu" }) as HTMLInputElement;
  const token = h("input", { class: "input", type: "password", placeholder: "Dlouhodobý přístupový token", "aria-label": "Token", autocomplete: "off" }) as HTMLInputElement;
  const connect = () => {
    if (!url.value.trim()) { toast("Zadej adresu Home Assistantu", "error"); return; }
    client.send("home_set", { url: url.value.trim(), token: token.value.trim() });
    toast("Zkouším spojení…", "ok");
  };
  const setupCard = () => h("div", { class: "card home-setup" },
    h("p", {}, "Připoj Home Assistant a JARVIS bude ovládat světla, zásuvky, topení, žaluzie a scény – hlasem i odsud."),
    h("ol", { class: "help" },
      h("li", {}, "V Home Assistantu klikni vlevo dole na svůj profil → Zabezpečení."),
      h("li", {}, "Dole „Dlouhodobé přístupové tokeny“ → Vytvořit token → zkopíruj ho."),
      h("li", {}, "Sem vlož adresu (třeba http://homeassistant.local:8123) a token.")),
    h("label", { class: "pe-row" }, h("span", {}, "Adresa"), url),
    h("label", { class: "pe-row" }, h("span", {}, "Token"), token),
    h("div", { class: "btn-row" }, h("button", { class: "btn primary", type: "button", onclick: connect }, icon("plugs-connected"), "Připojit")),
    h("p", { class: "help" }, "Token se uloží do trezoru Windows, nikam jinam."));

  function tile(d: Device): HTMLElement {
    const on = ["on", "open", "playing", "heat", "cool", "unlocked"].includes(d.state);
    const meta = DOMAIN[d.domain] || { label: d.domain, ico: "circle" };
    const label = d.domain === "sensor" ? `${d.state} ${d.unit || ""}` : d.domain === "climate"
      ? `${d.current ?? "?"} °C → ${d.target ?? "?"} °C` : d.domain === "scene" || d.domain === "script" ? "spustit"
      : `${STATE[d.state] || d.state}${d.brightness && d.state === "on" ? ` · ${d.brightness} %` : ""}${d.position != null ? ` · ${d.position} %` : ""}`;
    const act = (action: string, value?: number) => client.send("home_action", { id: d.id, action, value });
    const extra: HTMLElement[] = [];
    if (d.domain === "climate" && d.target != null) {
      extra.push(h("div", { class: "home-temp" },
        h("button", { class: "icon-btn sm", type: "button", "aria-label": "Ubrat stupeň", onclick: (e: Event) => { e.stopPropagation(); act("set", (d.target || 20) - 0.5); } }, icon("minus")),
        h("button", { class: "icon-btn sm", type: "button", "aria-label": "Přidat stupeň", onclick: (e: Event) => { e.stopPropagation(); act("set", (d.target || 20) + 0.5); } }, icon("plus"))));
    }
    if (d.domain === "cover") {
      extra.push(h("div", { class: "home-temp" },
        h("button", { class: "icon-btn sm", type: "button", "aria-label": "Otevřít", onclick: (e: Event) => { e.stopPropagation(); act("open"); } }, icon("arrow-up")),
        h("button", { class: "icon-btn sm", type: "button", "aria-label": "Zastavit", onclick: (e: Event) => { e.stopPropagation(); act("stop"); } }, icon("pause")),
        h("button", { class: "icon-btn sm", type: "button", "aria-label": "Zavřít", onclick: (e: Event) => { e.stopPropagation(); act("close"); } }, icon("arrow-down"))));
    }
    const clickable = ["light", "switch", "fan", "input_boolean", "media_player", "scene", "script"].includes(d.domain);
    const el = h(clickable ? "button" : "div", { class: `home-tile ${on ? "on" : ""} ${d.state === "unavailable" ? "na" : ""}`, type: clickable ? "button" : undefined,
      title: d.id, onclick: clickable ? () => act(d.domain === "scene" || d.domain === "script" ? "on" : "toggle") : undefined },
      h("span", { class: "ht-ico" }, icon(meta.ico, on ? "ph-fill" : "ph")), h("strong", {}, d.name), h("span", { class: "muted" }, label), ...extra);
    return el;
  }

  function renderHome() {
    if (!configured) { homeBox.replaceChildren(setupCard()); return; }
    const groups = ORDER.map((dom) => [dom, devices.filter((d) => d.domain === dom)] as const).filter(([, ds]) => ds.length);
    homeBox.replaceChildren(
      h("div", { class: "btn-row" },
        h("button", { class: "btn", type: "button", onclick: () => client.send("home_get", {}) }, icon("arrow-clockwise"), "Obnovit"),
        h("button", { class: "btn ghost", type: "button", onclick: () => { configured = false; renderHome(); } }, icon("gear"), "Změnit připojení"),
        h("button", { class: "btn ghost", type: "button", onclick: () => { if (confirm("Odpojit Home Assistant?")) client.send("home_set", { url: "" }); } }, icon("plugs"), "Odpojit")),
      ...(groups.length ? groups.map(([dom, ds]) => h("div", { class: "home-group" },
        h("h3", {}, DOMAIN[dom]?.label || dom), h("div", { class: "home-grid" }, ...ds.map(tile))))
        : [h("p", { class: "help" }, "Home Assistant je připojený, ale nemá žádná světla ani zásuvky.")]),
      h("p", { class: "help" }, "Hlasem: „rozsviť v obýváku“, „zhasni všechna světla“, „nastav topení na 22“, „spusť scénu kino“. Zámky ovládej hlasem (zeptá se) nebo v Home Assistantu."));
  }
  client.on("home", (m) => {
    if (!m.ok) toast(m.error || "Home Assistant neodpovídá", "error", 6000);
    configured = !!m.configured;
    if (m.devices) devices = m.devices;
    if (m.ok && m.count) toast(`Připojeno – ${m.count} zařízení`, "ok");
    renderHome();
  });

  // ---------------- lists ----------------
  const listBox = h("div", { class: "card list-box" });
  const addInp = h("input", { class: "input", placeholder: "Přidat… (víc věcí odděl čárkou)", "aria-label": "Nová položka" }) as HTMLInputElement;
  const add = () => {
    const items = addInp.value.split(",").map((x) => x.trim()).filter(Boolean);
    if (!items.length) return;
    client.send("list_update", { list: current, add: items });
    addInp.value = "";
  };
  addInp.onkeydown = (e) => { if (e.key === "Enter") add(); };
  function renderLists() {
    const names = Array.from(new Set(["nákup", ...Object.keys(lists)]));
    const items = lists[current] || [];
    listBox.replaceChildren(
      h("div", { class: "list-tabs", role: "tablist" }, ...names.map((n) => h("button", { type: "button", role: "tab", class: `chip ${n === current ? "on" : ""}`,
        "aria-selected": String(n === current), onclick: () => { current = n; renderLists(); } }, n, lists[n]?.length ? h("span", { class: "badge" }, String(lists[n].length)) : null)),
        h("button", { type: "button", class: "chip", onclick: () => { const n = prompt("Název nového seznamu (např. dárky)")?.trim().toLowerCase(); if (n) { current = n; lists[n] = lists[n] || []; renderLists(); addInp.focus(); } } }, icon("plus"), "Nový")),
      h("ul", { class: "list-items" }, ...(items.length ? items.map((it) => h("li", {},
        h("label", {}, h("input", { type: "checkbox", "aria-label": `Hotovo: ${it}`, onchange: () => client.send("list_update", { list: current, remove: [it] }) }), h("span", {}, it))))
        : [h("li", { class: "muted" }, "Prázdný. Přidej sem, nebo řekni „přidej mléko na nákup“.")])),
      h("div", { class: "list-add" }, addInp, h("button", { class: "btn primary", type: "button", onclick: add }, icon("plus"), "Přidat")),
      h("div", { class: "btn-row" },
        h("button", { class: "btn", type: "button", onclick: () => client.send("user_text", { text: `Pošli mi seznam ${current} do mobilu`, attachments: [] }) }, icon("device-mobile"), "Poslat do mobilu"),
        items.length ? h("button", { class: "btn ghost", type: "button", onclick: () => { if (confirm(`Vymazat celý seznam ${current}?`)) client.send("list_update", { list: current, clear: true }); } }, icon("trash"), "Vymazat") : null));
  }
  client.on("lists", (m) => { lists = m.lists || {}; renderLists(); });

  // ---------------- network ----------------
  const netBox = h("div", { class: "net-box" });
  const watch = h("input", { type: "checkbox", role: "switch", "aria-label": "Hlídat nová zařízení" }) as HTMLInputElement;
  watch.onchange = () => client.send("settings_set", { patch: { stark: { network_watch: watch.checked } } });
  let scanning = false;
  const scan = () => { scanning = true; renderNet([]); client.send("network_get", {}); };
  function renderNet(items: NetDevice[]) {
    netBox.replaceChildren(
      h("label", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Hlídat nová zařízení"),
        h("span", { class: "help" }, "Když se do sítě připojí něco, co tu ještě nebylo, JARVIS to řekne (kontrola každých 10 minut).")),
        h("span", { class: "switch" }, watch, h("span"))),
      h("div", { class: "btn-row" }, h("button", { class: "btn primary", type: "button", onclick: scan, disabled: scanning }, icon("wifi-high"), scanning ? "Hledám…" : "Prohledat síť")),
      ...(items.length ? [netGraph(items, (items.find((d: any) => d.gateway) as any)?.ip || items.map((d) => d.ip).find((ip) => /\.1$/.test(ip)) || ""),
        h("div", { class: "net-table", role: "table" }, ...items.map((d) => {
        const nm = h("input", { class: "input sm", value: d.name, placeholder: d.host || "pojmenovat…", "aria-label": `Název zařízení ${d.ip}` }) as HTMLInputElement;
        nm.onchange = () => client.send("network_name", { mac: d.mac, name: nm.value });
        return h("div", { class: "net-row", role: "row" }, h("span", { class: "ht-ico" }, icon(d.new ? "warning-circle" : "devices")), nm,
          h("span", { class: "mono muted" }, d.ip), h("span", { class: "mono muted" }, d.mac), d.new ? h("span", { class: "badge warn" }, "nové") : h("span"),
          h("button", { class: "btn ghost sm", type: "button", title: "Zapnout přes Wake-on-LAN", onclick: () => client.send("network_wake", { mac: d.mac }) }, icon("power"), "Probudit"));
      }))] : []));
  }
  client.on("network", (m) => { scanning = false; renderNet(m.devices || []); });

  const sync = (s: any) => { settings = s; watch.checked = !!settings?.stark?.network_watch; };
  client.on("welcome", (m) => {
    sync(m.settings);
    configured = !!m.settings?.home?.url;
    url.value = m.settings?.home?.url || "";
    renderHome();
    client.send("lists_get", {});
    if (configured) client.send("home_get", {});
  });
  client.on("settings_changed", (m) => sync(m.settings));
  renderHome(); renderLists(); renderNet([]);

  const el = h("section", { class: "tasks-view home-view" },
    hero(HEROES.home, "Domov", "Chytrá domácnost, společné seznamy a tvoje síť – jako JARVIS v Starkově vile.", []),
    h("h2", { class: "group-label" }, "Chytrá domácnost"), homeBox,
    h("h2", { class: "group-label" }, "Seznamy"), listBox,
    h("h2", { class: "group-label" }, "Síť"), netBox);
  return { el };
}
