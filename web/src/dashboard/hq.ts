// 3.12 Velín firmy – the whole company on one full screen: the company brain in the middle, the departments around it,
// each department as a tree (services → agents → their jobs → the department), each agent's card (what it does, what it
// replaces, the ladder, its last work, what waits for approval), the list of all agents, approvals, results, the brain
// and "Postavit firmu" (hire the library's 100 agents). Everything an agent would send, write or pay still waits for
// your click – the control room only shows it in one place.
import "./hq.css";
import { h, icon, toast } from "../shared/dom";
import type { JarvisClient } from "../shared/ws";

interface Agent { id: number; name: string; icon: string; role: string; task: string; tools: string[]; every_min: number; daily_at: string;
  work_hours: boolean; enabled: boolean; last_run: number | null; last_ok: number | null; last_result: string | null; dept: string;
  skill: string; replaces: string; bkey: string; runs: number; fails: number; when: string; triggers: string[]; next: string[]; tier: string }
interface Proposal { id: number; agent_id: number; agent: string; tool: string; description: string; details: string[]; created: number;
  status: string; result?: string }
interface Dept { id: string; name: string; icon: string; color: string; desc: string; agents: number; library: number }
interface Lib { key: string; dept: string; name: string; icon: string; skill: string; replaces: string; needs: string[]; ready: string[];
  usable: boolean; hired: boolean; when: string }
interface Run { id: number; agent_id: number; agent: string; dept: string; started: number; seconds: number; ok: number; proposals: number; summary: string }
interface Numbers { runs_today: number; ok_today: number; proposals_today: number; runs_week: number; ok_week: number; approved_today: number;
  pending: number; notes: number; per_dept: Record<string, { runs: number; ok: number }>; budget: number; paused: boolean;
  per_day?: { label: string; runs: number; ok: number }[]; ai_week?: number; saved_week_min?: number; dept_budget?: Record<string, number>; phone?: string }
interface Company { depts: Dept[]; library: Lib[]; profile: Record<string, string>; profile_fields: Record<string, string>;
  notes: { id: number; text: string; source: string; created: number }[]; numbers: Numbers; runs: Run[];
  chains?: Record<string, { name: string; icon: string; steps: string[]; desc: string }>; events?: Record<string, { label: string; icon: string }> }
interface Conn { id: string; name: string; icon: string; connected: boolean; prefixes: string[] }

type View = "overview" | "dept" | "agents" | "approvals" | "results" | "brain" | "build";
/** Minutes as hours the Czech way: 0, 1,5, 12. */
const hours = (min?: number) => { const v = Math.round((min || 0) / 6) / 10; return v.toLocaleString("cs-CZ", { maximumFractionDigits: v >= 10 ? 0 : 1 }); };
const OTHER: Dept = { id: "ostatni", name: "Ostatní", icon: "dots-three-circle", color: "#7d8fb3", desc: "Agenti bez oddělení.", agents: 0, library: 0 };
const SVG = "http://www.w3.org/2000/svg";
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function s<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, any> = {}, ...kids: (Node | string | null | false)[]): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, String(v));
  }
  for (const c of kids) if (c) el.append(typeof c === "string" ? document.createTextNode(c) : c);
  return el;
}
const ago = (t: number | null) => {
  if (!t) return "ještě nepracoval";
  const x = Math.round(Date.now() / 1000 - t);
  return x < 60 ? "před chvílí" : x < 3600 ? `před ${Math.round(x / 60)} min` : x < 86400 ? `před ${Math.round(x / 3600)} h` : `před ${Math.round(x / 86400)} d`;
};
const clock = (t: number) => new Date(t * 1000).toLocaleString("cs-CZ", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });
const nice = (tool: string) => tool.replace(/^(google|outlook|onedrive|mstodo|company)_/, "").replace(/_/g, " ");

