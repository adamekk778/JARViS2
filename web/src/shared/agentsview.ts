// 3.14 Agenti (multitasking) – one view for the notch and the phone: ready-made teams, the monitors and who works on
// them, the play wallet of zkušební obchodování, every agent live (a watcher's values as a small chart), a message to
// a working agent, the AI use of a task, the results file, stop one or all.
import { h, icon, toast } from "./dom";
import type { JarvisClient } from "./ws";
import "./agents.css";

const KIND_ICON: Record<string, string> = { work: "brain", screen: "cursor-click", watch: "eye" };
const STATE: Record<string, string> = { waiting: "čeká", running: "pracuje", done: "hotovo", failed: "chyba", stopped: "zastaven" };
const kc = (n: number) => Math.round(n).toLocaleString("cs-CZ");

/** good / bad / neutral from a watcher's verdict ("vyplatí se" / "nevyplatí se" / "počkat") */
export function verdictTone(v: string): "good" | "bad" | "wait" | "" {
  const t = (v || "").toLowerCase();
  if (!t) return "";
  if (/nevyplat|neprodáv|prodat|prodej|ne\b|špatn|ztrát|klesá/.test(t)) return "bad";
  if (/vyplat|koupit|kup|ano|dobr|roste/.test(t)) return "good";
  return "wait";
}

/** a small line chart of a watcher's numbers; the last point coloured by its verdict */
function sparkline(series: [number, number, string][]): SVGSVGElement | null {
  const pts = (series || []).filter((p) => Number.isFinite(p[1]));
  if (pts.length < 2) return null;
  const W = 220, H = 40, P = 3;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = (x: number) => P + ((x - x0) / Math.max(1e-9, x1 - x0)) * (W - 2 * P);
  const Y = (y: number) => H - P - ((y - y0) / Math.max(1e-9, y1 - y0 || 1)) * (H - 2 * P);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "agv-spark");
  svg.setAttribute("preserveAspectRatio", "none");
  const d = pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ");
  const area = document.createElementNS(ns, "path");
  area.setAttribute("d", `${d} L${X(x1).toFixed(1)},${H} L${X(x0).toFixed(1)},${H} Z`);
  area.setAttribute("class", "agv-area");
  const line = document.createElementNS(ns, "path");
  line.setAttribute("d", d);
  line.setAttribute("class", "agv-line");
  svg.append(area, line);
  for (const p of pts) {                     // a dot where the verdict changed
    const i = pts.indexOf(p);
    if (i && p[2] === pts[i - 1][2] && i !== pts.length - 1) continue;
    // a zero-length line with round ends stays a round dot however the chart is stretched
    const c = document.createElementNS(ns, "line");
    const x = X(p[0]).toFixed(1), y = Y(p[1]).toFixed(1);
    c.setAttribute("x1", x); c.setAttribute("x2", x); c.setAttribute("y1", y); c.setAttribute("y2", y);
    c.setAttribute("class", `agv-pt ${verdictTone(p[2])} ${i === pts.length - 1 ? "last" : ""}`);
    svg.append(c);
  }
  return svg;
}

export interface AgentsView { el: HTMLElement; refresh(): void }

