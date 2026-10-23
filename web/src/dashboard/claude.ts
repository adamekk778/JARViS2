// Claude Code in JARVIS (3.0): connect the hooks (after seeing the exact change), live sessions, approvals.
import { h, icon, toast } from "../shared/dom";
import { hero, HEROES } from "../shared/hero";
import type { JarvisClient } from "../shared/ws";

const STATE: Record<string, [string, string]> = {
  idle: ["Připraveno", ""], thinking: ["Přemýšlí", "busy"], working: ["Pracuje", "busy"], waiting: ["Čeká na tebe", "wait"],
  done: ["Hotovo", "ok"], error: ["Chyba", "bad"],
};

export function buildClaude(client: JarvisClient) {
  let settings: any = null;
  let sessions: any[] = [];
  let asks: any[] = [];
  let hooks: any = null;
  const connect = h("div", {});
  const asksBox = h("div", { class: "cc-asks" });
  const list = h("div", {});
  const prefs = h("div", {});
  const el = h("section", { class: "page-view" },
    h("div", { class: "page-inner" },
      hero(HEROES.claude, "Claude Code", "Co Claude Code právě dělá a schvalování jeho akcí z notche nebo z telefonu."),
      connect, asksBox, h("p", { class: "group-label" }, "Relace"), list, prefs));

  const set = (patch: any) => client.send("settings_set", { patch: { claude: patch } });
  const sw = (label: string, detail: string, key: string) => {
    const inp = h("input", { type: "checkbox", role: "switch", "aria-label": label }) as HTMLInputElement;
    inp.checked = !!settings?.claude?.[key];
    inp.onchange = () => set({ [key]: inp.checked });
    return h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, label), h("span", {}, detail)), h("label", { class: "switch" }, inp, h("span")));
  };

  function paintConnect() {
    const st = hooks?.status;
    if (!st) { connect.replaceChildren(); return; }
    const preview = hooks?.preview;
    connect.replaceChildren(h("section", { class: "group" }, h("h2", { class: "group-label" }, "Propojení"),
      h("div", { class: "card list" },
        h("div", { class: "row" },
          h("div", { class: "row-text" },
            h("strong", {}, st.installed ? "Propojeno s Claude Code" : st.partial ? "Propojení je neúplné" : "Není propojeno"),
            h("span", {}, st.error || (st.installed
              ? "Claude Code posílá JARVISovi, co dělá. Když JARVIS neběží, Claude Code pokračuje jako obvykle."
              : "JARVIS přidá do ~/.claude/settings.json pár řádků (hooky). Nejdřív ti ukáže přesnou změnu a udělá zálohu."))),
          st.installed
            ? h("button", { class: "btn", type: "button", onclick: () => client.send("claude_hooks_preview", { remove: true }) }, "Odpojit")
            : h("button", { class: "btn primary", type: "button", onclick: () => client.send("claude_hooks_preview", {}) }, icon("plug"), "Propojit")),
        preview ? h("div", { class: "cc-preview" },
          h("p", { class: "help" }, `Změna v ${preview.path}:${preview.reformat ? " (soubor se zároveň zarovná na 2 mezery, obsah zůstane stejný)" : ""}`),
          h("pre", { class: "cc-diff" }, ...preview.diff.split("\n").map((l: string) => h("span", { class: l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : "" }, l + "\n"))),
          h("div", { class: "btn-row" },
            h("button", { class: "btn primary", type: "button", onclick: () => client.send("claude_hooks_apply", { fingerprint: preview.fingerprint, remove: preview.remove }) },
              preview.remove ? "Odebrat hooky" : "Zapsat (se zálohou)"),
            h("button", { class: "btn", type: "button", onclick: () => { hooks = { status: st }; paintConnect(); } }, "Zrušit"))) : null)));
  }

  function paintAsks() {
    asksBox.replaceChildren(...asks.map((a) => h("div", { class: "card cc-ask" },
      h("div", { class: "cc-ask-head" }, icon("shield-warning", "ph-fill"), h("div", {}, h("strong", {}, `${a.project} chce: ${a.label}`),
        h("span", { class: "help" }, "Bez odpovědi se Claude Code zeptá v terminálu."))),
      (a.details || []).length ? h("pre", { class: "cc-details" }, (a.details as string[]).join("\n")) : null,
      h("div", { class: "btn-row" },
        h("button", { class: "btn primary", type: "button", onclick: () => client.send("claude_decision", { id: a.id, decision: "allow" }) }, "Povolit"),
        h("button", { class: "btn", type: "button", onclick: () => client.send("claude_decision", { id: a.id, decision: "always" }) }, `Vždy povolit ${a.tool}`),
        h("button", { class: "btn danger", type: "button", onclick: () => client.send("claude_decision", { id: a.id, decision: "deny" }) }, "Zamítnout"),
        h("button", { class: "btn ghost", type: "button", onclick: () => client.send("claude_decision", { id: a.id, decision: "terminal" }) }, "Odpovím v terminálu")))));
  }

  function paintSessions() {
    if (!sessions.length) {
      list.replaceChildren(h("div", { class: "card d-empty" }, icon("terminal-window"),
        h("p", {}, hooks?.status?.installed ? "Teď neběží žádná relace. Spusť Claude Code a uvidíš ji tady i v notchi." : "Nejdřív Claude Code propoj (nahoře).")));
      return;
    }
    list.replaceChildren(...sessions.map((s) => {
      const [label, cls] = STATE[s.state] || [s.state, ""];
      return h("div", { class: "card cc-session" },
        h("div", { class: "cc-s-head" }, h("strong", {}, s.project), h("span", { class: `tag st-${cls}` }, label),
          h("span", { class: "help" }, `${s.edits} úprav · ${s.commands} příkazů`)),
        s.prompt ? h("p", { class: "cc-prompt" }, `„${s.prompt}“`) : null,
        h("ul", { class: "cc-steps" }, ...(s.steps || []).slice().reverse().map((st: any) => h("li", {},
          h("span", {}, new Date(st.t * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit", second: "2-digit" })), st.text))));
    }));
  }

  function paintPrefs() {
    const always: string[] = settings?.claude?.always_allow || [];
    prefs.replaceChildren(h("section", { class: "group" }, h("h2", { class: "group-label" }, "Nastavení"),
      h("div", { class: "card list" },
        sw("Sledovat Claude Code", "Relace v notchi a tady.", "enabled"),
        sw("Schvalovat z JARVISe", "Povolit / Zamítnout v notchi a v telefonu. Nic se nepovolí bez tvého kliknutí.", "approvals"),
        sw("Upozornit, když Claude skončí", "Notifikace v notchi a v telefonu.", "notify_done"),
        h("div", { class: "row" }, h("div", { class: "row-text" }, h("strong", {}, "Vždy povolené nástroje"),
          h("span", {}, always.length ? "Na tyhle se JARVIS neptá." : "Zatím žádné. Přidáš je tlačítkem Vždy u žádosti.")),
          h("div", { class: "chips" }, ...always.map((t) => h("span", { class: "chip" }, t,
            h("button", { class: "chip-x", type: "button", "aria-label": `Odebrat ${t}`, onclick: () => set({ always_allow: always.filter((x) => x !== t) }) }, icon("x")))))))));
  }

  client.on("welcome", (m) => { settings = m.settings; sessions = m.claude_sessions || []; asks = m.claude_pending || []; paintSessions(); paintAsks(); paintPrefs(); });
  client.on("settings_changed", (m) => { settings = m.settings; paintPrefs(); });
  client.on("claude_sessions", (m) => { sessions = m.items || []; paintSessions(); });
  client.on("claude_permission", (m) => { asks.push(m); paintAsks(); });
  client.on("claude_permission_resolved", (m) => { asks = asks.filter((a) => a.id !== m.id); paintAsks(); });
  client.on("claude_hooks", (m) => {
    if (m.error) toast(m.error, "error", 7000);
    if (m.applied) toast(m.applied.backup ? `Hotovo. Záloha: ${m.applied.backup}` : "Hotovo.", "ok", 6000);
    hooks = { status: m.status, preview: m.applied ? null : m.preview };
    paintConnect();
    paintSessions();
  });
  return { el, show: () => { client.send("claude_hooks_status"); client.send("claude_sessions_get"); } };
}
