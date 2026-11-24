// 3.14 Kdo odpovídá: the AIs as tiles – a click makes that one answer from now on; under the chosen one its models,
// switchable right here (Ollama: the models downloaded on this PC; Claude: Opus, Sonnet, Haiku, Fable). Claude without
// a key shows the key field right in its tile. The same picker is in Nastavení → Mozek and behind the AI chip in the chat.
import "./brainpicker.css";
import { brandEl, brandOf } from "./brands";
import { h, icon, toast } from "./dom";
import type { JarvisClient } from "./ws";

type Tile = { preset: string; id: string; label: string; local: boolean; added: boolean; enabled: boolean; model: string;
  key: boolean; needs_key: boolean; active: boolean };
type Current = { id: string; preset: string; label: string; model: string; only: boolean;
  claude?: { usd: number; limit: number; over: boolean; calls: number };
  split?: { on: boolean; easy: string; hard: string } };
type Model = { id: string; label: string; note: string; where?: string; recommended?: boolean; size_gb?: number };

const SHORT: Record<string, string> = { anthropic: "Claude", ollama: "Ollama (v PC)", groq: "Groq", gemini: "Gemini", openai: "ChatGPT",
  openrouter: "OpenRouter", omniroute: "OmniRoute", lmstudio: "LM Studio (v PC)" };
const KEY_HELP: Record<string, string> = {
  anthropic: "Klíč z console.anthropic.com → API Keys (začíná sk-ant-). Předplatné Claude Pro/Max klíč nedává.",
  groq: "Zdarma na console.groq.com (začíná gsk_).", gemini: "Zdarma na aistudio.google.com.", openai: "Z platform.openai.com.",
  openrouter: "Z openrouter.ai/keys (začíná sk-or-).",
};