// ---------------------------------------------------------------- the brain: a slowly turning sphere of points
class Brain {
  pts: { x: number; y: number; z: number }[] = [];
  links: [number, number][] = [];
  labels: { i: number; text: string }[] = [];
  angle = 0;
  constructor(n: number, labels: string[]) { this.make(n, labels); }
  make(n: number, labels: string[]) {
    this.pts = [];
    const g = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {               // a Fibonacci sphere, a little uneven so it looks alive
      const y = 1 - (i / (n - 1)) * 2, r = Math.sqrt(1 - y * y), th = g * i;
      const j = 0.82 + ((i * 7919) % 100) / 560;
      this.pts.push({ x: Math.cos(th) * r * j, y: y * j, z: Math.sin(th) * r * j });
    }
    this.links = [];
    for (let i = 0; i < n; i++) {
      const d = this.pts.map((p, k) => [k, (p.x - this.pts[i].x) ** 2 + (p.y - this.pts[i].y) ** 2 + (p.z - this.pts[i].z) ** 2] as [number, number])
        .filter(([k]) => k !== i).sort((a, b) => a[1] - b[1]).slice(0, 3);
      for (const [k] of d) if (k > i) this.links.push([i, k]);
      if (i % 9 === 0) this.links.push([i, (i * 31 + 17) % n]);        // a few long links across
    }
    this.labels = labels.map((text, k) => ({ text, i: Math.floor(((k + 0.5) / labels.length) * n) % n }));
  }
  draw(ctx: CanvasRenderingContext2D, cx: number, cy: number, R: number, color: string, step = 0.0022, labels = true, far = "#8b5cff") {
    this.angle += step;
    const ca = Math.cos(this.angle), sa = Math.sin(this.angle), tilt = 0.32, ct = Math.cos(tilt), st = Math.sin(tilt);
    const pr = this.pts.map((p) => {
      const x = p.x * ca - p.z * sa, z0 = p.x * sa + p.z * ca;
      const y = p.y * ct - z0 * st, z = p.y * st + z0 * ct;
      return { X: cx + x * R, Y: cy + y * R, z };
    });
    const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 1.05);       // the warm light inside
    core.addColorStop(0, `${color}38`); core.addColorStop(0.55, `${color}12`); core.addColorStop(1, `${color}00`);
    ctx.fillStyle = core; ctx.beginPath(); ctx.arc(cx, cy, R * 1.05, 0, Math.PI * 2); ctx.fill();
    ctx.globalCompositeOperation = "lighter";
    ctx.lineWidth = 0.75;
    for (const [a, b] of this.links) {
      const za = (pr[a].z + pr[b].z) / 2;
      ctx.strokeStyle = `${za > -0.1 ? color : far}${Math.round(14 + (za + 1) * 30).toString(16).padStart(2, "0")}`;
      ctx.beginPath(); ctx.moveTo(pr[a].X, pr[a].Y); ctx.lineTo(pr[b].X, pr[b].Y); ctx.stroke();
    }
    for (const p of pr) {                        // near points warm and big, far ones violet and small
      const near = (p.z + 1) / 2;
      ctx.fillStyle = near > 0.45 ? color : far;
      ctx.globalAlpha = 0.18 + near * 0.6;
      ctx.beginPath(); ctx.arc(p.X, p.Y, 3.2 + near * 3.4, 0, Math.PI * 2); ctx.fill();          // the soft halo
      ctx.globalAlpha = 0.45 + near * 0.55;
      ctx.beginPath(); ctx.arc(p.X, p.Y, 0.9 + near * 1.5, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    if (labels && R > 90) {
      ctx.font = `600 ${Math.max(10, Math.round(R / 15))}px "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif`;
      ctx.textAlign = "center";
      for (const l of this.labels) {
        const p = pr[l.i];
        if (p.z < -0.1) continue;
        ctx.fillStyle = "#ffd9cc"; ctx.globalAlpha = Math.min(0.9, 0.15 + p.z * 0.9);
        ctx.fillText(l.text, p.X, p.Y - 8);
      }
      ctx.globalAlpha = 1;
    }
  }
}

/** The shared SVG pieces of the glass look: the light on a glass disc, and the lens that bends what is behind. */
function glassDefs(): SVGSVGElement {
  return s("svg", { width: 0, height: 0, "aria-hidden": "true", style: "position:absolute;width:0;height:0" },
    s("defs", {},
      s("radialGradient", { id: "hq-sheen", cx: "32%", cy: "24%", r: "78%" },
        s("stop", { offset: "0%", "stop-color": "#fff", "stop-opacity": ".55" }),
        s("stop", { offset: "38%", "stop-color": "#fff", "stop-opacity": ".10" }),
        s("stop", { offset: "70%", "stop-color": "#fff", "stop-opacity": "0" }),
        s("stop", { offset: "100%", "stop-color": "#fff", "stop-opacity": ".18" })),
      s("filter", { id: "hq-lens", x: "0%", y: "0%", width: "100%", height: "100%", "color-interpolation-filters": "sRGB" },
        s("feTurbulence", { type: "fractalNoise", baseFrequency: "0.012 0.018", numOctaves: 1, seed: 4, result: "n" }),
        s("feGaussianBlur", { in: "n", stdDeviation: 3, result: "nb" }),
        s("feDisplacementMap", { in: "SourceGraphic", in2: "nb", scale: 26, xChannelSelector: "R", yChannelSelector: "G" }))));
}

export function openHQ(client: JarvisClient) {
  (window as any).__jarvisHQ ??= buildHQ(client);
  (window as any).__jarvisHQ.open();
}

function buildHQ(client: JarvisClient) {
  let agents: Agent[] = [], props: Proposal[] = [], running: number[] = [], queue: number[] = [], conns: Conn[] = [];
  let company: Company | null = null;
  let view: View = "overview", deptId = "", cardId: number | string | null = null, isOpen = false;
  let filter = { q: "", dept: "", status: "" };
  const live = new Map<number, string>();            // agent id → the tool it is using now

  const depts = () => {
    const ds = company?.depts?.length ? company.depts : [];
    return agents.some((a) => !a.dept || !ds.find((d) => d.id === a.dept)) ? [...ds, { ...OTHER, agents: agents.filter((a) => !a.dept).length }] : ds;
  };
  const deptOf = (id: string) => depts().find((d) => d.id === (id || "ostatni")) || OTHER;
  const agentsOf = (d: string) => agents.filter((a) => (a.dept || "ostatni") === d);
  const libOf = (d: string) => (company?.library || []).filter((l) => l.dept === d);
  const ownerOf = (tool: string) => conns.find((c) => (c.prefixes || []).some((p) => tool.startsWith(p)));
  const state = (a: Agent) => running.includes(a.id) ? "run" : queue.includes(a.id) ? "queue" : !a.enabled ? "off" : a.last_run && !a.last_ok ? "bad" : "on";
  const STATE_TXT: Record<string, string> = { run: "PRACUJE", queue: "VE FRONTĚ", off: "VYPNUTÝ", bad: "CHYBA", on: "ZAPNUTÝ" };
  const writes = (a: { tools: string[] }) => a.tools.some((t) => /_(send|create|append|set|post|add|refund|payment_link|note|done|timer|draft)$|_sql$/.test(t));

  // ---------------------------------------------------------------- frame
  const crumbs = h("div", { class: "hq-crumbs" });
  const title = h("h1", { class: "hq-title" });
  const body = h("div", { class: "hq-body" });
  const railStatus = h("div", { class: "hq-rail-status" });
  const nav = h("nav", { class: "hq-nav" });
  const dump = h("textarea", { class: "hq-dump-in", rows: 1, placeholder: "vhoď do mozku firmy… nebo popiš nového agenta",
    "aria-label": "Mozek firmy nebo nový agent" }) as HTMLTextAreaElement;
  const toBrain = () => {
    const t = dump.value.trim();
    if (t.length < 3) { toast("Napiš, co si má firma pamatovat.", "error"); return; }
    client.send("bizbrain_add", { text: t }); dump.value = "";
  };
  const toAgent = () => {
    const t = dump.value.trim();
    if (t.length < 8) { toast("Popiš, co má agent dělat.", "error"); return; }
    client.send("bizagent_text", { text: t }); dump.value = ""; toast("Vymýšlím agenta…", "info");
  };
  dump.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); (e.ctrlKey || e.metaKey ? toAgent : toBrain)(); }
  });
  const dumpBox = h("div", { class: "hq-dump glass" }, h("span", { class: "hq-dump-ico" }, icon("sparkle", "ph-fill")), dump,
    h("div", { class: "hq-dump-h" }, h("span", {}, "text · přetáhni soubor · Enter = do mozku · Ctrl+Enter = nový agent"),
      h("button", { type: "button", class: "hq-mini", onclick: toBrain }, icon("brain"), "Do mozku"),
      h("button", { type: "button", class: "hq-mini", onclick: toAgent }, icon("user-plus"), "Nový agent")));
  const drop = (e: DragEvent) => {
    e.preventDefault();
    for (const f of Array.from(e.dataTransfer?.files || [])) {
      if (!/\.(txt|md|csv|json|html?)$/i.test(f.name) || f.size > 400_000) { toast(`${f.name}: zatím umím jen textové soubory do 400 kB.`, "error"); continue; }
      f.text().then((t) => client.send("bizbrain_add", { text: `[${f.name}]\n${t.slice(0, 19000)}`, source: f.name }));
    }
  };
  const chips = h("div", { class: "hq-chips-top" });
  const root = h("div", { class: "hq", role: "dialog", "aria-label": "Velín firmy", hidden: true, ondragover: (e: DragEvent) => e.preventDefault(), ondrop: drop },
    h("div", { class: "hq-aurora", "aria-hidden": "true" }, h("i"), h("i"), h("i"), h("i")),
    h("aside", { class: "hq-rail glass" },
      h("div", { class: "hq-brand" }, h("span", { class: "hq-logo" }, icon("circles-three-plus", "ph-fill")),
        h("div", {}, h("b", {}, "JARVIS"), h("small", {}, "Velín firmy"))),
      nav, railStatus),
    h("main", { class: "hq-main" },
      h("header", { class: "hq-head glass" },
        h("div", { class: "hq-head-l" }, h("div", { class: "hq-kicker" }, crumbs), title, chips),
        dumpBox,
        h("button", { type: "button", class: "hq-x lens", title: "Zavřít velín (Esc)", "aria-label": "Zavřít velín", onclick: () => close() }, icon("x"))),
      body));
  document.body.append(root, glassDefs());

  const NAV: [View, string, string][] = [["overview", "squares-four", "Přehled"], ["dept", "tree-structure", "Oddělení"], ["agents", "users-three", "Agenti"],
    ["approvals", "seal-check", "Ke schválení"], ["results", "pulse", "Výsledky"], ["brain", "brain", "Mozek firmy"], ["build", "buildings", "Postavit firmu"]];
  const paintNav = () => {
    const n = company?.numbers;
    nav.replaceChildren(
      h("div", { class: "hq-nav-h" }, "ŘÍZENÍ"),
      ...NAV.map(([v, ic, label]) => h("button", { type: "button", class: `hq-nav-i ${view === v ? "on" : ""}`, onclick: () => go(v) },
        icon(ic), h("span", {}, label),
        v === "approvals" && props.length ? h("em", { class: "hq-badge" }, String(props.length)) : "",
        v === "agents" ? h("small", {}, String(agents.length)) : "")),
      h("div", { class: "hq-nav-h" }, "ODDĚLENÍ"),
      ...depts().map((d) => h("button", { type: "button", class: `hq-nav-i dept ${view === "dept" && deptId === d.id ? "on" : ""}`, style: { "--c": d.color },
        onclick: () => { deptId = d.id; go("dept"); } }, h("i", { class: "hq-dot" }), h("span", {}, d.name), h("small", {}, String(agentsOf(d.id).length)))));
    const run = agents.find((a) => running.includes(a.id));
    chips.replaceChildren(
      h("span", { class: "hq-chip-top ok" }, h("i"), `${agents.filter((a) => a.enabled).length} zapnuto`),
      h("span", { class: `hq-chip-top ${props.length ? "warn" : ""}` }, h("i"), `${props.length} ke schválení`),
      h("span", { class: "hq-chip-top" }, h("i"), `${n?.runs_today ?? 0} běhů dnes`),
      run ? h("span", { class: "hq-chip-top run" }, h("i"), `pracuje: ${run.name}`) : "");
    railStatus.replaceChildren(
      h("div", { class: `hq-live ${run ? "run" : n?.paused ? "off" : ""}` }, h("i"),
        h("span", {}, run ? `Pracuje: ${run.name}` : n?.paused ? "Agenti stojí" : "Připraveno")),
      h("div", { class: "hq-meter" }, h("span", {}, `Dnes ${n?.runs_today ?? 0} / ${n?.budget ?? 0} běhů`),
        h("i", { style: { "--p": `${Math.min(100, ((n?.runs_today || 0) / Math.max(1, n?.budget || 1)) * 100)}%` } })),
      queue.length ? h("small", {}, `Ve frontě: ${queue.length}`) : "",
      h("div", { class: "hq-rail-acts" },
        h("button", { type: "button", class: "hq-mini", onclick: () => client.send("bizpause_set", { paused: !n?.paused }) },
          icon(n?.paused ? "play" : "pause"), n?.paused ? "Spustit firmu" : "Pozastavit vše"),
        budgetSel(n?.budget ?? 80), phoneSel(n?.phone || "away"),
        h("button", { type: "button", class: "hq-mini", title: "Zkontrolovat nové e-maily, objednávky a platby hned", onclick: () => client.send("bizevents_check") },
          icon("arrows-clockwise"), "Zkontrolovat události")));
  };
  const phoneSel = (cur: string) => {
    const sel = h("select", { class: "hq-sel", "aria-label": "Schvalování z telefonu" },
      ...[["away", "Telefon: když nejsem u PC"], ["always", "Telefon: každý návrh"], ["off", "Telefon: neposílat"]]
        .map(([v, t]) => h("option", { value: v, selected: v === cur }, t))) as HTMLSelectElement;
    sel.onchange = () => client.send("bizphone_set", { mode: sel.value });
    return sel;
  };
  const budgetSel = (cur: number) => {
    const sel = h("select", { class: "hq-sel", "aria-label": "Denní limit běhů", title: "Kolikrát denně smí agenti celkem pracovat (šetří limity AI)" },
      ...[20, 40, 80, 150, 300, 600, 1500].map((v) => h("option", { value: String(v), selected: v === cur }, `${v} běhů/den`))) as HTMLSelectElement;
    if (![20, 40, 80, 150, 300, 600, 1500].includes(cur)) sel.prepend(h("option", { value: String(cur), selected: true }, `${cur} běhů/den`));
    sel.onchange = () => client.send("bizbudget_set", { runs: Number(sel.value) });
    return sel;
  };

  // ---------------------------------------------------------------- canvas loop (only while a picture is on screen)
  const brain = new Brain(170, []);
  const mini = new Brain(70, []);
  let raf = 0, last = 0;
  let painter: ((t: number) => void) | null = null;
  const loop = (t: number) => {
    raf = 0;
    if (!isOpen || !painter || document.hidden) return;
    if (t - last > 33 || reduced()) { last = t; painter(t); }
    if (!reduced()) raf = requestAnimationFrame(loop);
  };
  const animate = (fn: ((t: number) => void) | null) => {
    painter = fn;
    if (fn && !raf) raf = requestAnimationFrame(loop);
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden && painter && !raf) raf = requestAnimationFrame(loop); });
  const fit = (cv: HTMLCanvasElement) => {
    const r = cv.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
    if (cv.width !== Math.round(r.width * dpr) || cv.height !== Math.round(r.height * dpr)) {
      cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
    }
    const ctx = cv.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, r.width, r.height);
    return { ctx, w: r.width, h: r.height };
  };

  // ---------------------------------------------------------------- overview: the brain and the departments around it
  const overview = () => {
    const ds = depts();
    const n = company?.numbers;
    brain.make(Math.min(320, 150 + (n?.notes || 0) * 2 + agents.length), ds.map((d) => d.name));
    const cv = h("canvas", { class: "hq-cv" }) as HTMLCanvasElement;
    const svg = s("svg", { class: "hq-svg" });
    const layer = h("div", { class: "hq-nodes" });
    const stage = h("div", { class: "hq-stage" }, cv, svg, layer);
    let geo = { cx: 0, cy: 0, R: 0 };
    let spots: { x: number; y: number; ex: number; ey: number; color: string; busy: boolean; n: number }[] = [];
    const per = n?.per_dept || {};
    const layout = () => {
      const r = stage.getBoundingClientRect();
      const R = Math.max(70, Math.min(r.width * 0.2, r.height * 0.21)), rx = Math.min(r.width * 0.37, r.height * 0.52), ry = r.height * 0.355;
      geo = { cx: r.width / 2, cy: r.height / 2 - 6, R };
      svg.setAttribute("viewBox", `0 0 ${r.width} ${r.height}`);
      svg.replaceChildren(s("circle", { cx: geo.cx, cy: geo.cy, r: R * 1.1, class: "hq-ring" }), s("circle", { cx: geo.cx, cy: geo.cy, r: R * 1.22, class: "hq-ring2" }));
      spots = [];
      layer.replaceChildren(...ds.map((d, i) => {
        const a = -Math.PI / 2 + (i / ds.length) * Math.PI * 2;
        const x = geo.cx + Math.cos(a) * rx, y = geo.cy + Math.sin(a) * ry;
        const ex = geo.cx + Math.cos(a) * R * 1.1, ey = geo.cy + Math.sin(a) * R * 1.1;
        const mine = agentsOf(d.id);
        const busy = mine.some((x2) => running.includes(x2.id));
        const waiting = props.filter((p) => mine.some((m) => m.id === p.agent_id)).length;
        spots.push({ x, y, ex, ey, color: d.color, busy, n: mine.length });
        svg.append(s("line", { x1: ex, y1: ey, x2: x, y2: y, class: `hq-link ${busy ? "busy" : ""} ${mine.length ? "" : "empty"}`, style: `--c:${d.color}` }));
        const runs = per[d.id === "ostatni" ? "" : d.id]?.runs || 0;
        const orbit = h("span", { class: "hq-dn-orbit" }, ...mine.slice(0, 24).map((ag, k) =>
          h("i", { class: `hq-dn-dot ${state(ag)}`, style: { transform: `rotate(${(k / Math.max(1, Math.min(24, mine.length))) * 360}deg) translateX(47px)` } })));
        return h("button", { type: "button", class: `hq-dn ${busy ? "busy" : ""} ${mine.length ? "" : "empty"} ${y > geo.cy ? "low" : ""}`,
          style: { left: `${x}px`, top: `${y}px`, "--c": d.color }, "aria-label": `${d.name}: ${mine.length} agentů`,
          onclick: () => { deptId = d.id; go("dept"); } },
          orbit,
          h("span", { class: "hq-dn-disc" }, icon(d.icon, "ph-fill"), h("em", {}, String(mine.length))),
          h("span", { class: "hq-dn-label" }, d.name),
          h("span", { class: "hq-dn-tip" }, h("b", {}, d.name), h("span", {}, d.desc),
            h("small", {}, `${mine.length} agentů · ${runs} běhů za týden${waiting ? ` · ${waiting} ke schválení` : ""}${busy ? " · právě pracuje" : ""}`)));
      }));
    };
    const ro = new ResizeObserver(layout);
    requestAnimationFrame(() => { layout(); ro.observe(stage); });
    animate((t) => {
      if (!stage.isConnected) { ro.disconnect(); animate(null); return; }
      const { ctx } = fit(cv);
      brain.draw(ctx, geo.cx, geo.cy, geo.R, "#ff8a6b", running.length ? 0.006 : 0.0022);
      ctx.globalCompositeOperation = "lighter";
      for (const [k, sp] of spots.entries()) {          // signals: what the brain sends to the departments
        if (!sp.n) continue;
        const count = sp.busy ? 3 : 1, speed = sp.busy ? 0.00055 : 0.00016;
        for (let j = 0; j < count; j++) {
          const f = ((t * speed) + k * 0.137 + j / count) % 1;
          const px = sp.ex + (sp.x - sp.ex) * f, py = sp.ey + (sp.y - sp.ey) * f;
          const g = ctx.createRadialGradient(px, py, 0, px, py, sp.busy ? 9 : 6);
          g.addColorStop(0, `${sp.color}ff`); g.addColorStop(0.35, `${sp.color}88`); g.addColorStop(1, `${sp.color}00`);
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(px, py, sp.busy ? 9 : 6, 0, Math.PI * 2); ctx.fill();
        }
      }
      ctx.globalCompositeOperation = "source-over";
    });
    const week = n?.per_day || [];
    const wmax = Math.max(1, ...week.map((d) => d.runs));
    const left = h("div", { class: "hq-panel glass hq-brainpanel" },
      h("div", { class: "hq-ph" }, icon("brain"), "MOZEK FIRMY"),
      h("p", { class: "hq-sub" }, company?.profile?.name ? `${company.profile.name} – ${company.profile.what || "doplň, co firma dělá"}` : "Doplň profil firmy – agenti podle něj pracují."),
      h("div", { class: "hq-stats" },
        stat(String(agents.length), "AGENTŮ", "robot"), stat(String(agents.filter((a) => a.enabled).length), "ZAPNUTO", "power"),
        stat(String(n?.notes ?? 0), "POZNÁMEK", "note"), stat(String(conns.filter((c) => c.connected).length), "SLUŽEB", "plugs-connected"),
        stat(String(n?.runs_today ?? 0), "BĚHŮ DNES", "lightning"), stat(String(props.length), "KE SCHVÁLENÍ", "seal-check")),
      week.length ? h("div", { class: "hq-ph sm" }, icon("chart-line-up"), "PRÁCE ZA TÝDEN") : "",
      week.length ? h("div", { class: "hq-week" }, ...week.map((d) => h("div", { class: "hq-wcol", title: `${d.label}: ${d.runs} běhů, ${d.ok} úspěšných` },
        h("i", { style: { "--h": `${Math.max(4, (d.runs / wmax) * 100)}%`, "--ok": `${d.runs ? (d.ok / d.runs) * 100 : 100}%` } }),
        h("small", {}, d.label)))) : "",
      h("div", { class: "hq-ph sm" }, icon("chart-bar"), "ODDĚLENÍ (7 DNÍ)"),
      ...ds.map((d) => {
        const r = per[d.id === "ostatni" ? "" : d.id] || { runs: 0, ok: 0 };
        const max = Math.max(1, ...Object.values(per).map((x) => x.runs));
        return h("button", { type: "button", class: "hq-bar", style: { "--c": d.color }, onclick: () => { deptId = d.id; go("dept"); } },
          h("span", {}, d.name), h("i", { style: { "--p": `${(r.runs / max) * 100}%` } }), h("b", {}, String(r.runs)));
      }),
      h("button", { type: "button", class: "hq-btn wide", onclick: () => go("brain") }, icon("note-pencil"), "Otevřít mozek firmy"));
    const right = h("div", { class: "hq-panel glass hq-legend" },
      h("div", { class: "hq-ph" }, icon("pulse"), "ŽIVĚ"),
      ...[["on", "Zapnutý"], ["run", "Právě pracuje"], ["queue", "Čeká ve frontě"], ["bad", "Poslední běh selhal"], ["off", "Vypnutý"]]
        .map(([k, t]) => h("div", { class: "hq-leg" }, h("i", { class: `hq-adot-i ${k}` }), t,
          h("b", {}, String(agents.filter((a) => state(a) === k).length)))),
      h("div", { class: "hq-ph sm" }, icon("robot"), `NAPOSLEDY PRACOVALI`),
      h("div", { class: "hq-mini-list" }, ...agents.slice().sort((a, b) => (b.last_run || 0) - (a.last_run || 0)).slice(0, 14).map((a) =>
        h("button", { type: "button", class: "hq-mini-row", style: { "--c": deptOf(a.dept).color }, onclick: () => { deptId = a.dept || "ostatni"; cardId = a.id; go("dept"); } },
          h("span", { class: "hq-mini-ico" }, icon(a.icon || "robot", "ph-fill")), h("span", {}, a.name), h("small", {}, ago(a.last_run))))),
      agents.length ? "" : h("button", { type: "button", class: "hq-btn wide primary", onclick: () => go("build") }, icon("buildings"), "Postavit firmu"));
    return h("div", { class: "hq-overview" }, left, stage, right);
  };
  const stat = (v: string, l: string, ic = "") => h("div", { class: "hq-stat" }, ic ? icon(ic, "ph-fill") : "", h("b", {}, v), h("small", {}, l));

  // ---------------------------------------------------------------- one department as a tree
  const deptView = () => {
    const ds = depts();
    if (!deptId || !ds.find((d) => d.id === deptId)) deptId = ds[0]?.id || "";
    const d = deptOf(deptId);
    const mine = agentsOf(d.id);
    const ghosts = libOf(d.id).filter((l) => !l.hired);
    const nodes: ({ kind: "a"; a: Agent } | { kind: "l"; l: Lib })[] = [...mine.map((a) => ({ kind: "a" as const, a })), ...ghosts.map((l) => ({ kind: "l" as const, l }))];
    const toolsOf = (n: typeof nodes[number]) => n.kind === "a" ? n.a.tools : (BL[n.l.key] || []);
    const svcIds = [...new Set(nodes.flatMap((n) => toolsOf(n).map((t) => ownerOf(t)?.id).filter(Boolean) as string[]))];
    const cv = h("canvas", { class: "hq-cv" }) as HTMLCanvasElement;
    const svg = s("svg", { class: "hq-svg tree" });
    const wrap = h("div", { class: "hq-tree-scroll" }, h("div", { class: "hq-tree" }, cv, svg));
    const W = Math.max(980, nodes.length * 168, svcIds.length * 118), H = 640;
    const inner = wrap.firstElementChild as HTMLElement;
    inner.style.width = `${W}px`; inner.style.height = `${H}px`;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const hub = { x: W / 2, y: H - 70 };
    const sx = (i: number, n: number) => (W / (n + 1)) * (i + 1);
    const svcPos = new Map(svcIds.map((id, i) => [id, { x: sx(i, svcIds.length), y: 70 }]));
    const linkG = s("g"), labelG = s("g");
    const tlayer = h("div", { class: "hq-tnodes" });
    inner.append(tlayer);
    nodes.forEach((n, i) => {
      const x = sx(i, nodes.length), y = 270, jy = 430;
      const id = n.kind === "a" ? n.a.id : n.l.key;
      const st = n.kind === "a" ? state(n.a) : "ghost";
      for (const t of toolsOf(n)) {
        const o = ownerOf(t);
        const p = o && svcPos.get(o.id);
        if (p) linkG.append(s("line", { x1: x, y1: y - 28, x2: p.x, y2: p.y + 20, class: `hq-tl ${st}` }));
      }
      linkG.append(s("line", { x1: x, y1: y + 28, x2: x, y2: jy - 9, class: `hq-tl v ${st}` }));
      linkG.append(s("path", { d: `M${x} ${jy + 9} C ${x} ${jy + 80}, ${hub.x} ${hub.y - 90}, ${hub.x} ${hub.y - 38}`, class: `hq-flow ${st}` }));
      const label = n.kind === "a" ? n.a.name : n.l.name;
      const skill = n.kind === "a" ? (n.a.skill || n.a.task.slice(0, 40)) : n.l.skill;
      const lift = i % 2 ? 15 : 0;                        // neighbours' labels on two lines, never on top of each other
      linkG.append(s("rect", { x: x - 9, y: jy - 9, width: 18, height: 18, rx: 6, class: `hq-job ${st}` }));
      labelG.append(s("text", { x, y: jy + 26 + lift, class: `hq-jlabel ${st}` }, trunc(skill, 24)));
      const ic = n.kind === "a" ? (n.a.icon || "robot") : n.l.icon;
      tlayer.append(h("button", { type: "button", class: `hq-an ${st} ${cardId === id ? "sel" : ""}`, style: { left: `${x}px`, top: `${y}px` },
        title: `${label} – ${skill}`, "aria-label": label, onclick: () => { cardId = id; paint(); } },
        h("span", { class: "hq-an-disc" }, icon(ic, "ph-fill"), n.kind === "l" ? h("em", {}, icon("plus", "ph-bold")) : ""),
        h("span", { class: "hq-an-label", style: { marginTop: `${lift}px` } }, trunc(label, 21))));
    });
    svcIds.forEach((id) => {
      const c = conns.find((x) => x.id === id)!;
      const p = svcPos.get(id)!;
      tlayer.append(h("span", { class: `hq-sv ${c.connected ? "on" : "off"}`, style: { left: `${p.x}px`, top: `${p.y}px` },
        title: c.connected ? `${c.name} – propojeno` : `${c.name} – nepropojeno (Propojení)` },
        h("span", { class: "hq-sv-label" }, trunc(c.name.split(" (")[0], 16)),
        h("span", { class: "hq-sv-disc" }, icon(c.icon || "plug", "ph-fill"))));
    });
    svg.append(linkG, labelG, s("text", { x: hub.x, y: hub.y + 62, class: "hq-hublabel" }, d.name.toUpperCase()));
    animate(() => {
      if (!cv.isConnected) { animate(null); return; }
      const { ctx } = fit(cv);
      mini.draw(ctx, hub.x, hub.y, 38, d.color, running.some((r) => mine.find((a) => a.id === r)) ? 0.012 : 0.004, false, d.color);
    });
    const idx = ds.findIndex((x) => x.id === d.id);
    const sw = h("div", { class: "hq-switch glass lens" },
      h("button", { type: "button", "aria-label": "Předchozí oddělení", onclick: () => { deptId = ds[(idx - 1 + ds.length) % ds.length].id; cardId = null; paint(); } }, icon("caret-left")),
      h("span", { style: { "--c": d.color } }, d.name.toUpperCase()),
      h("button", { type: "button", "aria-label": "Další oddělení", onclick: () => { deptId = ds[(idx + 1) % ds.length].id; cardId = null; paint(); } }, icon("caret-right")));
    const head = h("div", { class: "hq-dhead", style: { "--c": d.color } },
      h("h2", {}, d.name.toUpperCase()), h("p", {}, d.desc),
      h("div", { class: "hq-dacts" },
        h("span", {}, `${mine.length} agentů · ${ghosts.length} v knihovně`),
        deptLimit(d.id),
        ghosts.length ? h("button", { type: "button", class: "hq-btn primary", onclick: () => client.send("bizcompany_build", { depts: [d.id], only_ready: false }) },
          icon("user-plus"), "Najmout celé oddělení") : "",
        mine.length ? h("button", { type: "button", class: "hq-btn", onclick: () => client.send("bizagents_bulk", { dept: d.id, enabled: !mine.every((a) => a.enabled) }) },
          icon("power"), mine.every((a) => a.enabled) ? "Vypnout oddělení" : "Zapnout oddělení") : ""));
    return h("div", { class: "hq-deptview", style: { "--c": d.color } }, head, wrap, sw, card());
  };
  const BL: Record<string, string[]> = {};
  const deptLimit = (dept: string) => {
    const cur = company?.numbers.dept_budget?.[dept] || 0;
    const sel = h("select", { class: "hq-sel", "aria-label": "Denní limit oddělení", title: "Kolikrát denně smí agenti tohoto oddělení pracovat" },
      ...[[0, "bez limitu oddělení"], [5, "max 5 běhů/den"], [10, "max 10 běhů/den"], [20, "max 20 běhů/den"], [50, "max 50 běhů/den"]]
        .map(([v, t]) => h("option", { value: String(v), selected: v === cur }, String(t)))) as HTMLSelectElement;
    sel.onchange = () => client.send("bizdept_budget_set", { dept, runs: Number(sel.value) });
    return sel;
  };
  const trunc = (t: string, n: number) => (t.length > n ? `${t.slice(0, n - 1)}…` : t);

  // ---------------------------------------------------------------- an agent's card
  let shownCard: number | string | null = null;        // the card slides in once – not again at every live update
  const card = () => {
    if (cardId === null) { shownCard = null; return ""; }
    const fresh = cardId !== shownCard;
    shownCard = cardId;
    const a = typeof cardId === "number" ? agents.find((x) => x.id === cardId) : undefined;
    const l = typeof cardId === "string" ? company?.library.find((x) => x.key === cardId) : a?.bkey ? company?.library.find((x) => x.key === a.bkey) : undefined;
    if (!a && !l) return "";
    const d = deptOf(a ? a.dept : l!.dept);
    const tools = a ? a.tools : BL[l!.key] || [];
    const svc = [...new Set(tools.map((t) => ownerOf(t)).filter(Boolean) as Conn[])];
    const st = a ? state(a) : "ghost";
    const propose = writes({ tools });
    const mine = a ? props.filter((p) => p.agent_id === a.id) : [];
    const rung = (k: string, t: string, txt: string) => h("div", { class: `hq-rung ${k}` }, h("b", {}, t), h("span", {}, txt));
    const closeCard = () => { cardId = null; paint(); };
    return h("aside", { class: `hq-card glass ${fresh ? "fresh" : ""}`, style: { "--c": d.color }, role: "dialog", "aria-label": a?.name || l!.name },
      h("div", { class: "hq-card-top" },
        h("button", { type: "button", class: "hq-back", onclick: closeCard }, icon("arrow-left"), `ZPĚT · ${d.name.toUpperCase()}`),
        h("button", { type: "button", class: "hq-x sm", "aria-label": "Zavřít", onclick: closeCard }, icon("x"))),
      h("div", { class: "hq-card-hero" },
        h("span", { class: `hq-card-ico ${st}` }, icon(a?.icon || l?.icon || "robot", "ph-fill")),
        h("div", {}, h("h3", {}, a?.skill || l?.skill || a?.name || ""),
          h("div", { class: "hq-card-sub" }, `${d.name.toUpperCase()} · ${a?.name || l!.name}`))),
      h("div", { class: "hq-pills" }, h("span", { class: `hq-pill ${st}` }, a ? STATE_TXT[st] : "V KNIHOVNĚ"),
        h("span", { class: "hq-pill" }, icon("clock"), a?.when || l!.when), live.get(a?.id || -1) ? h("span", { class: "hq-pill run" }, nice(live.get(a!.id)!)) : ""),
      a ? h("div", { class: "hq-card-stats" },
        h("div", {}, h("b", {}, String(a.runs || 0)), h("small", {}, "běhů")),
        h("div", {}, h("b", {}, a.runs ? `${Math.round(((a.runs - (a.fails || 0)) / a.runs) * 100)} %` : "–"), h("small", {}, "úspěšnost")),
        h("div", {}, h("b", {}, mine.length ? String(mine.length) : "0"), h("small", {}, "ke schválení"))) : "",
      sec("wrench", "NÁSTROJE", h("div", { class: "hq-chips" }, ...tools.slice(0, 18).map((t) => h("span", { class: "hq-chip" }, nice(t))))),
      svc.length ? sec("plugs-connected", "NAPOJENO NA", h("div", { class: "hq-chips" }, ...svc.map((c) =>
        h("span", { class: `hq-chip svc ${c.connected ? "on" : "off"}`, title: c.connected ? "propojeno" : "nepropojeno – Propojení" }, h("i"), c.name.split(" (")[0])))) : "",
      sec("currency-circle-dollar", "CO NAHRAZUJE", h("div", { class: "hq-replace" }, a?.replaces || l?.replaces || "Ruční práci, kterou teď děláš sám.")),
      sec("stairs", "ŽEBŘÍČEK",
        h("div", { class: `hq-ladder ${propose ? "p" : "r"}` },
          rung("hand", "RUČNĚ", a?.replaces || l?.replaces || "Děláš to sám."),
          rung("assist", "S AGENTEM", "Agent připraví e-maily, zápisy a změny; ty jedním klikem schválíš."),
          rung("auto", "AGENT SÁM", "Čte, hlídá a hlásí sám. Odeslat, zapsat nebo zaplatit nikdy bez tebe."))),
      sec("user", "TY", h("p", { class: "hq-p" }, propose ? "Schvaluješ jeho návrhy (Ke schválení) a doplňuješ mozek firmy." : "Čteš jeho hlášení a doplňuješ mozek firmy.")),
      a ? sec("clock-counter-clockwise", "POSLEDNÍ PRÁCE", h("p", { class: "hq-p" }, `${ago(a.last_run)} · ${a.runs || 0}× pracoval${a.fails ? ` · ${a.fails}× selhal` : ""}`),
        a.last_result ? h("pre", { class: `hq-res ${a.last_ok ? "" : "bad"}` }, a.last_result) : "") : "",
      mine.length ? sec("seal-check", `ČEKÁ NA SCHVÁLENÍ (${mine.length})`, ...mine.map(propCard)) : "",
      a ? sec("target", "ÚKOL", h("p", { class: "hq-p" }, a.task)) : "",
      a ? sec("lightning", "SPOUŠTĚT HNED PŘI", h("div", { class: "hq-chips" }, ...Object.entries(company?.events || {}).map(([k, ev]) => {
        const on = (a.triggers || []).includes(k);
        return h("button", { type: "button", class: `hq-chip toggle ${on ? "on" : ""}`, "aria-pressed": on ? "true" : "false",
          onclick: () => client.send("bizagent_save", { agent: { ...a, triggers: on ? a.triggers.filter((x) => x !== k) : [...(a.triggers || []), k] } }) },
          icon(ev.icon, on ? "ph-fill" : ""), ev.label);
      }))) : "",
      a ? sec("arrow-bend-down-right", "PO DOKONČENÍ PŘEDAT", nextPicker(a)) : "",
      a ? sec("cpu", "MODEL AI", h("div", { class: "hq-chips" }, ...[["smart", "Chytrý"], ["fast", "Rychlý a levný"]].map(([k, t]) =>
        h("button", { type: "button", class: `hq-chip toggle ${(a.tier || "smart") === k ? "on" : ""}`,
          onclick: () => client.send("bizagent_save", { agent: { ...a, tier: k } }) }, t)))) : "",
      h("div", { class: "hq-card-acts" }, ...(a ? [
        h("button", { type: "button", class: "hq-btn primary", disabled: running.includes(a.id), onclick: () => { client.send("bizagent_run", { id: a.id }); toast(`${a.name} pracuje…`, "info"); } },
          icon("play", "ph-fill"), "Spustit teď"),
        h("button", { type: "button", class: "hq-btn", onclick: () => client.send("bizagent_save", { agent: { ...a, enabled: !a.enabled } }) },
          icon("power"), a.enabled ? "Vypnout" : "Zapnout"),
        h("button", { type: "button", class: "hq-btn danger", onclick: () => { if (confirm(`Propustit agenta „${a.name}“?`)) { client.send("bizagent_delete", { id: a.id }); cardId = null; } } },
          icon("trash"))] : [
        h("button", { type: "button", class: "hq-btn primary", onclick: () => client.send("bizagent_hire", { key: l!.key }) }, icon("user-plus"), "Najmout agenta"),
        l!.needs.length && !l!.usable ? h("small", { class: "hq-need" }, `Potřebuje propojit: ${l!.needs.map((c) => conns.find((x) => x.id === c)?.name.split(" (")[0] || c).join(", ")}`) : ""])));
  };
  const nextPicker = (a: Agent) => {
    const refs = a.next || [];
    const linked = refs.map((r) => agents.find((x) => String(x.id) === r || x.bkey === r)).filter(Boolean) as Agent[];
    const sel = h("select", { class: "hq-sel", "aria-label": "Přidat agenta, kterému předá práci" },
      h("option", { value: "" }, "+ přidat agenta…"),
      ...agents.filter((x) => x.id !== a.id && !linked.includes(x)).map((x) => h("option", { value: x.bkey || String(x.id) }, `${x.name} (${deptOf(x.dept).name})`))) as HTMLSelectElement;
    sel.onchange = () => { if (sel.value) client.send("bizagent_save", { agent: { ...a, next: [...refs, sel.value] } }); };
    return h("div", { class: "hq-next" },
      ...linked.map((x) => h("span", { class: "hq-chip svc on" }, icon("arrow-right"), x.name,
        h("button", { type: "button", class: "hq-x-mini", "aria-label": `Nepředávat ${x.name}`,
          onclick: () => client.send("bizagent_save", { agent: { ...a, next: refs.filter((r) => r !== (x.bkey || String(x.id)) && r !== String(x.id)) } }) }, icon("x")))),
      linked.length ? "" : h("small", { class: "hq-muted" }, "Nikomu – výsledek zůstane jen v hlášení."),
      sel);
  };
  const sec = (ic: string, t: string, ...kids: (Node | string)[]) => h("section", { class: "hq-sec" }, h("div", { class: "hq-sec-h" }, icon(ic), t), ...kids);
  const propCard = (p: Proposal) => h("div", { class: "hq-prop glass" },
    h("div", { class: "hq-prop-h" }, h("b", {}, p.agent), h("span", {}, p.description)),
    p.details?.length ? h("pre", {}, p.details.slice(0, 30).join("\n")) : "",
    h("div", { class: "hq-prop-a" },
      h("button", { type: "button", class: "hq-btn primary", onclick: () => client.send("bizproposal_decide", { id: p.id, approve: true }) }, icon("check", "ph-bold"), "Schválit a provést"),
      h("button", { type: "button", class: "hq-btn", onclick: () => client.send("bizproposal_decide", { id: p.id, approve: false }) }, icon("x"), "Zamítnout")));

  // ---------------------------------------------------------------- all agents
  const agentsView = () => {
    const q = filter.q.toLowerCase();
    const list = agents.filter((a) => (!filter.dept || (a.dept || "ostatni") === filter.dept) && (!filter.status || state(a) === filter.status)
      && (!q || `${a.name} ${a.skill} ${a.task}`.toLowerCase().includes(q)));
    const search = h("input", { class: "hq-in", type: "search", placeholder: "hledat agenta…", value: filter.q, "aria-label": "Hledat agenta",
      oninput: () => { filter.q = search.value; repaintList(); } }) as HTMLInputElement;
    const dsel = h("select", { class: "hq-sel", "aria-label": "Oddělení", onchange: (e: Event) => { filter.dept = (e.target as HTMLSelectElement).value; paint(); } },
      h("option", { value: "" }, "Všechna oddělení"), ...depts().map((d) => h("option", { value: d.id, selected: filter.dept === d.id }, d.name)));
    const ssel = h("select", { class: "hq-sel", "aria-label": "Stav", onchange: (e: Event) => { filter.status = (e.target as HTMLSelectElement).value; paint(); } },
      h("option", { value: "" }, "Každý stav"), ...Object.entries(STATE_TXT).map(([k, v]) => h("option", { value: k, selected: filter.status === k }, v.toLowerCase())));
    const rows = h("div", { class: "hq-table glass" });
    const repaintList = () => {
      const qq = filter.q.toLowerCase();
      const l2 = list.filter((a) => !qq || `${a.name} ${a.skill} ${a.task}`.toLowerCase().includes(qq));
      rows.replaceChildren(h("div", { class: "hq-tr th" }, h("span", {}, "AGENT"), h("span", {}, "ODDĚLENÍ"), h("span", {}, "KDY"), h("span", {}, "NAPOSLEDY"),
        h("span", {}, "STAV"), h("span", {}, "")),
      ...l2.map((a) => {
        const d = deptOf(a.dept);
        return h("div", { class: "hq-tr", style: { "--c": d.color } },
          h("button", { type: "button", class: "hq-tname", onclick: () => { deptId = d.id; cardId = a.id; go("dept"); } }, icon(a.icon || "robot"),
            h("span", {}, h("b", {}, a.name), h("small", {}, a.skill || ""))),
          h("span", { class: "hq-tdept" }, h("i"), d.name), h("span", {}, a.when), h("span", {}, ago(a.last_run)),
          h("span", { class: `hq-pill ${state(a)}` }, STATE_TXT[state(a)]),
          h("span", { class: "hq-tacts" },
            h("button", { type: "button", class: "hq-icon", title: "Spustit teď", "aria-label": "Spustit teď", disabled: running.includes(a.id),
              onclick: () => client.send("bizagent_run", { id: a.id }) }, icon("play", "ph-fill")),
            h("button", { type: "button", class: "hq-icon", title: a.enabled ? "Vypnout" : "Zapnout", "aria-label": a.enabled ? "Vypnout" : "Zapnout",
              onclick: () => client.send("bizagent_save", { agent: { ...a, enabled: !a.enabled } }) }, icon("power"))));
      }), l2.length ? "" : h("p", { class: "hq-empty" }, agents.length ? "Nic neodpovídá filtru." : "Zatím žádní agenti – otevři Postavit firmu."));
    };
    repaintList();
    return h("div", { class: "hq-pane" },
      h("div", { class: "hq-tools" }, search, dsel, ssel,
        h("button", { type: "button", class: "hq-btn", onclick: () => client.send("bizagents_bulk", { dept: filter.dept || "*", enabled: true }) }, icon("power"), "Zapnout vše"),
        h("button", { type: "button", class: "hq-btn", onclick: () => client.send("bizagents_bulk", { dept: filter.dept || "*", enabled: false }) }, icon("power"), "Vypnout vše"),
        h("span", { class: "hq-count" }, `${list.length} z ${agents.length}`)),
      rows);
  };

  // ---------------------------------------------------------------- approvals, results, brain, build
  const approvalsView = () => h("div", { class: "hq-pane" },
    h("p", { class: "hq-sub" }, "Tohle agenti připravili. Nic z toho se nestalo – proběhne přesně to, co tu vidíš, až po tvém kliknutí."),
    props.length ? h("div", { class: "hq-props" }, ...props.map(propCard)) : h("p", { class: "hq-empty" }, "Nic nečeká. Agenti pracují a hlásí se, až budou něco potřebovat."));

  const resultsView = () => {
    const rs = company?.runs || [];
    return h("div", { class: "hq-pane" },
      h("div", { class: "hq-kpis" },
        kpi(String(company?.numbers.runs_today ?? 0), "běhů dnes"), kpi(String(company?.numbers.ok_today ?? 0), "úspěšných dnes"),
        kpi(String(company?.numbers.proposals_today ?? 0), "návrhů dnes"), kpi(String(company?.numbers.approved_today ?? 0), "schváleno dnes"),
        kpi(String(company?.numbers.runs_week ?? 0), "běhů za 7 dní"),
        kpi(company?.numbers.runs_week ? `${Math.round(((company.numbers.ok_week || 0) / company.numbers.runs_week) * 100)} %` : "–", "úspěšnost"),
        kpi(String(company?.numbers.ai_week ?? 0), "dotazů na AI (7 dní)"),
        kpi(`${hours(company?.numbers.saved_week_min)} h`, "ušetřeno za týden (odhad)")),
      h("div", { class: "hq-tools" },
        h("button", { type: "button", class: "hq-btn primary", onclick: () => { client.send("bizreport_make"); toast("Kreslím zprávu…", "info"); } },
          icon("file-pdf", "ph-fill"), "Týdenní zpráva (PDF)"),
        h("button", { type: "button", class: "hq-btn", onclick: () => client.send("bizaudit_export") }, icon("download-simple"), "Exportovat záznam (CSV)"),
        h("button", { type: "button", class: `hq-btn ${logView ? "on" : ""}`, onclick: () => { logView = !logView; if (logView) client.send("bizaudit_get", { limit: 400 }); paint(); } },
          icon("list-magnifying-glass"), logView ? "Zpět na běhy" : "Záznam všech akcí")),
      logView ? auditList() : "",
      !logView && rs.length ? h("div", { class: "hq-feed" }, ...rs.map((r) => {
        const d = deptOf(r.dept);
        return h("details", { class: `hq-run glass ${r.ok ? "" : "bad"}`, style: { "--c": d.color } },
          h("summary", {}, h("i", { class: "hq-dot" }), h("time", {}, clock(r.started)), h("b", {}, r.agent),
            h("span", {}, (r.summary || "").split("\n")[0].slice(0, 140)),
            h("em", {}, `${Math.round(r.seconds)} s${r.proposals ? ` · ${r.proposals} návrhů` : ""}`)),
          h("pre", {}, r.summary || ""));
      })) : logView ? "" : h("p", { class: "hq-empty" }, "Zatím žádná práce – spusť agenta nebo počkej na jeho čas."));
  };
  let logView = false;
  let audit: { at: number; agent: string; kind: string; tool: string; summary: string; ok: number }[] = [];
  const KIND: Record<string, [string, string]> = { tool: ["magnifying-glass", "zjistil"], proposal: ["seal-question", "navrhl"], approved: ["seal-check", "schváleno"],
    rejected: ["x-circle", "zamítnuto"], handoff: ["arrow-bend-down-right", "předal"], event: ["lightning", "událost"] };
  const auditList = () => h("div", { class: "hq-feed" }, ...(audit.length ? audit.map((x) => h("div", { class: `hq-audit ${x.ok ? "" : "bad"} k-${x.kind}` },
    icon((KIND[x.kind] || ["dot", ""])[0], "ph-fill"), h("time", {}, clock(x.at)), h("b", {}, x.agent || "–"),
    h("em", {}, (KIND[x.kind] || ["", x.kind])[1]), h("span", {}, `${x.tool ? nice(x.tool) + " · " : ""}${x.summary}`)))
    : [h("p", { class: "hq-empty" }, "Záznam je zatím prázdný.")]));
  const kpi = (v: string, l: string) => h("div", { class: "hq-kpi glass" }, h("b", {}, v), h("small", {}, l));

  const brainView = () => {
    const p = company?.profile || {};
    const fields = company?.profile_fields || {};
    const inputs: Record<string, HTMLTextAreaElement> = {};
    const note = h("textarea", { class: "hq-in", rows: 3, placeholder: "Ceník, pravidla, důležití zákazníci, co jsme rozhodli… cokoli, co mají agenti vědět",
      "aria-label": "Nová poznámka" }) as HTMLTextAreaElement;
    return h("div", { class: "hq-pane hq-brain" },
      h("section", { class: "hq-panel glass" }, h("div", { class: "hq-ph" }, icon("identification-card"), "PROFIL FIRMY"),
        h("p", { class: "hq-sub" }, "Tohle čte každý agent při každé práci."),
        ...Object.entries(fields).map(([k, label]) => {
          const ta = h("textarea", { class: "hq-in", rows: k === "rules" || k === "what" ? 3 : 2, "aria-label": label }, p[k] || "") as HTMLTextAreaElement;
          inputs[k] = ta;
          return h("label", { class: "hq-field" }, h("span", {}, label), ta);
        }),
        h("button", { type: "button", class: "hq-btn primary", onclick: () => client.send("bizprofile_save", { profile: Object.fromEntries(Object.entries(inputs).map(([k, v]) => [k, v.value])) }) },
          icon("floppy-disk"), "Uložit profil")),
      h("section", { class: "hq-panel glass" }, h("div", { class: "hq-ph" }, icon("brain"), `POZNÁMKY (${company?.numbers.notes ?? 0})`),
        h("p", { class: "hq-sub" }, "Sem píšeš ty i agenti (čísla dne, rozhodnutí, poučení). Soubory .txt/.md/.csv můžeš přetáhnout kamkoli do velínu."),
        note, h("button", { type: "button", class: "hq-btn primary", onclick: () => { if (note.value.trim()) { client.send("bizbrain_add", { text: note.value.trim() }); note.value = ""; } } },
          icon("plus"), "Přidat do mozku"),
        h("div", { class: "hq-notes" }, ...(company?.notes || []).map((n) => h("div", { class: "hq-note" },
          h("div", {}, h("small", {}, `${clock(n.created)} · ${n.source || ""}`), h("p", {}, n.text.slice(0, 600))),
          h("button", { type: "button", class: "hq-icon", "aria-label": "Smazat poznámku", title: "Smazat", onclick: () => client.send("bizbrain_delete", { id: n.id }) }, icon("trash")))))));
  };

  const buildView = () => {
    const lib = company?.library || [];
    const chosen = new Set(depts().filter((d) => d.id !== "ostatni").map((d) => d.id));
    let onlyReady = true;
    const total = h("b");
    const count = () => {
      const n = lib.filter((l) => chosen.has(l.dept) && !l.hired && (!onlyReady || l.usable)).length;
      total.textContent = String(n);
      return n;
    };
    const tiles = depts().filter((d) => d.id !== "ostatni").map((d) => {
      const mine = libOf(d.id);
      const need = [...new Set(mine.filter((l) => !l.usable && !l.hired).flatMap((l) => l.needs))].map((c) => conns.find((x) => x.id === c)?.name.split(" (")[0] || c);
      const cb = h("input", { type: "checkbox", checked: true }) as HTMLInputElement;
      cb.onchange = () => { cb.checked ? chosen.add(d.id) : chosen.delete(d.id); count(); };
      return h("label", { class: "hq-tile glass", style: { "--c": d.color } }, cb,
        h("span", { class: "hq-tile-ico" }, icon(d.icon, "ph-fill")),
        h("div", {}, h("b", {}, d.name), h("p", {}, d.desc),
          h("small", {}, `${mine.filter((l) => l.hired).length} / ${mine.length} najato · ${mine.filter((l) => !l.hired && l.usable).length} připraveno`),
          need.length ? h("small", { class: "hq-need" }, `Pro zbytek propoj: ${need.slice(0, 5).join(", ")}`) : ""));
    });
    const ready = h("input", { type: "checkbox", checked: true }) as HTMLInputElement;
    ready.onchange = () => { onlyReady = ready.checked; count(); };
    const out = h("div", { class: "hq-pane" },
      h("p", { class: "hq-sub" }, `Knihovna má ${lib.length} hotových agentů v ${depts().filter((d) => d.id !== "ostatni").length} odděleních. Najmi je jedním klikem – `
        + "dostanou nástroje tvých propojených služeb, profil a mozek firmy. Pracují postupně, jeden po druhém, v rámci denního limitu běhů."),
      h("div", { class: "hq-tiles" }, ...tiles),
      h("div", { class: "hq-ph sm chains" }, icon("link", "ph-bold"), "ŘETĚZCE – AGENTI SI PŘEDÁVAJÍ PRÁCI"),
      h("div", { class: "hq-chains" }, ...Object.entries(company?.chains || {}).map(([k, ch]) => {
        const lib = company?.library || [];
        return h("div", { class: "hq-chain glass" },
          h("div", { class: "hq-chain-h" }, h("span", { class: "hq-tile-ico", style: { "--c": "#8b6bff" } }, icon(ch.icon, "ph-fill")),
            h("div", {}, h("b", {}, ch.name), h("p", {}, ch.desc))),
          h("div", { class: "hq-chain-steps" }, ...ch.steps.flatMap((st, i) => {
            const l = lib.find((x) => x.key === st);
            const node = h("span", { class: `hq-step ${l?.hired ? "on" : ""}` }, icon(l?.icon || "robot", "ph-fill"), l?.name || st);
            return i ? [h("i", { class: "ph ph-arrow-right hq-step-arrow" }), node] : [node];
          })),
          h("button", { type: "button", class: "hq-btn primary", onclick: () => client.send("bizchain_build", { key: k }) }, icon("link", "ph-bold"), "Zapojit řetězec"));
      })),
      h("div", { class: "hq-build glass" },
        h("label", { class: "hq-check" }, ready, "Jen agenty, jejichž služby už jsou propojené"),
        h("button", { type: "button", class: "hq-btn primary big", onclick: () => client.send("bizcompany_build", { depts: [...chosen], only_ready: onlyReady }) },
          icon("buildings", "ph-fill"), "Postavit firmu (", total, " agentů)")));
    count();
    return out;
  };

  // ---------------------------------------------------------------- paint
  const TITLES: Record<View, string> = { overview: "PŘEHLED", dept: "ODDĚLENÍ", agents: "AGENTI", approvals: "KE SCHVÁLENÍ", results: "VÝSLEDKY",
    brain: "MOZEK FIRMY", build: "POSTAVIT FIRMU" };
  const paint = () => {
    if (!isOpen) return;
    const name = company?.profile?.name?.trim();
    title.textContent = view === "dept" ? deptOf(deptId).name.toUpperCase() : view === "overview" ? (name ? name.toUpperCase() : "VELÍN FIRMY") : TITLES[view];
    crumbs.textContent = `jarvis / velín / ${TITLES[view].toLowerCase()}`;
    root.dataset.view = view;
    const key = `${view}:${view === "dept" ? deptId : ""}`;
    const enter = key !== lastKey;
    lastKey = key;
    paintNav();
    animate(null);
    const scroll = (body.firstElementChild as HTMLElement | null)?.querySelector?.(".hq-tree-scroll")?.scrollLeft || 0;
    const cardScroll = body.querySelector(".hq-card")?.scrollTop || 0;          // a live update must not jump the card
    const paneScroll = body.querySelector(".hq-pane")?.scrollTop || 0;
    body.replaceChildren(view === "overview" ? overview() : view === "dept" ? deptView() : view === "agents" ? agentsView()
      : view === "approvals" ? approvalsView() : view === "results" ? resultsView() : view === "brain" ? brainView() : buildView());
    if (enter) (body.firstElementChild as HTMLElement | null)?.classList.add("enter");
    const sc = body.querySelector(".hq-tree-scroll") as HTMLElement | null;
    if (sc) sc.scrollLeft = scroll;
    const cd = body.querySelector(".hq-card") as HTMLElement | null;
    if (cd && !cd.classList.contains("fresh")) cd.scrollTop = cardScroll;
    const pn = body.querySelector(".hq-pane") as HTMLElement | null;
    if (pn && view === lastView) pn.scrollTop = paneScroll;
    lastView = view;
  };
  let lastView: View | null = null;
  let lastKey = "";
  const go = (v: View) => { view = v; if (v !== "dept") cardId = null; paint(); };

  // the agents/brain views have inputs: repainting under the user's fingers would lose what they type
  const typing = () => view === "brain" || (view === "agents" && document.activeElement?.closest(".hq-tools"));
  const soft = () => { if (!isOpen) return; if (typing()) paintNav(); else paint(); };

  client.on("bizagents", (m: any) => {
    agents = m.agents || []; props = m.proposals || []; running = m.running || []; queue = m.queue || [];
    if (m.company) {
      company = { ...(company || {}), ...m.company } as Company;        // a live update carries only what changed
      for (const l of company!.library) BL[l.key] = (l as any).tools || BL[l.key] || [];
    }
    if (isOpen && m.message && m.req && /^biz(company|agent_hire|agents_bulk|brain|profile|budget|pause)/.test(m.req)) toast(m.message, m.ok === false ? "error" : "ok", 6000);
    soft();
  });
  client.on("bizaudit", (m: any) => { audit = Array.isArray(m.items) ? m.items : []; if (logView) soft(); });
  client.on("export_done", (m: any) => { if (isOpen && (m.kind === "velin" || m.kind === "report")) toast(`Uloženo: ${m.path}`, "ok", 9000); });
  client.on("connectors", (m: any) => { conns = Array.isArray(m.items) ? m.items : conns; soft(); });
  client.on("agent_activity", (m: any) => {
    const k = String(m.key || "");
    if (!k.startsWith("biz")) return;
    const id = Number(k.slice(3));
    if (m.state === "start") { if (!running.includes(id)) running = [...running, id]; live.delete(id); }
    else if (m.state === "tool") live.set(id, String(m.tool || ""));
    else if (m.state === "done") { running = running.filter((x) => x !== id); live.delete(id); }
    if (isOpen && m.state !== "tool") soft();
    else if (isOpen && cardId === id) soft();
  });

  const onKey = (e: KeyboardEvent) => {
    if (!isOpen || e.key !== "Escape") return;
    if ((e.target as HTMLElement)?.closest?.("textarea, input, select")) { (e.target as HTMLElement).blur(); return; }
    if (cardId !== null) { cardId = null; paint(); } else close();
  };
  document.addEventListener("keydown", onKey);

  const open = () => {
    isOpen = true;
    root.hidden = false;
    document.body.classList.add("hq-open");
    try { if (!document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => { /* a window without full screen */ }); } catch { /* no API */ }
    client.send("bizagents_get"); client.send("connectors_get");
    paint();
    setTimeout(() => (nav.querySelector(".hq-nav-i.on") as HTMLElement | null)?.focus(), 50);
  };
  const close = () => {
    isOpen = false;
    animate(null);
    root.hidden = true;
    document.body.classList.remove("hq-open");
    try { if (document.fullscreenElement) document.exitFullscreen?.().catch(() => { /* already */ }); } catch { /* no API */ }
  };
  return { open, close };
}
