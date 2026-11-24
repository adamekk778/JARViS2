// Diagnostika (spec §8): what JARVIS itself costs, child processes, AI latency, voice, redacted log.
import { hero, HEROES } from "../shared/hero";
import { h, icon, loading, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import { openTrial } from "../shared/trial";

export function buildDiagnostics(client: JarvisClient, ask: (text: string) => void) {
  let timer = 0;
  const stats = h("div", { class: "diag-stats" });
  const sys = h("div", { class: "diag-stats" });
  const fx = h("div", { class: "diag-stats" });
  const speed = h("div", { class: "diag-stats" });
  // 3.17 Změřit rychlost: typical read-only requests + the voice there and back, on this PC with this AI
  const sc = h("div", { class: "card sc-list" }, h("p", { class: "help" }, "Projde 20 běžných dotazů, které nic nemění (čas, počasí, kalendář, výpočty…), a hlas tam a zpět. Trvá asi minutu; dotazy jdou na tvou AI jako obvykle, výsledek zůstane v počítači."));
  const scBtn = h("button", { class: "btn primary", type: "button", onclick: () => { scBtn.disabled = true; client.send("speedcheck_run" as any, { voice: true }); } }, icon("gauge"), "Změřit rychlost") as HTMLButtonElement;
  const ms = (v: any) => (v == null ? "–" : v >= 1000 ? `${(v / 1000).toFixed(1).replace(".", ",")} s` : `${v} ms`);
  client.on("speedcheck" as any, (m: any) => {
    if (m.running) { sc.replaceChildren(h("p", { class: "help" }, `Měřím… ${m.done || 0} z ${m.total || 20}${m.last ? ` · „${m.last.text}“ ${ms(m.last.total_ms)} (${m.last.how})` : ""}`)); return; }
    scBtn.disabled = false;
    if (m.error) { sc.replaceChildren(h("p", { class: "help" }, m.error)); return; }
    if (!m.report) return;
    const r = m.report;
    sc.replaceChildren(h("p", { class: "sc-sum ok" }, m.text),
      ...r.requests.map((q: any) => h("div", { class: "row" }, h("span", {}, q.text), h("span", { class: "help" }, `${q.how} · první slovo ${ms(q.first_word_ms)} · celé ${ms(q.total_ms)}`))),
      ...(r.voice || []).map((v: any) => h("div", { class: "row" }, h("span", {}, `🔊 ${v.text}`),
        h("span", { class: "help" }, v.error ? v.error : `hlas ${ms(v.tts_ms)} · rozpoznání ${ms(v.stt_ms)} · „${v.heard || ""}“ (${Math.round((v.match || 0) * 100)} %)`))));
  });
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
    // 3.15 each JARVIS window's frame rate and effects tier
    const NAMES: Record<string, string> = { hud: "Stark HUD", notch: "Notch", dashboard: "Aplikace", fullchat: "Chat", mobile: "Telefon",
      karaoke: "Karaoke", overlay: "Efekty na ploše", wallpaper: "Živá tapeta" };
    const TIERS: Record<string, string> = { ultra: "Ultra", high: "Vysoká", eco: "Úsporná", off: "bez efektů" };
    fx.replaceChildren(...((m.fx || []) as any[]).map((f) => stat(`${NAMES[f.page] || f.page} – ${TIERS[f.tier] || "?"}`, `${f.fps} FPS`, f.fps < 45)));
    if (!(m.fx || []).length) fx.replaceChildren(h("p", { class: "help" }, "Otevři HUD nebo notch – do půl minuty tu uvidíš jejich snímky za sekundu."));
    // 3.16 how fast JARVIS answers: each step (median of the last answers) and how often the tool was there at once
    const L = m.latency || {};
    const v = L.voice || {}, all = L.stages || {};
    const ms = (x: any) => (x ? (x.median >= 1000 ? `${(x.median / 1000).toFixed(1).replace(".", ",")} s` : `${x.median} ms`) : "–");
    const cells = [
      stat("Přepis řeči (hlas)", ms(v.stt), (v.stt?.median || 0) > 1200),
      stat("První slovo AI (hlas)", ms(v.first_token), (v.first_token?.median || 0) > 2500),
      stat("První zvuk (hlas)", ms(v.first_audio), (v.first_audio?.median || 0) > 3000),
      stat("První slovo AI (psaní)", ms(all.first_token), (all.first_token?.median || 0) > 2500),
    ];
    if (L.first_try != null) cells.push(stat("Nástroj trefen napoprvé", `${L.first_try} %`, L.first_try < 85));
    if (L.n) cells.push(stat("Odpovědí bez AI (okamžité)", `${L.instant || 0} z ${L.n}`), stat("S katalogem nástrojů", `${L.catalog || 0} z ${L.n}`));
    speed.replaceChildren(...(L.n ? cells : [h("p", { class: "help" }, "Zatím žádné odpovědi – po pár otázkách tu uvidíš, kolik trvá každý krok.")]));
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
  const health = h("div", { class: "card qh" }, loading());
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

  // 3.14 Úplně offline (návrh 31): speech recognition, AI and voice on this PC – sizes first, one click, then a test
  const offline = h("div", { class: "card qh" }, loading());
  const offlineLog = h("p", { class: "help" });
  client.on("offline_pack_progress", (m: any) => { offlineLog.textContent = m.text; });
  client.on("offline_pack", (m: any) => {
    offlineLog.textContent = (m.errors || []).join(" ");
    offline.replaceChildren(
      h("p", { class: "help" }, m.ready ? "Všechno potřebné pro práci bez internetu je v tomhle PC." :
        `Pro práci úplně bez internetu chybí ${m.parts.filter((p: any) => !p.ready).length} část(i) – ke stažení ${m.download_gb} GB.`),
      ...m.parts.map((p: any) => h("div", { class: `row ${p.ready ? "" : "warn"}` }, h("span", {}, icon(p.ready ? "check-circle" : "download-simple"), " ", p.name),
        h("span", { class: "help" }, p.ready ? `připraveno · ${p.note}` : `${p.size_gb} GB · ${p.note}`))),
      h("div", { class: "btn-row" },
        m.ready ? null : h("button", { class: "btn primary", type: "button", onclick: () => {
          if (!window.confirm(`Stáhnout ${m.download_gb} GB pro práci bez internetu?`)) return;
          offlineLog.textContent = "Připravuju…"; client.send("offline_pack_prepare", { switch: false });
        } }, icon("download-simple"), "Připravit vše offline"),
        h("button", { class: "btn", type: "button", onclick: () => { offlineLog.textContent = "Zkouším hlas → rozpoznání → AI…"; client.send("offline_pack_test"); } }, icon("play"), "Vyzkoušet"),
        m.ready && !m.offline_only ? h("button", { class: "btn", type: "button", onclick: () => client.send("offline_pack_prepare", { switch: true }) }, icon("wifi-slash"), "Používat jen offline") : null),
      offlineLog);
  });
  client.on("offline_pack_test_result", (m: any) => {
    offlineLog.replaceChildren(...(m.items || []).map((i: any) => h("span", { class: "row" }, icon(i.ok === false ? "x-circle" : i.ok ? "check-circle" : "minus-circle"), " ", i.detail)));
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
    h("p", { class: "group-label" }, "Úplně offline"), offline,
    h("p", { class: "group-label" }, "JARVIS"), stats,
    h("p", { class: "group-label" }, "Počítač"), sys,
    h("p", { class: "group-label" }, "Rychlost odpovědí (střed posledních 60)"), speed,
    h("div", { class: "btn-row" }, scBtn), sc,
    h("p", { class: "group-label" }, "Animace (snímky za sekundu)"), fx,
    h("div", { class: "grid2" },
      h("div", {}, h("p", { class: "group-label" }, "Podprocesy"), h("div", { class: "card" }, kids)),
      h("div", {}, h("p", { class: "group-label" }, "Rychlost AI (do prvního slova)"), h("div", { class: "card" }, ttft))),
    h("p", { class: "group-label" }, "Log (bez hesel a klíčů)"), h("div", { class: "card" }, log));
  return {
    el,
    show() { tick(); client.send("quality_get"); client.send("offline_pack_get"); window.clearInterval(timer); timer = window.setInterval(() => { if (el.isConnected && !el.hidden) tick(); else window.clearInterval(timer); }, 2000); },
    hide() { window.clearInterval(timer); },
  };
}
