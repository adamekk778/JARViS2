// 3.12 Propojení: the services JARVIS works in for you (like ChatGPT's connectors) – Google, Supabase, Spaceship,
// GitHub, Notion, Slack, and any MCP server by its address. Keys go straight into Windows' secure storage; this page
// only ever sees whether a key is set, never the key.
import "./connect.css";
import { h, icon, toast } from "../shared/dom";
import { hero, HEROES } from "../shared/hero";
import type { JarvisClient } from "../shared/ws";

interface Field { key: string; label: string; secret: boolean; hint: string; set: boolean; optional?: boolean }
interface Conn { id: string; name: string; icon: string; help: string[]; url: string; oauth: boolean; what: string; fields: Field[];
  connected: boolean; last?: { ok: boolean; detail: string } | null; group?: string; group_name?: string; login?: string }

const GROUP_ORDER = ["work", "money", "sales", "tasks", "dev", "chat", "music"];
const fold = (t: string) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
// the sign-in address in the steps names this PC's real port (8765 unless changed)
const port = (t: string) => (location.port && location.port !== "8765" ? t.replace(/:8765\//g, `:${location.port}/`) : t);

export function buildConnect(client: JarvisClient) {
  let items: Conn[] = [];
  let open = "";
  let mcp: any[] = [];
  let query = "";
  let group = "";
  const grid = h("div", { class: "cn-sections" });
  const mcpBox = h("div", { class: "cn-mcp" });

  const card = (c: Conn) => {
    const inputs: Record<string, HTMLInputElement> = {};
    const isOpen = open === c.id;
    const state = c.connected ? (c.last && !c.last.ok ? "warn" : "on") : "off";
    const head = h("button", { type: "button", class: "cn-head", onclick: () => { open = isOpen ? "" : c.id; paint(); } },
      h("span", { class: "cn-ico" }, icon(c.icon, "ph-fill")),
      h("div", { class: "cn-tt" }, h("strong", {}, c.name), h("span", {}, c.what)),
      h("span", { class: `cn-pill ${state}` }, c.connected ? (state === "warn" ? "Problém" : "Propojeno") : "Propojit"),
      icon(isOpen ? "caret-up" : "caret-down"));
    if (!isOpen) return h("div", { class: `cn-card ${state}` }, head);
    const form = h("div", { class: "cn-form" },
      ...c.fields.map((f) => {
        const inp = h("input", { class: "cn-in", type: f.secret ? "password" : "text", autocomplete: "off", spellcheck: "false",
          placeholder: f.set ? "•••••••• uloženo (nové přepíše)" : (f.hint || f.label), "aria-label": f.label }) as HTMLInputElement;
        inputs[f.key] = inp;
        return h("label", { class: "cn-field" }, h("span", {}, f.label, f.optional && !/nepovinn/i.test(f.label) ? " (nepovinné)" : ""), inp);
      }));
    const save = () => {
      const values: Record<string, string> = {};
      for (const [k, inp] of Object.entries(inputs)) if (inp.value.trim()) values[k] = inp.value.trim();
      if (!Object.keys(values).length && !c.connected) { toast("Vyplň klíč.", "error"); return; }
      client.send("connector_save", { id: c.id, values });
      toast("Ukládám a zkouším…", "info");
    };
    return h("div", { class: `cn-card open ${state}` }, head,
      c.last ? h("p", { class: `cn-last ${c.last.ok ? "ok" : "bad"}` }, icon(c.last.ok ? "check-circle" : "warning-circle", "ph-fill"), c.last.detail) : "",
      h("ol", { class: "cn-steps" }, ...c.help.map((s) => h("li", {}, port(s)))),
      c.url ? h("a", { class: "cn-link", href: c.url, target: "_blank", rel: "noopener" }, icon("arrow-square-out"), "Otevřít stránku služby") : "",
      form,
      h("div", { class: "cn-acts" },
        h("button", { type: "button", class: "btn primary", onclick: save }, icon("floppy-disk"), c.oauth ? "Uložit" : "Uložit a vyzkoušet"),
        c.oauth ? h("button", { type: "button", class: "btn", onclick: () => client.send("connector_oauth", { id: c.id }) },
          icon("sign-in"), c.login || "Přihlásit se") : "",
        c.connected ? h("button", { type: "button", class: "btn", onclick: () => client.send("connector_test", { id: c.id }) }, icon("lightning"), "Vyzkoušet") : "",
        c.connected ? h("button", { type: "button", class: "btn danger", onclick: () => {
          if (confirm(`Odpojit ${c.name}? Klíče se z tohoto PC smažou.`)) client.send("connector_remove", { id: c.id });
        } }, icon("plug"), "Odpojit") : ""));
  };

  const paintMcp = () => {
    const name = h("input", { class: "cn-in", placeholder: "Název (např. linear)", "aria-label": "Název" }) as HTMLInputElement;
    const url = h("input", { class: "cn-in", placeholder: "https://…/mcp", "aria-label": "Adresa MCP serveru" }) as HTMLInputElement;
    const tok = h("input", { class: "cn-in", type: "password", placeholder: "Token (nepovinný)", "aria-label": "Token" }) as HTMLInputElement;
    mcpBox.replaceChildren(
      h("div", { class: "cn-mcp-h" }, h("strong", {}, "Vlastní (MCP server)"),
        h("span", {}, "Cokoli dalšího – Linear, Stripe, Sentry, Zapier… Stačí adresa jejich MCP serveru a případně token.")),
      ...mcp.map((s) => h("div", { class: "cn-mcp-row" }, icon(s.ok ? "check-circle" : "circle", s.ok ? "ph-fill" : undefined),
        h("b", {}, s.name), h("span", {}, s.ok ? `${s.tools} nástrojů` : (s.error || "nepřipojeno")),
        h("button", { type: "button", class: "btn sm", onclick: () => client.send("mcp_remove", { name: s.name }) }, "Odebrat"))),
      h("div", { class: "cn-mcp-add" }, name, url, tok,
        h("button", { type: "button", class: "btn", onclick: () => {
          if (!name.value.trim() || !/^https?:\/\//.test(url.value.trim())) { toast("Vyplň název a adresu (https://…).", "error"); return; }
          client.send("mcp_add", { name: name.value.trim(), url: url.value.trim(), token: tok.value.trim() });
        } }, icon("plus"), "Přidat")));
  };

  const section = (title: string, list: Conn[], cls = "") => list.length
    ? h("section", { class: `cn-sec ${cls}` }, h("h3", { class: "cn-sec-h" }, title, h("span", {}, String(list.length))),
      h("div", { class: "cn-grid" }, ...list.map(card)))
    : "";
  const paint = () => {
    const on = items.filter((c) => c.connected).length;
    count.textContent = items.length ? `${on} z ${items.length} propojeno` : "";
    const q = fold(query.trim());
    const shown = items.filter((c) => (!group || c.group === group)
      && (!q || fold(`${c.name} ${c.what} ${c.id}`).includes(q)));
    const groups = [...new Set([...GROUP_ORDER, ...items.map((c) => c.group || "")])].filter(Boolean);
    chips.replaceChildren(
      h("button", { type: "button", class: `cn-chip ${group ? "" : "on"}`, onclick: () => { group = ""; paint(); } }, "Vše"),
      ...groups.filter((g) => items.some((c) => c.group === g)).map((g) => h("button", {
        type: "button", class: `cn-chip ${group === g ? "on" : ""}`, onclick: () => { group = group === g ? "" : g; paint(); },
      }, items.find((c) => c.group === g)?.group_name || g)));
    const linked = shown.filter((c) => c.connected);
    grid.replaceChildren(
      section("Propojené", linked, "linked"),
      ...groups.map((g) => section(items.find((c) => c.group === g)?.group_name || g, shown.filter((c) => c.group === g && !c.connected))),
      shown.length ? "" : h("p", { class: "help cn-empty" }, "Nic takového tu není – zkus jiné slovo, nebo přidej službu jako vlastní MCP server dole."));
    paintMcp();
  };
  const count = h("span", { class: "cn-count" });
  const chips = h("div", { class: "cn-chips", role: "toolbar", "aria-label": "Skupiny služeb" });
  const search = h("input", { class: "cn-in cn-search", type: "search", placeholder: "Hledat službu (Stripe, faktury, e-shop…)",
    "aria-label": "Hledat službu", oninput: () => { query = search.value; paint(); } }) as HTMLInputElement;
  client.on("connectors", (m: any) => {
    items = Array.isArray(m.items) ? m.items : [];
    if (m.message) toast(m.message, /^✓/.test(m.message) || /Propojen|Uloženo|Odpojeno|otevřelo/.test(m.message) ? "ok" : "error", 7000);
    paint();
  });
  client.on("mcp", (m: any) => { mcp = Array.isArray(m.servers) ? m.servers : Array.isArray(m.items) ? m.items : []; paintMcp(); });

  const el = h("section", { class: "cn-view" },
    hero(HEROES.connect, "Propojení", "JARVIS pracuje i v tvých službách – čte, hledá a připravuje. Odeslat, zapsat nebo změnit "
      + "něco smí jen s tvým potvrzením.", [count]),
    h("div", { class: "cn-bar" }, search, chips),
    grid, mcpBox,
    h("p", { class: "help cn-note" }, icon("lock-key"), " Klíče a tokeny se ukládají do zabezpečeného úložiště Windows, ne do souborů. "
      + "Po propojení stačí napsat třeba „co mám nového v Gmailu“, „kolik mi dnes přišlo na Fio“, „které faktury jsou po splatnosti“ "
      + "nebo „co mám dnes v Todoistu“."));
  paint();
  return { el, show() { client.send("connectors_get"); client.send("mcp_get"); } };
}
