// 3.14 Kdo odpovídá: the AIs as tiles – a click makes that one answer from now on; under the chosen one its models,
// switchable right here (Ollama: the models downloaded on this PC; Claude: Opus, Sonnet, Haiku, Fable). Claude without
// a key shows the key field right in its tile. The same picker is in Nastavení → Mozek and behind the AI chip in the chat.
import "./brainpicker.css";
import { brandEl, brandOf } from "./brands";
import { h, icon, toast } from "./dom";
import type { JarvisClient } from "./ws";

type Tile = { preset: string; id: string; label: string; local: boolean; added: boolean; enabled: boolean; model: string;
  key: boolean; needs_key: boolean; active: boolean };
type Current = { id: string; preset: string; label: string; model: string; only: boolean };
type Model = { id: string; label: string; note: string };

const SHORT: Record<string, string> = { anthropic: "Claude", ollama: "Ollama (v PC)", groq: "Groq", gemini: "Gemini", openai: "ChatGPT",
  openrouter: "OpenRouter", omniroute: "OmniRoute", lmstudio: "LM Studio (v PC)" };
const KEY_HELP: Record<string, string> = {
  anthropic: "Klíč z console.anthropic.com → API Keys (začíná sk-ant-). Předplatné Claude Pro/Max klíč nedává.",
  groq: "Zdarma na console.groq.com (začíná gsk_).", gemini: "Zdarma na aistudio.google.com.", openai: "Z platform.openai.com.",
  openrouter: "Z openrouter.ai/keys (začíná sk-or-).",
};

export function createBrainPicker(client: JarvisClient, opts: { compact?: boolean } = {}) {
  let tiles: Tile[] = [], cur: Current | null = null;
  let models: { key: string; models: Model[]; current: string; error: string } | null = null;
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
    return h("label", { class: "bp-models" }, h("span", {}, "Model"), sel,
      t.preset === "ollama" ? h("button", { class: "icon-btn sm", type: "button", title: "Načíst znovu", "aria-label": "Načíst modely znovu",
        onclick: () => { asked = ""; models = null; paint(); } }, icon("arrows-clockwise")) : "");
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
        (() => {
          const cb = h("input", { type: "checkbox", role: "switch", "aria-label": "Jen tento mozek" }) as HTMLInputElement;
          cb.checked = !!cur?.only;
          cb.onchange = () => client.send("brain_use", { key: act.id, only: cb.checked });
          return h("label", { class: "row bp-only" }, h("div", { class: "row-text" }, h("strong", {}, "Jen tento mozek"),
            h("span", { class: "help" }, cb.checked ? "Ostatní AI se nepoužijí ani jako záloha." : "Když tahle AI nepůjde, zkusí JARVIS další v pořadí.")),
            h("span", { class: "switch" }, cb, h("span")));
        })()));
    }
    el.replaceChildren(...parts);
  }

  client.on("brain_tiles", (m: any) => {
    const before = cur?.id;
    tiles = Array.isArray(m.tiles) ? m.tiles : [];
    cur = m.current || null;
    if (before !== cur?.id) { models = null; asked = ""; }
    paint();
  });
  client.on("brain_models", (m: any) => {
    models = { key: String(m.key || m.id || ""), models: Array.isArray(m.models) ? m.models : [], current: String(m.current || ""), error: String(m.error || "") };
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
  client.on("settings_changed", () => { if (el.isConnected) refresh(); });

  function refresh() { client.send("brain_tiles_get"); }
  return { el, refresh };
}