export function createAgentsView(client: JarvisClient, opts: { compact?: boolean } = {}): AgentsView {
  let last: any = null;
  let openPreset = "";
  let tellTo: { session: string; worker: string; name: string } | null = null;
  const head = h("span", { class: "agv-sub" });
  const stopAll = h("button", { class: "agv-btn danger", type: "button", hidden: true, onclick: () => client.send("multitask_stop", {}) },
    icon("stop-circle"), "Zastavit vše");
  const presetsBox = h("div", { class: "agv-presets" });
  const monsBox = h("div", { class: "agv-mons" });
  const paperBox = h("div", { class: "agv-paper", hidden: true });
  const list = h("div", { class: "agv-list" });
  const el = h("div", { class: `agv ${opts.compact ? "compact" : ""}` },
    h("div", { class: "agv-head" }, h("div", {}, h("strong", {}, "Agenti"), head), stopAll),
    presetsBox, monsBox, paperBox, list);

  // ---------- ready-made teams ----------
  const paintPresets = (presets: any[]) => {
    presetsBox.replaceChildren(...presets.map((p) => {
      const open = openPreset === p.id;
      const tile = h("button", { class: `agv-preset ${open ? "on" : ""}`, type: "button", title: p.about,
        onclick: () => { openPreset = open ? "" : p.id; paint(); } }, icon(p.icon || "users-three"), h("span", {}, p.name));
      return tile;
    }));
    const p = presets.find((x) => x.id === openPreset);
    if (p) {
      const inp = h("input", { class: "agv-input", type: "text", placeholder: p.ask }) as HTMLInputElement;
      const paperCb = h("input", { type: "checkbox", checked: true }) as HTMLInputElement;
      const go = () => {
        const topic = inp.value.trim();
        if (!topic) { inp.focus(); return; }
        client.send("multitask_preset", { preset: p.id, topic, ...(p.paper ? { paper: paperCb.checked } : {}) });
        openPreset = "";
        paint();
      };
      inp.onkeydown = (e) => { if (e.key === "Enter") go(); };
      presetsBox.append(h("div", { class: "agv-form" }, h("p", {}, p.about), inp,
        p.paper ? h("label", { class: "agv-check" }, paperCb, h("span", {}, "Zkušebně – bez skutečných peněz")) : null,
        h("button", { class: "agv-btn primary", type: "button", onclick: go }, icon("play"), "Spustit")));
      if (!typing()) window.setTimeout(() => inp.focus(), 30);
    }
  };

  // ---------- the play wallet ----------
  const paintPaper = (pp: any) => {
    paperBox.hidden = !pp;
    if (!pp) return;
    const up = pp.pl >= 0;
    paperBox.replaceChildren(
      h("div", { class: "agv-paper-head" }, icon("piggy-bank"), h("strong", {}, "Zkušební účet"),
        h("span", { class: `agv-pl ${up ? "good" : "bad"}` }, `${up ? "+" : ""}${kc(pp.pl)} Kč (${up ? "+" : ""}${pp.pl_pct} %)`)),
      h("p", {}, `Hodnota ${kc(pp.value)} Kč · hotovost ${kc(pp.cash)} Kč · start ${kc(pp.start)} Kč · obchodů ${pp.count}`),
      ...(pp.positions || []).map((x: any) => h("div", { class: "agv-pos" }, h("b", {}, x.symbol),
        h("span", {}, `${x.qty} ks · teď ${kc(x.price)} · ${x.pl >= 0 ? "+" : ""}${kc(x.pl)} Kč`))),
      ...(pp.trades || []).slice(0, 3).map((t: any) => h("div", { class: "agv-trade" },
        h("span", { class: t.side === "buy" ? "good" : "bad" }, t.side === "buy" ? "Nákup" : "Prodej"),
        h("span", {}, `${t.qty} ${t.symbol} za ${kc(t.price)} (${kc(t.czk)} Kč)`),
        h("em", {}, new Date(t.ts * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" })))),
      h("button", { class: "agv-btn ghost", type: "button", onclick: () => { if (confirm("Začít zkušební účet znovu s 10 000 Kč?")) client.send("paper_reset", { cash: 10000 }); } },
        icon("arrow-counter-clockwise"), "Začít znovu"));
  };

  // ---------- everything ----------
  const paint = () => {
    const m = last || {};
    const sessions: any[] = m.sessions || [];
    const running = Number(m.running) || 0;
    stopAll.hidden = !running;
    const who = running === 1 ? "Pracuje 1 agent" : running < 5 ? `Pracují ${running} agenti` : `Pracuje ${running} agentů`;
    head.textContent = running ? `${who} · AI najednou ${m.parallel}${m.slowed ? " · zpomaleno kvůli limitu AI" : ""}`
      : "Řekni třeba: „na monitoru 1 obchoduj, na monitoru 2 hlídej, jestli se to vyplatí“ – nebo vyber sestavu";
    paintPresets(m.presets || []);
    const live = sessions.flatMap((s) => (s.workers || []).filter((w: any) => w.state === "running" && w.monitor));
    monsBox.replaceChildren(...(m.monitors || []).map((mo: any) => {
      const on = live.filter((w: any) => w.monitor === mo.index);
      const tone = verdictTone(on.find((w: any) => w.verdict)?.verdict || "");
      return h("div", { class: `agv-mon ${on.length ? "on" : ""}`, "data-tone": tone },
        h("strong", {}, `Monitor ${mo.index}`), h("span", {}, `${mo.width}×${mo.height}${mo.primary ? " · hlavní" : ""}`),
        h("em", {}, on.length ? on.map((w: any) => `${w.name}${w.verdict ? ` · ${w.verdict}` : ""}`).join(", ") : "volný"));
    }));
    paintPaper(m.paper);
    list.replaceChildren(...(sessions.length ? sessions.slice(0, opts.compact ? 2 : 3).map((s) => {
      const c = s.count || {};
      const u = s.usage || {};
      const workers: any[] = s.workers || [];
      const watchers = workers.filter((w) => w.kind === "watch" && (w.series || []).length > 1);
      return h("div", { class: "agv-session" },
        h("div", { class: "agv-row" }, h("strong", {}, String(s.goal || "Úkol")),
          h("span", { class: "agv-time" }, `${c.running || 0} pracuje · ${c.done || 0} hotovo${c.failed ? ` · ${c.failed} chyba` : ""}`)),
        h("div", { class: "agv-meta" },
          s.paper ? h("span", { class: "agv-tag" }, icon("piggy-bank"), "zkušebně") : null,
          h("span", {}, `AI: ${u.calls || 0} dotazů${u.czk ? ` · ~${u.czk.toLocaleString("cs-CZ")} Kč u placeného klíče` : ""}`),
          s.report ? h("button", { class: "agv-link", type: "button",
            onclick: () => client.send("notice_action", { action: "open_report", args: { path: s.report } }) }, icon("file-text"), "Otevřít zprávu") : null),
        s.summary ? h("p", { class: "agv-sum" }, String(s.summary)) : null,
        ...watchers.slice(0, 2).map((w) => {
          const sp = sparkline(w.series);
          const lastP = w.series[w.series.length - 1];
          return h("div", { class: "agv-chart" }, h("div", { class: "agv-row" }, h("b", {}, `${w.name} · M${w.monitor}`),
            h("span", { class: `agv-verdict ${verdictTone(w.verdict)}` }, `${kc(lastP[1])} · ${w.verdict || "—"}`)), sp);
        }),
        h("div", { class: "agv-grid" }, ...workers.slice(0, 100).map((w) => {
          const live2 = w.state === "running" || w.state === "waiting";
          const tile = h("div", { class: `agv-w ${w.state} ${tellTo?.worker === w.id ? "sel" : ""}`, title: live2 ? `${w.task}\n\nKlikni a napiš mu pokyn` : String(w.task || ""),
            onclick: () => { if (!live2) return; tellTo = tellTo?.worker === w.id ? null : { session: s.id, worker: w.id, name: w.name }; paint(); } },
            h("span", { class: "agv-ico" }, icon(KIND_ICON[w.kind] || "robot")),
            h("div", { class: "agv-txt" },
              h("b", {}, String(w.name), w.monitor ? h("i", {}, ` · M${w.monitor}`) : null,
                (w.areas || []).length ? h("i", { title: "Smí jen tyto oblasti oprávnění" }, ` · jen ${(w.areas as string[]).join(", ")}`) : null),
              h("span", {}, w.verdict ? `${w.verdict}${w.last && w.last !== w.verdict ? " · " + w.last : ""}` : String(w.last || STATE[w.state] || ""))),
            live2 ? h("button", { class: "agv-x", type: "button", title: "Zastavit tohohle agenta",
              onclick: (e: Event) => { e.stopPropagation(); client.send("multitask_stop", { session: s.id, worker: w.id }); } }, icon("x"))
              : h("span", { class: `agv-dot ${w.state}` }));
          return tile;
        })),
        tellTo && tellTo.session === s.id ? (() => {
          const inp = h("input", { class: "agv-input", type: "text", placeholder: `Napiš agentovi ${tellTo!.name} (např. sleduj i ETH)` }) as HTMLInputElement;
          const send = () => {
            if (!inp.value.trim() || !tellTo) return;
            client.send("multitask_tell", { session: tellTo.session, worker: tellTo.worker, text: inp.value.trim() });
            tellTo = null;
            paint();
          };
          inp.onkeydown = (e) => { if (e.key === "Enter") send(); if (e.key === "Escape") { tellTo = null; paint(); } };
          if (!typing()) window.setTimeout(() => inp.focus(), 30);
          return h("div", { class: "agv-tell" }, inp, h("button", { class: "agv-btn primary", type: "button", onclick: send }, icon("paper-plane-tilt"), "Poslat"));
        })() : null);
    }) : [h("p", { class: "agv-empty" }, "JARVIS se umí rozdělit až na 100 agentů najednou: jeden ovládá monitor, druhý ho sleduje a hodnotí, další hledají a počítají.")]));
  };

  // while you type (a message to an agent, the topic of a team) the live updates wait – they would wipe the text
  let pending = false;
  const typing = () => { const a = document.activeElement; return !!a && el.contains(a) && a.tagName === "INPUT" && (a as HTMLInputElement).type === "text"; };
  const later = () => { if (typing()) { pending = true; return; } pending = false; paint(); };
  el.addEventListener("focusout", () => window.setTimeout(() => { if (pending && !typing()) { pending = false; paint(); } }, 250));
  client.on("multitask", (m: any) => { last = m; later(); });
  client.on("paper", (m: any) => { if (last) { last = { ...last, paper: m }; later(); } });
  client.on("multitask_result", (m: any) => toast(String(m.message || ""), m.ok ? "ok" : "error", 4000));
  return { el, refresh: () => client.send("multitask_get") };
}
