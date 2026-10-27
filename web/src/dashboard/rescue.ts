// Dashboard → Záchrana a výkon (OMEGA §25–§27, §32, §53): read-only diagnostics of the PC by area with a verified
// report, what slows the PC right now, a repeatable benchmark with history, the network check and the security center
// (link, downloaded file, leaked keys, copy check, password leak, system files, restore point). Nothing here changes
// the PC except the restore point, which asks first.
import { hero, HEROES } from "../shared/hero";
import { fmtSize, h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";
import { pcExplorer } from "../shared/pcexplorer";

const AREAS: [string, string, string][] = [
  ["crashes", "Pády a modré obrazovky", "warning-octagon"], ["drivers", "Ovladače", "cpu"], ["apps", "Padající aplikace", "app-window"],
  ["boot", "Pomalý start", "timer"], ["usb", "USB a disky", "usb"], ["disks", "Zdraví disků", "hard-drives"],
  ["services", "Služby", "gear-six"], ["security", "Viry a bezpečnost", "shield-warning"], ["network", "Síť", "wifi-high"],
  ["restore", "Body obnovy a RAM", "clock-counter-clockwise"],
];
const LVL: Record<string, [string, string]> = { bad: ["bad", "problém"], warn: ["warn", "pozor"], info: ["info", "info"], ok: ["ok", "v pořádku"] };

const finding = (f: any) => h("li", { class: `rs-f ${f.level}` },
  h("span", { class: `rs-badge ${LVL[f.level]?.[0] || "info"}` }, LVL[f.level]?.[1] || f.level),
  h("div", {}, h("p", {}, f.text), f.fix ? h("p", { class: "rs-fix" }, `Co udělat: ${f.fix}`) : "",
    f.source ? h("p", { class: "muted rs-src" }, `Zdroj: ${f.source}`) : ""));

const busy = (b: HTMLButtonElement, on: boolean, text?: string) => {
  b.disabled = on;
  if (text) b.lastChild!.textContent = on ? "Pracuju…" : text;
};

export function buildRescue(client: JarvisClient) {
  // ---------------------------------------------------------------- diagnostics
  const picked = new Set<string>(["crashes", "drivers", "usb", "disks"]);
  const chips = h("div", { class: "rs-chips", role: "group", "aria-label": "Oblasti diagnostiky" }, ...AREAS.map(([id, label, ic]) => {
    const b = h("button", { class: `rs-chip${picked.has(id) ? " on" : ""}`, type: "button", "aria-pressed": String(picked.has(id)) }, icon(ic), label) as HTMLButtonElement;
    b.onclick = () => { picked.has(id) ? picked.delete(id) : picked.add(id); b.classList.toggle("on"); b.setAttribute("aria-pressed", String(picked.has(id))); };
    return b;
  }));
  const runBtn = h("button", { class: "btn primary", type: "button" }, icon("stethoscope"), "Spustit diagnostiku") as HTMLButtonElement;
  const allBtn = h("button", { class: "btn", type: "button" }, icon("list-checks"), "Všechno") as HTMLButtonElement;
  const diagOut = h("div", { class: "rs-out" }, h("p", { class: "muted" }, "Vyber, co zlobí, a spusť diagnostiku. Jen čte – nic nemění."));
  const run = (areas: string[]) => {
    if (!areas.length) { toast("Vyber aspoň jednu oblast", "error"); return; }
    busy(runBtn, true, "Spustit diagnostiku"); allBtn.disabled = true;
    diagOut.replaceChildren(h("p", { class: "muted" }, "Čtu systémové logy a stav zařízení… (do minuty)"));
    client.send("rescue_run", { area: areas.join(",") });
  };
  runBtn.onclick = () => run([...picked]);
  allBtn.onclick = () => run(AREAS.map((a) => a[0]));
  client.on("rescue", (m) => {
    busy(runBtn, false, "Spustit diagnostiku"); allBtn.disabled = false;
    const top: any[] = m.top || [];
    diagOut.replaceChildren(
      h("div", { class: "rs-summary" },
        h("strong", {}, top.length ? `${top.length} ${top.length === 1 ? "věc chce" : "věci chtějí"} pozornost` : "Nenašel jsem žádný problém"),
        h("span", { class: "muted" }, m.verified ? "report ověřen (otisk SHA-256)" : "report se nepodařilo ověřit"),
        client.local ? h("button", { class: "btn sm", type: "button", onclick: () => client.send("rescue_open", { path: m.path }) }, icon("arrow-square-out"), "Otevřít report") : ""),
      ...(m.results || []).map((r: any) => h("details", { class: "rs-area", open: r.findings.some((f: any) => f.level === "bad" || f.level === "warn") },
        h("summary", {}, h("span", {}, r.title), h("span", { class: "muted" }, r.ok ? `${r.ms} ms` : "nezměřeno")),
        h("ul", { class: "rs-list" }, ...r.findings.map(finding)))));
  });

  // ---------------------------------------------------------------- performance
  const perfOut = h("div", { class: "rs-out" }, h("p", { class: "muted" }, "Změřím, co právě brzdí počítač (3 s)."));
  const benchOut = h("div", { class: "rs-out" });
  const histBox = h("div", { class: "rs-hist", "aria-label": "Vytížení za 24 hodin" });
  const perfBtn = h("button", { class: "btn primary", type: "button" }, icon("gauge"), "Co brzdí PC?") as HTMLButtonElement;
  const benchLabel = h("input", { class: "input sm", placeholder: "popisek, např. po úklidu", "aria-label": "Popisek měření" }) as HTMLInputElement;
  const benchBtn = h("button", { class: "btn", type: "button" }, icon("timer"), "Test výkonu (6 s)") as HTMLButtonElement;
  perfBtn.onclick = () => { busy(perfBtn, true, "Co brzdí PC?"); client.send("perf_get") };
  benchBtn.onclick = () => { busy(benchBtn, true, "Test výkonu (6 s)"); client.send("perf_bench", { label: benchLabel.value.trim() }); };
  const renderHist = (rows: any[]) => {
    if (!rows?.length) { histBox.replaceChildren(h("p", { class: "muted" }, "Historie se plní každých 5 minut.")); return; }
    histBox.replaceChildren(...rows.slice(-96).map((r) => h("i", { title: `${new Date(r.ts * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })}: CPU ${Math.round(r.cpu ?? 0)} %, RAM ${Math.round(r.ram ?? 0)} %`,
      style: { height: `${Math.max(3, r.cpu ?? 0)}%` } })));
  };
  const renderBenches = (bs: any[], cmp: string[] = []) => {
    benchOut.replaceChildren(
      cmp.length ? h("p", {}, h("strong", {}, "Proti minule: "), cmp.join(" · ")) : "",
      bs?.length ? h("table", { class: "task-actions" }, h("thead", {}, h("tr", {}, ...["Kdy", "Popisek", "Procesor", "Paměť GB/s", "Zápis MB/s", "Čtení MB/s"].map((x) => h("th", {}, x)))),
        h("tbody", {}, ...bs.map((b) => h("tr", {}, h("td", {}, new Date(b.ts * 1000).toLocaleString("cs-CZ")), h("td", {}, b.label || "—"),
          h("td", {}, String(b.cpu_score)), h("td", {}, String(b.ram_gb_s)), h("td", {}, String(b.disk_write_mb_s)), h("td", {}, String(b.disk_read_mb_s)))))) : "");
  };
  client.on("perf", (m) => {
    busy(perfBtn, false, "Co brzdí PC?"); busy(benchBtn, false, "Test výkonu (6 s)");
    renderHist(m.history);
    renderBenches(m.benches, m.compare);
    if (m.sample) {
      const s = m.sample, l = m.latency || {};
      perfOut.replaceChildren(
        h("div", { class: "rs-stats" },
          ...[["Procesor", `${s.cpu} %`], ["Paměť", `${s.ram_pct} %`], ["Grafika", typeof s.gpu?.gpu === "number" ? `${s.gpu.gpu} %` : "—"],
            ["Odezva", l.avg_ms != null ? `${l.avg_ms} ms` : "—"], ["Kolísání", l.jitter_ms != null ? `${l.jitter_ms} ms` : "—"], ["Ztráta", l.loss_pct != null ? `${l.loss_pct} %` : "—"]]
            .map(([k, v]) => h("div", {}, h("strong", {}, v), h("span", { class: "muted" }, k)))),
        h("ul", { class: "rs-list" }, ...(m.findings || []).map(finding)),
        (s.top_cpu || []).length ? h("p", { class: "muted" }, "Nejnáročnější: " + s.top_cpu.slice(0, 5).map((p: any) => `${p.name} ${p.cpu} %`).join(", ")) : "");
    }
  });

  // ---------------------------------------------------------------- network
  const target = h("input", { class: "input", placeholder: "web nebo doména (volitelné), např. seznam.cz", "aria-label": "Cíl" }) as HTMLInputElement;
  const route = h("input", { type: "checkbox", "aria-label": "Trasa" }) as HTMLInputElement;
  const netBtn = h("button", { class: "btn primary", type: "button" }, icon("wifi-high"), "Zkontrolovat síť") as HTMLButtonElement;
  const netOut = h("div", { class: "rs-out" });
  netBtn.onclick = () => { busy(netBtn, true, "Zkontrolovat síť"); client.send("netcheck", { target: target.value.trim(), route: route.checked }); };
  client.on("netcheck", (m) => {
    busy(netBtn, false, "Zkontrolovat síť");
    const d = m.data || {};
    netOut.replaceChildren(h("p", {}, m.summary),
      d.trace?.length ? h("ol", { class: "rs-trace" }, ...d.trace.map((x: any) => h("li", {}, `${x.ip}${x.ms != null ? ` · ${x.ms} ms` : ""}`))) : "");
  });

  // ---------------------------------------------------------------- security center
  const secOut = h("div", { class: "rs-out" });
  const field = (ph: string, label: string, type = "text") => h("input", { class: "input", type, placeholder: ph, "aria-label": label, autocomplete: "off" }) as HTMLInputElement;
  const link = field("https://…", "Odkaz");
  const file = field("C:\\Users\\…\\Downloads\\soubor.exe", "Soubor");
  const folder = field("C:\\projekty\\muj-web", "Složka projektu");
  const src = field("originál, např. D:\\Fotky", "Originál"), dst = field("kopie, např. E:\\Záloha\\Fotky", "Kopie");
  const pwd = field("heslo (neodejde ani do AI, ani na internet)", "Heslo", "password");
  const sec = (kind: string, value = "", extra: any = {}) => {
    secOut.replaceChildren(h("p", { class: "muted" }, "Kontroluju…"));
    client.send("seccheck", { kind, value, ...extra });
  };
  const row = (inp: HTMLElement, label: string, ic: string, go: () => void) =>
    h("div", { class: "list-add" }, inp, h("button", { class: "btn", type: "button", onclick: go }, icon(ic), label));
  client.on("seccheck", (m) => {
    if (m.error) { secOut.replaceChildren(h("p", { class: "rs-f bad" }, m.error)); return; }
    const r = m.result || {};
    const out: (HTMLElement | string)[] = [];
    if (m.kind === "link") out.push(finding({ level: r.level, text: `${r.host}: ${r.level === "ok" ? "nevidím nic podezřelého" : r.reasons.join("; ")}`, source: "kontrola bez otevření odkazu" }));
    if (m.kind === "file") {
      if (r.error) out.push(finding({ level: "info", text: r.error }));
      else {
        out.push(finding({ level: r.level, text: `${r.type}${r.origin ? `, staženo z ${r.origin}` : ""}${r.reasons.length ? ` – ${r.reasons.join("; ")}` : ""}`, source: `SHA-256 ${r.sha256}` }));
        if (r.defender) out.push(finding(r.defender.clean ? { level: "ok", text: "Microsoft Defender nic nenašel." }
          : r.defender.threats?.length ? { level: "bad", text: `Defender našel: ${r.defender.threats.join(", ")}` } : { level: "info", text: `Defender: ${r.defender.error || "bez výsledku"}` }));
      }
    }
    if (m.kind === "secrets") out.push(r.hits.length ? h("ul", { class: "rs-list" }, ...r.hits.slice(0, 50).map((x: any) => finding({ level: "bad", text: `${x.file}:${x.line} – ${x.kind} (${x.preview})`, fix: "Klíč zneplatni u poskytovatele a přesuň do proměnné prostředí." })))
      : finding({ level: "ok", text: "Žádné klíče ani hesla v kódu." }));
    if (m.kind === "copy") out.push(finding(!r.missing?.length && !r.different?.length ? { level: "ok", text: `Kopie je v pořádku: ${r.files} souborů shodných.` }
      : { level: "bad", text: `Chybí ${r.missing.length}, liší se ${r.different.length} (např. ${[...r.missing, ...r.different].slice(0, 5).join(", ")}).` }));
    if (m.kind === "pwned") out.push(finding(r.count ? { level: "bad", text: `Tohle heslo se objevilo v únicích ${r.count.toLocaleString("cs-CZ")}×.`, fix: "Změň ho všude, kde ho používáš." }
      : { level: "ok", text: "V známých únicích jsem ho nenašel." }));
    if (m.kind === "rescue_plan") out.push(h("ol", { class: "rs-trace" }, ...r.folders.map((f: any) => h("li", {}, `${f.folder} – ${f.files} souborů, ${fmtSize(f.bytes)}`))),
      h("p", { class: "help" }, "Kopíruj v tomhle pořadí na jiný disk. Nic neformátuj a pak kopii ověř tady nahoře."));
    if (m.kind === "integrity") out.push(h("ul", { class: "rs-list" }, ...r.findings.map(finding)));
    if (m.kind === "restore_point") out.push(finding({ level: r.ok ? "ok" : "info", text: r.text }));
    secOut.replaceChildren(...out);
  });
  const secBox = h("div", { class: "card sec-card" },
    row(link, "Odkaz", "link", () => link.value.trim() && sec("link", link.value.trim())),
    row(file, "Soubor", "file-magnifying-glass", () => file.value.trim() && sec("file", file.value.trim(), { scan: true })),
    row(folder, "Klíče v kódu", "key", () => folder.value.trim() && sec("secrets", folder.value.trim())),
    h("div", { class: "list-add" }, src, dst, h("button", { class: "btn", type: "button", onclick: () => src.value.trim() && sec("copy", src.value.trim(), { value2: dst.value.trim() }) }, icon("copy"), "Ověřit kopii")),
    row(pwd, "Uniklo heslo?", "password", () => { if (pwd.value) { sec("pwned", pwd.value); pwd.value = ""; } }),
    h("p", { class: "help" }, "U hesla odejde jen prvních 5 znaků jeho otisku (služba Have I Been Pwned) – heslo samo nikam."),
    h("div", { class: "btn-row" },
      h("button", { class: "btn", type: "button", onclick: () => sec("rescue_plan") }, icon("lifebuoy"), "Disk umírá – co zachránit?"),
      h("button", { class: "btn", type: "button", onclick: () => sec("integrity") }, icon("check-square-offset"), "Systémové soubory (jen kontrola)"),
      h("button", { class: "btn", type: "button", onclick: () => { if (confirm("Vytvořit bod obnovy systému? (potřebuje práva správce)")) sec("restore_point", "JARVIS"); } }, icon("clock-counter-clockwise"), "Vytvořit bod obnovy")),
    secOut);

  const pcx = pcExplorer(client);            // OMEGA 193: the parts of the PC in 3D
  const el = h("section", { class: "tasks-view rescue-view" },
    hero(HEROES.rescue, "Záchrana a výkon", "Proč PC padá, co ho brzdí, jestli je disk v pořádku a jestli je soubor nebo odkaz bezpečný. Jen čte a radí – měnit budeš ty.", []),
    pcx.el,
    h("h2", { class: "group-label" }, "Diagnostika"), h("div", { class: "card sec-card" }, chips, h("div", { class: "btn-row" }, runBtn, allBtn), diagOut),
    h("h2", { class: "group-label" }, "Výkon"), h("div", { class: "card sec-card" }, h("div", { class: "btn-row" }, perfBtn), perfOut,
      h("h4", {}, "Vytížení procesoru za 24 h"), histBox, h("h4", {}, "Test výkonu"), h("div", { class: "list-add" }, benchLabel, benchBtn), benchOut),
    h("h2", { class: "group-label" }, "Síť"), h("div", { class: "card sec-card" }, h("div", { class: "list-add" }, target, netBtn),
      h("label", { class: "rs-check" }, route, "i trasa k cíli (tracert, do 1 min)"), netOut),
    h("h2", { class: "group-label" }, "Bezpečnostní centrum"), secBox);
  let loaded = false;
  return { el, show: () => { pcx.refresh(); if (!loaded) { loaded = true; client.send("perf_get"); } } };
}
