// Wave F1: small dependency-free SVG charts – a time line chart (CPU / RAM / disk / packet loss / latency over time,
// OMEGA 305 / 309 / 719), the route to a host as a chain of hops coloured by latency (706) and the home network as a
// star around the router (194).
import "./viz.css";
import { h } from "./dom";

const NS = "http://www.w3.org/2000/svg";
const s = (tag: string, attrs: Record<string, string | number> = {}, ...kids: (SVGElement | string)[]) => {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  for (const k of kids) el.append(k);
  return el;
};

export type Series = { name: string; color: string; points: { t: number; v: number | null }[]; unit?: string };

const hm = (t: number) => new Date(t * 1000).toLocaleTimeString("cs-CZ", { hour: "2-digit", minute: "2-digit" });

/** Nice upper bound for an axis (1, 2, 5 × 10^n). */
export function niceMax(v: number): number {
  if (!(v > 0)) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 5, 10]) if (v <= m * p) return m * p;
  return 10 * p;
}

/** A line chart over time; gaps (null) break the line. Hover shows the values at that moment. */
export function lineChart(series: Series[], opts: { height?: number; max?: number; label?: string } = {}): HTMLElement {
  const W = 640, H = opts.height || 160, L = 36, R = 8, T = 10, B = 22;
  const all = series.flatMap((x) => x.points);
  const ts = all.map((p) => p.t);
  const box = h("div", { class: "chart", role: "img", "aria-label": opts.label || series.map((x) => x.name).join(", ") });
  if (!ts.length) { box.append(h("p", { class: "muted" }, "Zatím žádná data – měří se průběžně.")); return box; }
  const t0 = Math.min(...ts), t1 = Math.max(...ts, t0 + 1);
  const vmax = opts.max ?? niceMax(Math.max(...all.map((p) => p.v ?? 0), 0.001));
  const x = (t: number) => L + ((t - t0) / (t1 - t0)) * (W - L - R);
  const y = (v: number) => T + (1 - Math.min(v, vmax) / vmax) * (H - T - B);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", class: "chart-svg" });
  for (const f of [0, 0.5, 1]) {
    svg.append(s("line", { x1: L, x2: W - R, y1: y(vmax * f), y2: y(vmax * f), class: "chart-grid" }),
      s("text", { x: L - 4, y: y(vmax * f) + 4, "text-anchor": "end", class: "chart-ax" }, String(+(vmax * f).toFixed(2))));
  }
  for (const f of [0, 0.5, 1]) svg.append(s("text", { x: L + f * (W - L - R), y: H - 6, "text-anchor": f === 0 ? "start" : f === 1 ? "end" : "middle", class: "chart-ax" }, hm(t0 + f * (t1 - t0))));
  for (const se of series) {
    let d = "", pen = false;
    for (const p of se.points) {
      if (p.v == null) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`;
      pen = true;
    }
    if (d) svg.append(s("path", { d, fill: "none", stroke: se.color, "stroke-width": 1.8, "vector-effect": "non-scaling-stroke" }));
  }
  const cursor = s("line", { y1: T, y2: H - B, class: "chart-cursor", visibility: "hidden" });
  svg.append(cursor);
  const tip = h("div", { class: "chart-tip", hidden: true });
  svg.addEventListener("pointermove", (e: PointerEvent) => {
    const r = svg.getBoundingClientRect();
    const t = t0 + ((e.clientX - r.left) / r.width * W - L) / (W - L - R) * (t1 - t0);
    const near = (pts: Series["points"]) => pts.reduce((a, b) => Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a, pts[0]);
    const rows = series.filter((se) => se.points.length).map((se) => { const p = near(se.points); return { se, p }; });
    if (!rows.length) return;
    cursor.setAttribute("x1", String(x(rows[0].p.t))); cursor.setAttribute("x2", String(x(rows[0].p.t)));
    cursor.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.replaceChildren(h("strong", {}, hm(rows[0].p.t)), ...rows.map(({ se, p }) => h("span", { style: { color: se.color } }, `${se.name}: ${p.v == null ? "—" : p.v}${se.unit ? " " + se.unit : ""}`)));
  });
  svg.addEventListener("pointerleave", () => { cursor.setAttribute("visibility", "hidden"); tip.hidden = true; });
  const legend = h("div", { class: "chart-legend" }, ...series.map((se) => h("span", {}, h("i", { style: { background: se.color } }), se.name)));
  box.append(svg as unknown as HTMLElement, legend, tip);
  return box;
}

/** Latency → colour: green fast, amber slow, red very slow, grey no answer. */
export const latColor = (ms: number | null | undefined) => ms == null ? "#64748b" : ms < 30 ? "#22c55e" : ms < 80 ? "#84cc16" : ms < 150 ? "#f59e0b" : "#ef4444";

/** OMEGA 706: the route as a chain of hops; the jump in latency between hops is where the delay is added. */
export function routeMap(hops: { hop: number; ip: string; ms: number | null }[]): HTMLElement {
  if (!hops.length) return h("p", { class: "muted" }, "Trasa je prázdná.");
  const W = Math.max(640, hops.length * 70), H = 150, gap = (W - 60) / Math.max(1, hops.length - 1);
  const maxMs = niceMax(Math.max(...hops.map((x) => x.ms ?? 0), 1));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "route-svg", width: W, height: H });
  let prev: { x: number; y: number } | null = null, prevMs: number | null = null;
  let worst = { i: -1, add: 0 };
  hops.forEach((hp, i) => {
    const cx = 30 + i * gap, cy = 26 + (1 - (hp.ms ?? 0) / maxMs) * 60 + 0;
    if (prev) svg.append(s("line", { x1: prev.x, y1: prev.y, x2: cx, y2: cy, stroke: latColor(hp.ms), "stroke-width": 3, "stroke-dasharray": hp.ms == null ? "4 4" : "" }));
    if (hp.ms != null && prevMs != null && hp.ms - prevMs > worst.add) worst = { i, add: hp.ms - prevMs };
    if (hp.ms != null) prevMs = hp.ms;
    prev = { x: cx, y: cy };
  });
  hops.forEach((hp, i) => {
    const cx = 30 + i * gap, cy = 26 + (1 - (hp.ms ?? 0) / maxMs) * 60;
    const g = s("g", {}, s("title", {}, `${hp.hop}. ${hp.ip}${hp.ms != null ? ` – ${hp.ms} ms` : " – neodpověděl"}`),
      s("circle", { cx, cy, r: i === worst.i ? 9 : 7, fill: latColor(hp.ms), stroke: i === worst.i ? "#fff" : "none", "stroke-width": 2 }),
      s("text", { x: cx, y: 118, "text-anchor": "middle", class: "chart-ax" }, String(hp.hop)),
      s("text", { x: cx, y: 134, "text-anchor": "middle", class: "chart-ax" }, hp.ms != null ? `${Math.round(hp.ms)} ms` : "*"));
    svg.append(g);
  });
  const note = worst.i > 0 && worst.add >= 20
    ? `Nejvíc zdržení přibude u skoku ${hops[worst.i].hop} (${hops[worst.i].ip}): +${Math.round(worst.add)} ms.`
    : "Zdržení přibývá rovnoměrně – žádný skok výrazně nebrzdí.";
  return h("div", { class: "route-map" }, h("div", { class: "route-scroll" }, svg as unknown as HTMLElement), h("p", { class: "muted" }, note));
}

/** OMEGA 194: the home network – the router in the middle, devices around it; new ones highlighted. */
export function netGraph(devices: { ip: string; mac: string; name?: string; host?: string; new?: boolean }[], gateway = ""): HTMLElement {
  const W = 520, H = 360, cx = W / 2, cy = H / 2;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "netgraph-svg", role: "img", "aria-label": `Síť: ${devices.length} zařízení` });
  const others = devices.filter((d) => d.ip !== gateway);
  const n = Math.max(1, others.length);
  others.forEach((d, i) => {
    const ring = n > 14 && i % 2 ? 0.92 : 0.7;
    const a = (2 * Math.PI * i) / n - Math.PI / 2;
    const x = cx + Math.cos(a) * (W / 2 - 60) * ring, y = cy + Math.sin(a) * (H / 2 - 40) * ring;
    const label = (d.name || d.host || d.ip).slice(0, 18);
    svg.append(s("line", { x1: cx, y1: cy, x2: x, y2: y, class: "ng-edge" }),
      s("g", { class: `ng-node${d.new ? " new" : ""}` }, s("title", {}, `${d.name || d.host || "?"} · ${d.ip} · ${d.mac}`),
        s("circle", { cx: x, cy: y, r: 8 }), s("text", { x, y: y + 22, "text-anchor": "middle" }, label)));
  });
  svg.append(s("g", { class: "ng-node router" }, s("circle", { cx, cy, r: 16 }), s("text", { x: cx, y: cy + 32, "text-anchor": "middle" }, gateway ? `router ${gateway}` : "router")));
  return h("div", { class: "netgraph" }, svg as unknown as HTMLElement);
}

/** OMEGA 222: the mission's steps as a dependency graph – columns run together, colour = state of the step. */
export function stepDag(steps: { title: string; status: string }[], graph: { layers: number[][]; edges: { from: number; to: number }[] }): HTMLElement {
  const colW = 200, rowH = 54, W = graph.layers.length * colW + 20;
  const H = Math.max(...graph.layers.map((l) => l.length), 1) * rowH + 20;
  const pos = new Map<number, { x: number; y: number }>();
  graph.layers.forEach((layer, c) => layer.forEach((i, r) => pos.set(i, { x: 10 + c * colW, y: 10 + r * rowH })));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "dag-svg" });
  for (const e of graph.edges) {
    const a = pos.get(e.from), b = pos.get(e.to);
    if (!a || !b) continue;
    const x1 = a.x + 170, y1 = a.y + 20, x2 = b.x, y2 = b.y + 20, mx = (x1 + x2) / 2;
    svg.append(s("path", { d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, class: "dag-edge" }));
  }
  pos.forEach((p, i) => {
    const st = steps[i]?.status || "pending";
    const t = (steps[i]?.title || `krok ${i + 1}`);
    svg.append(s("g", { class: `dag-node s-${st}` }, s("title", {}, t),
      s("rect", { x: p.x, y: p.y, width: 170, height: 40, rx: 10 }),
      s("text", { x: p.x + 10, y: p.y + 25 }, `${i + 1}. ${t.length > 22 ? t.slice(0, 21) + "…" : t}`)));
  });
  return h("div", { class: "dag" }, svg as unknown as HTMLElement);
}
