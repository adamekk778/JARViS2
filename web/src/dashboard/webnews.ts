// Spec 2026-11-20 §5.7: "Co je nového" – the latest digest of the hourly study of the internet, by field.
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";

export function ago(ts: number): string {
  if (!ts) return "zatím nikdy";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "teď";
  if (s < 3600) return `před ${Math.floor(s / 60)} min`;
  if (s < 86400) return `před ${Math.floor(s / 3600)} h`;
  if (s < 2 * 86400) return "včera";
  return new Date(ts * 1000).toLocaleDateString("cs-CZ");
}

/** A digest as headings ("## Sport") and paragraphs. */
export function digestBody(text: string): HTMLElement {
  const box = h("div", { class: "wk-digest" });
  for (const line of (text || "").split("\n")) {
    const t = line.trim();
    if (!t) continue;
    box.append(t.startsWith("##") ? h("h3", {}, t.replace(/^#+\s*/, "")) : h("p", {}, t));
  }
  return box;
}

export function whatsNewCard(client: JarvisClient): { el: HTMLElement; refresh: () => void } {
  let data: any = null;
  let tab = "";
  const body = h("div", { class: "card sec-card" });
  const el = h("div", { class: "wk-news", hidden: true }, h("h2", { class: "group-label" }, "Co je nového"), body);
  const render = () => {
    const d = tab ? data?.digests?.[tab] : data?.digest;
    el.hidden = !data?.digest;
    if (!data?.digest) return;
    const tabs = Object.entries(data.digests || {}).filter(([, v]) => v);
    body.replaceChildren(
      h("div", { class: "btn-row" },
        h("button", { type: "button", class: `chip ${tab === "" ? "on" : ""}`, onclick: () => { tab = ""; render(); } }, "Vše"),
        ...tabs.map(([k]) => h("button", { type: "button", class: `chip ${tab === k ? "on" : ""}`, onclick: () => { tab = k; render(); } },
          data.categories?.[k] || k))),
      d ? digestBody(d.text) : h("p", { class: "muted" }, "Pro tenhle obor zatím přehled není."),
      h("div", { class: "btn-row" },
        h("span", { class: "muted" }, `Přehled ${ago(d?.fetched || data.digest.fetched)} · data z internetu`),
        h("button", { class: "btn ghost sm", type: "button", onclick: () => { client.send("webknow_study_now"); toast("Studuju, co je nového…", "ok"); } },
          icon("arrows-clockwise"), "Prostudovat teď")));
  };
  client.on("webknow", (m) => { data = m; render(); });
  return { el, refresh: () => client.send("webknow_get") };
}