export function createBrainPicker(client: JarvisClient, opts: { compact?: boolean } = {}) {
  let tiles: Tile[] = [], cur: Current | null = null;
  let models: { key: string; models: Model[]; current: string; error: string; catalog: Model[] } | null = null;
  // 3.14 a model being downloaded from here: its progress, then it is switched on
  let pull: { name: string; key: string; pct: number; status: string; error?: string } | null = null;
  let asked = "";
  let mine = 0;                                         // this picker asked for the change: only it shows the notes
  const el = h("div", { class: `bp ${opts.compact ? "compact" : ""}` }, h("p", { class: "bp-wait" }, "Načítám…"));

  const keyRow = (t: Tile) => {
    const inp = h("input", { class: "input", type: "password", autocomplete: "off", placeholder: t.preset === "anthropic" ? "sk-ant-…" : "API klíč",
      "aria-label": `API klíč pro ${t.label}` }) as HTMLInputElement;
    const save = () => {
      const v = inp.value.replace(/[\s"'“”„]/g, "");
      if (!v) return;
      inp.value = "";
      client.send("brain_key", { key: v, preset: t.preset });
      toast("Klíč ukládám a zkouším…", "info", 2200);
      window.setTimeout(refresh, 1500);
    };
    inp.onpaste = () => window.setTimeout(save, 30);
    inp.onkeydown = (e: KeyboardEvent) => { if (e.key === "Enter") { e.preventDefault(); save(); } };
    return h("div", { class: "bp-key" }, h("div", { class: "key-row" }, inp,
      h("button", { class: "btn primary sm", type: "button", onclick: save }, icon("check"), "Uložit")),
      h("p", { class: "help" }, KEY_HELP[t.preset] || "Vlož API klíč této služby."));
  };

  function modelsRow(t: Tile) {
    if (!models || models.key !== t.id) {
      if (asked !== t.id) { asked = t.id; client.send("brain_models_get", { key: t.id }); }
      return h("p", { class: "help bp-models" }, icon("circle-notch"), " Načítám modely…");
    }
    if (models.error && !models.models.length) {
      return h("div", { class: "bp-models" }, h("p", { class: "help bad" }, models.error),
        h("button", { class: "btn ghost sm", type: "button", onclick: () => { asked = ""; models = null; paint(); } }, icon("arrows-clockwise"), "Zkusit znovu"));
    }
    const sel = h("select", { class: "input", "aria-label": `Model pro ${t.label}` },
      ...models.models.map((m) => h("option", { value: m.id, selected: m.id === (cur?.model || models!.current) }, m.note ? `${m.label} – ${m.note}` : m.label))) as HTMLSelectElement;
    if (!models.models.some((m) => m.id === (cur?.model || ""))) sel.prepend(h("option", { value: cur?.model || "", selected: true }, cur?.model || "—"));
    sel.onchange = () => { client.send("brain_use", { key: t.id, model: sel.value }); toast(`Model: ${sel.value}`, "ok", 1600); };
    const row = h("label", { class: "bp-models" }, h("span", {}, "Model"), sel,
      t.preset === "ollama" ? h("button", { class: "icon-btn sm", type: "button", title: "Načíst znovu", "aria-label": "Načíst modely znovu",
        onclick: () => { asked = ""; models = null; paint(); } }, icon("arrows-clockwise")) : "");
    return t.preset === "ollama" ? h("div", { class: "bp-ollama" }, row, downloadRow(t)) : row;
  }

  // 3.14 another model for Ollama, downloaded right here (the best for this PC first, with the speed it would have)
  function downloadRow(t: Tile): HTMLElement | string {
    if (pull && pull.key === t.id) {
      return h("div", { class: "bp-pull" }, h("span", {}, pull.error ? `Stažení ${pull.name} selhalo: ${pull.error}` : `Stahuji ${pull.name} – ${pull.status || "…"}`),
        pull.error ? h("button", { class: "btn ghost sm", type: "button", onclick: () => { pull = null; paint(); } }, "Zavřít")
          : h("span", { class: "bp-bar", role: "progressbar", "aria-valuenow": String(pull.pct), "aria-valuemin": "0", "aria-valuemax": "100" },
            h("i", { style: { width: `${Math.max(3, pull.pct)}%` } })),
        pull.error ? "" : h("button", { class: "btn ghost sm", type: "button", onclick: () => client.send("local_pull_cancel") }, "Zrušit"));
    }
    const cat = models?.catalog || [];
    if (!cat.length) return "";
    const sel = h("select", { class: "input", "aria-label": "Model ke stažení" },
      ...cat.map((m) => h("option", { value: m.id }, `${m.recommended ? "★ " : ""}${m.label} – ${m.note}`))) as HTMLSelectElement;
    const go = () => {
      const m = cat.find((x) => x.id === sel.value);
      if (!m) return;
      if (m.where === "nevejde se" && !confirm(`${m.label} se do paměti tohoto PC nevejde a poběží velmi pomalu (nebo vůbec). Stáhnout i tak?`)) return;
      if (!confirm(`Stáhnout ${m.label} (${m.size_gb ?? "?"} GB)? Pak na něj JARVIS přepne.`)) return;
      pull = { name: m.id, key: t.id, pct: 0, status: "začínám" };
      client.send("local_pull", { name: m.id });
      paint();
    };
    return h("details", { class: "bp-more" }, h("summary", {}, icon("download-simple"), " Stáhnout další model"),
      h("div", { class: "bp-models" }, sel, h("button", { class: "btn sm", type: "button", onclick: go }, "Stáhnout")),
      h("p", { class: "help" }, "★ = doporučený pro tvůj počítač. Rychlý = celý se vejde do grafické karty."));
  }

  function paint() {
    if (!tiles.length) return;
    const shown = opts.compact ? tiles.filter((t) => t.added || t.active || t.preset === "anthropic" || t.preset === "ollama") : tiles;
    const act = tiles.find((t) => t.active);
    const grid = h("div", { class: "bp-grid", role: "radiogroup", "aria-label": "Která AI odpovídá" }, ...shown.map((t) => {
      const state = t.active ? "odpovídá" : !t.key ? "chybí klíč" : t.added && t.enabled ? "záloha" : t.local ? "v tomhle PC" : "přidat";
      return h("button", { type: "button", role: "radio", "aria-checked": String(t.active), class: `bp-tile ${t.active ? "on" : ""} ${!t.key ? "nokey" : ""}`,
        onclick: () => { if (!t.active) { mine = Date.now(); client.send("brain_use", { key: t.id }); models = null; asked = ""; } } },
        h("span", { class: "bp-logo" }, brandEl(brandOf(t.preset, ""))),
        h("span", { class: "bp-txt" }, h("b", {}, SHORT[t.preset] || t.label), h("small", {}, state)));
    }));
    const parts: (HTMLElement | string)[] = [grid];
    if (act) {
      parts.push(h("div", { class: "bp-detail" },
        h("div", { class: "bp-now" }, h("strong", {}, `Odpovídá ${SHORT[act.preset] || act.label}`), cur?.model ? h("span", {}, cur.model) : ""),
        !act.key ? keyRow(act) : modelsRow(act),
        act.preset === "anthropic" && act.key ? spendRow() : "",
        (() => {
          const cb = h("input", { type: "checkbox", role: "switch", "aria-label": "Jen tento mozek" }) as HTMLInputElement;
          cb.checked = !!cur?.only;
          cb.onchange = () => client.send("brain_use", { key: act.id, only: cb.checked });
          return h("label", { class: "row bp-only" }, h("div", { class: "row-text" }, h("strong", {}, "Jen tento mozek"),
            h("span", { class: "help" }, cb.checked ? "Ostatní AI se nepoužijí ani jako záloha." : "Když tahle AI nepůjde, zkusí JARVIS další v pořadí.")),
            h("span", { class: "switch" }, cb, h("span")));
        })()));
    }
    if (!opts.compact) parts.push(splitBox());
    el.replaceChildren(...parts);
  }

  // 3.14 what Claude cost today (USD by the model's price list – an estimate) and a daily limit
  function spendRow(): HTMLElement {
    const c = cur?.claude || { usd: 0, limit: 0, over: false, calls: 0 };
    const money = (v: number) => `$${v.toFixed(v < 1 ? 2 : 1)}`.replace(".", ",");
    const lim = h("input", { class: "input sm", type: "number", min: 0, step: 0.5, value: c.limit || "", placeholder: "bez limitu",
      "aria-label": "Denní limit pro Claude v dolarech" }) as HTMLInputElement;
    lim.onchange = () => client.send("settings_set", { patch: { limits: { claude_daily_usd: Math.max(0, Number(lim.value) || 0) } } });
    return h("div", { class: "bp-spend" },
      h("span", {}, "Dnes ≈ ", h("b", { class: c.over ? "bad" : "" }, money(c.usd)), c.calls ? ` · ${c.calls}× dotaz` : "", " (odhad)"),
      h("label", {}, "Denní limit $", lim));
  }

  // 3.14 chytré rozdělení: easy questions to one AI (e.g. Ollama, free), hard tasks to another (e.g. Claude)
  function splitBox(): HTMLElement {
    const sp = cur?.split || { on: false, easy: "", hard: "" };
    const pick = (label: string, val: string, fallback: string, put: (v: string) => void) => {
      const want = val || fallback;
      const sel = h("select", { class: "input", "aria-label": label },
        ...tiles.map((t) => h("option", { value: t.id, selected: t.id === want || (!val && t.preset === fallback) }, SHORT[t.preset] || t.label))) as HTMLSelectElement;
      sel.onchange = () => put(sel.value);
      return h("label", { class: "bp-models" }, h("span", {}, label), sel);
    };
    const easyDef = tiles.find((t) => t.preset === "ollama")?.id || "ollama";
    const hardDef = tiles.find((t) => t.preset === "anthropic")?.id || "anthropic";
    let easy = sp.easy || easyDef, hard = sp.hard || hardDef;
    const send = (on: boolean) => { mine = Date.now(); client.send("brain_split", { on, easy, hard }); };
    const cb = h("input", { type: "checkbox", role: "switch", "aria-label": "Chytré rozdělení" }) as HTMLInputElement;
    cb.checked = !!sp.on;
    cb.onchange = () => send(cb.checked);
    return h("div", { class: "bp-detail bp-split" },
      h("label", { class: "row bp-only" }, h("div", { class: "row-text" }, h("strong", {}, "Chytré rozdělení"),
        h("span", { class: "help" }, "Lehké otázky (pozdrav, rychlý dotaz) dělá jedna AI – třeba Ollama zdarma v PC. Těžké úkoly (plán, kód, analýza) jiná – třeba Claude.")),
        h("span", { class: "switch" }, cb, h("span"))),
      h("div", { class: "grid2" },
        pick("Lehké", sp.easy, "ollama", (v) => { easy = v; if (cb.checked) send(true); }),
        pick("Těžké", sp.hard, "anthropic", (v) => { hard = v; if (cb.checked) send(true); })));
  }

  client.on("brain_tiles", (m: any) => {
    const before = cur?.id;
    tiles = Array.isArray(m.tiles) ? m.tiles : [];
    cur = m.current || null;
    if (before !== cur?.id) { models = null; asked = ""; }
    paint();
  });
  client.on("brain_models", (m: any) => {
    models = { key: String(m.key || m.id || ""), models: Array.isArray(m.models) ? m.models : [], current: String(m.current || ""), error: String(m.error || ""),
      catalog: Array.isArray(m.catalog) ? m.catalog : [] };
    const t = tiles.find((x) => x.active);
    if (t && models.key !== t.id && m.id === t.id) models.key = t.id;
    paint();
  });
  client.on("brain_used", (m: any) => {
    if (Date.now() - mine > 4000) return;
    mine = 0;
    for (const n of (m.notes || []) as string[]) toast(n, "info", 5000);
  });
  client.on("brain_key_result", () => window.setTimeout(refresh, 300));
  client.on("local_pull_progress", (m: any) => {
    if (!pull || m.name !== pull.name) return;
    if (m.error) pull.error = String(m.error);
    else if (m.cancelled) pull = null;
    else if (m.done) {
      const { name, key } = pull;
      pull = null;
      models = null; asked = "";
      mine = Date.now();
      client.send("brain_use", { key, model: name });
      toast(`${name} je stažený – JARVIS na něj přepnul`, "ok", 3000);
    } else {
      pull.status = String(m.status || "");
      if (m.total) pull.pct = Math.round((Number(m.completed) || 0) / Number(m.total) * 100);
    }
    paint();
  });
  client.on("settings_changed", () => { if (el.isConnected) refresh(); });

  function refresh() { client.send("brain_tiles_get"); }
  return { el, refresh };
}
