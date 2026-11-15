// 3.12 Přehled AI: every brain in your order – its logo, whether it has a key, whether its limit is used up right now
// (and for how long), % left today when known, the last test. One button tries them all at once.
import "./brains.css";
import { brandEl, brandOf } from "./brands";
import { h, icon } from "./dom";
import type { JarvisClient } from "./ws";

export interface BrainRow { id: string; preset: string; label: string; model: string; enabled: boolean; local: boolean; key: boolean;
  limited_s: number; left: number | null; error: string }
export interface BrainTest { ok: boolean; message: string; ms?: number; limit?: boolean }

const mins = (s: number) => (s >= 3600 ? `${Math.round(s / 3600)} h` : `${Math.max(1, Math.round(s / 60))} min`);

function status(b: BrainRow, t?: BrainTest): [string, string] {
  if (!b.enabled) return ["off", "vypnutá"];
  if (!b.key) return ["off", "chybí klíč"];
  if (t) {
    if (t.ok && !t.limit) return ["ok", `funguje${t.ms ? ` · ${(t.ms / 1000).toFixed(1).replace(".", ",")} s` : ""}`];
    if (t.limit) return ["wait", "limit vyčerpán – zkusí ji později"];
    return ["bad", t.message || "nefunguje"];
  }
  if (b.limited_s > 0) return ["wait", `limit vyčerpán · znovu za ${mins(b.limited_s)}`];
  if (b.left != null) return [b.left > 15 ? "ok" : "wait", `dnes zbývá ${Math.max(0, Math.round(b.left))} %`];
  return ["idle", b.local ? "v tomhle PC · bez limitu" : "připravená"];
}

export function brainsList(items: BrainRow[], tested: Record<string, BrainTest>, busy: boolean,
  onTest: () => void): HTMLElement {
  items = items.filter((b) => (b.preset !== "custom" && b.preset !== "omniroute") || b.key);   // a gateway you never set up: not shown
  const rows = items.map((b, i) => {
    const [cls, text] = status(b, tested[b.id]);
    const left = b.left == null ? (cls === "ok" ? 100 : cls === "wait" ? 4 : 0) : Math.max(2, Math.min(100, b.left));
    return h("div", { class: `br-row ${cls}` },
      h("span", { class: "br-n" }, String(i + 1)),
      h("span", { class: "br-logo" }, brandEl(brandOf(b.preset, ""))),
      h("div", { class: "br-txt" }, h("strong", {}, b.label), h("span", {}, text)),
      h("span", { class: "br-bar", title: text }, h("i", { style: { width: `${cls === "off" || cls === "bad" ? 0 : left}%` } })));
  });
  const working = items.filter((b) => {
    const t = tested[b.id];
    return b.enabled && b.key && (t ? t.ok && !t.limit : b.limited_s <= 0);
  }).length;
  return h("div", { class: "br" },
    h("div", { class: "br-head" },
      h("div", {}, h("strong", {}, `${working} z ${items.filter((b) => b.enabled && b.key).length} AI připraveno`),
        h("span", {}, "JARVIS je zkouší v tomhle pořadí; když jedné dojde limit, vezme další.")),
      h("button", { type: "button", class: "br-test", disabled: busy, onclick: onTest },
        icon(busy ? "circle-notch" : "lightning", "ph-bold"), busy ? "Zkouším…" : "Vyzkoušet všechny")),
    rows.length ? h("div", { class: "br-rows" }, ...rows) : h("p", { class: "br-empty" }, "Zatím žádná AI – vlož klíč v Nastavení → AI mozek."));
}

/** A self-updating panel: asks for the list, repaints on "brains". */
export function createBrainsPanel(client: JarvisClient) {
  let items: BrainRow[] = [], tested: Record<string, BrainTest> = {}, busy = false;
  const el = h("div", { class: "br-wrap" });
  const paint = () => el.replaceChildren(brainsList(items, tested, busy, () => {
    busy = true; paint(); client.send("brains_test_all");
  }));
  client.on("brains", (m: any) => {
    items = Array.isArray(m.items) ? m.items : [];
    if (m.tested && Object.keys(m.tested).length) { tested = m.tested; busy = false; }
    paint();
  });
  paint();
  return { el, refresh: () => client.send("brains_get") };
}
