// Diagnostika (spec §8): what JARVIS itself costs, child processes, AI latency, voice, redacted log.
import { hero, HEROES } from "../shared/hero";
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";

export function buildDiagnostics(client: JarvisClient, ask: (text: string) => void) {
  let timer = 0;
  const stats = h("div", { class: "diag-stats" });
  const sys = h("div", { class: "diag-stats" });
  const kids = h("div", {});
  const ttft = h("div", {});
  const log = h("pre", { class: "diag-log" });
  const stat = (label: string, value: string, warn = false) => h("div", { class: `diag-stat ${warn ? "warn" : ""}` }, h("span", {}, label), h("b", {}, value));

  client.on("diagnostics", (m) => {
    stats.replaceChildren(stat("JARVIS – procesor", `${m.cpu_pct.toFixed(1)} %`, m.cpu_pct > 4), stat("JARVIS – paměť", `${Math.round(m.ram_mb)} MB`, m.ram_mb > 800),
      stat("Vlákna", String(m.threads)), stat("Zpoždění smyčky", `${m.loop_lag_ms} ms`, m.loop_lag_ms > 100),
      stat("Hlas", m.voice?.available ? (m.voice.listening ? "poslouchá" : "pozastaven") : "nedostupný"));
    kids.replaceChildren(...(m.children.length ? m.children.map((c: any) => h("div", { class: "row" }, h("span", {}, c.name), h("span", { class: "help" }, `${c.ram_mb} MB · PID ${c.pid}`)))
      : [h("p", { class: "help" }, "Žádné podprocesy (Ollama běží samostatně).")]));
    const t = Object.entries(m.ttft as Record<string, number[]>);
    ttft.replaceChildren(...(t.length ? t.map(([p, v]) => h("div", { class: "row" }, h("span", {}, p),
      h("span", { class: "help" }, `průměr ${Math.round(v.reduce((a, b) => a + b, 0) / v.length)} ms · posledních ${v.length}`)))
      : [h("p", { class: "help" }, "Zatím žádné odpovědi.")]));
    log.textContent = (m.log_tail || []).slice(-60).join("\n");
  });
  client.on("system", (m) => {
    const gpu = m.gpu ? `${m.gpu.name}${m.gpu.util != null ? ` · ${m.gpu.util} %` : ""}` : "n/a";
    sys.replaceChildren(stat("CPU", `${Math.round(m.cpu_percent)} %`), stat("RAM", `${Math.round(m.ram_percent)} %`),
      stat("GPU", gpu), stat("Síť", `↓ ${Math.round(m.net_down_kbps)} kB/s · ↑ ${Math.round(m.net_up_kbps)} kB/s`),
      ...(m.disks || []).map((d: any) => stat(`Disk ${d.mount}`, `${Math.round(d.used_pct)} % · volno ${d.free_gb} GB`, d.used_pct > 90)));
  });
  client.on("diagnostics_file", (m) => {
    const a = h("a", { href: client.url(m.attachment.url), download: m.attachment.name });
    a.click();
    toast("Diagnostika exportována (bez hesel a klíčů)", "ok");
  });

  const tick = () => { client.send("diagnostics_get"); client.send("system_get", { gpu: true }); };
  const el = h("section", { class: "diag-view" },
    hero(HEROES.diagnostics, "Diagnostika", "Jak se daří JARVISovi a tvému počítači.", [
      h("button", { class: "btn primary", type: "button", onclick: () => ask("Proč je můj počítač pomalý? Použij performance_report.") }, icon("gauge"), "Proč je PC pomalý?"),
      h("button", { class: "btn", type: "button", onclick: () => client.send("diagnostics_export") }, icon("file-zip"), "Exportovat")]),
    h("p", { class: "group-label" }, "JARVIS"), stats,
    h("p", { class: "group-label" }, "Počítač"), sys,
    h("div", { class: "grid2" },
      h("div", {}, h("p", { class: "group-label" }, "Podprocesy"), h("div", { class: "card" }, kids)),
      h("div", {}, h("p", { class: "group-label" }, "Rychlost AI (do prvního slova)"), h("div", { class: "card" }, ttft))),
    h("p", { class: "group-label" }, "Log (bez hesel a klíčů)"), h("div", { class: "card" }, log));
  return {
    el,
    show() { tick(); window.clearInterval(timer); timer = window.setInterval(() => { if (el.isConnected && !el.hidden) tick(); else window.clearInterval(timer); }, 2000); },
    hide() { window.clearInterval(timer); },
  };
}
