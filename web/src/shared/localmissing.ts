// "Offline model is not downloaded" card (spec §5.4): shown in the notch panel and the dashboard until it is pulled.
import { h, icon } from "./dom";
import type { JarvisClient } from "./ws";

export function missingModelCard(client: JarvisClient, cls = "") {
  let missing: { name: string; size_gb?: number | null } | null = null;
  let progress: any = null;
  const el = h("div", { class: `missing-model ${cls}`, hidden: true, role: "status" });
  const render = () => {
    el.hidden = !missing;
    if (!missing) return;
    const size = missing.size_gb ? ` (${String(missing.size_gb).replace(".", ",")} GB)` : "";
    const pct = progress?.total ? Math.round((progress.completed || 0) / progress.total * 100) : null;
    const busy = progress && !progress.done && !progress.error && !progress.cancelled;
    el.replaceChildren(icon("cloud-slash"),
      h("div", { class: "mm-text" }, h("strong", {}, "Offline mozek není stažený"),
        h("span", {}, progress?.error ? `Stahování selhalo: ${progress.error}` : `Pro práci bez internetu stáhni ${missing.name}${size}.`)),
      busy
        ? h("span", { class: "mm-progress" }, h("b", { style: { width: `${pct ?? 3}%` } }), h("em", {}, pct != null ? `${pct} %` : "…"))
        : h("button", { class: "btn sm primary", type: "button", onclick: () => {
            if (!confirm(`Stáhnout ${missing!.name}${size}?`)) return;
            progress = { completed: 0 };
            client.send("local_pull", { name: missing!.name });
            render();
          } }, icon("download-simple"), "Stáhnout"));
  };
  client.on("welcome", (m) => { missing = m.local_missing || null; render(); });
  client.on("local_model_missing", (m) => { missing = { name: m.name, size_gb: m.size_gb }; render(); });
  client.on("local_info", (m) => { missing = m.missing || null; render(); });
  client.on("local_pull_progress", (m) => {
    if (!missing || m.name !== missing.name) return;
    progress = m;
    if (m.done) missing = null;
    render();
  });
  return el;
}
