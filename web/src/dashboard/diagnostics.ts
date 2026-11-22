// Diagnostika (spec §8): what JARVIS itself costs, child processes, AI latency, voice, redacted log.
import { hero, HEROES } from "../shared/hero";
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import { openTrial } from "../shared/trial";

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

  // 3.12 Kontrola funkcí: every part tried on this PC, what is wrong and what to do – in plain words
  const checks = h("div", { class: "card sc-list" }, h("p", { class: "help" }, "Klikni na Zkontrolovat – za pár sekund uvidíš, co funguje a co ne (a co s tím)."));
  client.on("selfcheck", (m) => {
    if (m.running) { checks.replaceChildren(h("p", { class: "help" }, "Kontroluji… (asi 10–20 s; mikrofon se na půl sekundy otevře)")); return; }
    const items: any[] = m.items || [];
    const bad = items.filter((i) => i.ok === false).length;
    // one button fixes the network for JARVIS (home network, firewall in and out) – shown once, at the first such item
    const netFixKey = items.find((i) => i.ok === false && ["internet", "profile", "firewall"].includes(i.key))?.key;
    checks.replaceChildren(
      h("p", { class: `sc-sum ${bad ? "bad" : "ok"}` }, bad ? `${bad} ${bad === 1 ? "věc nefunguje" : bad < 5 ? "věci nefungují" : "věcí nefunguje"} – postup je u každé níže.` : "Všechno funguje."),
      ...items.map((i) => h("div", { class: `sc-item ${i.ok === false ? "bad" : i.ok ? "ok" : "na"}` },
        icon(i.ok === false ? "x-circle" : i.ok ? "check-circle" : "minus-circle", "ph-fill"),
        h("div", { class: "sc-text" }, h("strong", {}, i.name), h("span", {}, i.detail), i.fix ? h("em", {}, i.fix) : null,
          i.key === netFixKey ? h("button", { class: "btn primary sm", type: "button", onclick: () => {
            client.send("firewall_allow");
            toast("Windows se teď zeptá, jestli JARVIS smí změnit nastavení sítě – potvrď Ano. Za chvíli zkontroluju znovu.", "info");
            window.setTimeout(runCheck, 20000);
          } }, icon("shield-check"), "Opravit síť pro JARVIS") : null))));
  });
  const runCheck = () => client.send("selfcheck_run");
  // 3.12 a summary to paste when asking for help – what works, the AIs and services; never a key or password
  client.on("diagnostics_summary", async (m: any) => {
    const text = String(m.text || "");
    try { await navigator.clipboard.writeText(text); toast("Diagnostika je ve schránce – vlož ji (Ctrl+V) do zprávy.", "ok", 6000); }
    catch {
      const ta = h("textarea", { class: "diag-copy", readonly: true }, text) as HTMLTextAreaElement;
      checks.prepend(ta); ta.select(); toast("Označeno – zkopíruj Ctrl+C.", "info");
    }
  });

  // 3.14 Zdraví JARVISe (návrhy 12, 13, 16, 17, 20): failing tools, AI speed, voice delay, versions, battery
  const health = h("div", { class: "card qh" }, h("p", { class: "help" }, "Načítám…"));
  const pct = (x: number) => `${Math.round(x * 1000) / 10} %`;
  client.on("quality", (m: any) => {
    const v = m.voice || {};
    const verdict = m.verdict ? `Nová verze je ${m.verdict} než předchozí (podle chybovosti nástrojů).` : "Na porovnání verzí je zatím málo dat.";
    const row = (a: string, b: string, warn = false) => h("div", { class: `row ${warn ? "warn" : ""}` }, h("span", {}, a), h("span", { class: "help" }, b));
    const ch = h("select", { onchange: (e: Event) => client.send("update_channel_set", { channel: (e.target as HTMLSelectElement).value }) },
      h("option", { value: "stable", selected: m.channel !== "beta" }, "Stabilní verze"),
      h("option", { value: "beta", selected: m.channel === "beta" }, "Beta (novinky dřív, víc chyb)"));
    const auto = h("input", { type: "checkbox", checked: !!m.auto_rollback,
      onchange: (e: Event) => client.send("settings_set", { patch: { general: { auto_rollback: (e.target as HTMLInputElement).checked } } }) });
    health.replaceChildren(
      h("div", { class: "diag-stats" },
        stat("Hlas – do prvního slova", v.median_ms != null ? `${v.median_ms} ms` : "zatím neměřeno", v.median_ms != null && v.median_ms > (v.target_ms || 1200)),
        stat("Chyby v logu (7 dní)", String(m.errors ?? 0), (m.errors ?? 0) > 20),
        stat("JARVIS z procesoru", m.power?.cpu_share != null ? `${m.power.cpu_share} %` : "měřím…"),
        stat("JARVIS z baterie", m.power?.jarvis_per_h != null ? `${m.power.jarvis_per_h} % za hodinu` : "jen na baterii")),
      h("p", { class: "help" }, verdict),
      ...(m.versions || []).map((x: any) => row(`Verze ${x.version}`, `${x.calls} akcí · chybovost ${pct(x.rate)} · od ${x.since}`)),
      h("p", { class: "group-label" }, "Nástroje, které nejčastěji selhávají"),
      ...((m.failing || []).length ? m.failing.map((t: any) => row(t.tool, `${t.fails} z ${t.calls} selhalo · ${t.avg_ms} ms`, true))
        : [h("p", { class: "help" }, "Žádný nástroj neselhává častěji než ve 30 % případů.")]),
      h("p", { class: "group-label" }, "Rychlost AI (medián do prvního slova)"),
      ...((m.models || []).length ? m.models.map((x: any) => row(x.provider, `${x.median_ms} ms · ${x.answers} odpovědí${x.error ? " · " + x.error : ""}`, !!x.error))
        : [h("p", { class: "help" }, "Zatím žádné odpovědi.")]),
      h("div", { class: "row" }, h("span", {}, "Aktualizace"), ch),
      h("label", { class: "row" }, h("span", {}, "Když po aktualizaci přestane fungovat notch nebo hlas, vrátit se samo na předchozí verzi"), auto),
      h("div", { class: "btn-row" },
        h("button", { class: "btn", type: "button", onclick: () => {
          const text = window.prompt("Co se stalo? (napiš pár slov – diagnostiku bez hesel a klíčů přidám sám)");
          if (text === null) return;                                    // Zrušit
          client.send("bug_report", { title: text.slice(0, 80), text });
        } }, icon("bug"), "Nahlásit chybu"),
        m.previous && m.previous !== m.current ? h("button", { class: "btn", type: "button", onclick: () => {
          if (window.confirm(`Nainstalovat zpět verzi ${m.previous}? JARVIS se na chvíli zavře.`)) client.send("rollback_now", { to: m.previous });
        } }, icon("arrow-counter-clockwise"), `Vrátit verzi ${m.previous}`) : null));
  });
  client.on("bug_report_url", (m: any) => {
    if (!m.url) { toast("Adresu pro hlášení neznám (aktualizace nejsou z GitHubu).", "error"); return; }
    const a = h("a", { href: m.url, target: "_blank", rel: "noopener" }); a.click();
    toast("Otevírám formulář na GitHubu – zkontroluj text a klikni Submit.", "ok", 6000);
  });

  const tick = () => { client.send("diagnostics_get"); client.send("system_get", { gpu: true }); };
  const el = h("section", { class: "diag-view" },
    hero(HEROES.diagnostics, "Diagnostika", "Jak se daří JARVISovi a tvému počítači.", [
      h("button", { class: "btn primary", type: "button", onclick: () => ask("Proč je můj počítač pomalý? Použij performance_report.") }, icon("gauge"), "Proč je PC pomalý?"),
      h("button", { class: "btn", type: "button", onclick: () => openTrial(client) }, icon("play-circle"), "Vyzkoušet novinky"),
      h("button", { class: "btn", type: "button", onclick: () => client.send("diagnostics_summary") }, icon("copy"), "Zkopírovat diagnostiku"),
      h("button", { class: "btn", type: "button", onclick: () => client.send("diagnostics_export") }, icon("file-zip"), "Exportovat")]),
    h("div", { class: "sc-head" }, h("p", { class: "group-label" }, "Kontrola funkcí"),
      h("button", { class: "btn primary", type: "button", onclick: runCheck }, icon("stethoscope"), "Zkontrolovat")), checks,
    h("p", { class: "group-label" }, "Zdraví JARVISe"), health,
    h("p", { class: "group-label" }, "JARVIS"), stats,
    h("p", { class: "group-label" }, "Počítač"), sys,
    h("div", { class: "grid2" },
      h("div", {}, h("p", { class: "group-label" }, "Podprocesy"), h("div", { class: "card" }, kids)),
      h("div", {}, h("p", { class: "group-label" }, "Rychlost AI (do prvního slova)"), h("div", { class: "card" }, ttft))),
    h("p", { class: "group-label" }, "Log (bez hesel a klíčů)"), h("div", { class: "card" }, log));
  return {
    el,
    show() { tick(); client.send("quality_get"); window.clearInterval(timer); timer = window.setInterval(() => { if (el.isConnected && !el.hidden) tick(); else window.clearInterval(timer); }, 2000); },
    hide() { window.clearInterval(timer); },
  };
}
